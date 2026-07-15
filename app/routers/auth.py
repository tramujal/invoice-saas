import logging
from datetime import datetime, timedelta, timezone
from typing import NamedTuple

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.database import SessionLocal, get_db
from app.deps import get_current_user
from app.email.base import EmailMessage, EmailSendError
from app.email.factory import get_email_sender
from app.email.templates import build_password_reset_email, build_verification_email
from app.email_verification import (
    VERIFICATION_TOKEN_TTL_HOURS,
    build_verification_link,
    generate_verification_token,
    hash_verification_token,
)
from app.localization import DEFAULT_LANGUAGE
from app.membership_role import MembershipRole
from app.models import (
    EmailVerificationToken,
    Organization,
    OrganizationMember,
    PasswordResetToken,
    User,
)
from app.password_reset import (
    RESET_TOKEN_TTL_MINUTES,
    build_reset_link,
    generate_reset_token,
    hash_reset_token,
    tokens_match,
)
from app.rate_limit import (
    FORGOT_PASSWORD_RULES,
    LOGIN_EMAIL_RULES,
    LOGIN_IP_RULES,
    REGISTER_RULES,
    RESEND_VERIFICATION_RULES,
    RESET_PASSWORD_RULES,
    VERIFY_EMAIL_RULES,
    RateLimitCheck,
    email_identity,
    enforce_rate_limit,
    ip_identity,
    user_identity,
    user_ip_identity,
)
from app.schemas import (
    AuthResponse,
    ForgotPasswordRequest,
    ForgotPasswordResponse,
    LoginRequest,
    MeResponse,
    OrganizationSummary,
    RegisterRequest,
    ResendVerificationResponse,
    ResetPasswordRequest,
    ResetPasswordResponse,
    UserResponse,
    VerifyEmailRequest,
    VerifyEmailResponse,
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

VERIFICATION_SENT_MESSAGE = "A verification email has been sent to your address."
ALREADY_VERIFIED_MESSAGE = "Your email address is already verified."
VERIFY_EMAIL_SUCCESS_MESSAGE = "Your email address has been verified."
VERIFY_EMAIL_ERROR_MESSAGE = "Invalid or expired verification token."


class _UserOrganization(NamedTuple):
    """An org the caller belongs to, paired with their own membership row --
    the membership is what carries .permissions (see
    OrganizationMember.permissions), needed to build OrganizationSummary
    without a second query per org."""

    organization: Organization
    member: OrganizationMember


def _user_organizations(db: Session, user_id: str) -> list[_UserOrganization]:
    rows = db.execute(
        select(Organization, OrganizationMember)
        .join(
            OrganizationMember,
            OrganizationMember.organization_id == Organization.id,
        )
        .where(OrganizationMember.user_id == user_id)
        .order_by(Organization.name)
    ).all()
    return [_UserOrganization(organization=org, member=member) for org, member in rows]


def _organization_summary(user_org: _UserOrganization) -> OrganizationSummary:
    return OrganizationSummary(
        id=user_org.organization.id,
        name=user_org.organization.name,
        currency_code=user_org.organization.currency_code,
        language=user_org.organization.language,
        permissions=user_org.member.permissions,
    )


@router.post(
    "/register", response_model=AuthResponse, status_code=status.HTTP_201_CREATED
)
def register(
    body: RegisterRequest,
    background_tasks: BackgroundTasks,
    request: Request,
    db: Session = Depends(get_db),
) -> AuthResponse:
    enforce_rate_limit(
        [RateLimitCheck(scope="auth:register:ip", identity=ip_identity(request), rules=REGISTER_RULES)]
    )

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

    # The org-creating user must always become its owner -- the "at least
    # one owner" invariant (app.services.team) has to hold from the very
    # first membership row, not just after someone later grants ownership.
    # OrganizationMember.role otherwise defaults to "member".
    membership = OrganizationMember(
        user_id=user.id, organization_id=organization.id, role=MembershipRole.owner.value
    )
    db.add(membership)
    db.commit()
    db.refresh(user)

    # Registration always succeeds and issues the normal JWT regardless of
    # whether the verification email can actually be sent — see
    # issue_email_verification, which swallows send failures the same way
    # issue_password_reset does. Only user.id and the submitted language
    # (plain strings) cross into the background task; see
    # _issue_email_verification_task for why the request's `db` session
    # can't be reused there.
    background_tasks.add_task(
        _issue_email_verification_task, user.id, body.language.value
    )

    return AuthResponse(
        access_token=create_access_token(user.id),
        user=UserResponse.model_validate(user),
        organizations=[
            _organization_summary(_UserOrganization(organization=organization, member=membership))
        ],
    )


@router.post("/login", response_model=AuthResponse)
def login(body: LoginRequest, request: Request, db: Session = Depends(get_db)) -> AuthResponse:
    # Two independent buckets: per-IP (5/min, 20/hour — catches a single
    # source hammering any account) and per-account via a hash of the
    # normalized email (10/hour — catches distributed brute force against
    # ONE account spread across many IPs, which the IP buckets alone can't
    # see). Checked regardless of whether the account exists, exactly like
    # the dummy-password-hash comparison below — the rate limiter must
    # never become a second timing/enumeration side-channel.
    enforce_rate_limit(
        [
            RateLimitCheck(scope="auth:login:ip", identity=ip_identity(request), rules=LOGIN_IP_RULES),
            RateLimitCheck(
                scope="auth:login:email", identity=email_identity(body.email), rules=LOGIN_EMAIL_RULES
            ),
        ]
    )

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
            _organization_summary(uo) for uo in _user_organizations(db, user.id)
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
            _organization_summary(uo) for uo in _user_organizations(db, current_user.id)
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
    request: Request,
    db: Session = Depends(get_db),
) -> ForgotPasswordResponse:
    enforce_rate_limit(
        [
            RateLimitCheck(
                scope="auth:forgot_password:ip", identity=ip_identity(request), rules=FORGOT_PASSWORD_RULES
            )
        ]
    )

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
    body: ResetPasswordRequest, request: Request, db: Session = Depends(get_db)
) -> ResetPasswordResponse:
    enforce_rate_limit(
        [
            RateLimitCheck(
                scope="auth:reset_password:ip", identity=ip_identity(request), rules=RESET_PASSWORD_RULES
            )
        ]
    )

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


