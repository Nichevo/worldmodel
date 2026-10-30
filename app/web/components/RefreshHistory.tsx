"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import EChart from "@/components/EChart";
import { api, type RefreshRun, type Storage } from "@/lib/api";
import { changesOption, healthOption, spaceOption } from "@/lib/charts";
import { seriesVar } from "@/lib/colors";
import { SOURCE_SHORT } from "@/lib/format";

// Data status: how much room the data folder takes against the limits in
// Settings, a button to free space, and charts of every refresh from the
// pipeline's refresh log (space over time, rows changed, health).
const gb = (b: number) => `${(b / 1024 ** 3).toFixed(b < 10 * 1024 ** 3 ? 2 : 1)} GB`;
const mb = (b: number) => (b >= 1024 ** 3 ? gb(b) : `${(b / 1024 ** 2).toFixed(1)} MB`);
const LEVEL: Record<string, { label: string; tone: string }> = {
  ok: { label: "OK", tone: "ok" }, warn: { label: "Over 80%", tone: "warn" },
  critical: { label: "Over 95%", tone: "warn" }, full: { label: "Limit reached", tone: "warn" },
};

export function StorageCard() {
  const [st, setSt] = useState<Storage | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const load = () => api.storage().then(setSt).catch((e) => setMsg(String(e.message || e)));
  useEffect(() => { load(); }, []);
  const free = async () => {
    if (!st || !window.confirm(`Delete old raw downloads (${mb(st.freeable)})? The newest two downloads of each source are kept, and nothing the app shows is affected.`)) return;
    setBusy(true);
    try {
      const r = await api.freeUp();
      setMsg(`Freed ${mb(r.freed_bytes)} (${r.removed.length} old downloads).`);
      load();
    } catch (e) {
      setMsg(String((e as Error).message || e));
    } finally {
      setBusy(false);
    }
  };
  if (!st) return <div className="card" id="storage"><h2>Storage</h2><p className="muted">{msg ?? "Loading…"}</p></div>;
  const shown = st.categories.filter((c) => c.bytes > 0);
  return (
    <div className="card" id="storage">
      <h2>Storage</h2>
      <p className="ink-2" style={{ marginTop: 0 }}>
        The data folder <code>{st.home}</code> holds {gb(st.total)}. Limits are set in <Link href="/settings">Settings</Link>;
        warnings show at 80% and 95%. Nothing is deleted on its own.
      </p>
      {st.limits.map((l) => {
        const share = l.limit ? l.used / l.limit : 0;
        return (
          <div className="limit" key={l.key}>
            <div className="limit-head">
              <b>{l.label}</b> <span className="muted">{gb(l.used)} of {gb(l.limit)} ({(share * 100).toFixed(share < 0.1 ? 1 : 0)}%)</span>
              <span className={`status ${LEVEL[l.level].tone}`}>{LEVEL[l.level].label}</span>
            </div>
            <div className="meter" role="meter" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(share * 100)} aria-label={l.label}>
              <div className={`fill ${l.level}`} style={{ width: `${Math.min(100, share * 100)}%` }} />
              <i style={{ left: "80%" }} title="80%" /><i style={{ left: "95%" }} title="95%" />
            </div>
          </div>
        );
      })}
      <table className="small" style={{ marginTop: 8 }}>
        <thead><tr><th>What</th><th className="num">Size</th></tr></thead>
        <tbody>
          {(shown.length ? shown : st.categories).map((c) => (
            <tr key={c.key}><td>{c.label}</td><td className="num">{mb(c.bytes)}</td></tr>
          ))}
        </tbody>
      </table>
      <p className="small">
        <button onClick={free} disabled={busy || st.freeable === 0}>Free up space</button>{" "}
        <span className="muted">
          {st.freeable > 0 ? `${mb(st.freeable)} of old raw downloads can go (the newest two per source are kept).` : "No old downloads to remove."}
        </span>
        {msg && <span> {msg}</span>}
      </p>
    </div>
  );
}

const CATS = [
  { key: "raw", label: "Raw downloads" }, { key: "vintages", label: "Vintages" }, { key: "builds", label: "Builds" },
  { key: "reports", label: "Reports" }, { key: "pictures", label: "Pictures" }, { key: "user", label: "Your files" }, { key: "other", label: "Other" },
];

