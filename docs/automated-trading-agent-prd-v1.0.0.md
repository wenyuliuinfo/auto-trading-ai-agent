# Automated Trading Agent — PRD
### Theme-Based Category Trading for Financial Advisors

| Meta | Detail |
|---|---|
| **Status** | Draft v1.0 |
| **Author** | Product Management |
| **Date** | 2026-07-23 |
| **Target Release** | Q4 2026 (MVP: Theme Classifier + Compliance Overlay) |
| **Stakeholders** | Product, Engineering, Compliance/Legal, Executive Sponsor |

---

## 1. Executive Summary

We are building an **automated trading agent** for financial advisors at large wirehouse and broker-dealer teams that translates client theme requests (e.g., "I want AI exposure") into compliant, executable trade baskets across client portfolios in minutes — replacing a manual process that today takes hours to days across fragmented research tools and disconnected OMS platforms. This will generate revenue through seat licenses and AUM-based fees, while giving the broker-dealer a differentiated technology offering to win new advisor teams.

---

## 2. Problem Statement

### Who has this problem?

Financial advisors at large wirehouse / broker-dealer teams managing 50-150 client portfolios. Their clients increasingly ask for thematic exposure — "AI," "clean energy," "defense" — but cannot name specific securities or ETFs.

### What is the problem?

There is a **double translation gap**: (1) from a client's trend language to specific, defensible securities, and (2) from selected securities to compliant, bulk execution across accounts. Advisors spend 2-4 hours per theme manually screening across Morningstar, YCharts, and Bloomberg, then enter trades one account at a time in the OMS. By the time this completes, the market opportunity has often moved.

### Why is it painful?

- **Advisor impact:** Overwhelmed by research burden; anxious about missing client opportunities and eroding trust when execution windows close
- **Client impact:** Frustrated by slow response times; the "trend" they wanted exposure to is yesterday's news
- **Business impact:** Advisors lose confidence in their firm's tools; disengaged advisors are a retention and recruitment risk

### Evidence

- 🔵 **Open Question:** Formal discovery interviews not yet conducted. Customer quotes, support ticket data, and time-motion studies are needed.
- 🔶 **Assumption:** The 2-4 hour research window and account-by-account execution friction are based on industry patterns and domain expertise. Validation through advisor shadowing is a POC deliverable.

### Customer Journey — Pain Points

| Stage | Pain Level | Core Friction |
|---|---|---|
| Theme Request | Medium | Client brings trend, not ticker — advisor must interpret |
| **Research** | 🔴 **High** | Hours across fragmented tools, no clear ranking |
| Compliance | Medium | Separate gate — anxiety about rejection |
| **Execution** | 🔴 **High** | Account-by-account manual entry, slow, error-prone |
| Post-Trade | Low-Med | Uncertainty — did I pick the right securities? |

---

## 3. Target Users & Personas

### Primary Persona: Institutional Advisor at a Large Broker-Dealer

| Attribute | Detail |
|---|---|
| **Role** | Financial advisor on a team of 5-20 within a wirehouse / large broker-dealer |
| **Portfolio load** | 50-150 client portfolios with varying mandates and risk profiles |
| **Client dynamic** | Clients increasingly request thematic exposure; expect fast, informed responses |
| **Tech environment** | Uses Morningstar, YCharts, Bloomberg for research; firm OMS for trade entry; separate compliance portal |
| **Compliance burden** | Every trade must pass firm-level approved list, suitability, and concentration checks |
| **Goals** | Respond to client theme requests within 1 business day; maintain trust through transparent, well-researched recommendations; grow AUM through differentiated service |
| **Pain points** | Security selection paralysis across too many options; manual trade entry per account; anxiety about compliance rejection; missed market windows |
| **Current behavior** | Manual screen → spreadsheet → compliance check → OMS entry per account → follow up with client days later |

### Secondary Persona: Investment Committee Member

- **Role:** Senior portfolio strategist setting thematic allocations firm-wide
- **Need:** Push a theme basket (e.g., "overweight energy transition") to all advisor desks and have it executed consistently and compliantly
- **Differs from primary:** Top-down vs. bottom-up; cares about consistency and audit trail more than speed

