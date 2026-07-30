# Deployment Configuration

## 1. Start Vector DB and Relational DB Configuration
Need to run the following command to have two services that need to come up together for local dev (`pnpm dev` per AGENTS.md):
```bash
docker compose up -d
``` 

## 2. Stop Vector DB and Relational DB 
Tear down two services after the development is done:
```bash
docker compose down
```

## 3. Environment Variables
Set the following environment variables locally to form the connection with Pinecone and PostgreSQL:
```
# === Pinecone ===
PINECONE_API_KEY="your_key_here"
PINECONE_HOST_URL="http://localhost:5080"
PINECONE_INDEX_NAME="knowledge-base"

# === PostgreSQL ===
DB_HOST=localhost
DB_PORT=5432
DB_NAME="your_db_name"
DB_USER="your_user_name"
DB_PASSWORD="your_password"
DATABASE_URL="postgresql+asyncpg://your_user_name:your_password@localhost:5432/your_db_name"
```