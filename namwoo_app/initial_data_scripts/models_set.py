--- START OF FILE models_set.py ---

import re
import json
import os

# -------- CONFIG -------- #
THIS_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = THIS_DIR
OUTPUT_FITMENTS_JSON_PATH = os.path.join(DATA_DIR, "vehicle_fitments_data.json")
OUTPUT_BATTERIES_JSON_PATH = os.path.join(DATA_DIR, "batteries_master_data.json")
ERROR_LOG_PATH = os.path.join(DATA_DIR, "fitments_parse_errors.json")

# --- DATA STRUCTURES TO HOLD PARSED INFO ---
BATTERY_PRICE_MAP = {}
BATTERY_BRAND_MAP = {}
PARSED_BATTERIES_DATA = []

# --- NEW: Function to parse the price data ---
def parse_battery_prices(price_data_text):
    lines = price_data_text.strip().split('\n')
    for line in lines:
        line = line.strip()
        if not line or ':' not in line:
            continue
        
        parts = line.split(':', 1)
        # The key is now the 'Codigo' from the PDF, which is our canonical prefixed code
        model_code_with_prefix = parts[0].strip()
        
        # The value is a tuple of (brand, non_prefixed_code, price)
        try:
            value_parts = parts[1].strip().split(',')
            brand = value_parts[0].strip()
            non_prefixed_code = value_parts[1].strip()
            price_str = value_parts[2].strip().replace('$', '')
            price = float(price_str)

            # Store the data
            BATTERY_PRICE_MAP[model_code_with_prefix] = price
            BATTERY_BRAND_MAP[model_code_with_prefix] = brand

            # Add to the list that will become batteries_master_data.json
            PARSED_BATTERIES_DATA.append({
                "brand": brand,
                "model_code": model_code_with_prefix,
                "reference_code": non_prefixed_code, # For cross-referencing
                "price_full": price,
                "price_discounted_usd": None, # Or calculate this if you have a rule
                "warranty_months": 18 # You can add this to the price input if it varies
            })

        except (ValueError, IndexError) as e:
            print(f"⚠️  Warning: Could not parse price line for '{line}': {e}")

# --- MODIFIED: The rest of the functions are now simpler ---
def extract_models_from_brand_segment(brand_name, segment_text, vehicle_info_for_log, error_logs_list):
    # This regex now just looks for the prefixed model codes
    potential_raw_codes = re.findall(
        r'\b([FBNEO][A-Z0-9]+(?:[\-\/][A-Z0-9\/]+)*[A-Z0-9])\b',
        segment_text, re.IGNORECASE)
    
    extracted_batteries = []
    ignore_words = {"THE", "IN", "IS", "ARE", "BRAND", "MODELS", "MODEL", "AND",
                    "OPTION", "OPTIONS", "AVAILABLE", "WHICH", "ONLY", "ONE", "THERE",
                    "ADDITIONAL", "NO", "FOR", "BATTERIES", "BATTERY"}
                    
    for raw_code in potential_raw_codes:
        if raw_code.upper() in ignore_words:
            continue

        # Check if this prefixed code is a valid battery we have priced
        if raw_code in BATTERY_PRICE_MAP:
             extracted_batteries.append({"brand": BATTERY_BRAND_MAP[raw_code], "model_code": raw_code})
        else:
            error_logs_list.append({
                "vehicle_info": vehicle_info_for_log,
                "reason": f"MAPPING WARNING: Model code '{raw_code}' found in fitment text but is not in the battery price list."
            })
            
    return extracted_batteries

def parse_vehicle_fitments(data_text, error_logs):
    results = []
    vehicle_entries_text = [entry.strip() for entry in data_text.strip().split("\n\n") if entry.strip()]
    for entry_idx, entry_text in enumerate(vehicle_entries_text):
        first_line = entry_text.split('\n')[0].strip()
        vehicle_info_for_log = f"Entry #{entry_idx+1}: {first_line[:100]}..."
        
        # --- MODIFICATION START: Improved Regex to capture engine_details ---
        # This regex has a non-greedy part for the model and a new optional group for engine_details
        car_match = re.match(r"^(.*?)\s+((?:[A-Z0-9\s\/\.\-']|\((?!\d{4}))+?)(?:\s+\((.*?)\))?\s+\((\d{4})(?:[\/\-](\d{4}))?\):(.*)", first_line)
        # --- MODIFICATION END ---

        if not car_match:
            error_logs.append({"vehicle_info": vehicle_info_for_log, "reason": "REGEX FAIL: Could not parse vehicle make/model/year from first line."})
            continue
            
        # --- MODIFICATION START: Unpack groups including new engine_details group ---
        groups = car_match.groups()
        # The new regex adds 'engine_details' as the 3rd captured group
        vehicle_make, vehicle_model_raw, engine_details, year_start, year_end, details_text = (g.strip() if g else None for g in groups)
        # --- MODIFICATION END ---
        
        year_start = int(year_start)
        year_end = int(year_end) if year_end else year_start
        vehicle_model = re.sub(r'\s*\(.*?\)\s*$', '', vehicle_model_raw).strip() or vehicle_model_raw

        print(f"\nProcessing: {vehicle_make} | {vehicle_model} | Engine: {engine_details} | ({year_start}-{year_end})")
        
        all_compatible_batteries_for_vehicle = []
        brand_search_order = ["Fulgor", "Black Edition", "Mac", "Optima", "Everlite"]
        for brand_name in brand_search_order:
            brand_section_regex = re.compile(
                rf"(?i)(?:In\s+the\s+)?{brand_name}\s+brand\b(.*?)(?=\s+(?:In\s+the\s+)?(?:{'|'.join(brand_search_order)})\s+brand|\s*$)",
                re.DOTALL
            )
            match = brand_section_regex.search(details_text)
            if match:
                segment_for_brand = match.group(1).strip()
                codes = extract_models_from_brand_segment(brand_name, segment_for_brand, vehicle_info_for_log, error_logs)
                all_compatible_batteries_for_vehicle.extend(codes)

        unique_compatible_batteries = [dict(t) for t in {tuple(d.items()) for d in all_compatible_batteries_for_vehicle}]
        
        # --- MODIFICATION START: Add engine_details to the JSON output ---
        car_json_output = {
            "vehicle_make": vehicle_make,
            "vehicle_model": vehicle_model,
            "year_start": year_start,
            "year_end": year_end,
            "engine_details": engine_details,
            "compatible_battery_model_codes": unique_compatible_batteries
        }
        # --- MODIFICATION END ---
        results.append(car_json_output)
    return results

