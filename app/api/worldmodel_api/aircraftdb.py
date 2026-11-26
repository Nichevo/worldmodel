"""What each plane is, from its 24-bit ICAO address: registration, type (B738, EC45, ...), maker and
model, how the map draws it, whether it is military, and the country that issued the address (its flag).

- Registrations and types: the aircraft database tar1090 uses (Mictronics' database, about 650,000
  aircraft, refreshed weekly), https://github.com/wiedehopf/tar1090-db, downloaded once a month
  (about 9 MB) into <home>/live/planes/aircraft.csv.gz (Settings > Transport: "Plane types").
- Type designators -> maker, model and map group, and address blocks -> country: aircraft_types.py
  (Virtual Radar Server standing data, CC0), kept in the code.

Most planes don't send an ADS-B category to OpenSky, so without this nearly all of them were
"Type not sent".
"""

from __future__ import annotations

import csv
import gzip
import logging
import threading
import time
from functools import lru_cache
from pathlib import Path

import httpx
import numpy as np

from worldmodel_api.aircraft_types import BLOCKS, TYPES

log = logging.getLogger(__name__)

URL = "https://raw.githubusercontent.com/wiedehopf/tar1090-db/csv/aircraft.csv.gz"
REFRESH = 30 * 86400   # download again when the file is older than this
RETRY = 6 * 3600       # after a failed download


class AircraftDb:
    def __init__(self, folder: Path) -> None:
        self.file = folder / "aircraft.csv.gz"
        self.lock = threading.Lock()
        # sorted addresses and, in the same order, registration, index into self.types, military
        self.keys = np.zeros(0, dtype=np.uint32)
        self.regs = np.zeros(0, dtype="S10")
        self.kinds = np.zeros(0, dtype=np.uint16)
        self.mil = np.zeros(0, dtype=bool)
        self.types: list[str] = [""]
        self.loaded_at = 0.0
        self.tried = 0.0
        self.note: str | None = None
        self.loading = False

    # ------------------------------------------------------------------ the file
    def due(self) -> bool:
        try:
            age = time.time() - self.file.stat().st_mtime
        except OSError:
            age = float("inf")
        return age > REFRESH and time.time() - self.tried > RETRY

    def download(self) -> None:
        """Fetch the database (in the background thread) and load it."""
        self.tried = time.time()
        try:
            with httpx.Client(timeout=120, follow_redirects=True, headers={"User-Agent": "worldmodel (personal research tool)"}) as client:
                r = client.get(URL)
                r.raise_for_status()
            gzip.decompress(r.content)  # a broken download is not kept
            self.file.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.file.with_suffix(".tmp")
            tmp.write_bytes(r.content)
            tmp.replace(self.file)
            self.note = None
            self.load(force=True)
        except (httpx.HTTPError, OSError, EOFError, gzip.BadGzipFile) as exc:
            self.note = f"Could not download the aircraft database ({exc.__class__.__name__}); trying again in 6 hours."
            log.warning("aircraft database: %s", exc)

    def load(self, force: bool = False) -> bool:
        """Read the file into memory (once, or again after a download)."""
        if len(self.keys) and not force:
            return True
        if not self.file.exists():
            return False
        keys, regs, kinds, mil = [], [], [], []
        types: dict[str, int] = {"": 0}
        try:
            with gzip.open(self.file, "rt", encoding="utf-8", errors="replace", newline="") as fh:
                for row in csv.reader(fh, delimiter=";"):
                    if len(row) < 4 or not (row[1] or row[2]):
                        continue
                    try:
                        key = int(row[0], 16)
                    except ValueError:
                        continue
                    keys.append(key)
                    regs.append(row[1].strip()[:10].encode("ascii", "replace"))
                    kinds.append(types.setdefault(row[2].strip().upper(), len(types)))
                    mil.append(row[3][:1] == "1")
        except (OSError, EOFError, gzip.BadGzipFile, csv.Error) as exc:
            log.warning("aircraft database: could not read %s: %s", self.file, exc)
            return False
        order = np.argsort(np.array(keys, dtype=np.uint32), kind="stable")
        with self.lock:
            self.keys = np.array(keys, dtype=np.uint32)[order]
            self.regs = np.array(regs, dtype="S10")[order]
            self.kinds = np.array(kinds, dtype=np.uint16 if len(types) < 65_000 else np.uint32)[order]
            self.mil = np.array(mil, dtype=bool)[order]
            self.types = list(types)
            self.loaded_at = time.time()
        log.info("aircraft database: %s aircraft", f"{len(keys):,}")
        return True

    # ------------------------------------------------------------------ look-ups
    def ensure_loaded(self) -> None:
        """Load the saved file in the background the first time a plane is looked up."""
        if len(self.keys) or self.loading or not self.file.exists():
            return
        self.loading = True

        def run():
            try:
                self.load()
            finally:
                self.loading = False

        threading.Thread(target=run, daemon=True, name="aircraft-db-load").start()

    def find(self, icao24: str | None) -> dict:
        """What is known about one address: reg, type, model, group (or None), military, flag."""
        self.ensure_loaded()
        try:
            key = int(str(icao24 or ""), 16)
        except ValueError:
            return {}
        out = dict(_block(key))
        hit = None
        with self.lock:
            i = int(np.searchsorted(self.keys, np.uint32(key)))  # same dtype: a Python int would copy the whole array each call
            if i < len(self.keys) and int(self.keys[i]) == key:
                hit = (self.regs[i].decode("ascii", "replace"), self.types[int(self.kinds[i])], bool(self.mil[i]))
        if hit:
            reg, typ, mil = hit
            known = TYPES.get(typ)
            out.update(reg=reg or None, type=typ or None, model=known[1] if known else None,
                       group=known[0] if known and known[0] != "unknown" else None)
            out["military"] = out.get("military") or mil
        return out

    def status(self) -> dict:
        try:
            st = self.file.stat()
            on_disk = {"bytes": st.st_size, "downloaded": int(st.st_mtime)}
        except OSError:
            on_disk = {"bytes": 0, "downloaded": None}
        return {**on_disk, "aircraft": len(self.keys), "note": self.note}


