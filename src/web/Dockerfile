FROM node:20-alpine AS builder
WORKDIR /web

# Pin pnpm version (CONVENTIONS.md §3.5 — pin exact versions)
RUN npm install -g pnpm@9.15.0

# Copy package files first for layer caching
COPY package.json pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

# Copy source and build (requires next.config.* to set output: "standalone")
COPY . .
RUN pnpm build

# Production stage
FROM node:20-alpine AS runner
WORKDIR /web

ENV NODE_ENV=production
ENV HOSTNAME="0.0.0.0"
ENV PORT=3000

# Run as non-root (node:20-alpine ships a built-in `node` user)
RUN chown -R node:node /web
USER node

# Standalone output does NOT include public/ or .next/static automatically —
# both must be copied by hand.
COPY --from=builder --chown=node:node /web/public ./public
COPY --from=builder --chown=node:node /web/.next/standalone ./
COPY --from=builder --chown=node:node /web/.next/static ./.next/static

EXPOSE 3000

HEALTHCHECK --interval=10s --timeout=5s --retries=5 --start-period=10s \
  CMD wget -qO- http://localhost:3000/ || exit 1

CMD ["node", "server.js"]