### Jobs-to-be-Done

- **When** a client asks for exposure to a theme, **I want to** translate that theme into a ranked, defensible security basket in minutes, **so I can** respond while the opportunity is still relevant.
- **When** I have a security basket, **I want to** know immediately which securities pass compliance, **so I can** avoid wasted research on picks that will be rejected.
- **When** a basket is ready, **I want to** execute it across all relevant client accounts in one action, **so I can** avoid hours of repetitive manual trade entry.

---

## 4. Strategic Context

### Business Goals

This initiative supports two strategic objectives:

1. **Revenue Growth:** Open a new revenue line through per-seat advisor licenses and/or AUM-based transaction fees on theme-basket trades. This is net-new revenue, not cannibalizing existing advisory fees.
2. **Client Acquisition (Broker-Dealer):** Offer a differentiated technology capability that helps the broker-dealer recruit and retain top advisor teams who expect modern, AI-augmented tools.

### Why Now?

- 🔵 **Open Question:** Formal competitive urgency assessment needed. Preliminary hypothesis: Partial solutions exist (research tools, OMS platforms) but no end-to-end competitor has emerged. The window to establish category leadership is open but narrowing as AI capabilities become commoditized.
- Market trends in thematic investing (ESG, AI, energy transition, defense) are accelerating client demand. Advisors who can't efficiently respond to these requests risk losing relevance — and their firms risk losing those advisors to platforms that can.

### Competitive Landscape

| Category | Players | Gap |
|---|---|---|
| Research / Screening | Morningstar, YCharts, Bloomberg, FactSet | Strong on data, zero on execution |
| OMS / Execution | Charles River, Bloomberg AIM, Aladdin | Strong on execution, zero on theme intelligence |
| Thematic ETF Issuers | BlackRock, ARK, Global X | Curated themes but no advisor workflow |
| **End-to-End Theme-to-Execution** | **No direct competitor identified** | **Our white space** |

🔶 **Assumption:** No direct end-to-end competitor exists. Needs validation through competitive analysis.

---

## 5. Solution Overview

### High-Level Description

The Automated Trading Agent is a web-based platform that sits between the advisor's research workflow and the firm's OMS. It provides:

1. **AI Theme Classifier:** The advisor types a theme keyword ("AI infrastructure," "clean energy transition") and receives a ranked basket of 8-12 securities (stocks and ETFs) with confidence scores and inclusion rationale — in under 60 seconds.

2. **Real-time Compliance Overlay:** Every security in the basket shows a green/yellow/red compliance badge inline — based on the firm's approved list, concentration limits, and suitability rules — so the advisor knows immediately what's trade-ready.

3. **Smart Allocation Rules (v2):** Per-account distribution logic allocates the basket across client portfolios based on mandate, risk profile, and tax considerations.

4. **Advisor-in-the-loop UX (v2):** Before execution, the advisor reviews the full basket, tweaks allocations, removes/adds securities, and approves with full transparency.

### v1 MVP Scope (Q4 2026)

The advisor types a theme → receives a ranked, rationale-backed security basket → sees inline compliance flags per security → customizes the basket → reviews a basket-level compliance summary.

**Flow:**
```
[Theme Input] → [AI Classifier ranks securities] → [Compliance overlays appear]
    → [Advisor customizes basket] → [Basket compliance summary] → [Ready for execution handoff]
```

### Key Non-Functional Requirements

- 🔶 **Assumption:** Sub-60-second basket generation. Validated during POC.
- **Compliance rules engine** must support configurable firm-level rules (no hard-coded rules per firm).
- **Audit trail:** Every basket generation, customization, and compliance check must be logged for regulatory review.
- **SSO / enterprise auth:** Must integrate with the firm's identity provider (Okta, Azure AD, etc.).

---

## 6. Success Metrics

### Primary Metric

**Advisor adoption — active weekly seats**
- **Current:** 0 (pre-launch)
- **Target:** 50 active advisor seats within 6 months post-launch (Q2 2027)
- **Measurement:** Unique advisors who generate at least one theme basket per week

