# namwoo_app/services/providers/azure_chat_provider.py
# -*- coding: utf-8 -*-
import logging
import json
from typing import Dict, Any

from openai import AzureOpenAI

logger = logging.getLogger(__name__)

class AzureChatProvider:
    """
    A provider that uses Azure OpenAI's Chat Completion API for specific tasks,
    like parsing vehicle information from a user query.
    """
    def __init__(self, *, api_key: str, azure_endpoint: str, api_version: str, deployment_name: str):
        if not all([api_key, azure_endpoint, api_version, deployment_name]):
            raise ValueError("AzureChatProvider requires api_key, azure_endpoint, api_version, and deployment_name.")
        
        self.client = AzureOpenAI(
            api_key=api_key,
            api_version=api_version,
            azure_endpoint=azure_endpoint
        )
        self.deployment_name = deployment_name

    def parse_vehicle_query(self, query: str, system_prompt: str) -> Dict[str, Any]:
        """
        Uses the configured Azure OpenAI model to execute a specific task
        defined by the system_prompt and expects a JSON response.
        """
        logger.info(f"Sending query to Azure OpenAI for JSON parsing: '{query[:100]}...'")
        try:
            response = self.client.chat.completions.create(
                model=self.deployment_name,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": query}
                ],
                temperature=0.0,
                response_format={"type": "json_object"}
            )
            
            content = response.choices[0].message.content
            parsed_json = json.loads(content)
            logger.info(f"Successfully parsed data from AI: {parsed_json}")
            return parsed_json
            
        except json.JSONDecodeError as json_err:
            logger.error(f"Failed to decode JSON from Azure OpenAI response. Error: {json_err}. Response: {content}")
            return {}
        except Exception as e:
            logger.exception(f"An unexpected error occurred while calling Azure OpenAI for parsing: {e}")
            return {}

    # --- THIS IS THE NEW METHOD THAT FIXES THE CRASH ---
    def get_simple_response(self, query: str, system_prompt: str) -> str:
        """
        Uses the configured Azure OpenAI model for a simple text-in, text-out task.
        Does NOT expect a JSON response. This is used by the AI Decision-Maker.
        """
        logger.info(f"Sending query to Azure OpenAI for simple text response: '{query[:100]}...'")
        try:
            response = self.client.chat.completions.create(
                model=self.deployment_name,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": query}
                ],
                temperature=0.0,
                max_tokens=150 # Keep response short and focused on the vehicle name
            )
            
            content = response.choices[0].message.content
            logger.info(f"Received simple text response from AI: '{content}'")
            return content.strip() if content else ""
            
        except Exception as e:
            logger.exception(f"An unexpected error occurred while calling Azure OpenAI for simple response: {e}")
            return ""
    # --- END OF NEW METHOD ---