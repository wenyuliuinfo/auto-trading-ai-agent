import { StockSDK } from "stock-sdk";

const sdk = new StockSDK();

const CONCURRENCY = 4;

function parseRequest(raw) {
  try {
    return JSON.parse(raw);
  } catch {
    throw new Error("INVALID_STDIN_JSON");
  }
}

function normalizeBar(raw) {
  if (!raw) return null;
  const date = String(raw.date ?? raw.time ?? "");
  const open = Number(raw.open);
  const high = Number(raw.high);
  const low = Number(raw.low);
  const close = Number(raw.close);
  const volume = Number(raw.volume ?? 0);
  if (
    !date ||
    !Number.isFinite(open) ||
    !Number.isFinite(high) ||
    !Number.isFinite(low) ||
    !Number.isFinite(close)
  ) {
    return null;
  }
  return { date, open, high, low, close, volume: Number.isFinite(volume) ? volume : 0 };
}

async function fetchOne(symbol, bars, adjust) {
  try {
    const raw = await sdk.kline.us(symbol, {
      period: "daily",
      adjust: adjust === "forward" ? "qfq" : "",
    });
    const rows = Array.isArray(raw) ? raw : raw?.bars ?? raw?.data ?? [];
    const normalized = rows.map(normalizeBar).filter(Boolean);
    return { status: "ok", bars: normalized.slice(-bars) };
  } catch (error) {
    return { status: "error", code: String(error?.code ?? "SDK_ERROR") };
  }
}

async function main() {
  let raw = "";
  for await (const chunk of process.stdin) raw += chunk;
  const request = parseRequest(raw);
  if (request.version !== 1) {
    throw new Error("UNSUPPORTED_VERSION");
  }
  const symbols = request.symbols ?? [];
  const bars = Number(request.bars ?? 140);
  const adjust = request.adjust === "forward" ? "forward" : "none";

  const queue = [...symbols];
  const results = {};
  async function worker() {
    while (queue.length > 0) {
      const symbol = queue.shift();
      results[symbol] = await fetchOne(symbol, bars, adjust);
    }
  }
  await Promise.all(
    Array.from({ length: Math.min(CONCURRENCY, symbols.length) }, () => worker()),
  );
  process.stdout.write(
    JSON.stringify({
      version: 1,
      sdk_version: "2.4.5",
      results,
    }),
  );
}

main().catch((error) => {
  process.stderr.write(`${error?.message ?? error}\n`);
  process.exit(1);
});
