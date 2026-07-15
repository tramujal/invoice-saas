# Backend image for local Docker Compose use (see docker-compose.yml).
# Single-stage: every dependency in requirements.txt ships prebuilt wheels
# (psycopg[binary], bcrypt, reportlab, uvicorn[standard]) -- no compiler is
# ever needed, so a multi-stage build wouldn't shrink the image, only add
# complexity. This does not replace or alter the existing Render deployment
# (see render.yaml), which does not use this file.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Installed as an early, cache-friendly layer, before application code, so
# a code-only change doesn't invalidate the dependency-install layer.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app

RUN useradd --create-home --uid 1000 appuser \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# No custom entrypoint/migration step -- app/main.py's FastAPI lifespan
# hook already calls init_db() (idempotent, safe on every startup; see
# app/schema_migrations.py) before requests are served. Mirrors exactly how
# the existing Render deployment runs this app (render.yaml's startCommand
# also just execs uvicorn directly, no separate migration step).
HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=3 \
    CMD python3 -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health', timeout=2)" || exit 1

# --forwarded-allow-ips= (empty) disables uvicorn's own X-Forwarded-For
# trust, matching render.yaml and .claude/launch.json exactly -- only
# app.rate_limit's TRUSTED_PROXY_HOPS env var governs client-IP resolution.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--forwarded-allow-ips="]
