FROM node:20-slim AS kline-deps
WORKDIR /tools/stock-sdk-kline
COPY tools/stock-sdk-kline/package.json ./
RUN npm install --omit=dev
COPY tools/stock-sdk-kline/fetch_klines.mjs ./

FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY src/app/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY src/app/ .
COPY config/ ./config/
COPY --from=kline-deps /tools/stock-sdk-kline ./tools/stock-sdk-kline

# Create non-root user
RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