def issue_email_verification(
    db: Session, user: User, language: str = DEFAULT_LANGUAGE
) -> str:
    """Invalidates the user's prior unused verification tokens, issues a new
    one, and emails the verification link. Returns the raw token (mirrors
    issue_password_reset's return-the-raw-token shape, useful for tests).

    `language` is the public/marketing-page language the visitor had
    selected when registering (see RegisterRequest.language) — or, for a
    resend, the user's organization's current language — used only to
    localize the email.
    """
    now = datetime.now(timezone.utc)
    db.execute(
        update(EmailVerificationToken)
        .where(
            EmailVerificationToken.user_id == user.id,
            EmailVerificationToken.used_at.is_(None),
        )
        .values(used_at=now)
    )

    raw_token = generate_verification_token()
    db.add(
        EmailVerificationToken(
            user_id=user.id,
            token_hash=hash_verification_token(raw_token),
            expires_at=now + timedelta(hours=VERIFICATION_TOKEN_TTL_HOURS),
        )
    )
    db.commit()

    verification_link = build_verification_link(raw_token)
    subject, body = build_verification_email(verification_link, language)
    try:
        email_sender = get_email_sender()
        email_sender.send(
            EmailMessage(to=user.email, subject=subject, text_body=body, attachments=[])
        )
    except (EmailSendError, HTTPException):
        # Never surfaced to the caller, matching issue_password_reset: a
        # delivery failure (including email simply not being configured in
        # this environment) must never block registration or resend from
        # completing normally. Never logs the raw token — only user.id.
        logger.warning("Verification email could not be sent to user %s", user.id)

    return raw_token


def _issue_email_verification_task(user_id: str, language: str) -> None:
    """Background-task entry point — same shape as
    _issue_password_reset_task and for the same reason: opens its own
    SessionLocal rather than reusing the request-scoped session, which
    FastAPI closes once the response is sent."""
    db = SessionLocal()
    try:
        user = db.scalar(select(User).where(User.id == user_id))
        if user is not None:
            issue_email_verification(db, user, language)
    finally:
        db.close()


@router.post("/resend-verification", response_model=ResendVerificationResponse)
def resend_verification(
    background_tasks: BackgroundTasks,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ResendVerificationResponse:
    # Authenticated via the caller's own JWT rather than an email address in
    # the request body — unlike forgot-password, there's no enumeration
    # surface to protect here at all, since the caller has already proven
    # ownership of this exact account just to reach this endpoint.
    #
    # Two independent buckets, both 3/hour: a user-only bucket (so this
    # account can't be spammed by switching IPs) and a user+IP bucket (so
    # IP-level abuse from a single source is still visible independently).
    enforce_rate_limit(
        [
            RateLimitCheck(
                scope="auth:resend_verification:user",
                identity=user_identity(current_user.id),
                rules=RESEND_VERIFICATION_RULES,
            ),
            RateLimitCheck(
                scope="auth:resend_verification:user_ip",
                identity=user_ip_identity(request, current_user.id),
                rules=RESEND_VERIFICATION_RULES,
            ),
        ]
    )

    if current_user.email_verified_at is not None:
        return ResendVerificationResponse(message=ALREADY_VERIFIED_MESSAGE)

    organizations = _user_organizations(db, current_user.id)
    language = organizations[0].organization.language if organizations else DEFAULT_LANGUAGE
    background_tasks.add_task(
        _issue_email_verification_task, current_user.id, language
    )
    return ResendVerificationResponse(message=VERIFICATION_SENT_MESSAGE)


@router.post("/verify-email", response_model=VerifyEmailResponse)
def verify_email(
    body: VerifyEmailRequest, request: Request, db: Session = Depends(get_db)
) -> VerifyEmailResponse:
    enforce_rate_limit(
        [RateLimitCheck(scope="auth:verify_email:ip", identity=ip_identity(request), rules=VERIFY_EMAIL_RULES)]
    )

    token_hash = hash_verification_token(body.token)
    now = datetime.now(timezone.utc)

    # Same shape as reset_password(): expiry and used-at folded into the
    # query itself so "token doesn't exist", "expired", and "already used"
    # are indistinguishable to the caller.
    verification_token = db.scalar(
        select(EmailVerificationToken).where(
            EmailVerificationToken.token_hash == token_hash,
            EmailVerificationToken.used_at.is_(None),
            EmailVerificationToken.expires_at > now,
        )
    )
    if verification_token is None or not tokens_match(
        body.token, verification_token.token_hash
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=VERIFY_EMAIL_ERROR_MESSAGE,
        )

    user = db.scalar(select(User).where(User.id == verification_token.user_id))
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=VERIFY_EMAIL_ERROR_MESSAGE,
        )

    user.email_verified_at = now
    verification_token.used_at = now
    db.commit()

    return VerifyEmailResponse(message=VERIFY_EMAIL_SUCCESS_MESSAGE)
