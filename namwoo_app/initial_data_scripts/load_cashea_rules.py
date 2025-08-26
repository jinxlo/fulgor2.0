import csv
import os
import sys
from decimal import Decimal
import logging

# --- Python Path Setup ---
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, '..'))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
# --- End Python Path Setup ---

from dotenv import load_dotenv
DOTENV_PATH = os.path.join(PROJECT_ROOT, '.env')
if os.path.exists(DOTENV_PATH):
    load_dotenv(DOTENV_PATH)

try:
    from __init__ import create_app, db
    from models.financing_rule import FinancingRule
    from sqlalchemy import text
except ImportError as e:
    print(f"CRITICAL ERROR: Failed to import application components: {e}")
    sys.exit(1)

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(name)s: %(message)s')
logger = logging.getLogger(__name__)

def main():
    """
    Loads Cashea financing rules from a CSV file into the database
    within the Flask application context.
    """
    csv_file_path = os.path.join(PROJECT_ROOT, 'data', 'fulgor cashea - Sheet1.csv')
    logger.info(f"Reading Cashea rules from: {csv_file_path}")

    if not os.path.exists(csv_file_path):
        logger.error(f"ABORTING: Data file not found: {csv_file_path}")
        return

    flask_app = create_app()
    with flask_app.app_context():
        session = db.session
        try:
            with open(csv_file_path, mode='r', encoding='utf-8') as infile:
                reader = csv.DictReader(infile)
                
                # Clear existing Cashea rules to avoid duplicates
                logger.info("Deleting existing Cashea rules...")
                session.execute(text("DELETE FROM financing_rules WHERE provider = 'Cashea'"))
                
                rules_to_add = []
                for row in reader:
                    level = row.get('Nivel cashea', '').strip()
                    initial_pct_str = row.get('Porcentaje inicial normal', '0').replace('%', '').strip()
                    installments_str = row.get('Cuotas normales', '0').strip()
                    discount_pct_str = row.get('porcentaje de descuento', '0').replace('%', '').strip()

                    if not all([level, initial_pct_str, installments_str, discount_pct_str]):
                        logger.warning(f"Skipping row due to missing data: {row}")
                        continue

                    try:
                        initial_pct = Decimal(initial_pct_str) / 100
                        discount_pct = Decimal(discount_pct_str) / 100
                        installments = int(installments_str)
                    except (ValueError, TypeError) as e:
                        logger.warning(f"Skipping row due to data conversion error: {row} - Error: {e}")
                        continue

                    rule = FinancingRule(
                        provider='Cashea',
                        level_name=level,
                        initial_payment_percentage=initial_pct,
                        installments=installments,
                        provider_discount_percentage=discount_pct
                    )
                    rules_to_add.append(rule)
                    logger.info(f"Staging rule for {level}...")

            if rules_to_add:
                session.add_all(rules_to_add)
                session.commit()
                logger.info(f"\nSuccessfully loaded {len(rules_to_add)} Cashea rules into the database.")
            else:
                logger.warning("No valid rules found in the CSV file to load.")

        except Exception as e:
            session.rollback()
            logger.error(f"\nAn error occurred: {e}", exc_info=True)
        
if __name__ == '__main__':
    main()