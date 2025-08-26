# namwoo_app/api/routes.py (NamFulgor Version - Refactored for AI Service)

import logging
import datetime
import hmac
import hashlib
import json
import os
from datetime import timezone

from flask import request, jsonify, current_app, abort
from sqlalchemy import text

# --- CORRECTED IMPORTS ---
from utils import db_utils
from services import ai_service
from services import support_board_service
from config.config import Config
from models.conversation_pause import ConversationPause
from utils.logging_utils import get_conversation_loggers, LOGS_BASE_DIR
from . import api_bp # +++ THIS IS THE FIX +++
# ------------------------------

logger = logging.getLogger(__name__) # This remains for module-level logging outside a conversation context

# --- Optional: Helper for Webhook Secret Validation ---
def _validate_sb_webhook_secret(request):
    secret = current_app.config.get('SUPPORT_BOARD_WEBHOOK_SECRET')
    if not secret:
        return True
    signature_header = request.headers.get('X-Sb-Signature')
    if not signature_header:
        return False
    try:
        method, signature_hash = signature_header.split('=', 1)
        if method != 'sha1':
            return False
        request_data_bytes = request.get_data()
        mac = hmac.new(secret.encode('utf-8'), msg=request_data_bytes, digestmod=hashlib.sha1)
        expected_signature = mac.hexdigest()
        return hmac.compare_digest(expected_signature, signature_hash)
    except Exception as e:
        logger.exception(f"Error during webhook signature validation: {e}")
        return False

