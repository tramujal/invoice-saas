import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.database import SessionLocal, get_db
from app.deps import get_current_user
from app.email.base import EmailMessage, EmailSendError
from app.email.factory import get_email_sender
from app.email.templates import build_password_reset_email
from app.localization import DEFAULT_LANGUAGE
from app.models import Organization, OrganizationMember, PasswordResetToken, User
from app.password_reset import (
    RESET_TOKEN_TTL_MINUTES,
    build_reset_link,
    generate_reset_token,
    hash_reset_token,
    tokens_match,
)
from app.schemas import (
    AuthResponse,
    ForgotPasswordRequest,
    ForgotPasswordResponse,
    LoginRequest,
    MeResponse,
    OrganizationSummary,
    RegisterRequest,
    ResetPasswordRequest,
    ResetPasswordResponse,
    UserResponse,
)
from app.security import create_access_token, hash_password, verify_password

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

# Hashed once at import time so a login attempt against an unknown email still
# runs a bcrypt comparison, keeping response timing similar to a real user.
_DUMMY_PASSWORD_HASH = hash_password("dummy-password-for-constant-time-comparison")

FORGOT_PASSWORD_MESSAGE = (
    "If an account exists for this email, a password reset link has been sent."
)
RESET_PASSWORD_SUCCESS_MESSAGE = (
    "Your password has been reset. You can now sign in with your new password."
)
RESET_PASSWORD_ERROR_MESSAGE = "Invalid or expired reset token."


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


def issue_password_reset(db: Session, user: User, language: str = DEFAULT_LANGUAGE) -> str:
    """Invalidates the user's prior unused reset tokens, issues a new one,
    and emails the reset link. Returns the raw token (the caller decides
    what, if anything, to do with it — production code discards it once the
    email is sent; tests can capture it directly instead of receiving email).

    `language` is the public/marketing-page language the visitor had
    selected when submitting the forgot-password form (see
    ForgotPasswordRequest.language), used only to localize the email.
    """
    now = datetime.now(timezone.utc)
    db.execute(
        update(PasswordResetToken)
        .where(
            PasswordResetToken.user_id == user.id,
            PasswordResetToken.used_at.is_(None),
        )
        .values(used_at=now)
    )

    raw_token = generate_reset_token()
    db.add(
        PasswordResetToken(
            user_id=user.id,
            token_hash=hash_reset_token(raw_token),
            expires_at=now + timedelta(minutes=RESET_TOKEN_TTL_MINUTES),
        )
    )
    db.commit()

    reset_link = build_reset_link(raw_token)
    subject, body = build_password_reset_email(reset_link, language)
    try:
        email_sender = get_email_sender()
        email_sender.send(
            EmailMessage(to=user.email, subject=subject, text_body=body, attachments=[])
        )
    except (EmailSendError, HTTPException):
        # Never surfaced to the caller: forgot-password always returns the
        # same generic response, so a delivery failure (including email
        # simply not being configured in this environment) can't become a
        # signal that distinguishes a real account from a nonexistent one.
        logger.warning("Password reset email could not be sent to user %s", user.id)

    return raw_token


def _issue_password_reset_task(user_id: str, language: str) -> None:
    """Background-task entry point.

    Deliberately takes only plain scalars (user_id, language) — never the
    request-scoped `db: Session = Depends(get_db)` from forgot_password()
    below, which FastAPI closes once the response is sent (get_db's
    `finally: db.close()`). Reusing that session here would operate on a
    closed connection; instead this opens and closes its own SessionLocal,
    independent of the request lifecycle.
    """
    db = SessionLocal()
    try:
        user = db.scalar(select(User).where(User.id == user_id))
        if user is not None:
            issue_password_reset(db, user, language)
    finally:
        db.close()


@router.post("/forgot-password", response_model=ForgotPasswordResponse)
def forgot_password(
    body: ForgotPasswordRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> ForgotPasswordResponse:
    # Token creation and email sending happen in a background task, after
    # this response is already sent, so the response time can't reveal
    # whether the account exists — otherwise "email exists" would take a
    # full email-provider round-trip while "email doesn't exist" returns
    # instantly, a much larger and more obvious timing gap than the one
    # _DUMMY_PASSWORD_HASH exists to close for login. Only user.id and the
    # submitted language (plain strings) cross into the background task —
    # never the request's `db` session; see _issue_password_reset_task.
    user = db.scalar(select(User).where(User.email == body.email))
    if user is not None:
        background_tasks.add_task(_issue_password_reset_task, user.id, body.language.value)
    return ForgotPasswordResponse(message=FORGOT_PASSWORD_MESSAGE)


@router.post("/reset-password", response_model=ResetPasswordResponse)
def reset_password(
    body: ResetPasswordRequest, db: Session = Depends(get_db)
) -> ResetPasswordResponse:
    token_hash = hash_reset_token(body.token)
    now = datetime.now(timezone.utc)

    # Expiry and used-at are folded into the query itself so "token doesn't
    # exist", "token expired", and "token already used" are indistinguishable
    # to the caller — same principle as login's single "Invalid email or
    # password" message.
    reset_token = db.scalar(
        select(PasswordResetToken).where(
            PasswordResetToken.token_hash == token_hash,
            PasswordResetToken.used_at.is_(None),
            PasswordResetToken.expires_at > now,
        )
    )
    if reset_token is None or not tokens_match(body.token, reset_token.token_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=RESET_PASSWORD_ERROR_MESSAGE,
        )

    user = db.scalar(select(User).where(User.id == reset_token.user_id))
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=RESET_PASSWORD_ERROR_MESSAGE,
        )

    user.hashed_password = hash_password(body.new_password)
    reset_token.used_at = now
    db.commit()

    return ResetPasswordResponse(message=RESET_PASSWORD_SUCCESS_MESSAGE)
