import requests
import json
import random
import sys
import time
import os
import logging
import threading
import glob
import re
from datetime import datetime
from typing import Dict, Any, Tuple, List, Optional, Callable

# --- Load Environment Variables ---
from dotenv import load_dotenv
load_dotenv()

# --- OpenAI/Azure Client ---
from openai import AzureOpenAI

# --- Import from test_definitions.py ---
# We keep this for AI-driven scenarios, but the new mode won't use it.
try:
    from test_definitions import AI_SCENARIOS, PRODUCT_CATEGORIES
except ImportError:
    print("Warning: test_definitions.py not found. AI Conversation mode [1] will not be available.")
    AI_SCENARIOS, PRODUCT_CATEGORIES = {}, []


# --- CONFIGURATION (loaded from .env) ---
SUPPORT_BOARD_API_URL = os.getenv("SUPPORT_BOARD_API_URL")
SUPPORT_BOARD_API_TOKEN = os.getenv("SUPPORT_BOARD_API_TOKEN")
BOT_USER_ID = os.getenv("BOT_USER_ID")
AZURE_ENDPOINT = os.getenv("AZURE_ENDPOINT")
AZURE_API_KEY = os.getenv("AZURE_API_KEY")
AZURE_API_VERSION = os.getenv("AZURE_API_VERSION")
AZURE_DEPLOYMENT_USER_AGENT = os.getenv("AZURE_DEPLOYMENT_USER_AGENT", "gpt-4o-mini")
AZURE_DEPLOYMENT_ANALYZER = os.getenv("AZURE_DEPLOYMENT_ANALYZER", "gpt-4o")

# --- Testing Configuration ---
LOG_DIRECTORY = "test_logs"
PROMPT_DIRECTORY = "prompts"
# NEW: Path to the data scripts to find our vehicle list
DATA_SCRIPTS_PATH = "initial_data_scripts" 
VEHICLE_DATA_FILE = os.path.join(DATA_SCRIPTS_PATH, "vehicle_fitments_data.json")

ANALYZER_PROMPT_FILE = "analyzer_qa.txt"
ANALYZER_COMPREHENSIVE_PROMPT_FILE = "analyzer_comprehensive.txt"
AGENT_SYSTEM_PROMPT_FILE = "agent_system_prompt.txt"
MAX_CONVERSATION_TURNS = 15
ASSISTANT_REPLY_TIMEOUT_SECONDS = 40
POLLING_INTERVAL_SECONDS = 10
MAX_USER_WAIT_SECONDS = 120

# Phrases that signal the end of the bot's involvement or failure
STOP_PHRASES = ["Tu conversación ha sido transferida a un agente", "Un agente estará contigo en breve", "para que pueda ayudarte mejor"]
FAILURE_PHRASE = "No pudimos encontrar la información para tu vehículo"
SUCCESS_KEYWORDS = ["Marca:", "Modelo:", "Garantía:", "Fulgor", "Black Edition"]

# Configuration for Controlled (Replay) Conversations
SIMULATED_LOGS_DIRECTORY = "test_logs"
PRODUCTION_LOGS_DIRECTORY = "production_logs"
LOG_FILENAME_PATTERNS = ["conversation.log", "*.txt"]

# Log format prefixes
SIMULATED_USER_PREFIX, SIMULATED_ASSISTANT_PREFIX = "USER (SIMULATED):", "ASSISTANT (TOMÁS):"
PRODUCTION_USER_PREFIX, PRODUCTION_AGENT_PREFIX = "USER", "AGENT"


# --- HELPER FUNCTIONS (Mostly unchanged) ---
def load_prompt(filename: str) -> str:
    path = os.path.join(PROMPT_DIRECTORY, filename)
    try:
        with open(path, 'r', encoding='utf-8') as f: return f.read()
    except FileNotFoundError:
        print(f"FATAL ERROR: Prompt file not found at '{path}'. Please ensure it exists.")
        raise

def _call_sb_api(payload: Dict) -> Tuple[bool, Any]:
    if not SUPPORT_BOARD_API_URL or not SUPPORT_BOARD_API_TOKEN:
        print("❌ ERROR: Ensure SUPPORT_BOARD_API_URL and SUPPORT_BOARD_API_TOKEN are set.")
        return False, {"error": "Configuration missing."}
    payload['token'] = SUPPORT_BOARD_API_TOKEN
    try:
        response = requests.post(SUPPORT_BOARD_API_URL, data=payload, timeout=20)
        response.raise_for_status()
        response_json = response.json()
        if response_json.get("success") is True:
            return True, response_json.get("response")
        else:
            print(f"❌ API call to '{payload.get('function', 'N/A')}' failed. Response: {response_json}")
            return False, response_json
    except requests.exceptions.RequestException as e:
        print(f"❌ HTTP Error on API call '{payload.get('function', 'N/A')}': {e}")
        return False, {"error": str(e)}
    except json.JSONDecodeError:
        print(f"❌ JSON Decode Error from API. Raw text: {response.text}")
        return False, {"error": "JSON Decode Error"}

