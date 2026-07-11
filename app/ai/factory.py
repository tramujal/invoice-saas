import logging
import os

from fastapi import HTTPException, status

from app.ai.anthropic_provider import AnthropicProvider
from app.ai.base import AIProvider
from app.ai.gemini_provider import GeminiProvider
from app.ai.limits import AI_MAX_OUTPUT_TOKENS, AI_REQUEST_TIMEOUT_SECONDS
from app.security import ENVIRONMENT

logger = logging.getLogger(__name__)

# Which env var holds the API key for each supported AI_PROVIDER value.
# Each provider only ever requires its own key -- switching AI_PROVIDER
# from "anthropic" to "gemini" means setting GEMINI_API_KEY, not touching
# ANTHROPIC_API_KEY at all (and vice versa).
_PROVIDER_API_KEY_ENV_VARS = {
    "anthropic": "ANTHROPIC_API_KEY",
    "gemini": "GEMINI_API_KEY",
}

# Documented development-only fallback models -- see .env.example and
# README.md. Never used when ENVIRONMENT=production: silently assuming one
# specific model id stays valid forever is exactly what we were asked not
# to do, so production always requires AI_MODEL to be set explicitly,
# regardless of which provider is selected.
_DEV_FALLBACK_MODEL = {
    "anthropic": "claude-sonnet-5",
    "gemini": "gemini-2.5-flash",
}

# Unset AI_PROVIDER keeps behaving exactly as before this provider was
# added: Anthropic, driven by ANTHROPIC_API_KEY + AI_MODEL alone.
_DEFAULT_PROVIDER = "anthropic"


def is_ai_configured() -> bool:
    """Cheap check for whether get_ai_provider() would currently succeed --
    no provider object is constructed, no exception is raised. Used by
    callers that need to know AI availability without necessarily calling
    it this request (e.g. app/routers/insights.py deciding whether to
    advertise a "Refresh insights" action at all, even on a narration
    cache hit where get_ai_provider() is never actually called)."""
    provider_name = (os.environ.get("AI_PROVIDER") or _DEFAULT_PROVIDER).strip().lower()
    if provider_name not in _PROVIDER_API_KEY_ENV_VARS:
        return False

    api_key = os.environ.get(_PROVIDER_API_KEY_ENV_VARS[provider_name])
    model = os.environ.get("AI_MODEL")
    if not model and ENVIRONMENT != "production":
        model = _DEV_FALLBACK_MODEL[provider_name]

    return bool(api_key) and bool(model)


def get_ai_provider(*, timeout_seconds: float | None = None) -> AIProvider:
    """Resolves the configured AI provider. Called explicitly inside a
    route body (not as a FastAPI Depends parameter) — like
    get_email_sender(), so that cheaper checks (auth, org membership, email
    verification, rate limiting) run first and this is only reached, and
    only pays the cost of an env lookup, once those have already passed.

    AI is optional infrastructure, like email: missing or invalid
    configuration doesn't stop the app from booting, it just makes this
    call raise a clean 503 when actually invoked.

    `timeout_seconds` overrides AI_REQUEST_TIMEOUT_SECONDS for call sites
    with a tighter budget than the assistant chat's default 30s -- e.g.
    the dashboard insights narration call (app/insights/narration.py),
    which sits on the critical path of a page load rather than a chat the
    user is already waiting on. Every existing caller that doesn't pass
    this keeps behaving exactly as before.
    """
    provider_name = (os.environ.get("AI_PROVIDER") or _DEFAULT_PROVIDER).strip().lower()

    if provider_name not in _PROVIDER_API_KEY_ENV_VARS:
        logger.error(
            "get_ai_provider: unknown AI_PROVIDER=%r (expected one of: %s)",
            provider_name,
            ", ".join(sorted(_PROVIDER_API_KEY_ENV_VARS)),
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "ai_not_configured",
                "message": (
                    f"Unknown AI_PROVIDER '{provider_name}'. Expected one of: "
                    f"{', '.join(sorted(_PROVIDER_API_KEY_ENV_VARS))}."
                ),
            },
        )

    api_key_env_var = _PROVIDER_API_KEY_ENV_VARS[provider_name]
    api_key = os.environ.get(api_key_env_var)
    model = os.environ.get("AI_MODEL")

    if not model and ENVIRONMENT != "production":
        model = _DEV_FALLBACK_MODEL[provider_name]
        logger.warning(
            "get_ai_provider: AI_MODEL not set; using development fallback "
            "provider=%s model=%s (never used when ENVIRONMENT=production)",
            provider_name,
            model,
        )

    logger.info(
        "get_ai_provider: provider=%s api_key_present=%s model=%s environment=%s",
        provider_name,
        bool(api_key),
        model,
        ENVIRONMENT,
    )

    if not api_key or not model:
        logger.warning(
            "get_ai_provider: AI assistant NOT initialized "
            "(provider=%s api_key_present=%s model_present=%s environment=%s)",
            provider_name,
            bool(api_key),
            bool(model),
            ENVIRONMENT,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "ai_not_configured",
                "message": (
                    "The AI assistant is not configured. Set "
                    f"{api_key_env_var} and AI_MODEL to enable it."
                ),
            },
        )

    logger.info(
        "get_ai_provider: AI provider initialized successfully provider=%s model=%s",
        provider_name,
        model,
    )

    resolved_timeout = timeout_seconds if timeout_seconds is not None else AI_REQUEST_TIMEOUT_SECONDS

    if provider_name == "gemini":
        return GeminiProvider(
            api_key=api_key,
            model=model,
            max_output_tokens=AI_MAX_OUTPUT_TOKENS,
            timeout_seconds=resolved_timeout,
        )

    return AnthropicProvider(
        api_key=api_key,
        model=model,
        max_output_tokens=AI_MAX_OUTPUT_TOKENS,
        timeout_seconds=resolved_timeout,
    )
