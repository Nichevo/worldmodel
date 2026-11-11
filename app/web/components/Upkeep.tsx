"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { toast } from "@/lib/ai";
import { api, type InboxState, type Job, type SourceHealth } from "@/lib/api";
import { saveSettings, useSettings } from "@/lib/settings";

// Looking after the sources: the job running now (a refresh, filing the inbox, getting the
// due files, a backup), the inbox, and every source's health in one table.

const mins = (s: number) => (s < 90 ? "about a minute" : s < 3600 ? `about ${Math.round(s / 60)} minutes` : `about ${(s / 3600).toFixed(1)} hours`);
export const mb = (b: number) => (b >= 1024 ** 3 ? `${(b / 1024 ** 3).toFixed(1)} GB` : b >= 1024 ** 2 ? `${(b / 1024 ** 2).toFixed(0)} MB` : b ? `${Math.max(1, Math.round(b / 1024))} KB` : "–");

// The job, asked for every 3 seconds while one runs (and once a minute otherwise, so a
// refresh started from refresh.bat or the scheduled task shows up too).
export function useJob() {
  const [job, setJob] = useState<Job | null>(null);
  const load = useCallback(() => api.job().then(setJob).catch(() => {}), []);
  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    const t = setInterval(load, job?.running ? 3000 : 60000);
    return () => clearInterval(t);
  }, [job?.running, load]);
  const start = async (kind: NonNullable<Job["kind"]>, sources?: string[]) => {
    try {
      setJob(await api.startJob(kind, sources));
    } catch (e) {
      toast(String((e as Error).message || e));
    }
  };
  return { job, start, reload: load };
}

export function JobPanel({ job, onDone }: { job: Job | null; onDone?: () => void }) {
  const [open, setOpen] = useState(false);
  const [wasRunning, setWasRunning] = useState(false);
  useEffect(() => {
    if (job?.running) setWasRunning(true);
    else if (wasRunning) { setWasRunning(false); onDone?.(); }
  }, [job?.running]); // eslint-disable-line react-hooks/exhaustive-deps
  if (!job || !job.kind) return null;
  const p = job.progress;
  const pct = p && p.total ? Math.round((100 * p.done) / p.total) : null;
  const ok = !job.running && job.exit_code === 0;
  return (
    <div className="card job-panel">
      <div className="card-head">
        <h3 style={{ margin: 0 }}>{job.label}{job.sources?.length ? `: ${job.sources.join(", ")}` : ""}</h3>
        {job.lines.length > 0 && <button className="link small" onClick={() => setOpen(!open)}>{open ? "Hide the details" : "Show the details"}</button>}
      </div>
      {job.running ? (
        <>
          {p && <div className="progress" role="progressbar" aria-valuenow={pct ?? 0} aria-valuemin={0} aria-valuemax={100}>
            <span style={{ width: `${pct ?? 0}%` }} /></div>}
          <p className="small" style={{ margin: "4px 0" }}>
            {p ? `${p.done} of ${p.total} sources done${p.current ? `; now ${p.current}` : ""}${p.seconds_left != null ? `; ${mins(p.seconds_left)} left` : ""}.`
              : "Running…"}
            {job.by === "outside" ? " Started from refresh.bat or the scheduled task." : " You can leave this page; it carries on."}
          </p>
        </>
      ) : (
        <p className={`small ${ok ? "" : "error"}`} style={{ margin: "4px 0" }}>
          {ok ? "Finished" : `Stopped with problems (code ${job.exit_code})`}
          {job.finished_at ? ` at ${new Date(job.finished_at).toLocaleTimeString()}` : ""}.
          {ok ? " Reload a page to see new data." : " The last lines below say why; the app keeps its last good data."}
        </p>
      )}
      {(open || (!job.running && !ok)) && job.lines.length > 0 && (
        <pre className="job-log small">{job.lines.slice(open ? -200 : -12).join("\n")}</pre>
      )}
    </div>
  );
}

