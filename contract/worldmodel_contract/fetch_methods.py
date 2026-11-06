"""How each source is fetched, and the rules that switch it when a site changes.

A source can come in up to four ways:

- ``site``: ``.\\refresh.bat`` gets it from the site itself. Depending on the source that is a
  plain download, an API that needs a key in .env, or reading web pages (the scraping tools).
- ``verify``: ``.\\verify.bat`` opens the site in your own browser, where you pass any
  "are you a person?" check; the page or file is saved into var\\manual and loaded.
- ``file``: you save the file into var\\manual\\<source> yourself; refresh and load.bat read it.
- ``auto`` (the default): the site, until it keeps refusing. Then the app switches to
  verify.bat (or your file when the site has no browser route) and tries the site again
  once the saved file is due to be out of date; when the site works again it switches back.

Your choices are kept in the user folder (``fetch_methods.json``, source -> method; ``auto``
is not stored). The data side writes what each source can do and what auto chose to
``warehouse/fetch_methods.json`` after every refresh, so the Data status page can show it.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from worldmodel_contract import local

METHODS = ("auto", "site", "verify", "file")
LABELS = {
    "auto": "Automatic",
    "site": "Refresh from the site",
    "verify": "verify.bat (your browser)",
    "file": "Your file (load.bat)",
}
SITE_KINDS = {
    "download": "download",
    "api": "API with a key",
    "pages": "reads web pages",
}

BLOCKED_IN_A_ROW = 2  # refused this many refreshes in a row -> auto switches away from the site
RETRY_DAYS = 30       # auto tries the site again after this long (or the source's own schedule)

_BLOCKED = re.compile(r"(?i)\b(401|403|429|202)\b|forbidden|unauthori[sz]ed|too many requests|captcha|just a moment|"
                      r"access denied|cloudflare|incapsula|request unsuccessful|verify you are human|are you a robot|"
                      r"checking your browser|bot check|refused|blocked")
_GONE = re.compile(r"(?i)\b(404|410)\b|not found|no longer (?:offered|available)|link is gone")
_NETWORK = re.compile(r"(?i)timed? ?out|timeout|connect(?:ion)? (?:error|reset|refused by peer)|name resolution|"
                      r"getaddrinfo|temporar(?:y|ily)|\b50[0-4]\b|server error|ssl|certificate|network")


def classify(error: str) -> str:
    """What a failed download says about the site: "blocked" (it turns programs away),
    "gone" (the address no longer exists), "network" (try again later) or "changed"
    (the site answered but not with what the loader expects: its layout or file changed)."""
    e = error or ""
    if _GONE.search(e):
        return "gone"
    if _BLOCKED.search(e):
        return "blocked"
    if _NETWORK.search(e):
        return "network"
    return "changed"


def choices_path(root: Path | None = None) -> Path:
    import os
    base = root / "user" if root and not os.environ.get("WORLDMODEL_USER_DIR") else local.user_dir()
    return base / "fetch_methods.json"


def state_path(root: Path | None = None) -> Path:
    return (root or local.home()) / "warehouse" / "fetch_methods.json"


def read_choices(root: Path | None = None) -> dict[str, str]:
    """Your choices: source -> site, verify or file (sources left on Automatic are absent)."""
    try:
        data = json.loads(choices_path(root).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {k: v for k, v in data.items() if isinstance(k, str) and v in METHODS and v != "auto"} \
        if isinstance(data, dict) else {}


def set_choice(source_id: str, method: str, root: Path | None = None) -> dict[str, str]:
    if method not in METHODS:
        raise ValueError(f"method must be one of {', '.join(METHODS)}")
    out = read_choices(root)
    if method == "auto":
        out.pop(source_id, None)
    else:
        out[source_id] = method
    path = choices_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(out, indent=1, sort_keys=True), encoding="utf-8")
    tmp.replace(path)
    return out


def read_state(root: Path | None = None) -> dict:
    """What the data side last wrote: {"written_at", "sources": {id: {"can", "kind", "auto",
    "since", "why", "refused", "last_kind", "last_error", "retry_from"}}}."""
    try:
        data = json.loads(state_path(root).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def effective(choice: str | None, auto: str | None, can: list[str]) -> str:
    """The method in use: your choice when it is one the source can do, else what auto chose,
    else the site (or your file for a source that is only ever loaded by hand)."""
    if choice in can and choice != "auto":
        return choice
    if auto in can:
        return auto
    return "site" if "site" in can else "file"
