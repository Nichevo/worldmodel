"""worldmodel-data: the command line for the data side.

    worldmodel-data fetch un_wpp            download a source and store a new vintage
    worldmodel-data fetch imf_weo --from DIR   ... or load files you downloaded yourself
    worldmodel-data build                   build, validate and swap in a new warehouse
    worldmodel-data refresh                 fetch every active source, then build
    worldmodel-data upgrade                 rebuild from stored data if the live build is an older format
    worldmodel-data status                  vintages, live build, last report, disk use
    worldmodel-data free-space              delete old raw downloads (keeps 2 per source)
    worldmodel-data validate                check the catalogues and re-run gates on the live build
    worldmodel-data keys                    which API keys are set (values never printed)
    worldmodel-data export NAME             write a named stream to CSV, Parquet or JSON
    worldmodel-data publish PATH            copy the live build somewhere (e.g. the app's sample)
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from datetime import date, datetime
from importlib import resources
from pathlib import Path
from typing import Optional

import duckdb
import typer
import yaml

from worldmodel_contract import catalogue, local
from worldmodel_contract.queries import series_sql, stream_query
from worldmodel_data import build as build_mod
from worldmodel_data import gates, monitor
from worldmodel_data.config import load_env, paths
from worldmodel_data.connectors import CONNECTORS
from worldmodel_data.vintage_store import VintageStore, now_utc

app = typer.Typer(add_completion=False, no_args_is_help=True, help="Worldmodel data pipeline.")


@app.callback()
def main(
    home: Optional[Path] = typer.Option(None, "--home", envvar="WORLDMODEL_HOME",
                                        help="Data folder (default ./var)."),
    env_file: Optional[Path] = typer.Option(None, "--env-file", help="Path to .env (default: search upwards)."),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
):
    load_env(env_file)
    if home:
        os.environ["WORLDMODEL_HOME"] = str(home)
    logging.basicConfig(level=logging.DEBUG if verbose else logging.INFO, format="%(levelname)s %(message)s")
    for noisy in ("httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


@app.command()
def fetch(
    source: str = typer.Argument(..., help=f"One of: {', '.join(CONNECTORS)}"),
    from_path: Optional[Path] = typer.Option(None, "--from", help="Use local files instead of downloading."),
    release: Optional[str] = typer.Option(None, help="Release label, e.g. 2024 (WPP) or 2025-10 (WEO)."),
):
    """Fetch one source and store it as a new vintage."""
    if source not in CONNECTORS:
        raise typer.BadParameter(f"unknown source {source}; choose from {', '.join(CONNECTORS)}")
    manifest, is_new = CONNECTORS[source]().ingest(VintageStore(paths()), from_path, release)
    word = "stored new vintage" if is_new else "unchanged, already have vintage"
    typer.echo(f"{source}: {word} {manifest.vintage} ({manifest.row_count:,} rows)")


@app.command()
def build(allow_shrink: bool = typer.Option(False, help="Do not fail when a series loses rows.")):
    """Build a new warehouse, run the validation gates and swap it in if they pass."""
    _build_and_log(allow_shrink, {"kind": "build", "started_at": now_utc().isoformat(), "sources": []})


def _build_and_log(allow_shrink: bool, record: dict) -> None:
    """Build, then append the refresh log record: checks, rows changed per source, disk use."""
    p = paths()
    previous = p.current_build()
    try:
        result = build_mod.build(p, allow_shrink=allow_shrink)
    except build_mod.BuildFailed as exc:
        typer.echo(f"BUILD FAILED: {exc}", err=True)
        if exc.report:
            typer.echo(exc.report.read_text(), err=True)
        _log(p, {**record, "status": "failed", "error": str(exc).splitlines()[0],
                 "build_id": exc.report.stem if exc.report else None})
        raise typer.Exit(1)
    counts = {s: sum(c.status == s for c in result.checks) for s in ("pass", "warn", "fail", "skip")}
    changes = monitor.diff_builds(result.path, previous)
    by_source = {s["source_id"]: s for s in record["sources"]}
    for source_id, ch in changes.items():
        by_source.setdefault(source_id, {"source_id": source_id}).update(ch)
    storage = monitor.storage_lines(p)
    with result.report.open("a", encoding="utf-8") as fh:
        fh.write("\n## Storage\n\n" + "\n".join(f"- {line}" for line in storage) + "\n")
    _log(p, {**record, "status": "ok", "build_id": result.build_id, "checks": counts,
             "sources": list(by_source.values())})
    typer.echo(f"build {result.build_id} is live: {counts['pass']} checks passed, {counts['warn']} warnings, "
               f"{counts['skip']} skipped. Report: {result.report}")
    for line in storage:
        typer.echo(line)


def _log(p, record: dict) -> None:
    record["finished_at"] = now_utc().isoformat()
    record["disk"] = local.disk_usage(p.home)
    try:
        monitor.append(p, record)
    except OSError as exc:  # the log is a nice-to-have; never fail a refresh over it
        typer.echo(f"could not write the refresh log: {exc}", err=True)


LARGE_DOWNLOAD = 50 * 1024 ** 2  # skipped once the data folder is at its limit


@app.command()
def refresh(allow_shrink: bool = typer.Option(False)):
    """Fetch every active source, then build. Logs what each source brought in."""
    p = paths()
    store = VintageStore(p)
    record = {"kind": "refresh", "started_at": now_utc().isoformat(), "sources": []}
    full = local.storage(p.home)["limits"][0]["level"] == "full"
    if full:
        typer.echo("The data folder is at its size limit: sources with large downloads are skipped this time. "
                   "Free up space on the Data status page or raise the limit in Settings.")
    for name in _restage_stale(store):
        typer.echo(f"{name}: staged again with the fixed loader")
    failed = []
    for source_id, cls in CONNECTORS.items():
        last = store.latest(source_id)
        size = sum(f.get("bytes", 0) for f in last.files) if last else 0
        entry = {"source_id": source_id}
        record["sources"].append(entry)
        if full and size > LARGE_DOWNLOAD:
            entry.update(status="skipped", note=f"limit reached; last download {size / 1024 ** 2:.0f} MB")
            typer.echo(f"{source_id}: skipped (data folder at its limit)")
            continue
        wait = _not_due(cls, last)
        if wait:
            entry.update(status="skipped", vintage=last.vintage, note=wait)
            typer.echo(f"{source_id}: skipped ({wait})")
            continue
        conn = cls()
        t0 = time.monotonic()
        try:
            manifest, is_new = conn.ingest(store)
        except Exception as exc:  # one source failing should not stop the others
            entry.update(status="error", error=str(exc), seconds=round(time.monotonic() - t0, 1),
                         download_bytes=conn.downloaded_bytes)
            typer.echo(f"{source_id}: FAILED {exc}", err=True)
            failed.append(source_id)
            continue
        entry.update(status="new" if is_new else "unchanged", vintage=manifest.vintage,
                     seconds=round(time.monotonic() - t0, 1), download_bytes=conn.downloaded_bytes,
                     vintage_rows=manifest.row_count)
        typer.echo(f"{source_id}: {'new vintage' if is_new else 'unchanged'} {manifest.vintage}")
    _build_and_log(allow_shrink, record)
    if failed:
        typer.echo(f"Some sources failed to fetch and kept their previous data: {', '.join(failed)}", err=True)
        raise typer.Exit(1)


def _not_due(cls, last) -> str | None:
    """Why a refresh leaves a source alone this time: a closed archive already stored,
    or one fetched on a schedule (monthly, say) whose time has not come."""
    if last is None:
        return None
    if cls.frozen:
        return f"archive that no longer changes; stored as {last.vintage}"
    if cls.fetch_every_days:
        age = now_utc() - datetime.fromisoformat(last.retrieved_at)
        if age.days < cls.fetch_every_days:
            return f"fetched {age.days} days ago; fetched every {cls.fetch_every_days} days"
    return None


@app.command()
def upgrade():
    """After a code update: stage again any stored vintage whose loader has since been fixed,
    and if that happened, or the live warehouse was built in an older format than this code
    reads, build it again from the data already downloaded (nothing is fetched)."""
    from worldmodel_contract import SCHEMA_VERSION, is_compatible

    restaged = _restage_stale(VintageStore(paths()))
    if restaged:
        typer.echo(f"Staged again with fixed loaders: {', '.join(restaged)}")
    current = paths().current_build()
    if not current:
        typer.echo("No live warehouse yet; the app uses its sample until the first refresh.")
        return
    con = duckdb.connect(str(current), read_only=True)
    try:
        found = dict(con.execute("SELECT key, value FROM meta").fetchall()).get("schema_version", "0.0.0")
    finally:
        con.close()
    if is_compatible(found, SCHEMA_VERSION) and not restaged:
        typer.echo(f"Warehouse format {found} is current; nothing to rebuild.")
        return
    if restaged:
        typer.echo("Rebuilding the warehouse from the data already downloaded...")
    else:
        typer.echo(f"Warehouse format {found} is older than this code's {SCHEMA_VERSION}; "
                   "rebuilding it from the data already downloaded...")
    _build_and_log(False, {"kind": "build", "started_at": now_utc().isoformat(), "sources": []})


def _restage_stale(store: VintageStore) -> list[str]:
    """Stage again, from the raw files, the vintages staged by an older version of their loader."""
    done = []
    for m in store.manifests():
        cls = CONNECTORS.get(m.source_id)
        if not cls or m.stage_version >= cls.stage_version:
            continue
        try:
            cls().restage(store, m)
            done.append(f"{m.source_id} {m.vintage}")
        except Exception as exc:  # noqa: BLE001 - one source's raw files gone must not stop the others
            typer.echo(f"{m.source_id} {m.vintage}: could not stage again ({exc}); run refresh.bat.")
    return done


@app.command("free-space")
def free_space(keep: int = typer.Option(2, help="Downloads to keep per source."),
               yes: bool = typer.Option(False, "--yes", help="Delete without asking.")):
    """Delete old raw downloads, keeping the newest few per source. Vintages and builds are kept."""
    p = paths()
    found = local.freeable_raw(p.home, keep)
    if not found:
        typer.echo("Nothing to free: every source has at most the downloads it keeps.")
        return
    total = sum(f["bytes"] for f in found)
    for f in found:
        typer.echo(f"  {f['path']}  {f['bytes'] / 1024 ** 2:,.1f} MB")
    if not yes and not typer.confirm(f"Delete these {len(found)} old downloads ({total / 1024 ** 2:,.1f} MB)?"):
        raise typer.Exit(1)
    done = local.free_raw(p.home, keep)
    typer.echo(f"Freed {done['freed_bytes'] / 1024 ** 2:,.1f} MB.")


@app.command()
def status():
    """Show stored vintages and the live build."""
    p = paths()
    typer.echo(f"data folder: {p.home}")
    for m in VintageStore(p).manifests():
        typer.echo(f"  {m.source_id:10} {m.vintage:20} {m.row_count:>10,} rows  fetched {m.retrieved_at}")
    current = p.current_build()
    typer.echo(f"live build: {current or 'none'}")
    if current:
        report = p.reports / current.name.replace(".duckdb", ".md")
        if report.exists():
            typer.echo(f"report: {report}")
    for line in monitor.storage_lines(p):
        typer.echo(line)


@app.command()
def validate():
    """Check the catalogues, then re-run the Python gates on the live build."""
    problems = catalogue.validate()
    for pr in problems:
        typer.echo(f"catalogue: {pr}", err=True)
    current = paths().current_build()
    failed = bool(problems)
    if current:
        con = duckdb.connect(str(current), read_only=True)
        for c in gates.run(con, previous=None):
            if c.kind != "manual":
                typer.echo(f"{c.status:5} {c.check_id}: {c.detail}")
            failed |= c.status == "fail"
        con.close()
    else:
        typer.echo("no live build; catalogue checks only")
    raise typer.Exit(1 if failed else 0)


@app.command()
def keys():
    """Show the API key register and which keys are set."""
    register = yaml.safe_load((resources.files("worldmodel_data") / "api_keys.yaml").read_text())
    for entry in register:
        env = entry.get("env") or []
        state = ", ".join(f"{v}={'set' if os.environ.get(v) else 'missing'}" for v in env) or "no key needed"
        typer.echo(f"{entry['source']:16} {entry['status']:28} {state}")


@app.command()
def export(
    name: str = typer.Argument(..., help="Stream name from contract streams.yaml"),
    fmt: str = typer.Option("csv", "--format", help="csv, parquet or json"),
    out: Optional[Path] = typer.Option(None, help="Output file (default: stdout for csv/json)."),
    as_of: Optional[str] = typer.Option(None, help="Values as known on this date (YYYY-MM-DD)."),
):
    """Write a named stream from the live build."""
    stream = next((s for s in catalogue.streams() if s["name"] == name), None)
    if stream is None:
        raise typer.BadParameter(f"no stream {name}; see contract streams.yaml")
    current = paths().current_build()
    if current is None:
        raise typer.BadParameter("no live build; run `worldmodel-data build` first")
    q = stream_query(stream)
    q.as_of = date.fromisoformat(as_of) if as_of else None
    sql, params = series_sql(q)
    con = duckdb.connect(str(current), read_only=True)
    rel = con.execute(sql, params)
    if fmt == "parquet":
        if out is None:
            raise typer.BadParameter("--out is needed for parquet")
        con.execute(f"COPY ({sql}) TO '{out.as_posix()}' (FORMAT parquet)", params)
    elif fmt == "json":
        cols = [d[0] for d in rel.description]
        rows = [dict(zip(cols, r)) for r in rel.fetchall()]
        text = json.dumps({"stream": stream, "rows": rows}, default=str, indent=1)
        (out.write_text(text) if out else sys.stdout.write(text + "\n"))
    else:
        import csv as csvmod
        fh = out.open("w", newline="") if out else sys.stdout
        w = csvmod.writer(fh)
        w.writerow([d[0] for d in rel.description])
        w.writerows(rel.fetchall())
        if out:
            fh.close()
    con.close()


@app.command()
def publish(dest: Path = typer.Argument(..., help="Where to copy the live build.")):
    """Copy the live build to a file, for example app/sample/worldmodel-sample.duckdb."""
    typer.echo(f"copied to {build_mod.publish(paths(), dest)}")


if __name__ == "__main__":
    app()
