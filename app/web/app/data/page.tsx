"use client";

import { Fragment, useEffect, useState } from "react";
import { RefreshHistoryCard, StorageCard } from "@/components/RefreshHistory";
import { api, type Dataset, type Meta, type Source } from "@/lib/api";

type Check = { check_id: string; kind: string; status: string; detail: string };
type Status = { label: string; tone: "ok" | "warn" | "off"; note: string };

const DAY = 86_400_000;

// One plain status per dataset, worst first: not connected, nothing loaded,
// sample data, an old release, then live.
function statusOf(d: Dataset, meta: Meta | null): Status {
  if (d.status === "planned") return { label: "Not connected yet", tone: "off", note: "Planned source; no connector yet." };
  if (!d.latest_vintage) return { label: "No data", tone: "warn", note: "Connected, but nothing loaded. Run a refresh." };
  if (meta?.is_sample) return { label: "Sample", tone: "warn", note: "Bundled sample. Run worldmodel-data refresh for the latest release." };
  const releaseYear = parseInt(d.latest_vintage.release, 10);
  if (releaseYear && new Date().getFullYear() - releaseYear > 2)
    return { label: "Old release", tone: "warn", note: `Release ${d.latest_vintage.release}; a newer one is likely out.` };
  return { label: "Live", tone: "ok", note: "Latest fetched release is in use." };
}

function ago(iso: string): string {
  const days = Math.floor((Date.now() - new Date(iso.replace(" ", "T")).getTime()) / DAY);
  return days < 1 ? "today" : days === 1 ? "yesterday" : days < 60 ? `${days} days ago` : `${Math.round(days / 30)} months ago`;
}

function span(a: number | null, b: number | null) {
  return a === null || b === null ? "–" : `${a}–${b}`;
}