### Secondary Metrics

| Metric | Current | Target | Timeline |
|---|---|---|---|
| AUM influenced through platform | 0 | $500M in executed/recommended baskets | 12 months post-launch |
| Time-to-basket | 2-4 hours (manual) | ≤15 minutes (theme input → compliance-cleared basket) | At launch |
| Compliance first-pass rate | N/A | ≥85% of generated securities pass all compliance rules on first basket | At launch |
| Basket-to-execution conversion | N/A | ≥60% of generated baskets reach execution handoff | 6 months post-launch |

### Guardrail Metrics

- **Compliance violation rate:** 0% — no security that fails compliance should reach the execution stage without flagging
- **Advisor trust (qualitative):** ≥80% of POC advisors say "Would trade this basket" — measured during POC experiment
- **System availability:** 99.5% uptime during market hours (9:30 AM - 4:00 PM ET)

---

## 7. User Stories & Requirements

### Epic 1: AI Theme Classifier

**Epic Hypothesis:**
> We believe that an AI-powered theme classifier that maps a theme keyword to a ranked security basket with rationale will reduce advisor research time from 2-4 hours to under 15 minutes, because the NLP engine eliminates manual cross-tool screening. We'll measure success by time-to-basket during the POC with 10-15 advisors.

#### US 1.1 — Theme Search & Basket Generation

**As a** financial advisor managing client portfolios at a wirehouse
**I want to** type a theme like "AI infrastructure" and receive a ranked list of 8-12 stocks/ETFs with confidence scores
**so that** I can skip 2-4 hours of manual screening across research tools

**Acceptance Criteria:**
- **Scenario:** Advisor searches a well-known theme
- **Given:** I am authenticated on the platform
- **and Given:** The theme classifier model is trained and available
- **When:** I type "AI infrastructure" into the theme search bar and submit
- **Then:** I receive a ranked basket of 8-12 securities within 60 seconds
- **Then:** Each security displays: ticker, name, asset type (stock/ETF), sector, confidence score (0-100%), and expense ratio (ETFs only)
- **Then:** If the theme is unrecognized, I see: "Theme not recognized. Try a broader term or browse trending themes."

**Edge Cases:**
- Theme with fewer than 8 high-confidence securities → return what's available with a warning
- Theme with too many matches → cap at 15, show "top-ranked" label
- Empty input → disable submit button
- Off-hours model availability → show estimated wait time

---

#### US 1.2 — Basket Rationale & Transparency

**As a** financial advisor
**I want to** see the rationale behind each security's inclusion in the theme basket
**so that** I can confidently explain the picks to my clients and compliance team

**Acceptance Criteria:**
- **Scenario:** Advisor drills into a security's classification rationale
- **Given:** A theme basket has been generated for "clean energy transition"
- **When:** I click on a security (e.g., ENPH)
- **Then:** A detail panel shows: classification rationale (text), key data points (revenue exposure %, ESG fund inclusions, regulatory filing references), source citations with dates
- **Then:** I can copy the rationale text for client communication

---

#### US 1.3 — Basket Customization

**As a** financial advisor
**I want to** add, remove, and reweight securities in the AI-generated basket
**so that** I can incorporate my own market knowledge and client-specific preferences

**Acceptance Criteria:**
- **Scenario:** Advisor removes a security and adjusts allocation
- **Given:** A theme basket of 10 securities is displayed
- **When:** I remove 1 security and increase another from 10% to 15%
- **Then:** The remaining securities auto-rebalance to 100% total allocation
- **Then:** I can save the customized basket with a custom name
- **Then:** The basket shows a "customized" badge and tracks which changes I made vs. AI defaults

**Edge Cases:**
- Remove all securities → warning: "Basket is empty. Add at least 2 securities."
- Manual weights don't sum to 100% → show warning with "auto-fix" button
- Adding a security that's not in the AI's top results → flag: "Not in the top-ranked results for this theme. Add anyway?"

---

### Epic 2: Real-time Compliance Overlay