def setup_logging(conversation_id: str, test_name: str) -> Tuple[logging.Logger, str]:
    log_dir = LOG_DIRECTORY
    if "Replay of" in test_name:
        log_dir = os.path.join(LOG_DIRECTORY, "replays")
    elif "Vehicle Check" in test_name:
        log_dir = os.path.join(LOG_DIRECTORY, "vehicle_checks")

    if not os.path.exists(log_dir):
        os.makedirs(log_dir)
    safe_name = "".join(c for c in test_name if c.isalnum() or c in (' ', '_')).rstrip()
    log_filename = f"{log_dir}/test_log_{safe_name}_conv_{conversation_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    logger = logging.getLogger(f"conv_{conversation_id}")
    if logger.hasHandlers():
        logger.handlers.clear()
    logger.setLevel(logging.INFO)
    handler = logging.FileHandler(log_filename, encoding='utf-8')
    formatter = logging.Formatter('%(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    print(f"📜 Thread for '{test_name}' will log to: {os.path.basename(log_filename)}")
    return logger, log_filename

def format_extra_details_for_sb(details: Dict[str, str]) -> str:
    formatted_details = {}
    for key, value in details.items():
        display_name = key.replace('_', ' ').title()
        formatted_details[key] = [value, display_name]
    return json.dumps(formatted_details)

def create_user() -> Optional[str]:
    user_details = {"phone": f"+1555{random.randint(1000000, 9999999)}", "city": "Testville", "country": "USA"}
    payload = {'function': 'add-user', 'first_name': 'Comprehensive Test', 'last_name': f'#{random.randint(1000,9999)}', 'user_type': 'visitor', 'extra': format_extra_details_for_sb(user_details)}
    success, response = _call_sb_api(payload)
    if success and isinstance(response, int): return str(response)
    return None

def create_conversation(user_id: str) -> Optional[str]:
    payload = {'function': 'new-conversation', 'user_id': user_id, 'status_code': 0}
    success, response = _call_sb_api(payload)
    if success and isinstance(response, dict) and response.get('details', {}).get('id'):
        return str(response['details']['id'])
    return None

def send_message(user_id: str, conversation_id: str, message_text: str, logger: logging.Logger) -> bool:
    logger.info(f"{SIMULATED_USER_PREFIX} {message_text}")
    payload = {'function': 'send-message', 'user_id': user_id, 'conversation_id': conversation_id, 'message': message_text}
    success, _ = _call_sb_api(payload)
    return success

def poll_for_new_reply(conversation_id: str, last_message_count: int, logger: logging.Logger) -> Optional[str]:
    start_time = time.time()
    while time.time() - start_time < ASSISTANT_REPLY_TIMEOUT_SECONDS:
        success, response = _call_sb_api({'function': 'get-conversation', 'conversation_id': conversation_id})
        if success and isinstance(response, dict) and 'messages' in response:
            messages = response['messages']
            if len(messages) > last_message_count:
                for i in range(last_message_count, len(messages)):
                    new_message = messages[i]
                    if str(new_message.get('user_id')) == BOT_USER_ID:
                        response_time = time.time() - start_time
                        reply_text = new_message.get('message', '')
                        logger.info(f"{SIMULATED_ASSISTANT_PREFIX} {reply_text}  [Response Time: {response_time:.2f}s]")
                        return reply_text
        time.sleep(POLLING_INTERVAL_SECONDS)
    logger.warning(f"TIMEOUT: Assistant did not reply within {ASSISTANT_REPLY_TIMEOUT_SECONDS}s.")
    return None

def get_ai_user_response(client: AzureOpenAI, conversation_history: List[str], persona_prompt: str) -> str:
    # This function is for AI-driven conversations, not our new vehicle check mode.
    system_message = {"role": "system", "content": persona_prompt}
    history_text = "\n".join(conversation_history)
    user_prompt_content = f"This is the conversation so far:\n\n---\n{history_text}\n---\n\nBased on your strict test plan and the last thing the assistant said, what is your next single response? Your response must be short and direct. Just output the response text, nothing else."
    messages = [system_message, {"role": "user", "content": user_prompt_content}]
    try:
        completion = client.chat.completions.create(model=AZURE_DEPLOYMENT_USER_AGENT, messages=messages, max_tokens=150, temperature=0.5)
        return completion.choices[0].message.content.strip().strip('"')
    except Exception as e:
        return f"Tengo un problema técnico: {e}"

# --- NEW FUNCTION: GENERATE VEHICLE TESTS ---
def generate_vehicle_tests_from_json() -> Dict[str, Any]:
    print(f"\n🔎 Scanning for vehicle data in '{VEHICLE_DATA_FILE}'...")
    if not os.path.exists(VEHICLE_DATA_FILE):
        print(f"❌ FATAL: Vehicle data file not found at '{VEHICLE_DATA_FILE}'. Please run the `models_set.py` script first.")
        return {}
    
    generated_tests = {}
    try:
        with open(VEHICLE_DATA_FILE, 'r', encoding='utf-8') as f:
            vehicles = json.load(f)
        
        for i, vehicle in enumerate(vehicles):
            make = vehicle.get('vehicle_make')
            model = vehicle.get('vehicle_model')
            year = vehicle.get('year_start') # Use the start year for testing
            
            if not all([make, model, year]):
                continue

            test_id = f"vehicle_check_{i+1}"
            generated_tests[test_id] = {
                "name": f"Vehicle Check: {make} {model} ({year})",
                "type": "vehicle_check",
                "vehicle_data": {
                    "make": make,
                    "model": model,
                    "year": year
                }
            }
        print(f"✨ Successfully generated {len(generated_tests)} vehicle test cases.")
        return generated_tests
    except Exception as e:
        print(f"⚠️ Warning: Could not parse vehicle data file. Error: {e}")
        return {}


# --- LOG PARSING (Unchanged) ---
def parse_simulated_log(log_filepath: str) -> Optional[List[Dict[str, Any]]]:
    # ... (function content is unchanged)
    pass
def parse_real_world_log(log_filepath: str) -> Optional[List[Dict[str, Any]]]:
    # ... (function content is unchanged)
    pass
def generate_controlled_tests_from_logs(logs_directory: str, parser_func: Callable[[str], Optional[List[Dict[str, Any]]]]) -> Dict[str, Any]:
    # ... (function content is unchanged)
    pass


# --- ANALYSIS & TEST EXECUTION ---
def analyze_conversation_log(client: AzureOpenAI, test_plan: str, log_filepath: str, original_log_content: Optional[str] = None) -> str:
    # ... (function content is unchanged, but will be bypassed for vehicle checks)
    pass

# --- MODIFIED: run_test_conversation ---
def run_test_conversation(test_case_info: Dict, results_list: List):
    test_name = test_case_info['name']
    test_type = test_case_info.get('type')
    
    # Initialize variables
    azure_client = AzureOpenAI(api_key=AZURE_API_KEY, azure_endpoint=AZURE_ENDPOINT, api_version=AZURE_API_VERSION)
    new_user_id, log_file, result = None, None, "FAIL (Setup)"

    try:
        new_user_id = create_user()
        if not new_user_id: return
        new_conversation_id = create_conversation(new_user_id)
        if not new_conversation_id: return
        
        logger, log_file = setup_logging(new_conversation_id, test_name)

        if test_type == "vehicle_check":
            print(f"🚀 Starting Comprehensive Vehicle Check: '{test_name}'")
            vehicle = test_case_info['vehicle_data']
            user_message = f"Hola, necesito una batería para un {vehicle['make']} {vehicle['model']} del año {vehicle['year']}"
            
            logger.info(f"TEST PLAN: {test_name}\nGOAL: Verify agent finds a battery for the vehicle.\n---")
            
            send_message(new_user_id, new_conversation_id, user_message, logger)
            assistant_reply = poll_for_new_reply(new_conversation_id, 1, logger)

            # Automated analysis for this test type
            if not assistant_reply:
                result = "FAIL (Timeout)"
            elif FAILURE_PHRASE in assistant_reply:
                result = "FAIL (Vehicle Not Found)"
            elif any(keyword in assistant_reply for keyword in SUCCESS_KEYWORDS):
                result = "SUCCESS"
            else:
                result = "UNKNOWN (Manual Check Required)"
            
            logger.info(f"\n--- AUTO-ANALYSIS ---\nOverall Summary: {result}")

        elif test_type == 'controlled':
            # ... (controlled conversation logic is unchanged) ...
            pass
        else: # Default to AI Conversation
            # ... (ai conversation logic is unchanged) ...
            pass

    except Exception as e:
        print(f"❌ UNEXPECTED ERROR in thread for '{test_name}': {e}")
        import traceback
        traceback.print_exc()
        result = f"FAIL (Exception: {e})"
    finally:
        results_list.append({"name": test_name, "status": result, "log": os.path.basename(log_file) if log_file else "N/A"})
        print(f"✅ Thread finished for test: '{test_name}'. Status: {result}")


def run_tests(test_cases_to_run: List[Dict], delay_seconds: float, is_random_delay: bool):
    # ... (function content is unchanged)
    pass

# --- MODIFIED: main ---
def main():
    if not os.path.isdir(PROMPT_DIRECTORY):
        sys.exit(f"FATAL: The required prompt directory '{PROMPT_DIRECTORY}' was not found.")
    if not all([SUPPORT_BOARD_API_URL, SUPPORT_BOARD_API_TOKEN, BOT_USER_ID, AZURE_ENDPOINT, AZURE_API_KEY, AZURE_API_VERSION]):
        sys.exit("FATAL: One or more required environment variables are missing. Check your .env file.")

    print("--- Conversational AI Test Runner ---")
    print("\nSelect a testing mode:")
    print("  [1] AI Conversations (Prompt-Guided Scenarios)")
    print("  [2] Controlled Conversations (Scripted Replays from Logs)")
    print("  [3] Comprehensive Vehicle Model Test (NEW)")
    mode_choice = input("Enter your choice: ")
    
    test_cases_to_run = []

    if mode_choice == '1':
        # ... (unchanged logic for AI conversations) ...
        pass
    
    elif mode_choice == '2':
        # ... (unchanged logic for controlled conversations) ...
        pass

    elif mode_choice == '3':
        print("\n--- Comprehensive Vehicle Model Test ---")
        all_vehicle_tests = generate_vehicle_tests_from_json()
        if not all_vehicle_tests:
            sys.exit("No vehicle tests could be generated. Aborting.")
        
        test_cases_to_run = list(all_vehicle_tests.values())
        print("\n--- Autonomous Run Configuration ---")
        try:
            batch_input = input(f"Generated {len(test_cases_to_run)} tests. Enter number of tests to run per batch (e.g., 2): ")
            batch_size = int(batch_input) if batch_input.strip() else 2
        except ValueError:
            batch_size = 2

        delay_seconds = 5 # Default delay between tests in a batch
        is_random_delay = False
        
        while test_cases_to_run:
            current_batch = test_cases_to_run[:batch_size]
            run_tests(current_batch, delay_seconds, is_random_delay)
            test_cases_to_run = test_cases_to_run[batch_size:]
            if test_cases_to_run:
                print(f"\n--- {len(test_cases_to_run)} tests remaining. Proceeding automatically to the next batch in 10 seconds... ---")
                time.sleep(10)
        
        print("\nAll vehicle test batches have been run.")
        return # End execution after comprehensive test

    else:
        sys.exit("Invalid mode selection. Aborting.")

    # This part will only run for modes 1 and 2
    delay_seconds, is_random_delay = 0, True
    if len(test_cases_to_run) > 1:
        user_input = input("Enter delay in seconds between tests (default is 3-5s): ")
        try:
            delay_seconds = float(user_input) if user_input.strip() else -1
            if delay_seconds >= 0: is_random_delay = False
            else: is_random_delay = True
        except ValueError: is_random_delay = True
    run_tests(test_cases_to_run, delay_seconds, is_random_delay)


if __name__ == "__main__":
    # --- Re-pasting the placeholder functions to make the script self-contained ---
    def parse_simulated_log(log_filepath: str) -> Optional[List[Dict[str, Any]]]: return None
    def parse_real_world_log(log_filepath: str) -> Optional[List[Dict[str, Any]]]: return None
    def generate_controlled_tests_from_logs(logs_directory: str, parser_func: Callable[[str], Optional[List[Dict[str, Any]]]]) -> Dict[str, Any]: return {}
    def analyze_conversation_log(client: AzureOpenAI, test_plan: str, log_filepath: str, original_log_content: Optional[str] = None) -> str: return "SKIPPED"
    def run_tests(test_cases_to_run: List[Dict], delay_seconds: float, is_random_delay: bool):
        if not test_cases_to_run:
            print("No test cases selected to run.")
            return
        threads, results = [], []
        total_tests = len(test_cases_to_run)
        print(f"\n--- Starting batch of {total_tests} test(s) ---")
        for i, test_case in enumerate(test_cases_to_run):
            thread = threading.Thread(target=run_test_conversation, args=(test_case, results))
            threads.append(thread)
            thread.start()
            if total_tests > 1 and i < total_tests - 1:
                current_delay = random.uniform(3, 5) if is_random_delay else delay_seconds
                print(f"\n--- Waiting {current_delay:.2f} seconds before launching the next test... ---")
                time.sleep(current_delay)
        for thread in threads: thread.join()
        print("\n\n" + "="*70)
        print("--- BATCH COMPLETE - SUMMARY ---")
        print("="*70)
        results.sort(key=lambda x: x['name'])
        for res in results:
            status_short = res['status'].split('(')[0].strip()
            status_color = {"SUCCESS": "\033[92m", "PARTIAL": "\033[93m", "FAIL": "\033[91m", "UNKNOWN": "\033[95m"}.get(status_short, "\033[0m")
            print(f"  - Test: {res['name']:<55} Status: {status_color}{res['status']:<20}\033[0m Log: {res['log']}")
        print("="*70)

    main()