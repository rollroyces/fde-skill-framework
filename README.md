# FDE Skill Framework

A production-grade Forward Deployed Engineer (FDE) skill for Hermes. Enforces
a four-phase loop — **Discovery → Architecture → Build → ROI Evaluation** —
with hard gates at each transition so engineering work always ties back to a
named customer, a measurable business metric, and a contracted SLA.

## What's in this repo

```
.
├── .hermes/
│   └── skills/
│       └── fde-workflow.md         # The four-phase loop, anti-patterns, exit gates
├── .hermes.md                       # Project-wide business metrics, SLA defaults, tech stack contract
├── fde/                             # CLI wrapper (stdlib only; zero install)
│   ├── __init__.py                  #   subcommands: score, init, log-week, watch
│   └── __main__.py                  #   entry point for `python -m fde`
├── references/
│   └── business-discovery-template.md  # Stakeholder interview template (used in Discovery phase)
├── tests/
│   ├── test_fde_eval.py            # Black-box evaluator: scores an engagement log on 4 axes
│   └── test_cli.py                  # CLI smoke tests — guarantee CLI uses same evaluator
└── README.md                        # This file
```

## Use the CLI

The CLI wraps the same `evaluate()` function the pytest suite asserts
against, so scores cannot drift between the two surfaces.

```bash
# Scaffold a new engagement file (markdown + starter log)
python -m fde init globex --date 2026-09-16 --dir engagements/

# Append weekly measurements (interactive prompts)
python -m fde log-week engagements/globex-2026-09-16.log.json

# Score it
python -m fde score engagements/globex-2026-09-16.log.json
# →  ✓ SCALE   globex-2026-09-16  →  overall 87.3 / 100
#    Business  100.0  [████████████████████]  discovery & ROI
#    SLA        90.0  [██████████████████··]  0 p99 / 0 err / 1 avail breaches
#    ...

# CI-friendly one-shot: exit non-zero if decision is `cut`
python -m fde watch engagements/globex-2026-09-16.log.json --once --strict

# Live dashboard: re-score on every save
python -m fde watch engagements/globex-2026-09-16.log.json --interval 1.0
```

The CLI reuses the harness's `evaluate()` directly — see
`fde/__init__.py` (`sys.path` bootstrap + `import test_fde_eval as _harness`)
and the matching tests in `tests/test_cli.py`.

## Install into Hermes

The skill is designed to be loaded by Hermes from a local checkout. Two
options:

### A. Per-repo install (recommended)

The files already live at the right paths inside this repo. From the Hermes
desktop app or CLI in this project, the skill auto-loads from `.hermes/skills/`
and the project config from `.hermes.md`.

```bash
# Inside this repo
hermes skills list
# You should see: fde-workflow

hermes status
# Should print the metrics from .hermes.md
```

### B. Global install

Copy the skill into your global Hermes skills directory so it's available in
every project:

```bash
mkdir -p ~/.hermes/skills
cp .hermes/skills/fde-workflow.md ~/.hermes/skills/
cp .hermes.md ~/                                # optional global defaults
cp -r references ~/                              # global discovery template
```

> **Note.** The per-repo version is preferred — `.hermes.md` and the
> references are project-specific (your SLA targets, your constraints). The
> skill file (`fde-workflow.md`) is generic and safe to globalize.

## Use the loop

In any Hermes session in this project, invoke the FDE skill explicitly when
the work is FDE-shaped (named customer, external delivery, contract SLA):

```
/skill fde-workflow
```

Hermes will refuse to write code until the Discovery gate is met. Follow the
checklist:

1. Open `references/business-discovery-template.md` and fill it out **with**
   the sponsor. Don't paraphrase, don't guess.
2. Once signed, copy the Discovery block into
   `engagements/<customer>-<date>.md`.
3. Draft the 1-page solution brief, then send it to the sponsor before
   touching code.
4. Build a vertical slice in the customer's environment first. No mocks
   across the trust boundary.
5. Run ROI scoring via the harness after every meaningful ship.

## Run the evaluation harness

The harness scores an engagement log against the contract defined in
`.hermes.md`. It is a black-box evaluator — feed it a JSON file and it
returns a 0-100 score and a `scale | iterate | cut` decision.

```bash
# Run the bundled fixtures (smoke test + sample output)
python tests/test_fde_eval.py

# Run the full unittest suite (harness + CLI wrapper)
python -m unittest discover -s tests -v

# Score a real engagement log
python -m fde score path/to/engagement.json
```

Expected JSON shape for an engagement log is documented at the top of
`tests/test_fde_eval.py`.

### What the four axes measure

| Axis              | Weight | What it catches                                              |
|-------------------|--------|--------------------------------------------------------------|
| Business criteria | 35%    | Was Discovery done? Are metric, baseline, target, ROI sourced? |
| SLA compliance    | 30%    | p99, error rate, availability vs contracted targets post-GA  |
| Latency trend     | 15%    | Is p99 stable or improving over the post-GA weeks?            |
| API error rate    | 20%    | Mean error rate vs the customer's error budget               |

### Decision rule

- **Scale** (overall ≥ 85, business ≥ 90): hit the target, ROI positive →
  expand.
- **Iterate** (50 ≤ overall < 85, business ≥ 60): hit direction, miss
  number → one bounded iteration.
- **Cut** (overall < 50, or business < 60): ROI negative or blocked →
  wind down cleanly.

The harness exits non-zero if the smoke test fails, so wire it into CI:

```yaml
# .github/workflows/fde-eval.yml
- run: python tests/test_fde_eval.py tests/fixtures/most_recent.json
```

## Contributing

This framework is opinionated. Changes that loosen a gate, soften an
anti-pattern, or remove a hard constraint need:

1. A one-paragraph rationale in the PR description.
2. Sign-off from at least one FDE lead.
3. An updated `.hermes.md` if business metrics or SLA targets shift.

## License

Internal use. Adapt the framework to your engagement model before sharing
externally.