"""Thesis tracker data model.

One structured file per holding. A thesis is a falsifiable claim plus the
evidence ledger, red lines, key dates, and decision log that let a session
(or a person) check it mechanically instead of re-reading prose.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date as date_cls
from pathlib import Path

import yaml

THESIS_DIR = Path(__file__).resolve().parent / "theses"

# Lifecycle verdicts. INTACT: claim holds. WEAKENED: evidence mounting
# against, position kept but on watch. BROKEN: thesis dead — exit.
# CLOSED: position exited, kept as history.
VERDICTS = ("INTACT", "WEAKENED", "BROKEN", "CLOSED")


@dataclass
class Evidence:
    date: str            # YYYY-MM-DD
    side: str            # "for" | "against"
    text: str
    source: str = ""


@dataclass
class RedLine:
    trigger: str         # human-readable trigger
    action: str          # what to do when it fires
    price_level: float | None = None  # numeric level when trigger is price-based
    close_based: bool = False  # True: only the closing print matters (e.g. ARWR $60);
                               # intraday touches are not actionable
    suspended_until: str | None = None  # YYYY-MM-DD: line ignored while today <= this date
                               # (judgment pause, e.g. through a binary catalyst);
                               # lapses automatically; the revision lives in decisions[]


@dataclass
class KeyDate:
    date: str            # YYYY-MM-DD
    event: str


@dataclass
class Position:
    shares: float = 0.0
    blended_cost: float = 0.0
    stop: float | None = None
    stop_note: str = ""
    # Option legs (0 = equity position). Extended 2026-10-13 so the thesis
    # board can carry single-leg option positions (SOFI Jan'28 $15C).
    contracts: int = 0
    strike: float | None = None
    expiry: str = ""
    premium_paid: float | None = None   # per-contract premium at entry
    premium_total: float | None = None  # total debit
    breakeven: float | None = None      # underlying price at expiry for flat


@dataclass
class Decision:
    date: str
    text: str
    source: str = ""  # where the decision came from (session, chat, hook)


@dataclass
class Thesis:
    ticker: str
    name: str
    status: str = "INTACT"
    opened: str = ""
    claim: str = ""
    kpis: list[dict] = field(default_factory=list)
    evidence: list[Evidence] = field(default_factory=list)
    red_lines: list[RedLine] = field(default_factory=list)
    key_dates: list[KeyDate] = field(default_factory=list)
    position: Position | None = None
    decisions: list[Decision] = field(default_factory=list)

    # ---- persistence ----
    @classmethod
    def load(cls, path: str | Path) -> "Thesis":
        raw = yaml.safe_load(Path(path).read_text()) or {}
        return cls(
            ticker=raw.get("ticker", ""),
            name=raw.get("name", ""),
            status=raw.get("status", "INTACT"),
            opened=raw.get("opened", ""),
            claim=raw.get("claim", ""),
            kpis=raw.get("kpis", []),
            evidence=[Evidence(**e) for e in raw.get("evidence", [])],
            red_lines=[RedLine(**r) for r in raw.get("red_lines", [])],
            key_dates=[KeyDate(**k) for k in raw.get("key_dates", [])],
            position=Position(**raw["position"]) if raw.get("position") else None,
            decisions=[Decision(**d) for d in raw.get("decisions", [])],
        )

    def to_dict(self) -> dict:
        d: dict = {
            "ticker": self.ticker,
            "name": self.name,
            "status": self.status,
            "opened": self.opened,
            "claim": self.claim,
            "kpis": self.kpis,
            "evidence": [e.__dict__ for e in self.evidence],
            "red_lines": [r.__dict__ for r in self.red_lines],
            "key_dates": [k.__dict__ for k in self.key_dates],
            "decisions": [x.__dict__ for x in self.decisions],
        }
        if self.position:
            d["position"] = self.position.__dict__
        return d

    def save(self, path: str | Path | None = None) -> Path:
        p = Path(path) if path else THESIS_DIR / f"{self.ticker}.yaml"
        p.write_text(yaml.safe_dump(self.to_dict(), sort_keys=False,
                                   allow_unicode=True, width=100))
        return p

    # ---- mutation helpers (append-only ledgers) ----
    def add_evidence(self, side: str, text: str, source: str = "",
                     when: str | None = None) -> Evidence:
        assert side in ("for", "against"), "side must be 'for' or 'against'"
        ev = Evidence(date=when or date_cls.today().isoformat(),
                      side=side, text=text, source=source)
        self.evidence.append(ev)
        return ev

    def log_decision(self, text: str, when: str | None = None) -> Decision:
        dec = Decision(date=when or date_cls.today().isoformat(), text=text)
        self.decisions.append(dec)
        return dec

    def set_verdict(self, verdict: str) -> None:
        assert verdict in VERDICTS, f"verdict must be one of {VERDICTS}"
        self.status = verdict


def load_all(directory: str | Path = THESIS_DIR) -> list[Thesis]:
    """Load every thesis file. Skips EXAMPLE.yaml — the fictional schema
    demo shipped in the public repo; real books keep it as reference only."""
    theses = []
    for p in sorted(Path(directory).glob("*.yaml")):
        if p.stem == "EXAMPLE":
            continue
        theses.append(Thesis.load(p))
    return theses
