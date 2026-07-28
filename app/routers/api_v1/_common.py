"""Shared OpenAPI response documentation for the public API -- every
route in app/routers/api_v1 hits the exact same authentication/
authorization/plan-limit machinery (see app.api_key_auth,
app.services.plan_limits), so its failure shapes are identical
everywhere. Centralizing them here means every endpoint's docs describe
the true, shared error contract, and a future change to that contract
(e.g. a new field on the 409 body) only needs updating in one place.
"""

AUTH_RESPONSES: dict[int | str, dict] = {
    401: {
        "description": "Missing, malformed, unrecognized, revoked, or expired API key.",
        "content": {
            "application/json": {
                "example": {"detail": {"code": "invalid_api_key", "message": "Invalid or missing API key."}}
            }
        },
    },
    403: {
        "description": "The API key lacks the permission this endpoint requires, "
        "or the organization is suspended.",
        "content": {
            "application/json": {
                "example": {
                    "detail": {
                        "code": "api_key_permission_denied",
                        "message": "This API key does not have the 'customers.write' permission.",
                    }
                }
            }
        },
    },
    429: {
        "description": "Rate limit exceeded.",
        "content": {"application/json": {"example": {"detail": {"code": "rate_limit_exceeded"}}}},
    },
}

PLAN_LIMIT_RESPONSE: dict[int | str, dict] = {
    409: {
        "description": "This organization's plan limit for this resource has been reached.",
        "content": {
            "application/json": {
                "example": {
                    "detail": {
                        "code": "plan_limit_reached",
                        "resource": "customers",
                        "used": 100,
                        "limit": 100,
                        "plan": {"id": "plan_free", "code": "free", "name": "Free"},
                        "message": "You've reached your plan's customers limit (100/100) on the Free plan.",
                    }
                }
            }
        },
    }
}

NOT_FOUND_RESPONSE: dict[int | str, dict] = {
    404: {
        "description": "No resource with this id exists in the authenticated organization.",
        "content": {"application/json": {"example": {"detail": "Customer not found"}}},
    }
}