export function InboxCard({ start, busy }: { start: (kind: "inbox") => void; busy: boolean }) {
  const [box, setBox] = useState<InboxState | null>(null);
  const [pick, setPick] = useState<Record<string, string>>({});
  const load = useCallback(() => api.inbox().then(setBox).catch(() => {}), []);
  useEffect(() => { load(); }, [load]);
  if (!box) return null;
  const assign = async (name: string) => {
    const sid = pick[name] || box.waiting.find((w) => w.name === name)?.candidates[0];
    if (!sid) return;
    try {
      await api.inboxAssign(name, sid);
      toast(`${name} filed; loading it now`);
      load();
    } catch (e) { toast(String((e as Error).message || e)); }
  };
  return (
    <div className="card" id="inbox">
      <div className="card-head">
        <h2 style={{ margin: 0 }}>Inbox</h2>
        <button className="small" disabled={busy} onClick={() => { start("inbox"); setTimeout(load, 4000); }}
          title="Move each file in the inbox (and recent downloads whose source is certain) into its source's folder, load it and rebuild">File them now</button>
      </div>
      <p className="small ink-2" style={{ marginTop: 4 }}>
        Save any file you download for the app in <code>{box.inbox}</code>
        {box.downloads ? <> or just leave it in <code>{box.downloads}</code> (the last {box.downloads_days} days are checked; files there are copied, never moved)</> : null}.
        Each refresh, <code>.\load.bat</code> and <b>File them now</b> work out which source a file belongs to (by its name, a file like it
        loaded before, or the site it came from), put it in that source&apos;s folder and load it. {box.downloads_on ? "" : "Watching Downloads is off in Settings."}
      </p>
      {box.waiting.length > 0 && (
        <div className="table-scroll"><table className="summary-table">
          <thead><tr><th>Waiting</th><th>Which source?</th><th /></tr></thead>
          <tbody>{box.waiting.map((w) => (
            <tr key={w.name}>
              <td className="small"><b>{w.name}</b><div className="muted">{mb(w.size)}; {w.source_id ? `goes to ${w.candidate_names[w.source_id]} (${w.how})` : w.how}</div></td>
              <td><select value={pick[w.name] ?? w.source_id ?? w.candidates[0] ?? ""} onChange={(e) => setPick({ ...pick, [w.name]: e.target.value })}
                aria-label={`Source for ${w.name}`}>
                <option value="">Choose…</option>
                {w.candidates.length > 0 && <optgroup label="Likely">{w.candidates.map((c) => <option key={c} value={c}>{w.candidate_names[c] ?? c}</option>)}</optgroup>}
                <optgroup label="Every source">{box.sources.map((s) => <option key={s.source_id} value={s.source_id}>{s.name}</option>)}</optgroup>
              </select></td>
              <td><button className="small" disabled={!(pick[w.name] || w.source_id || w.candidates[0])} onClick={() => assign(w.name)}>File it</button></td>
            </tr>
          ))}</tbody>
        </table></div>
      )}
      {box.waiting.length === 0 && <p className="small muted">Nothing waiting.</p>}
      {box.recent.length > 0 && (
        <details><summary className="small">Filed lately ({box.recent.length})</summary>
          <ul className="small">{box.recent.slice(0, 20).map((r, i) => <li key={i}>{r.at.slice(0, 16).replace("T", " ")}: {r.name} from {r.from} to <b>{r.source_name}</b> ({r.how})</li>)}</ul>
        </details>
      )}
    </div>
  );
}

const STATE_TEXT: Record<SourceHealth["state"], string> = { failing: "Failing", never: "Nothing loaded", due: "Due", ok: "Fine", off: "Switched off" };
const METHOD_TEXT: Record<string, string> = { site: "From the site", verify: "verify.bat", file: "Your file" };

