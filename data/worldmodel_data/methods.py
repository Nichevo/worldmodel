"""Which way each source is fetched (see worldmodel_contract.fetch_methods), and the automatic
switch: a site that refuses refreshes in a row, or whose address is gone, is moved to
verify.bat or to your file, tried again once that is due, and moved back when it works."""

from __future__ import annotations

import json
from datetime import timedelta

from worldmodel_contract import fetch_methods as fm

from worldmodel_data.config import Paths
from worldmodel_data.vintage_store import now_utc


def verify_sources() -> set[str]:
    from worldmodel_data import verify
    return {t.source for t in verify.targets()}


def scraped() -> set[str]:
    from worldmodel_contract import catalogue
    return {s.id for s in catalogue.sources().values() if s.scraper}


def can(source_id: str, cls, verify_ids: set[str] | None = None) -> list[str]:
    from worldmodel_data import manual

    out = []
    if not cls.manual:
        out.append("site")
    if source_id in (verify_ids if verify_ids is not None else verify_sources()):
        out.append("verify")
    if cls.manual or source_id in manual.FALLBACK:
        out.append("file")
    return out


def site_kind(source_id: str, cls, scraped_ids: set[str] | None = None) -> str | None:
    if cls.manual:
        return None
    if source_id in (scraped_ids if scraped_ids is not None else scraped()):
        return "pages"
    return "api" if cls.needs_env else "download"


class Methods:
    """The choices and automatic state for one refresh; `save` writes the state file."""

    def __init__(self, p: Paths, connectors: dict):
        self.p = p
        self.connectors = connectors
        self.choices = fm.read_choices(p.home)
        self.state = fm.read_state(p.home).get("sources", {})
        v, s = verify_sources(), scraped()
        self.can = {sid: can(sid, cls, v) for sid, cls in connectors.items()}
        self.kind = {sid: site_kind(sid, cls, s) for sid, cls in connectors.items()}

    def entry(self, sid: str) -> dict:
        return self.state.setdefault(sid, {"auto": "site"})

    def chosen(self, sid: str) -> str | None:
        """Your own choice for the source, when it is one the source can do."""
        c = self.choices.get(sid)
        return c if c in self.can.get(sid, []) else None

    def method(self, sid: str) -> str:
        return fm.effective(self.choices.get(sid), self.entry(sid).get("auto"), self.can.get(sid, []))

    def label(self, sid: str) -> str:
        how = {"verify": "verify.bat", "file": "your file"}.get(self.method(sid), "the site")
        if self.chosen(sid):
            return f"set to {how} on the Data status page"
        e = self.entry(sid)
        return f"switched to {how} automatically on {e.get('since', '?')[:10]}: {e.get('why', '')}".rstrip(": ")

    def retry_due(self, sid: str) -> bool:
        """Auto moved this source off the site: is it time to try the site once more?"""
        e = self.entry(sid)
        when = e.get("retry_from")
        return bool(when) and now_utc().date().isoformat() >= when[:10]

    def _away(self, sid: str, to: str, why: str) -> None:
        e = self.entry(sid)
        cls = self.connectors[sid]
        days = cls.fetch_every_days or fm.RETRY_DAYS
        now = now_utc()
        if e.get("auto") != to:
            e.update(auto=to, since=now.isoformat(), why=why)
        e["retry_from"] = (now + timedelta(days=max(days, 7))).date().isoformat()

    def outcome(self, sid: str, ok: bool, error: str = "", tried_site: bool = True) -> str | None:
        """Note how the site did; returns a sentence when the automatic choice changed."""
        if not tried_site or sid not in self.can:
            return None
        e = self.entry(sid)
        if ok:
            was = e.get("auto", "site")
            e.update(refused=0, last_kind=None, last_error=None, retry_from=None)
            if was != "site":
                e.update(auto="site", since=now_utc().isoformat(), why="the site worked again")
                return "the site worked again: back to refreshing from it"
            return None
        kind = fm.classify(error)
        e.update(last_kind=kind, last_error=(error or "")[:300])
        e["refused"] = e.get("refused", 0) + 1 if kind == "blocked" else 0
        can_ = self.can[sid]
        to = "verify" if "verify" in can_ else "file" if "file" in can_ else None
        if e.get("auto", "site") != "site":  # a retry that failed: stay away until the next one
            self._away(sid, e["auto"], e.get("why", ""))
            return None
        if to is None:
            return None
        if kind == "blocked" and e["refused"] >= fm.BLOCKED_IN_A_ROW:
            self._away(sid, to, f"the site refused {e['refused']} refreshes in a row ({(error or '')[:80]})")
        elif kind == "gone" and "file" in can_:
            to = "file"
            self._away(sid, to, f"the download address is gone ({(error or '')[:80]})")
        else:
            return None
        how = "verify.bat" if to == "verify" else "your file in var\\manual\\" + sid
        return f"switched to {how} automatically"

    def save(self) -> None:
        out = {}
        for sid in self.connectors:
            e = dict(self.state.get(sid) or {"auto": "site"})
            e.update(can=self.can[sid], kind=self.kind[sid], method=self.method(sid))
            out[sid] = e
        path = fm.state_path(self.p.home)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"written_at": now_utc().isoformat(), "sources": out}, indent=1), encoding="utf-8")
        tmp.replace(path)

