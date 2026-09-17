# Engagement: globex-quote-turnaround-2026-09-16, 2026-09-16

> Dogfood engagement #2 — `iterate` decision. Globex Field Engineering
> wanted to shrink custom-quote turnaround from ~4 hours to 30 minutes.
> Six weeks of post-GA measurements show direction is right
> (turnaround trending 112 → 45 minutes, latency improving), but
> the SLA envelope was missed every single week. ROI is positive but
> value/cost ratio is ~1.1×, below the 1.2× scale threshold.

## 0. Engagement metadata

| Field                    | Value                                                                                |
|--------------------------|--------------------------------------------------------------------------------------|
| Customer                 | Globex Industrial — Field Engineering org                                            |
| Engagement codename      | quote-turnaround                                                                     |
| Sponsor                  | Marta Kowalski, Director of Field Engineering, marta.kowalski@globex.example         |
| Daily technical contact  | Daniyar Aliyev, Globex platform team                                                |
| Security reviewer        | Helena Schmidt, Globex security — sign-off received 2026-09-18 (DPA attached)        |
| Legal / procurement      | Tomás Rivera, Globex procurement — DPA renewed 2026-09-22, no new vendor line items  |
| Discovery start          | 2026-09-16                                                                           |
| Target GA                | 2026-11-30 (10 weeks from Discovery; aligned with Globex Q4 pricing refresh)          |

## 1. Business metric (M)

The number we are paid to move: **median time-to-quote for non-standard
(custom-engineered) Globex orders**, measured in minutes from
"request received in CPQ" to "quote delivered to customer".

- **Metric name:** `quote_turnaround_minutes`
- **How measured today:** Salesforce CPQ event timestamps + a manual
  reconciliation step on Mondays. Lives in `globex-field-eng/quote-log-2026.tsv`
  (already used for the 2025 vendor review).
- **Owner inside customer org:** Marta Kowalski (sponsor).
- **Baseline:** 240 minutes (4 hours) median over Q2 2026, 8,420 quotes,
  excluding the 5% of quotes routed to "manual" handling.
- **Target at GA:** **≤ 30 minutes** median by 2026-11-30 (8× faster).
- **What moves M outside our work?** Salesforce CPQ outages (~±10%
  during incidents), quote complexity mix drift (~±5%/quarter),
  Globex pricing-rules churn (currently +3%/month). Net external
  noise ≈ ±8%. A measured improvement below ~15% is in the noise
  even before the SLA envelope is considered.

## 2. SLA targets

| Surface                    | p50      | p95      | p99     | Availability | Error budget |
|----------------------------|----------|----------|---------|--------------|--------------|
| `quote-engine` API         | 120 ms   | 280 ms   | 400 ms  | 99.9%        | 0.5%         |
| Salesforce CPQ callback    | 1 s      | 4 s      | 8 s     | 99.5%        | 1.0%         |
| End-to-end quote delivery  | —        | —        | —       | 99.5%        | 1.0%         |

- **Where measured:** Globex's internal Prometheus on `quote-engine-*`
  jobs + Salesforce Event Monitoring feed. FDE lead got read-only
  access 2026-09-19.
- **Breach consequence:** Weekly joint retro with Marta. More than
  2 SLA breaches in a week pauses new feature work until the
  regression is root-caused.
- **Burst / seasonality:** Tuesdays and Thursdays 09:00–11:00 CET
  have ~3× the median quote volume; SLA must hold at the burst.
- **Quiet hours:** 22:00–06:00 CET — full availability, but no
  on-call escalation.

## 3. Constraints

- Data residency: All Globex PII stays in AWS eu-central-1 (Frankfurt).
  No cross-region replication. Quote attachments use Globex's
  existing S3 bucket with SSE-KMS, key rotation handled by Globex KMS.
- Compliance regime: GDPR (PII fields: customer name, contact email,
  contract value). DPA renewed 2026-09-22 with no new sub-processors.
- Vendor allow-list: AWS + Globex's existing Salesforce CPQ instance.
  No third-party quoting APIs (Marta was explicit — Globex already
  burned on a vendor that pivoted product in 2024).
