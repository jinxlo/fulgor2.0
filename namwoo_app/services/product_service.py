# NAMWOO/services/product_service.py (OPTIMIZED VERSION)
import logging
import re
from typing import List, Dict, Any, Optional, Tuple
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation as InvalidDecimalOperation

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import and_, text, or_

from models.product import Product, VehicleBatteryFitment
from models.financing_rule import FinancingRule
from utils import db_utils
# --- MODIFICATION: The AI service is now central to our strategy ---
from services import ai_service

logger = logging.getLogger(__name__)


# --- REMOVED: _get_candidate_fitments is no longer needed ---
# The old broad, unreliable search is replaced by a precise, filtered search.


# --- THE NEW OPTIMIZED WORKFLOW ---
def find_batteries_for_vehicle(
    db_session: Session,
    user_query: str,
) -> Dict[str, Any]:
    """
    Orchestrates the new "Parse then Filter" search flow:
    1. Use the AI service to parse the user's query into structured data (make, model, year).
    2. Build a precise, filtered database query using this structured data.
    3. If results are clear, return them. If they are ambiguous, ask the user to clarify.
    """
    if not user_query:
        return {}

    # 1. Parse the user's query into structured data.
    # This is the most important step. We let the AI do what it's best at.
    parsed_vehicle = ai_service.parse_vehicle_query_to_structured(user_query)

    if not parsed_vehicle or not parsed_vehicle.get("make"):
        logger.warning(f"AI could not parse a vehicle make from query: '{user_query}'. Cannot proceed.")
        # We can't search without at least a make.
        # The response here should eventually be handled by the main conversation logic.
        return {}

    # 2. Build a precise, filtered database query.
    try:
        query_builder = db_session.query(VehicleBatteryFitment)

        # --- THE MAKE GUARDRAIL ---
        # This is a hard filter. Non-negotiable.
        make = parsed_vehicle["make"]
        query_builder = query_builder.filter(VehicleBatteryFitment.vehicle_make.ilike(make))
        logger.info(f"Applying MAKE guardrail: '{make}'")

        # --- MODEL KEYWORD FILTER (OR logic) ---
        # We search for models that contain ANY of the keywords from the parsed model.
        if parsed_vehicle.get("model"):
            model_keywords = [kw for kw in re.split(r'\s+|-', parsed_vehicle["model"]) if len(kw) > 1]
            if model_keywords:
                # Create a list of individual ILIKE conditions
                conditions = [VehicleBatteryFitment.vehicle_model.ilike(f'%{keyword}%') for keyword in model_keywords]
                # Apply them all at once with an OR condition
                query_builder = query_builder.filter(or_(*conditions))
                logger.info(f"Filtering by MODEL keywords (OR): {model_keywords}")

        # --- YEAR FILTER ---
        # Check if the parsed year falls within the fitment's start/end range.
        if parsed_vehicle.get("year"):
            year = parsed_vehicle["year"]
            query_builder = query_builder.filter(
                and_(
                    VehicleBatteryFitment.year_start <= year,
                    or_(
                        VehicleBatteryFitment.year_end >= year,
                        VehicleBatteryFitment.year_end == None # Handle 'Present'
                    )
                )
            )
            logger.info(f"Filtering by YEAR: {year}")

        # Execute the precise query
        precise_fitments = query_builder.limit(10).all()
        logger.info(f"Precise query found {len(precise_fitments)} fitments for parsed data: {parsed_vehicle}")

    except Exception as e:
        logger.exception(f"Precise search failed for query '{user_query}': {e}")
        return {}

    # 3. Handle the results
    if not precise_fitments:
        # The specific vehicle wasn't found. This is a "clean" failure.
        return {"status": "not_found", "message": "No pudimos encontrar la información para tu vehículo."}

    if len(precise_fitments) == 1:
        # Perfect match! We found exactly one fitment.
        best_fitment = precise_fitments[0]
        logger.info(f"Found a single, confident match: ID {best_fitment.fitment_id}")
        return _format_success_response(db_session, best_fitment)
    
    # We found a few, highly-relevant options. Ask the user to choose.
    # This is much better than asking them to choose from a list of wrong makes.
    options_map = {}
    for fitment in precise_fitments:
        year_range = f"{fitment.year_start}-{fitment.year_end or 'Presente'}"
        key = f"{fitment.vehicle_make} {fitment.vehicle_model} ({year_range})"
        options_map[key] = fitment

    logger.info(f"Found multiple relevant options. Asking user for clarification.")
    return {
        "status": "clarification_needed",
        "message": "Encontré algunas versiones que podrían coincidir. Para darte la batería correcta, por favor selecciona tu vehículo:",
        "options": list(options_map.keys())
    }


