FROM node:20-alpine AS builder
WORKDIR /workspace

# Pin pnpm version (CONVENTIONS.md §3.5 — pin exact versions)
RUN npm install -g pnpm@9.15.0

# Workspace manifests first so dependency installation can be cached
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
COPY src/web/package.json ./src/web/package.json
RUN pnpm install --frozen-lockfile

# Copy source and build (requires next.config.* to set output: "standalone")
COPY src/web ./src/web
RUN pnpm --dir src/web build

# Production stage
FROM node:20-alpine AS runner
WORKDIR /workspace

ENV NODE_ENV=production
ENV HOSTNAME="0.0.0.0"
ENV PORT=3000

# Run as non-root (node:20-alpine ships a built-in `node` user)
RUN chown -R node:node /workspace
USER node

# Standalone output does NOT include public/ or .next/static automatically —
# both must be copied by hand. Next traces from the monorepo root, so the
# standalone server lives under src/web/.
COPY --from=builder --chown=node:node /workspace/src/web/.next/standalone ./
COPY --from=builder --chown=node:node /workspace/src/web/.next/static ./src/web/.next/static
COPY --from=builder --chown=node:node /workspace/src/web/public ./src/web/public

EXPOSE 3000

HEALTHCHECK --interval=10s --timeout=5s --retries=5 --start-period=10s \
  CMD wget -qO- http://localhost:3000/ || exit 1

CMD ["node", "src/web/server.js"]
