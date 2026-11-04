"""The manual downloads folder: <home>/manual/<source>/.

Some sites refuse downloads from scripts, or need a sign-in, so their files are
saved by hand. Each such source has its own folder here; save the file in it and
run `.\\load.bat` (every folder) or `.\\load.bat <source>`, or just `.\\refresh.bat`,
which reads these folders for sources that are loaded by hand and falls back to
them when a download fails. Files are only ever moved to an `old` subfolder,
never deleted.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from worldmodel_data.config import Paths

# Sources whose sites often block scripted downloads: they get a folder too, and a
# refresh falls back to it when the download fails.
FALLBACK = {"rbnz", "mbie_energy", "us_census_voting", "idea_turnout", "powell_thyne", "anthropic_aei", "ilostat_earnings", "un_wup", "nz_corrections", "ms_ai_diffusion",
            "unga_votes", "un_vetoes", "imf_mona", "wto_disputes", "un_treaties", "crisiswatch", "nsidc_sea_ice",
            "celestrak_satcat"}
ABOUT = "_where to get it.txt"
OLD = "old"
_SKIP_SUFFIXES = (".tmp", ".crdownload", ".part", ".partial")


def root(p: Paths) -> Path:
    return p.home / "manual"


def folder(p: Paths, source_id: str) -> Path:
    return root(p) / source_id


def files(path: Path) -> list[Path]:
    """The files to load from a folder: not this module's notes, hidden files, part downloads or subfolders."""
    if not path.is_dir():
        return []
    return sorted(f for f in path.iterdir() if f.is_file() and not f.name.startswith(("_", ".", "~$"))
                  and not f.name.lower().endswith(_SKIP_SUFFIXES) and f.name.lower() != "desktop.ini")


def wanted(connectors: dict) -> list[str]:
    """Sources that get a folder made for them: loaded by hand, or often blocked."""
    return [s for s, cls in connectors.items() if cls.manual or s in FALLBACK]


def prepare(p: Paths, connectors: dict) -> list[str]:
    """Make the folder and one subfolder per source that needs it, each with a note on
    where to get the file. Returns the subfolders made this time."""
    from worldmodel_contract.catalogue import sources

    meta = sources()
    made = []
    root(p).mkdir(parents=True, exist_ok=True)
    (root(p) / "_read me.txt").write_text(
        "Files you download yourself, one folder per source.\r\n\r\n"
        "Save the file in its source's folder (keep the name the site gives it), then run one of:\r\n"
        "  .\\load.bat              loads every folder here that has a new file\r\n"
        "  .\\load.bat SOURCE       loads one folder, for example .\\load.bat rbnz\r\n"
        "  .\\refresh.bat           also reads these folders\r\n\r\n"
        "Loading the same file again changes nothing. When .\\load.bat SOURCE FILE is given a file\r\n"
        "from elsewhere, it is copied in here, and the folder's older files move to its 'old' folder.\r\n"
        "Nothing here is ever deleted.\r\n", encoding="utf-8")
    for source_id in wanted(connectors):
        d = folder(p, source_id)
        if not d.is_dir():
            d.mkdir(parents=True)
            made.append(source_id)
        s = meta.get(source_id)
        cls = connectors[source_id]
        how = ("This source is only loaded by hand." if cls.manual else
               "A refresh downloads this source itself; a file here is used when the site blocks the download.")
        keep = ("Every file here is loaded together (for example one per election, or the current and history files), "
                "so keep them all." if cls.keeps_files else "Keep only the newest file here; move older ones to the 'old' folder.")
        (d / ABOUT).write_text(
            f"{s.name if s else source_id}\r\n\r\nGet it from: "
            f"{s.manual.get if s and s.manual else s.url if s and s.url else '(see the Sources page)'}\r\n"
            f"{s.manual.what if s and s.manual else ''}\r\n\r\n"
            f"{how}\r\n{keep}\r\nThen run: .\\load.bat {source_id}\r\n", encoding="utf-8")
    return made


def keep_copy(p: Paths, source_id: str, file: Path, keeps_files: bool) -> Path:
    """Copy a file loaded from elsewhere into its source's folder, so it stays with the
    others. For a source that loads one file at a time, older files move to 'old'."""
    d = folder(p, source_id)
    d.mkdir(parents=True, exist_ok=True)
    file = Path(file).resolve()
    if file.parent == d.resolve():
        return file
    if not keeps_files:
        for f in files(d):
            if f.name != file.name:
                (d / OLD).mkdir(exist_ok=True)
                shutil.move(str(f), str(d / OLD / f.name))
    target = d / file.name
    shutil.copy2(file, target)
    return target
