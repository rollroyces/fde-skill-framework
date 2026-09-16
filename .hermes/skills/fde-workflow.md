---
name: fde-workflow
description: Use when a Forward Deployed Engineer task lands — engineering work that must tie to a named customer outcome, SLA, and ROI number. Enforces Discovery → Architecture → Build → ROI Evaluation loop.
version: 1.0.0
tags: [fde, roi, sla, customer-outcomes, business-discovery]
---

# FDE Workflow Skill

A Forward Deployed Engineer (FDE) ships working code into a customer environment
that closes a measurable business gap. This skill enforces the four-phase loop
below. **No code is written until a named customer, a measurable outcome, and
a target SLA are on paper.** ROI is evaluated against those numbers after every
ship — not as an afterthought.

---

## 1. Discovery (must complete before any architecture work)

Goals: convert a vague request ("speed this up", "add AI") into a defensible
business case that engineering can build against.

Required artifacts:

- **Named customer & sponsor.** "Acme Corp — VP Ops Jane Doe". No sponsor →
  stop and ask. Use `references/business-discovery-template.md` to drive the
  interview; do not improvise.
- **Business metric (the *M* in M-Score).** A single number that the customer
  cares about and the FDE can move. Examples: weekly support tickets resolved
  per agent, average quote turnaround (minutes), fraud-loss rate (basis
  points), cost-per-invoice ($). If the customer can't name one, the metric
  hasn't been chosen — reframe until they can.
- **Baseline.** Today's value of *M*, with source (BI dashboard CSV,
  spreadsheet, query result). No baseline → no delta.
- **Target.** Where *M* must land by the contract date. Must be a number, with
  a date.
- **SLA envelope.** Latency p50/p95/p99, availability %, per-request error
  budget. Tied to the customer-facing surface (API, UI, batch job), not to
  internal components.
- **Constraints.** Data residency (GDPR, HIPAA, ITAR, mainland-China PIPL),
  vendor list, fixed launch date, fixed budget. Anything that closes a design
  door.
- **Stakeholder map.** Sponsor, daily technical contact, security reviewer,
  legal/procurement. Names + contact channel + timezone. Without this, you
  ship to a black hole.

Exit gate: every row above is filled in. The full discovery pack lives in
`references/business-discovery-template.md`. If a row is "TBD", escalate to the
sponsor — do **not** invent a number.

## 2. Architecture

Translate the discovery pack into a buildable shape.

- **Solution brief (1 page).** What we're building, why, what we're not
  building, who uses it, how success is measured. Sent to sponsor before code.
- **System sketch.** Components, data flow, trust boundaries, external
  dependencies. ASCII or Mermaid — clarity beats fidelity.
- **Tech stack contract.** Languages, frameworks, services, deployment target,
  observability stack. Must respect `tech_stack.constraints` in `.hermes.md`.
  If the requested stack violates a constraint, raise it before writing code.
- **Risk register.** Top 5 things that could prevent us from hitting the
  target. Each row: risk, likelihood, blast radius, mitigation, owner.
- **SLA budget allocation.** p99 = Σ(component p99). If the sum exceeds the
  customer's SLA, redesign before building.
- **ROI model (draft).** Revenue enabled, cost avoided, or hours saved ×
  loaded cost. Show the inputs — the customer will challenge them.

Exit gate: solution brief is sent and sponsor replies within 1 business day
(or an alternate reviewer is named). Risk register has owners for every row.
ROI model inputs are sourced.

## 3. Build

Ship the smallest thing that lets us measure.

- **Vertical slice first.** One real customer transaction, end-to-end, in
  their environment. No mocks across the trust boundary.
- **Instrument everything.** Every component emits: request id, customer id,
  latency (start/end), result, error class, dependency name. If a metric
  isn't on a dashboard the FDE looks at daily, it doesn't exist.
- **Hard rules.**
    - Never log PII without a documented redaction rule.
    - Never disable auth to "make it work".
    - Never ship a feature behind a flag that defaults off — that's not a
      feature, it's a draft.
    - Every external API call has a timeout, retry policy, and circuit
      breaker.
- **Stakeholder communication.** Daily one-paragraph status to sponsor
  (blockers first, decisions needed second, progress last). Weekly demo of
  working software against the real customer data.
- **Code review gate.** At least one engineer outside the FDE pair reviews
  before customer-facing deploy. FDE code has a higher bar because it lives
  in someone else's org.

Exit gate: vertical slice is live in the customer's environment, instrumented,
and the baseline-vs-now delta is being captured automatically.

## 4. ROI Evaluation

Run after every meaningful ship — never at the end of the engagement.

- **Did *M* move?** Compare baseline to current value, with the same
  measurement method. If methodology drifted, re-measure the baseline.
- **Did we hit SLA?** p99 latency, error rate, availability — actual vs
  contract. Any breach triggers an incident review even if the customer
  hasn't noticed.
- **What did it cost?** Engineering hours, infrastructure spend, third-party
  API costs. Compare to ROI model's predicted cost.
- **Decision.** Three outcomes only:
    1. **Scale.** Hit the target, ROI positive → expand to next workflow /
       customer.
    2. **Iterate.** Hit direction, miss number → one bounded iteration with
       a new target date.
    3. **Cut.** ROI negative or blocked by a constraint that won't move →
       wind down cleanly, hand off what shipped, document lessons in this
       skill.

Every ROI evaluation is appended to the engagement log (see template below).
The log is the durable record of what was promised, what shipped, and what
the customer got.

---

## Engagement log template

Append a block per engagement to `engagements/<customer>-<date>.md`:

```markdown
# Engagement: <customer>, <date>

## Discovery
- Sponsor: …
- Business metric M: …
- Baseline: … (source: …)
- Target: … (date: …)
- SLA: p50=…, p95=…, p99=…, error_budget=…
- Constraints: …
- Stakeholders: …

## Architecture (link to solution brief)
…

## Build (ship log)
- <date>: vertical slice live in <env>; p99=X ms
- <date>: v1 to 10% traffic; SLA breaches = …
- <date>: GA; M moved from … to …

## ROI evaluation
- M: baseline=…, now=…, delta=… (% toward target)
- SLA: p99=… (target …), error_rate=… (target …), availability=… (target …)
- Cost: actual=… vs predicted=…
- Decision: scale | iterate | cut
- Lessons: …
```

---

## Anti-patterns (do not do these)

- **Hero-mode coding.** Building before the metric and baseline exist.
- **Vanity metrics.** "We process 1M events/day" — meaningless without the
  business outcome it enables.
- **Shadow IT.** Deploying into the customer's cloud without their security
  reviewer's approval in writing.
- **Demo-ware.** A polished demo that collapses on real data. Always build
  against the customer's data, not a sanitized toy set.
- **Promising ROI you can't measure.** If you can't draw the measurement
  pipeline, don't put a number in the slide.

## When this skill is wrong

Skip the loop if any of:

- The work is internal tooling with no external customer. Use plain
  engineering review.
- The work is a security incident response. Use `systematic-debugging` instead.
- The "customer" is you, and the metric is unblocking yourself. Just build.