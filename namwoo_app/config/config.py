# namwoo_app/config/config.py (NamFulgor Version - Refactored for AI Providers)
# -*- coding: utf-8 -*-
import os
import logging
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# --- CORRECTED BASEDIR CALCULATION (Unchanged) ---
basedir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
dotenv_path = os.path.join(basedir, '.env')

if os.path.exists(dotenv_path):
    load_dotenv(dotenv_path=dotenv_path, override=True)
    logger.debug("Loaded .env from: %s", dotenv_path)
else:
    logger.warning(".env file not found at %s", dotenv_path)

class Config:
    # --- Flask App (Unchanged) ---
    SECRET_KEY = os.environ.get('SECRET_KEY', 'default-insecure-namfulgor-key')
    FLASK_ENV = os.environ.get('FLASK_ENV', 'production')
    DEBUG = FLASK_ENV == 'development'

    # --- Logging (Unchanged) ---
    LOG_LEVEL = os.environ.get('LOG_LEVEL', 'INFO').upper()
    LOG_DIR = os.path.join(basedir, 'logs')
    os.makedirs(LOG_DIR, exist_ok=True)
    LOG_FILE = os.path.join(LOG_DIR, 'namfulgor_app.log')

    # --- AI Provider Configuration (MODIFIED SECTION) ---
    # This is the central switch for the AI logic.
    # Valid options: "openai_chat", "openai_assistant", "azure_assistant", "google_gemini"
    AI_PROVIDER = os.environ.get('AI_PROVIDER', 'openai_chat').lower()

    # --- OpenAI Configuration (for both Chat and Assistant) ---
    OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY')
    OPENAI_CHAT_MODEL = os.environ.get('OPENAI_CHAT_MODEL', 'gpt-4o-mini')
    OPENAI_MAX_TOKENS = int(os.environ.get('OPENAI_MAX_TOKENS', 1024))
    OPENAI_REQUEST_TIMEOUT = float(os.environ.get('OPENAI_REQUEST_TIMEOUT', 60.0))
    # --- OpenAI Assistant Specific (NEW) ---
    OPENAI_ASSISTANT_ID = os.environ.get('OPENAI_ASSISTANT_ID')

    # --- Azure OpenAI Assistant Specific (NEW) ---
    AZURE_OPENAI_API_KEY = os.environ.get("AZURE_OPENAI_API_KEY")
    AZURE_OPENAI_ASSISTANT_ID = os.environ.get("AZURE_OPENAI_ASSISTANT_ID")
    AZURE_OPENAI_ENDPOINT = os.environ.get("AZURE_OPENAI_ENDPOINT")
    AZURE_OPENAI_API_VERSION = os.environ.get("AZURE_OPENAI_API_VERSION")
    # This is the name of the model *deployment* in your Azure AI Studio
    AZURE_OPENAI_ASSISTANT_MODEL_DEPLOYMENT_NAME = os.environ.get("AZURE_OPENAI_ASSISTANT_MODEL_DEPLOYMENT_NAME")
    
    # --- NEW VARIABLE FOR THE CHAT PARSER ---
    AZURE_OPENAI_CHAT_DEPLOYMENT_NAME = os.environ.get("AZURE_OPENAI_CHAT_DEPLOYMENT_NAME")

    # --- Google Gemini Configuration (Unchanged) ---
    GOOGLE_API_KEY = os.environ.get('GOOGLE_API_KEY')
    GOOGLE_GEMINI_MODEL = os.environ.get('GOOGLE_GEMINI_MODEL', 'gemini-1.5-flash-latest')
    GOOGLE_MAX_TOKENS = int(os.environ.get('GOOGLE_MAX_TOKENS', 2048))
    GOOGLE_REQUEST_TIMEOUT = float(os.environ.get('GOOGLE_REQUEST_TIMEOUT', 60.0))

    # --- PostgreSQL Database (Unchanged) ---
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL')
    if SQLALCHEMY_DATABASE_URI and SQLALCHEMY_DATABASE_URI.startswith("postgres://"):
        SQLALCHEMY_DATABASE_URI = SQLALCHEMY_DATABASE_URI.replace("postgres://", "postgresql://", 1)
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ECHO = DEBUG

    # --- Redis (for Assistant locking) (NEW) ---
    REDIS_URL = os.environ.get('REDIS_URL', 'redis://localhost:6379/0')

    # --- Support Board Configuration (Unchanged) ---
    SUPPORT_BOARD_API_URL = os.environ.get('SUPPORT_BOARD_API_URL')
    SUPPORT_BOARD_API_TOKEN = os.environ.get('SUPPORT_BOARD_API_TOKEN')
    SUPPORT_BOARD_WEBHOOK_SECRET = os.environ.get('SUPPORT_BOARD_WEBHOOK_SECRET')
    SUPPORT_BOARD_DM_BOT_USER_ID = os.environ.get('SUPPORT_BOARD_DM_BOT_USER_ID')
    
    # +++ START OF FIX +++
    # Department IDs for conversation routing
    SUPPORT_BOARD_SALES_DEPARTMENT_ID = os.environ.get('SUPPORT_BOARD_SALES_DEPARTMENT_ID')
    SUPPORT_BOARD_SUPPORT_DEPARTMENT_ID = os.environ.get('SUPPORT_BOARD_SUPPORT_DEPARTMENT_ID')
    # +++ END OF FIX +++

    COMMENT_BOT_PROXY_USER_ID = os.environ.get('COMMENT_BOT_PROXY_USER_ID')
    COMMENT_BOT_INITIATION_TAG = os.environ.get('COMMENT_BOT_INITIATION_TAG')
    _agent_ids_str = os.environ.get('SUPPORT_BOARD_AGENT_IDS', '')
    SUPPORT_BOARD_AGENT_IDS = {id.strip() for id in _agent_ids_str.split(',') if id.strip()} if _agent_ids_str else set()
    HUMAN_TAKEOVER_PAUSE_MINUTES = int(os.environ.get('HUMAN_TAKEOVER_PAUSE_MINUTES', 30))

    # --- WhatsApp Cloud API (Unchanged) ---
    WHATSAPP_CLOUD_API_TOKEN = os.environ.get('WHATSAPP_CLOUD_API_TOKEN')
    WHATSAPP_PHONE_NUMBER_ID = os.environ.get('WHATSAPP_PHONE_NUMBER_ID')

    # --- Application Specific (Unchanged) ---
    MAX_HISTORY_MESSAGES = int(os.environ.get('MAX_HISTORY_MESSAGES', 16))

    # --- API Key for Price Updates (Unchanged) ---
    INTERNAL_SERVICE_API_KEY = os.environ.get('INTERNAL_SERVICE_API_KEY')
    if not INTERNAL_SERVICE_API_KEY:
        logger.warning("INTERNAL_SERVICE_API_KEY is not set. Price update endpoint is vulnerable.")

    # --- System Prompt for AI Assistant (Unchanged) ---
    SYSTEM_PROMPT_FILE = os.path.join(basedir, 'data', 'system_prompt.txt')
    try:
        with open(SYSTEM_PROMPT_FILE, 'r', encoding='utf-8') as f:
            SYSTEM_PROMPT = f.read().strip()
        logger.info("Loaded system prompt from %s", SYSTEM_PROMPT_FILE)
    except FileNotFoundError:
        logger.error("system_prompt.txt not found at %s. Using fallback.", SYSTEM_PROMPT_FILE)
        SYSTEM_PROMPT = (
            "Eres un asistente virtual especializado en baterías para vehículos. "
            "Ayuda a los clientes a encontrar la batería correcta y proporciona "
            "información sobre precios y garantía."
        )

    # --- Lead Capture API (Unchanged) ---
    LEAD_CAPTURE_API_URL = os.environ.get('LEAD_CAPTURE_API_URL')
    LEAD_CAPTURE_API_KEY = os.environ.get('LEAD_CAPTURE_API_KEY')
    ENABLE_LEAD_GENERATION_TOOLS = os.environ.get('ENABLE_LEAD_GENERATION_TOOLS', 'true').lower() == 'true'


# --- Config Sanity Check (MODIFIED) ---
if __name__ != "__main__":
    logger.info("--- NamFulgor Config Initialized (Provider Architecture) ---")
    logger.info("Project Basedir (for .env, logs): %s", basedir)
    logger.info(".env Loaded From: %s", dotenv_path if os.path.exists(dotenv_path) else 'Not Found')
    logger.info("ENV: %s, DEBUG=%s, Active AI Provider: %s", Config.FLASK_ENV, Config.DEBUG, Config.AI_PROVIDER)
    logger.info("DB URI: %s", 'SET' if Config.SQLALCHEMY_DATABASE_URI else 'MISSING')
    logger.info("Redis URL: %s", Config.REDIS_URL)
    logger.info("Log File Path: %s", Config.LOG_FILE)
    logger.info("Support Board URL: %s", Config.SUPPORT_BOARD_API_URL)
    logger.info("DM Bot User ID: %s", Config.SUPPORT_BOARD_DM_BOT_USER_ID)
    logger.info(
        "System Prompt File: %s - Loaded: %s",
        Config.SYSTEM_PROMPT_FILE,
        'Yes' if "Eres un asistente virtual especializado" in Config.SYSTEM_PROMPT else 'Fallback Used'
    )
    logger.info("--------------------")