# --- Support Board Webhook Receiver ---
@api_bp.route('/sb-webhook', methods=['POST'])
def handle_support_board_webhook():
    try:
        payload = request.get_json(force=True)
        if not payload:
            abort(400, description="Invalid payload: Empty body.")
    except Exception as e:
        logger.error(f"Failed to parse request JSON for SB Webhook: {e}", exc_info=True)
        abort(400, description="Invalid JSON payload received.")

    webhook_function = payload.get('function')
    if webhook_function != 'message-sent':
        return jsonify({"status": "ok", "message": "Webhook type ignored"}), 200

    data = payload.get('data', {})
    sb_conversation_id = data.get('conversation_id')
    sender_user_id_str_from_payload = data.get('user_id')
    customer_user_id_str = data.get('conversation_user_id')
    triggering_message_id = data.get('message_id')
    new_user_message_text = data.get('message')
    conversation_source = data.get('conversation_source')

    if not all([sb_conversation_id, sender_user_id_str_from_payload, customer_user_id_str]):
        missing_keys = [k for k, v in {'conversation_id': sb_conversation_id, 'user_id': sender_user_id_str_from_payload, 'conversation_user_id': customer_user_id_str}.items() if v is None]
        logger.error(f"Missing critical ID data in SB webhook payload. Missing: {missing_keys}.")
        return jsonify({"status": "error", "message": "Webhook payload missing required ID fields"}), 200

    sb_conversation_id_str = str(sb_conversation_id)
    sender_user_id_str = str(sender_user_id_str_from_payload)
    customer_user_id_str = str(customer_user_id_str)
    
    # +++ GET CONVERSATION-SPECIFIC LOGGERS +++
    server_logger, conversation_logger = get_conversation_loggers(sb_conversation_id_str)
    
    # +++ FETCH AND SAVE USER DETAILS (ONCE PER CONVERSATION) +++
    try:
        log_dir = os.path.join(LOGS_BASE_DIR, sb_conversation_id_str)
        details_file_path = os.path.join(log_dir, "user_details.json")
        if not os.path.exists(details_file_path):
            server_logger.info(f"User details file not found for conv {sb_conversation_id_str}. Fetching from API.")
            user_details = support_board_service.get_sb_user_details(customer_user_id_str)
            if user_details:
                with open(details_file_path, 'w', encoding='utf-8') as f:
                    json.dump(user_details, f, indent=4, ensure_ascii=False)
                server_logger.info(f"Successfully saved user details to {details_file_path}.")
            else:
                server_logger.warning(f"Failed to fetch user details for user {customer_user_id_str}.")
    except Exception as e:
        server_logger.exception(f"An error occurred while fetching/saving user details for conv {sb_conversation_id_str}: {e}")
    # +++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

    DM_BOT_ID_STR = str(Config.SUPPORT_BOARD_DM_BOT_USER_ID) if Config.SUPPORT_BOARD_DM_BOT_USER_ID else None
    HUMAN_AGENT_IDS_SET = Config.SUPPORT_BOARD_AGENT_IDS
    pause_minutes = Config.HUMAN_TAKEOVER_PAUSE_MINUTES

    if not DM_BOT_ID_STR:
         server_logger.critical("FATAL: SUPPORT_BOARD_DM_BOT_USER_ID not configured correctly.")
         return jsonify({"status": "error", "message": "Internal configuration error."}), 200
    
    server_logger.info(f"Processing webhook for SB Conv ID: {sb_conversation_id_str} from Sender: {sender_user_id_str}")

    if sender_user_id_str == DM_BOT_ID_STR:
        server_logger.info(f"Ignoring own message echo from DM bot in conversation {sb_conversation_id_str}.")
        return jsonify({"status": "ok", "message": "Bot message echo ignored"}), 200

    if sender_user_id_str in HUMAN_AGENT_IDS_SET:
        server_logger.info(f"Human agent message in conversation {sb_conversation_id_str}. Pausing DM bot.")
        conversation_logger.info(new_user_message_text, extra={'speaker': 'Agent'}) # Log agent's message
        db_utils.pause_conversation_for_duration(sb_conversation_id_str, duration_seconds=pause_minutes * 60)
        return jsonify({"status": "ok", "message": "Human agent message received, bot paused"}), 200

    if sender_user_id_str == customer_user_id_str:
        # +++ LOG CUSTOMER'S MESSAGE +++
        if new_user_message_text:
            conversation_logger.info(new_user_message_text, extra={'speaker': 'Customer'})
        # ++++++++++++++++++++++++++++++

        if db_utils.is_conversation_paused(sb_conversation_id_str):
            server_logger.info(f"Conversation {sb_conversation_id_str} is paused. DM Bot will not reply.")
            return jsonify({"status": "ok", "message": "Conversation paused"}), 200

        provider = current_app.config.get('AI_PROVIDER', 'openai_chat').lower()
        server_logger.info(f"Conversation {sb_conversation_id_str} is active. Triggering AI Provider: {provider}.")

        process_args = {
            "sb_conversation_id": sb_conversation_id_str,
            "new_user_message": new_user_message_text,
            "conversation_source": conversation_source,
            "sender_user_id": sender_user_id_str,
            "customer_user_id": customer_user_id_str,
            "triggering_message_id": str(triggering_message_id) if triggering_message_id is not None else None
        }

        try:
            ai_service.process_new_message(**process_args)
            return jsonify({"status": "ok", "message": f"Customer message processing initiated via {provider}"}), 200
        except Exception as e:
            server_logger.exception(f"Error triggering ai_service processing for SB conv {sb_conversation_id_str}: {e}")
            support_board_service.send_reply_to_channel(
                 conversation_id=sb_conversation_id_str,
                 message_text="Lo siento, ocurrió un error inesperado al intentar procesar tu mensaje.",
                 source=conversation_source, 
                 target_user_id=customer_user_id_str,
                 conversation_details=None,
                 triggering_message_id=process_args.get("triggering_message_id")
            )
            return jsonify({"status": "error", "message": "Error occurred during message processing trigger"}), 200

    server_logger.warning(f"Received message in conv {sb_conversation_id_str} from unhandled sender {sender_user_id_str}. Pausing.")
    db_utils.pause_conversation_for_duration(sb_conversation_id_str, duration_seconds=pause_minutes * 60)
    return jsonify({"status": "ok", "message": "Message from unhandled sender, bot paused"}), 200


# --- Health Check and Test Endpoints ---
@api_bp.route('/health', methods=['GET'])
def health_check():
    db_ok = False
    try:
        with db_utils.get_db_session() as session:
            if session:
                session.execute(text("SELECT 1"))
                db_ok = True
            else:
                logger.error("Database session not available for health check.")
    except Exception as e:
        logger.error(f"Database health check failed: {e}", exc_info=True)
    return jsonify({"status": "ok", "database_connected": db_ok}), 200

@api_bp.route('/supportboard/test', methods=['GET'])
def handle_support_board_test():
    response_data = {
        "status": "success",
        "message": f"Namwoo (NamFulgor) endpoint /api/supportboard/test reached successfully!",
        "timestamp": datetime.datetime.now(timezone.utc).isoformat()
    }
    return jsonify([response_data]), 200