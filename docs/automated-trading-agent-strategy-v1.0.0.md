# Product Strategy: Automated Trading Agent
### Theme-Based Category Trading for Financial Advisors

> Generated: 2026-07-23 | Product Strategy Session

---

## Phase 1: Positioning & Market Context

### Positioning Statement

> For **financial advisors at large wirehouse/broker-dealer teams** who need to respond to **client-driven theme requests** (AI, clean energy, defense) with specific, timely trades, the **Automated Trading Agent** is a **theme-to-execution platform** that translates a theme into compliant, executable trade baskets across client portfolios in minutes — unlike fragmented research tools and OMS platforms that leave advisors stuck between hours of manual screening and missed market windows.

### Target Persona

**Financial Advisor at a Large Broker-Dealer**
- Manages 50-150 client portfolios with varying mandates and risk profiles
- Clients increasingly ask for thematic exposure but can't name specific securities
- Operates under strict firm compliance: approved lists, suitability, concentration limits
- Spends 2-4 hours per theme researching across Morningstar/YCharts/Bloomberg
- Then manually enters trades account-by-account in the OMS
- **Result:** missed market windows, anxious clients, erosion of trust

### Core Use Case
Theme-based investing — client says "AI" or "clean energy," agent auto-selects the right securities and prepares for compliant execution.

### Double Pain Point
1. **Security selection paralysis** — too many ETFs/stocks per theme, hours wasted screening
2. **Execution timing** — theme opportunities are time-sensitive, but manual execution misses the window

These compound each other: time spent researching eats into the execution window.

### Differentiation
1. **Proprietary AI theme-to-security classification** — NLP engine that maps themes to securities better than generic screeners
2. **Compliance-first design** — pre-trade compliance checks baked inline, not a separate gate

### Competitive Landscape
Partial solutions exist — research tools (Morningstar, YCharts) and OMS platforms handle pieces, but nothing connects theme → securities → compliance → execution end-to-end.

### GTM Motion
Bottom-up advisor adoption → prove value → compliance formalizes → firm-wide rollout.

### North Star Metrics (Year 1)
- **Active advisor seats** using the product weekly
- **AUM influenced** through theme-based trades executed by the agent

---

## Phase 2: Problem Statement

> Financial advisors at large broker-dealers need a way to translate client trend requests into compliant, executable trade baskets across portfolios in hours instead of days — because the gap between what clients *ask for* (trends) and what advisors can *deliver* (specific, timely trades) causes missed market moves and erodes client confidence.

### Problem Framing Narrative

**I am:** A financial advisor at a large wirehouse / broker-dealer team
- Managing 50-150 client portfolios
- Clients ask for exposure to trends (AI, clean energy, defense) without naming specific securities
- Operating under strict compliance: approved lists, suitability, concentration limits

**Trying to:** Turn vague client trend requests into specific, compliant, executed trades — fast enough to capture the market move the client is chasing

**But:**
- Clients bring themes, not tickers — advisor must first interpret the trend, then research which securities represent it
- Research sprawls across disconnected tools (Morningstar, YCharts, Bloomberg) — hours per theme
- After selection, trades must clear compliance and be entered individually into OMS account-by-account
- By the time this completes, the market has moved — the client's "trend" is yesterday's news

**Because:** There's a double translation gap — (1) from client trend language to specific securities, and (2) from selected securities to compliant, bulk execution. No tool bridges either gap end-to-end.

**Which makes me feel:** Stuck between an eager client and a slow process — overwhelmed by research, anxious about losing trust when the window closes.

### Customer Journey Pain Points

| Stage | Pain Level | Core Friction |
|---|---|---|
| Theme Request | Medium | Client brings trend, not ticker — advisor must interpret |
| **Research** | 🔴 **High** | Hours across fragmented tools, no clear ranking |
| Compliance | Medium | Separate gate — anxiety about rejection |
| **Execution** | 🔴 **High** | Account-by-account manual entry, slow, error-prone |
| Post-Trade | Low-Med | Uncertainty — did I pick the right securities? |

---

## Phase 3: Solution Exploration

### Opportunity Solution Tree

```
Problem: Translate client trends → compliant, executable trade baskets, fast

├── O1: AI Theme Classifier
│   └── NLP engine that maps a theme keyword to a ranked basket of 8-12 securities
│       with confidence scores and rationale
│
├── O2: Real-time Compliance Overlay
│   └── Inline compliance flags per security (green/yellow/red) surfaced
│       directly in the basket view — no separate portal
│
├── O3: Smart Allocation Rules
│   └── Per-account distribution logic (equal weight, risk-adjusted, tax-aware)
│       for bulk execution across client portfolios
│
└── O4: Advisor-in-the-loop UX
    └── Full review/edit/approve workflow before execution — advisor has
        complete control and transparency
```

### POC Experiment: Theme Classifier Validation

| Element | Plan |
|---|---|
| **Format** | Side-by-side comparison sessions (30 min per advisor) |
| **Sample** | 10-15 advisors across 2-3 wirehouse teams |
| **Setup** | Give advisors a theme prompt. Time their manual basket build (current tools). Then show AI-generated basket — time their review. |
| **Primary Metric** | ≥80% overlap between advisor picks and AI picks |
| **Secondary** | Time-to-basket ≤5 min vs. 2-4 hrs manual |
| **Trust Gauge** | "Would you trade this basket?" ≥80% yes |
| **Timeline** | 2 weeks: recruit → run sessions → analyze |