export function SourceHealthCard({ start, busy }: { start: (kind: "refresh" | "load", sources?: string[]) => void; busy: boolean }) {
  const s = useSettings();
  const [rows, setRows] = useState<SourceHealth[] | null>(null);
  const [state, setState] = useState<string>("problems");
  const [group, setGroup] = useState("");
  const [q, setQ] = useState("");
  const [open, setOpen] = useState<string | null>(null);
  const load = useCallback(() => api.sourceHealth().then((d) => setRows(d.sources)).catch(() => setRows([])), []);
  useEffect(() => { load(); }, [load, s.sources_off]);
  const groups = useMemo(() => [...new Set((rows ?? []).map((r) => r.group))].sort(), [rows]);
  if (!rows) return null;
  const shown = rows.filter((r) => (state === "all" || (state === "problems" ? ["failing", "never", "due"].includes(r.state)
    : state === "hand" ? r.by_hand : state === "unused" ? r.uses === 0 && !r.off : r.state === state))
    && (!group || r.group === group) && (!q || `${r.name} ${r.publisher} ${r.source_id}`.toLowerCase().includes(q.toLowerCase())));
  const counts = rows.reduce<Record<string, number>>((a, r) => ({ ...a, [r.state]: (a[r.state] ?? 0) + 1 }), {});
  const offList = (s.sources_off || "").split(",").filter(Boolean);
  const setOff = (ids: string[], off: boolean) => {
    const next = off ? [...new Set([...offList, ...ids])] : offList.filter((x) => !ids.includes(x));
    saveSettings({ sources_off: next.join(",") }).then(() => toast(off ? `${ids.length} switched off` : `${ids.length} switched on`));
  };
  const total = rows.reduce((a, r) => a + r.bytes, 0);
  return (
    <div className="card" id="sources-health">
      <div className="card-head">
        <h2 style={{ margin: 0 }}>Every source</h2>
        <button className="small" disabled={busy} onClick={() => start("refresh")} title="Fetch every source that is due, then rebuild (as refresh.bat does)">Refresh everything</button>
      </div>
      <p className="small ink-2" style={{ marginTop: 4 }}>
        {rows.length} sources, {mb(total)} on disk: {counts.failing ?? 0} failing, {counts.never ?? 0} with nothing loaded, {counts.due ?? 0} due at the next refresh,
        {" "}{counts.off ?? 0} switched off. A switched-off source is never fetched and never on the <Link href="/todo">To do</Link> list; what it fed stays as last loaded.
      </p>
      <div className="chips-row small">
        <span className="seg">
          {[["problems", "Needs a look"], ["failing", "Failing"], ["hand", "By hand"], ["unused", "No chart uses it"], ["off", "Off"], ["all", "All"]].map(([k, l]) => (
            <button key={k} className={state === k ? "on" : ""} onClick={() => setState(k)}>{l}</button>))}
        </span>
        <select value={group} onChange={(e) => setGroup(e.target.value)} aria-label="Topic"><option value="">Every topic</option>
          {groups.map((g) => <option key={g} value={g}>{g}</option>)}</select>
        <input type="search" value={q} placeholder="Filter by name" onChange={(e) => setQ(e.target.value)} aria-label="Filter sources" />
        {shown.length > 0 && <>
          <button className="link small" onClick={() => setOff(shown.filter((r) => !r.off).map((r) => r.source_id), true)}
            title="Switch off every source shown: they stop being fetched and leave the To do list">Switch these {shown.filter((r) => !r.off).length} off</button>
          {shown.some((r) => r.off) && <button className="link small" onClick={() => setOff(shown.filter((r) => r.off).map((r) => r.source_id), false)}>Switch them back on</button>}
        </>}
      </div>
      {shown.length === 0 ? <p className="muted small">None here.</p> : (
        <div className="table-scroll"><table className="summary-table health-table">
          <thead><tr><th>Source</th><th>State</th><th>Last worked</th><th>Next</th><th>How</th><th>Rows</th><th>On disk</th><th>Used by</th><th /></tr></thead>
          <tbody>{shown.map((r) => (
            <tr key={r.source_id} className={r.off ? "muted" : ""}>
              <td className="small"><b>{r.name}</b><div className="muted">{r.publisher}</div></td>
              <td className="small"><span className={`pill state-${r.state}`}>{STATE_TEXT[r.state]}</span>
                {r.failing && <div className="muted" title={r.failing}>{r.failing.slice(0, 90)}{r.failing.length > 90 ? "…" : ""}</div>}</td>
              <td className="small">{r.last_ok ? r.last_ok.slice(0, 10) : r.loaded ? r.loaded.slice(0, 10) : "–"}{r.release ? <div className="muted">release {r.release}</div> : null}</td>
              <td className="small">{r.off ? "–" : r.due ?? "–"}</td>
              <td className="small">{r.by_hand ? "By hand" : METHOD_TEXT[r.method ?? ""] ?? (r.scraper ? "Web pages" : "From the site")}</td>
              <td className="small">{r.rows != null ? r.rows.toLocaleString() : "–"}</td>
              <td className="small">{mb(r.bytes)}</td>
              <td className="small">{r.uses ? <span title={r.uses_names.join(", ")}>{r.uses} indicator{r.uses === 1 ? "" : "s"}</span> : <span className="muted">maps, events or pages</span>}</td>
              <td className="small nowrap">
                {!r.off && r.fetched && <button className="link small" disabled={busy} onClick={() => start(r.by_hand ? "load" : "refresh", [r.source_id])}
                  title={r.by_hand ? "Load the files in its folder, then rebuild" : "Fetch just this source now (even if not due), then rebuild"}>{r.by_hand ? "Load" : "Refresh"}</button>}
                {" "}<button className="link small" onClick={() => setOpen(open === r.source_id ? null : r.source_id)}>{open === r.source_id ? "Less" : "More"}</button>
                {open === r.source_id && (
                  <div className="health-more">
                    <div>{r.cadence}</div>
                    {r.note && <div className="muted">Last refresh: {r.note}</div>}
                    <div>Folder: <code>var\manual\{r.source_id}</code></div>
                    <div>{r.uses ? `Switching it off leaves ${r.uses} indicator${r.uses === 1 ? "" : "s"} as last loaded: ${r.uses_names.join(", ")}${r.uses > r.uses_names.length ? "…" : ""}.`
                      : "No indicator reads it; its maps, layers, events or page sections stay as last loaded if it is off."}</div>
                    <button className="link small" onClick={() => setOff([r.source_id], !r.off)}>{r.off ? "Switch it back on" : "Switch it off"}</button>
                    {" "}<a href={r.url} target="_blank" rel="noreferrer">Its site</a>
                  </div>
                )}
              </td>
            </tr>
          ))}</tbody>
        </table></div>
      )}
    </div>
  );
}

// Keys typed here go into the .env file on this computer; they are never shown again.
export function KeyInput({ envs, onSaved }: { envs: string[]; onSaved?: () => void }) {
  const [vals, setVals] = useState<Record<string, string>>({});
  const save = async () => {
    try {
      for (const e of envs) if (vals[e]?.trim()) await api.setKey(e, vals[e].trim());
      toast("Saved in .env on this computer");
      setVals({});
      onSaved?.();
    } catch (err) { toast(String((err as Error).message || err)); }
  };
  return (
    <>
      {envs.map((e) => <input key={e} type="password" autoComplete="off" placeholder={e} value={vals[e] ?? ""} aria-label={e}
        onChange={(x) => setVals({ ...vals, [e]: x.target.value })} style={{ width: 200 }} />)}
      <button className="small" disabled={!envs.some((e) => vals[e]?.trim())} onClick={save}>Save</button>
    </>
  );
}
