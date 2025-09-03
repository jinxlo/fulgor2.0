# --- MODIFIED SCRIPT FOR FOCUSED RE-RUN ---
# This script has been adapted to exclusively re-test a specific list of 78 vehicles
# that previously failed or had an unknown status. The main function bypasses the
# usual menu and proceeds directly to running this predefined test set.
# ---

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
    # Create a specific subdirectory for these re-run logs
    log_dir = os.path.join(LOG_DIRECTORY, "failed_reruns")

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
    payload = {'function': 'add-user', 'first_name': 'Rerun Test', 'last_name': f'#{random.randint(1000,9999)}', 'user_type': 'visitor', 'extra': format_extra_details_for_sb(user_details)}
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
    # This function is for AI-driven conversations, not used in this focused re-run.
    system_message = {"role": "system", "content": persona_prompt}
    history_text = "\n".join(conversation_history)
    user_prompt_content = f"This is the conversation so far:\n\n---\n{history_text}\n---\n\nBased on your strict test plan and the last thing the assistant said, what is your next single response? Your response must be short and direct. Just output the response text, nothing else."
    messages = [system_message, {"role": "user", "content": user_prompt_content}]
    try:
        completion = client.chat.completions.create(model=AZURE_DEPLOYMENT_USER_AGENT, messages=messages, max_tokens=150, temperature=0.5)
        return completion.choices[0].message.content.strip().strip('"')
    except Exception as e:
        return f"Tengo un problema técnico: {e}"