---

## Phase 4: Prioritization & Roadmap

### Framework: Value/Effort Matrix (2x2)

Pre-launch with no usage data → RICE ruled out. Value/Effort chosen for visual resource allocation.

### Epic Scoring

| # | Epic | Value | Effort | Quadrant |
|---|---|---|---|---|
| 1 | AI Theme Classifier | 🔴 High | 🔴 High | Strategic Bet |
| 2 | Real-time Compliance Overlay | 🔴 High | 🟡 Med | Quick Win ⚡ |
| 3 | Smart Allocation Rules | 🟡 Med-High | 🟡 Med | Invest |
| 4 | Advisor-in-the-loop UX | 🟡 Med | 🟢 Low-Med | Fill-in |

### Roadmap

```
            Team A (5-7 eng)          Team B (4-5 eng)
Q3-Q4  ┌──────────────────┐       ┌──────────────────────┐
       │ AI Theme         │       │ Real-time             │
       │ Classifier       │       │ Compliance Overlay    │
       │ [Strategic Bet]  │       │ [Quick Win]           │
       └────────┬─────────┘       └───────────┬───────────┘
                │                             │
                └──────────────┬──────────────┘
                               │  ←── MVP: Theme → Securities → Compliance
Q1-Q2                    ┌─────┴──────┐
                         │ Smart      │
                         │ Allocation │
                         │ [Invest]   │
                         └─────┬──────┘
                               │
Q2-Q3                    ┌─────┴──────┐
                         │ Advisor    │
                         │ Review UX  │
                         │ [Fill-in]  │
                         └────────────┘
```

**MVP Gate:** Theme classifier POC with ≥80% basket overlap threshold before full build-out.

---

## Phase 5: Stakeholder Alignment

*This document serves as the stakeholder presentation artifact. Present in 60-min session covering: positioning, problem, solution tree, roadmap, and next steps.*

---

## Phase 6: Execution Planning

### Epic 1: AI Theme Classifier — User Stories

**US 1.1 — Theme Search & Basket Generation**
- **As a** financial advisor
- **I want to** type a theme and receive a ranked security basket
- **so that** I skip hours of manual screening
- **Acceptance:** Type "AI infrastructure" → 8-12 securities with confidence scores within 60 seconds

**US 1.2 — Basket Rationale & Transparency**
- **As a** financial advisor
- **I want to** see *why* each security was included
- **so that** I can confidently explain picks to clients and compliance
- **Acceptance:** Click a security → see NLP rationale with source citations

**US 1.3 — Basket Customization**
- **As a** financial advisor
- **I want to** add/remove/re-weight securities in the AI basket
- **so that** I can incorporate my own market knowledge
- **Acceptance:** Remove a security → remaining auto-rebalance to 100%

### Epic 2: Real-time Compliance Overlay — User Stories

**US 2.1 — Inline Compliance Flags**
- **As a** financial advisor
- **I want to** see compliance status per security in the basket
- **so that** I know immediately what passes firm rules
- **Acceptance:** Green/yellow/red badges per security, filterable

**US 2.2 — Compliance Detail Drill-down**
- **As a** financial advisor
- **I want to** click a flag and see exactly which rule triggered it
- **so that** I can decide to override or replace without calling compliance
- **Acceptance:** Detail panel with rule name, threshold, last review date, contact info

**US 2.3 — Basket-Level Compliance Summary**
- **As a** financial advisor
- **I want to** see a one-screen compliance posture for the whole basket
- **so that** I know at a glance if it's trade-ready
- **Acceptance:** "8/10 pass. 1 warning. 1 blocked." with auto-fix suggestions

### Sprint Plan (2-Week Sprints)

| Sprint | Team A (Classifier) | Team B (Compliance) | Integration Goal |
|---|---|---|---|
| **Sprint 1** | US 1.1: Theme search + basket MVP | US 2.1: Inline flags (green only) | Classifier API → UI skeleton + flags |
| **Sprint 2** | US 1.2: Rationale display | US 2.2: Detail drill-down | Click security → rationale + compliance |
| **Sprint 3** | US 1.3: Basket customization | US 2.3: Compliance summary | Full basket: customize + compliance posture |
| **Sprint 4** | POC feedback iteration | POC prep | **POC ready** — 10-15 advisors test end-to-end |

---

## Appendix: Quick Reference

| Artifact | Summary |
|---|---|
| **Target User** | Financial advisors at large wirehouse/broker-dealer teams |
| **Use Case** | Theme-based investing — client says "AI," agent picks securities |
| **Problem** | Double translation gap: trend→securities→compliant execution, all manual |
| **Differentiation** | Proprietary AI classification + compliance-first design |
| **GTM** | Bottom-up advisor adoption → land-and-expand inside firms |
| **Competition** | Fragmented tools (Morningstar, OMS) — no end-to-end solution exists |
| **v1 Scope** | Theme Classifier + Compliance Overlay (Q3-Q4, 2 teams parallel) |
| **North Star** | Active advisor seats + AUM influenced |
