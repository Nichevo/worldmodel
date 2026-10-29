"""worldmodel-data: the command line for the data side.

    worldmodel-data fetch un_wpp            download a source and store a new vintage
    worldmodel-data fetch imf_weo --from DIR   ... or load files you downloaded yourself
    worldmodel-data build                   build, validate and swap in a new warehouse
    worldmodel-data refresh                 fetch every active source, then build
    worldmodel-data status                  vintages, live build, last report
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
from datetime import date
from importlib import resources
from pathlib import Path
from typing import Optional

import duckdb
import typer
import yaml

from worldmodel_contract import catalogue
from worldmodel_contract.queries import series_sql, stream_query
from worldmodel_data import build as build_mod
from worldmodel_data import gates
from worldmodel_data.config import load_env, paths
from worldmodel_data.connectors import CONNECTORS
from worldmodel_data.vintage_store import VintageStore

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
    try:
        result = build_mod.build(paths(), allow_shrink=allow_shrink)
    except build_mod.BuildFailed as exc:
        typer.echo(f"BUILD FAILED: {exc}", err=True)
        if exc.report:
            typer.echo(exc.report.read_text(), err=True)
        raise typer.Exit(1)
    counts = {s: sum(c.status == s for c in result.checks) for s in ("pass", "warn", "skip")}
    typer.echo(f"build {result.build_id} is live: {counts['pass']} checks passed, {counts['warn']} warnings, "
               f"{counts['skip']} skipped. Report: {result.report}")


@app.command()
def refresh(allow_shrink: bool = typer.Option(False)):
    """Fetch every active source, then build."""
    store = VintageStore(paths())
    for source_id, cls in CONNECTORS.items():
        manifest, is_new = cls().ingest(store)
        typer.echo(f"{source_id}: {'new vintage' if is_new else 'unchanged'} {manifest.vintage}")
    build(allow_shrink=allow_shrink)


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
