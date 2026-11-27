"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import CardAsk from "@/components/CardAsk";
import EChart from "@/components/EChart";
import Help from "@/components/Help";
import { api, type Indicator, type SeriesRow } from "@/lib/api";
import { useSavePicture } from "@/lib/cards";
import { HOUSE_DEFAULT, HOUSE_MEASURES, HOUSE_SOURCE, houseOption, houseValue, houseRow, priceLevel, shown, toMs,
  type HouseLine, type Pt, type Show } from "@/lib/houseprices";
import { entityColors } from "@/lib/look";

// House prices over time for a country and each of its regions (New Zealand monthly from 1980,
// Australia quarterly), on one chart: pick the figure, the places, and whether to show dollars,
// today's dollars, the change on a year earlier or an index. A table gives each place's latest
// value, its change over one and five years and how far it sits below its peak.
// On a region's own page the region and its country are drawn bold.
const FROM = [0, 2000, 2010, 2015, 2020];

export default function RegionHousePricesCard({ entity, name, country, indicators }:
  { entity: string; name: string; country: "NZL" | "AUS"; indicators: Map<string, Indicator> }) {
  const measures = useMemo(() => HOUSE_MEASURES[country].filter((m) => indicators.get(m.id)?.available), [country, indicators]);
  const [pick, setPick] = useState<string | null>(null);
  const m = measures.find((x) => x.id === pick) ?? measures[0];
  const [places, setPlaces] = useState<{ id: string; name: string }[]>([]);
  const [chosen, setChosen] = useState<string[] | null>(null);
  const [rows, setRows] = useState<SeriesRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [show, setShow] = useState<Show>("value");
  const [from, setFrom] = useState(0);
  const [inflation, setInflation] = useState<[number, number][]>([]);
  const { onReady, save, ask } = useSavePicture();

  useEffect(() => {
    let live = true;
    api.regions(country, { indicator: m?.yearly ?? "none" })
      .then((d) => live && setPlaces([{ id: country, name: country === "NZL" ? "New Zealand" : "Australia" },
        ...d.regions.map((r) => ({ id: r.entity_id, name: r.name }))]))
      .catch(() => live && setPlaces([]));
    return () => { live = false; };
  }, [country, m?.yearly]);
  const ids = useMemo(() => places.map((p) => p.id), [places]);
  useEffect(() => {
    if (!m || !ids.length) return;
    let live = true;
    setRows(null);
    api.series(m.id, ids).then((r) => { if (live) { setRows(r); setError(null); } })
      .catch((e) => live && setError(String(e.message || e)));
    return () => { live = false; };
  }, [m, ids]);
  useEffect(() => {
    let live = true;
    api.series("inflation", [country]).then((r) => live && setInflation(r.map((x) => [+x.period, x.value] as [number, number])))
      .catch(() => live && setInflation([]));
    return () => { live = false; };
  }, [country]);

  const level = useMemo(() => priceLevel(inflation), [inflation]);
  const perYear = m?.id.endsWith("_q") ? 4 : 12;
  const byPlace = useMemo(() => {
    const out = new Map<string, Pt[]>();
    for (const r of rows ?? []) {
      if (!out.has(r.entity_id)) out.set(r.entity_id, []);
      out.get(r.entity_id)!.push([toMs(r.period), r.value]);
    }
    out.forEach((v) => v.sort((a, b) => a[0] - b[0]));
    return out;
  }, [rows]);
  const held = places.filter((p) => byPlace.get(p.id)?.length);
  const defaults = entity === country ? HOUSE_DEFAULT[country] : [country, entity];
  const on = (chosen ?? defaults).filter((id) => byPlace.has(id));
  const colors = useMemo(() => {
    const c = entityColors(held.map((p) => p.id));
    return new Map(held.map((p, i) => [p.id, c[i]]));
  }, [held]);
  const fromMs = from ? Date.UTC(from, 0, 1) : 0;
  const what: Show = show === "real" && (!level || !m?.money) ? "value" : show;
  const lines: HouseLine[] = useMemo(() => on.map((id) => {
    const all = byPlace.get(id) ?? [];
    const pts = shown(all, what, perYear, fromMs, level).filter((p) => p[0] >= fromMs);
    return { id, name: places.find((p) => p.id === id)?.name ?? id, color: colors.get(id) ?? "", points: pts, bold: id === entity || id === country };
  }).filter((l) => l.points.length), [on, byPlace, what, perYear, fromMs, level, places, colors, entity, country]);
  const option = useCallback(() => houseOption(lines, m?.unit ?? "", what), [lines, m, what]);
  const table = useMemo(() => held.map((p) => houseRow(p.id, p.name, byPlace.get(p.id) ?? [], perYear)).filter((r) => r !== null)
    .sort((a, b) => (a!.id === country ? -1 : b!.id === country ? 1 : b!.latest - a!.latest)), [held, byPlace, perYear, country]);

  if (!measures.length) return null;
  const toggle = (id: string) => setChosen((c) => { const cur = (c ?? defaults).filter((x) => byPlace.has(x)); return cur.includes(id) ? cur.filter((x) => x !== id) : [...cur, id]; });
  const title = `House prices by region: ${m.label.toLowerCase()}`;
  const showLabel = { value: m.money ? "in dollars of the day" : "", real: "in today's dollars (after consumer price inflation)",
    change: "change on a year earlier, %", index: `index, ${from || "first month"} = 100` }[what];
  const note = `${m.note} ${showLabel ? `Shown ${showLabel}.` : ""}`.trim();
  const month = (ms: number) => new Date(ms).toLocaleDateString(undefined, { month: "short", year: "numeric", timeZone: "UTC" });
  const pct = (v: number | null) => v === null ? "" : `${v > 0 ? "+" : ""}${v.toFixed(1)}%`;
  const tone = (v: number | null) => (v === null ? undefined : v >= 0 ? "var(--good, #2e7d32)" : "var(--bad, #c62828)");

  return (
    <div className="card" id="house-prices-regions">
      <div className="card-head">
        <h3>House prices by region <Help note="house_regions" /></h3>
        {lines.length > 0 && <CardAsk onAsk={() => ask(`${title} (${name})`, note, [indicators.get(m.id)?.sources[0]?.source_id], entity)} />}
        {lines.length > 0 && <button className="link small" title="Save this chart as a picture, with its sources"
          onClick={() => save(`${title} (${name})`, note, [indicators.get(m.id)?.sources[0]?.source_id], "house-prices", country, m.id)}>Save picture</button>}
      </div>
      <div className="chips-row small">
        <label>Figure{" "}
          <select value={m.id} onChange={(e) => setPick(e.target.value)}>
            {measures.map((x) => <option key={x.id} value={x.id}>{x.label}</option>)}
          </select>
        </label>
        <div className="seg" role="group" aria-label="Show as">
          {([["value", m.money ? "Dollars" : "Values"], ["real", "Today's dollars"], ["change", "Change in a year"], ["index", "Index"]] as [Show, string][])
            .filter(([k]) => k !== "real" || (m.money && level))
            .map(([k, label]) => <button key={k} className={what === k ? "on" : ""} aria-pressed={what === k} onClick={() => setShow(k)}>{label}</button>)}
        </div>
        <label>From{" "}
          <select value={from} onChange={(e) => setFrom(+e.target.value)}>
            {FROM.map((y) => <option key={y} value={y}>{y || "the start"}</option>)}
          </select>
        </label>
      </div>
      <div className="chips-row small" role="group" aria-label="Places">
        {held.map((p) => {
          const sel = on.includes(p.id);
          return <button key={p.id} className={`chip${sel ? " on" : ""}`} aria-pressed={sel} onClick={() => toggle(p.id)}
            style={sel ? { borderColor: colors.get(p.id), boxShadow: `inset 3px 0 0 ${colors.get(p.id)}` } : undefined}>{p.name}</button>;
        })}
        {held.length > 1 && <>
          <button className="link small" onClick={() => setChosen(held.map((p) => p.id))}>All</button>
          <button className="link small" onClick={() => setChosen([country])}>Just {country === "NZL" ? "New Zealand" : "Australia"}</button>
        </>}
      </div>
      {error && <p className="error">{error}</p>}
      {!error && rows === null && <p className="muted">Loading…</p>}
      {rows !== null && !held.length && <p className="muted">No {m.label.toLowerCase()} figures yet: they come with a refresh.</p>}
      {lines.length > 0 && <EChart option={option} height={360} label={`${title} in ${name}`} onReady={onReady} />}
      {table.length > 0 && (
        <div style={{ overflowX: "auto" }}>
          <table className="summary-table small">
            <thead><tr><th>Place</th><th className="num">Latest</th><th className="num">In a year</th><th className="num">In 5 years</th>
              <th className="num">Peak</th><th className="num">Below peak</th></tr></thead>
            <tbody>{table.map((r) => (
              <tr key={r!.id} style={r!.id === entity ? { fontWeight: 600 } : undefined}>
                <td>{r!.id === country ? r!.name : <Link href={`/entity/${r!.id}`}>{r!.name}</Link>}</td>
                <td className="num"><b>{houseValue(r!.latest, m.unit)}</b> <span className="muted">{month(r!.at)}</span></td>
                <td className="num" style={{ color: tone(r!.y1) }}>{pct(r!.y1)}</td>
                <td className="num" style={{ color: tone(r!.y5) }}>{pct(r!.y5)}</td>
                <td className="num">{houseValue(r!.peak, m.unit)} <span className="muted">{month(r!.peakAt)}</span></td>
                <td className="num">{r!.peak > r!.latest ? pct(100 * (r!.latest / r!.peak - 1)) : "at peak"}</td>
              </tr>))}</tbody>
          </table>
        </div>
      )}
      <p className="caption">{m.note}{what === "real" ? " Today's dollars use the country's yearly consumer price inflation." : ""}
        {" "}Source: {HOUSE_SOURCE[country]}. <Link href={`/regions?country=${country}`}>All figures on a map of the regions</Link>.</p>
    </div>
  );
}
