# NAMWOO/services/product_service.py (OPTIMIZED VERSION)
import logging
import re
import time
from typing import List, Dict, Any, Optional, Tuple
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation as InvalidDecimalOperation

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import and_, text, or_, func
from thefuzz import process as fuzzy_process

from models.product import Product, VehicleBatteryFitment
from models.financing_rule import FinancingRule
from utils import db_utils
from services import ai_service
from services.vehicle_aliases import MAKE_ALIASES

logger = logging.getLogger(__name__)

# --- CACHING AND CONFIGURATION ---
_vehicle_makes_cache: Dict[str, Any] = {"data": None, "timestamp": 0}
CACHE_DURATION_SECONDS = 3600  # Cache for 1 hour
FUZZY_MATCH_CONFIDENCE_THRESHOLD = 85 # Minimum similarity score (out of 100) to be considered a match

# --- CACHE HELPER FUNCTION ---
def _get_all_makes_cached(db_session: Session) -> List[str]:
    """
    Fetches a distinct list of all vehicle makes from the DB and caches it.
    """
    current_time = time.time()
    if _vehicle_makes_cache["data"] and (current_time - _vehicle_makes_cache["timestamp"] < CACHE_DURATION_SECONDS):
        return _vehicle_makes_cache["data"]

    try:
        logger.info("Refreshing vehicle makes cache from database...")
        results = db_session.query(VehicleBatteryFitment.vehicle_make).distinct().all()
        # The query returns a list of tuples, so we extract the first element of each
        makes = sorted([make[0] for make in results if make[0]], key=len, reverse=True)
        
        _vehicle_makes_cache["data"] = makes
        _vehicle_makes_cache["timestamp"] = current_time
        logger.info(f"Successfully cached {len(makes)} vehicle makes.")
        return makes
    except Exception as e:
        logger.exception("Failed to query and cache vehicle makes.")
        return []

# --- DATA-DRIVEN MAKE FINDER (FALLBACK LOGIC) ---
def _find_make_from_query(db_session: Session, user_query: str) -> Optional[str]:
    """
    Identifies the vehicle make from a user query using a data-driven approach.
    1. Checks for known aliases.
    2. Falls back to fuzzy matching against all makes in the DB.
    """
    all_makes = _get_all_makes_cached(db_session)
    query_lower = user_query.lower()

    # 1. Exact match via aliases (most reliable)
    # Sort by length to match "alfa romeo" before "alfa"
    sorted_aliases = sorted(MAKE_ALIASES.keys(), key=len, reverse=True)
    for alias in sorted_aliases:
        if alias in query_lower:
            canonical_make = MAKE_ALIASES[alias]
            logger.info(f"Data-driven search: Found make '{canonical_make}' via alias '{alias}'.")
            return canonical_make

    # 2. Fuzzy match against canonical makes (for typos)
    # `extractOne` finds the best match from a list of choices
    best_match = fuzzy_process.extractOne(query_lower, all_makes)
    if best_match:
        found_make, score = best_match
        if score >= FUZZY_MATCH_CONFIDENCE_THRESHOLD:
            logger.info(f"Data-driven search: Found make '{found_make}' via fuzzy match with score {score}%.")
            return found_make
        else:
            logger.warning(f"Fuzzy match found '{found_make}' but score ({score}%) was below threshold.")

    logger.warning(f"Data-driven search could not confidently identify a make in query: '{user_query}'.")
    return None


