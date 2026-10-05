# Backtest Methodology (version 1)

Audience: users, reviewers, and compliance. The Backtest section's
methodology popover summarizes this document. Final wording of the
disclosures requires compliance review.

> **Hypothetical backtest, not performance.** The results below are a
> simulation of a rules-based strategy on historical data. No money was
> invested. Simulated results have inherent limitations, are prepared with
> hindsight about which securities existed and how data was reported, and do
> not predict future results.

## 1. What is being tested

The system picks a basket of 5–10 stocks for a theme using its screening,
factor-ranking, and portfolio-construction rules. The backtest asks: **if
those rules had been applied every quarter, and the resulting basket bought
and held for three months, how would $10,000 have grown compared with a
Nasdaq index fund?**

It tests the *deterministic* part of the strategy. The live system also uses
an AI analyst for two inputs (thematic relevance and news sentiment). Those
cannot be replayed honestly on past dates because the model has knowledge of
what happened afterwards. They are replaced by two rule-based measures
(section 5). The backtest is therefore a close relative of the live strategy,
not an exact replay.

## 2. Timeline

- **Rebalance dates:** first trading day of January, April, July, October.
- **Signal date:** the last trading day before the rebalance date. Only
  information available on or before that date is used.
- **Trade date:** the rebalance date, at the closing price.
- **Hold:** three months, until the next rebalance.

Example: for the 2024-01-02 rebalance, signals use prices through 2023-12-29,
financial statements filed on or before 2023-12-29, and ETF holdings dated on
or before 2023-12-29. Trades execute at the 2024-01-02 close and are held until
the 2024-04-01 close.

Two modes:

| Mode | Period | Rebalances |
|---|---|---|
| Trailing | The four most recent completed quarters before the run date (plus the current quarter if at least 10 trading days old) | 4 (or 5) |
| Full | 2021-01-04 to 2025-12-31 | 20 |

The theme tested is the theme of the run (its sub-exposures, screens, and
weighting rules as saved with the run).

## 3. Universe for each rebalance

1. Take the ETFs mapped to the theme's sub-exposures
   (`config/sub_exposure_etf_map.yaml`).
2. For each ETF, use its most recent holdings snapshot dated on or before the
   signal date (and no older than the configured maximum age). ETFs with no
   valid snapshot at that date, for example funds not yet launched, are
   ignored for that rebalance.
3. Combine the stocks held, remove duplicates, and cap the list using the same
   function the live system uses (at most 100 names, with a floor per
   sub-exposure, preferring larger market caps measured on the signal date).

The live system also adds stocks whose industry classification matches a
keyword. That list cannot be reconstructed for past dates, so the backtest
universe contains ETF holdings only.

## 4. Scoring and basket construction

The backtest calls the same code the live system uses:

1. Raw factors (valuation, growth, quality, momentum, liquidity and volatility
   where enabled, plus size, beta and trading volume) are computed from data as
   it was on the signal date.
2. Each factor is converted to a z-score across the candidate universe, the
   factors are combined with the weights saved with the run, and the stocks
   are ranked.
3. The portfolio rules select up to 10 names after applying minimum market cap
   and trading-volume screens, a limit on names per sub-industry, and equal or
   score-based weights as configured for the theme.

If fewer than five names qualify, the universe is widened as in the live
system (up to the configured number of attempts). If no name qualifies, the
portfolio stays in cash for that quarter; if fewer than five qualify, those
names are bought. These cases are flagged.

## 5. Substituted signals

| Live system | Backtest |
|---|---|
| **Thematic relevance** (1–5, written by the AI analyst) | **ETF breadth:** the number of the theme's mapped ETFs that hold the stock on the signal date |
| **Sentiment** (bearish/neutral/bullish from AI-read news) | **Money-flow ratio** over the last 126 trading days |

Money-flow ratio, from daily bars:

```
position_t = ((close - low) - (high - close)) / (high - low)     # 0 if high == low
flow_t     = position_t * volume_t
ratio      = sum(flow_t) / sum(volume_t)                          # between -1 and +1
```

A close near the day's high counts the volume as buying pressure; near the
low, as selling pressure. This is an approximation of "buying volume minus
selling volume": exchanges do not publish which side initiated each trade in
daily data, and even trade-level services infer it. Dividing by total volume
keeps large companies from dominating.

Because the substituted signals differ from the live ones, backtest rankings
and live rankings will not match exactly.

## 6. Execution, costs, and accounting

- Starting capital $10,000; fractional shares allowed (configurable).
- On each rebalance the portfolio trades only the difference between current
  and target holdings. Each trade pays **10 basis points of its value** to
  represent commissions, spread, and slippage (configurable).