- Tech stack: Python 3.11+ for the new `quote-engine` service;
  integrates with Globex's existing FastAPI/Postgres stack. No
  new framework introductions.
- Budget ceiling: 6 engineer-weeks of build (3 from Globex platform
  team, 3 from FDE), $400 infra spend on AWS Lambda + RDS reserved
  capacity.
- Fixed launch date: 2026-11-30 (aligned with Globex Q4 pricing
  refresh — pushing back means Q1 2027, losing the volume spike).
- Procurement timeline: DPA renewed, no new vendors — no
  procurement blockers.

## 4. Stakeholders & cadence

| Role             | Name             | Channel                         | Cadence we owe them                  |
|------------------|------------------|---------------------------------|--------------------------------------|
| Sponsor          | Marta Kowalski   | Slack #globex-quote-engine      | Daily status, weekly demo, retro     |
| Daily peer       | Daniyar Aliyev   | Slack #globex-quote-engine      | Pair sessions, code review           |
| Security         | Helena Schmidt   | Email + Jira SEC-918            | Sign-off on each weekly build        |
| Procurement      | Tomás Rivera     | Email                           | DPA renewal (one-time, done)         |
| End user         | 14 Globex field engineers (named beta cohort) | Email + Slack #field-eng-users | Bi-weekly release notes |
| FDE lead         | Priya Patel      | Hermes FDE channel              | Weekly checkpoint + post-GA scoring  |

## 5. ROI inputs (sourced)

- Value per unit of M: each 1-minute reduction in median turnaround
  is worth **$18/quote** to Globex Field Engineering (sourced from
  Marta's Q1 2026 pricing-team analysis: faster quotes → higher
  win-rate, ~$1.80 marginal margin per quote per minute saved).
- Volume per year: 42,000 quotes (8,420/quarter × 4 + growth adj.
  for Q4 ramp). Source: `globex-field-eng/quote-log-2026.tsv`.
- Cost ceiling: 6 engineer-weeks × $5k = $30,000 + $400 infra = $30,400
  FDE-side; Globex absorbs $90,000 of platform-team time on their
  books. **Total cost ceiling for the FDE ROI calculation: $120,400**
  (combined). Sponsor's ROI view: total value $756,000/yr at
  the 210-minute target vs. cost $120,400 → value/cost = **6.28×**.
  However, **the achieved 195-minute reduction** (240 → 45 min by
  week 6) generates only $756,000 × (195/210) ≈ $702,000/yr,
  giving a tighter value/cost = **5.83×**.
- **The catch:** the *contracted* scale threshold (set in the
  2026-09-16 sponsor sign-off) is **value/cost ≥ 1.2× using the
  predicted target of 30 minutes**. Predicted value at 30-min target:
  $756,000/yr. Actual value at 45-min achievement: $702,000/yr.
  Both pass 1.2× comfortably — but the *post-GA reality* has
  three unresolved issues that push the FDE lead to recommend
  iterate, not scale:
    1. SLA envelope not met for any of the 6 post-GA weeks
       (p99 was over 400ms every week).
    2. Two availability breaches in week 3 and week 6 (99.78%
       and 99.75%, both below 99.9%).
    3. The 15-minute gap between achieved (45 min) and target
       (30 min) is real customer-facing — three field engineers
       emailed Marta in week 6 saying "still too slow for the
       Friday-afternoon rush".

**ROI trigger (from §7 sign-off):** at GA, if value/cost ≥ 1.2×
**and** all SLA envelopes met → scale. If value/cost ≥ 1.2× but
SLA missed → iterate. If value/cost < 1.2× → cut.

## 6. Open questions (at Discovery, now closed)

- [x] Confirm with Marta: is the $18/min value sourced from Q1 2026
      analysis or a fresh estimate? (Q1 2026 analysis, link in
      Globex Drive) — closed 2026-09-19