**Epic Hypothesis:**
> We believe that surfacing compliance status inline in the basket view — rather than in a separate portal — will reduce the compliance review cycle from hours to minutes, because advisors can see and fix issues before submission. We'll measure success by compliance first-pass rate at POC.

#### US 2.1 — Inline Compliance Flags

**As a** financial advisor
**I want to** see compliance status for each security directly in the basket view
**so that** I know immediately which picks will pass firm rules without opening a separate system

**Acceptance Criteria:**
- **Scenario:** Basket contains securities with mixed compliance status
- **Given:** A theme basket of 10 securities is displayed
- **and Given:** The firm's approved list, concentration limits, and suitability rules are configured
- **When:** The basket loads
- **Then:** Each row shows a colored badge — 🟢 green (passes all rules), 🟡 yellow (warning), 🔴 red (blocked)
- **Then:** I can filter the basket to show only green, yellow, or red securities
- **Then:** The basket header shows: "8 pass. 1 warning. 1 blocked."

**Compliance Rules (v1):**
- Approved list membership (ticker in/out)
- Concentration limit (single security ≤ X% of portfolio — configurable per firm)
- Suitability (security type allowed for account mandate — e.g., no leveraged ETFs for conservative accounts)
- 🔶 **Assumption:** These three rules cover ≥80% of pre-trade compliance checks. Needs validation with compliance stakeholders.

---

#### US 2.2 — Compliance Detail Drilldown

**As a** financial advisor
**I want to** click a red or yellow compliance badge and see exactly which rule triggered the flag
**so that** I can decide whether to override (yellow) or replace (red) without calling the compliance desk

**Acceptance Criteria:**
- **Scenario:** Advisor inspects a red-flagged security
- **Given:** A security shows a 🔴 red compliance badge
- **When:** I click the badge
- **Then:** A detail panel opens showing: rule violated, threshold (if applicable), current value, last review date, compliance contact
- **Then:** I see a "Request Exception" button for yellow warnings
- **Then:** I see a "Find Replacement" button for red blocked securities, which suggests the next-highest-ranked green security in the same sector
- **Then:** All detail views are logged to the audit trail

---

#### US 2.3 — Basket-Level Compliance Summary

**As a** financial advisor
**I want to** see a single compliance summary for the entire basket before execution
**so that** I can confirm at a glance the basket is trade-ready or know exactly what needs fixing

**Acceptance Criteria:**
- **Scenario:** Advisor reviews compliance before execution
- **Given:** A customized theme basket is ready for review
- **When:** I navigate to the compliance summary view
- **Then:** I see: "8 of 10 securities pass all rules. 1 warning (AAPL concentration: 12%, limit 10%). 1 blocked (TSLA: not on Q3 approved list). Estimated fix time: replace 1 security."
- **Then:** I can click "Fix All" to auto-suggest replacements for blocked/warned securities
- **Then:** The "Submit for Execution" button is disabled until all securities are 🟢 green
- **Then:** The summary can be exported as PDF for compliance record-keeping

---

### Story Map Summary

```
v1 (Q4 2026)
  Epic 1: Theme Classifier          Epic 2: Compliance Overlay
  ├── US 1.1: Search & Generate      ├── US 2.1: Inline Flags
  ├── US 1.2: Rationale              ├── US 2.2: Detail Drilldown
  └── US 1.3: Customize              └── US 2.3: Compliance Summary

v2 (Q1-Q2 2027)
  Epic 3: Smart Allocation
  ├── Per-account distribution (equal weight)
  ├── Risk-adjusted allocation rules
  └── Tax-aware allocation (tax-loss harvesting by category)

  Epic 4: Advisor-in-the-loop UX
  ├── Full basket review before execution
  ├── Pre-execution impact preview (estimated P&L)
  └── Client-ready rationale reports (PDF export)
```

### Sprint Plan (2-Week Sprints)

