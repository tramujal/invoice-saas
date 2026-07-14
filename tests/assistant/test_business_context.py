"""build_business_context (fed into the AI system prompt) must never leak
another organization's data into the prompt -- checked by inspecting what
was actually passed to the fake provider, since that's the exact string
a real model would see."""

from tests.factories import make_customer, make_org_with_owner


def test_business_context_is_scoped_to_calling_organization(client, db_session, fake_ai_provider):
    org_a = make_org_with_owner(db_session, email="owner-a@example.com", org_name="Org A")
    org_b = make_org_with_owner(db_session, email="owner-b@example.com", org_name="Org B")
    make_customer(db_session, org_a.organization, name="Alpha Customer Ltd")
    make_customer(db_session, org_b.organization, name="Beta Customer Ltd")

    response = client.post(
        f"/organizations/{org_a.organization.id}/assistant/chat",
        json={"message": "hello"},
        headers=org_a.auth_headers,
    )
    assert response.status_code == 200
    assert len(fake_ai_provider.calls) == 1
    system_prompt = fake_ai_provider.calls[0][0]

    assert "Alpha Customer Ltd" in system_prompt
    assert "Beta Customer Ltd" not in system_prompt
    assert "Org B" not in system_prompt
