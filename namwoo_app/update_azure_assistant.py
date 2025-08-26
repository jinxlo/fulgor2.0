# namwoo_app/update_azure_assistant.py
import os
import sys
import logging
from openai import AzureOpenAI
from dotenv import load_dotenv

# Add the app directory to Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '.')))

# --- Preserving original tool schema loading logic ---
try:
    class Config:
        ENABLE_LEAD_GENERATION_TOOLS = True
    
    with open('services/tools_schema.py', 'r') as f:
        tools_schema_code = f.read()
    
    tools_schema_code = tools_schema_code.replace('from ..config import Config', '')
    
    exec(tools_schema_code)
    
except Exception as e:
    print(f"\nERROR: Could not load 'tools_schema'.\n"
          f"Details: {e}")
    sys.exit(1)
# --- End of tool schema loading ---

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def update_azure_namfulgor_assistant():
    """
    Updates an existing Azure OpenAI Assistant with the latest instructions and tools.
    """
    basedir = os.path.abspath(os.path.dirname(__file__))
    dotenv_path = os.path.join(basedir, '.env')
    load_dotenv(dotenv_path=dotenv_path)
    logging.info("Loaded environment variables...")

    # --- Fetch all required environment variables ---
    azure_endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
    api_key = os.getenv("AZURE_OPENAI_API_KEY")
    api_version = os.getenv("AZURE_OPENAI_API_VERSION")
    model_deployment_name = os.getenv("AZURE_OPENAI_ASSISTANT_MODEL_DEPLOYMENT_NAME")
    assistant_id = os.getenv("AZURE_OPENAI_ASSISTANT_ID") # <-- Get the ID of the assistant to update

    # --- Validate all required variables ---
    if not all([azure_endpoint, api_key, api_version, model_deployment_name]):
        logging.error("CRITICAL: One or more required Azure connection variables are missing.")
        return
    
    if not assistant_id:
        logging.error("CRITICAL: AZURE_OPENAI_ASSISTANT_ID is missing from your .env file.")
        logging.error("Please run the create_azure_assistant.py script first to create an assistant and get its ID.")
        return

    client = AzureOpenAI(
        api_key=api_key,
        api_version=api_version,
        azure_endpoint=azure_endpoint
    )

    try:
        prompt_file_path = os.path.join(basedir, "data", "system_prompt.txt")
        with open(prompt_file_path, "r", encoding="utf-8") as f:
            prompt_content = f.read()
        logging.info(f"Successfully read system prompt from: {prompt_file_path}")
    except FileNotFoundError:
        logging.error(f"CRITICAL: Could not find system_prompt.txt at: {prompt_file_path}")
        return

    logging.info(f"Sending request to Azure OpenAI to UPDATE Assistant ID '{assistant_id}'...")
    try:
        assistant = client.beta.assistants.update(
            assistant_id=assistant_id,
            name="Serviauto Supremo (NamFulgor Azure)", # Keeping the name consistent
            instructions=prompt_content,
            tools=tools_schema,
            model=model_deployment_name
        )
        logging.info(f"Azure Assistant updated successfully. Details received for ID: {assistant.id}")

        print("\n" + "="*50)
        print("✅ Azure Assistant Updated Successfully!")
        print(f"   Assistant ID: {assistant.id}")
        print("="*50)
        print("\nThis assistant has been updated with the latest instructions and tools.")

    except Exception as e:
        logging.error(f"Failed to update Assistant on Azure's servers. Error: {e}", exc_info=True)

if __name__ == "__main__":
    update_azure_namfulgor_assistant()