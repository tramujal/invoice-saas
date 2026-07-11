import logging
import os

from fastapi import HTTPException, status

from app.ai.anthropic_provider import AnthropicProvider
from app.ai.base import AIProvider
from app.ai.limits import AI_MAX_OUTPUT_TOKENS, AI_REQUEST_TIMEOUT_SECONDS
from app.security import ENVIRONMENT

logger = logging.getLogger(__name__)

# Documented development-only fallback — see .env.example and README.md.
# Never used when ENVIRONMENT=production: silently assuming one specific
# model id stays valid forever is exactly what we were asked not to do, so
# production always requires AI_MODEL to be set explicitly.
_DEV_FALLBACK_MODEL = "claude-sonnet-5"


def get_ai_provider() -> AIProvider:
    """Resolves the configured AI provider. Called explicitly inside a
    route body (not as a FastAPI Depends parameter) — like
    get_email_sender(), so that cheaper checks (auth, org membership, email
    verification, rate limiting) run first and this is only reached, and
    only pays the cost of an env lookup, once those have already passed.

    AI is optional infrastructure, like email: missing configuration
    doesn't stop the app from booting, it just makes this call raise a
    clean 503 when actually invoked.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    model = os.environ.get("AI_MODEL")

    if not model and ENVIRONMENT != "production":
        model = _DEV_FALLBACK_MODEL
        logger.warning(
            "get_ai_provider: AI_MODEL not set; using development fallback "
            "model=%s (never used when ENVIRONMENT=production)",
            model,
        )

    logger.info(
        "get_ai_provider: anthropic_api_key_present=%s model=%s environment=%s",
        bool(api_key),
        model,
        ENVIRONMENT,
    )

    if not api_key or not model:
        logger.warning(
            "get_ai_provider: AI assistant NOT initialized "
            "(api_key_present=%s model_present=%s environment=%s)",
            bool(api_key),
            bool(model),
            ENVIRONMENT,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "ai_not_configured",
                "message": (
                    "The AI assistant is not configured. Set ANTHROPIC_API_KEY "
                    "and AI_MODEL to enable it."
                ),
            },
        )

    logger.info("get_ai_provider: AI provider initialized successfully (Anthropic) model=%s", model)
    return AnthropicProvider(
        api_key=api_key,
        model=model,
        max_output_tokens=AI_MAX_OUTPUT_TOKENS,
        timeout_seconds=AI_REQUEST_TIMEOUT_SECONDS,
    )