# --- THE ULTIMATE MULTI-TIERED SEARCH WORKFLOW ---
def find_batteries_for_vehicle(
    db_session: Session,
    user_query: str,
) -> Dict[str, Any]:
    """
    Orchestrates a multi-tiered, resilient search:
    1. TIER 1 (Fast Path): Use AI to parse the query into structured data.
    2. TIER 2 (Smart Fallback): If AI fails, use a data-driven approach with aliasing and
       fuzzy logic to identify the vehicle make.
    3. Execute the two-stage DB filter with the identified vehicle data.
    """
    if not user_query:
        return {}

    parsed_vehicle = None

    # TIER 1: Attempt AI parsing first
    ai_parsed = ai_service.parse_vehicle_query_to_structured(user_query)
    if ai_parsed and ai_parsed.get("make") and ai_parsed.get("model"):
        logger.info("Search Tier 1 (AI Parse) SUCCEEDED. Using AI-structured data.")
        # Normalize the make using our alias map
        make_lower = ai_parsed["make"].lower()
        ai_parsed["make"] = MAKE_ALIASES.get(make_lower, ai_parsed["make"])
        parsed_vehicle = ai_parsed
    else:
        logger.warning("Search Tier 1 (AI Parse) FAILED. Initiating Tier 2 (Data-Driven Fallback).")
        # TIER 2: Data-Driven Fallback
        found_make = _find_make_from_query(db_session, user_query)
        if found_make:
            # We found a make! Now, let's reconstruct the rest of the query.
            # Remove the found make (and its aliases) from the query to isolate the model/year/engine
            remaining_query = user_query
            # Also remove aliases to clean the model string
            all_aliases_for_make = [k for k, v in MAKE_ALIASES.items() if v == found_make] + [found_make]
            for term in sorted(all_aliases_for_make, key=len, reverse=True):
                remaining_query = re.sub(r'\b' + re.escape(term) + r'\b', '', remaining_query, flags=re.IGNORECASE)
            
            # Use the remaining string to re-parse with the AI, but now we guide it.
            # This is more reliable than complex regex.
            re_parsed = ai_service.parse_vehicle_query_to_structured(remaining_query.strip())
            
            parsed_vehicle = {
                "make": found_make,
                "model": re_parsed.get("model") if re_parsed else remaining_query.strip(),
                "year": re_parsed.get("year") if re_parsed else None,
                "engine_details": re_parsed.get("engine_details") if re_parsed else None
            }
            logger.info(f"Tier 2 SUCCEEDED. Reconstructed vehicle data: {parsed_vehicle}")
        else:
             logger.error(f"All search tiers FAILED for query: '{user_query}'.")
             return {"status": "not_found", "message": "No pudimos determinar el vehículo que buscas."}
    
    # --- EXECUTION STAGE (Uses data from either Tier 1 or Tier 2) ---
    try:
        query_builder = db_session.query(VehicleBatteryFitment)

        if parsed_vehicle.get("make"):
            query_builder = query_builder.filter(VehicleBatteryFitment.vehicle_make.ilike(parsed_vehicle["make"]))

        if parsed_vehicle.get("model"):
            model_keywords = [kw for kw in re.split(r'\s+|-', parsed_vehicle["model"]) if len(kw) > 1]
            if model_keywords:
                conditions = [VehicleBatteryFitment.vehicle_model.op('~*')(r'\y{}\y'.format(re.escape(keyword))) for keyword in model_keywords]
                query_builder = query_builder.filter(and_(*conditions))
        
        if parsed_vehicle.get("year"):
            year = parsed_vehicle["year"]
            query_builder = query_builder.filter(and_(
                VehicleBatteryFitment.year_start <= year,
                or_(VehicleBatteryFitment.year_end >= year, VehicleBatteryFitment.year_end.is_(None))
            ))

        candidate_fitments = query_builder.limit(10).all()
        logger.info(f"Stage 1 DB query found {len(candidate_fitments)} candidate(s) for: {parsed_vehicle}")

    except Exception as e:
        logger.exception(f"Stage 1 DB search failed for query '{user_query}': {e}")
        return {}

    # --- Stage 2: Secondary In-Memory Filtering (Precise) ---
    final_fitments = candidate_fitments
    if len(candidate_fitments) > 1 and parsed_vehicle.get("engine_details"):
        engine_keywords_str = parsed_vehicle["engine_details"].lower()
        engine_keywords = set(re.findall(r'\w+', engine_keywords_str))
        logger.info(f"Stage 2 Filtering: Applying engine keywords {engine_keywords} to {len(candidate_fitments)} candidates.")
        
        filtered_results = []
        for fitment in candidate_fitments:
            searchable_text = " ".join(filter(None, [fitment.vehicle_model, fitment.engine_details, fitment.notes])).lower()
            if all(keyword in searchable_text for keyword in engine_keywords):
                filtered_results.append(fitment)
        
        if filtered_results:
            logger.info(f"Stage 2 Filtering: Reduced candidates to {len(filtered_results)} final fitment(s).")
            final_fitments = filtered_results
        else:
            logger.warning("Stage 2 Filtering: Engine details eliminated all candidates. Proceeding with original list.")

    # --- Final Result Handling ---
    if not final_fitments:
        return {"status": "not_found", "message": "No pudimos encontrar la información para tu vehículo."}

    if len(final_fitments) == 1:
        return _format_success_response(db_session, final_fitments[0])
    
    if len(final_fitments) > 1:
        # Intelligent Ambiguity Resolution
        fitment_ids = [f.fitment_id for f in final_fitments]
        fitments_with_batteries = db_session.query(VehicleBatteryFitment).options(joinedload(VehicleBatteryFitment.compatible_battery_products)).filter(VehicleBatteryFitment.fitment_id.in_(fitment_ids)).all()

        if not fitments_with_batteries or not any(f.compatible_battery_products for f in fitments_with_batteries):
            return {"status": "not_found", "message": "Encontramos tu vehículo, pero no tenemos baterías compatibles registradas."}

        first_battery_set = frozenset(p.id for p in fitments_with_batteries[0].compatible_battery_products)
        if not first_battery_set:
            return _format_clarification_response(final_fitments)

        if all(frozenset(p.id for p in f.compatible_battery_products) == first_battery_set for f in fitments_with_batteries[1:]):
            return _format_merged_success_response(fitments_with_batteries)
        else:
            return _format_clarification_response(final_fitments)

    return {}