- Prices for profit and loss are total-return-adjusted closes, so dividends
  are included and splits do not distort results.
- Cash earns no interest.
- Taxes, financing costs, position limits, and market impact are not modeled.
- If a price is missing on a trade date, that purchase is skipped and the
  money stays in cash. If a holding stops trading during a hold (for example,
  a delisting), it is carried at its last price and then converted to cash.

## 7. Benchmarks

- **Primary: QQQ**, an exchange-traded fund tracking the Nasdaq-100, total
  return. It is a practical index-fund proxy; it is not the Nasdaq Composite.
- **Optional:** SPY; an equal-weighted mix of the theme's ETFs that existed at
  each date; an equal-weighted mix of the candidate universe at each
  rebalance.

Every benchmark starts on the same date with the same $10,000 and the same
one-time entry cost as the strategy. Fund expense ratios are already reflected
in fund prices.

The equal-weight baselines show whether the ranking added anything beyond
owning the theme.

## 8. Metrics

| Metric | Definition |
|---|---|
| Total return | Final value / initial − 1, net of costs |
| CAGR | Annualized return; shown only for periods of at least one year |
| Volatility | Standard deviation of daily returns × √252 |
| Sharpe | Mean daily excess return / standard deviation × √252 (risk-free rate from configuration, default 0) |
| Max drawdown | Largest peak-to-trough fall of portfolio value |
| Beta, alpha | Daily regression of strategy returns on the primary benchmark; alpha annualized |
| Tracking error / information ratio | Volatility of daily excess returns; mean excess / tracking error |
| Quarterly win rate | Share of holding periods where the strategy beat the benchmark |
| Turnover | Annualized value bought / average portfolio value |
| Costs paid | Sum of all trading costs |
| Contribution | Each stock's profit or loss divided by initial capital; costs shown separately; contributions plus costs equal total profit |

## 9. Point-in-time data rules

| Data | Rule |
|---|---|
| Prices | Only dates on or before the signal date for scoring; adjusted for splits for returns and trading volume; unadjusted close for price-to-earnings so it matches earnings as reported at the time |
| Financial statements | Only filings made on or before the signal date; trailing-twelve-month figures use the latest four filed quarters |
| Market capitalization | The value on the signal date |
| ETF holdings | Latest snapshot on or before the signal date within the maximum age |
| Industry classification | Current classification (a small look-ahead; disclosed) |

## 10. Known limitations

1. **Survivorship and membership bias.** ETF holdings reflect what funds held
   then, but data sources may not include stocks that were later delisted. A
   count of candidates without price history is reported where detectable.
2. **ETF coverage over time.** Some mapped ETFs launched after 2021. Early
   periods may have thin universes, trigger "hold cash" quarters, or lean on a
   few funds.
3. **Replaced signals.** Thematic and sentiment scores are proxies; results
   say little about the live AI-assisted inputs.
4. **Proxy for buy/sell volume.** Daily-bar estimate only.
5. **Small samples.** Four quarters (or 20) from one theme in one market
   regime cannot show skill. Treat results as diagnostics, not evidence of
   future returns. No significance tests are reported.
6. **Concentration.** Baskets of 5–10 stocks produce large swings from single
   names.
7. **Execution realism.** Closing-price fills at a flat cost do not capture
   market impact, partial fills, or capacity limits.
8. **Data quality.** Vendor data can contain errors or revisions. Possible
   unadjusted splits are flagged on charts.
9. **Parameter choices.** Weights, screens, costs, and schedules are set
   before running and are not tuned to the results.
10. **No taxes or financing.**

## 11. Reproducibility and versioning

Every result stores: the configuration used and its hash, this methodology
version, the code version, and a fingerprint of the data used. Rerunning
creates a new result. Changing any rule in this document increments the
methodology version, and older results show a "computed with an earlier
methodology" notice.

## 12. How to read the results

- Compare the strategy with **both** the Nasdaq fund and the equal-weight
  baselines.
- Look at drawdown and the quarterly win rate, not only total return.
- Check the flag chips (short window, survivorship risk, replaced signals).
- Do not extrapolate; the strategy's rules were designed with knowledge of
  recent market behavior.

## 13. Disclosure text (draft for compliance review)

"This analysis is a hypothetical backtest of a rules-based strategy. It does
not represent actual trading, and no client assets were managed using it.
Hypothetical results are prepared with the benefit of hindsight, do not
reflect the impact of market conditions on actual decisions, and may differ
materially from actual results. Past performance, simulated or actual, does
not guarantee future results. This material is for research purposes only and
does not constitute investment advice or a recommendation to buy or sell any
security."
