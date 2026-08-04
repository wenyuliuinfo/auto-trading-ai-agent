# Deployment Configuration

## 1. Start the Local Stack

Run from the repository root. `docker compose` reads
`infra/docker-compose.yml` and uses the root `.env` for variable
substitution:

```bash
docker compose --env-file .env -f infra/docker-compose.yml up -d
```

This starts the infrastructure services: Postgres (domain DB + LangGraph
checkpoints), Redis (Celery broker/cache), Pinecone local (vector store),
and Langfuse with its own dedicated Postgres. The `fastapi`,
`celery-worker`, and `nextjs` services are commented out in the compose
file until the app code exists — for local dev the backend and frontend
run via `pnpm dev` per AGENTS.md.

## 2. Stop the Local Stack

Tear down the services after development is done:

```bash
docker compose --env-file .env -f infra/docker-compose.yml down
```

## 3. Environment Variables

Copy `.env.example` at the repository root to `.env` and fill in real
values. `.env.example` is the canonical list; the main groups are:

```
# === Domain Postgres ===
POSTGRES_DB_HOST=localhost
POSTGRES_DB_PORT=5432
POSTGRES_USER="your_user_name"
POSTGRES_PASSWORD="your_password"
POSTGRES_DB="your_db_name"
POSTGRES_DATABASE_URL="postgresql+asyncpg://your_user_name:your_password@localhost:5432/your_db_name"

# === Backend ===
API_URL="http://localhost:8000"

# === Langfuse (self-hosted tracing) ===
LANGFUSE_DB_PASSWORD="change_me"
LANGFUSE_NEXTAUTH_SECRET="change_me_random_string"
LANGFUSE_SALT="change_me_random_string"

# === LLM Providers ===
DEEPSEEK_API_KEY="your_key_here"
DEEPSEEK_BASE_URL="https://api.deepseek.com/v1"

# === Vector store ===
PINECONE_API_KEY="your_key_here"
PINECONE_HOST_URL="http://localhost:5080"
PINECONE_INDEX_NAME="vector_store"

# === Free-tier data vendors ===
FMP_API_KEY="your_key_here"
FINNHUB_API_KEY="your_key_here"
SERP_API_KEY="your_key_here"
```
