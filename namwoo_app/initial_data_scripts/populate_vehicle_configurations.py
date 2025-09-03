# initial_data_scripts/populate_vehicle_configurations.py
import json
import os
import sys
import logging

# --- Python Path Setup ---
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, '..'))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
print(f"INFO: [populate_vehicle_configurations] Project root added to sys.path: {PROJECT_ROOT}")
# --- End Python Path Setup ---

# --- Load .env ---
from dotenv import load_dotenv
DOTENV_PATH = os.path.join(PROJECT_ROOT, '.env')
if os.path.exists(DOTENV_PATH):
    print(f"INFO: [populate_vehicle_configurations] Loading .env from {DOTENV_PATH}")
    load_dotenv(DOTENV_PATH)
else:
    print(f"WARNING: [populate_vehicle_configurations] .env file not found at {DOTENV_PATH}. Using environment variables if set elsewhere.")
# --- End .env loading ---

try:
    from __init__ import create_app, db
    from models.product import VehicleBatteryFitment as VehicleConfigModel 
except ImportError as e:
    print(f"CRITICAL ERROR: [populate_vehicle_configurations] Failed to import application components: {e}")
    print("  Current sys.path:", sys.path)
    print("  Ensure that:")
    print(f"  1. Your project root is correctly identified as: {PROJECT_ROOT}")
    print(f"  2. An '__init__.py' file exists at the project root ('{PROJECT_ROOT}/__init__.py') containing 'create_app' and 'db'.")
    print(f"  3. The 'utils' and 'models' directories exist directly under '{PROJECT_ROOT}'.")
    sys.exit(1)

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(name)s: %(message)s')
# --- MODIFICATION START: Corrected the typo from getLogger to logging.getLogger ---
logger = logging.getLogger(__name__)
# --- MODIFICATION END ---

JSON_DATA_FILE = os.path.join(SCRIPT_DIR, 'vehicle_fitments_data.json') 

def populate_vehicle_configurations():
    logger.info(f"Populating 'vehicle_battery_fitment' (vehicle configurations) table from: {JSON_DATA_FILE}")

    if not os.path.exists(JSON_DATA_FILE):
        logger.error(f"ABORTING: Data file not found: {JSON_DATA_FILE}")
        return

    flask_app = create_app()
    with flask_app.app_context():
        session = db.session

        try:
            with open(JSON_DATA_FILE, 'r', encoding='utf-8') as f:
                fitments_data_list = json.load(f)
        except Exception as e:
            logger.error(f"Error reading or parsing {JSON_DATA_FILE}: {e}")
            return

        unique_vehicle_configs_to_process = {}
        for fit_entry in fitments_data_list:
            key_make = fit_entry.get('vehicle_make')
            key_model = fit_entry.get('vehicle_model')
            key_year_start = fit_entry.get('year_start')
            key_year_end = fit_entry.get('year_end')
            key_engine_details = fit_entry.get('engine_details')
            key_notes = fit_entry.get('notes')

            if not all([key_make, key_model, key_year_start is not None, key_year_end is not None]):
                logger.warning(f"Skipping fitment entry due to missing key vehicle data: {fit_entry}")
                continue
            
            # --- MODIFICATION START: Made the uniqueness key more robust ---
            config_key_tuple = (
                key_make,
                key_model,
                str(key_year_start),
                str(key_year_end),
                key_engine_details or '__NONE__' # Use a placeholder for None
            )
            # --- MODIFICATION END ---
                
            if config_key_tuple not in unique_vehicle_configs_to_process:
                data_for_model = {
                    "vehicle_make": key_make,
                    "vehicle_model": key_model,
                    "year_start": key_year_start,
                    "year_end": key_year_end,
                }
                if key_engine_details is not None:
                    data_for_model["engine_details"] = key_engine_details
                if key_notes is not None:
                    data_for_model["notes"] = key_notes
                unique_vehicle_configs_to_process[config_key_tuple] = data_for_model
            
        added_count = 0
        updated_count = 0
        error_count = 0
        logger.info(f"Found {len(unique_vehicle_configs_to_process)} unique vehicle configurations to process.")

        # --- MODIFICATION START: Resilient loop with individual commits ---
        for veh_config_data in unique_vehicle_configs_to_process.values():
            try:
                filter_args = {
                    'vehicle_make': veh_config_data['vehicle_make'],
                    'vehicle_model': veh_config_data['vehicle_model'],
                    'year_start': veh_config_data['year_start'],
                    'year_end': veh_config_data['year_end']
                }
                
                if "engine_details" in veh_config_data and veh_config_data.get('engine_details') is not None:
                    filter_args['engine_details'] = veh_config_data.get('engine_details')
                else:
                    filter_args['engine_details'] = None

                existing_config = session.query(VehicleConfigModel).filter_by(**filter_args).first()

                if not existing_config:
                    model_fields = {key: veh_config_data[key] for key in veh_config_data if hasattr(VehicleConfigModel, key)}
                    new_config = VehicleConfigModel(**model_fields)
                    session.add(new_config)
                    session.commit() # Commit after each ADD
                    added_count += 1
                else:
                    changed = False
                    if "notes" in veh_config_data and existing_config.notes != veh_config_data.get('notes'):
                        existing_config.notes = veh_config_data.get('notes')
                        changed = True
                    
                    if changed:
                        session.commit() # Commit after each UPDATE
                        updated_count += 1
                        
            except Exception as e_inner:
                error_count += 1
                logger.error(f"Error processing vehicle config data '{veh_config_data}': {e_inner}")
                session.rollback() # Rollback the single failed operation and continue
        # --- MODIFICATION END ---
        
        logger.info("--- Vehicle Configuration Summary ---")
        logger.info(f"Successfully added: {added_count} new vehicle configurations.")
        logger.info(f"Successfully updated: {updated_count} existing ones.")
        logger.info(f"Errors encountered: {error_count}.")

    logger.info("Vehicle configuration population script finished.")

if __name__ == "__main__":
    populate_vehicle_configurations()