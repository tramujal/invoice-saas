"""Phase 28 -- Uruguayan RUT validation.

FIXTURES: every "valid" RUT used here is either a publicly listed
company RUT (Antel, 21-100342-001-7) or a value constructed by computing
the correct check digit with the documented algorithm. No customer or
production data appears anywhere in this file.
"""

from decimal import Decimal  # noqa: F401 -- keeps the import style uniform with siblings

import pytest

from app.customer_validation import normalize_tax_id
from app.imports.customers import (
    REASON_DUPLICATE_TAX_ID,
    REASON_INVALID_RUT,
    make_row_processor,
)
from app.imports.types import PreviewRowStatus
from app.services.customers import (
    InvalidUruguayRutError,
    TaxIdDuplicateError,
    create_customer_record,
)
from app.uruguay_rut import (
    compute_rut_check_digit,
    format_uruguay_rut,
    is_valid_uruguay_rut,
    should_validate_as_uruguay_rut,
)
from tests.factories import make_customer, make_org_with_owner

# Publicly listed (Antel). Used as the anchor fixture because its check
# digit can be verified against a real, published identifier rather than
# against our own implementation.
ANTEL = "211003420017"


def with_check_digit(first_eleven: str) -> str:
    return first_eleven + str(compute_rut_check_digit(first_eleven))


# --- algorithm ---------------------------------------------------------


def test_check_digit_matches_a_publicly_listed_rut():
    assert compute_rut_check_digit(ANTEL[:11]) == int(ANTEL[11])


def test_check_digit_refuses_wrong_length_rather_than_guessing():
    with pytest.raises(ValueError):
        compute_rut_check_digit("2110034200")
    with pytest.raises(ValueError):
        compute_rut_check_digit("abcdefghijk")


# --- validation --------------------------------------------------------


@pytest.mark.parametrize(
    "value",
    [
        ANTEL,
        "21-100342-001-7",
        "21.100342.001-7",
        "RUT 21-100342-001-7",
        "rut:211003420017",
        "  211003420017  ",
    ],
)
def test_valid_rut_accepted_in_any_reasonable_formatting(value):
    assert is_valid_uruguay_rut(value) is True


def test_invalid_check_digit_rejected():
    wrong = ANTEL[:11] + ("8" if ANTEL[11] != "8" else "9")
    assert is_valid_uruguay_rut(wrong) is False


@pytest.mark.parametrize("value", ["2110034200", "2110034200178", "", "   ", "abcdefghijkl"])
def test_invalid_length_or_shape_rejected(value):
    assert is_valid_uruguay_rut(value) is False


def test_formatting_helper_is_display_only():
    assert format_uruguay_rut(ANTEL) == "21-100342-001-7"
    # Never a second, quieter validator: an invalid value comes back
    # untouched rather than being reshaped into something that looks
    # legitimate.
    assert format_uruguay_rut("not-a-rut") == "not-a-rut"


# --- the trigger rule (international safety) ---------------------------


@pytest.mark.parametrize(
    "value,label,expected",
    [
        (ANTEL, "RUT", True),
        (ANTEL, "Tax ID", False),          # numeric, but not a Uruguayan org
        ("B12345678", "RUT", False),       # alphanumeric -> never a RUT
        ("ESB12345678", "RUT", False),
        ("RUT 123", "Tax ID", True),       # explicit label = explicit intent
        ("", "RUT", False),
        (ANTEL, None, False),
    ],
)
def test_trigger_rule(value, label, expected):
    assert should_validate_as_uruguay_rut(value, tax_label=label) is expected


# --- normalization vs validation are separate --------------------------


def test_normalization_collides_formatted_and_unformatted():
    assert normalize_tax_id("21-100342-001-7") == normalize_tax_id(ANTEL)
    assert normalize_tax_id("12.345.678-9") == normalize_tax_id("123456789")


def test_normalization_strips_the_rut_label():
    """Phase 28 bug fix. Before this, "RUT 12.345.678-9" normalized to
    "rut123456789" and did NOT collide with "123456789", so the same
    taxpayer could be created twice -- despite normalize_tax_id's own
    docstring promising these compare equal."""
    assert normalize_tax_id("RUT 12.345.678-9") == normalize_tax_id("123456789")


def test_normalization_leaves_international_identifiers_intact():
    assert normalize_tax_id("B12345678") == "b12345678"
    assert normalize_tax_id("ES-B-12345678") == "esb12345678"


def test_normalization_never_validates():
    """The split in responsibilities: normalization answers "what
    characters represent this", never "is this real"."""
    assert normalize_tax_id("999999999999") == "999999999999"
    assert is_valid_uruguay_rut("999999999999") is False


# --- create/update wiring ----------------------------------------------


def _uruguayan_org(db, email, name):
    owner = make_org_with_owner(db, email=email, org_name=name)
    owner.organization.tax_label = "RUT"
    db.commit()
    return owner


