# namwoo_app/services/ai_service.py
# -*- coding: utf-8 -*-
import logging
import json
import re
from typing import Optional, Dict, Any, List

from openai import AzureOpenAI
from config.config import Config
from models.product import VehicleBatteryFitment
from services import support_board_service
from services.providers import openai_chat_provider
from services.providers import openai_assistant_provider
from services.providers import google_gemini_provider
from services.providers import azure_assistant_provider
from services.providers import azure_chat_provider
from utils import db_utils
from utils.logging_utils import get_conversation_loggers

logger = logging.getLogger(__name__)

# --- Re-use your existing Azure OpenAI client setup ---
client = AzureOpenAI(
    api_key=Config.AZURE_OPENAI_API_KEY,
    azure_endpoint=Config.AZURE_OPENAI_ENDPOINT,
    api_version=Config.AZURE_OPENAI_API_VERSION,
)
AZURE_DEPLOYMENT_PARSER = "gpt-4o-mini" # Or your preferred model for this task
AZURE_DEPLOYMENT_CHOOSER = Config.AZURE_OPENAI_CHAT_DEPLOYMENT_NAME # Should be a powerful model like GPT-4

# The system prompt that instructs the AI how to parse the query
VEHICLE_PARSER_PROMPT = """
You are an expert vehicle data extraction API. Your job is to analyze a user's Spanish text query and extract the vehicle's Make, Model, and Year.

Your response MUST be a single, valid JSON object and nothing else.

The JSON object should have three keys: "make", "model", and "year".
- "make": The vehicle brand (e.g., "CHEVROLET", "FORD"). Standardize it to uppercase.
- "model": The specific model name and any sub-model identifiers (e.g., "AVEO", "F-150", "GRAN VITARA XL5 6CIL").
- "year": The 4-digit year as an integer.

Rules:
- If a key's value cannot be determined, the value should be `null`.
- Do NOT include any explanations or extra text outside of the JSON object.
- If the user provides a brand that is also a person's name like "Mercedes", correctly identify it as the make "MERCEDES BENZ".

Examples:
User: "bateria para un ford fiesta del 2011"
Response: {"make": "FORD", "model": "FIESTA", "year": 2011}

User: "chevrolet gran vitara xl5 6cil 2000"
Response: {"make": "CHEVROLET", "model": "GRAN VITARA XL5 6CIL", "year": 2000}

User: "tienes para mi camioneta toyota"
Response: {"make": "TOYOTA", "model": null, "year": null}

User: "cuanto cuesta para un aveo?"
Response: {"make": null, "model": "AVEO", "year": null}
"""

def parse_vehicle_query_to_structured(user_query: str) -> Optional[dict]:
    """
    Uses an LLM to parse a natural language query into a structured
    dictionary of {make, model, year}.
    """
    if not user_query:
        return None

    logger.info(f"Attempting to parse vehicle query with AI: '{user_query}'")
    try:
        completion = client.chat.completions.create(
            model=AZURE_DEPLOYMENT_PARSER,
            messages=[
                {"role": "system", "content": VEHICLE_PARSER_PROMPT},
                {"role": "user", "content": user_query}
            ],
            temperature=0.0,
            response_format={"type": "json_object"} # Use JSON mode for reliability
        )
        
        response_content = completion.choices[0].message.content
        parsed_json = json.loads(response_content)
        
        # Basic validation of the returned structure
        if "make" in parsed_json and "model" in parsed_json and "year" in parsed_json:
            logger.info(f"AI successfully parsed query into: {parsed_json}")
            return parsed_json
        else:
            logger.error(f"AI returned invalid JSON structure: {response_content}")
            return None

    except Exception as e:
        logger.exception(f"Error calling AI parser for query '{user_query}': {e}")
        return None


