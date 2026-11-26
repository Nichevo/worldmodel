"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { api, type Problem } from "@/lib/api";
import { useSettings } from "@/lib/settings";

// Refresh problems in plain words: each failed check, failed download or stopped build
// from the refresh log, how often it has happened and whether a later run fixed it.
const when = (iso: string) => new Date(iso).toLocaleString("en", { dateStyle: "medium", timeStyle: "short" });
const day = (iso: string) => new Date(iso).toLocaleDateString("en", { day: "numeric", month: "short", year: "numeric" });

function repeats(p: Problem): string {
  if (p.times === 1) return `Happened once, ${when(p.last_seen)}.`;
  const row = p.in_a_row > 1 ? ` The last ${p.in_a_row} runs in a row.` : "";
  return `Happened ${p.times} times since ${day(p.first_seen)}, most recently ${when(p.last_seen)}.${row}`;
}

// A ready-to-paste summary for the project thread.
function details(p: Problem): string {
  return [
    `${p.title} (${p.kind === "fetch" ? "download" : p.kind === "check" ? "validation check" : "build"})`,
    p.check_id ? `Check: ${p.check_id}` : p.source_id ? `Source: ${p.source_id}` : "",
    `Detail: ${p.summary}`,
    ...p.examples.map((e) => `  ${e}`),
    repeats(p),
    p.build_id ? `Build report: var\\warehouse\\reports\\${p.build_id}.md` : "",
  ].filter(Boolean).join("\n");
}

function ProblemItem({ p }: { p: Problem }) {
  const [copied, setCopied] = useState(false);
  const copy = () => navigator.clipboard?.writeText(details(p)).then(() => { setCopied(true); setTimeout(() => setCopied(false), 2000); });
  return (
    <div className={`problem ${p.open ? "open" : "fixed"}`}>
      <div className="problem-head">
        <b>{p.title}</b>
        {p.times > 1 && <span className="status warn">{p.times}×</span>}
        <span className="muted small">{p.kind === "fetch" ? "Download" : p.kind === "check" ? "Validation check" : "Build"}</span>
      </div>
      <p className="small" style={{ margin: "4px 0" }}>{p.explain}</p>
      {p.summary && p.summary !== p.explain && <p className="small" style={{ margin: "4px 0" }}><code>{p.summary}</code></p>}
      {p.examples.length > 0 && (
        <details className="small">
          <summary>What failed ({p.examples.length}{p.examples.length >= 12 ? "+" : ""} lines)</summary>
          <ul className="problem-rows">{p.examples.map((e, i) => <li key={i}><code>{e}</code></li>)}</ul>
        </details>
      )}
      <p className="small ink-2" style={{ margin: "4px 0" }}>
        {repeats(p)}{!p.open && p.fixed_at ? ` Fixed by the run of ${when(p.fixed_at)}.` : ""}
      </p>
      {p.open && <p className="small" style={{ margin: "4px 0" }}>{p.todo}</p>}
      <p className="small" style={{ margin: "4px 0" }}>
        <button onClick={copy}>{copied ? "Copied" : "Copy details"}</button>
        {p.build_id && <span className="muted"> Report: <code>var\warehouse\reports\{p.build_id}.md</code></span>}
      </p>
    </div>
  );
}

export default function ProblemsCard() {
  const [list, setList] = useState<Problem[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { api.problems().then(setList).catch((e) => setError(String(e.message || e))); }, []);
  const open = (list ?? []).filter((p) => p.open);
  const fixed = (list ?? []).filter((p) => !p.open);
  return (
    <div className="card" id="problems">
      <h2>Problems{open.length ? ` (${open.length} open)` : ""}</h2>
      {error && <p className="error">{error}</p>}
      {list && open.length === 0 && (
        <p className="ink-2" style={{ marginTop: 0 }}>No open problems: the latest refresh passed{fixed.length ? " and fixed everything listed below" : ""}.</p>
      )}
      {open.length > 0 && (
        <p className="ink-2" style={{ marginTop: 0 }}>
          From the refresh log, latest first. A problem stays open until a later refresh passes (or, for a download, fetches that source).
        </p>
      )}
      {open.map((p) => <ProblemItem key={p.key} p={p} />)}
      {fixed.length > 0 && (
        <details style={{ marginTop: 8 }}>
          <summary>Fixed ({fixed.length})</summary>
          {fixed.map((p) => <ProblemItem key={p.key} p={p} />)}
        </details>
      )}
    </div>
  );
}

// Problems already shown in the banner (by key), kept in this browser. A problem goes in once
// it has been hidden with the cross or seen on Data status, so the banner names each failure
// once and then leaves it to the Problems list. A key is dropped when its problem is fixed,
// so the same failure coming back later shows again.
const SEEN = "worldmodel-problems-seen";
function readSeen(): string[] {
  try { return JSON.parse(localStorage.getItem(SEEN) || "[]"); } catch { return []; }
}
function writeSeen(keys: string[]) {
  try { localStorage.setItem(SEEN, JSON.stringify(keys)); } catch { /* private window: shows again next time */ }
}

// One line at the top of every page while a new problem is open (switchable in Settings).
export function ProblemBanner() {
  const s = useSettings();
  const path = usePathname();
  const [open, setOpen] = useState<Problem[]>([]);
  const [seen, setSeen] = useState<string[]>([]);
  useEffect(() => {
    if (!s.problem_banner) return;
    api.problems().then((l) => {
      const now = l.filter((p) => p.open);
      const keys = new Set(now.map((p) => p.key));
      // Data status lists them all, so being there counts as having seen them.
      const kept = path === "/data" ? [...keys] : readSeen().filter((k) => keys.has(k));
      writeSeen(kept);
      setSeen(kept);
      setOpen(now);
    }).catch(() => setOpen([]));
  }, [path, s.problem_banner]);
  const fresh = open.filter((p) => !seen.includes(p.key));
  if (!s.problem_banner || fresh.length === 0 || path === "/data") return null;
  const p = fresh[0];
  const hide = () => { const all = [...new Set([...seen, ...fresh.map((x) => x.key)])]; writeSeen(all); setSeen(all); };
  return (
    <div className="banner critical" role="status">
      New refresh problem: <b>{p.title}</b>{p.times > 1 ? ` (${p.times} times, ${p.in_a_row} in a row)` : ""}
      {fresh.length > 1 ? ` and ${fresh.length - 1} more` : ""}. The app keeps the last good data.{" "}
      See <Link href="/data#problems">Data status</Link>.{" "}
      <button className="link" onClick={hide} title="Hide until a new problem comes up; they stay listed on Data status">Hide</button>
    </div>
  );
}
