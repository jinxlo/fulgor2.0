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

# --- UPGRADED PROMPT WITH ENGINE_DETAILS ---
VEHICLE_PARSER_PROMPT = """
You are an expert vehicle data extraction API. Your job is to analyze a user's Spanish text query and extract the vehicle's Make, Model, Year, and Engine Details.

Your response MUST be a single, valid JSON object and nothing else.

The JSON object should have four keys: "make", "model", "year", and "engine_details".
- "make": The vehicle brand (e.g., "CHEVROLET", "FORD"). Standardize it to uppercase.
- "model": The specific model name. Exclude engine details from this field. (e.g., "AVEO", "F-150", "GRAN VITARA XL5").
- "year": The 4-digit year as an integer.
- "engine_details": Any specific engine or technical specifiers like "4CIL", "6 CILINDROS", "V6", "2.0L", "4WD", "DIESEL". If none, this should be `null`.

Rules:
- If a key's value cannot be determined, the value should be `null`.
- Do NOT include any explanations or extra text outside of the JSON object.
- If the user provides a brand that is also a person's name like "Mercedes", correctly identify it as the make "MERCEDES BENZ".
- Separate the core model name from engine/technical specifications.

Examples:
User: "bateria para un ford fiesta del 2011"
Response: {"make": "FORD", "model": "FIESTA", "year": 2011, "engine_details": null}

User: "chevrolet gran vitara xl5 6cil 2000"
Response: {"make": "CHEVROLET", "model": "GRAN VITARA XL5", "year": 2000, "engine_details": "6cil"}

User: "tienes para mi camioneta toyota"
Response: {"make": "TOYOTA", "model": null, "year": null, "engine_details": null}

User: "para un CHERY TIGGO 4/4PRO del 2022"
Response: {"make": "CHERY", "model": "TIGGO 4/4PRO", "year": 2022, "engine_details": null}

User: "busco para una jeep grand cherokee laredo 4x4 2009"
Response: {"make": "JEEP", "model": "GRAND CHEROKEE LAREDO", "year": 2009, "engine_details": "4x4"}
"""

def parse_vehicle_query_to_structured(user_query: str) -> Optional[dict]:
    """
    Uses an LLM to parse a natural language query into a structured
    dictionary of {make, model, year, engine_details}.
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
        
        # Validation for the new, richer structure
        if all(k in parsed_json for k in ["make", "model", "year", "engine_details"]):
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


# --- NEW AI DECISION-MAKER FUNCTION ---
def decide_best_vehicle_match(user_query: str, db_candidates: List[str]) -> Optional[str]:
    # ... (this function remains unchanged) ...
    if not user_query or not db_candidates:
        return None

    # This prompt asks the AI to act as a specialist and just return the best choice.
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

    # Format the candidates for the prompt
    formatted_candidates = "\n".join([f"{i+1}. {c}" for i, c in enumerate(db_candidates)])
    
    combined_prompt = f"User Query: \"{user_query}\"\n\nDatabase Candidates:\n[\n{formatted_candidates}\n]"

    try:
        # We use the simple Chat provider for this specific, stateless task.
        provider = azure_chat_provider.AzureChatProvider(
            api_key=Config.AZURE_OPENAI_API_KEY,
            azure_endpoint=Config.AZURE_OPENAI_ENDPOINT,
            api_version=Config.AZURE_OPENAI_API_VERSION,
            deployment_name=Config.AZURE_OPENAI_CHAT_DEPLOYMENT_NAME  # Ensure this is a powerful model like GPT-4
        )
        # We cannot use JSON mode here, as we need a simple text response.
        response_text = provider.get_simple_response(query=combined_prompt, system_prompt=system_prompt_chooser)

        if response_text and "none" not in response_text.lower():
            # Find the chosen response in the original candidate list to ensure it's a valid choice
            for candidate in db_candidates:
                if candidate in response_text:
                    logger.info(f"AI decision-maker chose '{candidate}' for query '{user_query}'")
                    return candidate
        
        logger.warning(f"AI decision-maker could not find a suitable match for '{user_query}' among candidates.")
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