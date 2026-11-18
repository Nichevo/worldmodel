"use client";

import Link from "next/link";
import { Fragment, useEffect, useState } from "react";
import CardAsk from "@/components/CardAsk";
import CountryChoice from "@/components/CountryChoice";
import IndicatorSelect from "@/components/IndicatorSelect";
import { openAsk } from "@/lib/ai";
import type { Indicator } from "@/lib/api";
import { formatValue } from "@/lib/format";
import { peersApi, placeColour, type PeerRow, type Peers } from "@/lib/peers";

// A country page's "How it ranks among…": for each measure the best in the group, this country
// with its rank (cell coloured green for near the top to red for near the bottom), the group's
// middle and the worst, each with its actual value. Click a row for the whole ranked list.
const KEY = "peers.v1";
type Saved = { group?: string; measures?: string[]; custom?: string[] };
const load = (): Saved => { try { return JSON.parse(localStorage.getItem(KEY) || "{}"); } catch { return {}; } };
const save = (s: Saved) => { try { localStorage.setItem(KEY, JSON.stringify({ ...load(), ...s })); } catch { /* private window */ } };

export default function PeersCard({ entity, name, indicators }: { entity: string; name: string; indicators: Indicator[] }) {
  const [group, setGroup] = useState<string | undefined>(undefined);
  const [measures, setMeasures] = useState<string[] | undefined>(undefined);
  const [custom, setCustom] = useState<string[]>([]);
  const [data, setData] = useState<Peers | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const [picking, setPicking] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => { const s = load(); setMeasures(s.measures); setCustom(s.custom ?? []); }, []);
  useEffect(() => {
    let live = true;
    setErr(null);
    peersApi.get(entity, group, measures, group === "custom" ? custom : undefined)
      .then((r) => live && setData(r)).catch((e) => live && setErr(String(e)));
    return () => { live = false; };
  }, [entity, group, measures, custom]);

  if (err && !data) return null;
  if (!data) return <div className="card"><div className="card-head"><h3>How it ranks</h3></div><p className="muted small">Loading…</p></div>;

  const fmt = (r: PeerRow, v: number) => formatValue(v, r.unit, r.decimals);
  const current = measures ?? data.default_measures.map((m) => m.indicator_id);
  const setM = (m: string[] | undefined) => { setMeasures(m); save({ measures: m }); };
  const groupName = data.group === "custom" ? "countries you picked" : (data.groups.find((g) => g.id === data.group)?.name ?? data.group).replace(/ \(\d+\)$/, "");
  const ask = () => openAsk({ title: `How ${name} ranks among ${groupName}`, entity, parts: [
    { key: "group", kind: "data", label: "Group", text: `${groupName}: ${data.members.map((m) => m.name).join(", ")}` },
    ...data.rows.map((r) => ({ key: r.indicator_id, kind: "data" as const, label: r.name,
      text: `${r.me ? `${name} ${fmt(r, r.me.value)} (${r.me.year}), #${r.me.rank} of ${r.of}` : `${name} has no figure`}; best ${r.best.name} ${fmt(r, r.best.value)}; middle ${fmt(r, r.middle)}; worst ${r.worst.name} ${fmt(r, r.worst.value)}; ${r.better} is better.` })),
    { key: "how", kind: "description", label: "How", text: "Each country's latest figure from the main source, kept within three years of the year most of the group report; ties share a rank." }] });

  const cell = (r: PeerRow, c: { name: string; value: number; year: number; tied?: number }) => (
    <><b>{fmt(r, c.value)}</b><span className="peers-who">{c.name}{c.tied && c.tied > 1 ? ` +${c.tied - 1} tied` : ""}{c.year !== r.year ? ` (${c.year})` : ""}</span></>);

  return (
    <div className="card peers-card" id="peers">
      <div className="card-head"><h3>How it ranks among…</h3>
        <span><CardAsk onAsk={ask} /> <button type="button" className="small" onClick={() => setPicking(!picking)} aria-expanded={picking}>Pick measures</button></span></div>
      <div className="chips-row" role="group" aria-label="Group to rank among">
        {[...data.groups, { id: "custom", name: "Pick countries", type: "custom" }].map((g) => (
          <button type="button" key={g.id} className={`chip peers-chip${g.id === data.group ? " on" : ""}`} aria-pressed={g.id === data.group}
            onClick={() => { setGroup(g.id); setOpen(null); }}>{g.name}</button>))}
      </div>
      {data.group === "custom" && (
        <div className="chips-row">
          {custom.map((c) => <span key={c} className="chip">{data.members.find((m) => m.entity_id === c)?.name ?? c}
            <button type="button" aria-label={`Remove ${c}`} onClick={() => { const n = custom.filter((x) => x !== c); setCustom(n); save({ custom: n }); }}>×</button></span>)}
          <CountryChoice value="" label="Add" onChange={(id) => { if (!custom.includes(id) && id !== entity) { const n = [...custom, id]; setCustom(n); save({ custom: n }); } }} />
        </div>)}
      {picking && (
        <div className="chips-row peers-pick">
          {current.map((m) => <span key={m} className="chip">{indicators.find((i) => i.indicator_id === m)?.name ?? m}
            <button type="button" aria-label={`Remove ${m}`} onClick={() => setM(current.filter((x) => x !== m))}>×</button></span>)}
          <IndicatorSelect indicators={indicators} value="" label="Add" onChange={(id) => id && !current.includes(id) && setM([...current, id])} />
          <button type="button" className="small" onClick={() => setM(undefined)}>Back to the usual set</button>
        </div>)}
      <p className="small muted" style={{ margin: "2px 0 6px" }}>
        {data.members.length} other {data.members.length === 1 ? "country" : "countries"}
        {data.group === "neighbours" ? ": those touching it, then the nearest across the sea (up to 3,000 km)" : ""}.
      </p>
      {data.rows.length === 0 ? <p className="muted small">No figures to compare for this group yet.</p> : (
        <div className="peers-scroll">
          <table className="peers-table">
            <thead><tr><th>Measure</th><th>Best</th><th>{name}</th><th>Middle</th><th>Worst</th></tr></thead>
            <tbody>
              {data.rows.map((r) => (
                <Fragment key={r.indicator_id}>
                  <tr className="peers-row" onClick={() => setOpen(open === r.indicator_id ? null : r.indicator_id)}
                    tabIndex={0} onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); setOpen(open === r.indicator_id ? null : r.indicator_id); } }}
                    aria-expanded={open === r.indicator_id}>
                    <th scope="row">{r.name}<span className="peers-who">{r.better} is better · {r.year}</span></th>
                    <td>{cell(r, r.best)}</td>
                    <td className="peers-me" style={r.me ? { background: placeColour(r.me.position) } : undefined}>
                      {r.me ? <>
                        <b>{fmt(r, r.me.value)}</b><span className="peers-rank">#{r.me.rank} of {r.of}{r.me.year !== r.year ? ` (${r.me.year})` : ""}</span>
                        <span className="peers-bar" aria-hidden="true"><i style={{ left: `${(1 - r.me.position) * 100}%`, background: placeColour(r.me.position, 1) }} /></span>
                      </> : <span className="muted">no figure</span>}
                    </td>
                    <td><b>{fmt(r, r.middle)}</b></td>
                    <td>{cell(r, r.worst)}</td>
                  </tr>
                  {open === r.indicator_id && (
                    <tr className="peers-list"><td colSpan={5}>
                      <ol>{r.ranked.map((c) => (
                        <li key={c.entity_id} value={c.rank} className={c.entity_id === entity ? "me" : ""}>
                          <Link href={`/entity/${c.entity_id}`}>{c.name}</Link> <b>{fmt(r, c.value)}</b>{c.year !== r.year ? <span className="muted"> ({c.year})</span> : null}
                        </li>))}</ol>
                    </td></tr>)}
                </Fragment>))}
            </tbody>
          </table>
        </div>)}
      <p className="caption">Best and worst follow which way is better for each measure. The coloured cell runs green (near the top) to red (near the bottom); the bar under it shows where {name} sits. Countries under 100,000 people are left out of made-up groups.</p>
    </div>
  );
}