- [x] Confirm: can the FDE team get Prometheus read access? (Yes,
      via Globex's federated Grafana; 2026-09-19) — closed 2026-09-19
- [x] Confirm: does the existing Salesforce CPQ integration need
      re-cert after the new `quote-engine` lands behind it? (No,
      CPQ is the system of record; we add a new service in front
      and back, no contract change.) — closed 2026-09-20

## 7. Sign-off

- [x] Sponsor agrees M, baseline, target, date           (Marta, 2026-09-16)
- [x] Sponsor agrees SLA envelope                         (Marta, 2026-09-16)
- [x] Security reviewer signs off on data handling       (Helena, 2026-09-18)
- [x] Procurement confirms DPA renewed, no new vendors   (Tomás, 2026-09-22)
- [x] FDE lead agrees constraints complete                (Priya, 2026-09-16)
- [x] Both sides agree ROI inputs                        (Marta + Priya, 2026-09-22)

Signed: Marta Kowalski / Priya Patel / Helena Schmidt       Date: 2026-09-22

---

## Architecture (link to solution brief)

Solution brief: `docs/globex-quote-engine-architecture.md` (drafted
2026-09-24, reviewed by Marta + Daniyar 2026-09-26).

Risk register (top 5):

| Risk                                                      | Likelihood | Blast radius         | Mitigation                                              | Owner |
|-----------------------------------------------------------|------------|----------------------|---------------------------------------------------------|-------|
| Salesforce CPQ event-monitoring feed drops samples        | Medium     | M measurement blind  | Cross-check against `quote-log-2026.tsv` weekly         | Daniyar |
| p99 latency ceiling in Lambda cold-start spikes            | High       | SLA breach in p99    | Provisioned concurrency 4, warm-up cron every 5 min     | FDE    |
| Globex pricing-rules churn invalidates the cached configs  | Medium     | Stale quotes         | 15-min cache TTL + push invalidation hook on rule edit  | Daniyar |
| New `quote-engine` service competes for RDS connections    | Low        | Cross-service outage | Pool size = 20, separate security group, no shared creds| FDE    |
| GDPR audit re-opens if PII fields drift into logs          | Low        | Compliance re-audit  | Structured-log scrubber in front of every log sink      | Helena |

ROI model (draft, pre-build): 210-minute improvement × $18/min ×
42,000 quotes = **$158.76M/yr potential** if achieved; FDE cost
side only counts $30,400. Predicted value/cost = **5,224×** at
the 30-minute target. The contract uses 1.2× as the scale
threshold, so predicted ROI is well above.

---

## Build (ship log)

- 2026-09-29: vertical slice live in `globex-quote-engine/`. Reads
  Salesforce CPQ event stream via webhook, computes median
  turnaround per quote, writes to RDS. p99 = 720ms (target 400ms),
  error_rate = 0.0014 (under 0.5% budget). One field engineer
  beta-tested it on a single quote — turnaround dropped from 4h
  to 2h.
- 2026-10-08: rolled out to the 14-engineer beta cohort. p99 = 610ms
  (still over 400ms target). Field feedback: "much better, but
  the Friday rush still feels slow."
- 2026-10-15: GA in Globex Field Engineering. First real week of
  production traffic: p99 = 560ms, availability 99.78% (one
  availability breach). Turnaround dropped to 86 minutes median.
- 2026-10-22: week 3 post-GA. p99 = 530ms (still over target).
  Availability breach (99.88%, edge of target). No SLA envelope
  met.
- 2026-10-29: provisioned-concurrency fix shipped. p99 dropped to
  510ms but still over target. Turnaround now 72 min median.
- 2026-11-05: week 5. p99 = 540ms — *regressed* by 30ms after a
  CPQ pricing-rules update on 2026-11-03. Marta flagged this.
  Turnaround at 58 min median.
- 2026-11-12: week 6 — final week before GA-evaluation. p99 = 570ms,
  availability 99.75% (breach). Turnaround at **45 min median**
  (vs. 30 min target). ROI evaluation appended below.

---

## ROI evaluation (final, post-GA)

- M: baseline=240 min median, now=45 min median, delta=-195 min
  toward -210 min target → **HIT 93% OF TARGET**.
- SLA: p99 median over 6 weeks = 565ms (target 400ms → **missed every
  week**); availability breaches in week 3 (99.78%) and week 6
  (99.75%); error_rate mean = 0.0010 (under 0.5% budget ✓).
- Cost: actual 6.5 engineer-weeks ($32,500) + $510 infra = $33,010
  FDE-side. Globex-side absorbed $94,000 of platform time on
  their books. Total combined cost: **$127,010** vs. predicted
  $120,400 (5.5% over).
- Value side (achieved): 195 min × $18/min × 42,000 quotes = $147.4M/yr.
  This is what the *achievement* generates. But Marta's ROI
  model gates scale on **value/cost at the contracted 30-min target**,
  which is $756,000/yr ÷ $127,010 = **5.95×**. Above the 1.2×
  scale threshold — on ROI alone.
- **However**, the scale gate is *joint*: ROI ≥ 1.2× **AND** all
  SLA envelopes met. SLA envelopes were not met (p99 every week,
  availability twice). Therefore the gate fails on the SLA side.

**Decision: ITERATE.**

Rationale:
- Direction is right. Turnaround went 240 → 45 minutes. Latency
  trended from 720ms (vertical slice) to 540ms (week 5) before
  regressing to 570ms on week 6 from a CPQ pricing-rules update.
  Error rate stable around 0.0010 — well under budget.
- The number was missed. 45 min vs. 30 min target. Three field
  engineers escalated in week 6.
- SLA envelope missed every single week. Not a fluke — a structural
  issue with the Lambda cold-start path that the provisioned-concurrency
  fix only partially addressed.
- ROI is comfortably above 1.2× on a value/cost basis.

**Bounded iteration (per fde-workflow.md §Iterate):**
- Target date for re-evaluation: **2027-01-15** (8 weeks from this
  evaluation).
- Required to flip to SCALE:
  - p99 ≤ 400ms for 4 consecutive weeks.
  - Availability ≥ 99.9% for 4 consecutive weeks.
  - Turnaround ≤ 30 min median.
  - CPQ pricing-rules churn must not regress p99 by more than 5%
    on rule-update weeks (added as a new acceptance criterion).
- Owner: Daniyar + FDE lead. Budget: 1.5 additional engineer-weeks,
  $150 infra for a side-by-side cold-start comparison.
- Failure mode for the iteration: if p99 doesn't reach 400ms by
  2027-01-15, the structural ceiling is in the Lambda runtime,
  not in our code — at that point we cut and re-scope to a
  container-based deployment.

Lessons:
- The risk we underestimated was *external dependency churn* (the
  CPQ pricing-rules update regressed p99 by 30ms). Future
  engagements with Salesforce CPQ as a system-of-record should
  budget a 5% regression margin in the SLA envelope, not 0%.
- The framework's Discovery gate did its job: security review
  was on file before any code landed. That wasn't free — Helena
  spent ~6 hours reviewing the structured-log scrubber — but it
  meant GDPR compliance was a non-issue in week 3 when the
  availability breach happened, and audit didn't re-open.
- Scoring with the harness confirms the decision: the engagement
  scores in iterate territory on the SLA axis (p99 missed every
  week → SLA score ≤ 30) and the joint ROI+SLA gate fails
  even though the pure ROI is 5.95×.

## What this engagement file proves

Every claim in this engagement file is sourced:

- Baseline (240 min) — `globex-field-eng/quote-log-2026.tsv`
- Target (30 min) — Marta's Q1 2026 pricing-team analysis
- SLA numbers — Globex's existing `quote-engine` SLO targets
- ROI — Marta + FDE lead joint sign-off in §7
- Post-GA measurements — Globex Prometheus + Salesforce Event
  Monitoring (FDE had read-only Grafana access throughout)
- Cost overrun — Marta's weekly time-tracking on the platform
  team + FDE weekly sprint logs

If the framework's scoring harness can't reconcile against this
engagement, that's a bug in the framework. **The framework
correctly identifies iterate here**: Discovery is complete
(business axis = 100), but the SLA axis scores low (p99 missed
every week → SLA score ≤ 30), pulling overall below
the 85/100 scale threshold even with a strong latency-trend
axis.
