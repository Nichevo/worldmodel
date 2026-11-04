"use client";

import Help from "@/components/Help";
import { useEffect, useMemo, useState } from "react";
import CardAsk from "@/components/CardAsk";
import { api, type EventRow } from "@/lib/api";
import { openAsk, eventsText } from "@/lib/ai";
import { kindLabel, kindVar, sizeText, when } from "@/lib/events";

// The country's dealings with others and with world bodies, newest first, filtered by kind.
const KINDS = ["sanction", "imf", "trade_dispute", "treaty", "court", "summit", "un"];

export default function BetweenCard({ entity, name }: { entity: string; name: string }) {
  const [rows, setRows] = useState<EventRow[] | null>(null);
  const [kind, setKind] = useState<string>("");
  const [all, setAll] = useState(false);
  useEffect(() => {
    let live = true;
    setRows(null);
    api.events({ entities: [entity], kinds: KINDS }).then((r) => live && setRows(r.filter((e) => e.subkind !== "veto" && e.subkind !== "council_seat")))
      .catch(() => live && setRows([]));
    return () => { live = false; };
  }, [entity]);
  const counts = useMemo(() => {
    const c = new Map<string, number>();
    for (const e of rows ?? []) c.set(e.kind, (c.get(e.kind) ?? 0) + 1);
    return c;
  }, [rows]);
  if (!rows?.length) return null;
  const shown = rows.filter((e) => !kind || e.kind === kind).slice().reverse();
  const visible = all ? shown : shown.slice(0, 25);
  return (
    <div className="card" id="between">
      <div className="card-head">
        <h3>Between countries <Help note="between" /></h3>
        <CardAsk onAsk={() => openAsk({ title: `${name}: dealings with other countries and world bodies`, entity,
          parts: [{ key: "events", kind: "events", label: "Sanctions, IMF programmes, disputes, treaties, courts, summits", text: eventsText(shown.slice(0, 200)) }] })} />
      </div>
      <div className="chips-row small" role="group" aria-label="Which kind">
        <button className={`chip ${kind ? "off" : ""}`} aria-pressed={!kind} onClick={() => setKind("")}>All ({rows.length})</button>
        {KINDS.filter((k) => counts.get(k)).map((k) => (
          <button key={k} className={`chip kind ${!kind || kind === k ? "" : "off"}`} aria-pressed={kind === k} style={{ borderColor: kindVar(k) }}
            onClick={() => setKind(kind === k ? "" : k)}><i style={{ background: kindVar(k) }} />{kindLabel(k)} ({counts.get(k)})</button>
        ))}
      </div>
      <div style={{ overflowX: "auto" }}>
        <table className="small">
          <tbody>
            {visible.map((e) => (
              <tr key={e.event_id}>
                <td className="num" style={{ whiteSpace: "nowrap" }}>{when(e)}</td>
                <td><i className="dot" style={{ background: kindVar(e.kind) }} /> {e.url ? <a href={e.url} target="_blank" rel="noreferrer">{e.title}</a> : e.title}
                  {sizeText(e) ? <span className="muted"> · {sizeText(e)}</span> : null}
                  {e.detail ? <div className="muted">{e.detail}</div> : null}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {shown.length > 25 && <button className="link small" onClick={() => setAll(!all)}>{all ? "Show fewer" : `Show all ${shown.length}`}</button>}
      <p className="caption">Newest first. Sanctions need the Global Sanctions Data Base file (Data status, files you download yourself); the rest load on refresh.</p>
    </div>
  );
}
