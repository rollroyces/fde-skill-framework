# Business Discovery Template — Technical Stakeholder Interview

> Use this template **with** `fde-workflow` during the Discovery phase. Every
> section must be filled in before Architecture begins. "TBD" is a blocker —
> it means the answer was not given in the interview, not that we are allowed
> to guess.

---

## 0. Engagement metadata

| Field            | Value                                                                                |
|------------------|--------------------------------------------------------------------------------------|
| Customer         | Legal entity name (not the project codename)                                         |
| Engagement codename | Short internal name used in repos, dashboards                                       |
| Sponsor          | Name, title, email, phone, timezone                                                  |
| Daily technical contact | Name, role, response-time SLA, channel (Slack/Teams/email)                       |
| Security reviewer | Name + team, expected turnaround on review requests                       |
| Legal/procurement | Name + expected turnaround on contract addenda                       |
| Discovery start  | YYYY-MM-DD                                                                            |
| Target GA         | YYYY-MM-DD (negotiated, not assumed)                                                  |

## 1. The business metric (M)

The single number we are paid to move. Everything in the build exists to move
this number.

- **What is the metric?** Use the customer's words, then restate in ours.
- **How is it measured today?** Dashboard URL, report name, SQL query — we
  need to be able to re-run it.
- **Owner of the metric inside the customer's org?** (Finance? Ops? Eng? VP X?)
- **Current value (baseline):**
- **Target value at GA:**
- **Target date:**
- **What moves the metric outside our work?** Seasonal effects, other
  in-flight projects, regulatory changes. List them so the post-mortem
  doesn't blame us for someone else's lever.

If the customer cannot name a single metric, the engagement is not ready.
Stop Discovery. Help them pick one. Re-scope if needed.

## 2. SLA targets (the contract envelope)

These are the numbers we put in writing. Anything we cannot commit to must
be flagged here before build.

| Surface             | p50 | p95 | p99 | Availability | Error budget |
|---------------------|-----|-----|-----|--------------|--------------|
| (e.g. quoting API)  |     |     |     |              |              |
| (e.g. webhook)      |     |     |     |              |              |
| (e.g. batch job)    |     |     |     |              |              |

- **Where does the SLA get measured?** Whose monitoring, whose alerts?
- **What happens on a breach?** SLA credits, escalation path, RCA SLA.
- **Are there burst / seasonality expectations?** (Quarter close, Black Friday,
  Lunar New Year — name the dates.)
- **Are there quiet hours we can do deploys?** When, in the customer's TZ.

## 3. Constraints (doors that are closed)

Anything that prevents a design choice. Surface these now so we don't design
something we can't ship.

- **Data residency:** regions where data may live, may not live.
- **Compliance regime:** GDPR, HIPAA, PCI-DSS, SOC 2, PIPL, FedRAMP, ITAR,
  … List everything that applies, not just the obvious one.
- **Vendor allow-list / block-list.** Approved identity, payment, AI,
  observability vendors.
- **Tech stack constraints.** Languages, frameworks, deployment target the
  customer requires (or forbids).
- **Budget ceiling.** CapEx, OpEx, or both. Tied to a quarterly cycle?
- **Fixed launch date.** Hard date (regulatory deadline, contract
  commitment) or aspirational?
- **Procurement timeline.** How long does a new vendor take to be approved?

## 4. Stakeholder map & communication cadence

Without named people and channels, status updates vanish into inboxes.

| Role              | Name | Channel | Cadence we owe them |
|-------------------|------|---------|---------------------|
| Sponsor           |      |         | Daily status, weekly demo, milestone reviews |
| Daily technical   |      |         | Pair sessions, blockers within 1 business day |
| Security reviewer |      |         | Pre-Architecture review, pre-deploy review |
| Legal/procurement |      |         | Contract changes, addenda |
| End user (sample) |      |         | User research, beta, feedback loop |

## 5. ROI model inputs (sourced, not guessed)

The ROI model needs three numbers the customer signs off on.

1. **Value per unit of M.** If M is hours saved, what's the loaded cost of
   one hour? Who told us?
2. **Volume.** How many transactions / users / requests per year will M
   multiply across?
3. **Cost ceiling.** Engineering hours we're allowed to spend, infra budget,
   vendor budget. Numbers, not ranges.

Without all three, the ROI model is a wish list. Don't ship on a wish list.

## 6. Open questions (for follow-up)

List everything that came out of the interview that does not block
Architecture but must be answered before GA. Assign an owner and a date.

- [ ] … (owner: …, due: …)

## 7. Anti-discovery (questions that should have been asked earlier)

If we discover during Architecture or Build that any of these were missing,
that's a process failure worth flagging in the engagement retrospective.

- Did the sponsor understand they'd owe us a daily contact? Did the daily
  contact understand they'd owe us same-day responses during build?
- Did we get a written list of compliance regimes, or were they named in
  passing?
- Did we get the actual measurement pipeline for M, or just "the dashboard
  shows it"?
- Did we confirm who owns the cost of vendor onboarding (us or them)?

---

## Sign-off

- [ ] Sponsor agrees the metric M, baseline, target, and date are correct.
- [ ] Sponsor agrees the SLA envelope is correct.
- [ ] FDE lead agrees the constraints list is complete.
- [ ] Both sides agree on the ROI inputs.

Signed: ________________________  Date: ____________

Once this is signed, copy it into `engagements/<customer>-<date>.md` as the
**Discovery** section. Architecture begins.