def test_create_customer_rejects_invalid_rut_in_a_uruguayan_org(db_session):
    owner = _uruguayan_org(db_session, "r1@example.com", "UY Co")
    with pytest.raises(InvalidUruguayRutError):
        create_customer_record(
            db_session, owner.organization.id, "Cliente", "", "", "", "211003420018"
        )


def test_create_customer_accepts_valid_rut(db_session):
    owner = _uruguayan_org(db_session, "r2@example.com", "UY Co 2")
    customer = create_customer_record(
        db_session, owner.organization.id, "Cliente", "", "", "", "21-100342-001-7"
    )
    # Stored exactly as typed -- validation never rewrites the value.
    assert customer.tax_id == "21-100342-001-7"


def test_international_tax_id_unaffected_in_a_uruguayan_org(db_session):
    owner = _uruguayan_org(db_session, "r3@example.com", "UY Co 3")
    customer = create_customer_record(
        db_session, owner.organization.id, "Spanish Co", "", "", "", "B12345678"
    )
    assert customer.tax_id == "B12345678"


def test_numeric_tax_id_unaffected_when_org_is_not_uruguayan(db_session):
    """A non-RUT organization keeps the pre-Phase-28 behavior exactly:
    no Uruguayan rules are applied to anything."""
    owner = make_org_with_owner(db_session, email="r4@example.com", org_name="Intl Co")
    customer = create_customer_record(
        db_session, owner.organization.id, "Any Co", "", "", "", "211003420018"
    )
    assert customer.tax_id == "211003420018"


def test_empty_tax_id_is_allowed(db_session):
    owner = _uruguayan_org(db_session, "r5@example.com", "UY Co 5")
    customer = create_customer_record(db_session, owner.organization.id, "No Tax Id", "", "", "", "")
    assert customer.tax_id == ""


def test_validity_is_checked_before_duplication(db_session):
    """An invalid RUT must report "invalid", never "duplicate" -- even
    when a customer with that same normalized value already exists."""
    owner = _uruguayan_org(db_session, "r6@example.com", "UY Co 6")
    invalid = "211003420018"
    make_customer(db_session, owner.organization, email="a@example.com", tax_id=invalid)

    with pytest.raises(InvalidUruguayRutError):
        create_customer_record(db_session, owner.organization.id, "Otro", "", "", "", invalid)


def test_formatted_and_unformatted_rut_still_collide_as_duplicates(db_session):
    owner = _uruguayan_org(db_session, "r7@example.com", "UY Co 7")
    create_customer_record(db_session, owner.organization.id, "Uno", "", "", "", ANTEL)
    with pytest.raises(TaxIdDuplicateError):
        create_customer_record(
            db_session, owner.organization.id, "Dos", "", "", "", "21-100342-001-7"
        )


def test_duplicate_detection_is_scoped_to_the_organization(db_session):
    """Tenant isolation is unchanged: the same RUT in two organizations
    is two different customers, never a collision."""
    a = _uruguayan_org(db_session, "r8@example.com", "UY A")
    b = _uruguayan_org(db_session, "r9@example.com", "UY B")
    create_customer_record(db_session, a.organization.id, "Cliente", "", "", "", ANTEL)
    other = create_customer_record(db_session, b.organization.id, "Cliente", "", "", "", ANTEL)
    assert other.organization_id == b.organization.id


# --- import ------------------------------------------------------------


def test_import_flags_an_invalid_rut_as_invalid_not_duplicate():
    process = make_row_processor({}, {}, tax_label="RUT")
    status, reason = process({"name": "Cliente", "tax_id": "211003420018"})
    assert status is PreviewRowStatus.invalid
    assert reason == REASON_INVALID_RUT


def test_import_accepts_a_valid_rut():
    process = make_row_processor({}, {}, tax_label="RUT")
    status, _ = process({"name": "Cliente", "email": "c@example.com", "tax_id": ANTEL})
    assert status is PreviewRowStatus.valid


def test_import_leaves_international_tax_ids_alone():
    process = make_row_processor({}, {}, tax_label="RUT")
    status, _ = process({"name": "Spanish Co", "email": "s@example.com", "tax_id": "B12345678"})
    assert status is PreviewRowStatus.valid


def test_import_without_a_tax_label_applies_no_uruguayan_rules():
    process = make_row_processor({}, {})
    status, _ = process({"name": "Any", "email": "a@example.com", "tax_id": "211003420018"})
    assert status is PreviewRowStatus.valid


def test_import_still_detects_duplicates_across_formatting():
    process = make_row_processor({}, {normalize_tax_id(ANTEL): ("id-1", "Existing")}, tax_label="RUT")
    status, reason = process({"name": "Cliente", "tax_id": "21-100342-001-7"})
    assert status is PreviewRowStatus.duplicate
    assert reason == REASON_DUPLICATE_TAX_ID
