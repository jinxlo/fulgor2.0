import os
import re

# This script is designed to be placed in the 'initial_data_scripts' directory.
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
TARGET_FILE_PATH = os.path.join(SCRIPT_DIR, "models_set.py")

# --- CONTEXT-AWARE REPLACEMENT DICTIONARIES ---
# Each dictionary contains replacements for a specific brand.

FULGOR_REPLACEMENTS = {
    # OLD MODEL & PRICE -> NEW MODEL & PRICE
    "F22NF-700 priced at $93": "F22NF-750 priced at $126.37",
    "22NF-700 priced at $93": "F22NF-750 priced at $126.37",
    "F36FP-700 priced at $82": "F36FP-750 priced at $115.68",
    "36FP-700 priced at $82": "F36FP-750 priced at $115.68",
    "F22FA-800 priced at $95": "F22FA-850 priced at $144.85",
    "22FA-800 priced at $95": "F22FA-850 priced at $144.85",
    "F86-800 priced at $95": "F86-850 priced at $134.13",
    "86-800 priced at $95": "F86-850 priced at $134.13",
    "41MR priced at $116": "F41MR-950 priced at $160.59",
    "41M-900 priced at $116": "F41M-950 priced at $160.59",
    "F34M-900 priced at $109": "F34M-1000 priced at $163.44",
    "34M-900 priced at $109": "F34M-1000 priced at $163.44",
    "34MR-900 priced at $109": "F34MR-1000 priced at $163.44",
    "24R-900 priced at $118": "F24R-1000 priced at $190.58",
    "65-1100 priced at $150": "F65-1200 priced at $204.69",
    "F41FXR-900 priced at $116": "F41MR-950 priced at $160.59",
    "31T-1100 priced at $183": "F31T-1250 priced at $246.10",
    "F4D-1250 priced at $245": "F4D-1350 priced at $346.74",
    "F8D-1500 priced at $305": "F8D-1600 priced at $442.37",
    "NS40 priced at $88": "FNS40-670 priced at $132.50",
    # Priceless variants (will add price)
    "F27XR-950": "F27XR-1100 priced at $192.43",
    "27XR-950": "F27XR-1100 priced at $192.43",
    "27R-950": "F27R-1100 priced at $192.43",
    "30HC-1100": "F30H-1250 priced at $240.98",
    "41M-900": "F41M-950 priced at $160.59",
    "F41MR-900": "F41MR-950 priced at $160.59",
    "4D-1250": "F4D-1350 priced at $346.74",
    "NS40": "FNS40-670 priced at $132.50"
}

BLACK_EDITION_REPLACEMENTS = {
    # OLD MODEL & PRICE -> NEW MODEL & PRICE
    "BN22NF-800 priced at $100": "BN22NF-850 priced at $144.91",
    "22NF-800 priced at $100": "BN22NF-850 priced at $144.91", # For lines that omit prefix
    "36FP-700 priced at $82": "BN36FP-800 priced at $119.57",
    "22FA-800 priced at $95": "BN22FA-900 priced at $148.30",
    "F22FA-800 priced at $95": "BN22FA-900 priced at $148.30", # Handles mistaken prefix
    "86-800 priced at $95": "BN86-900 priced at $137.20",
    "F86-800 priced at $95": "BN86-900 priced at $137.20", # Handles mistaken prefix
    "41FXR-900 priced at $116": "BN41FXR-1000 priced at $164.97",
    "34-1000 priced at $131": "BN34-1100 priced at $180.12",
    "F34-1000 priced at $131": "BN34-1100 priced at $180.12", # Handles mistaken prefix
    "24MR-1100 priced at $140": "BN24MR-1150 priced at $195.08",
    "BN94R-1100 priced at $168": "BN94R-1200 priced at $232.70",
    "94R-1100 priced at $168": "BN94R-1200 priced at $232.70",
    # Priceless variants (will add price)
    "F94R-1100": "BN94R-1200 priced at $232.70",
    "94R": "BN94R-1200 priced at $232.70",
    "94R-1100AGM": "BN94R-1200 priced at $232.70" # Assuming AGM maps to standard
}


def update_car_data_input():
    print(f"Reading file: {TARGET_FILE_PATH}")
    try:
        with open(TARGET_FILE_PATH, 'r', encoding='utf-8') as f:
            content = f.read()
    except FileNotFoundError:
        print(f"❌ ERROR: The file was not found at {TARGET_FILE_PATH}.")
        return

    match = re.search(r'(car_data_input\s*=\s*""")(.*?)(""")', content, re.DOTALL)

    if not match:
        print("❌ ERROR: Could not find the `car_data_input` variable. No changes were made.")
        return

    start_marker, original_data, end_marker = match.groups()
    
    updated_lines = []
    lines = original_data.strip().split('\n')
    
    total_replacements = 0

    for line in lines:
        if not line.strip():
            updated_lines.append(line)
            continue

        parts = line.split(':', 1)
        if len(parts) < 2:
            updated_lines.append(line)
            continue
            
        vehicle_part = parts[0]
        details_part = parts[1]

        # Use regex to find brand segments, ensuring we handle cases where only one brand exists
        fulgor_match = re.search(r"(Fulgor brand\b.*?(?=\s+In the Black Edition brand|\s*$))", details_part, re.IGNORECASE)
        black_edition_match = re.search(r"(Black Edition brand\b.*?(?=\s+In the Fulgor brand|\s*$))", details_part, re.IGNORECASE)

        new_details_part = details_part

        if fulgor_match:
            segment = fulgor_match.group(1)
            updated_segment = segment
            for old, new in FULGOR_REPLACEMENTS.items():
                if old in updated_segment:
                    updated_segment = updated_segment.replace(old, new)
                    total_replacements += 1
            new_details_part = new_details_part.replace(segment, updated_segment)

        if black_edition_match:
            segment = black_edition_match.group(1)
            updated_segment = segment
            for old, new in BLACK_EDITION_REPLACEMENTS.items():
                if old in updated_segment:
                    updated_segment = updated_segment.replace(old, new)
                    total_replacements += 1
            new_details_part = new_details_part.replace(segment, updated_segment)
        
        updated_lines.append(f"{vehicle_part}:{new_details_part}")

    updated_data = "\n".join(updated_lines)
    
    # Use a more reliable way to check for changes
    if original_data.strip().replace(" ", "") == updated_data.strip().replace(" ", ""):
        print("⚠️  No changes were made. The data might already be up-to-date.")
    else:
        print(f"✅ Successfully performed {total_replacements} replacements.")

    new_content = content.replace(f"{start_marker}{original_data}{end_marker}", f'{start_marker}\n{updated_data}\n{end_marker}')

    try:
        with open(TARGET_FILE_PATH, 'w', encoding='utf-8') as f:
            f.write(new_content)
        print(f"✅ File updated successfully: {TARGET_FILE_PATH}")
    except Exception as e:
        print(f"❌ ERROR: Failed to write to file: {e}")

if __name__ == "__main__":
    update_car_data_input()