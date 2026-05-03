# syntax=docker/dockerfile:1.7
FROM node:22-alpine AS deps
WORKDIR /app
ENV NEXT_TELEMETRY_DISABLED=1
# Cache the npm tarball cache across builds so even a lockfile bump doesn't
# re-download from the registry.
COPY package.json package-lock.json ./
RUN --mount=type=cache,target=/root/.npm \
    npm ci --no-audit --no-fund

FROM node:22-alpine AS builder
WORKDIR /app
ENV NEXT_TELEMETRY_DISABLED=1
ENV NODE_ENV=production
COPY --from=deps /app/node_modules ./node_modules
COPY . .
# Cache Next's incremental build output (.next/cache) across rebuilds. This
# is the single biggest accelerant for source-only rebuilds: Next reuses
# webpack's module graph + minified chunks for unchanged files, so a tiny
# JSX edit takes 10-20s instead of 2 minutes.
RUN --mount=type=cache,target=/app/.next/cache \
    npm run build

FROM node:22-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1
COPY --from=builder /app/public ./public
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static
EXPOSE 3000
CMD ["node", "server.js"]
