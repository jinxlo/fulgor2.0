# services/vehicle_aliases.py
"""
Utility mapping for normalizing vehicle manufacturer names.

This module defines MAKE_ALIASES which maps common nicknames, alternate names, or
misspellings of vehicle makes to the canonical names now present in the database.
This ensures lookups are performed against consistent, clean values.

This file should be updated as new real-world user query variations are discovered.
"""

# Maps lowercase alias -> canonical vehicle make (the name as it appears in your DB)
MAKE_ALIASES: dict[str, str] = {
    # ACURA
    "acura": "ACURA",

    # ALFA ROMEO
    "alfa": "ALFA ROMEO",
    "alfa romeo": "ALFA ROMEO",

    # AUDI
    "audi": "AUDI",

    # BAW
    "baw": "BAW",

    # BLUE BIRD
    "blue": "BLUE BIRD",
    "bluebird": "BLUE BIRD",
    "blue bird": "BLUE BIRD",

    # BMW
    "bmw": "BMW",
    "beemer": "BMW",
    "bimmer": "BMW",

    # BUICK
    "buick": "BUICK",

    # BYD
    "byd": "BYD",

    # CHANA
    "chana": "CHANA",

    # CHANGAN
    "changan": "CHANGAN",

    # CHANGHE
    "changhe": "CHANGHE",

    # CHERY
    "chery": "CHERY",

    # CHEVROLET
    "chevrolet": "CHEVROLET",
    "chevy": "CHEVROLET",
    "chev": "CHEVROLET",
    "chebrolet": "CHEVROLET", # Misspelling

    # CHINOS (Generic category)
    "chinos": "CHINOS",

    # CHRYSLER
    "chrysler": "CHRYSLER",

    # CITROËN
    "citroën": "CITROËN",
    "citroen": "CITROËN", # Common user input without the diaeresis

    # DAEWOO
    "daewoo": "DAEWOO",

    # DODGE
    "dodge": "DODGE",

    # DONGFENG
    "dongfeng": "DONGFENG",

    # DSFK
    "dsfk": "DSFK",

    # ENCANVA
    "encanva": "ENCANVA",

    # FIAT
    "fiat": "FIAT",

    # FORD
    "ford": "FORD",

    # FOTON
    "foton": "FOTON",

    # FREIGHTLINER
    "freightliner": "FREIGHTLINER",
    "frieghtliner": "FREIGHTLINER", # Misspelling

    # GREAT (Possibly Great Wall)
    "great": "GREAT",
    "great wall": "GREAT",

    # HAFEI
    "hafei": "HAFEI",

    # HINO
    "hino": "HINO",

    # HONDA
    "honda": "HONDA",

    # HUMMER
    "hummer": "HUMMER",

    # HYUNDAI
    "hyundai": "HYUNDAI",
    "hyndai": "HYUNDAI", # Misspelling
    "hundai": "HYUNDAI", # Misspelling

    # IKCO
    "ikco": "IKCO",

    # INTERNATIONAL
    "international": "INTERNATIONAL",

    # ISUZU
    "isuzu": "ISUZU",

    # IVECO
    "iveco": "IVECO",

    # JAC
    "jac": "JAC",

    # JEEP
    "jeep": "JEEP",

    # JETOUR
    "jetour": "JETOUR",

    # JMC
    "jmc": "JMC",

    # KARRY
    "karry": "KARRY",

    # KENWORTH
    "kenworth": "KENWORTH",

    # KIA
    "kia": "KIA",

    # LADA
    "lada": "LADA",

    # LAND ROVER
    "land rover": "LAND ROVER",
    "landrover": "LAND ROVER",
    "land": "LAND ROVER", # Old DB name

    # LEXUS
    "lexus": "LEXUS",

    # LIFAN
    "lifan": "LIFAN",

    # LINCOLN
    "lincoln": "LINCOLN",

    # MACK
    "mack": "MACK",

    # MAXUS
    "maxus": "MAXUS",

    # MAZDA
    "mazda": "MAZDA",

    # MERCEDES BENZ
    "mercedes benz": "MERCEDES BENZ",
    "mercedes": "MERCEDES BENZ",
    "benz": "MERCEDES BENZ",
    "mercedez": "MERCEDES BENZ", # Misspelling
    "merc": "MERCEDES BENZ",
    "mb": "MERCEDES BENZ",

    # MG
    "mg": "MG",

    # MINI
    "mini": "MINI",

    # MITSUBISHI
    "mitsubishi": "MITSUBISHI",
    "mitsu": "MITSUBISHI",

    # NISSAN
    "nissan": "NISSAN",

    # PEUGEOT
    "peugeot": "PEUGEOT",

    # RAM
    "ram": "RAM",

    # RELLY
    "relly": "RELLY",

    # RENAULT
    "renault": "RENAULT",

    # ROVER
    "rover": "ROVER",

    # SAIC
    "saic": "SAIC",

    # SAIPA
    "saipa": "SAIPA",

    # SEAT
    "seat": "SEAT",

    # SKODA
    "skoda": "SKODA",

    # SUBARU
    "subaru": "SUBARU",

    # SUZUKI
    "suzuki": "SUZUKI",

    # TOYOTA
    "toyota": "TOYOTA",

    # VENUCIA
    "venucia": "VENUCIA",

    # VOLKSWAGEN
    "volkswagen": "VOLKSWAGEN",
    "vw": "VOLKSWAGEN",
    "volks": "VOLKSWAGEN",
    "volkswagon": "VOLKSWAGEN", # Misspelling

    # VOLVO
    "volvo": "VOLVO",

    # ZOTYE
    "zotye": "ZOTYE",
}