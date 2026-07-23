"""Phase 14A -- GET /organizations/{id}/entitlements, the tenant-facing,
read-only view of an organization's current plan. See
tests/platform_admin/test_plans.py for the platform-admin side."""

from app.security import create_access_token
from tests.factories import make_org_with_owner, make_user


def _super_admin_headers(db_session):
    admin = make_user(db_session, email="entitlements-admin@example.com")
    admin.platform_role = "super_admin"
    db_session.commit()
    return {"Authorization": f"Bearer {create_access_token(admin.id)}"}


def test_entitlements_requires_org_membership(client, db_session):
    owner = make_org_with_owner(db_session, email="ent-owner@example.com", org_name="Ent Co")
    stranger = make_user(db_session, email="ent-stranger@example.com")
    stranger_headers = {"Authorization": f"Bearer {create_access_token(stranger.id)}"}

    response = client.get(f"/organizations/{owner.organization.id}/entitlements", headers=stranger_headers)

    assert response.status_code == 403


def test_entitlements_reflects_the_organization_default_plan(client, db_session):
    owner = make_org_with_owner(db_session, email="ent-free@example.com", org_name="Ent Free Co")

    response = client.get(f"/organizations/{owner.organization.id}/entitlements", headers=owner.auth_headers)

    assert response.status_code == 200
    body = response.json()
    assert body["plan_code"] == "free"
    assert body["plan_name"] == "Free"
    assert body["limits"]["max_users"] == 2
    assert body["limits"]["max_customers"] == 100
    assert body["limits"]["max_products"] == 100
    assert body["limits"]["max_invoices_per_month"] == 50
    assert body["limits"]["max_quotes_per_month"] == 50
    assert body["limits"]["max_ai_actions_per_month"] == 25
    assert body["limits"]["storage_limit_mb"] == 500
    assert body["features"]["custom_branding_enabled"] is False
    assert body["features"]["api_access_enabled"] is False
    assert body["features"]["advanced_reports_enabled"] is False


def test_entitlements_serializes_unlimited_as_null(client, db_session):
    from app.models import Plan

    owner = make_org_with_owner(db_session, email="ent-enterprise@example.com", org_name="Ent Enterprise Co")
    enterprise = db_session.query(Plan).filter_by(code="enterprise").one()

    change = client.patch(
        f"/admin/organizations/{owner.organization.id}/plan",
        json={"plan_id": enterprise.id, "reason": "moving to enterprise for entitlements test"},
        headers=_super_admin_headers(db_session),
    )
    assert change.status_code == 200

    response = client.get(f"/organizations/{owner.organization.id}/entitlements", headers=owner.auth_headers)

    assert response.status_code == 200
    body = response.json()
    assert body["plan_code"] == "enterprise"
    assert body["limits"]["max_users"] is None
    assert body["limits"]["max_customers"] is None
    assert body["limits"]["max_products"] is None
    assert body["limits"]["max_invoices_per_month"] is None
    assert body["limits"]["max_quotes_per_month"] is None
    assert body["limits"]["max_ai_actions_per_month"] is None
    assert body["limits"]["storage_limit_mb"] is None
    assert body["features"]["custom_branding_enabled"] is True
    assert body["features"]["api_access_enabled"] is True
    assert body["features"]["advanced_reports_enabled"] is True


def test_entitlements_reflects_a_plan_with_a_zero_unavailable_limit(client, db_session):
    """0 means unavailable, distinctly from NULL (unlimited) -- proves
    the API preserves that distinction rather than collapsing both to
    null or both to a falsy zero."""
    admin_headers = _super_admin_headers(db_session)
    owner = make_org_with_owner(db_session, email="ent-zero@example.com", org_name="Ent Zero Co")
    zero_plan_response = client.post(
        "/admin/plans",
        json={
            "code": "no-ai",
            "name": "No AI",
            "max_ai_actions_per_month": 0,
            "reason": "test plan with an unavailable limit",
        },
        headers=admin_headers,
    )
    assert zero_plan_response.status_code == 201
    zero_plan_id = zero_plan_response.json()["id"]

    client.patch(
        f"/admin/organizations/{owner.organization.id}/plan",
        json={"plan_id": zero_plan_id, "reason": "test"},
        headers=admin_headers,
    )

    response = client.get(f"/organizations/{owner.organization.id}/entitlements", headers=owner.auth_headers)

    assert response.status_code == 200
    assert response.json()["limits"]["max_ai_actions_per_month"] == 0


def test_entitlements_behavior_comes_from_values_not_built_in_plan_codes(client, db_session):
    """The four built-in codes (free/starter/pro/enterprise) are stable
    identifiers for seeding/display/lookup only -- nothing in
    app.services.entitlements or the routers that call it may special-
    case them. Proven here by creating a plan with a totally arbitrary,
    non-built-in code and confirming its entitlements resolve purely
    from its own column values: NULL limits read back as unlimited
    (None) and enabled feature flags read back as True, exactly as they
    would for any built-in plan with the same values -- the system must
    support a future "agency"/"education"/"partner"/"custom" plan
    without any code change here."""
    admin_headers = _super_admin_headers(db_session)
    owner = make_org_with_owner(db_session, email="ent-custom-code@example.com", org_name="Ent Custom Code Co")

    custom = client.post(
        "/admin/plans",
        json={
            "code": "agency",
            "name": "Agency",
            "max_users": None,
            "max_customers": None,
            "max_products": None,
            "max_invoices_per_month": None,
            "max_quotes_per_month": None,
            "max_ai_actions_per_month": None,
            "storage_limit_mb": None,
            "custom_branding_enabled": True,
            "api_access_enabled": True,
            "advanced_reports_enabled": True,
            "reason": "arbitrary non-built-in plan code for a no-magic-strings regression test",
        },
        headers=admin_headers,
    )
    assert custom.status_code == 201
    custom_plan_id = custom.json()["id"]

    client.patch(
        f"/admin/organizations/{owner.organization.id}/plan",
        json={"plan_id": custom_plan_id, "reason": "test"},
        headers=admin_headers,
    )

    response = client.get(f"/organizations/{owner.organization.id}/entitlements", headers=owner.auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["plan_code"] == "agency"
    # Same shape "enterprise" would produce -- driven entirely by this
    # plan's own NULL limits and enabled features, not by its code.
    assert body["limits"]["max_users"] is None
    assert body["limits"]["storage_limit_mb"] is None
    assert body["features"]["api_access_enabled"] is True
    assert body["features"]["advanced_reports_enabled"] is True

    from app.services.entitlements import PlanFeature, PlanLimit, feature_enabled, get_limit, get_organization_entitlements

    entitlements = get_organization_entitlements(db_session, owner.organization.id)
    assert entitlements.plan_code == "agency"
    assert get_limit(entitlements, PlanLimit.max_users) is None
    assert feature_enabled(entitlements, PlanFeature.api_access) is True


def test_entitlements_endpoint_never_reads_platform_role(client, db_session):
    """A user with no platform_role at all, but who IS an ordinary org
    member, still sees their own organization's entitlements -- this
    endpoint is gated by organization membership only, never by the
    platform-administration axis."""
    owner = make_org_with_owner(db_session, email="ent-no-platform-role@example.com", org_name="Ent No Role Co")

    response = client.get(f"/organizations/{owner.organization.id}/entitlements", headers=owner.auth_headers)

    assert response.status_code == 200
    assert owner.user.platform_role is None