export default function DataPage() {
  const [meta, setMeta] = useState<Meta | null>(null);
  const [sources, setSources] = useState<Source[]>([]);
  const [checks, setChecks] = useState<Check[]>([]);
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [open, setOpen] = useState<string | null>(null);

  useEffect(() => {
    api.meta().then(setMeta);
    api.sources().then(setSources);
    api.checks().then(setChecks);
    api.datasets().then(setDatasets).catch(() => setDatasets([]));
  }, []);

  const counts = checks.reduce<Record<string, number>>((acc, c) => ({ ...acc, [c.status]: (acc[c.status] ?? 0) + 1 }), {});
  const manual = checks.find((c) => c.kind === "manual");
  const notable = checks.filter((c) => c.kind !== "manual" && c.status !== "pass");

  return (
    <div className="grid">
      <div>
        <h1>Data status</h1>
        {meta && (
          <p className="ink-2" style={{ marginTop: 0 }}>
            Warehouse build {meta.build_id}, built {meta.built_at.replace("T", " ").slice(0, 16)} UTC
            {meta.is_sample ? " (the sample that ships with the app)" : ""}. Schema {meta.schema_version}.
          </p>
        )}
      </div>

      <div className="card">
        <h2>Datasets</h2>
        <p className="ink-2" style={{ marginTop: 0 }}>
          {datasets.filter((d) => d.latest_vintage && d.source_id !== "worldmodel").length} of {datasets.filter((d) => d.source_id !== "worldmodel").length} sources loaded.
          Validation: {counts.pass ?? 0} passed, {counts.warn ?? 0} warnings, {counts.fail ?? 0} failed.
          Click a row to see its indicators.
        </p>
        <div className="table-scroll">
          <table className="datasets">
            <thead>
              <tr>
                <th>Dataset</th><th>Status</th><th>Release</th><th>Fetched</th>
                <th className="num">Indicators</th><th className="num">Countries</th><th>Years</th><th>Updates</th>
              </tr>
            </thead>
            <tbody>
              {datasets.filter((d) => d.source_id !== "worldmodel").map((d) => {
                const st = statusOf(d, meta);
                const inds = d.indicators;
                const first = inds.length ? Math.min(...inds.map((i) => i.first_year ?? 9999)) : null;
                const last = inds.length ? Math.max(...inds.map((i) => i.last_year ?? 0)) : null;
                const est = inds.length ? Math.max(...inds.map((i) => i.last_estimate_year ?? 0)) : null;
                const countries = inds.length ? Math.max(...inds.map((i) => i.countries)) : null;
                const isOpen = open === d.source_id;
                return (
                  <Fragment key={d.source_id}>
                    <tr className="clickable" onClick={() => setOpen(isOpen ? null : d.source_id)} aria-expanded={isOpen}>
                      <td><b>{d.short_name}</b><div className="small muted">{d.publisher}</div></td>
                      <td><span className={`status ${st.tone}`} title={st.note}>{st.label}</span></td>
                      <td className="nowrap">{d.latest_vintage?.release ?? "–"}</td>
                      <td className="nowrap">{d.latest_vintage ? <>{d.latest_vintage.retrieved_at.slice(0, 10)}<div className="small muted">{ago(d.latest_vintage.retrieved_at)}</div></> : "–"}</td>
                      <td className="num">{inds.length || "–"}</td>
                      <td className="num">{countries ?? "–"}</td>
                      <td>{span(first, last)}{est && last && est < last ? <div className="small muted">estimates to {est}</div> : null}</td>
                      <td className="small">{d.cadence}</td>
                    </tr>
                    {isOpen && (
                      <tr className="detail">
                        <td colSpan={8}>
                          <p className="small ink-2" style={{ margin: "0 0 6px" }}>{st.note}</p>
                          {inds.length > 0 ? (
                            <table>
                              <thead><tr><th>Indicator</th><th>Topic</th><th>Years</th><th>Estimates to</th><th className="num">Countries</th><th className="num">Values</th></tr></thead>
                              <tbody>
                                {inds.map((i) => (
                                  <tr key={i.indicator_id}>
                                    <td>{i.name}</td><td>{i.domain}</td><td>{span(i.first_year, i.last_year)}</td>
                                    <td>{i.last_estimate_year ?? "–"}</td><td className="num">{i.countries}</td>
                                    <td className="num">{i.row_count.toLocaleString("en")}</td>
                                  </tr>
                                ))}
                              </tbody>
                            </table>
                          ) : <p className="small muted">No indicators loaded from this source.</p>}
                        </td>
                      </tr>
                    )}
                  </Fragment>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>

      <StorageCard />
      <RefreshHistoryCard />

      <div className="card">
        <h2>Loaded vintages</h2>
        <div style={{ overflowX: "auto" }}><table>
          <thead><tr><th>Source</th><th>Vintage</th><th>Fetched</th><th>Used</th><th>From</th></tr></thead>
          <tbody>
            {meta?.vintages.map((v) => (
              <tr key={`${v.source_id}:${v.vintage}`}>
                <td>{v.source_id}</td><td>{v.vintage}</td><td>{v.retrieved_at.slice(0, 10)}</td>
                <td>{v.is_latest ? "latest" : "history"}</td>
                <td className="small muted" style={{ wordBreak: "break-all" }}>{v.origin}</td>
              </tr>
            ))}
          </tbody>
        </table></div>
      </div>

      <div className="card">
        <h2>Validation gates</h2>
        <p className="ink-2" style={{ marginTop: 0 }}>
          {counts.pass ?? 0} passed, {counts.warn ?? 0} warnings, {counts.skip ?? 0} skipped, {counts.fail ?? 0} failed.
          A build that fails a gate is never swapped in.
        </p>
        {notable.length > 0 && (
          <div style={{ overflowX: "auto" }}><table>
            <thead><tr><th>Check</th><th>Status</th><th>Detail</th></tr></thead>
            <tbody>
              {notable.map((c) => (
                <tr key={c.check_id}><td>{c.check_id}</td><td>{c.status}</td><td className="small">{c.detail}</td></tr>
              ))}
            </tbody>
          </table></div>
        )}
        {manual && (
          <details style={{ marginTop: 8 }}>
            <summary>Values to check by eye against the source sites</summary>
            <ul className="small">
              {manual.detail.split("\n").map((line) => {
                const url = line.match(/https?:\/\/\S+/)?.[0];
                return <li key={line}>{url ? <>{line.replace(url, "")}<a href={url} target="_blank" rel="noreferrer">open</a></> : line}</li>;
              })}
            </ul>
          </details>
        )}
      </div>

      <div className="card">
        <h2>Sources</h2>
        <div style={{ overflowX: "auto" }}><table>
          <thead><tr><th>Source</th><th>Licence</th><th>Cadence</th><th>Status</th></tr></thead>
          <tbody>
            {sources.map((s) => (
              <tr key={s.source_id}>
                <td>{s.url ? <a href={s.url} target="_blank" rel="noreferrer">{s.name}</a> : s.name}<div className="small muted">{s.attribution}</div></td>
                <td>{s.licence_url ? <a href={s.licence_url} target="_blank" rel="noreferrer">{s.licence}</a> : s.licence}</td>
                <td>{s.cadence}</td>
                <td>{s.status}</td>
              </tr>
            ))}
          </tbody>
        </table></div>
      </div>
    </div>
  );
}
