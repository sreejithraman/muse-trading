# packages/thesis — thesis tracker

The backbone of the trading operation: every holding's *falsifiable* claim,
the evidence ledger, red lines, key dates, and decision log — as
machine-checkable state instead of session prose.

## Concept

A thesis is not "I like this stock." It is:

- **claim** — one paragraph, falsifiable
- **kpis** — named metrics with target vs current (the scoreboard)
- **evidence** — append-only, tagged `for` / `against`, with sources
- **red_lines** — trigger → action pairs; price triggers carry a numeric
  `price_level` so `check.py` can measure distance mechanically
- **key_dates** — catalysts with dates (earnings, FDA, webinars)
- **position** — shares, blended cost, stop (with notes on exceptions
  like ARWR's close-below-$60 rule)
- **decisions** — append-only log of what was done and why
- **status** — `INTACT` / `WEAKENED` / `BROKEN` / `CLOSED`

Borrowed schema pattern from investskill/yourich agent-skill conventions;
built bespoke because nothing off-the-shelf fits an agent-run book.

## Usage

```bash
cd packages/thesis
python3 check.py            # status board vs live prices
python3 check.py --offline  # theses only
```

`check.py` flags any holding within 5% above a price red line (⚠) or
below one (✖), and prints the next key date per thesis. It is read-only:
it never touches the brokerage account beyond quotes.

## Private data

Real thesis files carry live positions, costs, and stops — they stay in
your local `theses/` directory and are **never pushed** (see the repo
`.gitignore`). The public repo ships only `theses/EXAMPLE.yaml`, a
fictional file showing the schema. Clone the repo, copy
`EXAMPLE.yaml` to `<TICKER>.yaml`, and fill in your own book.

## Editing

Theses are hand-editable YAML in `theses/`. In sessions, prefer the
model helpers:

```python
from models import Thesis
t = Thesis.load("theses/SMMT.yaml")
t.add_evidence("for", "ESMO data beat expectations", source="…")
t.log_decision("Trimmed 25% into strength")
t.set_verdict("WEAKENED")
t.save()
```

## Rules

- Evidence is append-only: never rewrite history, add a new entry.
- A red line firing means the action fires — no re-debate in the moment.
- `WEAKENED` is a watch state, not an action; `BROKEN` means exit.
- Keep one file per ticker; delete nothing — closed theses stay as history.
