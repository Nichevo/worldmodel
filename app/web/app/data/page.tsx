"use client";

import { useEffect, useState } from "react";
import { api, type Meta, type Source } from "@/lib/api";

type Check = { check_id: string; kind: string; status: string; detail: string };

export default function DataPage() {
  const [meta, setMeta] = useState<Meta | null>(null);
  const [sources, setSources] = useState<Source[]>([]);
  const [checks, setChecks] = useState<Check[]>([]);

  useEffect(() => {
    api.meta().then(setMeta);
    api.sources().then(setSources);
    api.checks().then(setChecks);
  }, []);

  const counts = checks.reduce<Record<string, number>>((acc, c) => ({ ...acc, [c.status]: (acc[c.status] ?? 0) + 1 }), {});
  const manual = checks.find((c) => c.kind === "manual");
  const notable = checks.filter((c) => c.kind !== "manual" && c.status !== "pass");

  return (
    <div className="grid">
      <div>
        <h1>Sources and data health</h1>
        {meta && (
          <p className="ink-2" style={{ marginTop: 0 }}>
            Warehouse build {meta.build_id}, built {meta.built_at.replace("T", " ").slice(0, 16)} UTC
            {meta.is_sample ? " (the sample that ships with the app)" : ""}. Schema {meta.schema_version}.
          </p>
        )}
      </div>

      <div className="card">
        <h2>Loaded vintages</h2>
        <table>
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
        </table>
      </div>

      <div className="card">
        <h2>Validation gates</h2>
        <p className="ink-2" style={{ marginTop: 0 }}>
          {counts.pass ?? 0} passed, {counts.warn ?? 0} warnings, {counts.skip ?? 0} skipped, {counts.fail ?? 0} failed.
          A build that fails a gate is never swapped in.
        </p>
        {notable.length > 0 && (
          <table>
            <thead><tr><th>Check</th><th>Status</th><th>Detail</th></tr></thead>
            <tbody>
              {notable.map((c) => (
                <tr key={c.check_id}><td>{c.check_id}</td><td>{c.status}</td><td className="small">{c.detail}</td></tr>
              ))}
            </tbody>
          </table>
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
        <table>
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
        </table>
      </div>
    </div>
  );
}
