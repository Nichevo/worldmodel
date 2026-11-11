"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { toast } from "@/lib/ai";
import { api, type InboxState, type TodoItem, type TodoList } from "@/lib/api";
import { saveSettings, useSettings } from "@/lib/settings";
import { InboxCard, JobPanel, KeyInput, useJob } from "@/components/Upkeep";

// Everything that needs you to keep the data coming, in one ranked list: files to choose a
// source for, files to load or save, sources failing, keys and forms. Each can be dealt with
// here, marked done (hidden until it changes), snoozed, or its source switched off.

const KIND_TEXT: Record<TodoItem["kind"], string> = {
  inbox: "Choose a source", load: "Ready to load", download: "Save a file", failing: "Failing", check: "A check failed",
  key: "Add a key", form: "Fill in a form",
};

export default function TodoPage() {
  const s = useSettings();
  const [list, setList] = useState<TodoList | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showHidden, setShowHidden] = useState(false);
  const { job, start } = useJob();
  const busy = !!job?.running;
  const load = useCallback(() => api.todo().then((d) => { setList(d); setError(null); }).catch((e) => setError(String(e.message || e))), []);
  useEffect(() => { load(); }, [load, s.sources_off]);
  const mark = (key: string, action: "done" | "snooze" | "clear", days?: number) =>
    api.todoMark(key, action, days).then(setList).catch((e) => toast(String(e.message || e)));
  const switchOff = (sid: string) => {
    const off = new Set((s.sources_off || "").split(",").filter(Boolean));
    off.add(sid);
    saveSettings({ sources_off: [...off].join(",") }).then(() => toast("Switched off; it is never fetched now (Data status > Every source turns it back on)"));
  };
  const due = (list?.items ?? []).filter((i) => i.kind === "download").map((i) => i.source_id!).filter(Boolean);
  return (
    <div className="grid">
      <div>
        <h1>To do</h1>
        <p className="ink-2" style={{ marginTop: 0 }}>
          What the data needs from you, most useful first. Things the app is handling by itself (retrying a site, waiting until a
          source is due) are left out. <Link href="/data">Data status</Link> has every source&apos;s details.
        </p>
      </div>
      <div className="chips-row">
        <button disabled={busy || due.length === 0} onClick={() => start("get", due)}
          title="Opens each due file's download page in your browser, one tab each, then files and loads each file as it lands in Downloads or the inbox">
          Get all {due.length || ""} due files</button>
        <button disabled={busy} onClick={() => start("inbox")} title="File what is in the inbox and recent downloads, load it and rebuild">File them now</button>
        <button disabled={busy} onClick={() => start("refresh")} title="Fetch every source that is due, then rebuild, as refresh.bat does">Refresh everything</button>
        <span className="muted small">Or from PowerShell: <code>.\get.bat</code>, <code>.\load.bat</code>, <code>.\refresh.bat</code></span>
      </div>
      <JobPanel job={job} onDone={load} />
      {error && <p className="error">{error}</p>}
      {!list ? <p className="muted">Loading…</p> : list.items.length === 0 ? (
        <div className="card"><p style={{ margin: 0 }}>Nothing needs you. Every source is loaded or being handled by itself.</p></div>
      ) : (
        <div className="todo-list">
          {list.items.map((it) => <Item key={it.key} it={it} busy={busy} start={start} mark={mark} switchOff={switchOff} reload={load} />)}
        </div>
      )}
      {list && list.hidden.length > 0 && (
        <div>
          <button className="link small" onClick={() => setShowHidden(!showHidden)}>
            {showHidden ? "Hide" : "Show"} {list.hidden.length} marked done or snoozed</button>
          {showHidden && <ul className="small">{list.hidden.map((h) => (
            <li key={h.key}>{h.title}: {h.mark?.snooze_until ? `snoozed until ${h.mark.snooze_until}` : `marked done ${h.mark?.at ?? ""}`}
              {" "}<button className="link small" onClick={() => mark(h.key, "clear")}>Show again</button></li>))}</ul>}
        </div>
      )}
      <InboxCard start={() => start("inbox")} busy={busy} />
    </div>
  );
}