def get_ai_provider():
    # ... (this function remains unchanged) ...
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
    elif provider_name == "azure_chat":
        required_vars = [
            Config.AZURE_OPENAI_API_KEY,
            Config.AZURE_OPENAI_ENDPOINT,
            Config.AZURE_OPENAI_API_VERSION
        ]
        if not all(required_vars):
            raise ValueError("AI_PROVIDER is 'azure_chat', but one or more required Azure configs are missing.")
        return azure_chat_provider.AzureChatProvider(
            api_key=Config.AZURE_OPENAI_API_KEY,
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


# --- REFACTORED AI DECISION-MAKER FUNCTION ---
def decide_best_vehicle_match(user_query: str, db_candidates: List[str]) -> Optional[str]:
    """
    Uses a powerful AI model to analyze a list of database candidates and
    determine the best match for the user's original query.
    """
    if not user_query or not db_candidates:
        return None

    system_prompt_chooser = f"""
You are a vehicle data validation expert. Your task is to select the single best match for a user's query from a list of potential database entries.

You will be given:
1.  The user's original, natural language query.
2.  A numbered list of potential vehicle matches found in our database.

Your instructions:
1.  Analyze the user's query for make, model, year, and any other specific details.
2.  Carefully compare the query to each candidate in the list.
3.  Choose the ONE candidate that is the most likely and specific match.
4.  You MUST respond with ONLY the full text of the single best candidate, exactly as it appears in the list.
5.  If no candidate is a good match, respond with the word "None".

Example:
User Query: "bateria para mi ford explorer eddie bauer 2007"
Database Candidates:
[
    "1. FORD EXPLORER (2006-2010)",
    "2. FORD F-150 (2004-2008)",
    "3. FORD ESCAPE (2005-2007)"
]
Your Response:
FORD EXPLORER (2006-2010)
"""

    formatted_candidates = "\n".join([f"{i+1}. {c}" for i, c in enumerate(db_candidates)])
    user_message_content = f"User Query: \"{user_query}\"\n\nDatabase Candidates:\n[\n{formatted_candidates}\n]"

    try:
        completion = client.chat.completions.create(
            model=AZURE_DEPLOYMENT_CHOOSER,
            messages=[
                {"role": "system", "content": system_prompt_chooser},
                {"role": "user", "content": user_message_content}
            ],
            temperature=0.0,
        )
        response_text = completion.choices[0].message.content

        if response_text and "none" not in response_text.lower():
            # Find the chosen response in the original candidate list to ensure it's a valid choice
            for candidate in db_candidates:
                if candidate in response_text:
                    logger.info(f"AI decision-maker chose '{candidate}' for query '{user_query}'")
                    return candidate
        
        logger.warning(
            f"AI decision-maker could not find a suitable match for '{user_query}' among candidates. "
            f"Response: '{response_text}'"
        )
        return None

    except Exception as e:
        logger.exception("Failed during AI decision-making process.")
        return None


def process_new_message(
    # ... (this function remains unchanged) ...
    sb_conversation_id: str,
    new_user_message: Optional[str],
    conversation_source: Optional[str],
    sender_user_id: str,
    customer_user_id: str,
    triggering_message_id: Optional[str],
) -> None:
    # ... (this function remains unchanged) ...
    server_logger, conversation_logger = get_conversation_loggers(sb_conversation_id)

    try:
        provider = get_ai_provider()
    except Exception as e:
        server_logger.exception("Failed to initialize an AI provider. Check configuration.")
        support_board_service.send_reply_to_channel(
            conversation_id=sb_conversation_id,
            message_text=f"Error de configuración del servidor de IA: {e}",
            source=conversation_source,
            target_user_id=customer_user_id,
            conversation_details=None,
            triggering_message_id=triggering_message_id,
        )
        return

    conversation_data = support_board_service.get_sb_conversation_data(sb_conversation_id)

    final_assistant_response = provider.process_message(
        sb_conversation_id=sb_conversation_id,
        new_user_message=new_user_message,
        conversation_data=conversation_data
    )

    if final_assistant_response and str(final_assistant_response).strip():
        conversation_logger.info(str(final_assistant_response), extra={'speaker': 'Assistant'})
        support_board_service.send_reply_to_channel(
            conversation_id=sb_conversation_id,
            message_text=str(final_assistant_response),
            source=conversation_source,
            target_user_id=customer_user_id,
            conversation_details=conversation_data,
            triggering_message_id=triggering_message_id,
        )
    else:
        server_logger.warning(
            f"Provider '{Config.AI_PROVIDER}' returned no response for Conv {sb_conversation_id}. "
            "This is treated as an intentional skip. No message sent to user."
        )