# Vehicle Make Alias Rules

To keep vehicle data consistent, common nicknames and misspellings of
manufacturer names are mapped to canonical forms. These aliases are
applied automatically when processing user queries and should also be
used when importing data so that all records share the same
manufacturer names.

Current alias mappings are defined in `services/vehicle_aliases.py` as
the `MAKE_ALIASES` dictionary. Key examples include:

| Alias | Canonical Name |
| ----- | -------------- |
| Benz, Merc, Mercedes Benz | Mercedes-Benz |
| VW, Volks, Volkswagon | Volkswagen |
| Chevy, Chev | Chevrolet |
| Beemer, Bimmer | BMW |

When new variations are encountered, add them to `MAKE_ALIASES` and
update this document accordingly.