def _format_success_response(db_session: Session, fitment: VehicleBatteryFitment) -> Dict[str, Any]:
    """Helper function to fetch batteries for a fitment and format the final response."""
    fitment_with_batteries = db_session.query(VehicleBatteryFitment).options(
        joinedload(VehicleBatteryFitment.compatible_battery_products)
    ).get(fitment.fitment_id)
    
    if not fitment_with_batteries or not fitment_with_batteries.compatible_battery_products:
        logger.warning(f"Fitment {fitment.fitment_id} found but has no linked batteries.")
        return {}

    battery_list = []
    for battery in fitment_with_batteries.compatible_battery_products:
        battery_list.append({
            "brand": battery.brand, "model_code": battery.model_code,
            "warranty_info": f"{battery.warranty_months} meses" if battery.warranty_months else "No especificada",
            "price_regular": float(battery.price_regular) if battery.price_regular is not None else None,
            "price_discount_fx": float(battery.price_discount_fx) if battery.price_discount_fx is not None else None,
        })
    
    year_range = f"{fitment.year_start}-{fitment.year_end or 'Presente'}"
    vehicle_key = f"{fitment.vehicle_make} {fitment.vehicle_model} ({year_range})"

    return {"status": "success", "results": {vehicle_key: battery_list}}


# --- Add/Update Battery Product ---
def add_or_update_battery_product(
    session: Session,
    battery_id: str,
    battery_data: Dict[str, Any]
) -> Tuple[bool, str]:
    """
    Adds a new battery product or updates an existing one.
    The Product model is now used exclusively for batteries.
    """
    if not battery_id:
        return False, "Missing battery_id."
    if not battery_data or not isinstance(battery_data, dict):
        return False, "Missing or invalid battery_data."

    log_prefix = f"BatteryProduct DB Upsert (ID='{battery_id}'):"

    try:
        entry = session.query(Product).filter(Product.id == battery_id).first()
        action_taken = ""
        updated_fields_details = []

        if entry: # Update existing battery
            logger.info(f"{log_prefix} Found existing battery. Checking for updates.")
            action_taken = "updated"
            changed = False
            for key, new_value in battery_data.items():
                if hasattr(entry, key):
                    current_value = getattr(entry, key)
                    # --- MODIFICATION START ---
                    if key in ["price_regular", "price_discount_fx"]:
                        # Handle None gracefully for price fields
                        new_decimal_value = None
                        if new_value is not None:
                            try:
                                new_decimal_value = Decimal(str(new_value)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
                            except (InvalidDecimalOperation, TypeError):
                                logger.warning(f"{log_prefix} Invalid decimal value for {key}: {new_value}. Setting to None.")
                                new_decimal_value = None
                        
                        if current_value != new_decimal_value:
                            setattr(entry, key, new_decimal_value)
                            changed = True
                            updated_fields_details.append(f"{key}: {current_value} -> {new_decimal_value}")
                    # --- MODIFICATION END ---
                    elif current_value != new_value:
                        setattr(entry, key, new_value)
                        changed = True
                        updated_fields_details.append(f"{key}: {current_value} -> {new_value}")
            
            if not changed:
                action_taken = "skipped_no_change"
                logger.info(f"{log_prefix} No changes detected. Skipping DB write.")
                return True, action_taken
            else:
                logger.info(f"{log_prefix} Changes detected: {'; '.join(updated_fields_details)}")
        else: # Add new battery
            logger.info(f"{log_prefix} New battery. Adding to DB.")
            action_taken = "added_new"
            init_data = battery_data.copy()
            init_data['id'] = battery_id
            
            # --- MODIFICATION START ---
            # Handle regular price
            if "price_regular" in init_data and init_data["price_regular"] is not None:
                try:
                    init_data["price_regular"] = Decimal(str(init_data["price_regular"])).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
                except (InvalidDecimalOperation, TypeError):
                    logger.error(f"{log_prefix} Invalid decimal for new product price_regular: {init_data['price_regular']}. Setting to None.")
                    init_data["price_regular"] = None

            # Handle discounted price
            if "price_discount_fx" in init_data and init_data["price_discount_fx"] is not None:
                try:
                    init_data["price_discount_fx"] = Decimal(str(init_data["price_discount_fx"])).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
                except (InvalidDecimalOperation, TypeError):
                    logger.warning(f"{log_prefix} Invalid decimal for new product price_discount_fx: {init_data['price_discount_fx']}. Setting to None.")
                    init_data["price_discount_fx"] = None
            # --- MODIFICATION END ---

            entry = Product(**init_data)
            session.add(entry)
        
        session.commit()
        logger.info(f"{log_prefix} Battery successfully {action_taken}.")
        return True, action_taken
    except SQLAlchemyError as db_exc:
        session.rollback()
        logger.error(f"{log_prefix} DB error during add/update: {db_exc}", exc_info=True)
        return False, f"db_sqlalchemy_error: {str(db_exc)}"
    except Exception as exc:
        session.rollback()
        logger.exception(f"{log_prefix} Unexpected error processing: {exc}")
        return False, f"db_unexpected_error: {str(exc)}"

# --- Update Battery Prices ---
def update_battery_product_prices(
    session: Session,
    battery_product_id: str,
    new_price_regular: Optional[Decimal] = None,
    new_price_discount_fx: Optional[Decimal] = None
) -> Optional[Product]:
    if not battery_product_id:
        logger.warning("update_battery_product_prices: battery_product_id is required.")
        return None
    battery_product = session.query(Product).filter(Product.id == battery_product_id).first()
    if not battery_product:
        logger.warning(f"update_battery_product_prices: Battery Product with ID '{battery_product_id}' not found.")
        return None
    updated = False
    if new_price_regular is not None:
        if not isinstance(new_price_regular, Decimal): new_price_regular = Decimal(str(new_price_regular))
        price_reg_quantized = new_price_regular.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        if battery_product.price_regular != price_reg_quantized:
            battery_product.price_regular = price_reg_quantized
            updated = True
    if new_price_discount_fx is not None:
        if not isinstance(new_price_discount_fx, Decimal):
            new_price_discount_fx = Decimal(str(new_price_discount_fx))
        price_fx_quantized = new_price_discount_fx.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        if battery_product.price_discount_fx != price_fx_quantized:
            battery_product.price_discount_fx = price_fx_quantized
            updated = True
    if updated:
        try:
            session.commit()
            session.refresh(battery_product)
            logger.info(f"Prices successfully updated for Battery Product ID '{battery_product_id}'.")
            return battery_product
        except SQLAlchemyError as e:
            session.rollback()
            logger.exception(f"DB Error committing price updates for Battery Product ID '{battery_product_id}': {e}")
            return None
    else:
        logger.info(f"No price changes to apply for Battery Product ID '{battery_product_id}'.")
        return battery_product

def update_battery_price_or_stock(
    session: Session,
    identifier_type: str,
    identifier_value: str,
    new_price: Optional[Decimal] = None,
    new_stock: Optional[int] = None
) -> bool:
    if identifier_type == 'product_id':
        battery = session.query(Product).filter(Product.id == str(identifier_value)).first()
    elif identifier_type == 'model_code':
        battery = session.query(Product).filter(Product.model_code.ilike(str(identifier_value))).first()
    else:
        logger.warning(f"update_battery_price_or_stock: Unknown identifier_type {identifier_type}")
        return False
    if not battery:
        logger.warning(f"update_battery_price_or_stock: Battery not found for {identifier_type} '{identifier_value}'")
        return False
    updated = False
    if new_price is not None:
        if not isinstance(new_price, Decimal):
            try: new_price = Decimal(str(new_price))
            except InvalidDecimalOperation:
                logger.warning(f"update_battery_price_or_stock: Invalid price value '{new_price}' for {identifier_value}")
                return False
        price_q = new_price.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        if battery.price_regular != price_q:
            battery.price_regular = price_q
            updated = True
    if new_stock is not None:
        try: stock_int = int(new_stock)
        except (TypeError, ValueError):
            logger.warning(f"update_battery_price_or_stock: Invalid stock value '{new_stock}' for {identifier_value}")
            return False
        if battery.stock != stock_int:
            battery.stock = stock_int
            updated = True
    return updated

def update_battery_fields_by_brand_and_model(
    session: Session,
    brand: str,
    model_code: str,
    fields_to_update: Dict[str, Any],
    return_changes: bool = False
) -> Any:
    if not brand or not model_code:
        logger.warning("update_battery_fields_by_brand_and_model: brand and model_code are required")
        return (False, {}) if return_changes else False
    battery = session.query(Product).filter(
        Product.brand.ilike(str(brand)),
        Product.model_code.ilike(str(model_code))
    ).first()
    if not battery:
        logger.warning(f"update_battery_fields_by_brand_and_model: Battery not found for brand '{brand}' and model_code '{model_code}'")
        return (False, {}) if return_changes else False
    if not fields_to_update:
        logger.info(f"update_battery_fields_by_brand_and_model: No fields to update for '{brand} {model_code}'")
        return (False, {}) if return_changes else False
    updated = False
    changes_dict = {}
    for field_name, new_value in fields_to_update.items():
        if field_name == 'brand': continue
        if not hasattr(battery, field_name):
            logger.warning(f"Product has no attribute '{field_name}'. Skipping update for '{brand} {model_code}'.")
            continue
        current_val = getattr(battery, field_name)
        try:
            if field_name in ["price_regular", "price_discount_fx"] and new_value is not None:
                typed_val = Decimal(str(new_value)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            elif field_name in ["warranty_months", "stock"] and new_value is not None:
                typed_val = int(float(new_value))
            else:
                typed_val = new_value
        except (InvalidDecimalOperation, ValueError, TypeError) as exc:
            logger.warning(f"Failed to cast value for field '{field_name}' on '{brand} {model_code}': {exc}")
            continue
        if current_val != typed_val:
            setattr(battery, field_name, typed_val)
            updated = True
            changes_dict[field_name] = {
                "from": str(current_val) if isinstance(current_val, Decimal) else current_val,
                "to": str(typed_val) if isinstance(typed_val, Decimal) else typed_val
            }
    if return_changes:
        return updated, changes_dict
    else:
        return updated

# --- Manage Vehicle Fitments ---
def add_vehicle_fitment_with_links(
    session: Session,
    fitment_data: Dict[str, Any],
    compatible_battery_ids: List[str]
) -> Optional[VehicleBatteryFitment]:
    if not fitment_data or not fitment_data.get("vehicle_make") or not fitment_data.get("vehicle_model"):
        logger.error("add_vehicle_fitment_with_links: Missing required fitment_data (make, model).")
        return None
    try:
        new_fitment = VehicleBatteryFitment(**fitment_data)
        if compatible_battery_ids:
            battery_products_to_link = session.query(Product).filter(Product.id.in_(compatible_battery_ids)).all()
            if len(battery_products_to_link) != len(set(compatible_battery_ids)):
                found_ids = {bp.id for bp in battery_products_to_link}
                missing_ids = set(compatible_battery_ids) - found_ids
                logger.warning(f"Could not find all battery IDs for linking. Missing: {missing_ids}")
            new_fitment.compatible_battery_products = battery_products_to_link
        session.add(new_fitment)
        session.commit()
        session.refresh(new_fitment)
        logger.info(f"Added vehicle fitment ID {new_fitment.fitment_id} for {new_fitment.vehicle_make} {new_fitment.vehicle_model}")
        return new_fitment
    except SQLAlchemyError as db_exc:
        session.rollback()
        logger.exception(f"DB Error adding vehicle fitment: {db_exc}")
        return None
    except Exception as exc:
        session.rollback()
        logger.exception(f"Unexpected error adding vehicle fitment: {exc}")
        return None

def get_battery_product_by_id(session: Session, battery_product_id: str) -> Optional[Dict[str, Any]]:
    if not battery_product_id:
        return None
    battery = session.query(Product).filter(Product.id == battery_product_id).first()
    if battery:
        result = battery.to_dict()
        result['llm_formatted_message'] = battery.format_for_llm()
        return result
    return None

# --- Cashea Financing Logic ---
def get_cashea_financing_options(
    session: Session, 
    product_price: float,
    user_level: str,
    apply_discount: bool = False
) -> Dict[str, Any]:
    """
    Calculates a specific Cashea financing plan for a given product price and user level.
    - If apply_discount is False, it calculates the standard plan (for Bolivares).
    - If apply_discount is True, it applies the special discount logic (for Divisas).
    """
    try:
        price = Decimal(str(product_price))
        
        # Query for the specific rule for the user's level.
        rule = session.query(FinancingRule).filter_by(provider='Cashea', level_name=user_level).first()
        
        if not rule:
            logger.error(f"No financing rule found for Cashea and level '{user_level}'.")
            return {"status": "error", "message": f"No se encontró una regla de financiamiento para Cashea Nivel '{user_level}'."}

        base_price_for_financing = price
        discount_amount = Decimal('0.00')
        discount_applied_percent = 0.0

        if apply_discount and rule.provider_discount_percentage is not None and rule.provider_discount_percentage > 0:
            logger.info(f"Executing DIVISAS discount logic for {user_level}: Applying discount to total price FIRST.")
            # Divisas path: Discount is applied to the TOTAL product price first.
            discount_amount = (price * rule.provider_discount_percentage).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            base_price_for_financing = price - discount_amount
            discount_applied_percent = float(rule.provider_discount_percentage * 100)
        
        # All subsequent calculations are based on the (potentially discounted) price.
        initial_payment_final = (base_price_for_financing * rule.initial_payment_percentage).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        remaining_balance = base_price_for_financing - initial_payment_final
        
        if rule.installments and rule.installments > 0:
            installment_amount = (remaining_balance / rule.installments).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        else:
            installment_amount = remaining_balance.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP) if remaining_balance > 0 else Decimal('0.00')

        # The function now returns a single plan object, not a list.
        plan = {
            "level": rule.level_name,
            "initial_payment": float(initial_payment_final),
            "installments_count": rule.installments,
            "installment_amount": float(installment_amount),
            "total_final_price": float(base_price_for_financing.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)),
            "discount_applied_percent": discount_applied_percent,
            "total_discount_amount": float(discount_amount)
        }
            
        return {"status": "success", "original_product_price": product_price, "financing_plan": plan}
    except Exception as e:
        logger.error(f"Error calculating Cashea financing options: {e}", exc_info=True)
        return {"status": "error", "message": f"Error interno del servidor al calcular el financiamiento: {e}"}


