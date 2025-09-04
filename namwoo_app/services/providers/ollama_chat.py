# services/providers/ollama_chat.py
# -*- coding: utf-8 -*-
import logging
import json
import time
from typing import List, Dict, Optional, Any

import redis
from openai import OpenAI  # OpenAI-compatible; we will point base_url to Ollama

from config.config import Config
from services import product_service, support_board_service, lead_api_client, thread_mapping_service
from utils import db_utils
from utils.logging_utils import get_conversation_loggers

logger = logging.getLogger(__name__)

class OllamaChatProvider:
    """
    Provider for handling conversations using Ollama's OpenAI-compatible Chat Completions API.
    Supports function/tool calling by performing a two-step exchange when tools are requested.
    """
    def __init__(self, base_url: str, api_key: str):
        if not base_url:
            raise ValueError("Ollama base_url is required (e.g., http://<EC2_IP>:11434/v1/).")

        # Ollama ignores the API key but the OpenAI client requires a non-empty string.
        self.client = OpenAI(
            base_url=base_url.rstrip("/") + "/",
            api_key=api_key or "ollama",
            timeout=Config.OPENAI_REQUEST_TIMEOUT
        )
        self.model = getattr(Config, "OLLAMA_MODEL", "llama3.1:8b-instruct-q4_K_M")
        self.provider_name = "ollama_chat"
        self.redis = redis.Redis.from_url(Config.REDIS_URL)

        # SLOs / limits similar to your Azure provider
        self.polling_interval_seconds = 0.2
        self.run_timeout_seconds = 120

        logger.info(f"OllamaChatProvider initialized at {base_url} with model '{self.model}'.")

    # -------- Message prep (kept close to your Azure version) --------
    def _prepare_message_content(self, conversation_data: Dict[str, Any]) -> Optional[str]:
        """
        Bundles the most recent contiguous user messages into a single text block.
        """
        if not conversation_data or not conversation_data.get("messages"):
            return None
        user_messages_block = []
        customer_user_id = str(conversation_data.get("details", {}).get("user_id"))
        for message in reversed(conversation_data["messages"]):
            if str(message.get("user_id")) == customer_user_id:
                user_messages_block.insert(0, (message.get("message") or "").strip())
            else:
                break
        return " ".join(filter(None, user_messages_block)) or None

    # -------- Tool schema (MODIFIED SECTION) --------
    def _get_tools_schema(self) -> List[Dict[str, Any]]:
        """
        Returns the JSON schema for all supported tools.
        Descriptions are enhanced to act as "guardrails" for the LLM, aligning with the system prompt.
        """
        return [
            {
                "type": "function",
                "function": {
                    "name": "search_vehicle_batteries",
                    "description": "Busca baterías compatibles. Úsala SOLAMENTE cuando el usuario mencione un vehículo (marca, modelo, año). NO la uses para saludos o preguntas generales.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string", "description": "La descripción original y completa del vehículo que dio el usuario."}
                        },
                        "required": ["query"],
                        "additionalProperties": False
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "get_cashea_financing_options",
                    "description": "Calcula las opciones de financiamiento con Cashea para un producto. Se usa solo cuando el cliente pregunta específicamente por Cashea.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "product_price": {"type": "number", "description": "El precio BASE del producto (`price_regular`), NUNCA el precio con descuento."},
                            "user_level": {"type": "string", "description": "El nivel del usuario en Cashea (ej: 'Nivel 1', 'Nivel 3')."},
                            "apply_discount": {"type": "boolean", "description": "Debe ser `True` si el cliente paga la inicial en divisas, `False` si paga en bolívares."}
                        },
                        "required": ["product_price", "user_level", "apply_discount"],
                        "additionalProperties": False
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "submit_order_for_processing",
                    "description": "Registra el pedido del cliente en el sistema. Úsala como el ÚLTIMO paso del flujo de compra, DESPUÉS de haber recolectado todos los datos del cliente.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "conversation_id": {"type": "string"},
                            "user_id": {"type": "string"},
                            "chosen_battery_brand": {"type": "string"},
                            "chosen_battery_model": {"type": "string"},
                            "payment_method": {"type": "string"},
                            "customer_name": {"type": "string"},
                            "customer_phone": {"type": "string"}
                        },
                        "required": ["conversation_id", "user_id", "chosen_battery_brand",
                                     "chosen_battery_model", "payment_method", "customer_name", "customer_phone"],
                        "additionalProperties": False
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "route_to_sales_department",
                    "description": "Transfiere la conversación a un agente de ventas humano. Úsala SOLAMENTE al final de un flujo de compra exitoso, junto con `submit_order_for_processing`.",
                    "parameters": {"type": "object", "properties": {}, "additionalProperties": False}
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "route_to_human_support",
                    "description": "Transfiere la conversación a soporte general. Úsala cuando el sistema no encuentra un vehículo, el cliente está frustrado, o pide explícitamente hablar con una persona.",
                    "parameters": {"type": "object", "properties": {}, "additionalProperties": False}
                }
            }
        ]

    # -------- Core entry point (Unchanged) --------
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
                bundled_message = self._prepare_message_content(conversation_data)
                if not bundled_message:
                    server_logger.warning(f"No new user message content for Conv {sb_conversation_id}.")
                    return None

                messages = [
                    {"role": "system", "content": Config.SYSTEM_PROMPT},
                    {"role": "user", "content": bundled_message},
                ]

                server_logger.info(f"[{self.provider_name}] Asking LLM (Conv {sb_conversation_id})")
                first = self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    tools=self._get_tools_schema(),
                    tool_choice="auto",
                    temperature=getattr(Config, "OPENAI_TEMPERATURE", 0.3),
                    max_tokens=getattr(Config, "OPENAI_MAX_TOKENS", 1024) # Increased for potentially longer responses
                )

                choice = first.choices[0].message

                if not getattr(choice, "tool_calls", None):
                    content = (choice.content or "").strip()
                    return content or None

                tool_calls = choice.tool_calls
                server_logger.info(f"[{self.provider_name}] Tool calls requested: {len(tool_calls)}")

                tool_outputs = self._execute_tool_calls(
                    tool_calls=tool_calls,
                    sb_conversation_id=sb_conversation_id,
                    server_logger=server_logger
                )

                second_messages = list(messages)
                second_messages.append({
                    "role": "assistant",
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments
                            }
                        } for tc in tool_calls
                    ]
                })
                
                for out in tool_outputs:
                    second_messages.append({
                        "role": "tool",
                        "tool_call_id": out["tool_call_id"],
                        "name": self._tool_name_from_outputs(tool_calls, out["tool_call_id"]),
                        "content": out["output"]
                    })

                server_logger.info(f"[{self.provider_name}] Sending tool results back to LLM (Conv {sb_conversation_id})")
                second = self.client.chat.completions.create(
                    model=self.model,
                    messages=second_messages,
                    temperature=getattr(Config, "OPENAI_TEMPERATURE", 0.3),
                    max_tokens=getattr(Config, "OPENAI_MAX_TOKENS", 1024)
                )
                final_choice = second.choices[0].message
                return (final_choice.content or "").strip() or None

            except Exception as e:
                server_logger.exception(f"[OllamaChat Provider] Error for Conv {sb_conversation_id}: {e}")
                return "Ocurrió un error inesperado con nuestro asistente."

    @staticmethod
    def _tool_name_from_outputs(tool_calls: List[Any], tool_call_id: str) -> str:
        for tc in tool_calls:
            if getattr(tc, "id", None) == tool_call_id:
                return tc.function.name
        return "unknown_tool"

    # -------- Tool runner (Unchanged) --------
    def _execute_tool_calls(self, tool_calls: List[Any], sb_conversation_id: str, server_logger: logging.Logger) -> List[Dict[str, str]]:
        tool_outputs = []
        for tool_call in tool_calls:
            function_name = tool_call.function.name
            server_logger.info(f"[{self.provider_name}] Tool requested: {function_name} with args: {tool_call.function.arguments}")

            try:
                args = json.loads(tool_call.function.arguments or "{}")
                function_response: Dict[str, Any] = {}

                if function_name == "search_vehicle_batteries":
                    user_query = args.get("query")
                    if not user_query:
                        server_logger.warning("Tool 'search_vehicle_batteries' called without 'query'.")
                        function_response = {} # Return empty dict as per prompt's Path C
                    else:
                        server_logger.info(f"Passing raw query to product service: '{user_query}'")
                        with db_utils.get_db_session() as session:
                            # This service is expected to return the full JSON with status, results, etc.
                            function_response = product_service.find_batteries_for_vehicle(
                                db_session=session,
                                user_query=user_query
                            )

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
                        function_response = {
                            "status": "success",
                            "lead_id": lead_id,
                            "details_updated": details_res.get("success")
                        }
                    else:
                        function_response = {"status": "error", "message": lead_intent_res.get("error_message")}

                elif function_name == "route_to_sales_department":
                    support_board_service.route_conversation_to_sales(sb_conversation_id)
                    function_response = {"status": "success", "message": "Conversation routed to Sales."}

                elif function_name == "route_to_human_support":
                    support_board_service.route_conversation_to_support(sb_conversation_id)
                    function_response = {"status": "success", "message": "Conversation routed to Support."}

                else:
                    function_response = {"status": "error", "message": f"Unknown tool '{function_name}'."}

                tool_outputs.append({
                    "tool_call_id": tool_call.id,
                    "output": json.dumps(function_response, ensure_ascii=False)
                })

            except Exception as e:
                server_logger.exception(f"Error executing tool {function_name}: {e}")
                tool_outputs.append({
                    "tool_call_id": tool_call.id,
                    "output": json.dumps({"status": "error", "message": str(e)}, ensure_ascii=False)
                })
        return tool_outputs