function Item({ it, busy, start, mark, switchOff, reload }: {
  it: TodoItem; busy: boolean; start: (k: "get" | "load" | "refresh", s?: string[]) => void;
  mark: (key: string, a: "done" | "snooze" | "clear", d?: number) => void; switchOff: (sid: string) => void; reload: () => void;
}) {
  return (
    <div className={`card todo-item todo-${it.kind}`}>
      <div className="card-head">
        <h3 style={{ margin: 0 }}><span className="pill">{KIND_TEXT[it.kind]}</span> {it.title}</h3>
        <span className="card-actions">
          <button className="link small" onClick={() => mark(it.key, "done")} title="Hide it until something about it changes">Done</button>
          <button className="link small" onClick={() => mark(it.key, "snooze", 7)}>Snooze a week</button>
          <button className="link small" onClick={() => mark(it.key, "snooze", 30)}>a month</button>
          {it.source_id && it.kind !== "inbox" && <button className="link small" onClick={() => switchOff(it.source_id!)}
            title={it.uses ? `Never fetch it again; ${it.uses} indicators stay as last loaded` : "Never fetch it again"}>Switch the source off</button>}
        </span>
      </div>
      <p className="small" style={{ margin: "4px 0" }}>{it.why}{it.times && it.times > 1 ? ` (${it.times} refreshes in a row)` : ""}</p>
      {it.what && <p className="small ink-2" style={{ margin: "4px 0" }}>{it.what}</p>}
      {it.todo_text && <p className="small ink-2" style={{ margin: "4px 0" }}>{it.todo_text}</p>}
      {it.uses > 0 && <p className="small muted" style={{ margin: "4px 0" }}>Feeds {it.uses} indicator{it.uses === 1 ? "" : "s"}: {it.uses_names.join(", ")}{it.uses > it.uses_names.length ? "…" : ""}</p>}
      <div className="chips-row small">
        {it.kind === "inbox" && <Assign it={it} reload={reload} />}
        {it.link && it.kind !== "form" && <a href={it.link} target="_blank" rel="noreferrer">{it.kind === "key" ? "Sign up" : "Open the download page"}</a>}
        {it.kind === "form" && <Link href="/settings">Open Settings</Link>}
        {it.button === "get" && <button className="small" disabled={busy} onClick={() => start("get", [it.source_id!])}
          title="Opens the page and watches Downloads and the inbox; the file is filed and loaded when it lands">Get it</button>}
        {it.button === "load" && <button className="small" disabled={busy} onClick={() => start("load", [it.source_id!])}>Load it now</button>}
        {it.button === "refresh" && <button className="small" disabled={busy} onClick={() => start("refresh", [it.source_id!])}>Try again now</button>}
        {it.kind === "key" && <KeyInput envs={it.env ?? []} onSaved={reload} />}
        {it.command && <span>or run <code>{it.command}</code></span>}
        {it.folder && it.kind === "download" && <span className="muted">or save it in the inbox, Downloads or <code>{it.folder}</code></span>}
      </div>
    </div>
  );
}

function Assign({ it, reload }: { it: TodoItem; reload: () => void }) {
  const [sources, setSources] = useState<InboxState["sources"]>([]);
  const [pick, setPick] = useState(it.candidates?.[0] ?? "");
  useEffect(() => { api.inbox().then((b) => setSources(b.sources)).catch(() => {}); }, []);
  const go = () => api.inboxAssign(it.name!, pick).then(() => { toast("Filed; loading it now"); reload(); }).catch((e) => toast(String(e.message || e)));
  return (
    <>
      <select value={pick} onChange={(e) => setPick(e.target.value)} aria-label="Source">
        <option value="">Choose a source…</option>
        {sources.map((s) => <option key={s.source_id} value={s.source_id}>{s.name}</option>)}
      </select>
      <button className="small" disabled={!pick} onClick={go}>File it</button>
    </>
  );
}
