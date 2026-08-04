# Experimental, disabled-by-default WhatsApp bridge image (see
# docs/whatsapp.md). NOT part of the default `docker compose up` stack --
# see the `whatsapp` profile in ../docker-compose.yml. This container
# needs a persistent process and a real Chromium runtime (whatsapp-web.js
# drives an actual browser), so it cannot run on serverless platforms like
# Render's free web service or Vercel.
#
# Two stages, same reasoning as ../frontend/Dockerfile: the TypeScript
# build needs devDependencies (typescript itself, @types/express,
# @types/qrcode -- express and qrcode ship no types of their own). An
# earlier single-stage version of this file set NODE_ENV=production
# before `npm ci` ran -- npm's own documented behavior is to skip
# devDependencies whenever NODE_ENV=production is set at install time,
# so the build silently had no `tsc`/@types/* available and failed with
# "Could not find a declaration file for module 'express'"/'qrcode'.
# Keeping the build in its own stage, with NODE_ENV unset, makes that
# class of bug impossible to reintroduce by accident: the runtime stage
# below only ever sees a `dist/` that a real, fully-typed build already
# produced.
FROM node:20-slim AS builder
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY tsconfig.json ./
COPY src/ ./src
RUN npm run build

FROM node:20-slim AS runner

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

# node_modules is copied from the builder stage (already installed there
# against the same lockfile) rather than reinstalled -- one `npm ci`
# total, not two -- then pruned down to production-only now that the
# TypeScript build it was needed for has already succeeded.
COPY package.json package-lock.json ./
COPY --from=builder /app/node_modules ./node_modules
COPY --from=builder /app/dist ./dist
RUN npm prune --omit=dev

# UID 1001, not 1000 -- node:20-slim already ships its own built-in
# `node` user at UID/GID 1000 (confirmed via `docker run node:20-slim id
# node`), so `useradd --uid 1000` collides with it ("UID 1000 is not
# unique"). Matches ../frontend/Dockerfile's own node-base image, which
# hits this same collision and already uses 1001 for the same reason.
RUN useradd --create-home --uid 1001 bridgeuser \
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