# --- NEW FUNCTION: GENERATE FAILED VEHICLE TESTS FOR RE-RUN ---
def generate_failed_vehicle_tests() -> Dict[str, Any]:
    """
    Generates a dictionary of test cases based on a hardcoded list of
    78 previously failed vehicle tests.
    """
    print("\n🔎 Generating test cases from the hardcoded list of failed vehicles...")
    
    FAILED_VEHICLES_TEXT = """
1. Test Name: ALFA ROMEO GT (2003)
2. Test Name: BLUE BIRD AUTOBUSES A GASOLINA (1971)
3. Test Name: CHANGAN HUNTER 2.0 TURBO GASOLINA (2022)
4. Test Name: CHERY TIGGO 4/4PRO (2022)
5. Test Name: CHEVROLET GRAN VITARA XL5 4CIL (2000)
6. Test Name: CHEVROLET GRAN VITARA XL5 6CIL (2000)
7. Test Name: CHEVROLET GRAN VITARA XL7 (2003)
8. Test Name: CHEVROLET LUV 4 CIL 2.3L (2001)
9. Test Name: CHEVROLET OPTRA DESING (2009)
10. Test Name: CHEVROLET VITARA (2004)
11. Test Name: CHEVROLET VITARA (3 PUERTAS) (1997)
12. Test Name: CHRYSLER 300C (2007)
13. Test Name: CHRYSLER TOWN & COUNTRY (1991)
14. Test Name: DSFK GLORY 500 TURBO DYNAMIC (2022)
15. Test Name: DSFK GLORY 600 (2022)
16. Test Name: DSFK C31/Y32 (2022)
17. Test Name: DSFK K01S (2022)
18. Test Name: DODGE CHARGER DAYTONA (2015)
19. Test Name: DODGE RAM 2500 (2000)
20. Test Name: DONGFENG DOULIKA 5T, 7T (2012)
21. Test Name: FORD CARGO 1721 (2008)
22. Test Name: FORD EXPLORER ST (2023)
23. Test Name: FORD FORTALEZA (1997)
24. Test Name: FORD FX4 (2008)
25. Test Name: FORD RAPTOR XLS GASOLINA (2019)
26. Test Name: FORD SPORT TRAC (2005)
27. Test Name: GREAT WALL DEER (2006)
28. Test Name: GREAT WALL HOVER (2007)
29. Test Name: GREAT WALL PERI (2007)
30. Test Name: GREAT WALL SAFE (2006)
31. Test Name: HYUNDAI TIBURON (COUPE) (1997)
32. Test Name: JAC HFC1030P (X100) (2023)
33. Test Name: JEEP CHEROKEE T270 RENEGADO SPORT (2023)
34. Test Name: JEEP GRAND CHEROKEE LAREDO (1993)
35. Test Name: JEEP GRAND CHEROKEE WK-2 (4G) (2011)
36. Test Name: JEEP GRAND CHEROKEE OVERLAND (2023)
37. Test Name: JEEP RENEGADE/WRANGLER (1995)
38. Test Name: JEEP RUBICON (2008)
39. Test Name: KIA CARNIVAL (2023)
40. Test Name: KIA SORENTO (2023)
41. Test Name: LAND ROVER DEFENDER (1998)
42. Test Name: LAND ROVER DISCOVERY (1992)
43. Test Name: LAND ROVER RANGE ROVER (1956)
44. Test Name: MERCEDES BENZ AUTOBUSES (1958)
45. Test Name: MERCEDES BENZ E 190 (1991)
46. Test Name: MERCEDES BENZ E 300 (1991)
47. Test Name: MERCEDES BENZ ML 300 (2013)
48. Test Name: MERCEDES BENZ 500SEL (1991)
49. Test Name: MERCEDES BENZ 600SEL (1991)
50. Test Name: MERCEDES BENZ 711 (2007)
51. Test Name: MERCEDES BENZ LS 1634 (2005)
52. Test Name: MERCEDES BENZ LS 2640 (2005)
53. Test Name: MERCEDES BENZ MB 303 (1990)
54. Test Name: MERCEDES BENZ CLASE A (2001)
55. Test Name: MERCEDES BENZ CLASE B 200 (2006)
56. Test Name: MERCEDES BENZ CLASE C (1970)
57. Test Name: MERCEDES BENZ CLASE E (1986)
58. Test Name: MERCEDES BENZ CLASE G (2016)
59. Test Name: MERCEDES BENZ CLASE S (1975)
60. Test Name: MERCEDES BENZ SPRINTER (2004)
61. Test Name: MERCEDES BENZ PANEL (1990)
62. Test Name: PEUGEOT PARTNER (2012)
63. Test Name: RENAULT SADERO (2023)
64. Test Name: SAIC WULING CARGO (2006)
65. Test Name: SAIC WULING SUPER VAN (2006)
66. Test Name: SUZUKI GRAND VITARA (2007)
67. Test Name: TOYOTA COROLLA LE 1.8/LE 2.0 (2016)
68. Test Name: TOYOTA COROLLA IMPORTADO (SEGÚN MUESTRA) (2016)
69. Test Name: TOYOTA FORTUNER VXR (2018)
70. Test Name: TOYOTA FORTUNER VXR LEYENDER (2023)
71. Test Name: TOYOTA FORTUNER DIESEL 2.8 (2017)
72. Test Name: TOYOTA HILUX 2.7 (2006)
73. Test Name: TOYOTA HILUX DIESEL 2.8L (2022)
74. Test Name: TOYOTA LAND CRUISER SERIE 300 VX (2021)
75. Test Name: TOYOTA LAND CRUISER PRADO WX GASOLINA (2022)
76. Test Name: TOYOTA TERIOS (2002)
77. Test Name: TOYOTA YARIS E CVT (2022)
78. Test Name: VOLKSWAGEN TOUAREG (2004)
    """
    MULTI_WORD_MAKES = ["ALFA ROMEO", "BLUE BIRD", "GREAT WALL", "LAND ROVER", "MERCEDES BENZ", "SAIC WULING"]
    
    generated_tests = {}
    lines = FAILED_VEHICLES_TEXT.strip().split('\n')

    for i, line in enumerate(lines):
        line = line.strip()
        match = re.search(r'Test Name: (.*) \((\d{4})\)', line)
        if not match:
            continue

        full_name = match.group(1).strip()
        year = match.group(2).strip()
        
        make = ""
        model = ""
        found_make = False

        # Handle multi-word makes first
        for mw_make in MULTI_WORD_MAKES:
            if full_name.upper().startswith(mw_make):
                make = mw_make
                model = full_name[len(mw_make):].strip()
                found_make = True
                break
        
        if not found_make:
            # Assume first word is the make
            parts = full_name.split(' ', 1)
            make = parts[0]
            model = parts[1] if len(parts) > 1 else ""

        if not make or not model or not year:
            print(f"⚠️ Warning: Could not parse line: {line}")
            continue

        test_id = f"rerun_failed_{i+1}"
        generated_tests[test_id] = {
            "name": f"Rerun: {make} {model} ({year})",
            "type": "vehicle_check",
            "vehicle_data": {
                "make": make,
                "model": model,
                "year": year
            }
        }
        
    print(f"✨ Successfully generated {len(generated_tests)} vehicle test cases for re-run.")
    return generated_tests


