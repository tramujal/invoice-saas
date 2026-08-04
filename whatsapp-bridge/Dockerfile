# Experimental, disabled-by-default WhatsApp bridge image (see
# docs/whatsapp.md). NOT part of the default `docker compose up` stack --
# see the `whatsapp` profile in ../docker-compose.yml. This container
# needs a persistent process and a real Chromium runtime (whatsapp-web.js
# drives an actual browser), so it cannot run on serverless platforms like
# Render's free web service or Vercel.
FROM node:20-slim

ENV NODE_ENV=production \
    PUPPETEER_SKIP_CHROMIUM_DOWNLOAD=true \
    PUPPETEER_EXECUTABLE_PATH=/usr/bin/chromium

WORKDIR /app

# Debian's own `chromium` package (not Puppeteer's bundled download --
# PUPPETEER_SKIP_CHROMIUM_DOWNLOAD above skips that) pulls in the correct
# shared-library dependencies for this exact base image automatically,
# rather than hand-maintaining Puppeteer's often-stale "recommended apt
# packages" list.
RUN apt-get update \
    && apt-get install -y --no-install-recommends chromium \
    && rm -rf /var/lib/apt/lists/*

COPY package.json package-lock.json ./
RUN npm ci

COPY tsconfig.json ./
COPY src/ ./src
RUN npm run build \
    && npm prune --omit=dev

RUN useradd --create-home --uid 1000 bridgeuser \
    && mkdir -p /app/.wwebjs_auth \
    && chown -R bridgeuser:bridgeuser /app
USER bridgeuser

EXPOSE 3100

# Unauthenticated by design (see src/health/routes.ts) -- purely a
# liveness probe, never exposes connection/session details.
HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=3 \
    CMD node -e "require('http').get('http://localhost:' + (process.env.PORT || 3100) + '/health', r => process.exit(r.statusCode === 200 ? 0 : 1)).on('error', () => process.exit(1))"

# WHATSAPP_SESSION_PATH should point at a mounted volume (see
# docker-compose.yml's whatsapp-bridge service) -- session data written
# outside one is lost on every container recreation, and is equivalent to
# full WhatsApp account access if it ever leaks (see docs/whatsapp.md).
CMD ["node", "dist/index.js"]