def _format_merged_success_response(fitments: List[VehicleBatteryFitment]) -> Dict[str, Any]:
    # ... (this function is unchanged) ...
    make = fitments[0].vehicle_make
    models = sorted(list(set(f.vehicle_model for f in fitments)))
    model_str = " / ".join(models)
    
    min_year = min(f.year_start for f in fitments)
    max_year_ends = [f.year_end for f in fitments if f.year_end is not None]
    max_year = max(max_year_ends) if max_year_ends else None
    year_range = f"{min_year}-{max_year or 'Presente'}"
    
    vehicle_key = f"{make} {model_str} ({year_range})"
    
    battery_list = []
    seen_battery_ids = set()
    for battery in fitments[0].compatible_battery_products:
        if battery.id not in seen_battery_ids:
            battery_list.append({
                "brand": battery.brand, "model_code": battery.model_code,
                "warranty_info": f"{battery.warranty_months} meses" if battery.warranty_months else "No especificada",
                "price_regular": float(battery.price_regular) if battery.price_regular is not None else None,
                "price_discount_fx": float(battery.price_discount_fx) if battery.price_discount_fx is not None else None,
            })
            seen_battery_ids.add(battery.id)
            
    return {"status": "success", "results": {vehicle_key: battery_list}}


def _format_clarification_response(fitments: List[VehicleBatteryFitment]) -> Dict[str, Any]:
    # ... (this function is unchanged) ...
    options_map = {}
    for fitment in fitments:
        year_range = f"{fitment.year_start}-{fitment.year_end or 'Presente'}"
        key = f"{fitment.vehicle_make} {fitment.vehicle_model} ({year_range})"
        if fitment.engine_details:
             key = f"{fitment.vehicle_make} {fitment.vehicle_model} {fitment.engine_details} ({year_range})"
        if key not in options_map:
            options_map[key] = fitment

    return {
        "status": "clarification_needed",
        "message": "Encontré algunas versiones que podrían coincidir. Para darte la batería correcta, por favor selecciona tu vehículo:",
        "options": list(options_map.keys())
    }