# --- LOG PARSING (Unchanged) ---
def parse_simulated_log(log_filepath: str) -> Optional[List[Dict[str, Any]]]:
    pass
def parse_real_world_log(log_filepath: str) -> Optional[List[Dict[str, Any]]]:
    pass
def generate_controlled_tests_from_logs(logs_directory: str, parser_func: Callable[[str], Optional[List[Dict[str, Any]]]]) -> Dict[str, Any]:
    pass


# --- ANALYSIS & TEST EXECUTION ---
def analyze_conversation_log(client: AzureOpenAI, test_plan: str, log_filepath: str, original_log_content: Optional[str] = None) -> str:
    pass

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
            print(f"🚀 Starting Vehicle Check: '{test_name}'")
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
            elif any(keyword.lower() in assistant_reply.lower() for keyword in SUCCESS_KEYWORDS):
                result = "SUCCESS"
            else:
                result = "UNKNOWN (Manual Check Required)"
            
            logger.info(f"\n--- AUTO-ANALYSIS ---\nOverall Summary: {result}")

        else:
            logger.error(f"Unsupported test type '{test_type}' encountered.")
            result = "FAIL (Unsupported Type)"

    except Exception as e:
        print(f"❌ UNEXPECTED ERROR in thread for '{test_name}': {e}")
        import traceback
        traceback.print_exc()
        result = f"FAIL (Exception: {e})"
    finally:
        results_list.append({"name": test_name, "status": result, "log": os.path.basename(log_file) if log_file else "N/A"})
        print(f"✅ Thread finished for test: '{test_name}'. Status: {result}")


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
        print(f"  - Test: {res['name']:<65} Status: {status_color}{res['status']:<20}\033[0m Log: {res['log']}")
    print("="*70)

# --- MODIFIED: main ---
def main():
    if not os.path.isdir(PROMPT_DIRECTORY):
        sys.exit(f"FATAL: The required prompt directory '{PROMPT_DIRECTORY}' was not found.")
    if not all([SUPPORT_BOARD_API_URL, SUPPORT_BOARD_API_TOKEN, BOT_USER_ID, AZURE_ENDPOINT, AZURE_API_KEY, AZURE_API_VERSION]):
        sys.exit("FATAL: One or more required environment variables are missing. Check your .env file.")

    print("--- Conversational AI Test Runner ---")
    print("\n--- FOCUSED RE-RUN MODE ---")
    
    all_failed_tests = generate_failed_vehicle_tests()
    if not all_failed_tests:
        sys.exit("No failed vehicle tests could be generated. Aborting.")
    
    test_cases_to_run = list(all_failed_tests.values())
    
    print("\n--- Autonomous Run Configuration ---")
    try:
        batch_input = input(f"Loaded {len(test_cases_to_run)} tests. Enter number of tests to run per batch (e.g., 5): ")
        batch_size = int(batch_input) if batch_input.strip() else 5
    except ValueError:
        print("Invalid input, defaulting to batch size of 5.")
        batch_size = 5

    delay_seconds = 5 # Default delay between tests in a batch
    is_random_delay = False
    
    while test_cases_to_run:
        current_batch = test_cases_to_run[:batch_size]
        run_tests(current_batch, delay_seconds, is_random_delay)
        test_cases_to_run = test_cases_to_run[batch_size:]
        if test_cases_to_run:
            print(f"\n--- {len(test_cases_to_run)} tests remaining. Proceeding to the next batch in 10 seconds... ---")
            time.sleep(10)
    
    print("\nAll vehicle re-test batches have been run.")
    print("Check the 'test_logs/failed_reruns' directory for detailed logs.")


if __name__ == "__main__":
    # --- Re-pasting the placeholder functions to make the script self-contained ---
    def parse_simulated_log(log_filepath: str) -> Optional[List[Dict[str, Any]]]: return None
    def parse_real_world_log(log_filepath: str) -> Optional[List[Dict[str, Any]]]: return None
    def generate_controlled_tests_from_logs(logs_directory: str, parser_func: Callable[[str], Optional[List[Dict[str, Any]]]]) -> Dict[str, Any]: return {}
    def analyze_conversation_log(client: AzureOpenAI, test_plan: str, log_filepath: str, original_log_content: Optional[str] = None) -> str: return "SKIPPED"
    
    main()