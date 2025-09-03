# namwoo_app/services/tools_schema.py
# -*- coding: utf-8 -*-
"""
Defines the JSON schema for tools to be used with the OpenAI/Azure Assistants API.
This ensures the Assistant is created with a consistent, version-controlled set of tools.
"""

from config.config import Config

def get_tools_schema():
    """Returns the list of tool schemas."""
    tools = [
        # --- MODIFICATION START ---
        # The old, complex tool definition is replaced with this new, simpler one.
        {
            "type": "function",
            "function": {
                "name": "search_vehicle_batteries",
                "description": "Searches for compatible vehicle batteries using a raw, natural language query from the user. This is the primary tool for finding any battery product.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "The user's full, original query about the vehicle. For example: 'bateria para mi chevrolet optra desing 2009' or 'great wall safe 2006'."
                        }
                    },
                    "required": ["query"],
                },
            },
        },
        # --- MODIFICATION END ---
        {
            "type": "function",
            "function": {
                "name": "get_cashea_financing_options",
                "description": "Calcula un plan de financiamiento de Cashea para un precio de producto y un nivel de usuario específicos. Úsalo cuando un cliente pregunta '¿cómo puedo pagar con Cashea?' o solicita un plan de pagos y ya ha proporcionado su nivel de Cashea.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "product_price": {
                            "type": "number",
                            "description": "El precio base del producto sobre el cual se calculará el financiamiento (price_regular)."
                        },
                        "user_level": {
                            "type": "string",
                            "description": "El nivel de Cashea del usuario, por ejemplo, 'Nivel 1', 'Nivel 6'."
                        },
                        "apply_discount": {
                            "type": "boolean",
                            "description": "Debe ser `true` si el cliente pagará en Divisas (dólares) para aplicar el descuento, o `false` si pagará en Bolívares."
                        }
                    },
                    "required": ["product_price", "user_level", "apply_discount"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "route_to_sales_department",
                "description": "Transfers the conversation to the human sales team. Use this when the user shows clear intent to purchase, has confirmed the product they want, and is ready to finalize payment and delivery details.",
                "parameters": { "type": "object", "properties": {} },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "route_to_human_support",
                "description": "Transfers the conversation to a general human support agent. Use this for complex issues not covered by other tools, user complaints, or when the user explicitly asks to speak to a person for a non-sales related reason.",
                "parameters": { "type": "object", "properties": {} },
            },
        }
    ]

    if Config.ENABLE_LEAD_GENERATION_TOOLS:
        tools.append({
            "type": "function",
            "function": {
                "name": "submit_order_for_processing",
                "description": "Submits the final, confirmed order details to the sales team for processing.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "conversation_id": {"type": "string", "description": "The current conversation ID."},
                        "user_id": {"type": "string", "description": "The platform-specific user ID of the customer."},
                        "customer_name": {"type": "string", "description": "Customer's full name."},
                        "customer_cedula": {"type": "string", "description": "Customer's ID number (Cédula)."},
                        "customer_phone": {"type": "string", "description": "Customer's phone number."},
                        "chosen_battery_brand": {"type": "string", "description": "The brand of the chosen battery."},
                        "chosen_battery_model": {"type": "string", "description": "The model code of the chosen battery."},
                        "original_list_price": {"type": "number", "description": "The base price of the battery from the database search result (price_full)."},
                        "location_discount_applied_percent": {"type": "integer", "description": "The location-based discount percentage that was already included in the original_list_price (e.g., 25 or 26)."},
                        "product_discount_applied_percent": {"type": "number", "description": "The additional product-specific discount percentage applied (e.g., 0.10 for Fulgor Black, 0.15 for Optima, 0 for others)."},
                        "final_price_paid": {"type": "number", "description": "The final calculated price after all discounts."},
                        "shipping_method": {"type": "string", "description": "How the customer will receive the battery (e.g., 'Entrega a Domicilio', 'Recoger en Tienda')."},
                        "delivery_address": {"type": "string", "description": "Customer's full delivery address, if applicable."},
                        "pickup_store_location": {"type": "string", "description": "The name or location of the store for pickup, if applicable."},
                        "payment_method": {"type": "string", "description": "Chosen payment method (e.g., 'Divisas', 'Cashea', 'Pago Móvil')."},
                        "cashea_level": {"type": "string", "description": "The customer's Cashea level (e.g., 'Nivel 1'), if applicable."},
                        "cashea_initial_payment": {"type": "number", "description": "The calculated initial payment for Cashea, if applicable."},
                        "cashea_installment_amount": {"type": "number", "description": "The calculated amount for each of the 3 Cashea installments, if applicable."},
                        "notes_about_old_battery_fee": {"type": "string", "description": "A note confirming the user was informed about the old battery requirement/fee."},
                    },
                    "required": ["conversation_id", "user_id", "customer_name", "customer_phone", "chosen_battery_brand", "chosen_battery_model", "final_price_paid", "shipping_method", "payment_method"],
                }
            }
        })
    return tools

# Make the list directly available for import
tools_schema = get_tools_schema()