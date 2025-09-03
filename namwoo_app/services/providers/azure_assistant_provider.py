# namwoo_app/services/providers/azure_assistant_provider.py
# -*- coding: utf-8 -*-
import logging
import json
import time
from typing import List, Dict, Optional, Any

import redis
from openai import AzureOpenAI

# --- CORRECTED IMPORTS ---
from config.config import Config
from services import product_service, support_board_service, lead_api_client, thread_mapping_service
from utils import db_utils
from utils.logging_utils import get_conversation_loggers

logger = logging.getLogger(__name__)

class AzureAssistantProvider:
    """
    Provider for handling conversations using Azure OpenAI's Assistant API.
    """
    def __init__(self, api_key: str, assistant_id: str, azure_endpoint: str, api_version: str):
        if not all([api_key, assistant_id, azure_endpoint, api_version]):
            raise ValueError("All Azure credentials are required for AzureAssistantProvider.")
        
        self.client = AzureOpenAI(
            api_key=api_key,
            api_version=api_version,
            azure_endpoint=azure_endpoint,
            timeout=Config.OPENAI_REQUEST_TIMEOUT
        )
        self.assistant_id = assistant_id
        self.provider_name = "azure_assistant"
        self.polling_interval_seconds = 2
        self.run_timeout_seconds = 120
        self.redis = redis.Redis.from_url(Config.REDIS_URL)
        logger.info(f"AzureAssistantProvider initialized for Assistant ID '{self.assistant_id}' at endpoint '{azure_endpoint}'.")

    def _get_or_create_thread_id(self, sb_conversation_id: str) -> str:
        """Gets or creates a thread_id using the correct Azure client."""
        server_logger, _ = get_conversation_loggers(sb_conversation_id)
        thread_id = thread_mapping_service.get_thread_id(
            sb_conversation_id=sb_conversation_id,
            provider=self.provider_name
        )
        if not thread_id:
            server_logger.info(f"No existing thread for Conv {sb_conversation_id} (Provider: {self.provider_name}). Creating new.")
            thread = self.client.beta.threads.create()
            thread_id = thread.id
            thread_mapping_service.store_thread_id(
                sb_conversation_id=sb_conversation_id,
                thread_id=thread_id,
                provider=self.provider_name
            )
        return thread_id

    def _prepare_message_content(self, conversation_data: Dict[str, Any]) -> Optional[str]:
        """Bundles the most recent contiguous user messages into a single text block."""
        if not conversation_data or not conversation_data.get("messages"):
            return None
        user_messages_block = []
        customer_user_id = str(conversation_data.get("details", {}).get("user_id"))
        for message in reversed(conversation_data["messages"]):
            if str(message.get("user_id")) == customer_user_id:
                user_messages_block.insert(0, message.get("message", "").strip())
            else:
                break
        return " ".join(filter(None, user_messages_block)) or None

    def process_message(
        self,
        sb_conversation_id: str,
        new_user_message: Optional[str],
        conversation_data: Dict[str, Any]
    ) -> Optional[str]:
        server_logger, _ = get_conversation_loggers(sb_conversation_id)
        lock_key = f"lock:conv:{sb_conversation_id}"
        with self.redis.lock(lock_key, timeout=self.run_timeout_seconds + 10, blocking_timeout=60):
            try:
                thread_id = self._get_or_create_thread_id(sb_conversation_id)
                
                bundled_message = self._prepare_message_content(conversation_data)
                if bundled_message:
                    self.client.beta.threads.messages.create(
                        thread_id=thread_id, role="user", content=bundled_message
                    )
                else:
                    server_logger.warning(f"No new user message content to process for Conv {sb_conversation_id}. Skipping.")
                    return None

                run = self.client.beta.threads.runs.create(
                    thread_id=thread_id,
                    assistant_id=self.assistant_id,
                    instructions=Config.SYSTEM_PROMPT
                )
                server_logger.info(f"Created Azure Run {run.id} for Thread {thread_id}.")

                start_time = time.time()
                while time.time() - start_time < self.run_timeout_seconds:
                    run = self.client.beta.threads.runs.retrieve(thread_id=thread_id, run_id=run.id)

                    if run.status == 'completed':
                        messages = self.client.beta.threads.messages.list(thread_id=thread_id, limit=1)
                        if messages.data and messages.data[0].role == 'assistant' and messages.data[0].content:
                            return messages.data[0].content[0].text.value
                        return None

                    if run.status == 'requires_action':
                        tool_outputs = self._execute_tool_calls(
                            tool_calls=run.required_action.submit_tool_outputs.tool_calls,
                            sb_conversation_id=sb_conversation_id,
                            server_logger=server_logger
                        )
                        self.client.beta.threads.runs.submit_tool_outputs(
                            thread_id=thread_id,
                            run_id=run.id,
                            tool_outputs=tool_outputs
                        )
                    
                    if run.status in ('failed', 'cancelled', 'expired'):
                        server_logger.error(f"Azure Run {run.id} ended with status {run.status}: {run.last_error}")
                        return f"Lo siento, la operación en Azure falló: {run.status}."

                    time.sleep(self.polling_interval_seconds)

                server_logger.error(f"Azure Run {run.id} timed out after {self.run_timeout_seconds}s.")
                return "Lo siento, la operación en Azure tardó demasiado."

            except Exception as e:
                server_logger.exception(f"[AzureAssistant Provider] Error for Conv {sb_conversation_id}: {e}")
                return "Ocurrió un error inesperado con nuestro asistente de Azure."

    def _execute_tool_calls(self, tool_calls: List[Any], sb_conversation_id: str, server_logger: logging.Logger) -> List[Dict[str, str]]:
        """
        Executes tool calls requested by the assistant.
        """
        tool_outputs = []
        for tool_call in tool_calls:
            function_name = tool_call.function.name
            server_logger.info(f"[{self.provider_name} Provider] Tool requested: {function_name} with args: {tool_call.function.arguments}")
            
            try:
                args = json.loads(tool_call.function.arguments)
                function_response = {}

                # --- REFACTORED ARCHITECTURE ---
                if function_name == "search_vehicle_batteries":
                    user_query = args.get("query")
                    if not user_query:
                        server_logger.warning("Tool 'search_vehicle_batteries' called without a 'query' argument.")
                        function_response = {"status": "error", "message": "Missing vehicle query."}
                    else:
                        server_logger.info(f"Passing raw query to product service: '{user_query}'")
                        with db_utils.get_db_session() as session:
                            results = product_service.find_batteries_for_vehicle(
                                db_session=session,
                                user_query=user_query
                            )
                        function_response = {"batteries_found": results}
                # --- END OF REFACTOR ---
                
                elif function_name == "get_cashea_financing_options":
                    with db_utils.get_db_session() as session:
                        function_response = product_service.get_cashea_financing_options(
                            session=session,
                            product_price=args.get("product_price"),
                            user_level=args.get("user_level"),
                            apply_discount=args.get("apply_discount", False)
                        )

                elif function_name == "submit_order_for_processing":
                    lead_intent_res = lead_api_client.call_initiate_lead_intent(
                        conversation_id=args.get("conversation_id"),
                        platform_user_id=args.get("user_id"),
                        products_of_interest=[{
                            "sku": f"{args.get('chosen_battery_brand')}_{args.get('chosen_battery_model')}",
                            "description": f"Batería {args.get('chosen_battery_brand')} {args.get('chosen_battery_model')}",
                            "quantity": 1
                        }],
                        payment_method_preference=args.get("payment_method")
                    )
                    
                    if lead_intent_res.get("success"):
                        lead_id = lead_intent_res.get("data", {}).get("id")
                        details_res = lead_api_client.call_submit_customer_details(
                            lead_id=lead_id,
                            customer_full_name=args.get("customer_name"),
                            customer_email="not_provided@example.com",
                            customer_phone_number=args.get("customer_phone")
                        )
                        function_response = {"status": "success", "lead_id": lead_id, "details_updated": details_res.get("success")}
                    else:
                        function_response = {"status": "error", "message": lead_intent_res.get("error_message")}

                elif function_name == "route_to_sales_department":
                    support_board_service.route_conversation_to_sales(sb_conversation_id)
                    function_response = {"status": "success", "message": "Conversation has been routed to the Sales department."}
                
                elif function_name == "route_to_human_support":
                    support_board_service.route_conversation_to_support(sb_conversation_id)
                    function_response = {"status": "success", "message": "Conversation has been routed to the Support department."}
                
                else:
                    function_response = {"status": "error", "message": f"Herramienta desconocida '{function_name}'."}

                tool_outputs.append({
                    "tool_call_id": tool_call.id,
                    "output": json.dumps(function_response)
                })

            except Exception as e:
                server_logger.exception(f"Error executing tool {function_name}: {e}")
                tool_outputs.append({
                    "tool_call_id": tool_call.id,
                    "output": json.dumps({"status": "error", "message": str(e)})
                })
        return tool_outputs