# -------- MAIN EXECUTION -------- #
if __name__ == "__main__":
    
    # --- INPUT FIELD 1: BATTERY PRICES (EXTRACTED FROM YOUR PDF) ---
    # Format: Prefixed Code: Brand, Non-Prefixed Code, Price
    battery_price_input = """
    M22NF-850: Mac, 22NF - 850, $153.31
    M36FP-800: Mac, 36FP - 800, $131.74
    M22FA-850: Mac, 22FA - 850, $152.78
    M41MR-1050: Mac, 41MR - 1050, $166.75
    M41M-1050: Mac, 41M - 1050, $166.75
    M86-900: Mac, 86 - 900, $153.20
    M24R-1150: Mac, 24R - 1150, $218.49
    M34-1150: Mac, 34 - 1150, $205.32
    M65-1200: Mac, 65 - 1200, $215.92
    M94R-1200: Mac, 94R - 1200, $254.67
    M49-1250: Mac, 49 - 1250, $247.82
    BN22NF-850: Black Edition, 22NF - 850, $144.91
    BN36FP-800: Black Edition, 36FP - 800, $119.57
    BN22FA-900: Black Edition, 22FA - 900, $148.30
    BN86-900: Black Edition, 86 - 900, $137.20
    BN41FXR-1000: Black Edition, 41FXR - 1000, $164.97
    BN41XR-1000: Black Edition, 41XR - 1000, $164.97
    BN34-1100: Black Edition, 34 - 1100, $180.12
    BN24MR-1150: Black Edition, 24MR - 1150, $195.08
    BN94R-1200: Black Edition, 94R - 1200, $232.70
    FNS40-670: Fulgor, NS40 - 670, $132.50
    F22NF-750: Fulgor, 22NF - 750, $126.37
    F36FP-750: Fulgor, 36FP - 750, $115.68
    F22FA-850: Fulgor, 22FA - 850, $144.85
    F86-850: Fulgor, 86 - 850, $134.13
    F41MR-950: Fulgor, 41MR - 950, $160.59
    F41M-950: Fulgor, 41M - 950, $160.59
    F65-1200: Fulgor, 65 - 1200, $204.69
    F34M-1000: Fulgor, 34M - 1000, $163.44
    F34MR-1000: Fulgor, 34MR - 1000, $163.44
    F24R-1000: Fulgor, 24R - 1000, $190.58
    F27XR-1100: Fulgor, 27XR - 1100, $192.43
    F27R-1100: Fulgor, 27R - 1100, $192.43
    E36FP-700: Everlite, 36FP - 700, $97.17
    E22FA-800: Everlite, 22FA - 800, $113.24
    E86-800: Everlite, 86 - 800, $115.61
    E85-800: Everlite, 85 - 800, $115.61
    E34MR-900: Everlite, 34MR - 900, $140.93
    E34M-900: Everlite, 34M - 900, $140.93
    F30H-1250: Fulgor, 30H - 1250, $240.98
    F31T-1250: Fulgor, 31T - 1250, $246.10
    F4D-1350: Fulgor, 4D - 1350, $346.74
    F8D-1600: Fulgor, 8D - 1600, $442.37
    O34R-ROJA: Optima, 34R - ROJA, $386.77
    O34-ROJA: Optima, 34 - ROJA, $386.77
    OD34M-AZUL: Optima, D34M - AZUL, $495.97
    OD35-AMARILLA: Optima, D35 - AMARILLA, $489.14
    OD34-AMARILLA: Optima, D34 - AMARILLA, $500.52
    OD34/78-AMARILLA: Optima, D34/78 - AMARILLA, $514.17
    """

    # --- INPUT FIELD 2: VEHICLE FITMENTS (NO PRICES, BUT WITH PREFIXES) ---
    car_fitment_input = """
    ACURA INTEGRA (1992/2001): The available battery model in the Fulgor brand is the F22NF750. In the Black Edition brand, the available battery is the BN22NF850.
ACURA LEGEND (1990/1995): The available battery models in the Fulgor brand are the F86850 and the F34M1000. In the Black Edition brand, the available batteries are the BN86900 and the BN341100.

ALFA ROMEO 145 (1996/2001): The available battery models in the Fulgor brand are the F22FA850 and the F41MR950. In the Black Edition brand, the available batteries are the BN22FA900 and the BN41FXR1000.
ALFA ROMEO 146 (1996/2001): The available battery models in the Fulgor brand are the F22FA850 and the F41MR950. In the Black Edition brand, the available batteries are the BN22FA900 and the BN41FXR1000.
ALFA ROMEO 147 (2001/2010): The available battery models in the Fulgor brand are the F22FA850 and the F41MR950. In the Black Edition brand, the available batteries are the BN22FA900 and the BN41FXR1000.
ALFA ROMEO 155 (1992/1997): The available battery models in the Fulgor brand are the F22FA850 and the F41MR950. In the Black Edition brand, the available batteries are the BN22FA900 and the BN41FXR1000.
ALFA ROMEO 156 (1997/2006): The available battery models in the Fulgor brand are the F22FA850 and the F41MR950. In the Black Edition brand, the available batteries are the BN22FA900 and the BN41FXR1000.
ALFA ROMEO 164 (1992/1998): The available battery models in the Fulgor brand are the F24R1000 and the F34MR1000. In the Black Edition brand, the available battery is the BN24MR1150.
ALFA ROMEO 166 (1998/2007): The available battery models in the Fulgor brand are the F22FA850 and the F41MR950. In the Black Edition brand, the available batteries are the BN22FA900 and the BN41FXR1000.
ALFA ROMEO 33 (1990/2004): The available battery models in the Fulgor brand are the F22FA850 and the F41MR950. In the Black Edition brand, the available batteries are the BN22FA900 and the BN41FXR1000.
ALFA ROMEO GT (2003/2010): The available battery models in the Fulgor brand are the F22FA850 and the F41MR950. In the Black Edition brand, the available batteries are the BN22FA900 and the BN41FXR1000.
ALFA ROMEO GTV (1995/2005): The available battery models in the Fulgor brand are the F22FA850 and the F41MR950. In the Black Edition brand, the available batteries are the BN22FA900 and the BN41FXR1000.
ALFA ROMEO SPIDER (1994/2005): The available battery models in the Fulgor brand are the F22FA850 and the F41MR950. In the Black Edition brand, the available batteries are the BN22FA900 and the BN41FXR1000.

AUDI A3 (1998/2007): The available battery models in the Fulgor brand are the F22FA850 and the F41MR950. In the Black Edition brand, the available batteries are the BN22FA900 and the BN41FXR1000.
AUDI A4 (2002/2008): The available battery models in the Fulgor brand are the F22FA850 and the F41MR950. In the Black Edition brand, the available batteries are the BN22FA900 and the BN41FXR1000.
AUDI A6 (2004/2006): The available battery models in the Fulgor brand are the F22FA850 and the F41MR950. In the Black Edition brand, the available batteries are the BN22FA900 and the BN41FXR1000.
AUDI A8 (2004/2006): The available battery models in the Fulgor brand are the F22FA850 and the F41MR950. In the Black Edition brand, the available batteries are the BN22FA900 and the BN41FXR1000.
AUDI Q7 (1998/2008): The available battery model in the Fulgor brand is the F41MR950. In the Black Edition brand, the available batteries are the BN41FXR1000 and the BN94R1200.

BAW CALORIE F7 PICKUP (2022/2024): The available battery model in the Fulgor brand is the F22FA850. In the Black Edition brand, the available battery is the BN22FA900.
BAW LA BESTIA (2022/2024): The available battery model in the Fulgor brand is the F22NF750. In the Black Edition brand, the available battery is the BN22NF850.
BAW MPV M7 VAN/CARGO (2022/2024): The available battery model in the Fulgor brand is the F22NF750. In the Black Edition brand, the available battery is the BN22NF850.

BLUE BIRD AUTOBUSES A GASOLINA (1971/1993): The available battery models in the Fulgor brand are the F4D1350 and the F8D1600. There are no available models in the Black Edition brand.
BLUE BIRD AUTOBUSES DIESEL (1973/1993): The available battery models in the Fulgor brand are the F4D1350 and the F8D1600. There are no available models in the Black Edition brand.

BMW 116I (1998/2008): The available battery model in the Fulgor brand is the F41MR950. In the Black Edition brand, the available battery is the BN41FXR1000.
BMW 131I (1998/2008): The available battery model in the Fulgor brand is the F41MR950. In the Black Edition brand, the available battery is the BN41FXR1000.
BMW 135I (1998/2009): The available battery model in the Fulgor brand is the F41MR950. In the Black Edition brand, the available battery is the BN41FXR1000.
BMW 318I (1998/2008): The available battery model in the Fulgor brand is the F41MR950. In the Black Edition brand, the available battery is the BN41FXR1000.
BMW 525I (1998/2008): The available battery model in the Fulgor brand is the F41MR950. In the Black Edition brand, the available battery is the BN41FXR1000.
BMW 530I (1998/2008): The available battery model in the Fulgor brand is the F41MR950. In the Black Edition brand, the available battery is the BN41FXR1000.
BMW 830I (2000/2008): The available battery model in the Fulgor brand is the F41MR950. In the Black Edition brand, the available batteries are the BN41FXR1000 and the BN94R1200.
BMW SERIE 3 (1992/2009): The available battery model in the Fulgor brand is the F41MR950. In the Black Edition brand, the available battery is the BN41FXR1000.
BMW SERIE 5 (1992/2010): The available battery model in the Fulgor brand is the F41MR950. In the Black Edition brand, the available battery is the BN41FXR1000.
BMW X3 (1998/2008): The available battery model in the Fulgor brand is the F41MR950. In the Black Edition brand, the available battery is the BN41FXR1000.
BMW X5 (2000/2010): The available battery model in the Fulgor brand is the F41MR950. In the Black Edition brand, the available batteries are the BN41FXR1000 and the BN94R1200.
BMW X6 (2000/2010): The available battery model in the Fulgor brand is the F41MR950. In the Black Edition brand, the available batteries are the BN41FXR1000 and the BN94R1200.
BMW X7 (2000/2010): The available battery model in the Fulgor brand is the F41MR950. In the Black Edition brand, the available batteries are the BN41FXR1000 and the BN94R1200.
BMW Z3 (1998/2008): The available battery model in the Fulgor brand is the F41MR950. In the Black Edition brand, the available battery is the BN41FXR1000.
BMW Z4 (1998/2008): The available battery model in the Fulgor brand is the F41MR950. In the Black Edition brand, the available battery is the BN41FXR1000.

BUICK CENTURY (1983/1996): The available battery models in the Fulgor brand are the F86850 and the F34M1000. In the Black Edition brand, the available batteries are the BN86900 and the BN341100.
BUICK LE SABRE (1992/1999): The available battery models in the Fulgor brand are the F86850 and the F34M1000. In the Black Edition brand, the available batteries are the BN86900 and the BN341100.

BYD F3 (2008): The available battery model in the Fulgor brand is the F22NF750. In the Black Edition brand, the available battery is the BN22NF850.
BYD FLYER (2006/2007): The available battery model in the Fulgor brand is the F22NF750. In the Black Edition brand, the available battery is the BN22NF850.

CHANA PICK UP (2008/2009): The available battery model in the Fulgor brand is the F22NF750. In the Black Edition brand, the available battery is the BN22NF850.
CHANA SUPER VAN (2007/2009): The available battery model in the Fulgor brand is the F22NF750. In the Black Edition brand, the available battery is the BN22NF850.

CHANGAN ALSVIN CS15 (2022/2024): The available battery model in the Fulgor brand is the F22FA850. In the Black Edition brand, the available battery is the BN22FA900.
CHANGAN BENNI E-STAR (2023/2024): The available battery model in the Fulgor brand is the F22NF750. In the Black Edition brand, the available battery is the BN22FA900.
CHANGAN CS35 PLUS (2022/2024): The available battery model in the Fulgor brand is the F86850. In the Black Edition brand, the available battery is the BN86900.
CHANGAN CS55 (2022/2024): The available battery model in the Fulgor brand is the F22FA850. In the Black Edition brand, the available battery is the BN22FA900.
CHANGAN HUNTER 2.0 TURBO GASOLINA (2022/2024): There are no available models in the Fulgor brand. In the Black Edition brand, the available battery is the BN94R1200.
CHANGAN HUNTER 2.5 DIESEL (2022/2024): The available battery model in the Fulgor brand is the F27XR1100. There are no available models in the Black Edition brand.
CHANGAN KAICENE (2022/2024): The available battery model in the Fulgor brand is the F27XR1100. There are no available models in the Black Edition brand.

CHANGHE IDEAL (2007): The available battery model in the Fulgor brand is the F22NF750. In the Black Edition brand, the available battery is the BN22NF850.

CHERY ARAUCA (2012/2016): The available battery models in the Fulgor brand are the F36FP750 and the F22FA850. In the Black Edition brand, the available batteries are the F36FP800 and the F22FA900.
CHERY ARAUCA (2019): The available battery models in the Fulgor brand are the FNS40670 and the F22NF750. In the Black Edition brand, the available battery is the F22NF850.
CHERY COWIN (2008): The available battery models in the Fulgor brand are the F36FP750 and the F22FA850. In the Black Edition brand, the available batteries are the F36FP800 and the F22FA900.
CHERY GRAND TIGER (2012/2013): The available battery model in the Fulgor brand is the F34M1000. In the Black Edition brand, the available battery is the BN341100.
CHERY GRAND TIGGO (2014/2015): The available battery models in the Fulgor brand are the F22FA850 and the F34MR1000. In the Black Edition brand, the available battery is the BN22FA900.
CHERY GRAND TIGGO (2016): The available battery model in the Fulgor brand is the F41MR950. In the Black Edition brand, the available battery is the BN41FXR1000.
CHERY ORINOCO (2012/2018): The available battery models in the Fulgor brand are the F36FP750 and the F22FA850. In the Black Edition brand, the available batteries are the F36FP800 and the F22FA900.
CHERY QQ (2008/2009): The available battery models in the Fulgor brand are the FNS40670 and the F22NF750. In the Black Edition brand, the available battery is the F22NF850.
CHERY TIGGO (2006/2009): The available battery model in the Fulgor brand is the F34M1000. In the Black Edition brand, the available battery is the BN341100.
CHERY TIGGO 4/4PRO (2022/2024): The available battery model in the Fulgor brand is the F22FA850. In the Black Edition brand, the available battery is the BN22FA900.
CHERY TIGGO 7 PRO (2022/2024): The available battery model in the Fulgor brand is the F22FA900. In the Black Edition brand, the available battery is the BN22FA900.
CHERY TIGGO 8 PRO (2022/2024): The available battery model in the Fulgor brand is the F41MR950. In the Black Edition brand, the available battery is the BN41FXR1000.
CHERY TIUNA X5 (2015/2016): The available battery model in the Fulgor brand is the F34M1000. In the Black Edition brand, the available battery is the BN341100.
CHERY VAN H5 (2016): The available battery model in the Fulgor brand is the F22FA850. There are no available models in the Black Edition brand.
CHERY WIND CLOUD (2006/2007): The available battery model in the Fulgor brand is the F86850. In the Black Edition brand, the available battery is the F86900.
CHERY X1 (2013/2016): The available battery model in the Fulgor brand is the F22NF750. In the Black Edition brand, the available battery is the BN22FA900.
CHERY ZOYTE (2008): The available battery model in the Fulgor brand is the F22NF750. There are no available models in the Black Edition brand.

CHEVROLET ASTRA (2002/2007): The available battery model in the Fulgor brand is the F41MR-950. In the Black Edition brand, the available battery is the BN22FA-900.
CHEVROLET AUTOBUSES (1955/2000): The available battery model in the Fulgor brand is the F4D-1350. There are no available models in the Black Edition brand.
CHEVROLET AVALANCHE (2005/2008): The available battery model in the Fulgor brand is the F34M-1000. In the Black Edition brand, the available battery is the BN34-1100.
CHEVROLET AVEO (2005/2010): The available battery models in the Fulgor brand are the F86-850 and the F41M-950. In the Black Edition brand, the available batteries are the BN86-900 and the BN41FXR-1000.
CHEVROLET AVEO LT GNV (2011/2014): The available battery model in the Fulgor brand is the F86-850. There are no available models in the Black Edition brand.
CHEVROLET BLAZER (1990/2003): The available battery model in the Fulgor brand is the F86-850. In the Black Edition brand, the available battery is the BN86-900.
CHEVROLET C10 (1956/2001): The available battery model in the Fulgor brand is the F34M-1000. In the Black Edition brand, the available battery is the BN34-1100.
CHEVROLET C30 (1980/1991): The available battery model in the Fulgor brand is the F34M-1000. In the Black Edition brand, the available battery is the BN34-1100.
CHEVROLET C60 (1956/1999): The available battery model in the Fulgor brand is the F34M-1000. In the Black Edition brand, the available battery is the BN34-1100.
CHEVROLET C70 (2001): The available battery model in the Fulgor brand is the F34M-1000. In the Black Edition brand, the available battery is the BN34-1100.
CHEVROLET C3500 (1956/1999): The available battery model in the Fulgor brand is the F34M-1000. In the Black Edition brand, the available battery is the BN34-1100.
CHEVROLET C3500 (2000/2005): The available battery model in the Fulgor brand is the F34M-1000. In the Black Edition brand, the available battery is the BN34-1100.
CHEVROLET C3500 (2011/2015): The available battery model in the Fulgor brand is the F24R-1000. In the Black Edition brand, the available battery is the BN24MR-1150.
CHEVROLET CAMARO SS LT1 V8 (2010/2018): The available battery model in the Fulgor brand is the F24R-1000. In the Black Edition brand, the available battery is the BN24MR-1150.
CHEVROLET CAMARO (1988/2002): The available battery model in the Fulgor brand is the F24R-1000. In the Black Edition brand, the available battery is the BN24MR-1150.
CHEVROLET CAPRICE (1973/1998): The available battery model in the Fulgor brand is the F34M-1000. In the Black Edition brand, the available battery is the BN34-1100.
CHEVROLET CAPTIVA (2007/2008): The available battery models in the Fulgor brand are the F41M-950 and the F34M-1000. In the Black Edition brand, the available batteries are the BN41XR-1000 and the BN34-1100.
CHEVROLET CAVALIER (1992/2005): The available battery model in the Fulgor brand is the F86-850. In the Black Edition brand, the available battery is the BN86-900.
CHEVROLET CENTURY (1983/1996): The available battery model in the Fulgor brand is the F86-850. In the Black Edition brand, the available battery is the BN86-900.
CHEVROLET CELEBRITY (1983/1991): The available battery model in the Fulgor brand is the F86-850. In the Black Edition brand, the available battery is the BN86-900.
CHEVROLET CHEVETTE (1981/1996): The available battery models in the Fulgor brand are the F36FP-750 and the F22FA-850. In the Black Edition brand, the available batteries are the BN36FP-800 and the BN22FA-900.
CHEVROLET CHEVY C2 (2008/2011): The available battery models in the Fulgor brand are the F36FP-750 and the F22FA-850. In the Black Edition brand, the available batteries are the BN36FP-800 and the BN22FA-900.
CHEVROLET CHEYENNE/SILVERADO (1992/1999): The available battery models in the Fulgor brand are the F41MR-950 and the F34M-1000. In the Black Edition brand, the available battery is the BN41FXR-1000.
CHEVROLET CHEYENNE/SILVERADO (2000/2007): The available battery model in the Fulgor brand is the F34MR-1000. There are no available models in the Black Edition brand.
CHEVROLET CHEYENNE/SILVERADO (2008/2015): The available battery model in the Fulgor brand is the F24R-1000. In the Black Edition brand, the available battery is the BN24MR-1150.
CHEVROLET CORSA (1996/2006): The available battery models in the Fulgor brand are the F36FP-750 and the F22FA-850. In the Black Edition brand, the available batteries are the BN36FP-800 and the BN22FA-900.
CHEVROLET CORSICA (1990/1996): The available battery model in the Fulgor brand is the F86-850. In the Black Edition brand, the available battery is the BN86-900.
CHEVROLET CRUZE (2011/2013): The available battery model in the Fulgor brand is the F41MR-950. In the Black Edition brand, the available battery is the BN41FXR-1000.
CHEVROLET CORVETTE STRINGRAY Z51 2LT 6.2L (2015/2018): The available battery model in the Fulgor brand is the F24R-1000. In the Black Edition brand, the available battery is the BN24MR-1150.
CHEVROLET COLORADO (2007/2008): The available battery model in the Fulgor brand is the F86-850. There are no available models in the Black Edition brand.
CHEVROLET EPICA (2007/2009): The available battery model in the Fulgor brand is the F34M-1000. In the Black Edition brand, the available battery is the BN34-1100.
CHEVROLET ESTEEM (2007/2011): The available battery models in the Fulgor brand are the F36FP-750 and the F22FA-850. In the Black Edition brand, the available batteries are the BN36FP-800 and the BN22FA-900.
CHEVROLET EXZ (2008/2015): The available battery model in the Fulgor brand is the F4D-1350. There are no available models in the Black Edition brand.
CHEVROLET EXR (2008/2015): The available battery model in the Fulgor brand is the F4D-1350. There are no available models in the Black Edition brand.
CHEVROLET FSR (2014): The available battery model in the Fulgor brand is the F4D-1350. There are no available models in the Black Edition brand.
CHEVROLET FSR (2006/2011): The available battery models in the Fulgor brand are the F30HC-1250 and the F31T-1250. There are no available models in the Black Edition brand.
CHEVROLET FVR (2006/2011): The available battery models in the Fulgor brand are the F30HC-1250 and the F31T-1250. There are no available models in the Black Edition brand.
CHEVROLET GRAN VITARA XL5 4CIL (2000/2008): The available battery models in the Fulgor brand are the F22FA-850 and the F41MR-950. In the Black Edition brand, the available batteries are the BN22FA-900 and the BN41FXR-1000.
CHEVROLET GRAN VITARA XL5 6CIL (2000/2008): The available battery model in the Fulgor brand is the F34MR-1000. There are no available models in the Black Edition brand.
CHEVROLET GRAN VITARA XL7 (2003/2007): The available battery model in the Fulgor brand is the F34MR-1000. There are no available models in the Black Edition brand.
CHEVROLET GRAND BLAZER (1992/2001): The available battery model in the Fulgor brand is the F34M-1000. There are no available models in the Black Edition brand.
CHEVROLET IMPALA SS (2007/2008): The available battery models in the Fulgor brand are the F22FA-850 and the F34MR-1000. In the Black Edition brand, the available battery is the BN22FA-900.
CHEVROLET IMPALA (2000/2005): The available battery model in the Fulgor brand is the F41MR-950. In the Black Edition brand, the available battery is the BN41FXR-1000.
CHEVROLET JIMMY (2000/2003): The available battery model in the Fulgor brand is the F36FP-750. There are no available models in the Black Edition brand.
CHEVROLET KODIAK 157/175 (2002/2010): The available battery models in the Fulgor brand are the F30HC-1250 and the F31T-1250. There are no available models in the Black Edition brand.
CHEVROLET KODIAK 229 (1992/2010): The available battery models in the Fulgor brand are the F30HC-1250 and the F31T-1250. There are no available models in the Black Edition brand.
CHEVROLET LUMINA (1996/1999): The available battery model in the Fulgor brand is the F41MR-950. In the Black Edition brand, the available battery is the BN41FXR-1000.
CHEVROLET LUV 4 CIL 2.3L (2001/2006): The available battery models in the Fulgor brand are the F86-850 and the F34M-1000. In the Black Edition brand, the available batteries are the BN86-900 and the BN34-1100.
CHEVROLET LUV D/MAX 6 CIL GNV (2009/2015): The available battery model in the Fulgor brand is the F34M-1000. In the Black Edition brand, the available battery is the BN34-1100.
CHEVROLET LUV D/MAX 6 CIL (2001/2006): The available battery model in the Fulgor brand is the F34M-1000. In the Black Edition brand, the available battery is the BN34-1100.
CHEVROLET MALIBU (1969/1984): The available battery model in the Fulgor brand is the F34M-1000. In the Black Edition brand, the available battery is the BN34-1100.
CHEVROLET MERIVA (2007/2008): The available battery models in the Fulgor brand are the F36FP-750 and the F22FA-850. In the Black Edition brand, the available batteries are the BN36FP-800 and the BN22FA-900.
CHEVROLET MONTANA (2005/2008): The available battery models in the Fulgor brand are the F22FA-850 and the F41MR-950. In the Black Edition brand, the available batteries are the BN22FA-900 and the BN41FXR-1000.
CHEVROLET MONTECARLO (1978/2005): The available battery model in the Fulgor brand is the F34M-1000. In the Black Edition brand, the available battery is the BN34-1100.
CHEVROLET MONZA (1985/1998): The available battery models in the Fulgor brand are the F36FP-750 and the F22FA-850. In the Black Edition brand, the available batteries are the BN36FP-800 and the BN22FA-900.
CHEVROLET NHR (1992/2015): The available battery model in the Fulgor brand is the F24R-1000. In the Black Edition brand, the available battery is the BN24MR-1150.
CHEVROLET NOVA (1971/1977): The available battery model in the Fulgor brand is the F86-850. In the Black Edition brand, the available battery is the BN86-900.
CHEVROLET NPR 24 (1992/2015): The available battery model in the Fulgor brand is the F24R-1000. In the Black Edition brand, the available battery is the BN24MR-1150.
CHEVROLET NPR TURBO 12V (1992/2015): The available battery models in the Fulgor brand are the F27XR-1100 and the F27R-1100. There are no available models in the Black Edition brand.
CHEVROLET NPR AUTOBUS (2005/2007): The available battery models in the Fulgor brand are the F27XR-1100 and the F27R-1100. There are no available models in the Black Edition brand.
CHEVROLET ONIX (2018/2023): The available battery models in the Fulgor brand are the F36FP-750 and the F22FA-850. In the Black Edition brand, the available batteries are the BN36FP-800 and the BN22FA-900.
CHEVROLET OPTRA ADVANCE (2004/2007): The available battery models in the Fulgor brand are the F86-850 and the F34M-1000. In the Black Edition brand, the available batteries are the BN86-900 and the BN34-1100.
CHEVROLET OPTRA DESING / HATCHBACK (2007/2008): The available battery models in the Fulgor brand are the F86-850 and the F34M-1000. In the Black Edition brand, the available batteries are the BN86-900 and the BN34-1100.
CHEVROLET OPTRA LIMITED (2008/2012): The available battery models in the Fulgor brand are the F86-850 and the F34M-1000. In the Black Edition brand, the available batteries are the BN86-900 and the BN34-1100.
CHEVROLET OPTRA DESING (2009/2011): The available battery models in the Fulgor brand are the F86-850 and the F34M-1000. In the Black Edition brand, the available batteries are the BN86-900 and the BN34-1100.
CHEVROLET ORLANDO (2011/2013): The available battery model in the Fulgor brand is the F41MR-950. In the Black Edition brand, the available battery is the BN41FXR-1000.
CHEVROLET S/10 (1990/1999): The available battery model in the Fulgor brand is the F86-850. In the Black Edition brand, the available battery is the BN86-900.
CHEVROLET SPARK (2006/2014): The available battery models in the Fulgor brand are the FNS40-670 and the F36FP-750. In the Black Edition brand, the available battery is the BN22NF-850.
CHEVROLET SPARK GT (2017/2021): The available battery model in the Fulgor brand is the F36FP-750. In the Black Edition brand, the available battery is the BN36FP-800.
CHEVROLET SUNFIRE (1995/2003): The available battery model in the Fulgor brand is the F86-850. In the Black Edition brand, the available battery is the BN86-900.
CHEVROLET SUPER CARRY (1992/2007): The available battery models in the Fulgor brand are the FNS40-670 and the F22NF-750. In the Black Edition brand, the available battery is the BN22NF-850.
CHEVROLET SWIFT (1991/1997): The available battery models in the Fulgor brand are the F22NF-750 and the F36FP-750. In the Black Edition brand, the available batteries are the BN36FP-800 and the BN22FA-900.
CHEVROLET TAHOE (2007/2014): The available battery model in the Fulgor brand is the F24R-1000. In the Black Edition brand, the available battery is the BN24MR-1150.
CHEVROLET TRAIL BLAZER (2002/2008): The available battery model in the Fulgor brand is the F34M-1000. In the Black Edition brand, the available battery is the BN34-1100.
CHEVROLET VANS EXPRESS (2007/2008): The available battery model in the Fulgor brand is the F34M-1000. In the Black Edition brand, the available battery is the BN34-1100.
CHEVROLET VECTRA (1992/1995): The available battery models in the Fulgor brand are the F36FP-750 and the F22FA-850. In the Black Edition brand, the available batteries are the BN36FP-800 and the BN22FA-900.
CHEVROLET VITARA (2004/2007): The available battery model in the Fulgor brand is the F86-850. In the Black Edition brand, the available battery is the BN86-900.
CHEVROLET VITARA (3 PUERTAS) (1997/2003): The available battery model in the Fulgor brand is the F22FA-850. In the Black Edition brand, the available batteries are the BN22FA-900 and the BN86-900.
CHEVROLET WAGON R (1999/2004): The available battery models in the Fulgor brand are the FNS40-670 and the F22NF-750. In the Black Edition brand, the available battery is the BN22NF-850

CHRYSLER 300C (2007/2008): There are no available models in the Fulgor brand. In the Black Edition brand, the available battery is the BN94R1200.
CHRYSLER 300M (1998/2001): The available battery model in the Fulgor brand is the F34M1000. In the Black Edition brand, the available battery is the BN341100.
CHRYSLER CAMIONES (1956/1999): The available battery models in the Fulgor brand are the F30HC1250 and the F31T1250. There are no available models in the Black Edition brand.
CHRYSLER GRAND CARAVAN (1992/2006): The available battery model in the Fulgor brand is the F34M1000. In the Black Edition brand, the available battery is the BN341100.
CHRYSLER JOURNEY (2009/2019): The available battery model in the Fulgor brand is the F86850. In the Black Edition brand, the available battery is the BN86900.
CHRYSLER LE BARON (1978/1995): The available battery model in the Fulgor brand is the F34M1000. In the Black Edition brand, the available battery is the BN341100.
CHRYSLER NEON (1997/2000): The available battery model in the Fulgor brand is the F36FP750. In the Black Edition brand, the available battery is the F36FP800.
CHRYSLER PT CRUISER (2002/2008): The available battery model in the Fulgor brand is the F86850. In the Black Edition brand, the available battery is the BN86900.
CHRYSLER SEBRING (2005/2009): The available battery model in the Fulgor brand is the F86850. In the Black Edition brand, the available battery is the BN86900.
CHRYSLER SPIRIT (1989/1995): The available battery model in the Fulgor brand is the F34M1000. In the Black Edition brand, the available battery is the BN341100.
CHRYSLER STRATUS (1996/2001): The available battery model in the Fulgor brand is the F86850. In the Black Edition brand, the available battery is the BN86900.
CHRYSLER TOWN & COUNTRY (1991/2007): The available battery model in the Fulgor brand is the F34M1000. In the Black Edition brand, the available battery is the BN341100.

CITROËN C3 (2004/2008): The available battery models in the Fulgor brand are the F36FP750 and the F22FA850. In the Black Edition brand, the available batteries are the F36FP800 and the F22FA900.
CITROËN C4 (2005/2008): The available battery models in the Fulgor brand are the F36FP750 and the F22FA850. In the Black Edition brand, the available batteries are the F36FP800 and the F22FA900.

DAEWOO CIELO (1995/2002): The available battery models in the Fulgor brand are the F36FP-750 and the F22FA-850. In the Black Edition brand, the available batteries are the BN36FP-800 and the BN22FA-900.
DAEWOO DAMAS (1993/2002): The available battery model in the Fulgor brand is the FNS40-670. There are no available models in the Black Edition brand.
DAEWOO ESPERO (1994/1998): The available battery models in the Fulgor brand are the F36FP-750 and the F22FA-850. In the Black Edition brand, the available batteries are the BN36FP-800 and the BN22FA-900.
DAEWOO LABO (1995/2002): The available battery models in the Fulgor brand are the FNS40-670 and the F22NF-750. In the Black Edition brand, the available battery is the BN22NF-850.
DAEWOO LANOS (1997/2002): The available battery model in the Fulgor brand is the F86-850. In the Black Edition brand, the available battery is the BN86-900.
DAEWOO LEGANZA (1998/2002): The available battery model in the Fulgor brand is the F86-850. In the Black Edition brand, the available battery is the BN86-900.
DAEWOO LUBLIN II (1997/1998): The available battery model in the Fulgor brand is the F34M-1000. In the Black Edition brand, the available battery is the BN34-1100.
DAEWOO MATIZ (1998/2002): The available battery models in the Fulgor brand are the FNS40-670 and the F22NF-750. In the Black Edition brand, the available battery is the BN22NF-850.
DAEWOO MUSSO (1998/2000): The available battery model in the Fulgor brand is the F34MR-1000. There are no available models in the Black Edition brand.
DAEWOO NUBIRA (1998/2002): The available battery models in the Fulgor brand are the F36FP-750 and the F22FA-850. In the Black Edition brand, the available batteries are the BN36FP-800 and the BN22FA-900.
DAEWOO PRINCE (1997/1998): The available battery model in the Fulgor brand is the F34M-1000. In the Black Edition brand, the available battery is the BN34-1100.
DAEWOO RACER (1993/1998): The available battery models in the Fulgor brand are the F36FP-750 and the F22FA-850. In the Black Edition brand, the available batteries are the BN36FP-800 and the BN22FA-900.
DAEWOO SUPER SALOM (1996/1998): The available battery model in the Fulgor brand is the F34M-1000. In the Black Edition brand, the available battery is the BN34-1100.
DAEWOO TACUMA (2000/2002): The available battery models in the Fulgor brand are the F86-850 and the F34M-1000. In the Black Edition brand, the available battery is the BN34-1100.
DAEWOO TICO (2000/2002): The available battery model in the Fulgor brand is the FNS40-670. There are no available models in the Black Edition brand.

DSFK C31 / Y32 (2022/2024): The available battery model in the Fulgor brand is the F22NF-750. In the Black Edition brand, the available battery is the BN22NF-850.
DSFK C35/C37 (2022/2024): The available battery model in the Fulgor brand is the F22NF-750. In the Black Edition brand, the available battery is the BN22NF-850.
DSFK D1 (2022/2024): The available battery model in the Fulgor brand is the F27R-1100. In the Black Edition brand, the available battery is the BN24MR-1150.
DSFK GLORY 500 TURBO DYNAMIC (2022/2024): The available battery models in the Fulgor brand are the F22FA-850 and the F41MR-950. In the Black Edition brand, the available batteries are the BN22FA-900 and the BN41FXR-1000.
DSFK GLORY 600 (2022/2024): The available battery model in the Fulgor brand is the F86-850. In the Black Edition brand, the available battery is the BN86-900.
DSFK K01S / K02S (2022/2024): The available battery model in the Fulgor brand is the F22NF-750. In the Black Edition brand, the available battery is the BN22NF-850.
DSFK K05S / K07S (2022/2024): The available battery model in the Fulgor brand is the FNS40-670. There are no available models in the Black Edition brand.
DSFK SHINERGY X30 (2022/2024): The available battery model in the Fulgor brand is the F22NF-750. In the Black Edition brand, the available battery is the BN22NF-850.

DODGE ASPEN (1977/1980): The available battery model in the Fulgor brand is the F34M-1000. In the Black Edition brand, the available battery is the BN34-1100.
DODGE BRISA (2002/2007): The available battery models in the Fulgor brand are the F36FP-750 and the F22FA-850. In the Black Edition brand, the available batteries are the BN36FP-800 and the BN22FA-900.
DODGE CALIBER (2007/2012): The available battery model in the Fulgor brand is the F86-850. In the Black Edition brand, the available battery is the BN86-900.
DODGE CARAVAN (1984/2003): The available battery model in the Fulgor brand is the F34M-1000. In the Black Edition brand, the available battery is the BN34-1100.
DODGE CHARGER DAYTONA (2015/2024): There are no available models in the Fulgor brand. In the Black Edition brand, the available battery is the BN94R-1200.
DODGE CHALLENGER (2008/2018): The available battery model in the Fulgor brand is the F41MR-950. In the Black Edition brand, the available batteries are the BN41FXR-1000 and the BN94R-1200.
DODGE DAKOTA (2006/2009): The available battery model in the Fulgor brand is the F65-1200. There are no available models in the Black Edition brand.
DODGE DART (1963/1982): The available battery model in the Fulgor brand is the F34M-1000. In the Black Edition brand, the available battery is the BN34-1100.
DODGE INTREPID (1993/2001): The available battery model in the Fulgor brand is the F34M-1000. In the Black Edition brand, the available battery is the BN34-1100.
DODGE NEON (2000/2006): The available battery model in the Fulgor brand is the F36FP-750. In the Black Edition brand, the available battery is the BN36FP-800.
DODGE RAM 1200 (2017/2018): The available battery model in the Fulgor brand is the F24R-1000. In the Black Edition brand, the available battery is the BN24MR-1150.
DODGE RAM 2500 (1997/2000): The available battery model in the Fulgor brand is the F34M-1000. In the Black Edition brand, the available battery is the BN34-1100.
DODGE RAM 2500 (2000/2009): The available battery model in the Fulgor brand is the F65-1200. There are no available models in the Black Edition brand.
DODGE STEALTH (1990/1992): The available battery model in the Fulgor brand is the F34M-1000. In the Black Edition brand, the available battery is the BN34-1100.
DODGE VAN RAM (1956/2001): The available battery model in the Fulgor brand is the F34M-1000. In the Black Edition brand, the available battery is the BN34-1100.

DONGFENG AEOLUS AX7 PRO (2022/2024): The available battery models in the Fulgor brand are the F22FA-850 and the F41MR-950. In the Black Edition brand, the available batteries are the BN22FA-900 and the BN41FXR-1000.
DONGFENG A60 (2020/2022): The available battery model in the Fulgor brand is the F22NF-750. In the Black Edition brand, the available battery is the BN22NF-850.
DONGFENG CAPTAIN C (2022/2024): The available battery models in the Fulgor brand are the F27XR-1100 and the F27R-1100. In the Black Edition brand, the available battery is the BN24MR-1150.
DONGFENG DOULIKA 5T,7T (2012/2015): The available battery models in the Fulgor brand are the F27XR-1100 and the F27R-1100. There are no available models in the Black Edition brand.
DONGFENG HAIMA 7 (2012/2014): The available battery model in the Fulgor brand is the F34M-1000. In the Black Edition brand, the available battery is the BN34-1100.
DONGFENG JIMBA (2012/2015): The available battery model in the Fulgor brand is the F27R-1100. There are no available models in the Black Edition brand.
DONGFENG JOYEAR S50 (2021/2023): The available battery model in the Fulgor brand is the F22NF-750. In the Black Edition brand, the available battery is the BN22NF-850.
DONGFENG KR 140/KG 190 (2022/2024): The available battery models in the Fulgor brand are the F27XR-1100, the F27R-1100, the F30HC-1250, and the F31T-1250. There are no available models in the Black Edition brand.
DONGFENG KX460/KX520 (2022/2024): The available battery model in the Fulgor brand is the F4D-1350. There are no available models in the Black Edition brand.
DONGFENG MINI VAN W18 (2022/2024): The available battery model in the Fulgor brand is the FNS40-670. There are no available models in the Black Edition brand.
DONGFENG NEW MINI BUS (2013): The available battery model in the Fulgor brand is the FNS40-670. There are no available models in the Black Edition brand.
DONGFENG RICH 6 DIESEL/GASOLINA (2016/2024): The available battery model in the Fulgor brand is the F27XR-1100. In the Black Edition brand, the available battery is the BN24MR-1150.
DONGFENG S30 (2011/2013): The available battery model in the Fulgor brand is the F22FA-850. In the Black Edition brand, the available battery is the BN22FA-900.
DONGFENG VR 270 (2022/2024): The available battery models in the Fulgor brand are the F30HC-1250 and the F31T-1250. There are no available models in the Black Edition brand.
DONGFENG XIAOBA (2012/2015): The available battery model in the Fulgor brand is the F24R-1000. In the Black Edition brand, the available battery is the BN24MR-1150.
DONGFENG YIXUAN A60 MAX (2023/2024): The available battery model in the Fulgor brand is the F36FP-750. In the Black Edition brand, the available battery is the BN36FP-800.
DONGFENG ZNA RICH (2012): The available battery models in the Fulgor brand are the F86-850 and the F34MR-1000. In the Black Edition brand, the available battery is the BN86-900.

ENCAVA ENT-3300 (2022/2024): The available battery models in the Fulgor brand are the F4D-1350 and the F8D-1600. There are no available models in the Black Edition brand.
ENCAVA ENT-510 (1980/1995): The available battery models in the Fulgor brand are the F30HC-1250 and the F31T-1250. There are no available models in the Black Edition brand.
ENCAVA ENT-610 32PTOS (1995/2024): The available battery model in the Fulgor brand is the F4D-1350. There are no available models in the Black Edition brand.
ENCAVA ENT-900 26PTOS (2000/2024): The available battery models in the Fulgor brand are the F30HC-1250 and the F31T-1250. There are no available models in the Black Edition brand.
ENCAVA EP-1000 DIESEL (2022/2024): The available battery model in the Fulgor brand is the F34M-1000. In the Black Edition brand, the available battery is the BN34-1100.
ENCAVA ET-40 (2022/2024): The available battery model in the Fulgor brand is the F4D-1350. There are no available models in the Black Edition brand.
ENCAVA ET-5 (2022/2024): The available battery models in the Fulgor brand are the F34M-1000 and the F27XR-1100. In the Black Edition brand, the available battery is the BN34-1100.

FIAT 147 (1981/1990): The available battery models in the Fulgor brand are the F36FP-750 and the F22FA-850. In the Black Edition brand, the available batteries are the BN36FP-800 and the BN22FA-900.
FIAT 500 ELECTRICO (2017): The available battery models in the Fulgor brand are the F36FP-750 and the F22FA-850. In the Black Edition brand, the available batteries are the BN36FP-800 and the BN22FA-900.
FIAT 500 GASOLINA (2015/2018): The available battery models in the Fulgor brand are the F36FP-750 and the F22FA-850. In the Black Edition brand, the available batteries are the BN36FP-800 and the BN22FA-900.
FIAT ADVENTURE (1990/2014): The available battery models in the Fulgor brand are the F36FP-750 and the F22FA-850. In the Black Edition brand, the available batteries are the BN36FP-800 and the BN22FA-900.
FIAT ARGO (2023/2024): The available battery models in the Fulgor brand are the F36FP-750 and the F22FA-850. In the Black Edition brand, the available batteries are the BN36FP-800 and the BN22FA-900.
FIAT COUPÉ (1995/2010): The available battery models in the Fulgor brand are the F36FP-750 and the F22FA-850. In the Black Edition brand, the available batteries are the BN36FP-800 and the BN22FA-900.
FIAT CRONOS (2023/2024): The available battery models in the Fulgor brand are the F36FP-750 and the F22FA-850. In the Black Edition brand, the available batteries are the BN36FP-800 and the BN22FA-900.
FIAT DUCATO (2006/2008): The available battery models in the Fulgor brand are the F22FA-850 and the F41MR-950. In the Black Edition brand, the available batteries are the BN22FA-850 and the BN41FXR-1000.
FIAT FIORINO (1981/2010): The available battery models in the Fulgor brand are the F36FP-750 and the F22FA-850. In the Black Edition brand, the available batteries are the BN36FP-800 and the BN22FA-900.
FIAT FULLBACK (2016/2017): The available battery models in the Fulgor brand are the F22FA-850 and the F34MR-1000. In the Black Edition brand, the available battery is the BN22FA-900.
FIAT IDEA (2007/2008): The available battery models in the Fulgor brand are the F36FP-750 and the F22FA-850. In the Black Edition brand, the available batteries are the BN36FP-800 and the BN22FA-900.
FIAT MAREA (1999/2002): The available battery models in the Fulgor brand are the F36FP-750 and the F22FA-850. In the Black Edition brand, the available batteries are the BN36FP-800 and the BN22FA-900.
FIAT MOBIL (2023/2024): The available battery models in the Fulgor brand are the F36FP-750 and the F22FA-850. In the Black Edition brand, the available batteries are the BN36FP-800 and the BN22FA-900.
FIAT PALIO (1997/2008): The available battery models in the Fulgor brand are the F36FP-750 and the F22FA-850. In the Black Edition brand, the available batteries are the BN36FP-800 and the BN22FA-900.
FIAT PREMIO (1985/1999): The available battery models in the Fulgor brand are the F36FP-750 and the F22FA-850. In the Black Edition brand, the available batteries are the BN36FP-800 and the BN22FA-900.
FIAT PUNTO (2008): The available battery models in the Fulgor brand are the F36FP-750 and the F22FA-850. In the Black Edition brand, the available batteries are the BN36FP-800 and the BN22FA-900.
FIAT REGATA (1984/1990): The available battery models in the Fulgor brand are the F36FP-750 and the F22FA-850. In the Black Edition brand, the available batteries are the BN36FP-800 and the BN22FA-900.
FIAT RITMO (1984/1990): The available battery models in the Fulgor brand are the F36FP-750 and the F22FA-850. In the Black Edition brand, the available batteries are the BN36FP-800 and the BN22FA-900.
FIAT SIENA (1987/2008): The available battery models in the Fulgor brand are the F36FP-750 and the F22FA-850. In the Black Edition brand, the available batteries are the BN36FP-800 and the BN22FA-900.
FIAT SPAZIO (1981/1990): The available battery models in the Fulgor brand are the F36FP-750 and the F22FA-850. In the Black Edition brand, the available batteries are the BN36FP-800 and the BN22FA-900.
FIAT STILO (2006/2007): The available battery models in the Fulgor brand are the F36FP-750 and the F22FA-850. In the Black Edition brand, the available batteries are the BN36FP-800 and the BN22FA-900.
FIAT STRADA (2006/2007): The available battery models in the Fulgor brand are the F36FP-750 and the F22FA-850. In the Black Edition brand, the available batteries are the BN36FP-800 and the BN22FA-900.
FIAT TEMPRA (1988/1999): The available battery models in the Fulgor brand are the F36FP-750 and the F22FA-850. In the Black Edition brand, the available batteries are the BN36FP-800 and the BN22FA-900.
FIAT TUCAN (1981/1990): The available battery models in the Fulgor brand are the F36FP-750 and the F22FA-850. In the Black Edition brand, the available batteries are the BN36FP-800 and the BN22FA-900.
FIAT UNO (1981/1992): The available battery models in the Fulgor brand are the F36FP-750 and the F22FA-850. In the Black Edition brand, the available batteries are the BN36FP-800 and the BN22FA-900.
FIAT UNO (2000/2008): The available battery models in the Fulgor brand are the F36FP-750 and the F22FA-850. In the Black Edition brand, the available batteries are the BN36FP-800 and the BN22FA-900.
FIAT UNO A/A (1993/1999): The available battery models in the Fulgor brand are the F36FP-750 and the F22FA-850. In the Black Edition brand, the available batteries are the BN36FP-800 and the BN22FA-900.

FORDFORD AUTOBUSES (1956/2000): The available battery model in the Fulgor brand is the F4D-1350. There are no available models in the Black Edition brand.
FORD BRONCO 6 CIL/ 8 CIL (1989/1997): The available battery model in the Fulgor brand is the F34M-1000. In the Black Edition brand, the available battery is the BN34-1100.
FORD BRONCO SPORT (2023/2024): The available battery model in the Fulgor brand is the F41MR-950. In the Black Edition brand, the available battery is the BN41FXR-1000.
FORD CAMIONES (1987/1999): The available battery models in the Fulgor brand are the F30HC-1250 and the F31T-1250. There are no available models in the Black Edition brand.
FORD CARGO 815 / 817 (2003/2011): The available battery models in the Fulgor brand are the F30HC-1250 and the F31T-1250. There are no available models in the Black Edition brand.
FORD CARGO 1721 (2004/2008): The available battery models in the Fulgor brand are the F30HC-1250 and the F31T-1250. There are no available models in the Black Edition brand.
FORD CARGO 1721 (2008/2015): The available battery model in the Fulgor brand is the F4D-1350. There are no available models in the Black Edition brand.
FORD CARGO 2632 (2005/2014): The available battery models in the Fulgor brand are the F4D-1350 and the F8D-1600. There are no available models in the Black Edition brand.
FORD CARGO 4432 (2005/2014): The available battery models in the Fulgor brand are the F4D-1350 and the F8D-1600. There are no available models in the Black Edition brand.
FORD CARGO 4532 (2005/2014): The available battery models in the Fulgor brand are the F4D-1350 and the F8D-1600. There are no available models in the Black Edition brand.
FORD CONQUISTADOR (1982/2000): The available battery model in the Fulgor brand is the F34M-1000. In the Black Edition brand, the available battery is the BN34-1100.
FORD CORCEL (1983/1987): The available battery model in the Fulgor brand is the F36FP-750. In the Black Edition brand, the available battery is the BN36FP-800.
FORD COUGAR (1980/1987): The available battery model in the Fulgor brand is the F22FA-850. In the Black Edition brand, the available battery is the BN22FA-900.
FORD DEL REY (1983/1987): The available battery models in the Fulgor brand are the F36FP-750 and the F22FA-850. In the Black Edition brand, the available batteries are the BN36FP-800 and the BN22FA-900.
FORD ECONOLINE (1977/1999): The available battery model in the Fulgor brand is the F34M-1000. In the Black Edition brand, the available battery is the BN34-1100.
FORD ECOSPORT (2004/2008): The available battery model in the Fulgor brand is the F36FP-750. In the Black Edition brand, the available battery is the BN36FP-800.
FORD ECOSPORT TITANIUM (2015/2022): The available battery model in the Fulgor brand is the F22FA-850. In the Black Edition brand, the available battery is the BN22FA-900.
FORD ESCAPE (2006/2007): The available battery models in the Fulgor brand are the F22FA-850 and the F41MR-950. In the Black Edition brand, the available batteries are the BN22FA-900 and the BN41FXR-1000.
FORD ESCORT (1988/2000): The available battery model in the Fulgor brand is the F36FP-750. In the Black Edition brand, the available battery is the BN36FP-800.
FORD EXPEDITION (2000/2008): The available battery model in the Fulgor brand is the F65-1200. There are no available models in the Black Edition brand.
FORD EXPEDITION LIMITED (2023/2024): There are no available models in the Fulgor brand. In the Black Edition brand, the available battery is the BN94R-1200.
FORD EXPLORER (1995/2004): The available battery model in the Fulgor brand is the F34M-1000. In the Black Edition brand, the available battery is the BN34-1100.
FORD EXPLORER SPORT TRACK (2005/2015): The available battery model in the Fulgor brand is the F65-1200. There are no available models in the Black Edition brand.
FORD EXPLORER ST (2023/2024): The available battery model in the Fulgor brand is the F41MR-950. In the Black Edition brand, the available battery is the BN41FXR-1000.
FORD F-100 (1965/1982): The available battery model in the Fulgor brand is the F34M-1000. In the Black Edition brand, the available battery is the BN34-1100.
FORD F/150 PICK UP (1973/2005): The available battery model in the Fulgor brand is the F34M-1000. In the Black Edition brand, the available battery is the BN34-1100.
FORD F/350 (1956/1999): The available battery model in the Fulgor brand is the F34M-1000. In the Black Edition brand, the available battery is the BN34-1100.
FORD F/350 (TRITON) (2000/2010): The available battery model in the Fulgor brand is the F65-1200. There are no available models in the Black Edition brand.
FORD F/350 (SUPER DUTY) (2011/2014): The available battery model in the Fulgor brand is the F65-1200. There are no available models in the Black Edition brand.
FORD F750 (1965/2000): The available battery models in the Fulgor brand are the F30HC-1250 and the F31T-1250. There are no available models in the Black Edition brand.
FORD F7000 / F8000 (1980/2002): The available battery models in the Fulgor brand are the F30HC-1250 and the F31T-1250. There are no available models in the Black Edition brand.
FORD FESTIVA (1992/2002): The available battery models in the Fulgor brand are the F36FP-750 and the F22FA-850. In the Black Edition brand, the available batteries are the BN36FP-800 and the BN22FA-900.
FORD FIESTA (1996/2010): The available battery model in the Fulgor brand is the F36FP-750. In the Black Edition brand, the available battery is the BN36FP-800.
FORD FOCUS (2000/2009): The available battery model in the Fulgor brand is the F36FP-750. In the Black Edition brand, the available battery is the BN36FP-800.
FORD FORTALEZA (1997/2008): The available battery model in the Fulgor brand is the F34M-1000. In the Black Edition brand, the available battery is the BN34-1100.
FORD FX4 (2008/2009): The available battery model in the Fulgor brand is the F65-1200. There are no available models in the Black Edition brand.
FORD FUSION (2007/2014): The available battery models in the Fulgor brand are the F36FP-750 and the F22FA-850. In the Black Edition brand, the available batteries are the BN36FP-800 and the BN22FA-900.
FORD GRANADA (1980/1985): The available battery model in the Fulgor brand is the F22FA-850. In the Black Edition brand, the available battery is the BN22FA-900.
FORD GRAND MARQUIS (1992/1997): The available battery model in the Fulgor brand is the F34M-1000. In the Black Edition brand, the available battery is the BN34-1100.
FORD KA (2004/2007): The available battery model in the Fulgor brand is the F36FP-750. In the Black Edition brand, the available battery is the BN36FP-800.
FORD LASER (1992/2004): The available battery model in the Fulgor brand is the F22FA-850. In the Black Edition brand, the available battery is the BN22FA-900.
FORD LTD (1973/1984): The available battery model in the Fulgor brand is the F34M-1000. In the Black Edition brand, the available battery is the BN34-1100.
FORD LINCOLN (1992/1996): The available battery model in the Fulgor brand is the F34M-1000. In the Black Edition brand, the available battery is the BN34-1100.
FORD MUSTANG (1964/1973): The available battery model in the Fulgor brand is the F34M-1000. In the Black Edition brand, the available battery is the BN34-1100.
FORD MUSTANG (1974/1978): The available battery model in the Fulgor brand is the F41MR-950. In the Black Edition brand, the available battery is the BN41FXR-1000.
FORD MUSTANG (1979/1993): The available battery model in the Fulgor brand is the F34M-1000. In the Black Edition brand, the available battery is the BN34-1100.
FORD MUSTANG (1994/2004): The available battery model in the Fulgor brand is the F41MR-950. In the Black Edition brand, the available battery is the BN41FXR-1000.
FORD MUSTANG (2005/2014): The available battery model in the Fulgor brand is the F41MR-950. In the Black Edition brand, the available battery is the BN41FXR-1000.
FORD MUSTANG (2015/2024): The available battery model in the Fulgor brand is the F41MR-950. In the Black Edition brand, the available battery is the BN41FXR-1000.
FORD RANGER (1997/2008): The available battery model in the Fulgor brand is the F41MR-950. In the Black Edition brand, the available battery is the BN41FXR-1000.
FORD RAPTOR (2014/2024): There are no available models in the Fulgor brand. In the Black Edition brand, the available battery is the BN94R-1200.
FORD RAPTOR XLS GASOLINA (2019/2024): There are no available models in the Fulgor brand. In the Black Edition brand, the available battery is the BN94R-1200.
FORD RANGER XLT DIESEL (2019/2024): There are no available models in the Fulgor brand. In the Black Edition brand, the available battery is the BN94R-1200.
FORD RANGER XLT GASOLINA (2019/2024): The available battery model in the Fulgor brand is the F41MR-950. In the Black Edition brand, the available battery is the BN41FXR-1000.
FORD SIERRA (1985/1998): The available battery model in the Fulgor brand is the F41MR-950. In the Black Edition brand, the available battery is the BN41FXR-1000.
FORD SPORT TRAC (2005/2011): The available battery model in the Fulgor brand is the F65-1200. There are no available models in the Black Edition brand.
FORD TAURUS (1995/2001): The available battery model in the Fulgor brand is the F34MR-1000. In the Black Edition brand, the available battery is the BN34-1100.
FORD TERRITORY (2023/2024): The available battery model in the Fulgor brand is the F41MR-950. In the Black Edition brand, the available battery is the BN41FXR-1000.
FORD THUNDERBIRD (1979): The available battery model in the Fulgor brand is the F34M-1000. In the Black Edition brand, the available battery is the BN34-1100.
FORD TRACER (1992/1996): The available battery model in the Fulgor brand is the F86-850. In the Black Edition brand, the available battery is the BN86-900.
FORD TRANSIT VANS XLT (2016/2023): The available battery model in the Fulgor brand is the F41MR-950. In the Black Edition brand, the available battery is the BN41FXR-1000.
FORD ZEPHYR (1980/1985): The available battery model in the Fulgor brand is the F34M-1000. In the Black Edition brand, the available battery is the BN34-1100.

FOTON AUMAN EST (2022/2024): The available battery model in the Fulgor brand is the F4D-1350. There are no available models in the Black Edition brand.
FOTON AUMAN GTL 2540 (2022/2024): The available battery model in the Fulgor brand is the F4D-1350. There are no available models in the Black Edition brand.
FOTON AUMARK E60 (2022/2024): The available battery model in the Fulgor brand is the F24R-1000. In the Black Edition brand, the available battery is the BN24MR-1150.
FOTON AUMARK S E85 (2022/2024): The available battery models in the Fulgor brand are the F27XR-1100 and the F27R-1100. There are no available models in the Black Edition brand.
FOTON THM5H (2023/2024): The available battery model in the Fulgor brand is the F24R-1000. In the Black Edition brand, the available battery is the BN24MR-1150.
FOTON VIEW C2 (2023/2024): The available battery model in the Fulgor brand is the F41M-950. In the Black Edition brand, the available battery is the BN41XR-1000.

FREIGHTLINER 112 (2000/2010): The available battery models in the Fulgor brand are the F30HC-1250 and the F31T-1250. There are no available models in the Black Edition brand.
FREIGHTLINER CULUMBIA CL (2000/2010): The available battery models in the Fulgor brand are the F30HC-1250 and the F31T-1250. There are no available models in the Black Edition brand.
FREIGHTLINER M2-106 (2000/2010): The available battery models in the Fulgor brand are the F30HC-1250 and the F31T-1250. There are no available models in the Black Edition brand.

GREAT WALL DEER (2006/2009): The available battery model in the Fulgor brand is the F34M-1000. In the Black Edition brand, the available battery is the BN34-1100.
GREAT WALL HOVER (2007/2009): The available battery model in the Fulgor brand is the F34M-1000. In the Black Edition brand, the available battery is the BN34-1100.
GREAT WALL PERI (2007/2010): The available battery model in the Fulgor brand is the F22NF-750. In the Black Edition brand, the available battery is the BN22NF-850.
GREAT WALL SAFE (2006/2008): The available battery model in the Fulgor brand is the F34M-1000. In the Black Edition brand, the available battery is the BN34-1100.

HAFEI LOBO (2007): The available battery model in the Fulgor brand is the F36FP-750. In the Black Edition brand, the available battery is the BN36FP-800.
HAFEI MINYI (2007): The available battery models in the Fulgor brand are the FNS40-670 and the F22NF-750. In the Black Edition brand, the available battery is the BN22NF-850.
HAFEI ZHONGYI (2007): The available battery model in the Fulgor brand is the F22NF-750. In the Black Edition brand, the available battery is the BN22NF-850.

HINO BUS (2012/2017): The available battery models in the Fulgor brand are the F27XR-1100 and the F27R-1100. There are no available models in the Black Edition brand.

HONDA ACCORD 4 CIL (1990/1998): The available battery model in the Fulgor brand is the F22FA-850. In the Black Edition brand, the available battery is the BN22FA-900.
HONDA ACCORD 4 CIL (2000/2008): The available battery models in the Fulgor brand are the F22FA-850 and the F34MR-1000. In the Black Edition brand, the available battery is the BN22FA-900.
HONDA ACCORD 6 CIL (2000/2008): The available battery model in the Fulgor brand is the F34MR-1000. There are no available models in the Black Edition brand.
HONDA ACCORD SPORT (2018/2024): The available battery model in the Fulgor brand is the F22FA-850. In the Black Edition brand, the available battery is the BN22FA-900.
HONDA CIVIC (1990/1995): The available battery model in the Fulgor brand is the F22NF-750. In the Black Edition brand, the available battery is the BN22NF-850.
HONDA CIVIC (1996/2000): The available battery model in the Fulgor brand is the F22NF-750. In the Black Edition brand, the available battery is the BN22NF-850.
HONDA CIVIC (2001/2005): The available battery model in the Fulgor brand is the F86-850. In the Black Edition brand, the available battery is the BN86-900.
HONDA CIVIC EMOTION (2006/2011): The available battery model in the Fulgor brand is the F22NF-750. In the Black Edition brand, the available battery is the BN22NF-850.
HONDA CIVIC EVOLUTION (2011/2015): The available battery model in the Fulgor brand is the F22NF-750. In the Black Edition brand, the available battery is the BN22NF-850.
HONDA CIVIC SPORT/TURBO (2016/2021): The available battery model in the Fulgor brand is the F22NF-750. In the Black Edition brand, the available battery is the BN22NF-850.
HONDA CR/V (2000/2008): The available battery model in the Fulgor brand is the F22NF-750. In the Black Edition brand, the available battery is the BN22NF-850.
HONDA CRX (1992/1995): The available battery model in the Fulgor brand is the F22NF-750. In the Black Edition brand, the available battery is the BN22NF-850.
HONDA FIT (2002/2008): The available battery models in the Fulgor brand are the FNS40-670 and the F22NF-750. In the Black Edition brand, the available battery is the BN22NF-850.
HONDA LEGEND (1990/1995): The available battery models in the Fulgor brand are the F86-850 and the F34M-1000. In the Black Edition brand, the available batteries are the BN86-900 and the BN34-1100.
HONDA ODYSSEY (1997/2007): The available battery model in the Fulgor brand is the F34MR-1000. There are no available models in the Black Edition brand.
HONDA PILOT (2006/2007): The available battery model in the Fulgor brand is the F34MR-1000. In the Black Edition brand, the available battery is the BN34-1100.
HONDA PRELUDE (1992/1996): The available battery model in the Fulgor brand is the F34M-1000. There are no available models in the Black Edition brand.
HONDA VIGOR (1992/1995): The available battery model in the Fulgor brand is the F86-850. In the Black Edition brand, the available battery is the BN86-900.
HUMMER
HUMMER H2 (2003/2007): The available battery model in the Fulgor brand is the F34M-1000. In the Black Edition brand, the available battery is the BN34-1100.
HUMMER H3 (2003/2007): The available battery model in the Fulgor brand is the F34M-1000. In the Black Edition brand, the available battery is the BN34-1100.

HYUNDAI ACCENT (1997/2008): The available battery models in the Fulgor brand are the F36FP-750 and the F22FA-850. In the Black Edition brand, the available batteries are the BN36FP-800 and the BN22FA-900.
HYUNDAI ACCENT (2012/2017): The available battery models in the Fulgor brand are the F36FP-750 and the F22FA-850. In the Black Edition brand, the available batteries are the BN36FP-800 and the BN22FA-900.
HYUNDAI ACCENT (2024/2025): The available battery model in the Fulgor brand is the F36FP-750. In the Black Edition brand, the available battery is the BN36FP-800.
HYUNDAI ATOS PRIME (2006/2008): The available battery models in the Fulgor brand are the FNS40-670 and the F22NF-750. In the Black Edition brand, the available battery is the BN22NF-850.
HYUNDAI ELANTRA (1992/2001): The available battery model in the Fulgor brand is the F86-800. In the Black Edition brand, the available battery is the BN86-900.
HYUNDAI ELANTRA (2002/2018): The available battery model in the Fulgor brand is the F22FA-850. In the Black Edition brand, the available batteries are the BN22FA-900 and the BN22FA-900.
HYUNDAI ELANTRA (2022/2024): The available battery model in the Fulgor brand is the F22FA-850. In the Black Edition brand, the available battery is the BN22FA-900.
HYUNDAI EXCEL (1992/1999): The available battery models in the Fulgor brand are the F36FP-750 and the F22FA-850. In the Black Edition brand, the available batteries are the BN36FP-800 and the BN22FA-900.
HYUNDAI GALLOPER (1997/2001): The available battery model in the Fulgor brand is the F34MR-1000. There are no available models in the Black Edition brand.
HYUNDAI GETZ (2007/2010): The available battery models in the Fulgor brand are the F36FP-750 and the F22FA-850. In the Black Edition brand, the available batteries are the BN36FP-800 and the BN22FA-900.
HYUNDAI GETZ GLS-GNV (2011/2012): The available battery model in the Fulgor brand is the F22NF-750. In the Black Edition brand, the available battery is the BN22NF-850.
HYUNDAI Gi10 (2022/2024): The available battery model in the Fulgor brand is the FNS40-670. There are no available models in the Black Edition brand.
HYUNDAI H/100 (1997/1999): The available battery models in the Fulgor brand are the F27XR-1100 and the F27R-1100. There are no available models in the Black Edition brand.
HYUNDAI H1 (2007/2012): The available battery model in the Fulgor brand is the F34M-1000. In the Black Edition brand, the available battery is the BN34-1100.
HYUNDAI HD36L (2022/2024): The available battery models in the Fulgor brand are the F27XR-1100 and the F27R-1100. There are no available models in the Black Edition brand.
HYUNDAI MATRIX (1997/2010): The available battery models in the Fulgor brand are the F36FP-750 and the F22FA-850. In the Black Edition brand, the available batteries are the BN36FP-800 and the BN22FA-900.
HYUNDAI PALISADE (2022/2024): There are no available models in the Fulgor brand. In the Black Edition brand, the available battery is the BN94R-1200.
HYUNDAI SANTA FÉ (2001/2019): The available battery model in the Fulgor brand is the F34MR-1000. There are no available models in the Black Edition brand.
HYUNDAI SANTA FE (2023/2024): The available battery model in the Fulgor brand is the F41MR-950. In the Black Edition brand, the available battery is the BN41FXR-1000.
HYUNDAI SONATA (1992/2001): The available battery model in the Fulgor brand is the F34MR-1000. There are no available models in the Black Edition brand.
HYUNDAI SONATA (2002/2016): The available battery model in the Fulgor brand is the F34MR-1000. There are no available models in the Black Edition brand.
HYUNDAI STARIA (2023/2024): There are no available models in the Fulgor brand. In the Black Edition brand, the available battery is the BN94R-1200.
HYUNDAI TIBURON (COUPE) (1997/2007): The available battery model in the Fulgor brand is the F22FA-850. In the Black Edition brand, the available battery is the BN22FA-900.
HYUNDAI TUCSON (2005/2012): The available battery models in the Fulgor brand are the F22FA-850 and the F34MR-1000. In the Black Edition brand, the available battery is the BN22FA-900.
HYUNDAI TUCSON (2022/2024): The available battery models in the Fulgor brand are the F22FA-850 and the F41MR-950. In the Black Edition brand, the available batteries are the BN22FA-900 and the BN41FXR-1000.
HYUNDAI VELOSTER (2012/2016): The available battery models in the Fulgor brand are the F36FP-750 and the F22FA-850. In the Black Edition brand, the available batteries are the BN36FP-800 and the BN22FA-900.

IKCO DENA + (2022/2024): The available battery models in the Fulgor brand are the F36FP-750 and the F22FA-850. In the Black Edition brand, the available batteries are the BN36FP-800 and the BN22FA-900.
IKCO TARA (2022/2024): The available battery models in the Fulgor brand are the F36FP-750 and the F22FA-850. In the Black Edition brand, the available batteries are the BN36FP-800 and the BN22FA-900.

INTERNATIONAL 1700 (1971/1990): The available battery models in the Fulgor brand are the F30HC-1250 and the F31T-1250. There are no available models in the Black Edition brand.
INTERNATIONAL 1800 (1980/1990): The available battery models in the Fulgor brand are the F30HC-1250 and the F31T-1250. There are no available models in the Black Edition brand.
INTERNATIONAL 2050 (1971/1990): The available battery models in the Fulgor brand are the F30HC-1250 and the F31T-1250. There are no available models in the Black Edition brand.
INTERNATIONAL 5000 (1980/1991): The available battery models in the Fulgor brand are the F30HC-1250 and the F31T-1250. There are no available models in the Black Edition brand.
INTERNATIONAL 5070 (1971/1990): The available battery models in the Fulgor brand are the F30HC-1250 and the F31T-1250. There are no available models in the Black Edition brand.
INTERNATIONAL 7600 (2012): The available battery models in the Fulgor brand are the F30HC-1250 and the F31T-1250. There are no available models in the Black Edition brand.

ISUZU AMIGO (1992/2000): The available battery model in the Fulgor brand is the F86-850. In the Black Edition brand, the available battery is the BN86-900.
ISUZU CARIBE 442 (1982/1993): The available battery model in the Fulgor brand is the F86-850. In the Black Edition brand, the available battery is the BN86-900.
ISUZU RODEO (1991/2000): The available battery model in the Fulgor brand is the F34MR-1000. There are no available models in the Black Edition brand.
ISUZU SIDEKICK (1992/1994): The available battery model in the Fulgor brand is the F22FA-850. In the Black Edition brand, the available battery is the BN22FA-900.
ISUZU TROOPER (1992/2001): The available battery model in the Fulgor brand is the F34M-1000. In the Black Edition brand, the available battery is the BN34-1100.

IVECO DAILY GNV (2011/2012): The available battery models in the Fulgor brand are the F27XR-1100 and the F27R-1100. There are no available models in the Black Edition brand.
IVECO DAILY LIVIANOS (1998/2011): The available battery models in the Fulgor brand are the F27XR-1100 and the F27R-1100. There are no available models in the Black Edition brand.
IVECO NEW STRALIS (1983/2011): The available battery models in the Fulgor brand are the F30HC-1250 and the F31T-1250. There are no available models in the Black Edition brand.
IVECO POWER DAILY (2012/2016): The available battery models in the Fulgor brand are the F27XR-1100 and the F27R-1100. There are no available models in the Black Edition brand.
IVECO SERIE EUROCARGO (1989/2003): The available battery models in the Fulgor brand are the F30HC-1250 and the F31T-1250. There are no available models in the Black Edition brand.
IVECO SERIE EURO TECTOR (1998/2011): The available battery models in the Fulgor brand are the F30HC-1250 and the F31T-1250. There are no available models in the Black Edition brand.
IVECO SERIE EUROTRAKKER (1983/2011): The available battery model in the Fulgor brand is the F4D-1350. There are no available models in the Black Edition brand.
IVECO SERIE STRALIS (1983/2011): The available battery model in the Fulgor brand is the F4D-1350. There are no available models in the Black Edition brand.
IVECO VERTIS (2012/2016): The available battery models in the Fulgor brand are the F30HC-1250 and the F31T-1250. There are no available models in the Black Edition brand.

JAC 1040 (2000/2015): The available battery models in the Fulgor brand are the F27XR-1100 and the F27R-1100. In the Black Edition brand, the available battery is the BN24MR-1150.
JAC 1040/1042 (2015/2024): The available battery models in the Fulgor brand are the F27XR-1100 and the F27R-1100. There are no available models in the Black Edition brand.
JAC 1061 (2000/2015): The available battery models in the Fulgor brand are the F27XR-1100 and the F27R-1100. In the Black Edition brand, the available battery is the BN24MR-1150.
JAC 1063 (2015/2017): The available battery models in the Fulgor brand are the F30HC-1250 and the F31T-1250. There are no available models in the Black Edition brand.
JAC 1134 (2015/2017): The available battery model in the Fulgor brand is the F4D-1350. There are no available models in the Black Edition brand.
JAC 4253 (2000/2015): The available battery model in the Fulgor brand is the F4D-1350. There are no available models in the Black Edition brand.
JAC ARENA JS2 (2023/2024): The available battery model in the Fulgor brand is the F86-850. In the Black Edition brand, the available battery is the BN86-900.
JAC AVENTURA DIESEL T9 (2023/2024): The available battery model in the Fulgor brand is the F27XR-1100. There are no available models in the Black Edition brand.
JAC AVENTURA GASOLINA T9 (2023/2024): The available battery model in the Fulgor brand is the F27XR-1100. There are no available models in the Black Edition brand.
JAC BUFALO HFC1131KR1 (2023/2024): The available battery model in the Fulgor brand is the F4D-1350. There are no available models in the Black Edition brand.
JAC E40X ELECTRICO (2023/2024): The available battery model in the Fulgor brand is the F22NF-750. In the Black Edition brand, the available battery is the BN22NF-850.
JAC EJS1 ELECTRICO (2023/2024): The available battery model in the Fulgor brand is the F22NF-750. In the Black Edition brand, the available battery is the BN22NF-850.
JAC EXTREME FC1037D3ESV T8 (2023/2024): The available battery model in the Fulgor brand is the F34M-1000. In the Black Edition brand, the available battery is the BN34-1100.
JAC HFC1030P (X100) (2023/2024): The available battery model in the Fulgor brand is the F24R-1000. In the Black Edition brand, the available battery is the BN24MR-1150.
JAC HFC1071L1K-N75S (2023/2024): The available battery models in the Fulgor brand are the F27XR-1100 and the F27R-1100. There are no available models in the Black Edition brand.
JAC HFC1090L1KT-N90L (2023/2024): The available battery models in the Fulgor brand are the F27XR-1100 and the F27R-1100. There are no available models in the Black Edition brand.
JAC HFC1254KR1 (2023/2024): The available battery models in the Fulgor brand are the F30HC-1250 and the F31T-1250. There are no available models in the Black Edition brand.
JAC HFC4160 (2023/2024): The available battery model in the Fulgor brand is the F4D-1350. There are no available models in the Black Edition brand.
JAC HFC4251KR1K3/ HFC4251KR1 (2023/2024): The available battery model in the Fulgor brand is the F4D-1350. There are no available models in the Black Edition brand.
JAC K8 AUTOBUS 26 PUESTOS (2023/2024): The available battery models in the Fulgor brand are the F30HC-1250 and the F31T-1250. There are no available models in the Black Edition brand.
JAC LA VENEZOLANA DIESEL T6 (2018/2024): The available battery model in the Fulgor brand is the F34M-1000. In the Black Edition brand, the available battery is the BN34-1100.
JAC LA VENEZOLANA GASOLINA T6 (2018/2024): The available battery model in the Fulgor brand is the F34M-1000. In the Black Edition brand, the available battery is the BN34-1100.
JAC M4 CARGA (2023/2024): The available battery model in the Fulgor brand is the F41M-950. In the Black Edition brand, the available battery is the BN41XR-1000.
JAC MINERO HFC3255K1R1/HFC3310K3R1 (2023/2024): The available battery model in the Fulgor brand is the F4D-1350. There are no available models in the Black Edition brand.
JAC NEVADO JS4 (2023/2024): The available battery model in the Fulgor brand is the F22FA-850. In the Black Edition brand, the available battery is the BN22FA-900.
JAC SAVANNA JS8 PRO (2023/2024): The available battery model in the Fulgor brand is the F22FA-850. In the Black Edition brand, the available battery is the BN22FA-900.
JAC SUNRAY CARGO DIESEL (2023/2024): The available battery models in the Fulgor brand are the F34M-1000 and the F27R-1100. In the Black Edition brand, the available battery is the BN34-1100.
JAC SUNRAY PASAJEROS (2023/2024): The available battery models in the Fulgor brand are the F34M-1000 and the F27R-1100. In the Black Edition brand, the available battery is the BN34-1100.
JAC TEPUY JS6 (2023/2024): The available battery model in the Fulgor brand is the F22FA-850. In the Black Edition brand, the available battery is the BN22FA-900.
JAC VAN M4 (2023/2024): The available battery model in the Fulgor brand is the F41M-950. In the Black Edition brand, the available battery is the BN41XR-1000.
JAC XL HFC1235K3R1L (2023/2024): The available battery model in the Fulgor brand is the F4D-1350. There are no available models in the Black Edition brand.

JEEP CHEROKEE KK (2008/2014): The available battery model in the Fulgor brand is the F34M-1000. In the Black Edition brand, the available battery is the BN34-1100.
JEEP CHEROKEE LIBERTY (2002/2007): The available battery model in the Fulgor brand is the F86-850. In the Black Edition brand, the available battery is the BN86-900.
JEEP CHEROKEE T270 RENEGADO SPORT (2023/2024): The available battery model in the Fulgor brand is the F41MR-950. In the Black Edition brand, the available battery is the BN41FXR-1000.
JEEP CHEROKEE XJ (1989/2002): The available battery model in the Fulgor brand is the F34M-1000. In the Black Edition brand, the available battery is the BN34-1100.
JEEP CJ / SERIES (1980/1990): The available battery model in the Fulgor brand is the F34M-1000. In the Black Edition brand, the available battery is the BN34-1100.
JEEP COMANCHE (1986/1992): The available battery model in the Fulgor brand is the F34M-1000. In the Black Edition brand, the available battery is the BN34-1100.
JEEP COMMANDER (2007/2010): The available battery model in the Fulgor brand is the F34MR-1000. There are no available models in the Black Edition brand.
JEEP COMPASS (2007/2012): The available battery model in the Fulgor brand is the F86-850. In the Black Edition brand, the available battery is the BN86-900.
JEEP COMPASS T270 (2023/2024): The available battery model in the Fulgor brand is the F41MR-950. In the Black Edition brand, the available battery is the BN41FXR-1000.
JEEP GRAND CHEROKEE LAREDO (1993/1998): The available battery model in the Fulgor brand is the F34M-1000. In the Black Edition brand, the available battery is the BN34-1100.
JEEP GRAND CHEROKEE WJ (1999/2005): The available battery model in the Fulgor brand is the F34M-1000. In the Black Edition brand, the available battery is the BN34-1100.
JEEP GRAND CHEROKEE WK (2006/2010): The available battery models in the Fulgor brand are the F34MR-1000 and the F41MR-950. In the Black Edition brand, the available battery is the BN41FXR-1000.
JEEP GRAND CHEROKEE WK-2 (4G) (2011/2013): There are no available models in the Fulgor brand. In the Black Edition brand, the available battery is the BN94R-1200.
JEEP GRAND WAGONEER (1979/1993): The available battery model in the Fulgor brand is the F34M-1000. In the Black Edition brand, the available battery is the BN34-1100.
JEEP RENEGADE/ WRANGLER (1995/2005): The available battery model in the Fulgor brand is the F34M-1000. In the Black Edition brand, the available battery is the BN34-1100.
JEEP RUBICON (2008/2019): The available battery model in the Fulgor brand is the F34MR-1000. There are no available models in the Black Edition brand.
JEEP WRANGLER (1987/2002): The available battery model in the Fulgor brand is the F34MR-1000. There are no available models in the Black Edition brand.

JETOUR X70/X70 PLUS (2023/2024): The available battery model in the Fulgor brand is the F41MR-950. In the Black Edition brand, the available battery is the BN41FXR-1000.

JMC BOARDING DIESEL (2023/2024): The available battery model in the Fulgor brand is the F27R-1100. There are no available models in the Black Edition brand.
JMC CONQUER N800 (2023/2024): The available battery models in the Fulgor brand are the F27XR-1100 and the F27R-1100. In the Black Edition brand, the available battery is the BN24MR-1150.
JMC GRAND AVENUE (2023/2024): There are no available models in the Fulgor brand. In the Black Edition brand, the available battery is the BN94R-1200.
JMC JIM RE-MAX S (2023/2024): The available battery model in the Fulgor brand is the F27XR-1100. There are no available models in the Black Edition brand.
JMC NEW CARRYING N697 2.8T (2023/2024): The available battery model in the Fulgor brand is the F24R-1000. In the Black Edition brand, the available battery is the BN24MR-1150.
JMC TOURING CARGA / PASAJERO (2023/2024): The available battery model in the Fulgor brand is the F27XR-1100. There are no available models in the Black Edition brand.
JMC VIGUS DIESEL (2023/2024): The available battery model in the Fulgor brand is the F27XR-1100. There are no available models in the Black Edition brand.
JMC VIGUS PRO PLUS (2023/2024): The available battery model in the Fulgor brand is the F41MR-950. In the Black Edition brand, the available battery is the BN41FXR-1000.

KARRY PANEL/PASAJERO (2022/2024): The available battery model in the Fulgor brand is the F22NF-750. In the Black Edition brand, the available battery is the BN22NF-850.
KARRY YOKI (2022/2024): The available battery model in the Fulgor brand is the F22NF-750. In the Black Edition brand, the available battery is the BN22NF-850.

KENWORTH TODOS (1980/2010): The available battery models in the Fulgor brand are the F30HC-1250 and the F31T-1250. There are no available models in the Black Edition brand.

KIA CARENS (2000/2007): The available battery model in the Fulgor brand is the F22FA-850. In the Black Edition brand, the available battery is the BN22FA-900.
KIA CARNIVAL (2000/2004): The available battery model in the Fulgor brand is the F34MR-1000. There are no available models in the Black Edition brand.
KIA CARNIVAL (2023/2024): There are no available models in the Fulgor brand. In the Black Edition brand, the available battery is the BN94R-1200.
KIA CERATO (2006/2009): The available battery model in the Fulgor brand is the F22FA-850. In the Black Edition brand, the available battery is the BN22FA-900.
KIA CERATO (2015): The available battery model in the Fulgor brand is the F36FP-750. In the Black Edition brand, the available battery is the BN36FP-800.
KIA OPIRUS (2006/2008): The available battery models in the Fulgor brand are the F24R-1000 and the F34MR-1000. In the Black Edition brand, the available battery is the BN24MR-1150.
KIA OPTIMA (2005/2009): The available battery model in the Fulgor brand is the F34MR-1000. There are no available models in the Black Edition brand.
KIA PICANTO (2005/2009): The available battery model in the Fulgor brand is the FNS40-670. There are no available models in the Black Edition brand.
KIA PICANTO (2023/2024): The available battery model in the Fulgor brand is the F36FP-750. In the Black Edition brand, the available battery is the BN36FP-800.
KIA PREGIO (2002/2010): The available battery model in the Fulgor brand is the F34M-1000. In the Black Edition brand, the available battery is the BN34-1100.
KIA RIO (2000/2012): The available battery models in the Fulgor brand are the F36FP-750 and the F22FA-850. In the Black Edition brand, the available batteries are the BN36FP-800 and the BN22FA-900.
KIA RIO (2023/2024): The available battery model in the Fulgor brand is the F36FP-750. In the Black Edition brand, the available battery is the BN36FP-800.
KIA SEDONA (2000/2009): The available battery model in the Fulgor brand is the F34MR-1000. There are no available models in the Black Edition brand.
KIA SELTOS (2023/2024): The available battery models in the Fulgor brand are the F36FP-750 and the F22FA-850. In the Black Edition brand, the available batteries are the BN36FP-800 and the BN22FA-900.
KIA SEPHIA (1999/2001): The available battery models in the Fulgor brand are the F36FP-750 and the F22FA-850. In the Black Edition brand, the available batteries are the BN36FP-800 and the BN22FA-900.
KIA SHUMA (2000/2002): The available battery model in the Fulgor brand is the F22FA-850. In the Black Edition brand, the available battery is the BN22FA-900.
KIA SOLUTO (2023/2024): The available battery model in the Fulgor brand is the F22NF-750. In the Black Edition brand, the available battery is the BN22NF-850.
KIA SONET (2023/2024): The available battery model in the Fulgor brand is the F36FP-750. In the Black Edition brand, the available battery is the BN36FP-800.
KIA SORENTO (2004/2009): The available battery model in the Fulgor brand is the F34M-1000. In the Black Edition brand, the available battery is the BN34-1100.
KIA SORENTO (2023/2024): There are no available models in the Fulgor brand. In the Black Edition brand, the available battery is the BN94R-1200.
KIA SPECTRA (2002/2003): The available battery model in the Fulgor brand is the F22FA-850. In the Black Edition brand, the available battery is the BN22FA-900.
KIA SPORTAGE (1999/2010): The available battery model in the Fulgor brand is the F34MR-1000. There are no available models in the Black Edition brand.
KIA SPORTAGE (2023/2024): The available battery model in the Fulgor brand is the F22FA-850. In the Black Edition brand, the available battery is the BN22FA-900.

LADA MATRIOSKA (1992/1996): The available battery models in the Fulgor brand are the F36FP-750 and the F22FA-850. In the Black Edition brand, the available batteries are the BN36FP-800 and the BN22FA-900.
LADA NIVA (1992/1996): The available battery model in the Fulgor brand is the F34M-1000. In the Black Edition brand, the available battery is the BN34-1100.
LADA SAMARA (1992/1996): The available battery model in the Fulgor brand is the F41MR-950. In the Black Edition brand, the available battery is the BN41FXR-1000.

LAND ROVER DEFENDER (1998/2001): The available battery model in the Fulgor brand is the F34M-1000. In the Black Edition brand, the available battery is the BN34-1100.
LAND ROVER DISCOVERY (1992/2001): The available battery model in the Fulgor brand is the F34M-1000. In the Black Edition brand, the available battery is the BN34-1100.
LAND ROVER RANGE ROVER (1956/2019): The available battery model in the Fulgor brand is the F34M-1000. In the Black Edition brand, the available battery is the BN34-1100.

LEXUS 300 (1991/1997): The available battery model in the Fulgor brand is the F24R-1000. In the Black Edition brand, the available battery is the BN24MR-1150.
LEXUS 400 (1991/1997): The available battery model in the Fulgor brand is the F34MR-1000. There are no available models in the Black Edition brand.
LEXUS ES (1989/2006): The available battery model in the Fulgor brand is the F41MR-950. In the Black Edition brand, the available battery is the BN41FXR-1000.
LEXUS GS (1993/2011): The available battery model in the Fulgor brand is the F24R-1000. In the Black Edition brand, the available battery is the BN24MR-1150.
LEXUS GX460 (2020/2023): The available battery model in the Fulgor brand is the F24R-1000. In the Black Edition brand, the available battery is the BN24MR-1150.
LEXUS LS (1989/2006): The available battery model in the Fulgor brand is the F24R-1000. In the Black Edition brand, the available battery is the BN24MR-1150.
LEXUS LX (1996/2008): The available battery model in the Fulgor brand is the F24R-1000. In the Black Edition brand, the available battery is the BN24MR-1150.
LEXUS LX 570 (2018/2023): The available battery model in the Fulgor brand is the F27R-1100. In the Black Edition brand, the available battery is the BN94R-1200.
LEXUS RX (1998/2008): The available battery model in the Fulgor brand is the F24R-1000. In the Black Edition brand, the available battery is the BN24MR-1150.

LIFAN 520 TALENT (2008/2009): The available battery model in the Fulgor brand is the F36FP-750. In the Black Edition brand, the available battery is the BN36FP-800.

LINCOLN NAVIGATOR (2006/2010): The available battery model in the Fulgor brand is the F65-1200. There are no available models in the Black Edition brand.
LINCOLN TOWN CAR (1990/2010): The available battery model in the Fulgor brand is the F41MR-950. In the Black Edition brand, the available battery is the BN41FXR-1000.

MACK CH-613 (1996/2002): The available battery models in the Fulgor brand are the F30HC-1250 and the F31T-1250. There are no available models in the Black Edition brand.
MACK CHHD Y CHLD (1997/2005): The available battery models in the Fulgor brand are the F30HC-1250 and the F31T-1250. There are no available models in the Black Edition brand.
MACK GRANITE VISION (2004/2006): The available battery models in the Fulgor brand are the F30HC-1250 and the F31T-1250. There are no available models in the Black Edition brand.
MACK MIDLINER (1996/2005): The available battery models in the Fulgor brand are the F30HC-1250 and the F31T-1250. There are no available models in the Black Edition brand.
MACK RDHD Y RDLD (1989/2005): The available battery models in the Fulgor brand are the F30HC-1250 and the F31T-1250. There are no available models in the Black Edition brand.
MACK SERIE R600 (1966/1996): The available battery models in the Fulgor brand are the F30HC-1250 and the F31T-1250. There are no available models in the Black Edition brand.

MAXUS D60 (2022/2024): The available battery model in the Fulgor brand is the F41MR-950. In the Black Edition brand, the available battery is the BN41FXR-1000.
MAXUS T60 (2022/2024): The available battery model in the Fulgor brand is the F41MR-950. In the Black Edition brand, the available battery is the BN41FXR-1000.

MAZDA 3 (2005/2009): The available battery model in the Fulgor brand is the F24R-1000. In the Black Edition brand, the available battery is the BN24MR-1150.
MAZDA 323 (1992/2003): The available battery models in the Fulgor brand are the F36FP-750 and the F22FA-850. In the Black Edition brand, the available batteries are the BN36FP-800 and the BN22FA-900.
MAZDA 5 (2005/2007): The available battery model in the Fulgor brand is the F24R-1000. In the Black Edition brand, the available battery is the BN24MR-1150.
MAZDA 6 (2004/2008): The available battery model in the Fulgor brand is the F24R-1000. In the Black Edition brand, the available battery is the BN24MR-1150.
MAZDA 626 (1992/2005): The available battery models in the Fulgor brand are the F22FA-850 and the F34M-1000. In the Black Edition brand, the available batteries are the BN22FA-900 and the BN34-1100.
MAZDA 929 (1992/1995): The available battery model in the Fulgor brand is the F34M-1000. In the Black Edition brand, the available battery is the BN34-1100.
MAZDA ALLEGRO (1994/2008): The available battery models in the Fulgor brand are the F36FP-750 and the F22FA-850. In the Black Edition brand, the available batteries are the BN36FP-800 and the BN22FA-900.
MAZDA B2600 (1992/2007): The available battery model in the Fulgor brand is the F34M-1000. In the Black Edition brand, the available battery is the BN34-1100.
MAZDA B400 (1998/2005): The available battery model in the Fulgor brand is the F34M-1000. In the Black Edition brand, the available battery is the BN34-1100.
MAZDA BT/50 (2008/2009): The available battery model in the Fulgor brand is the F34M-1000. In the Black Edition brand, the available battery is the BN34-1100.
MAZDA CX3/CX5/CX30 (2023/2024): The available battery model in the Fulgor brand is the F86-850. In the Black Edition brand, the available battery is the BN86-900.
MAZDA CX7 (2008/2010): The available battery model in the Fulgor brand is the F24R-1000. In the Black Edition brand, the available battery is the BN24MR-1150.
MAZDA CX9 (2008/2010): The available battery model in the Fulgor brand is the F24R-1000. In the Black Edition brand, the available battery is the BN24MR-1150.
MAZDA DEMIO (2005/2008): The available battery model in the Fulgor brand is the F36FP-750. In the Black Edition brand, the available battery is the BN36FP-800.
MAZDA MIATA (1992/1998): The available battery model in the Fulgor brand is the FNS40-670. There are no available models in the Black Edition brand.
MAZDA MPV (1992/2004): The available battery model in the Fulgor brand is the F22FA-850. In the Black Edition brand, the available battery is the BN22FA-900.
MAZDA MX3 (1992/2009): The available battery model in the Fulgor brand is the F22FA-850. In the Black Edition brand, the available battery is the BN22FA-900.
MAZDA MX5 (2010/2018): The available battery model in the Fulgor brand is the F22NF-750. In the Black Edition brand, the available battery is the BN22NF-850.
MAZDA MX6 (1993/1994): The available battery model in the Fulgor brand is the F34MR-1000. There are no available models in the Black Edition brand.

MERCEDES BENZ 500SEL (1991/2016): The available battery model in the Fulgor brand is the F41MR-950. In the Black Edition brand, the available battery is the BN41FXR-1000.
MERCEDES BENZ 600SEL (1991/2017): The available battery model in the Fulgor brand is the F41MR-950. In the Black Edition brand, the available battery is the BN41FXR-1000.
MERCEDES BENZ 711 (2007/2011): The available battery models in the Fulgor brand are the F27XR-1100 and the F27R-1100. There are no available models in the Black Edition brand.
MERCEDES BENZ AUTOBUSES (1958/1999): The available battery models in the Fulgor brand are the F30HC-1250 and the F31T-1250. There are no available models in the Black Edition brand.
MERCEDES BENZ CLASE A (2001/2008): The available battery models in the Fulgor brand are the F22FA-850 and the F41MR-950. In the Black Edition brand, the available batteries are the BN22FA-900 and the BN41FXR-1000.
MERCEDES BENZ CLASE B 200 (2006/2012): The available battery models in the Fulgor brand are the F86-850 and the F34M-1000. In the Black Edition brand, the available batteries are the BN86-900 and the BN34-1100.
MERCEDES BENZ CLASE C (1970/2009): The available battery models in the Fulgor brand are the F22FA-850 and the F41MR-950. In the Black Edition brand, the available batteries are the BN22FA-900 and the BN41FXR-1000.
MERCEDES BENZ CLASE E (1986/2008): There are no available models in the Fulgor brand. In the Black Edition brand, the available battery is the BN94R-1200.
MERCEDES BENZ CLASE G (2016): There are no available models in the Fulgor brand. In the Black Edition brand, the available battery is the BN94R-1200.
MERCEDES BENZ CLASE S (1975/2001): The available battery model in the Fulgor brand is the F41MR-950. In the Black Edition brand, the available battery is the BN41FXR-1000.
MERCEDES BENZ E 190 (1991/1998): The available battery model in the Fulgor brand is the F41MR-950. In the Black Edition brand, the available battery is the BN41FXR-1000.
MERCEDES BENZ E 300 (1991/1999): The available battery model in the Fulgor brand is the F41MR-950. In the Black Edition brand, the available battery is the BN41FXR-1000.
MERCEDES BENZ LS 1634 (2005/2009): The available battery model in the Fulgor brand is the F4D-1350. There are no available models in the Black Edition brand.
MERCEDES BENZ LS 2640 (2005/2010): The available battery model in the Fulgor brand is the F4D-1350. There are no available models in the Black Edition brand.
MERCEDES BENZ MB 303 (1990/2012): The available battery model in the Fulgor brand is the F4D-1350. There are no available models in the Black Edition brand.
MERCEDES BENZ ML 300 (2013/2018): There are no available models in the Fulgor brand. In the Black Edition brand, the available battery is the BN94R-1200.
MERCEDES BENZ PANEL (1990/1999): The available battery model in the Fulgor brand is the F22NF-750. In the Black Edition brand, the available battery is the BN22NF-850.
MERCEDES BENZ SPRINTER (2004/2008): The available battery models in the Fulgor brand are the F27XR-1100 and the F27R-1100. There are no available models in the Black Edition brand.

MG MG3 (2022/2024): The available battery models in the Fulgor brand are the F22FA-850 and the F41MR-950. In the Black Edition brand, the available batteries are the BN22FA-900 and the BN41FXR-1000.
MG RX8 (2022/2024): The available battery models in the Fulgor brand are the F36FP-750 and the F22FA-850. In the Black Edition brand, the available batteries are the BN36FP-800 and the BN22FA-900.
MG ZS (2022/2024): The available battery models in the Fulgor brand are the F22FA-850 and the F41MR-950. In the Black Edition brand, the available batteries are the BN22FA-900 and the BN41FXR-1000.

MINI COOPER (2005/2010): The available battery model in the Fulgor brand is the F36FP-750. In the Black Edition brand, the available battery is the BN36FP-800.

MITSUBISHI 3000 GT (1991/1999): The available battery models in the Fulgor brand are the F22FA-850 and the F41MR-950. In the Black Edition brand, the available batteries are the BN22FA-900 and the BN41FXR-1000.
MITSUBISHI ASX GASOLINA (2022/2024): The available battery model in the Fulgor brand is the F22FA-850. In the Black Edition brand, the available battery is the BN22FA-900.
MITSUBISHI ATTRAGE/MIRAGE (2022/2024): The available battery model in the Fulgor brand is the F22FA-850. In the Black Edition brand, the available battery is the BN22FA-900.
MITSUBISHI CANTER 12V (1992/2007): The available battery models in the Fulgor brand are the F27XR-1100 and the F27R-1100. There are no available models in the Black Edition brand.
MITSUBISHI CANTER 24V (2011/2015): The available battery model in the Fulgor brand is the F24R-1000. In the Black Edition brand, the available battery is the BN24MR-1150.
MITSUBISHI COLT (1993/2008): The available battery model in the Fulgor brand is the F22FA-850. In the Black Edition brand, the available battery is the BN22FA-900.
MITSUBISHI DIAMANTE (1992/1997): The available battery model in the Fulgor brand is the F86-850. In the Black Edition brand, the available battery is the BN86-900.
MITSUBISHI ECLIPSE (1992/1994): The available battery model in the Fulgor brand is the F86-850. In the Black Edition brand, the available battery is the BN86-900.
MITSUBISHI ECLIPSE G3 (1995/2008): The available battery models in the Fulgor brand are the F22FA-850 and the F41MR-950. In the Black Edition brand, the available batteries are the BN22FA-900 and the BN41FXR-1000.
MITSUBISHI FUSO CARTER (2022/2024): The available battery model in the Fulgor brand is the F86-850. In the Black Edition brand, the available battery is the BN86-900.
MITSUBISHI GALANT (1993/2005): The available battery model in the Fulgor brand is the F22FA-850. In the Black Edition brand, the available battery is the BN22FA-900.
MITSUBISHI GRANDIS (2003/2011): The available battery model in the Fulgor brand is the F34MR-1000. There are no available models in the Black Edition brand.
MITSUBISHI L200 SPORTERO DIESEL (2021/2024): The available battery model in the Fulgor brand is the F27XR-1100. In the Black Edition brand, the available battery is the BN24MR-1150.
MITSUBISHI L200 SPORTERO GASOLINA (2008/2012): The available battery model in the Fulgor brand is the F34MR-1000. There are no available models in the Black Edition brand.
MITSUBISHI L200 SPORTERO GASOLINA (2021/2024): The available battery model in the Fulgor brand is the F34MR-1000. In the Black Edition brand, the available battery is the BN24MR-1150.
MITSUBISHI LANCER (1992/2015): The available battery model in the Fulgor brand is the F22FA-850. In the Black Edition brand, the available battery is the BN22FA-900.
MITSUBISHI MF/MX (1993/1995): The available battery model in the Fulgor brand is the F86-850. In the Black Edition brand, the available battery is the BN86-900.
MITSUBISHI MF/MX/ZX (1998/2001): The available battery model in the Fulgor brand is the F22FA-850. In the Black Edition brand, the available battery is the BN22FA-900.
MITSUBISHI MIRAGE (1993/2001): The available battery models in the Fulgor brand are the F36FP-750 and the F22FA-850. In the Black Edition brand, the available batteries are the BN36FP-800 and the BN22FA-900.
MITSUBISHI MONTERO DAKAR (1992/2010): The available battery model in the Fulgor brand is the F34M-1000. In the Black Edition brand, the available battery is the BN34-1100.
MITSUBISHI MONTERO LIMITED (2007/2009): The available battery model in the Fulgor brand is the F24R-1000. In the Black Edition brand, the available battery is the BN24MR-1150.
MITSUBISHI MONTERO SPORT (2000/2012): The available battery model in the Fulgor brand is the F34M-1000. In the Black Edition brand, the available battery is the BN34-1100.
MITSUBISHI MONTERO SPORT (2013/2016): The available battery model in the Fulgor brand is the F24R-1000. In the Black Edition brand, the available battery is the BN24MR-1150.
MITSUBISHI OUTLANDER (2018/2020): The available battery model in the Fulgor brand is the F34MR-1000. There are no available models in the Black Edition brand.
MITSUBISHI OUTLANDER (2022/2024): The available battery model in the Fulgor brand is the F41MR-950. In the Black Edition brand, the available battery is the BN41FXR-1000.
MITSUBISHI OUTLANDER 4CIL (2003/2008): The available battery models in the Fulgor brand are the F24R-1000 and the F34MR-1000. In the Black Edition brand, the available battery is the BN24MR-1150.
MITSUBISHI OUTLANDER 6CIL (2009/2010): The available battery models in the Fulgor brand are the F24R-1000 and the F34MR-1000. In the Black Edition brand, the available battery is the BN24MR-1150.
MITSUBISHI PAJERO SPORT (2022/2024): The available battery model in the Fulgor brand is the F27XR-1100. In the Black Edition brand, the available battery is the BN24MR-1150.
MITSUBISHI PANEL L300/VAN L300 (1993/1995): The available battery model in the Fulgor brand is the F22NF-750. In the Black Edition brand, the available battery is the BN22NF-850.
MITSUBISHI SIGNO (2003/2010): The available battery models in the Fulgor brand are the F36FP-750 and the F22FA-850. In the Black Edition brand, the available batteries are the BN36FP-800 and the BN22FA-900.
MITSUBISHI SPACE WAGON (1992/2005): The available battery model in the Fulgor brand is the F22FA-850. In the Black Edition brand, the available battery is the BN22FA-900.
MITSUBISHI TOURING 2.0 (2007/2015): The available battery model in the Fulgor brand is the F22FA-850. In the Black Edition brand, the available battery is the BN22FA-900.
MITSUBISHI XPANDER (2023/2024): The available battery model in the Fulgor brand is the FNS40-670. There are no available models in the Black Edition brand.

MINI COOPER (2005/2010): The available battery model in the Fulgor brand is the F36FP-750. In the Black Edition brand, the available battery is the BN36FP-800.

MG MG3 (2022/2024): The available battery models in the Fulgor brand are the F22FA-850 and the F41MR-950. In the Black Edition brand, the available batteries are the BN22FA-900 and the BN41FXR-1000.
MG RX8 (2022/2024): The available battery models in the Fulgor brand are the F36FP-750 and the F22FA-850. In the Black Edition brand, the available batteries are the BN36FP-800 and the BN22FA-900.
MG ZS (2022/2024): The available battery models in the Fulgor brand are the F22FA-850 and the F41MR-950. In the Black Edition brand, the available batteries are the BN22FA-900 and the BN41FXR-1000.

NISSAN 200SX (1992/1998): The available battery model in the Fulgor brand is the F86-850. In the Black Edition brand, the available battery is the BN86-900.
NISSAN 300ZX (1992/1995): The available battery model in the Fulgor brand is the F86-850. In the Black Edition brand, the available battery is the BN86-900.
NISSAN 350Z/370 (2004/2018): The available battery model in the Fulgor brand is the F22FA-850. In the Black Edition brand, the available battery is the BN22FA-900.
NISSAN AD WAGON (1998/2007): The available battery model in the Fulgor brand is the F22FA-850. In the Black Edition brand, the available battery is the BN22FA-900.
NISSAN ALMERA (2007/2008): The available battery model in the Fulgor brand is the F22FA-850. In the Black Edition brand, the available battery is the BN22FA-900.
NISSAN ALTIMA (1993/2008): The available battery model in the Fulgor brand is the F34MR-1000. There are no available models in the Black Edition brand.
NISSAN ARMADA (2004/2007): The available battery model in the Fulgor brand is the F34MR-1000. There are no available models in the Black Edition brand.
NISSAN FRONTIER D22 DIESEL/GASOLINA (2003/2008): The available battery model in the Fulgor brand is the F34MR-1000. There are no available models in the Black Edition brand.
NISSAN FRONTIER 4X4 AUTOMATICO (2016/2020): The available battery model in the Fulgor brand is the F34MR-1000. There are no available models in the Black Edition brand.
NISSAN FRONTIER NP300 TURBO DIESEL (2009/2015): The available battery model in the Fulgor brand is the F34M-1000. In the Black Edition brand, the available battery is the BN34-1100.
NISSAN FRONTIER NP300 DIESEL (2019/2023): The available battery model in the Fulgor brand is the F34MR-1000. There are no available models in the Black Edition brand.
NISSAN MAXIMA (1989/2004): The available battery model in the Fulgor brand is the F34MR-1000. There are no available models in the Black Edition brand.
NISSAN MURANO (2003/2018): The available battery model in the Fulgor brand is the F24R-1000. In the Black Edition brand, the available battery is the BN24MR-1150.
NISSAN NV3500 DIESEL VAN (2019): The available battery model in the Fulgor brand is the F41MR-950. In the Black Edition brand, the available battery is the BN41FXR-1000.
NISSAN PATHFINDER (1990/2004): The available battery model in the Fulgor brand is the F34M-1000. In the Black Edition brand, the available battery is the BN34-1100.
NISSAN PATHFINDER (2006/2010): The available battery model in the Fulgor brand is the F34MR-1000. There are no available models in the Black Edition brand.
NISSAN PATROL (1975/1994): The available battery model in the Fulgor brand is the F34MR-1000. There are no available models in the Black Edition brand.
NISSAN PATROL 4.5 (1998/2002): The available battery model in the Fulgor brand is the F34MR-1000. There are no available models in the Black Edition brand.
NISSAN PATROL 4.8 (2005/2011): The available battery model in the Fulgor brand is the F34M-1000. In the Black Edition brand, the available battery is the BN34-1100.
NISSAN PICK UP D21 (1996/2007): The available battery model in the Fulgor brand is the F86-850. In the Black Edition brand, the available battery is the BN86-900.
NISSAN PRIMERA (1998/2001): The available battery models in the Fulgor brand are the F36FP-750 and the F22FA-850. In the Black Edition brand, the available batteries are the BN36FP-800 and the BN22FA-900.
NISSAN SENTRA B13/B15 (1991/2008): The available battery models in the Fulgor brand are the F36FP-750 and the F22FA-850. In the Black Edition brand, the available batteries are the BN36FP-800 and the BN22FA-900.
NISSAN SENTRA B14 (1999/2008): The available battery model in the Fulgor brand is the F22NF-750. In the Black Edition brand, the available battery is the BN22NF-850.
NISSAN SENTRA B16 (2007/2010): The available battery model in the Fulgor brand is the F22FA-850. In the Black Edition brand, the available battery is the BN22FA-900.
NISSAN TERRANO (2002/2005): The available battery models in the Fulgor brand are the F34M-1000 and the F34M-1000. In the Black Edition brand, the available batteries are the BN34-1100 and the BN22FA-900.
NISSAN TIIDA (2007/2009): The available battery model in the Fulgor brand is the F22NF-750. In the Black Edition brand, the available battery is the BN22NF-850.
NISSAN TITAN (2008/2017): The available battery model in the Fulgor brand is the F24R-1000. In the Black Edition brand, the available battery is the BN24MR-1150.
NISSAN VERSA (2012/2018): The available battery models in the Fulgor brand are the F36FP-750 and the F22FA-850. In the Black Edition brand, the available batteries are the BN36FP-800 and the BN22FA-900.
NISSAN XTRAIL T30 (2002/2018): The available battery model in the Fulgor brand is the F24R-1000. In the Black Edition brand, the available battery is the BN24MR-1150.

PEGASO AUTOBUSES Y CAMIONES (TODOS): The available battery model in the Fulgor brand is the F4D-1350. There are no available models in the Black Edition brand.

PEUGEOT 206 (2001/2008): The available battery models in the Fulgor brand are the F36FP-750 and the F22FA-850. In the Black Edition brand, the available batteries are the BN36FP-750 and the BN22FA-900.
PEUGEOT 207 (2010/2012): The available battery models in the Fulgor brand are the F36FP-750 and the F22FA-850. In the Black Edition brand, the available batteries are the BN36FP-750 and the BN22FA-900.
PEUGEOT 307 (2007/2010): The available battery models in the Fulgor brand are the F36FP-750 and the F22FA-850. In the Black Edition brand, the available batteries are the BN36FP-750 and the BN22FA-900.
PEUGEOT 405 (1992/1996): The available battery models in the Fulgor brand are the F36FP-750 and the F22FA-850. In the Black Edition brand, the available batteries are the BN36FP-750 and the BN22FA-900.
PEUGEOT 406 (2006/2008): The available battery models in the Fulgor brand are the F36FP-750 and the F22FA-850. In the Black Edition brand, the available batteries are the BN36FP-750 and the BN22FA-900.
PEUGEOT 407 (2006/2014): The available battery models in the Fulgor brand are the F36FP-750 and the F22FA-850. In the Black Edition brand, the available batteries are the BN36FP-750 and the BN22FA-900.
PEUGEOT 408 (2012): The available battery models in the Fulgor brand are the F22FA-850 and the F41MR-950. In the Black Edition brand, the available batteries are the BN22FA-900 and the BN41FXR-1000.
PEUGEOT 607 (2006/2008): The available battery models in the Fulgor brand are the F22FA-850 and the F41MR-950. In the Black Edition brand, the available batteries are the BN22FA-900 and the BN41FXR-1000.
PEUGEOT PARTNER (2012): The available battery models in the Fulgor brand are the F36FP-750 and the F22FA-850. In the Black Edition brand, the available batteries are the BN36FP-800 and the BN22FA-900.
PEUGEOT EXPERT (2009/2012): The available battery model in the Fulgor brand is the F41MR-950. In the Black Edition brand, the available battery is the BN41FXR-1000.
PEUGEOT PARTNER (2011/2012): The available battery models in the Fulgor brand are the F36FP-750 and the F22FA-850. In the Black Edition brand, the available batteries are the BN36FP-800 and the BN22FA-900.

RAM BIGHORN (2023/2024): The available battery models in the Fulgor brand are the F36FP-750 and the F22FA-850. In the Black Edition brand, the available batteries are the BN36FP-800 and the BN22FA-900.
RAM 2500 SLT (2010/2018): The available battery models in the Fulgor brand are the F27R-1100 and the F65-1200. There are no available models in the Black Edition brand.
RAM RAPID (2023/2025): The available battery models in the Fulgor brand are the F36FP-750 and the F22FA-850. In the Black Edition brand, the available batteries are the BN36FP-800 and the BN22FA-900.

RELLY RELY (2022/2024): The available battery model in the Fulgor brand is the F22FA-850. In the Black Edition brand, the available battery is the BN22FA-900.

RENAULT CLIO (1992/2009): The available battery models in the Fulgor brand are the F36FP-750 and the F22FA-850. In the Black Edition brand, the available batteries are the BN36FP-800 and the BN22FA-900.
RENAULT DUSTER (2013/2015): The available battery model in the Fulgor brand is the F22FA-850. In the Black Edition brand, the available battery is the BN22FA-900.
RENAULT DUSTER 1.3/1.6 TURBO (2023/2024): The available battery model in the Fulgor brand is the F22FA-850. In the Black Edition brand, the available battery is the BN22FA-900.
RENAULT FUEGO (1984/1995): The available battery models in the Fulgor brand are the F36FP-750 and the F22FA-850. In the Black Edition brand, the available batteries are the BN36FP-800 and the BN22FA-900.
RENAULT GALA (1984/1995): The available battery models in the Fulgor brand are the F36FP-750 and the F22FA-850. In the Black Edition brand, the available batteries are the BN36FP-800 and the BN22FA-900.
RENAULT KANGOO (2001/2009): The available battery models in the Fulgor brand are the F36FP-750 and the F22FA-850. In the Black Edition brand, the available batteries are the BN36FP-800 and the BN22FA-900.
RENAULT LAGUNA (2000/2001): The available battery models in the Fulgor brand are the F22FA-850 and the F41MR-950. In the Black Edition brand, the available batteries are the BN22FA-900 and the BN41FXR-1000.
RENAULT LOGAN (2005/2014): The available battery models in the Fulgor brand are the F36FP-750 and the F22FA-850. In the Black Edition brand, the available batteries are the BN36FP-800 and the BN22FA-900.
RENAULT LOGAN (2019/2024): The available battery models in the Fulgor brand are the F36FP-750 and the F22FA-850. In the Black Edition brand, the available batteries are the BN36FP-800 and the BN22FA-900.
RENAULT MEGANE (1999/2008): The available battery models in the Fulgor brand are the F36FP-750 and the F22FA-850. In the Black Edition brand, the available batteries are the BN36FP-800 and the BN22FA-900.
RENAULT MEGANE II SEDAN/HATCHBACK (2005/2008): The available battery models in the Fulgor brand are the F22FA-850 and the F41MR-950. In the Black Edition brand, the available batteries are the BN22FA-900 and the BN41FXR-1000.
RENAULT R/11 (1987/1993): The available battery models in the Fulgor brand are the F36FP-750 and the F22FA-850. In the Black Edition brand, the available batteries are the BN36FP-800 and the BN22FA-900.
RENAULT R/18 (1980/1990): The available battery models in the Fulgor brand are the F36FP-750 and the F22FA-850. In the Black Edition brand, the available batteries are the BN36FP-800 and the BN22FA-900.
RENAULT R/19 (1991/2001): The available battery models in the Fulgor brand are the F36FP-750 and the F22FA-850. In the Black Edition brand, the available batteries are the BN36FP-800 and the BN22FA-900.
RENAULT R/21 (1989/1994): The available battery models in the Fulgor brand are the F36FP-750 and the F22FA-850. In the Black Edition brand, the available batteries are the BN36FP-800 and the BN22FA-900.
RENAULT R/5 (1982/1986): The available battery models in the Fulgor brand are the F36FP-750 and the F22FA-850. In the Black Edition brand, the available batteries are the BN36FP-800 and the BN22FA-900.
RENAULT SADERO (2023/2024): The available battery models in the Fulgor brand are the F36FP-750 and the F22FA-850. In the Black Edition brand, the available batteries are the BN36FP-800 and the BN22FA-900.
RENAULT SANDERO (2009): The available battery model in the Fulgor brand is the F22FA-850. In the Black Edition brand, the available battery is the BN22FA-900.
RENAULT SCENIC (2000/2009): The available battery models in the Fulgor brand are the F36FP-750 and the F22FA-850. In the Black Edition brand, the available batteries are the BN36FP-800 and the BN22FA-900.
RENAULT STEEPWAY (2023/2024): The available battery models in the Fulgor brand are the F36FP-750 and the F22FA-850. In the Black Edition brand, the available batteries are the BN36FP-800 and the BN22FA-900.
RENAULT SYMBOL (2001/2009): The available battery models in the Fulgor brand are the F36FP-750 and the F22FA-850. In the Black Edition brand, the available batteries are the BN36FP-800 and the BN22FA-900.
RENAULT TRAFFIC (1992/2003): The available battery model in the Fulgor brand is the F36FP-750. In the Black Edition brand, the available battery is the BN36FP-800.
RENAULT TWINGO (1992/2009): The available battery model in the Fulgor brand is the F36FP-750. In the Black Edition brand, the available battery is the BN36FP-800.

ROVER MINICORD (1991/1995): The available battery models in the Fulgor brand are the F36FP-750 and the F22FA-850. In the Black Edition brand, the available batteries are the BN36FP-800 and the BN22FA-900.
SAIC WULING
SAIC WULING CARGO (2006/2008): The available battery models in the Fulgor brand are the FNS40-670 and the F22NF-750. In the Black Edition brand, the available battery is the BN22NF-850.
SAIC WULING SUPER VAN (2006/2008): The available battery models in the Fulgor brand are the FNS40-670 and the F22NF-750. In the Black Edition brand, the available battery is the BN22NF-850.

SAIPA QUICK ST (2022/2024): The available battery models in the Fulgor brand are the F36FP-750 and the F22FA-850. In the Black Edition brand, the available batteries are the BN36FP-800 and the BN22FA-900.
SAIPA SAINA (2022/2024): The available battery models in the Fulgor brand are the F36FP-750 and the F22FA-850. In the Black Edition brand, the available batteries are the BN36FP-800 and the BN22FA-900.

SEAT CORDOBA (2000/2008): The available battery models in the Fulgor brand are the F36FP-750 and the F22FA-850. In the Black Edition brand, the available batteries are the BN36FP-800 and the BN22FA-900.
SEAT IBIZA (2001/2007): The available battery models in the Fulgor brand are the F36FP-750 and the F22FA-850. In the Black Edition brand, the available batteries are the BN36FP-800 and the BN22FA-900.
SEAT LEON (2005/2008): The available battery models in the Fulgor brand are the F22FA-850 and the F41MR-950. In the Black Edition brand, the available batteries are the BN22FA-900 and the BN41FXR-1000.
SEAT TOLEDO (2001/2007): The available battery models in the Fulgor brand are the F36FP-750 and the F22FA-850. In the Black Edition brand, the available batteries are the BN36FP-800 and the BN22FA-900.

SKODA FABIA (2007/2009): The available battery models in the Fulgor brand are the F36FP-750 and the F22FA-850. In the Black Edition brand, the available batteries are the BN36FP-800 and the BN22FA-900.
SKODA FORMAN (1992/1994): The available battery model in the Fulgor brand is the F22FA-850. In the Black Edition brand, the available battery is the BN22FA-900.
SKODA OCTAVIA (2002/2008): The available battery model in the Fulgor brand is the F22FA-850. In the Black Edition brand, the available battery is the BN22FA-900.
SKODA ROOMSTER (2008/2010): The available battery model in the Fulgor brand is the F22FA-850. In the Black Edition brand, the available battery is the BN22FA-900.

SUBARU FORESTER (1998/2007): The available battery models in the Fulgor brand are the F22FA-850 and the F34MR-1000. In the Black Edition brand, the available battery is the BN22FA-900.
SUBARU IMPREZA (1993/1998): The available battery models in the Fulgor brand are the F36FP-750 and the F22FA-850. In the Black Edition brand, the available batteries are the BN36FP-800 and the BN22FA-900.
SUBARU IMPREZA (2000/2014): The available battery models in the Fulgor brand are the F36FP-750 and the F22FA-850. In the Black Edition brand, the available batteries are the BN36FP-800 and the BN22FA-900.
SUBARU LEGACY (1998/2007): The available battery models in the Fulgor brand are the F36FP-750 and the F22FA-850. In the Black Edition brand, the available batteries are the BN36FP-800 and the BN22FA-900.

SUZUKI ALTO (2023/2024): The available battery model in the Fulgor brand is the FNS40-670. There are no available models in the Black Edition brand.
SUZUKI BALENO (2022/2024): The available battery model in the Fulgor brand is the FNS40-670. There are no available models in the Black Edition brand.
SUZUKI CELERIO (2023/2024): The available battery model in the Fulgor brand is the FNS40-670. There are no available models in the Black Edition brand.
SUZUKI DZIRE (2023/2024): The available battery model in the Fulgor brand is the FNS40-670. There are no available models in the Black Edition brand.
SUZUKI EECO CARGA / PASAJEROS (2023/2024): The available battery model in the Fulgor brand is the FNS40-670. There are no available models in the Black Edition brand.
SUZUKI ERTIGA (2023/2024): The available battery model in the Fulgor brand is the FNS40-670. There are no available models in the Black Edition brand.
SUZUKI FRONX (2023/2024): The available battery model in the Fulgor brand is the FNS40-670. There are no available models in the Black Edition brand.
SUZUKI GRAND VITARA (2007/2008): The available battery model in the Fulgor brand is the F86-850. In the Black Edition brand, the available batteries are the BN86-900 and the BN22FA-900.
SUZUKI GRAND VITARA HYBRIDA (2023/2024): The available battery model in the Fulgor brand is the F24R-1000. In the Black Edition brand, the available battery is the BN24MR-1150.
SUZUKI JIMNY (2022/2024): The available battery model in the Fulgor brand is the FNS40-670. There are no available models in the Black Edition brand.
SUZUKI S-PRESSO (2023/2024): The available battery model in the Fulgor brand is the FNS40-670. There are no available models in the Black Edition brand.
SUZUKI SWIFT (2022/2024): The available battery model in the Fulgor brand is the FNS40-670. There are no available models in the Black Edition brand.

TATA INDICA (2007/2008): The available battery models in the Fulgor brand are the F36FP-750 and the F22FA-850. In the Black Edition brand, the available batteries are the BN36FP-800 and the BN22FA-900.
TATA INDIGO (2007/2008): The available battery models in the Fulgor brand are the F36FP-750 and the F22FA-850. In the Black Edition brand, the available batteries are the BN36FP-800 and the BN22FA-900.

TITAN AUTOBUSES (1984/1995): The available battery model in the Fulgor brand is the F4D-1250. There are no available models in the Black Edition brand.

TOYOTA 4RUNNER/SR5/LIMITED (1991/2024): The available battery model in the Fulgor brand is the F24R-1000. In the Black Edition brand, the available battery is the BN24MR-1150.
TOYOTA AGYA (2024/2025): The available battery model in the Fulgor brand is the FNS40-670. There are no available models in the Black Edition brand.
TOYOTA AUTANA/BURBUJA (1992/2007): The available battery model in the Fulgor brand is the F24R-1000. In the Black Edition brand, the available battery is the BN24MR-1150.
TOYOTA C/HR (2018/2019): The available battery models in the Fulgor brand are the F36FP-750 and the F22FA-850. In the Black Edition brand, the available batteries are the BN36FP-800 and the BN22FA-900.
TOYOTA CAMRY (1992/2015): The available battery model in the Fulgor brand is the F24R-1000. In the Black Edition brand, the available battery is the BN24MR-1150.
TOYOTA CAMRY (2017/2022): The available battery model in the Fulgor brand is the F22FA-850. In the Black Edition brand, the available battery is the BN22FA-900.
TOYOTA CELICA (1992/1999): The available battery model in the Fulgor brand is the F22NF-750. In the Black Edition brand, the available battery is the BN22NF-850.
TOYOTA CELICA (2000/2005): The available battery model in the Fulgor brand is the F22FA-850. In the Black Edition brand, the available battery is the BN22FA-900.
TOYOTA COROLLA/SKY (1986/2002): The available battery model in the Fulgor brand is the F22NF-750. In the Black Edition brand, the available battery is the BN22NF-850.
TOYOTA COROLLA (2003/2014): The available battery model in the Fulgor brand is the F22NF-750. In the Black Edition brand, the available battery is the BN22NF-850.
TOYOTA COROLLA LE 1.8/LE 2.0 (2016/2019): The available battery model in the Fulgor brand is the F22NF-750. In the Black Edition brand, the available battery is the BN22NF-850.
TOYOTA COROLLA S (2015/2019): The available battery model in the Fulgor brand is the F24R-1000. In the Black Edition brand, the available battery is the BN24MR-1150.
TOYOTA COROLLA SE/SE-G/LE (2020/2024): The available battery model in the Fulgor brand is the F36FP-750. In the Black Edition brand, the available battery is the BN36FP-800.
TOYOTA COROLLA IMPORTADO (SEGÚN MUESTRA) (2016/2024): There are no available models in the Fulgor or Black Edition brand.
TOYOTA COROLLA CROSS (2022/2024): The available battery model in the Fulgor brand is the F36FP-750. In the Black Edition brand, the available battery is the BN36FP-800.
TOYOTA COASTER (2001/2014): The available battery model in the Fulgor brand is the F22FA-850. In the Black Edition brand, the available battery is the BN22FA-900.
TOYOTA CROWN (1993/1998): The available battery model in the Fulgor brand is the F34MR-1000. There are no available models in the Black Edition brand.
TOYOTA DYNA (1992/2007): The available battery model in the Fulgor brand is the F24R-1000. In the Black Edition brand, the available battery is the BN24MR-1150.
TOYOTA ETIOS (2016/2023): The available battery model in the Fulgor brand is the F36FP-750. In the Black Edition brand, the available battery is the BN36FP-800.
TOYOTA FJ CRUISER (2005/2016): The available battery model in the Fulgor brand is the F24R-1000. In the Black Edition brand, the available battery is the BN24MR-1150.
TOYOTA FORTUNER VXR (2018/2019): The available battery model in the Fulgor brand is the F24R-1000. In the Black Edition brand, the available battery is the BN24MR-1150.
TOYOTA FORTUNER VXR LEYENDER (2023/2024): The available battery model in the Fulgor brand is the F41MR-950. In the Black Edition brand, the available battery is the BN41FXR-1000.
TOYOTA FORTUNER (2006/2019): The available battery model in the Fulgor brand is the F24R-1000. In the Black Edition brand, the available battery is the BN24MR-1150.
TOYOTA FORTUNER DUBAI (2018/2020): The available battery model in the Fulgor brand is the F41MR-950. In the Black Edition brand, the available battery is the BN41FXR-1000.
TOYOTA FORTUNER SW4 (2021/2024): The available battery model in the Fulgor brand is the F41MR-950. In the Black Edition brand, the available battery is the BN41FXR-1000.
TOYOTA FORTUNER DIESEL 2.8 (2017/2023): The available battery model in the Fulgor brand is the F41MR-950. In the Black Edition brand, the available battery is the BN41FXR-1000.
TOYOTA HIACE (2007/2009): The available battery model in the Fulgor brand is the F34M-1000. In the Black Edition brand, the available battery is the BN34-1000.
TOYOTA HIACE 2.5 TURBO DIESEL (2022/2024): The available battery models in the Fulgor brand are the F41MR-950 and the F34MR-1000. In the Black Edition brand, the available battery is the BN41FXR-1000.
TOYOTA HILUX (1992/2005): The available battery model in the Fulgor brand is the F24R-1000. In the Black Edition brand, the available battery is the BN24MR-1150.
TOYOTA HILUX 2.7 (2006/2015): The available battery model in the Fulgor brand is the F24R-1000. In the Black Edition brand, the available battery is the BN24MR-1150.
TOYOTA HILUX KAVAK 4.0 (2006/2015): The available battery model in the Fulgor brand is the F24R-1000. In the Black Edition brand, the available battery is the BN24MR-1150.
TOYOTA HILUX DUBAI (2018/2019): The available battery model in the Fulgor brand is the F41MR-950. In the Black Edition brand, the available battery is the BN41FXR-1000.
TOYOTA HILUX DIESEL 2.8L (2022/2024): The available battery model in the Fulgor brand is the F41MR-950. In the Black Edition brand, the available battery is the BN41FXR-1000.
TOYOTA HILUX 4.0 GASOLINA (2022/2024): The available battery model in the Fulgor brand is the F41MR-950. In the Black Edition brand, the available battery is the BN41FXR-1000.
TOYOTA LAND CRUISER SERIE J40 (MACHO) (1960/1984): The available battery model in the Fulgor brand is the F24R-1000. In the Black Edition brand, the available battery is the BN24MR-1150.
TOYOTA LAND CRUISER SERIE J60 (SAMURAI) (1984/1992): The available battery model in the Fulgor brand is the F34M-1000. In the Black Edition brand, the available battery is the BN34-1000.
TOYOTA LAND CRUISER SERIE J70 (MACHITO) (1985/2009): The available battery model in the Fulgor brand is the F24R-1000. In the Black Edition brand, the available battery is the BN24MR-1150.
TOYOTA LAND CRUISER SERIE J70 (MACHITO 4.0 V6) (2010/2024): The available battery model in the Fulgor brand is the F34M-1000. In the Black Edition brand, the available battery is the BN34-1000.
TOYOTA LAND CRUISER SERIE J70 DIESEL V8 (2022/2024): The available battery model in the Fulgor brand is the F27XR-1100. There are no available models in the Black Edition brand.
TOYOTA LAND CRUISER SERIE J80 (AUTANA/BURBUJA) (1990/2007): The available battery model in the Fulgor brand is the F24R-1000. In the Black Edition brand, the available battery is the BN24MR-1150.
TOYOTA LAND CRUISER SERIE 200 (RORAIMA) (2008/2021): The available battery model in the Fulgor brand is the F24R-1000. In the Black Edition brand, the available battery is the BN24MR-1150.
TOYOTA LAND CRUISER SERIE 300 VX (2021/2024): There are no available models in the Fulgor brand. In the Black Edition brand, the available battery is the BN94R-1200.
TOYOTA LAND CRUISER PRADO TX DIESEL (2022/2024): The available battery model in the Fulgor brand is the F27XR-1100. There are no available models in the Black Edition brand.
TOYOTA LAND CRUISER PRADO WX GASOLINA (2022/2024): There are no available models in the Fulgor brand. In the Black Edition brand, the available battery is the BN94R-1200.
TOYOTA MERU (2005/2009): The available battery model in the Fulgor brand is the F24R-1000. In the Black Edition brand, the available battery is the BN24MR-1150.
TOYOTA PASEO (1993/1997): The available battery models in the Fulgor brand are the F36FP-750 and the F22FA-850. In the Black Edition brand, the available batteries are the BN36FP-800 and the BN22FA-900.
TOYOTA PRADO (1999/2006): The available battery model in the Fulgor brand is the F24R-1000. In the Black Edition brand, the available battery is the BN24MR-1150.
TOYOTA PREVIA (1991/2010): The available battery model in the Fulgor brand is the F24R-1000. In the Black Edition brand, the available battery is the BN24MR-1150.
TOYOTA PRIUS (2012/2015): The available battery model in the Fulgor brand is the F36FP-750. In the Black Edition brand, the available battery is the BN36FP-800.
TOYOTA RAV/4 (1996/2007): The available battery models in the Fulgor brand are the F22FA-850 and the F41MR-950. In the Black Edition brand, the available batteries are the BN22FA-900 and the BN41FXR-1000.
TOYOTA RAV/4 (2016): The available battery model in the Fulgor brand is the F22FA-850. In the Black Edition brand, the available battery is the BN22FA-900.
TOYOTA SEQUOIA (2003/2009): The available battery models in the Fulgor brand are the F27XR-1100 and the F24R-1000. In the Black Edition brand, the available battery is the BN24MR-1150.
TOYOTA SIENNA (1998/2006): The available battery model in the Fulgor brand is the F24R-1000. In the Black Edition brand, the available battery is the BN24MR-1150.
TOYOTA STARLET (1992/2000): The available battery models in the Fulgor brand are the F36FP-750 and the F22FA-850. In the Black Edition brand, the available battery is the BN36FP-800.
TOYOTA SUPRA (1982/1998): The available battery models in the Fulgor brand are the F22FA-850 and the F41MR-950. In the Black Edition brand, the available batteries are the BN22FA-900 and the BN41FXR-1000.
TOYOTA TACOMA (2007/2019): The available battery model in the Fulgor brand is the F24R-1000. In the Black Edition brand, the available battery is the BN24MR-1150.
TOYOTA TERCEL (1991/1998): The available battery models in the Fulgor brand are the F36FP-750 and the F22FA-850. In the Black Edition brand, the available batteries are the BN36FP-800 and the BN22FA-900.
TOYOTA TERIOS (2002/2010): The available battery model in the Fulgor brand is the F22NF-750. In the Black Edition brand, the available battery is the BN22NF-850.
TOYOTA TUNDRA (2004/2010): The available battery models in the Fulgor brand are the F27R-1100 and the F24R-1000. In the Black Edition brand, the available battery is the BN24MR-1150.
TOYOTA YARIS (2000/2009): The available battery model in the Fulgor brand is the F22NF-750. In the Black Edition brand, the available battery is the BN22NF-800.
TOYOTA YARIS E/G (2020/2024): The available battery model in the Fulgor brand is the FNS40-670. There are no available models in the Black Edition brand.
TOYOTA YARIS CROSS/SD (2022/2024): The available battery model in the Fulgor brand is the FNS40-670. There are no available models in the Black Edition brand.

VENIRAN CENTAURO (2008/2010): The available battery model in the Fulgor brand is the F22FA-850. In the Black Edition brand, the available battery is the BN22FA-900.
VENIRAN SAIPA (2006/2015): The available battery models in the Fulgor brand are the F36FP-750 and the F22FA-850. In the Black Edition brand, the available batteries are the BN36FP-800 and the BN22FA-900.
VENIRAN TURPIAL (2008/2015): The available battery models in the Fulgor brand are the F36FP-750 and the F22FA-850. In the Black Edition brand, the available batteries are the BN36FP-800 and the BN22FA-900.

VOLKSWAGEN BORA (2000/2009): The available battery model in the Fulgor brand is the F22FA-850. In the Black Edition brand, the available battery is the BN22FA-900.
VOLKSWAGEN CADDY (1998/2006): The available battery models in the Fulgor brand are the F36FP-750 and the F22FA-850. In the Black Edition brand, the available batteries are the BN36FP-800 and the BN22FA-900.
VOLKSWAGEN CROSSFOX (2006/2008): The available battery models in the Fulgor brand are the F36FP-750 and the F22FA-850. In the Black Edition brand, the available batteries are the BN36FP-800 and the BN22FA-900.
VOLKSWAGEN ESCARABAJO (1963/1998): The available battery models in the Fulgor brand are the F36FP-750 and the F22FA-850. In the Black Edition brand, the available batteries are the BN36FP-800 and the BN22FA-900.
VOLKSWAGEN FOX (2005/2010): The available battery models in the Fulgor brand are the F36FP-750 and the F22FA-850. In the Black Edition brand, the available batteries are the BN36FP-800 and the BN22FA-900.
VOLKSWAGEN GOL (1992/2008): The available battery models in the Fulgor brand are the F36FP-750 and the F22FA-850. In the Black Edition brand, the available batteries are the BN36FP-800 and the BN22FA-900.
VOLKSWAGEN GOLF (1993/2007): The available battery models in the Fulgor brand are the F36FP-750 and the F22FA-850. In the Black Edition brand, the available batteries are the BN36FP-800 and the BN22FA-900.
VOLKSWAGEN JETTA (1992/2008): The available battery model in the Fulgor brand is the F22FA-850. In the Black Edition brand, the available battery is the BN22FA-900.
VOLKSWAGEN PARATI (2001/2008): The available battery models in the Fulgor brand are the F36FP-750 and the F22FA-850. In the Black Edition brand, the available batteries are the BN36FP-800 and the BN22FA-900.
VOLKSWAGEN PASSAT (1992/2007): The available battery model in the Fulgor brand is the F22FA-850. In the Black Edition brand, the available batteries are the BN22FA-900 and the BN22FA-900.
VOLKSWAGEN POLO (1998/2008): The available battery models in the Fulgor brand are the F36FP-750 and the F22FA-850. In the Black Edition brand, the available batteries are the BN36FP-800 and the BN22FA-900.
VOLKSWAGEN SANTANA (2002/2004): The available battery models in the Fulgor brand are the F36FP-750 and the F22FA-850. In the Black Edition brand, the available batteries are the BN36FP-800 and the BN22FA-900.
VOLKSWAGEN SAVEIRO (1998/2008): The available battery models in the Fulgor brand are the F36FP-750 and the F22FA-850. In the Black Edition brand, the available batteries are the BN36FP-800 and the BN22FA-900.
VOLKSWAGEN SPACEFOX (2007/2010): The available battery models in the Fulgor brand are the F36FP-750 and the F22FA-850. In the Black Edition brand, the available batteries are the BN36FP-800 and the BN22FA-900.
VOLKSWAGEN TOUAREG (2004/2008): There are no available models in the Fulgor brand. In the Black Edition brand, the available battery is the BN94R-1200.
VOLKSWAGEN VENTO (1993/1999): The available battery model in the Fulgor brand is the F22FA-850. In the Black Edition brand, the available battery is the BN22FA-900.

VOLVO 740 (1990/1992): The available battery model in the Fulgor brand is the F22FA-850. In the Black Edition brand, the available battery is the BN22FA-900.
VOLVO 940 (1991/1997): The available battery model in the Fulgor brand is the F22FA-850. In the Black Edition brand, the available battery is the BN22FA-900.
VOLVO FH 440 (2005/2010): The available battery model in the Fulgor brand is the F4D-1350. There are no available models in the Black Edition brand.
VOLVO VM (2005/2010): The available battery model in the Fulgor brand is the F30HC-1250. There are no available models in the Black Edition brand.

ZOTYE MANZA (2012/2014): The available battery model in the Fulgor brand is the F36FP-750. There are no available models in the Black Edition brand.
ZOTYE NOMADA (2007/2009): The available battery model in the Fulgor brand is the F22NF-750. In the Black Edition brand, the available battery is the BN22NF-850.
ZOTYE VISTA (2012/2014): The available battery model in the Fulgor brand is the F36FP-750. There are no available models in the Black Edition brand.
    """ # NOTE: For brevity, I've truncated the massive car list. The logic works on the full list.

    error_logs = []

    # 1. Parse prices first to create our price map and master battery list
    print("--- Parsing Battery Prices ---")
    parse_battery_prices(battery_price_input)
    print(f"✅ Parsed {len(BATTERY_PRICE_MAP)} battery prices.")

    # 2. Parse fitments, using the price map for validation
    print("\n--- Parsing Vehicle Fitments ---")
    structured_fitment_data = parse_vehicle_fitments(car_fitment_input, error_logs)

    # 3. Write the output files
    with open(OUTPUT_BATTERIES_JSON_PATH, "w", encoding="utf-8") as bf:
        json.dump(PARSED_BATTERIES_DATA, bf, indent=4, ensure_ascii=False)
    print(f"\n✅ Saved {len(PARSED_BATTERIES_DATA)} battery entries to {OUTPUT_BATTERIES_JSON_PATH}")

    with open(OUTPUT_FITMENTS_JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(structured_fitment_data, f, indent=4, ensure_ascii=False)
    print(f"✅ Saved {len(structured_fitment_data)} fitment entries to {OUTPUT_FITMENTS_JSON_PATH}")

    if error_logs:
        with open(ERROR_LOG_PATH, "w", encoding="utf-8") as ef:
            json.dump(error_logs, ef, indent=4, ensure_ascii=False)
        print(f"\n⚠️  Saved {len(error_logs)} error logs to {ERROR_LOG_PATH}")
    else:
        print("\n🎉 No parsing errors detected!")

    print("\n--- Script Finished ---")