| Sprint | Team A: Classifier | Team B: Compliance | Integration Goal |
|---|---|---|---|
| **Sprint 1** | US 1.1: Theme search + basket MVP | US 2.1: Inline flags (green badge only) | Classifier API → UI shell + basic flags |
| **Sprint 2** | US 1.2: Rationale display | US 2.2: Detail drilldown | Click security → rationale + compliance detail |
| **Sprint 3** | US 1.3: Basket customization | US 2.3: Basket-level summary | Full basket: customize → compliance posture |
| **Sprint 4** | POC polish + iteration | POC prep + firm config | **POC ready:** 10-15 advisors test end-to-end |
| **Sprints 5-6** | POC feedback integration | POC feedback integration | Post-POC fixes + hardening |
| **Sprints 7-8** | Production hardening | Production hardening | **MVP ship** |

### Technical Constraints

- **Model training data:** Requires corpus of SEC filings, ETF holdings data, and market news for theme classification. 🔵 **Open Question:** Data licensing costs and update frequency TBD.
- **Compliance rules engine:** Must be configurable per firm (no single hard-coded rule set). Each firm's compliance team must be able to upload/maintain approved lists.
- **OMS integration:** v1 assumes manual handoff (advisor exports basket → enters into OMS). v2 requires API-level OMS integration. 🔵 **Open Question:** Which OMS to integrate with first?
- **Latency:** Theme classification must complete in ≤60 seconds during market hours.
- **Browser support:** Chrome, Edge, Safari (latest 2 versions).

### Dependencies

| Dependency | Owner | Status | ETA |
|---|---|---|---|
| Theme classifier model training | ML Engineering | 🔵 Not started | Sprint 0 (pre-Sprint 1) |
| Compliance rule schema design | Eng + Compliance | 🔵 Not started | Sprint 0 |
| POC advisor recruitment (10-15 advisors) | Product + Sales | 🔵 Not started | Sprint 3 |
| Firm compliance rule data (approved lists, limits) | Compliance stakeholders | 🔵 Not started | Sprint 2 |
| SSO integration (Okta / Azure AD) | Platform Engineering | 🔵 Not started | Sprint 1 |

---

## 8. Out of Scope

### v1 Explicitly Excluded

| Item | Why Not v1 |
|---|---|
| **OMS integration** (API-level trade execution) | Adds 2-3 months of integration complexity. Manual handoff first, prove value, then integrate. |
| **Smart allocation rules** (per-account distribution) | Depends on OMS integration and account-level mandate data. v2. |
| **Tax-loss harvesting by category** | Complex tax logic requires dedicated legal review. Post-v2. |
| **Pre-execution P&L preview** | Requires real-time market data integration. v2. |
| **Client-facing rationale reports** | Advisor trust must be established first. v2. |
| **Mobile app** | Desktop-first for advisor workflow. |
| **Multi-language support** | English-only for initial US wirehouse launch. |
| **Real-time market data feeds** (streaming prices) | Adds cost and latency complexity. Use end-of-day or delayed data for v1 basket generation. |
| **Custom theme creation by advisors** (beyond keyword search) | Keyword + AI is sufficient for MVP. |
| **Trade execution itself** | This product generates and validates baskets; it does not route orders to exchanges. |

### Future Consideration

- Integration with CRM systems (Salesforce, Redtail) for client communication tracking
- Automated rebalancing schedules (monthly/quarterly theme rebalancing)
- Peer benchmarking — "how does your AI infrastructure basket compare to other advisors'?"
- Compliance pre-clearance workflow (submitting baskets for compliance officer approval before advisor review)

---

## 9. Dependencies & Risks

### External Dependencies

| Dependency | Impact if Delayed | Mitigation |
|---|---|---|
| Compliance team providing approved list + rule data | Blocks US 2.1-2.3 | Start with synthetic test data; parallel-track compliance onboarding |
| POC advisor recruitment | Blocks validation | Engage sales/channel partners early (Sprint 1) |
| SSO / identity provider integration | Blocks advisor login | Build username/password fallback for POC; SSO for production |
| Market data licensing (ETF holdings, filings) | Blocks classifier training | Start with publicly available SEC EDGAR data |

### Risks & Mitigations