export function RefreshHistoryCard() {
  const [runs, setRuns] = useState<RefreshRun[] | null>(null);
  const [limit, setLimit] = useState(100 * 1024 ** 3);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    api.refreshLog().then(setRuns).catch((e) => setError(String(e.message || e)));
    api.storage().then((s) => setLimit(s.limits[0].limit)).catch(() => {});
  }, []);

  // Runs are labelled by day, with the time too when a day has more than one.
  const day = (d: Date) => d.toLocaleDateString("en", { day: "numeric", month: "short" });
  const days = (runs ?? []).map((r) => day(new Date(r.started_at)));
  const pts = (runs ?? []).map((r, i) => {
    const d = new Date(r.started_at);
    const twice = days.filter((x) => x === days[i]).length > 1;
    return { label: twice ? `${days[i]} ${d.toLocaleTimeString("en", { hour: "2-digit", minute: "2-digit", hour12: false })}` : days[i],
      when: d.toLocaleString("en", { dateStyle: "medium", timeStyle: "short" }) };
  });
  const withDisk = (runs ?? []).map((r, i) => ({ r, p: pts[i] })).filter((x) => x.r.disk);
  const usedCats = CATS.filter((c) => withDisk.some((x) => (x.r.disk?.[c.key] ?? 0) > 0));
  const sum = (r: RefreshRun, k: "added" | "changed" | "removed") => r.sources.reduce((t, s) => t + (s[k] ?? 0), 0);
  const space = useCallback(() => spaceOption(withDisk.map((x) => x.p), usedCats, withDisk.map((x) => x.r.disk!), limit), [runs, limit]);
  const changes = useCallback(() => changesOption(pts, (runs ?? []).map((r) => sum(r, "added")),
    (runs ?? []).map((r) => sum(r, "changed")), (runs ?? []).map((r) => sum(r, "removed"))), [runs]);
  const health = useCallback(() => healthOption((runs ?? []).map((r, i) => ({
    ...pts[i], ok: r.status === "ok",
    minutes: r.finished_at ? (new Date(r.finished_at).getTime() - new Date(r.started_at).getTime()) / 60000 : null,
    note: r.error ?? (r.checks ? `${r.checks.pass} checks passed, ${r.checks.warn} warnings, ${r.checks.fail} failed` : "")
      + (r.sources.some((s) => s.status === "error") ? `; fetch failed: ${r.sources.filter((s) => s.status === "error").map((s) => s.source_id).join(", ")}` : ""),
  }))), [runs]);

  return (
    <div className="card">
      <h2>Refresh history</h2>
      <p className="ink-2" style={{ marginTop: 0 }}>
        Every refresh and build, oldest on the left. Runs before this log existed are filled in from their build reports, so they
        have no sizes or timings. Run <code>.\refresh.bat</code> to fetch the latest data.
      </p>
      {error && <p className="error">{error}</p>}
      {runs && runs.length === 0 && <p className="muted">No refreshes logged yet.</p>}
      {runs && runs.length > 0 && (
        <div className="grid two">
          <div>
            <h3>Space used after each run, GB</h3>
            {withDisk.length ? <EChart option={space} height={220} label="Disk space used after each refresh, by category" />
              : <p className="small muted">No sizes yet; the next refresh records them.</p>}
          </div>
          <div>
            <h3>Rows changed per run, all sources</h3>
            <EChart option={changes} height={220} label="Rows added, changed and removed by each refresh" />
          </div>
          <div>
            <h3>Run time in minutes, and result</h3>
            <EChart option={health} height={200} label="How long each refresh took; failed runs in red" />
            <p className="caption"><span className="swatch-inline" style={{ background: seriesVar(0) }} /> passed
              <span className="swatch-inline" style={{ background: "var(--div-neg-3)", marginLeft: 10 }} /> failed (kept the last good build)</p>
          </div>
        </div>
      )}
      {runs && runs.length > 0 && (
        <details style={{ marginTop: 8 }}>
          <summary>Each run, source by source</summary>
          <table className="small">
            <thead>
              <tr><th>When</th><th>Kind</th><th>Result</th><th>Source</th><th>Status</th><th className="num">Download</th>
                <th className="num">Time</th><th className="num">Added</th><th className="num">Changed</th><th className="num">Removed</th></tr>
            </thead>
            <tbody>
              {[...runs].reverse().flatMap((r, ri) => {
                const srcs = r.sources.length ? r.sources : [{ source_id: "" }];
                return srcs.map((s, i) => (
                  <tr key={`${ri}-${i}`}>
                    <td>{i === 0 ? pts[runs.length - 1 - ri].when : ""}</td>
                    <td>{i === 0 ? `${r.kind}${r.backfilled ? " (from report)" : ""}` : ""}</td>
                    <td>{i === 0 ? (r.status === "ok" ? "passed" : <b>failed</b>) : ""}</td>
                    <td>{SOURCE_SHORT[s.source_id] ?? s.source_id}</td>
                    <td>{s.status ?? ""}{s.error ? `: ${s.error}` : ""}{s.note ? ` (${s.note})` : ""}</td>
                    <td className="num">{s.download_bytes !== undefined ? mb(s.download_bytes) : "–"}</td>
                    <td className="num">{s.seconds !== undefined ? `${s.seconds}s` : "–"}</td>
                    <td className="num">{s.added?.toLocaleString("en") ?? "–"}</td>
                    <td className="num">{s.changed?.toLocaleString("en") ?? "–"}</td>
                    <td className="num">{s.removed?.toLocaleString("en") ?? "–"}</td>
                  </tr>
                ));
              })}
            </tbody>
          </table>
        </details>
      )}
    </div>
  );
}
