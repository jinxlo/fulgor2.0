import json
import os
import sys
import logging

# --- Python Path Setup ---
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, '..'))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
# --- End Python Path Setup ---

try:
    from utils.product_utils import generate_battery_product_id
except ImportError as e:
    print(f"CRITICAL ERROR: Failed to import 'generate_battery_product_id' from 'utils.product_utils'.")
    print(f"  Ensure this script is in 'initial_data_scripts/' and the 'utils/' directory is at the project root: {PROJECT_ROOT}")
    print(f"  Error details: {e}")
    sys.exit(1)


# Basic logging setup
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

# --- FILE PATHS ---
BATTERIES_MASTER_FILE = os.path.join(SCRIPT_DIR, 'batteries_master_data.json')
VEHICLE_FITMENTS_FILE = os.path.join(SCRIPT_DIR, 'vehicle_fitments_data.json')

def diagnose_data_integrity():
    """
    Cross-references vehicle fitment data against the master battery list
    to find battery models that are referenced but do not exist.
    """
    if not os.path.exists(BATTERIES_MASTER_FILE):
        logger.error(f"Master battery data file not found at: {BATTERIES_MASTER_FILE}")
        return
    if not os.path.exists(VEHICLE_FITMENTS_FILE):
        logger.error(f"Vehicle fitment data file not found at: {VEHICLE_FITMENTS_FILE}")
        return

    # 1. Load all master battery IDs into a set for fast lookup
    master_battery_ids = set()
    try:
        with open(BATTERIES_MASTER_FILE, 'r', encoding='utf-8') as f:
            master_data = json.load(f)
            for battery in master_data:
                battery_id = generate_battery_product_id(battery.get('brand'), battery.get('model_code'))
                if battery_id:
                    master_battery_ids.add(battery_id)
        logger.info(f"Loaded {len(master_battery_ids)} unique battery IDs from {BATTERIES_MASTER_FILE}")
    except Exception as e:
        logger.error(f"Failed to read or parse master battery data: {e}")
        return

    # 2. Iterate through vehicle fitments and check each compatible battery
    mismatch_count = 0
    total_links_checked = 0
    mismatched_vehicles = set()
    try:
        with open(VEHICLE_FITMENTS_FILE, 'r', encoding='utf-8') as f:
            fitment_data = json.load(f)
            logger.info(f"Checking {len(fitment_data)} vehicle fitment entries from {VEHICLE_FITMENTS_FILE}...\n")
            
            for i, vehicle in enumerate(fitment_data):
                vehicle_desc = f"{vehicle.get('vehicle_make')} {vehicle.get('vehicle_model')} ({vehicle.get('year_start')}-{vehicle.get('year_end')})"
                compatible_batteries = vehicle.get('compatible_battery_model_codes', [])
                
                if not compatible_batteries:
                    continue

                for battery_link in compatible_batteries:
                    total_links_checked += 1
                    brand = battery_link.get('brand')
                    model_code = battery_link.get('model_code')
                    
                    if not brand or not model_code:
                        logger.warning(f"[Malformed Link] Vehicle '{vehicle_desc}' (entry #{i+1}) has an invalid link object: {battery_link}")
                        mismatch_count += 1
                        mismatched_vehicles.add(vehicle_desc)
                        continue

                    # Generate the ID exactly as the populating script would
                    linked_battery_id = generate_battery_product_id(brand, model_code)

                    if linked_battery_id not in master_battery_ids:
                        logger.error(f"[MISMATCH] Vehicle '{vehicle_desc}' (entry #{i+1}) references a non-existent battery.")
                        logger.error(f"    -> Details: Brand='{brand}', Model='{model_code}'")
                        logger.error(f"    -> Generated ID: '{linked_battery_id}' was not found in the master battery list.\n")
                        mismatch_count += 1
                        mismatched_vehicles.add(vehicle_desc)

    except Exception as e:
        logger.error(f"Failed to read or parse vehicle fitment data: {e}")
        return

    logger.info("--- Diagnosis Summary ---")
    logger.info(f"Total vehicle entries checked: {len(fitment_data)}")
    logger.info(f"Total vehicle-battery links checked: {total_links_checked}")
    logger.info(f"Total vehicles with at least one mismatch: {len(mismatched_vehicles)}")
    logger.info(f"Total individual mismatches found: {mismatch_count}")
    
    if mismatch_count == 0:
        logger.info("\nSUCCESS: All battery references in the fitment data exist in the master list.")
    else:
        logger.warning(f"\nACTION REQUIRED: {mismatch_count} battery references in '{os.path.basename(VEHICLE_FITMENTS_FILE)}' must be corrected to match '{os.path.basename(BATTERIES_MASTER_FILE)}'.")
        logger.warning("The 'populate_battery_to_vehicle_links.py' script is skipping these mismatched entries, which is the reason for your empty search results.")

if __name__ == '__main__':
    diagnose_data_integrity()