| Risk | Severity | Likelihood | Mitigation |
|---|---|---|---|
| **Classifier quality below POC threshold (80% overlap)** | 🔴 Critical | Medium | POC is the gate — do not proceed to full build if threshold isn't met. Have a fallback: curated baskets by research team instead of AI. |
| **Compliance stakeholders reject inline overlay approach** | 🔴 Critical | Low-Med | Involve compliance from Sprint 0. Show them the UX before building. Get sign-off on the rule schema. |
| **Advisors don't trust AI-generated baskets** | 🟡 High | Medium | Rationale feature (US 1.2) and customization (US 1.3) are designed to build trust. POC will measure the "Would you trade this?" metric. |
| **Firm procurement/sales cycle blocks POC access** | 🟡 High | Medium | Bottom-up GTM — find an internal champion advisor first, then use their success to open the formal door. |
| **Scope creep — stakeholders push for OMS integration in v1** | 🟡 Medium | Medium | Out of scope is documented (Section 8). OMS integration is the #1 v2 priority. |
| **Model drift — classifier quality degrades over time as markets change** | 🟢 Low | Low | Model retraining schedule (quarterly minimum). Monitor confidence score distribution for drift. |

---

## 10. Open Questions

| # | Question | Owner | Needed By |
|---|---|---|---|
| 1 | What is the actual 2-4 hour time cost for advisors doing theme research today? (Validate with shadowing) | Product | POC (Sprint 4) |
| 2 | Which OMS platforms are most common among our target firms? (Charles River, Bloomberg AIM, Aladdin, other) | Product + Eng | v2 planning (Q1 2027) |
| 3 | What is the compliance rule schema? Which rules are universal vs. firm-specific? | Compliance + Eng | Sprint 0 |
| 4 | Data licensing for ETF holdings and SEC filings — cost and update frequency? | Eng + Legal | Sprint 0 |
| 5 | What is the pricing model? Per-seat license + AUM fee? What price points? | Product + Business | Pre-launch (Q4 2026) |
| 6 | Do we need FINRA/SEC review or approval for the classification model's outputs? | Compliance + Legal | Sprint 2 |
| 7 | Should the classifier include fractional shares and/or crypto-related securities? | Product + Compliance | v2 planning |
| 8 | What's the competitive intelligence on Bloomberg/Refinitiv potentially building this? | Product | Q3 2026 |

---

## POC Experiment Design (Pre-v1 Gate)

| Element | Plan |
|---|---|
| **Hypothesis** | AI theme classifier produces baskets with ≥80% overlap with advisor manual picks and reduces time from 2-4 hours to ≤15 minutes |
| **Format** | 30-min side-by-side sessions per advisor |
| **Sample** | 10-15 advisors across 2-3 wirehouse teams |
| **Tasks** | (1) Advisor builds basket for a given theme using current tools — timed. (2) Advisor reviews AI-generated basket for the same theme — timed. (3) Overlap analysis + "Would you trade this?" survey. |
| **Success** | ≥80% overlap, ≤15 min time-to-basket, ≥80% "would trade" |
| **Go/No-Go** | Meet all three thresholds → full build. Miss any → iterate classifier or pivot to curated baskets. |
| **Timeline** | POC sessions: Sprint 4 | Analysis: Sprint 5 | Decision: End of Sprint 5 |

---

## Self-Assessment

| Dimension | Rating | Notes |
|---|---|---|
| **Strongest section** | Solution Overview (5), User Stories (7) | Concrete, testable, sprint-mapped |
| **Weakest section** | Problem Statement (2) | Needs real advisor evidence (quotes, data). Currently built on domain expertise + assumptions. |
| **Top assumption to validate** | AI classifier quality — can it hit 80% overlap with advisor picks? | POC is the gate. |
| **Recommended next step** | Share with Compliance + Engineering for initial feedback. Recruit POC advisors. Begin Sprint 0 (model training + rule schema). | |

---

## Sign-Off

| Role | Name | Date | Status |
|---|---|---|---|
| Product Management | | | Pending |
| Engineering Lead | | | Pending |
| Compliance / Legal | | | Pending |
| Executive Sponsor | | | Pending |

---

*This PRD is a living document. Update as POC results, compliance feedback, and market intelligence become available.*
