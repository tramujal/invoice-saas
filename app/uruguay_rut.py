"""Uruguayan RUT (Registro Único Tributario) structural validation.

Deliberately SEPARATE from app.customer_validation.normalize_tax_id, which
answers a different question. The split is the whole point of this module:

    normalize_tax_id(value)      -> "what canonical characters represent
                                     this identifier?" (comparison key,
                                     country-agnostic, never rejects)

    validate_uruguay_rut(value)  -> "is this a structurally valid
                                     Uruguayan RUT?" (yes/no, Uruguay-
                                     specific, never rewrites anything)

This module never rewrites a persisted value and never performs a lookup
against DGI or any other registry -- it is pure arithmetic on the digits.
A RUT that is structurally valid may still not exist; that is a different
(and out-of-scope) question, and nothing here should be read as implying
otherwise.

FORMAT (corroborated by two independent public sources, and verified
against a publicly listed RUT rather than any customer data -- see
docs/taxes_and_rut.md for the sources):

    12 digits total: NN NNNNNN NNN D
      - 2 digits  registration/office number
      - 6 digits  taxpayer number
      - 3 digits  dependency code (commonly "001")
      - 1 digit   check digit

CHECK DIGIT: modulus 11 over the first 11 digits, with the fixed weight
vector below applied left to right. The expected check digit is
(11 - (weighted_sum % 11)) % 11 -- the outer % 11 is what maps a
remainder of 0 back to a check digit of 0.

Worked example using Antel's public RUT 21-100342-001-7:
    digits  2  1  1  0  0  3  4  2  0  0  1
    weights 4  3  2  9  8  7  6  5  4  3  2
    products 8  3  2  0  0 21 24 10  0  0  2  -> sum 70
    70 % 11 = 4 ; (11 - 4) % 11 = 7          -> matches the real check digit
"""

import re

# Applied left to right across the first 11 digits. Do not reorder: the
# sequence is not a simple descending run (it jumps 2 -> 9 at position 4),
# and "fixing" that would silently invalidate every real RUT.
_CHECK_DIGIT_WEIGHTS = (4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2)

RUT_LENGTH = 12

# An explicit "RUT" / "R.U.T." label the user typed in front of the digits.
# Matching this is what lets us distinguish "the user is telling us this is
# a Uruguayan RUT" from "this is some other country's identifier that
# happens to be numeric" -- see should_validate_as_uruguay_rut.
_RUT_PREFIX_RE = re.compile(r"^r\.?u\.?t\.?[\s:.\-]*", re.IGNORECASE)

_NON_DIGITS_RE = re.compile(r"\D")


def strip_rut_prefix(value: str) -> str:
    """Removes a leading "RUT"/"R.U.T." label, if present. Returns the
    remainder unchanged otherwise."""
    return _RUT_PREFIX_RE.sub("", value.strip(), count=1)


def has_rut_prefix(value: str) -> bool:
    """True when the user explicitly labelled the value as a RUT. Treated
    as a declaration of intent: such a value is always validated as a RUT,
    so "RUT 123" reports a clear error instead of being quietly accepted
    as some generic foreign identifier."""
    return bool(_RUT_PREFIX_RE.match(value.strip()))


def rut_digits(value: str) -> str:
    """The bare digit string, with any label and formatting removed."""
    return _NON_DIGITS_RE.sub("", strip_rut_prefix(value))


def compute_rut_check_digit(first_eleven_digits: str) -> int:
    """The modulus-11 check digit for the first 11 digits of a RUT.

    Raises ValueError rather than guessing if given anything other than
    exactly 11 digits -- a silent wrong answer here would be far worse
    than a loud failure, since callers use this to accept or reject a
    taxpayer identifier.
    """
    if len(first_eleven_digits) != len(_CHECK_DIGIT_WEIGHTS) or not first_eleven_digits.isdigit():
        raise ValueError("compute_rut_check_digit expects exactly 11 digits")
    weighted_sum = sum(
        int(digit) * weight
        for digit, weight in zip(first_eleven_digits, _CHECK_DIGIT_WEIGHTS, strict=True)
    )
    return (11 - (weighted_sum % 11)) % 11


def is_valid_uruguay_rut(value: str) -> bool:
    """True when `value` is a structurally valid Uruguayan RUT.

    Accepts any reasonable formatting the user might type -- "12.345.678-9",
    "123456789", "RUT 21-100342-001-7" all reach the same arithmetic (see
    this module's docstring on why normalization for *comparison* lives
    elsewhere and is not reused here: that function lowercases and folds
    accents for dedupe keys, which is neither necessary nor sufficient for
    a digits-only structural check).
    """
    digits = rut_digits(value)
    if len(digits) != RUT_LENGTH:
        return False
    return compute_rut_check_digit(digits[:11]) == int(digits[11])


def format_uruguay_rut(value: str) -> str:
    """Human-friendly display form, "21-100342-001-7". Returns the input
    untouched when it isn't a valid RUT -- formatting is a presentation
    nicety and must never be a second, quieter place that decides what
    counts as valid."""
    digits = rut_digits(value)
    if not is_valid_uruguay_rut(digits):
        return value
    return f"{digits[:2]}-{digits[2:8]}-{digits[8:11]}-{digits[11]}"


def organization_uses_rut(tax_label: str | None) -> bool:
    """Whether an organization's configured tax label says "RUT".

    Organization.tax_label already exists precisely to express "what is
    the tax identifier called here", so it is reused as the country
    signal rather than introducing a country/tax_id_type column that
    would duplicate information the model already carries. An
    organization that needs to store numeric identifiers from several
    countries can simply label the field something else ("Tax ID"), which
    is exactly what that field is for.
    """
    if not tax_label:
        return False
    canonical = tax_label.replace(".", "").strip().upper()
    return canonical in ("RUT", "RUT UY", "RUT URUGUAY")


def should_validate_as_uruguay_rut(value: str, *, tax_label: str | None) -> bool:
    """The trigger rule -- deliberately narrow, so adding RUT validation
    can never start rejecting an existing international customer.

    Validate when EITHER:
      1. the user explicitly wrote a "RUT" label in the value, or
      2. the organization's own tax label says RUT *and* the value is
         entirely digits (an alphanumeric identifier -- Spanish CIF
         "B12345678", a VAT number "ESB12345678" -- is never a RUT and is
         left alone even in a Uruguayan organization).

    Everything else is treated as a generic international tax identifier
    and is stored exactly as before, with no validation whatsoever.
    """
    if not value or not value.strip():
        return False
    if has_rut_prefix(value):
        return True
    if not organization_uses_rut(tax_label):
        return False
    bare = strip_rut_prefix(value).strip()
    # "Entirely digits once formatting punctuation is removed" -- the same
    # punctuation set normalize_tax_id already treats as meaningless.
    return bool(re.fullmatch(r"[\d\s.\-/]+", bare))