def _format_success_response(db_session: Session, fitment: VehicleBatteryFitment) -> Dict[str, Any]:
    # ... (this function is unchanged) ...
    fitment_with_batteries = db_session.query(VehicleBatteryFitment).options(
        joinedload(VehicleBatteryFitment.compatible_battery_products)
    ).get(fitment.fitment_id)
    
    if not fitment_with_batteries or not fitment_with_batteries.compatible_battery_products:
        logger.warning(f"Fitment {fitment.fitment_id} found but has no linked batteries.")
        return {"status": "not_found", "message": "Encontramos tu vehículo, pero no tenemos baterías compatibles registradas."}

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
    # ... (this function is unchanged) ...
    session: Session,
    battery_id: str,
    battery_data: Dict[str, Any]
) -> Tuple[bool, str]:
    if not battery_id:
        return False, "Missing battery_id."
    if not battery_data or not isinstance(battery_data, dict):
        return False, "Missing or invalid battery_data."
    log_prefix = f"BatteryProduct DB Upsert (ID='{battery_id}'):"
    try:
        entry = session.query(Product).filter(Product.id == battery_id).first()
        action_taken = ""
        updated_fields_details = []
        if entry:
            logger.info(f"{log_prefix} Found existing battery. Checking for updates.")
            action_taken = "updated"
            changed = False
            for key, new_value in battery_data.items():
                if hasattr(entry, key):
                    current_value = getattr(entry, key)
                    if key in ["price_regular", "price_discount_fx"]:
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
        else:
            logger.info(f"{log_prefix} New battery. Adding to DB.")
            action_taken = "added_new"
            init_data = battery_data.copy()
            init_data['id'] = battery_id
            if "price_regular" in init_data and init_data["price_regular"] is not None:
                try:
                    init_data["price_regular"] = Decimal(str(init_data["price_regular"])).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
                except (InvalidDecimalOperation, TypeError):
                    logger.error(f"{log_prefix} Invalid decimal for new product price_regular: {init_data['price_regular']}. Setting to None.")
                    init_data["price_regular"] = None
            if "price_discount_fx" in init_data and init_data["price_discount_fx"] is not None:
                try:
                    init_data["price_discount_fx"] = Decimal(str(init_data["price_discount_fx"])).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
                except (InvalidDecimalOperation, TypeError):
                    logger.warning(f"{log_prefix} Invalid decimal for new product price_discount_fx: {init_data['price_discount_fx']}. Setting to None.")
                    init_data["price_discount_fx"] = None
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

# --- [The rest of the functions (update_battery_product_prices, etc.) remain unchanged] ---
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

def get_cashea_financing_options(
    session: Session, 
    product_price: float,
    user_level: str,
    apply_discount: bool = False
) -> Dict[str, Any]:
    try:
        price = Decimal(str(product_price))
        rule = session.query(FinancingRule).filter_by(provider='Cashea', level_name=user_level).first()
        if not rule:
            logger.error(f"No financing rule found for Cashea and level '{user_level}'.")
            return {"status": "error", "message": f"No se encontró una regla de financiamiento para Cashea Nivel '{user_level}'."}
        base_price_for_financing = price
        discount_amount = Decimal('0.00')
        discount_applied_percent = 0.0
        if apply_discount and rule.provider_discount_percentage is not None and rule.provider_discount_percentage > 0:
            logger.info(f"Executing DIVISAS discount logic for {user_level}: Applying discount to total price FIRST.")
            discount_amount = (price * rule.provider_discount_percentage).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            base_price_for_financing = price - discount_amount
            discount_applied_percent = float(rule.provider_discount_percentage * 100)
        initial_payment_final = (base_price_for_financing * rule.initial_payment_percentage).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        remaining_balance = base_price_for_financing - initial_payment_final
        if rule.installments and rule.installments > 0:
            installment_amount = (remaining_balance / rule.installments).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        else:
            installment_amount = remaining_balance.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP) if remaining_balance > 0 else Decimal('0.00')
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

def update_financing_rules(session: Session, provider_name: str, new_rules: List[Dict[str, Any]]) -> Tuple[bool, Dict[str, int]]:
    summary = {"deleted": 0, "inserted": 0}
    deleted_rows_count = session.query(FinancingRule).filter_by(provider=provider_name).delete(synchronize_session=False)
    summary["deleted"] = deleted_rows_count
    logger.info(f"Deleted {deleted_rows_count} old financing rules for provider '{provider_name}'.")
    inserted_count = 0
    for rule_data in new_rules:
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