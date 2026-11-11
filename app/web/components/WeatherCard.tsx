"use client";

import { useCallback, useEffect, useState } from "react";
import CardAsk from "@/components/CardAsk";
import EChart from "@/components/EChart";
import { openAsk } from "@/lib/ai";
import { MONTHS, NORMAL_SUMMARY, normalsApi, normalsOption, type Normals } from "@/lib/climate";

// The year's weather: each month's average temperature inside its band from night-time low to
// daytime high, and its rainfall, as averaged over 1991-2020 and the whole country. With several
// countries, temperature or rainfall side by side. Hidden when there are no figures (a refresh loads them).
export default function WeatherCard({ entities, title, compact = false }: { entities: string[]; title?: string; compact?: boolean }) {
  const [cs, setCs] = useState<Normals[] | null>(null);
  const one = entities.length === 1;
  const [show, setShow] = useState<"both" | "temp" | "rain">(one ? "both" : "temp");
  const [from, setFrom] = useState(1);
  const key = entities.join(",");
  useEffect(() => {
    let live = true;
    normalsApi(entities).then((d) => live && setCs(d.countries)).catch(() => live && setCs([]));
    return () => { live = false; };
  }, [key]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (!one && show === "both") setShow("temp"); }, [one, show]);
  const option = useCallback(() => normalsOption(cs ?? [], show, from), [cs, show, from]);
  if (!cs) return compact ? null : <p className="muted small">Loading…</p>;
  if (!cs.length) return compact ? null : (
    <div className="card"><h3>{title ?? "Weather through the year"}</h3>
      <p className="muted small">No monthly figures yet: <code>.\refresh.bat</code> loads them from the World Bank (about 16 small requests).</p></div>
  );
  const f = (v: number | null, u: string) => (v === null ? "no data" : `${u === "mm" ? Math.round(v) : v.toFixed(1)} ${u}`);
  const ask = () => openAsk({ title: `${title ?? "Weather through the year"}: ${cs.map((c) => c.name).join(", ")}`, entity: one ? cs[0].entity_id : undefined, parts: cs.map((c) => ({
    key: c.entity_id, kind: "data" as const, label: `${c.name}, 1991-2020 monthly averages`,
    text: ["Month\tAverage °C\tHigh °C\tLow °C\tRain mm", ...MONTHS.map((m, i) => `${m}\t${f(c.temp[i], "")}\t${f(c.high[i], "")}\t${f(c.low[i], "")}\t${f(c.rain[i], "")}`)].join("\n"),
  })) });
  return (
    <div className="card" id="weather">
      <div className="card-head">
        <h3>{title ?? "Weather through the year"}</h3>
        <span className="card-actions">
          {!one && (
            <span className="seg small" role="group" aria-label="Show">
              {(["temp", "rain"] as const).map((k) => <button key={k} className={show === k ? "on" : ""} aria-pressed={show === k} onClick={() => setShow(k)}>{k === "temp" ? "Temperature" : "Rainfall"}</button>)}
            </span>
          )}
          {one && (
            <span className="seg small" role="group" aria-label="Show">
              {(["both", "temp", "rain"] as const).map((k) => <button key={k} className={show === k ? "on" : ""} aria-pressed={show === k} onClick={() => setShow(k)}>{{ both: "Both", temp: "Temperature", rain: "Rainfall" }[k]}</button>)}
            </span>
          )}
          <button className="link small" onClick={() => setFrom(from === 1 ? 7 : 1)} title="Start the chart in July, so a southern summer is in the middle">
            {from === 1 ? "Start in July" : "Start in January"}</button>
          <CardAsk onAsk={ask} />
        </span>
      </div>
      <EChart option={option} height={compact ? 260 : 320} label="Monthly temperature and rainfall, 1991-2020 averages" />
      <table className="small summary-table">
        <thead><tr><th />{cs.map((c) => <th key={c.entity_id} className="num">{c.name}</th>)}</tr></thead>
        <tbody>{NORMAL_SUMMARY.map(([k, label, u]) => (
          <tr key={k}><td>{label}</td>{cs.map((c) => <td key={c.entity_id} className="num">{f(c.summary[k] ?? null, u)}</td>)}</tr>
        ))}</tbody>
      </table>
      <p className="caption">
        Averages for 1991-2020 over the whole country{one ? "; the shaded band runs from the average night-time low to the average daytime high" : ""}.
        A big country&apos;s average hides its range: its coast and mountains differ. Source: World Bank Climate Change Knowledge Portal (CRU TS).
      </p>
    </div>
  );
}
