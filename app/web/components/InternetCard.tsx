"use client";

import { useCallback, useMemo, useState } from "react";
import CardAsk from "@/components/CardAsk";
import EChart from "@/components/EChart";
import Help from "@/components/Help";
import type { Indicator, SeriesRow } from "@/lib/api";
import { points, useSavePicture, useSeries } from "@/lib/cards";
import { lines } from "@/lib/climate";

// A country's internet: how fast it is (Ookla Speedtest, fixed broadband and mobile,
// each quarter) and how many are connected (internet users, broadband and mobile
// subscriptions).

const SPEEDS = [["internet_fixed_down_mbps_q", "internet_fixed_down_mbps", "Fixed broadband"], ["internet_mobile_down_mbps_q", "internet_mobile_down_mbps", "Mobile"]];
const CONNECTED = [["internet_users_share", "People using the internet (%)"], ["broadband_subscriptions_per_100", "Fixed broadband subscriptions per 100 people"],
  ["mobile_subscriptions_per_100", "Mobile subscriptions per 100 people"]];
const ALL = [...SPEEDS.flatMap((s) => [s[0], s[1]]), "internet_fixed_up_mbps", "internet_mobile_up_mbps", "internet_fixed_latency_ms", "internet_mobile_latency_ms", ...CONNECTED.map((c) => c[0])];
type View = "speed" | "connected";

// "2024-Q2" -> "2024-04", "2024" -> "2024-01": a month the time axis can place.
function month(period: string): string {
  const m = /^(\d{4})-Q([1-4])$/.exec(period);
  return m ? `${m[1]}-${String(3 * +m[2] - 2).padStart(2, "0")}` : `${period.slice(0, 4)}-01`;
}
const monthly = (rows: SeriesRow[] | undefined): [string, number][] =>
  (rows ?? []).map((r) => [month(r.period), r.value] as [string, number]).sort((a, b) => a[0].localeCompare(b[0]));

export default function InternetCard({ entity, name, indicators }: { entity: string; name: string; indicators: Map<string, Indicator> }) {
  const { data, error } = useSeries(entity, ALL, indicators);
  const [pick, setPick] = useState<View>("speed");
  const { onReady, save, ask } = useSavePicture();
  const speed = useMemo(() => SPEEDS.map(([q, a, label]) => ({ name: label, points: monthly(data?.get(q)?.length ? data.get(q) : data?.get(a)) }))
    .filter((s) => s.points.length), [data]);
  const connected = useMemo(() => CONNECTED.map(([id, label]) => ({ name: label, points: points(data?.get(id)).map((p) => [p[0], p[1]] as [number, number]) }))
    .filter((s) => s.points.length), [data]);
  const view: View = pick === "connected" && connected.length ? "connected" : speed.length ? "speed" : "connected";
  const option = useCallback(() => (view === "speed" ? lines(speed, "Mbps", { time: true, decimals: 0 }) : lines(connected, "", { decimals: 1 })), [view, speed, connected]);
  if (!data || (!speed.length && !connected.length)) {
    return error ? <div className="card"><h3>Internet</h3><p className="error">{error}</p></div> : null;
  }
  const last = (id: string) => { const r = data.get(id); return r?.length ? r[r.length - 1] : null; };
  const facts = (["fixed", "mobile"] as const).map((k) => {
    const up = last(`internet_${k}_up_mbps`), lat = last(`internet_${k}_latency_ms`);
    const bits = [up ? `upload ${up.value.toFixed(0)} Mbps` : "", lat ? `latency ${lat.value.toFixed(0)} ms` : ""].filter(Boolean);
    return bits.length ? `${k === "fixed" ? "Fixed broadband" : "Mobile"} in ${(up ?? lat)!.period}: ${bits.join(", ")}` : null;
  }).filter(Boolean);
  const ids = view === "speed" ? SPEEDS.map((s) => s[0]) : CONNECTED.map((c) => c[0]);
  const sources = ids.map((id) => indicators.get(id)?.sources[0]?.source_id);
  const title = view === "speed" ? "Download speed in Speedtest by Ookla tests" : "Connected to the internet";
  const note = view === "speed" ? "Mean of tests, weighted by tests, each quarter. Not Ookla's published medians, which run lower." : "";
  return (
    <div className="card" id="internet">
      <div className="card-head">
        <h3>Internet <Help note="internet" /></h3>
        <span>
          <CardAsk onAsk={() => ask(`${title}: ${name}`, note, sources, entity)} />{" "}
          <button className="link small" title="Save this chart as a picture, with its sources" onClick={() => save(`${title}: ${name}`, note, sources, "internet", view, entity)}>Save picture</button>
        </span>
      </div>
      <div className="chips-row small">
        <div className="seg">
          <button className={view === "speed" ? "on" : ""} aria-pressed={view === "speed"} disabled={!speed.length} onClick={() => setPick("speed")}>Speed</button>
          <button className={view === "connected" ? "on" : ""} aria-pressed={view === "connected"} disabled={!connected.length} onClick={() => setPick("connected")}>Connected</button>
        </div>
      </div>
      <EChart option={option} height={280} label={`${title} in ${name}`} onReady={onReady} />
      {view === "speed" && facts.length ? <p className="small ink-2">{facts.join(". ")}.</p> : null}
      <p className="caption">
        {view === "speed"
          ? "Megabits a second. Speedtest by Ookla open data (CC BY-NC-SA 4.0), map tiles summed by country here: the mean of tests, which runs higher than the medians Ookla publishes in its Speedtest Global Index."
          : `Sources: ${[...new Set(ids.map((id) => indicators.get(id)?.sources[0]?.source_name).filter(Boolean))].join("; ")}. Subscriptions can pass 100: many people have two phones.`}
      </p>
    </div>
  );
}
