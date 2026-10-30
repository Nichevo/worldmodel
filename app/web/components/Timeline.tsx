"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { api, type EventRow } from "@/lib/api";
import { KINDS, kindLabel, kindVar, sizeText, when } from "@/lib/events";
import { SOURCE_SHORT } from "@/lib/format";

// A country's dated events, newest first: elections, leaders, coups, conflicts,
// sporting events, disasters, recessions and booms worked out from the data, notable
// episodes and your own milestones, with filters and a form to add a milestone.
const SHOWN = 80;

export default function Timeline({ entity, name, isGroup }: { entity: string; name: string; isGroup: boolean }) {
  const [rows, setRows] = useState<EventRow[] | null>(null);
  const [off, setOff] = useState<Set<string>>(new Set(["leader"]));
  const [q, setQ] = useState("");
  const [all, setAll] = useState(false);
  const [adding, setAdding] = useState(false);
  const load = () => api.events({ entities: [entity] }).then(setRows).catch(() => setRows([]));
  useEffect(() => { setRows(null); setAll(false); load(); }, [entity]); // eslint-disable-line react-hooks/exhaustive-deps

  const kinds = useMemo(() => {
    const n = new Map<string, number>();
    (rows ?? []).forEach((r) => n.set(r.kind, (n.get(r.kind) ?? 0) + 1));
    return KINDS.filter((k) => n.has(k.kind)).map((k) => ({ ...k, n: n.get(k.kind)! }));
  }, [rows]);
  const shown = useMemo(() => {
    const words = q.trim().toLowerCase();
    return (rows ?? []).filter((r) => !off.has(r.kind)
      && (!words || `${r.title} ${r.subkind ?? ""} ${r.place ?? ""} ${r.detail ?? ""}`.toLowerCase().includes(words))).reverse();
  }, [rows, off, q]);
  if (isGroup || rows === null) return null;
  const toggle = (k: string) => setOff((s) => { const n = new Set(s); n.has(k) ? n.delete(k) : n.add(k); return n; });
  const list = all ? shown : shown.slice(0, SHOWN);
  let decade = "";

  return (
    <div className="card" id="timeline">
      <h3>Timeline <span className="small ink-2">· {rows.length} events</span></h3>
      <div className="chips-row">
        {kinds.map((k) => (
          <button key={k.kind} className={`chip kind ${off.has(k.kind) ? "off" : ""}`} onClick={() => toggle(k.kind)}
            aria-pressed={!off.has(k.kind)} style={{ borderColor: kindVar(k.kind) }}>
            <i style={{ background: kindVar(k.kind) }} />{k.label} <span className="muted">{k.n}</span>
          </button>
        ))}
        <input type="search" placeholder="Search events" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search events" />
        <button onClick={() => setAdding((a) => !a)}>{adding ? "Close" : "Add a milestone"}</button>
      </div>
      {adding && <MilestoneForm entity={entity} done={() => { setAdding(false); load(); }} />}
      {rows.length === 0 && <p className="muted small">No events stored for {name} yet. A refresh loads elections, coups, conflicts, sporting events and disasters.</p>}
      <div className="timeline">
        {list.map((r) => {
          const d = `${r.start_date.slice(0, 3)}0s`;
          const head = d !== decade ? (decade = d) : null;
          return (
            <div key={`${r.event_id}|${r.entity_id}`}>
              {head && <div className="decade">{head}</div>}
              <div className="event">
                <span className="when">{when(r)}</span>
                <span className="tag" style={{ background: kindVar(r.kind) }} title={kindLabel(r.kind)} />
                <span className="what">
                  {r.url ? <a href={r.url} target="_blank" rel="noreferrer">{r.title}</a> : r.title}
                  {r.subkind && !r.title.toLowerCase().includes(r.subkind.toLowerCase()) ? <span className="muted"> · {r.subkind}</span> : null}
                  {sizeText(r) ? <span className="ink-2"> · {sizeText(r)}</span> : null}
                  {r.place ? <span className="muted"> · {r.place}</span> : null}
                  {r.detail && r.source_id !== "worldmodel" ? <span className="muted small"> · {r.detail}</span> : null}
                </span>
                <span className="actions small">
                  <Link href={`/events?tab=around&event=${encodeURIComponent(r.event_id)}&entity=${r.entity_id}`} title="An indicator in the years around this event">Around it</Link>
                  {r.milestone_id && <> · <button className="link" onClick={() => api.deleteMilestone(r.milestone_id!).then(load)}>Delete</button></>}
                  <span className="muted"> · {SOURCE_SHORT[r.source_id] ?? (r.source_id === "user" ? "You" : r.source_id)}</span>
                </span>
              </div>
            </div>
          );
        })}
      </div>
      {shown.length > list.length && <p><button onClick={() => setAll(true)}>Show all {shown.length}</button></p>}
      <p className="caption">
        Recessions, booms, inflation spikes and debt surges are worked out from the data (rules in episode_rules.yaml).
        Which kinds show on the charts above is set in <Link href="/settings#events">Settings</Link>. See every country&apos;s
        events by year on the <Link href="/events">Events</Link> page.
      </p>
    </div>
  );
}

export function MilestoneForm({ entity, done }: { entity: string; done: () => void }) {
  const [m, setM] = useState({ title: "", start_date: "", end_date: "", note: "", url: "" });
  const [error, setError] = useState<string | null>(null);
  const save = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      await api.addMilestone({ ...m, entity_id: entity, end_date: m.end_date || null, url: m.url || null });
      done();
    } catch (err) {
      setError(String((err as Error).message || err));
    }
  };
  const field = (k: keyof typeof m, label: string, type = "text", required = false) => (
    <label className="small">{label}
      <input type={type} required={required} value={m[k]} onChange={(e) => setM({ ...m, [k]: e.target.value })} />
    </label>
  );
  return (
    <form className="milestone-form" onSubmit={save}>
      {field("title", "What happened", "text", true)}
      {field("start_date", "Date", "date", true)}
      {field("end_date", "Until (optional)", "date")}
      {field("note", "Note")}
      {field("url", "Link")}
      <button type="submit">Save milestone</button>
      {error && <span className="error small"> {error}</span>}
      <span className="caption">Kept only on this computer (var\user\milestones.json); shown on charts and in the Events page.</span>
    </form>
  );
}