# --- NEW FUNCTION FOR UPDATING FINANCING RULES ---
def update_financing_rules(session: Session, provider_name: str, new_rules: List[Dict[str, Any]]) -> Tuple[bool, Dict[str, int]]:
    """
    Deletes all existing rules for a given provider and inserts new ones.
    Returns a tuple of (success_status, summary_details).
    """
    summary = {"deleted": 0, "inserted": 0}
    
    # 1. Delete old rules for the specified provider
    deleted_rows_count = session.query(FinancingRule).filter_by(provider=provider_name).delete(synchronize_session=False)
    summary["deleted"] = deleted_rows_count
    logger.info(f"Deleted {deleted_rows_count} old financing rules for provider '{provider_name}'.")

    # 2. Insert new rules
    inserted_count = 0
    for rule_data in new_rules:
        # Basic validation
        if not all(k in rule_data for k in ['level_name', 'initial_payment_percentage', 'installments', 'provider_discount_percentage']):
            logger.warning(f"Skipping invalid rule data: {rule_data}")
            continue

        rule = FinancingRule(
            provider=provider_name,
            level_name=rule_data.get('level_name'),
            initial_payment_percentage=Decimal(str(rule_data.get('initial_payment_percentage'))),
            installments=int(rule_data.get('installments')),
            provider_discount_percentage=Decimal(str(rule_data.get('provider_discount_percentage')))
        )
        session.add(rule)
        inserted_count += 1
    
    summary["inserted"] = inserted_count
    logger.info(f"Staged {inserted_count} new financing rules for provider '{provider_name}'.")

    return True, summary
# --- END OF NEW FUNCTION ---