"""Pure unit tests for app.platform_audit_sanitize -- independent of the
HTTP layer, pinning down the redaction/masking rules the audit-log
endpoint relies on (see tests/platform_admin/test_audit_log.py for the
router-level proof these are actually wired in)."""

import json

from app.platform_audit_sanitize import mask_client_ip, sanitize_audit_details


def test_sanitize_audit_details_returns_none_for_empty_or_missing():
    assert sanitize_audit_details(None) is None
    assert sanitize_audit_details("") is None


def test_sanitize_audit_details_returns_none_for_malformed_json():
    assert sanitize_audit_details("{not valid json") is None


def test_sanitize_audit_details_returns_none_for_non_object_top_level():
    assert sanitize_audit_details(json.dumps(["a", "b"])) is None
    assert sanitize_audit_details(json.dumps("just a string")) is None


def test_sanitize_audit_details_passes_through_ordinary_values():
    raw = json.dumps({"old_role": None, "new_role": "super_admin"})
    assert sanitize_audit_details(raw) == {"old_role": None, "new_role": "super_admin"}


def test_sanitize_audit_details_redacts_sensitive_keys_case_insensitively_and_nested():
    raw = json.dumps(
        {
            "Token": "abc",
            "PASSWORD": "def",
            "secretValue": "ghi",
            "api_key": "jkl",
            "Authorization": "Bearer xyz",
            "cookie_jar": "mno",
            "password_hash": "pqr",
            "nested": {"reset_token": "stu", "safe": "kept"},
            "list_of_things": [{"api_key": "vwx"}, {"safe": "also kept"}],
            "safe_field": "unchanged",
        }
    )
    result = sanitize_audit_details(raw)
    assert result["Token"] == "[redacted]"
    assert result["PASSWORD"] == "[redacted]"
    assert result["secretValue"] == "[redacted]"
    assert result["api_key"] == "[redacted]"
    assert result["Authorization"] == "[redacted]"
    assert result["cookie_jar"] == "[redacted]"
    assert result["password_hash"] == "[redacted]"
    assert result["nested"]["reset_token"] == "[redacted]"
    assert result["nested"]["safe"] == "kept"
    assert result["list_of_things"][0]["api_key"] == "[redacted]"
    assert result["list_of_things"][1]["safe"] == "also kept"
    assert result["safe_field"] == "unchanged"


def test_sanitize_audit_details_returns_none_when_oversized():
    raw = json.dumps({"blob": "x" * 10_000})
    assert sanitize_audit_details(raw) is None


def test_mask_client_ip_ipv4_masks_to_slash_24():
    assert mask_client_ip("203.0.113.42") == "203.0.113.0"


def test_mask_client_ip_ipv6_masks_to_slash_48():
    assert mask_client_ip("2001:db8:1234:5678::1") == "2001:db8:1234::"


def test_mask_client_ip_returns_none_for_unparseable_or_missing():
    assert mask_client_ip(None) is None
    assert mask_client_ip("") is None
    assert mask_client_ip("unknown") is None
    assert mask_client_ip("not-an-ip") is None
