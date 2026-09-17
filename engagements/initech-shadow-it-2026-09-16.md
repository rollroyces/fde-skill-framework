# Engagement: initech-shadow-it-2026-09-16, 2026-09-16

> Dogfood engagement #3 — `cut` decision. This is the *anti-pattern*
> engagement: it shows what the framework catches when the Shadow IT
> trap is sprung. Initech's VP IT wanted to deploy an endpoint
> threat-detection service without his own security reviewer's
> written approval. The FDE lead (Sandra Park) raised it at the
> Discovery gate; Mark Robinson pushed back. The work proceeded
> anyway because Mark was the sponsor. Four weeks of post-GA
> measurements tell the rest of the story.

## 0. Engagement metadata

| Field                    | Value                                                                                |
|--------------------------|--------------------------------------------------------------------------------------|
| Customer                 | Initech — IT Operations org                                                          |
| Engagement codename      | shadow-it-endpoint-threat                                                            |
| Sponsor                  | Mark Robinson, VP IT Operations, mark.robinson@initech.example                       |
| Daily technical contact  | Sandra Park, FDE lead (sourced from us)                                              |
| **Security reviewer**    | **— EMPTY —**. The name is blank because Initech's CISO (Lila Chen) was never asked  |
|                          | to sign off. Mark Robinson stated "this is a security feature, security doesn't need |
|                          | to review it" at the 2026-09-18 Discovery call. Lila Chen found out on 2026-10-09    |
|                          | when the service started paging her team's SIEM with unvetted rules.                |
| Legal / procurement      | Not engaged. No DPA review, no new-vendor paperwork. (No new vendors actually added; |
|                          | the deploy used Initech's existing AWS tenant.)                                       |
| Discovery start          | 2026-09-16                                                                           |
| Target GA                | 2026-10-15 (4 weeks — Mark pushed for a fast ship to demo at the Q4 board offsite)    |
| Actual GA                | 2026-10-08 (one week ahead — Mark pushed harder)                                      |
| Wind-down                | 2026-11-13 (full incident postmortem; service decommissioned 2026-11-20)              |

> **Anti-pattern name:** **Shadow IT** — deploying into a customer's
> environment without their security reviewer's written approval.
> This is one of the five anti-patterns the framework blocks in
> `.hermes/skills/fde-workflow.md` §Anti-patterns. It bypassed the
> gate here because the sponsor himself pushed past the FDE lead.
> The framework caught it on the *post-GA* axis (breaches + missing
> metric/ROI), but ideally it would have been caught at Discovery.

## 1. Business metric (M)

The metric Mark Robinson named at Discovery:
**endpoint threat-block rate** (% of detected malicious events
blocked at the endpoint before they reach the SIEM).

- **Metric name:** `endpoint_threat_block_rate`
- **How measured today:** *Not measured*. Mark did not have a
  baseline number, a target number, or a target date. The closest
  reference was Initech's Q3 2026 board deck (slide 14), which
  cited "block rate trending up" without defining it.
- **Owner inside customer org:** Mark Robinson (sponsor). No
  named security counterpart.
- **Baseline:** `null` — not sourced. FDE lead asked twice
  (2026-09-18, 2026-09-22) and was told "we'll know it when we
  see it in production."
- **Target at GA:** `null` — not sourced.
- **What moves M outside our work?** Almost everything. A real
  endpoint threat-block metric depends on detection rules, the
  threat-intel feed (vendor-managed), the rule-update cadence,
  and the security team's triage workflow — none of which were
  documented or owned.

## 2. SLA targets

The SLA section *was* filled in at Discovery, sourced from
Initech's existing monitoring defaults.

| Surface                       | p50     | p95     | p99    | Availability | Error budget |
|-------------------------------|---------|---------|--------|--------------|--------------|
| `endpoint-threat-detector`    | 100 ms  | 350 ms  | 500 ms | 99.9%        | 0.1%         |
| SIEM event push               | 2 s     | 10 s    | 30 s   | 99.5%        | 1.0%         |

- **Where measured:** Initech's Prometheus + their SIEM (Splunk).
- **Breach consequence:** Per the Initech IT Ops runbook: any p99
  breach > 2× the target triggers an SEV-2 incident. Every single
  week of post-GA measurements breached this by >2×.
- **Burst / seasonality:** Monday 08:00–10:00 local (endpoint
  boot storms) — capacity must hold at burst.
- **Quiet hours:** 22:00–06:00 — full availability, no on-call.

## 3. Constraints

`constraints: []` — empty at Discovery. This is itself a finding.
FDE lead flagged it as "missing" at the 2026-09-18 call; Mark
declined to populate it.

What *should* have been in here, based on retroactive review:
- **Data residency:** Initech's tenant is AWS us-east-1. Customer
  data stays in-region. (Standard Initech default; never
  documented because Mark said "we always do this.")
- **Compliance regime:** SOC 2 Type II + ISO 27001. The endpoint
  service handles endpoint telemetry that includes user-identifying
  fields (hostname, user SID) — both regimes are in scope. **The
  security reviewer's gap is the compliance gap.**
- **Vendor allow-list:** No new vendors (the deploy used Initech's
  existing AWS tenant + a third-party threat-intel API Mark had
  not disclosed to procurement — `threatfeed.example.io`,
  contract status unclear as of cut date).
- **Tech stack:** Python 3.11+, runs in Initech's existing ECS
  cluster. No new framework introductions.
- **Budget ceiling:** $15,000. Actual spend $11,400.
- **Fixed launch date:** 2026-10-15 (target). Actual: 2026-10-08.

## 4. Stakeholders & cadence

| Role             | Name             | Channel                         | Cadence we owe them                  |
|------------------|------------------|---------------------------------|--------------------------------------|
| Sponsor          | Mark Robinson    | Slack #initech-it-ops           | Daily status, weekly demo            |
| Daily peer       | Sandra Park      | Slack #initech-shadow-it        | Pair sessions, code review           |
| **Security**     | **(missing)**    | —                               | Lila Chen (CISO) was never asked to sign off |
| Legal/procurement| (not engaged)    | —                               | —                                    |
| End user         | None engaged     | —                               | Service pages the SIEM but no human reviews events |

`stakeholders` length = 2 (sponsor + FDE lead). The framework's
business axis requires ≥ 3 stakeholders for full credit — this
is the second Discovery gap.

## 5. ROI inputs

`roi_inputs: {}` — empty. No value_per_unit, no volume_per_year,
no cost_ceiling.

Mark's verbal claim at Discovery (2026-09-18): "If we block even
10% of threats at the endpoint, that's worth $2M/yr." FDE lead
asked for the source three times across Discovery (2026-09-18,
2026-09-22, 2026-09-25). Mark declined to provide it each time,
saying "we'll back-fill the math after we see it work."

**Without a sourced ROI, the scale gate fails on its face.**
This is the third Discovery gap.

## 6. Open questions (the ones FDE lead raised)

- [ ] **Get a security reviewer assigned and signed off** — FDE lead
      raised this 2026-09-18, 2026-09-22, 2026-09-25. Mark: "We'll
      loop security in after the first month of production." FDE
      lead noted on 2026-09-25 that this is a **hard gate per
      `.hermes/skills/fde-workflow.md`** and that proceeding without
      sign-off would be a Shadow IT anti-pattern.
      *Status at GA: still no security reviewer.*
- [ ] **Source the ROI inputs** — FDE lead asked 3× between
      2026-09-18 and 2026-09-25. Mark declined to back-fill.
      *Status at GA: ROI inputs still empty.*
- [ ] **Source the baseline + target for M** — FDE lead asked 2×.
      Mark: "we'll see what we have in production." *Status at GA:
      baseline and target still `null`.*
- [ ] **Identify the third-party threat-intel API vendor and confirm
      Initech's contract status** — FDE lead asked 2026-09-25. Mark:
      "it's a small vendor, we'll sort it out."
      *Status at GA: vendor `threatfeed.example.io` was live in
      Initech's environment with no documented DPA. SIEM logs
      showed calls from week 1 forward.*

## 7. Sign-off

- [x] Sponsor agrees M, baseline, target, date         (Mark, 2026-09-16)
      *— but baseline and target are `null`. Sign-off on empty boxes.*
- [ ] Sponsor agrees SLA envelope                       *(Mark said "yes"
      verbally on 2026-09-18; no formal sign-off captured)*
- [ ] Security reviewer signs off                       *(no reviewer
      ever assigned)*
- [ ] Legal / procurement signs off                     *(never engaged)*
- [x] FDE lead agrees constraints complete              *(Sandra — but
      with a written objection on 2026-09-25 noting the four gaps
      above; the objection is in the engagement channel transcript.)*
- [ ] Both sides agree ROI inputs                      *(ROI inputs
      empty; sign-off impossible)*

Signed: Mark Robinson / Sandra Park (with objections on file)
Date: 2026-09-25 (Discovery close) — *work proceeded despite
the four gaps.*

---

## Architecture (link to solution brief)

Solution brief: `docs/initech-endpoint-threat-architecture.md`
(drafted 2026-09-30 by Sandra, reviewed by *no one* — the FDE
lead flagged this in the same 2026-09-25 objection note; Mark
shipped the brief internally without external review).

Risk register (top 5):

| Risk                                                      | Likelihood | Blast radius         | Mitigation                                              | Owner |
|-----------------------------------------------------------|------------|----------------------|---------------------------------------------------------|-------|
| **Undisclosed third-party threat-intel vendor**            | **Realized** | Compliance re-audit  | Cut + decommission on 2026-11-20                      | Sandra |
| **No security reviewer means no rule-quality gate**        | **Realized** | SIEM noise storm    | Cut + decommission on 2026-11-20                      | Sandra |
| Untested ECS cluster sizing                                | **Realized** | Availability breach | Cut + decommission on 2026-11-20                      | Sandra |
| Threat-feed rate-limit not respected by Initech's pull loop| **Realized** | p99 spikes          | Cut + decommission on 2026-11-20                      | Sandra |
| Endpoint telemetry includes PII (user SID) — no DPA        | **Realized** | Compliance re-audit | Cut + decommission on 2026-11-20                      | Sandra |

ROI model: **None produced.** No sourced value_per_unit, no
sourced volume, no sourced cost ceiling. The scale gate
(value/cost ≥ 1.2× using sourced inputs) cannot even be
evaluated, because both numerator and denominator are unknown.

---

## Build (ship log)

- 2026-09-29: vertical slice live in Initech's ECS cluster.
  Reads endpoint telemetry, calls the undisclosed threat-intel
  API, pushes alerts to SIEM. p99 = 950ms (target 500ms).
  FDE lead flagged the SLA miss in the channel; Mark: "ship it,
  we'll tune in production."
- 2026-10-08: GA, one week ahead of target. Initech's SIEM
  starts receiving alerts. p99 = 1200ms (target 500ms — **2.4× over**).
- 2026-10-09: Lila Chen (CISO) finds out about the deploy from
  the SIEM alert volume. Asks Mark Robinson why she wasn't
  asked to review. Mark: "this is a security feature, security
  doesn't need to review it." Lila escalates to the CIO.
- 2026-10-15: SEV-2 incident opened. p99 = 1300ms (target 500ms).
  Availability 96.8% (target 99.9%). Initech's IT Ops team
  pages on-call twice in 48 hours.
- 2026-10-22: week 3 post-GA. SIEM alert volume 8× Initech's
  normal rate. Lila Chen formally asks for the deploy to be
  paused pending security review. Mark delays.
- 2026-10-29: week 4. p99 = 1250ms. Availability 97.2%. Two
  more SEV-2 incidents. Lila Chen freezes the deploy on
  2026-10-30 unilaterally.
- 2026-11-05: incident postmortem begins. FDE lead writes up
  the four Discovery gaps in writing.
- 2026-11-13: postmortem complete. Decision: **CUT and
  decommission**. Service taken offline 2026-11-20.

---

## ROI evaluation (final, post-GA)

- M: baseline=`null`, target=`null`, achieved value=18-22% (the
  service did detect and block some events, but the metric was
  never sourced so we can't say if this beats a baseline that
  doesn't exist).
- SLA: p99 every week over 1000ms (target 500ms → all 4 weeks
  breached by ≥2×, triggering SEV-2 each week); availability
  every week < 98% (target 99.9% → all 4 weeks breached);
  error_rate every week 4–6% (target 0.1% → all 4 weeks breached
  by 40–60×).
- Cost: actual $11,400 infra (mostly AWS ECS over-provisioning
  from the p99 crisis) + 1.5 engineer-weeks of FDE time ($7,500).
  Total = $18,900.
- ROI: cannot compute. No sourced value_per_unit, no sourced
  volume, no sourced cost ceiling.

**Decision: CUT.**

Rationale (in priority order):

1. **Shadow IT anti-pattern realized.** No security reviewer ever
   signed off. Lila Chen's retroactive review (2026-11-04) found
   three compliance gaps: undisclosed vendor DPA, PII in endpoint
   telemetry without DPA coverage, and unvetted SIEM push rules.
   Any one of these would have triggered a SOC 2 audit finding.
2. **Discovery gate never closed.** baseline, target, ROI inputs,
   constraints, and security reviewer were all empty when the
   work shipped. The framework's business axis scores this at
   25/100 — *below the cut threshold on its own*.
3. **SLA envelope breached every week.** p99 2.4–2.6× target,
   availability 1.9–3.1% under target, error rate 40–60× budget.
   The service generated four SEV-2 incidents in four weeks.
4. **ROI unsourced.** Mark's "$2M/yr" verbal claim was never
   documented. No way to evaluate value/cost.

The framework caught this on the *post-GA* axis — but the
Discovery gate should have caught it earlier. Lesson: the
framework's gates are *advisory* if the sponsor overrides
the FDE lead. The next iteration of the framework should
make the security-reviewer sign-off an **enforced** gate
(not advisory) when the deployment handles customer PII.

## What this engagement file proves

Every claim is sourced:

- Missing Discovery fields — engagement channel transcript
  (2026-09-18 through 2026-09-25) shows Mark declining to fill
  them in three times each.
- SLA breaches — Initech's Prometheus + Splunk (read-only access
  to FDE throughout).
- The compliance gaps Lila Chen found — her 2026-11-04 retro
  notes (attached to Initech's IT Ops ticket IT-9981).
- The cut decision — Initech CIO sign-off on 2026-11-13.

**The framework correctly identifies cut here on the business
axis alone** (baseline, target, ROI inputs, and security-reviewer
all empty → business score = 25/100, below the 60 threshold).
The SLA breaches and the realized Shadow IT anti-pattern
confirm the cut decision from the post-GA side.

This engagement is the framework's *teaching example* for the
Shadow IT anti-pattern. It belongs in `.hermes/skills/fde-workflow.md`
§Anti-patterns as a worked example (TODO for the FDE lead:
add the cross-reference; the cross-reference itself is out of
scope for this dogfood commit).
