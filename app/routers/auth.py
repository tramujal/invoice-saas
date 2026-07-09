from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user
from app.models import Organization, OrganizationMember, User
from app.schemas import (
    AuthResponse,
    LoginRequest,
    MeResponse,
    OrganizationSummary,
    RegisterRequest,
    UserResponse,
)
from app.security import create_access_token, hash_password, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])

# Hashed once at import time so a login attempt against an unknown email still
# runs a bcrypt comparison, keeping response timing similar to a real user.
_DUMMY_PASSWORD_HASH = hash_password("dummy-password-for-constant-time-comparison")


def _user_organizations(db: Session, user_id: str) -> list[Organization]:
    return list(
        db.scalars(
            select(Organization)
            .join(
                OrganizationMember,
                OrganizationMember.organization_id == Organization.id,
            )
            .where(OrganizationMember.user_id == user_id)
            .order_by(Organization.name)
        ).all()
    )


@router.post(
    "/register", response_model=AuthResponse, status_code=status.HTTP_201_CREATED
)
def register(body: RegisterRequest, db: Session = Depends(get_db)) -> AuthResponse:
    existing = db.scalar(select(User).where(User.email == body.email))
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        )

    user = User(email=body.email, hashed_password=hash_password(body.password))
    db.add(user)
    db.flush()

    organization = Organization(name=body.organization_name)
    db.add(organization)
    db.flush()

    db.add(OrganizationMember(user_id=user.id, organization_id=organization.id))
    db.commit()
    db.refresh(user)

    return AuthResponse(
        access_token=create_access_token(user.id),
        user=UserResponse.model_validate(user),
        organizations=[OrganizationSummary.model_validate(organization)],
    )


@router.post("/login", response_model=AuthResponse)
def login(body: LoginRequest, db: Session = Depends(get_db)) -> AuthResponse:
    user = db.scalar(select(User).where(User.email == body.email))
    password_valid = verify_password(
        body.password, user.hashed_password if user else _DUMMY_PASSWORD_HASH
    )

    if user is None or not password_valid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    return AuthResponse(
        access_token=create_access_token(user.id),
        user=UserResponse.model_validate(user),
        organizations=[
            OrganizationSummary.model_validate(o)
            for o in _user_organizations(db, user.id)
        ],
    )


@router.get("/me", response_model=MeResponse)
def me(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> MeResponse:
    return MeResponse(
        user=UserResponse.model_validate(current_user),
        organizations=[
            OrganizationSummary.model_validate(o)
            for o in _user_organizations(db, current_user.id)
        ],
    )
