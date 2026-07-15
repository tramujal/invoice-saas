# Frontend image for local Docker Compose use (see ../docker-compose.yml).
# Multi-stage, relying on next.config.mjs's `output: "standalone"` (see
# comment there) so the final runtime stage never installs node_modules
# itself -- it just runs the pruned, generated server.js.

FROM node:20-slim AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

FROM node:20-slim AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
# NEXT_PUBLIC_* vars are inlined into the client bundle at build time, so
# this must be set before `next build` runs, and must be the URL the
# browser can actually reach -- never a Docker-internal service hostname.
ARG NEXT_PUBLIC_API_URL
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL
# next build type-checks and lints by default (no ignoreBuildErrors /
# ignoreDuringBuilds set in next.config.mjs) -- this fails the same way a
# local `npm run build` would on a real error, which is intended.
RUN npm run build

FROM node:20-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production
# The generated server.js defaults HOSTNAME to "localhost", which binds
# only the container's loopback interface -- Docker's port mapping cannot
# reach it, and an in-container healthcheck would still falsely pass since
# it also hits localhost. Must be 0.0.0.0.
ENV HOSTNAME="0.0.0.0"
ENV PORT=3000

RUN addgroup --system --gid 1001 nodejs \
    && adduser --system --uid 1001 nextjs

# .next/standalone does not include .next/static -- must be copied
# separately. No public/ directory exists in this project.
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static

USER nextjs

EXPOSE 3000

HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=3 \
    CMD node -e "require('http').get('http://localhost:3000/', r => process.exit(r.statusCode < 500 ? 0 : 1)).on('error', () => process.exit(1))"

CMD ["node", "server.js"]
