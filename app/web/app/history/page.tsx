"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { api, type HistoryEntry, type HistoryKind } from "@/lib/api";
import { useSettings } from "@/lib/settings";

// What you opened and looked at, by day: countries, popups, map views, pins and
// switched indicators. Star an entry to keep it as a bookmark, add a note to
// remember why. Kept only on this computer.
const KINDS: { id: HistoryKind | ""; label: string }[] = [
  { id: "", label: "Everything" },
  { id: "page", label: "Countries and pages" },
  { id: "view", label: "Map views" },
  { id: "pin", label: "Pins" },
  { id: "indicator", label: "Indicator switches" },
  { id: "fetch", label: "Fetches" },
];
const KIND_LABEL: Record<HistoryKind, string> = { page: "Page", view: "Map view", pin: "Pin", indicator: "Indicators", fetch: "Fetch" };

function dayLabel(day: string): string {
  const d = new Date(`${day}T12:00:00`);
  const today = new Date();
  const diff = Math.round((new Date(today.toDateString()).getTime() - new Date(d.toDateString()).getTime()) / 86_400_000);
  if (diff === 0) return "Today";
  if (diff === 1) return "Yesterday";
  return d.toLocaleDateString("en", { weekday: "long", day: "numeric", month: "long", year: "numeric" });
}

export default function HistoryPage() {
  const settings = useSettings();
  const [entries, setEntries] = useState<HistoryEntry[] | null>(null);
  const [q, setQ] = useState("");
  const [kind, setKind] = useState<HistoryKind | "">("");
  const [starred, setStarred] = useState(false);
  const [since, setSince] = useState("");
  const [until, setUntil] = useState("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    const t = setTimeout(() => {
      api.history({ q: q || undefined, kind: kind || undefined, starred, since: since || undefined, until: until || undefined, limit: 2000 })
        .then((e) => { if (live) { setEntries(e); setError(null); } })
        .catch((e) => live && setError(String(e.message || e)));
    }, 200);
    return () => { live = false; clearTimeout(t); };
  }, [q, kind, starred, since, until]);

  // Entries carry UTC times; group them by the local day they happened.
  const days = useMemo(() => {
    const out = new Map<string, HistoryEntry[]>();
    for (const e of entries ?? []) {
      const d = new Date(e.at);
      const key = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
      out.set(key, [...(out.get(key) ?? []), e]);
    }
    return [...out];
  }, [entries]);

  const update = (id: string, patch: Partial<HistoryEntry>) =>
    setEntries((cur) => cur?.map((e) => (e.id === id ? { ...e, ...patch } : e)) ?? cur);
  const star = (e: HistoryEntry) => {
    update(e.id, { star: !e.star });
    api.markHistory(e.id, { star: !e.star }).catch(() => update(e.id, { star: e.star }));
  };

  return (
    <div className="grid">
      <div>
        <h1>History</h1>
        <p className="ink-2" style={{ marginTop: 0 }}>
          What you opened and looked at, newest first. Click an entry to open it again; star it to keep it as a bookmark.
          Kept only on this computer{settings.history_paused ? "; logging is paused in Settings" : ""}. <Link href="/settings">Settings</Link>
        </p>
      </div>
      <div className="controls">
        <input type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search history and notes" aria-label="Search history" style={{ width: 260 }} />
        <select value={kind} onChange={(e) => setKind(e.target.value as HistoryKind | "")} aria-label="What">
          {KINDS.map((k) => <option key={k.id} value={k.id}>{k.label}</option>)}
        </select>
        <label className="small"><input type="checkbox" checked={starred} onChange={(e) => setStarred(e.target.checked)} /> Starred only</label>
        <label className="small">From <input type="date" value={since} onChange={(e) => setSince(e.target.value)} /></label>
        <label className="small">to <input type="date" value={until} onChange={(e) => setUntil(e.target.value)} /></label>
      </div>
      {error && <p className="error">{error}</p>}
      {entries && entries.length === 0 && <p className="muted">Nothing here yet{q || kind || starred || since || until ? " for these filters" : ""}.</p>}
      {days.map(([day, list]) => (
        <section key={day} className="card history-day">
          <h2>{dayLabel(day)} <span className="muted small">{list.length} {list.length === 1 ? "entry" : "entries"}</span></h2>
          <ul>
            {list.map((e) => <Row key={e.id} e={e} star={() => star(e)} saveNote={(note) => {
              update(e.id, { note });
              api.markHistory(e.id, { note }).catch(() => {});
            }} />)}
          </ul>
        </section>
      ))}
    </div>
  );
}

function Row({ e, star, saveNote }: { e: HistoryEntry; star: () => void; saveNote: (note: string) => void }) {
  const [editing, setEditing] = useState(false);
  const [note, setNote] = useState(e.note);
  const time = new Date(e.at).toLocaleTimeString("en", { hour: "2-digit", minute: "2-digit", hour12: false });
  return (
    <li className="history-row">
      <button className={`star${e.star ? " on" : ""}`} onClick={star} aria-pressed={e.star} aria-label={e.star ? "Unstar" : "Star"} title={e.star ? "Starred" : "Star to keep as a bookmark"}>
        {e.star ? "★" : "☆"}
      </button>
      <span className="muted small time">{time}</span>
      <span className="chip kind">{KIND_LABEL[e.kind]}{e.detail === "popup" ? " · popup" : ""}</span>
      <span className="title">{e.url ? <Link href={e.url}>{e.title}</Link> : e.title}</span>
      <button className="link small" onClick={() => setEditing(!editing)}>{e.note ? "Edit note" : "Note"}</button>
      {e.note && !editing && <div className="note small ink-2">{e.note}</div>}
      {editing && (
        <form className="note-form" onSubmit={(ev) => { ev.preventDefault(); saveNote(note.trim()); setEditing(false); }}>
          <input type="text" value={note} onChange={(ev) => setNote(ev.target.value)} placeholder="Why this mattered" maxLength={2000} autoFocus aria-label="Note" />
          <button type="submit">Save</button>
        </form>
      )}
    </li>
  );
}
