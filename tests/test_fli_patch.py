"""Tests for the fli library Airline enum patch.

Verifies that:
  1. The patch applies without error
  2. Every corrected enum value matches the expected name
  3. The fix is idempotent (applying twice doesn't break anything)
  4. Unaffected enum values are not changed
"""

import pytest


def test_patch_applies_cleanly():
    """apply_patches should not raise."""
    from app.utils.fli_patch import apply_patches
    apply_patches()


def test_corrected_values():
    """Every fix in FIXES should be reflected in the enum after patching."""
    from app.utils.fli_patch import apply_patches, FIXES
    import fli.models.airline as a
    apply_patches()

    for code, expected_name in FIXES.items():
        member = getattr(a.Airline, code, None)
        if member is None:
            pytest.skip(f"Airline.{code} not in fli enum — skipping")
        assert member.value == expected_name, (
            f"Airline.{code}.value = {member.value!r}, expected {expected_name!r}"
        )


def test_unaffected_values_not_changed():
    """Known-correct enum values should not be altered by the patch."""
    from app.utils.fli_patch import apply_patches
    import fli.models.airline as a
    apply_patches()

    # W3 (Arik Air) and OF (Overland Airways) are correct in fli
    assert a.Airline.W3.value == "Arik Air"
    assert a.Airline.OF.value == "Overland Airways"


def test_patch_idempotent():
    """Applying the patch twice should produce the same result."""
    from app.utils.fli_patch import apply_patches, FIXES
    import fli.models.airline as a
    apply_patches()
    apply_patches()

    for code, expected_name in FIXES.items():
        member = getattr(a.Airline, code, None)
        if member is None:
            pytest.skip(f"Airline.{code} not in fli enum — skipping")
        assert member.value == expected_name


def test_fli_value_now_matches_attribution_map():
    """After patching, fli values should match our WEST_AFRICAN_AIRLINES map."""
    from app.utils.fli_patch import apply_patches, FIXES
    from app.services.fare_ingestor import WEST_AFRICAN_AIRLINES
    import fli.models.airline as a
    apply_patches()

    for code, _ in FIXES.items():
        member = getattr(a.Airline, code, None)
        if member is None:
            continue
        expected = WEST_AFRICAN_AIRLINES.get(code)
        if expected and "(defunct)" not in expected:
            assert member.value == expected, (
                f"Airline.{code}: fli says {member.value!r}, "
                f"WEST_AFRICAN_AIRLINES says {expected!r}"
            )
