"""Shared Customer field rules — the single source of truth for email
format and tax_id normalization, used by both the regular CRUD schemas
(app.schemas.CustomerCreateRequest/CustomerUpdateRequest) and the CSV/XLSX
importer (app.imports.customers). Neither call site re-implements or
duplicates these rules; both import from here.
"""

import re
import unicodedata

# Same shape as the frontend's pre-existing client-side check
# (AddCustomerForm.tsx's simpleEmailValid) — deliberately simple (not a
# full RFC 5322 validator): good enough to reject obviously-malformed
# input ("not-an-email") without rejecting real addresses a stricter
# regex might choke on.
_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


def is_valid_email_format(value: str) -> bool:
    return bool(_EMAIL_RE.match(value))


def normalize_customer_email(value: str) -> str:
    """Trim + lowercase — used only for *comparison* (duplicate detection).
    Never rewrites what's actually persisted via the regular create/update
    endpoints, which store the value the user typed as-is."""
    return value.strip().lower()


# Formatting punctuation people commonly use in tax identifiers (RUT, CUIT,
# NIF, CIF, CNPJ, VAT numbers, ...) that carries no identifying meaning of
# its own — "12.345.678-9" and "123456789" should compare as the same id.
_TAX_ID_PUNCTUATION_RE = re.compile(r"[\s\.\-/]+")


def normalize_tax_id(value: str) -> str:
    """Normalizes a tax id for *comparison* purposes: strips common
    formatting separators (spaces, dots, hyphens, slashes) and case, so
    differently-formatted representations of the same id compare equal.
    Never rewrites the persisted value — same principle as
    normalize_customer_email above.

    Deliberately more than trim/lowercase (per the explicit requirement):
    "RUT 12.345.678-9" and "123456789" must normalize identically. This is
    still a per-organization comparison key only — no cross-organization
    uniqueness is ever implied or enforced by this function.
    """
    stripped = _TAX_ID_PUNCTUATION_RE.sub("", value)
    # NFKD + drop combining marks handles accented characters the same way
    # header normalization does (see app/imports/column_mapping.py), so
    # e.g. a stray accented character doesn't cause two otherwise-identical
    # ids to compare as different.
    decomposed = unicodedata.normalize("NFKD", stripped)
    without_accents = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return without_accents.strip().lower()


# Everything except digits and a leading '+' is pure formatting (spaces,
# parentheses, dashes, dots) that carries no identifying meaning --
# "+598 99 123 456", "(598) 99-123-456" and "598.99.123.456" should
# compare the same way "12.345.678-9" and "123456789" do for tax ids.
_PHONE_PUNCTUATION_RE = re.compile(r"[^\d+]")


def normalize_customer_phone(value: str) -> str:
    """Normalizes a phone number for *comparison* purposes (Level 3
    duplicate detection): strips spaces, parentheses, and dashes, and
    folds the "00" international prefix to "+" (ITU-equivalent, e.g. one
    customer entered as "0059899123456" and another as "+598 99 123 456"
    are the same number). Never rewrites the persisted value -- same
    principle as normalize_customer_email/normalize_tax_id above. Does
    NOT attempt to infer a missing country code -- "99123456" and
    "+59899123456" intentionally do not compare equal, since guessing a
    country code would be exactly the kind of fuzzy matching this feature
    explicitly avoids.
    """
    stripped = _PHONE_PUNCTUATION_RE.sub("", value.strip())
    if stripped.startswith("00"):
        stripped = "+" + stripped[2:]
    return stripped


_NAME_WHITESPACE_RE = re.compile(r"\s+")


def normalize_customer_name(value: str) -> str:
    """Normalizes a customer name for *comparison* purposes (Level 4
    duplicate detection, suggestion-only): trim + collapse repeated
    whitespace + lowercase. Deliberately simple -- no fuzzy/typo-tolerant
    matching (no edit distance, no phonetic matching): a cheap, exact,
    case/whitespace-insensitive comparison is all a "suggestion, never
    blocks" signal needs, and anything more expensive would run on every
    customer create/edit. Never rewrites the persisted value."""
    return _NAME_WHITESPACE_RE.sub(" ", value.strip()).lower()
