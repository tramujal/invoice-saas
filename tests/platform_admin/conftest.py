import pytest

from app.security import create_access_token
from tests.factories import make_user


@pytest.fixture
def super_admin(db_session):
    user = make_user(db_session, email="super-admin@example.com")
    user.platform_role = "super_admin"
    db_session.commit()
    return user


@pytest.fixture
def super_admin_headers(super_admin) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(super_admin.id)}"}