@lru_cache(maxsize=100_000)
def _block(key: int) -> tuple:
    """The country (ISO two letters) that issued an address, and whether the block is military.
    The smallest block holding the address wins (military blocks sit inside a country's)."""
    best = None
    for lo, hi, iso, mil in BLOCKS:
        if lo <= key <= hi and (best is None or hi - lo < best[1] - best[0]):
            best = (lo, hi, iso, mil)
    if not best:
        return ()
    return tuple(x for x in (("flag", best[2] if best[2] != "ZZ" else None), ("military", best[3])))


def flag_of(icao24: str | None) -> str | None:
    try:
        return dict(_block(int(str(icao24 or ""), 16))).get("flag")
    except ValueError:
        return None


# ----------------------------------------------------------------------------- airline logos
LOGOS = ("https://raw.githubusercontent.com/Jxck-S/airline-logos/main/flightaware_logos/{}.png",
         "https://raw.githubusercontent.com/Jxck-S/airline-logos/main/radarbox_logos/{}.png")
LOGO_MISS_AGAIN = 30 * 86400  # an airline with no logo is asked again after this
_logo_lock = threading.Lock()


def logo(folder: Path, code: str) -> bytes | None:
    """An airline's logo (PNG) by its three-letter ICAO code: from the folder, else fetched once
    and kept. A missing one is remembered (an empty file) and asked again after 30 days."""
    code = code.upper()
    if len(code) != 3 or not code.isalpha():
        return None
    path = folder / f"{code}.png"
    try:
        st = path.stat()
        if st.st_size:
            return path.read_bytes()
        if time.time() - st.st_mtime < LOGO_MISS_AGAIN:
            return None
    except OSError:
        pass
    with _logo_lock:  # one fetch at a time, so a map full of new airlines doesn't fire dozens at once
        got = b""
        with httpx.Client(timeout=15, headers={"User-Agent": "worldmodel (personal research tool)"}) as client:
            for url in LOGOS:
                try:
                    r = client.get(url.format(code))
                except httpx.HTTPError:
                    return None  # not reachable now: not remembered as missing
                if r.status_code == 200 and r.content[:8] == b"\x89PNG\r\n\x1a\n":
                    got = r.content
                    break
        try:
            folder.mkdir(parents=True, exist_ok=True)
            path.write_bytes(got)
        except OSError as exc:
            log.warning("airline logo %s: could not save: %s", code, exc)
        return got or None
