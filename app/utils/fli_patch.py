"""Permanent fix for fli library Airline enum values.

The fli library's Airline enum has incorrect .value strings for many carriers.
For example, Airline.P4.value returns 'Aerolineas Sosa' (a Honduran airline)
instead of 'Air Peace' (the correct Nigerian carrier).

This module patches the enum values at import time so the fix applies globally
to any code reading Airline.X.value. This is a root-cause fix, not a
workaround — it corrects the data at the source.

Add new corrections to FIXES dict as they are discovered.
"""

import logging

logger = logging.getLogger("araha.fli_patch")

# IATA code → correct airline name
# fli library has wrong values for these codes.
FIXES = {
    "P4": "Air Peace",
    "UN": "United Nigeria Airlines",
    "NK": "Green Africa Airways",
    "VK": "ValueJet",
    "NE": "NG Eagle",
    "MX": "Max Air",
    "UM": "Umza Air",
    "Q9": "Enugu Air",
}


def _get_fli_airline_enum():
    """Lazy-import and return the fli Airline enum."""
    try:
        from fli.models.airline import Airline
        return Airline
    except ImportError:
        return None
    except Exception:
        return None


def apply_patches():
    """Apply all patches to fli's Airline enum values.

    Call once at application startup, before any fare ingestion runs.
    Idempotent — safe to call multiple times.
    """
    Airline = _get_fli_airline_enum()
    if Airline is None:
        logger.warning("fli library not available — skipping Airline enum patches.")
        return

    patched = 0
    for code, correct_name in FIXES.items():
        member = getattr(Airline, code, None)
        if member is None:
            logger.warning(
                "Airline.%s not found in fli enum — can't patch.", code)
            continue

        current = member.value
        if current == correct_name:
            continue

        member._value_ = correct_name
        patched += 1
        logger.info(
            "Patched fli Airline.%s: %r → %r", code, current, correct_name)

    if patched == 0:
        logger.info("fli Airline enum patches: none needed (already correct).")
    else:
        logger.info("fli Airline enum patches applied: %d fixes.", patched)
