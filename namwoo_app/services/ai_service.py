# namwoo_app/services/ai_service.py
# -*- coding: utf-8 -*-
import logging
from typing import Optional

# --- CORRECTED IMPORTS ---
from config.config import Config
from services import support_board_service
from services.providers import openai_chat_provider
from services.providers import openai_assistant_provider
from services.providers import google_gemini_provider
from services.providers import azure_assistant_provider
# -------------------------

logger = logging.getLogger(__name__)

def get_ai_provider():
    """
    Factory function to read the config and instantiate the correct AI provider class.
    This is the core of the dynamic switching mechanism.
    """
    provider_name = Config.AI_PROVIDER
    logger.info(f"AI Provider selected via config: '{provider_name}'")

    if provider_name == "openai_assistant":
        if not Config.OPENAI_ASSISTANT_ID:
            raise ValueError("AI_PROVIDER is 'openai_assistant', but OPENAI_ASSISTANT_ID is not set.")
        return openai_assistant_provider.OpenAIAssistantProvider(
            api_key=Config.OPENAI_API_KEY,
            assistant_id=Config.OPENAI_ASSISTANT_ID
        )
    elif provider_name == "azure_assistant":
        required_vars = [
            Config.AZURE_OPENAI_API_KEY,
            Config.AZURE_OPENAI_ASSISTANT_ID,
            Config.AZURE_OPENAI_ENDPOINT,
            Config.AZURE_OPENAI_API_VERSION
        ]
        if not all(required_vars):
            raise ValueError("AI_PROVIDER is 'azure_assistant', but one or more required Azure configs are missing.")
        return azure_assistant_provider.AzureAssistantProvider(
            api_key=Config.AZURE_OPENAI_API_KEY,
            assistant_id=Config.AZURE_OPENAI_ASSISTANT_ID,
            azure_endpoint=Config.AZURE_OPENAI_ENDPOINT,
            api_version=Config.AZURE_OPENAI_API_VERSION
        )
    elif provider_name == "google_gemini":
        if not Config.GOOGLE_API_KEY:
            raise ValueError("AI_PROVIDER is 'google_gemini', but GOOGLE_API_KEY is not set.")
        return google_gemini_provider.GoogleGeminiProvider(
            api_key=Config.GOOGLE_API_KEY
        )
    elif provider_name == "openai_chat":
        if not Config.OPENAI_API_KEY:
            raise ValueError("AI_PROVIDER is 'openai_chat', but OPENAI_API_KEY is not set.")
        return openai_chat_provider.OpenAIChatProvider(
            api_key=Config.OPENAI_API_KEY
        )
    else:
        raise ValueError(f"Unsupported AI_PROVIDER configured: '{provider_name}'")


def process_new_message(
    sb_conversation_id: str,
    new_user_message: Optional[str],
    conversation_source: Optional[str],
    sender_user_id: str,
    customer_user_id: str,
    triggering_message_id: Optional[str],
) -> None:
    """
    This is the single, unified entry point from the web routes.
    It determines the correct AI provider and delegates the message processing.
    """
    try:
        provider = get_ai_provider()
    except Exception as e:
        logger.exception("Failed to initialize an AI provider. Check configuration.")
        # --- FIX #1 ---
        support_board_service.send_reply_to_channel(
            conversation_id=sb_conversation_id,
            message_text=f"Error de configuración del servidor de IA: {e}",
            source=conversation_source,
            target_user_id=customer_user_id,
            conversation_details=None, # Pass None for the missing argument
            triggering_message_id=triggering_message_id,
        )
        # --- END OF FIX #1 ---
        return

    # Fetch conversation data once, to be passed to the provider
    conversation_data = support_board_service.get_sb_conversation_data(sb_conversation_id)

    # Delegate the entire processing task to the selected provider's `process_message` method.
    final_assistant_response = provider.process_message(
        sb_conversation_id=sb_conversation_id,
        new_user_message=new_user_message,
        conversation_data=conversation_data
    )

    # Handle the response from the provider
    if final_assistant_response and str(final_assistant_response).strip():
        # --- FIX #2 ---
        support_board_service.send_reply_to_channel(
            conversation_id=sb_conversation_id,
            message_text=str(final_assistant_response),
            source=conversation_source,
            target_user_id=customer_user_id,
            conversation_details=conversation_data, # Pass the real data here
            triggering_message_id=triggering_message_id,
        )
        # --- END OF FIX #2 ---
    else:
        # A None or empty response from a provider is an intentional skip (e.g., duplicate event)
        logger.warning(
            f"Provider '{Config.AI_PROVIDER}' returned no response for Conv {sb_conversation_id}. "
            "This is treated as an intentional skip. No message sent to user."
        )