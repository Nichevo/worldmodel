"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import CardAsk from "@/components/CardAsk";
import EChart from "@/components/EChart";
import WorldMap from "@/components/WorldMap";
import { openAsk } from "@/lib/ai";
import { get, send } from "@/lib/api";
import { cssVar } from "@/lib/colors";

// Transport > Congestion: how busy airports get hour by hour against their limits, road
// counting sites against normal, live traffic, and trains now with lateness by line.
// Everything here is read by the app's own collectors (Settings > Transport > Congestion).

export type AirportRow = {
  icao: string; iata: string | null; name: string; country: string | null; tz: string; lon: number; lat: number;
  per_day: number | null; peak_hour: number | null; peak_flights: number | null; record_hour: number | null;
  hourly_limit: number | null; annual_limit: number | null; slot_level: number | null; curfew: string | null;
  use: number | null; against: "limit" | "record" | null; gates: number | null; stands: number | null; days: number;
};
type CollectorStatus = { busy?: boolean; error?: string | null; round_started?: number; round_ended?: number; days_fetched?: number; gates_at?: number; delays_at?: number };
type AirportList = { airports: AirportRow[]; status: CollectorStatus; has_counts: boolean };
type AirportDetail = AirportRow & {
  profile: { weekday: (number | null)[]; weekend: (number | null)[]; weekday_arr: (number | null)[]; weekday_dep: (number | null)[]; days: number; from: string | null; to: string | null };
  daily: { day: string; flights: number; peak: number }[];
  limit: { source?: string; link?: string; note?: string } | null; curfew_hours: number[];
  eurocontrol: { month: string; flights?: number; days?: number; arr_delay_min?: number | null; taxi_add_min?: number | null; asma_add_min?: number | null }[];
  faa?: { now: { kind: string; reason: string; detail: string }[]; error?: string | null; at?: number };
};
type RoadSite = {
  id: string; name: string; source: string; source_name: string; link: string; hourly: boolean; country: string;
  daily: { day: string; vehicles: number }[]; vehicles_now: number | null; vs_normal: number | null;
  hours?: { weekday: (number | null)[]; weekend: (number | null)[]; weekday_mph: (number | null)[] | null; from: string | null; to: string | null };
  weekdays?: (number | null)[]; aadt?: (number | null)[];
};
type RoadStatus = CollectorStatus & { tomtom_key: boolean; nsw_key: boolean; sources: Record<string, { name: string; country: string; link: string }> };
type Feed = { id: string; name: string; operator: string; key: string; signup?: string; has_key: boolean; trains: number; read_at?: number; error?: string | null };
type Network = { id: string; name: string; operator: string; on_time_minutes: number; days: string[];
  daily: { day: string; late_pct: number | null; avg_delay_min: number | null }[];
  lines: { line: string; late_pct: number; avg_delay_min: number; readings: number }[];
  hours: { hour: number; late_pct: number | null; avg_delay_min: number | null }[] };
type TrainsPage = { feeds: Feed[]; networks: Network[]; late_minutes: number; punctuality: { network: string; source: string; points: [string, number][] }[] };

const HOURS = Array.from({ length: 24 }, (_, h) => `${String(h).padStart(2, "0")}:00`);
const WEEK = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const ask = (title: string, label: string, text: string) => openAsk({ title, parts: [{ key: title, kind: "data", label, text }] });
const n0 = (v: number | null | undefined) => (v == null ? "" : Math.round(v).toLocaleString());
const when = (t?: number) => (t ? new Date(t * 1000).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" }) : "never");
const useTone = (v: number | null) => (v == null ? "" : v >= 95 ? "tone-bad" : v >= 75 ? "tone-neutral" : "tone-good");
const axis = () => ({ axisLabel: { color: cssVar("--ink-2") }, splitLine: { lineStyle: { color: cssVar("--border") } } });

// ----------------------------------------------------------------------------- airports
function BusyHours({ d }: { d: AirportDetail }) {
  const option = useMemo(() => () => {
    const lim = d.hourly_limit;
    return {
      tooltip: { trigger: "axis" }, legend: { textStyle: { color: cssVar("--ink-2") } },
      grid: { left: 48, right: 16, top: 36, bottom: 32 },
      xAxis: { type: "category", data: HOURS, axisLabel: { color: cssVar("--ink-2"), interval: 2 } },
      yAxis: { type: "value", name: "flights an hour", ...axis() },
      series: [
        { type: "bar", name: "Weekday arrivals", stack: "wk", data: d.profile.weekday_arr, itemStyle: { color: cssVar("--series-1") },
          markArea: d.curfew_hours.length ? { silent: true, itemStyle: { color: cssVar("--ink-2"), opacity: 0.12 },
            data: d.curfew_hours.map((h) => [{ xAxis: HOURS[h] }, { xAxis: HOURS[h] }]) } : undefined },
        { type: "bar", name: "Weekday departures", stack: "wk", data: d.profile.weekday_dep, itemStyle: { color: cssVar("--series-2") },
          markLine: lim ? { symbol: "none", silent: true, data: [{ yAxis: lim, name: "Limit" }],
            lineStyle: { color: cssVar("--div-neg-3"), type: "dashed", width: 1.6 }, label: { formatter: `Limit ${lim} an hour`, color: cssVar("--div-neg-3") } }
            : d.record_hour ? { symbol: "none", silent: true, data: [{ yAxis: d.record_hour }], lineStyle: { color: cssVar("--ink-2"), type: "dotted" },
              label: { formatter: `Busiest hour seen: ${d.record_hour}`, color: cssVar("--ink-2") } } : undefined },
        { type: "line", name: "Weekend", data: d.profile.weekend, showSymbol: false, lineStyle: { width: 2, color: cssVar("--series-4") }, itemStyle: { color: cssVar("--series-4") } },
      ],
    } as never;
  }, [d]);
  return <EChart height={300} label={`${d.name}: flights by local hour`} option={option} />;
}

function FlightsByDay({ d }: { d: AirportDetail }) {
  const option = useMemo(() => () => ({
    tooltip: { trigger: "axis" }, legend: { textStyle: { color: cssVar("--ink-2") } },
    grid: { left: 52, right: 48, top: 36, bottom: 64 },
    xAxis: { type: "time", axisLabel: { color: cssVar("--ink-2") } },
    yAxis: [{ type: "value", name: "flights a day", ...axis() }, { type: "value", name: "busiest hour", axisLabel: { color: cssVar("--ink-2") }, splitLine: { show: false } }],
    dataZoom: [{ type: "slider", bottom: 8, height: 18 }, { type: "inside", zoomOnMouseWheel: "shift" }],
    series: [
      { type: "line", name: "Flights", data: d.daily.map((r) => [r.day, r.flights]), showSymbol: false, lineStyle: { width: 1.8, color: cssVar("--series-1") }, itemStyle: { color: cssVar("--series-1") } },
      { type: "line", name: "Busiest hour", yAxisIndex: 1, data: d.daily.map((r) => [r.day, r.peak]), showSymbol: false, lineStyle: { width: 1, color: cssVar("--series-6") }, itemStyle: { color: cssVar("--series-6") } },
    ],
  }) as never, [d]);
  return <EChart height={260} label={`${d.name}: flights each day`} option={option} />;
}

function Delays({ d }: { d: AirportDetail }) {
  const option = useMemo(() => () => ({
    tooltip: { trigger: "axis" }, legend: { textStyle: { color: cssVar("--ink-2") } },
    grid: { left: 48, right: 16, top: 36, bottom: 32 },
    xAxis: { type: "category", data: d.eurocontrol.map((r) => r.month), axisLabel: { color: cssVar("--ink-2") } },
    yAxis: { type: "value", name: "minutes a flight", ...axis() },
    series: [
      { type: "bar", name: "Arrival delay (airport ATFM)", data: d.eurocontrol.map((r) => r.arr_delay_min ?? null), itemStyle: { color: cssVar("--div-neg-2") } },
      { type: "line", name: "Extra taxi-out", data: d.eurocontrol.map((r) => r.taxi_add_min ?? null), itemStyle: { color: cssVar("--series-2") } },
      { type: "line", name: "Extra holding on arrival", data: d.eurocontrol.map((r) => r.asma_add_min ?? null), itemStyle: { color: cssVar("--series-4") } },
    ],
  }) as never, [d]);
  return <EChart height={240} label={`${d.name}: delays by month`} option={option} />;
}

function Airports({ initial }: { initial?: string }) {
  const [list, setList] = useState<AirportList | null>(null);
  const [code, setCode] = useState(initial ?? "");
  const [d, setD] = useState<AirportDetail | null>(null);
  const [filter, setFilter] = useState("");
  const [note, setNote] = useState("");
  useEffect(() => {
    get<AirportList>("/congestion/airports").then((l) => {
      setList(l);
      setCode((c) => c || l.airports.find((a) => a.icao === "NZAA")?.icao || l.airports[0]?.icao || "");
    }).catch((e) => setNote(String(e.message || e)));
  }, []);
  useEffect(() => { if (code) { setD(null); get<AirportDetail>(`/congestion/airport/${encodeURIComponent(code)}`).then(setD).catch(() => setD(null)); } }, [code]);
  if (note) return <p className="error">{note}</p>;
  if (!list) return <p className="muted">Loading…</p>;
  const ranked = [...list.airports].filter((a) => a.use != null).sort((a, b) => (b.use ?? 0) - (a.use ?? 0));
  const shown = list.airports.filter((a) => !filter || `${a.icao} ${a.iata ?? ""} ${a.name} ${a.country ?? ""}`.toLowerCase().includes(filter.toLowerCase()));
  const count = () => send<{ started: boolean; note?: string }>("POST", "/congestion/airports/fetch").then((r) => setNote(r.started ? "" : r.note ?? "")).catch(() => {});
  return (
    <>
      <div className="grid two">
        <div className="card">
          <div className="card-head"><span className="small ink-2">Closest to their limit (busiest weekday hour)</span>
            <CardAsk onAsk={() => ask("Airports closest to their limit", "Airport, busiest hour flights, % of limit or record, flights a day",
              ranked.map((a) => `${a.name} (${a.icao})\t${a.peak_flights}\t${a.use}% of ${a.against}\t${a.per_day}`).join("\n"))} /></div>
          {ranked.length ? (
            <div style={{ maxHeight: 420, overflowY: "auto" }}>
              <table className="small"><thead><tr><th>Airport</th><th className="num">Busiest hour</th><th className="num">Of limit</th><th className="num">A day</th></tr></thead>
                <tbody>{ranked.slice(0, 40).map((a) => (
                  <tr key={a.icao} className={a.icao === code ? "on" : ""} style={{ cursor: "pointer" }} onClick={() => setCode(a.icao)}>
                    <td>{a.name} <span className="muted">{a.iata ?? a.icao}</span></td>
                    <td className="num">{n0(a.peak_flights)}{a.peak_hour != null ? <span className="muted"> at {HOURS[a.peak_hour]}</span> : null}</td>
                    <td className={`num ${useTone(a.use)}`}>{a.use}%{a.against === "record" ? <span className="muted">*</span> : null}</td>
                    <td className="num">{n0(a.per_day)}</td></tr>))}</tbody></table>
            </div>
          ) : <p className="small">No flights counted yet. The app counts them once a day from OpenSky (it backfills two weeks the first time);
            this needs your OpenSky client id and secret (Data status &gt; Keys). <button className="link" onClick={count}>Count now</button></p>}
          <p className="caption">Busiest weekday hour (arrivals plus departures, local time, last four weeks) against the airport&apos;s published hourly limit,
            or * against its own busiest hour of the past year where no limit is published. Last round: {when(list.status.round_ended)}
            {list.status.error ? <span className="tone-bad"> · {list.status.error}</span> : null}.</p>
        </div>
        <div className="card">
          <div className="card-head"><span className="small ink-2">Every airport counted ({list.airports.length})</span></div>
          <input placeholder="Filter by name, code or country" value={filter} onChange={(e) => setFilter(e.target.value)} aria-label="Filter airports" />
          <div style={{ maxHeight: 380, overflowY: "auto" }}>
            <table className="small"><thead><tr><th>Airport</th><th className="num">A day</th><th>Limits</th><th className="num">Gates</th><th className="num">Stands</th></tr></thead>
              <tbody>{shown.map((a) => (
                <tr key={a.icao} className={a.icao === code ? "on" : ""} style={{ cursor: "pointer" }} onClick={() => setCode(a.icao)}>
                  <td>{a.name} <span className="muted">{a.iata ?? a.icao} {a.country}</span></td><td className="num">{n0(a.per_day)}</td>
                  <td className="small">{[a.hourly_limit ? `${a.hourly_limit}/h` : "", a.annual_limit ? `${(a.annual_limit / 1000).toFixed(0)}k/yr` : "",
                    a.curfew ? `curfew ${a.curfew}` : "", a.slot_level ? `level ${a.slot_level}` : ""].filter(Boolean).join(" · ")}</td>
                  <td className="num">{n0(a.gates)}</td><td className="num">{n0(a.stands)}</td></tr>))}</tbody></table>
          </div>
          <p className="caption">Gates and stands are counted from OpenStreetMap (gate and parking position points within a few km), so they are only as complete as the map.
            Add limits of your own as CSV files (icao, hourly_limit, curfew, source) in <code>var\manual\airport_limits</code>.</p>
        </div>
      </div>
      {d ? (
        <div className="grid two">
          <div className="card" style={{ gridColumn: "1 / -1" }}>
            <div className="card-head"><span className="small ink-2">{d.name} ({d.iata ?? d.icao}): flights by local hour</span>
              <CardAsk onAsk={() => ask(`${d.name} busy hours`, "Hour, weekday flights, weekend flights",
                HOURS.map((h, i) => `${h}\t${d.profile.weekday[i] ?? ""}\t${d.profile.weekend[i] ?? ""}`).join("\n") + `\nLimit: ${d.hourly_limit ?? "none published"}; curfew ${d.curfew ?? "none"}`)} /></div>
            <h3 className="finding">{d.peak_flights == null ? `No flights counted yet for ${d.name}`
              : `Busiest at ${HOURS[d.peak_hour ?? 0]} with ${n0(d.peak_flights)} flights${d.use != null ? `, ${d.use}% of ${d.against === "limit" ? "its limit" : "its busiest hour seen"}` : ""}`}</h3>
            {d.profile.days ? <BusyHours d={d} /> : null}
            <p className="caption">Average over {d.profile.days} whole local days ({d.profile.from} to {d.profile.to}, time zone {d.tz}), counted from OpenSky&apos;s arrivals and departures.
              OpenSky only sees planes its volunteer receivers hear, so small or remote airports read low.
              {d.curfew ? ` Shaded: curfew ${d.curfew}.` : ""}{d.limit?.source ? <> Limits: {d.limit.link ? <a href={d.limit.link} target="_blank" rel="noreferrer">{d.limit.source}</a> : d.limit.source}.</> : ""}
              {d.limit?.note ? ` ${d.limit.note}` : ""}</p>
          </div>
          <div className="card">
            <div className="card-head"><span className="small ink-2">Flights each day</span></div>
            {d.daily.length ? <FlightsByDay d={d} /> : <p className="small muted">No days counted yet.</p>}
            <p className="small">{[d.gates != null ? `${d.gates} gates` : "", d.stands != null ? `${d.stands} aircraft stands` : "",
              d.annual_limit ? `cap of ${d.annual_limit.toLocaleString()} flights a year` : "", d.slot_level ? `IATA slot level ${d.slot_level}` : ""].filter(Boolean).join(" · ")}</p>
          </div>
          {d.eurocontrol.length ? (
            <div className="card">
              <div className="card-head"><span className="small ink-2">Delays by month (EUROCONTROL)</span></div>
              <Delays d={d} />
              <p className="caption">Minutes per flight: delay on arrival put down to the airport (ATFM), extra time taxiing out and extra holding before landing,
                against EUROCONTROL&apos;s reference times. Europe only; read once a week.</p>
            </div>
          ) : null}
          {d.faa ? (
            <div className="card">
              <div className="card-head"><span className="small ink-2">FAA status now</span></div>
              {d.faa.now.length ? <ul className="small">{d.faa.now.map((f, i) => <li key={i}><b>{f.kind}</b>: {f.reason} <span className="muted">{f.detail}</span></li>)}</ul>
                : <p className="small">{d.faa.error ? <span className="tone-bad">{d.faa.error}</span> : "No ground stops or delay programmes now."}</p>}
              <p className="caption">From the FAA&apos;s National Airspace System status, read when you open this (kept five minutes).</p>
            </div>
          ) : null}
        </div>
      ) : code ? <p className="muted">Loading {code}…</p> : null}
    </>
  );
}

// ----------------------------------------------------------------------------- roads
function SiteCharts({ s }: { s: RoadSite }) {
  const days = useMemo(() => () => ({
    tooltip: { trigger: "axis" }, grid: { left: 56, right: 16, top: 24, bottom: 64 },
    xAxis: { type: "time", axisLabel: { color: cssVar("--ink-2") } }, yAxis: { type: "value", name: "vehicles a day", ...axis() },
    dataZoom: [{ type: "slider", bottom: 8, height: 18 }, { type: "inside", zoomOnMouseWheel: "shift" }],
    series: [{ type: "line", name: "Vehicles", data: s.daily.map((r) => [r.day, r.vehicles]), showSymbol: false, lineStyle: { width: 1.6, color: cssVar("--series-1") }, itemStyle: { color: cssVar("--series-1") } }],
  }) as never, [s]);
  const hours = useMemo(() => () => ({
    tooltip: { trigger: "axis" }, legend: { textStyle: { color: cssVar("--ink-2") } }, grid: { left: 52, right: 48, top: 36, bottom: 32 },
    xAxis: { type: "category", data: s.hours ? HOURS : WEEK, axisLabel: { color: cssVar("--ink-2"), interval: s.hours ? 2 : 0 } },
    yAxis: [{ type: "value", name: s.hours ? "vehicles an hour" : "vehicles a day", ...axis() },
      ...(s.hours?.weekday_mph ? [{ type: "value", name: "mph", axisLabel: { color: cssVar("--ink-2") }, splitLine: { show: false } }] : [])],
    series: s.hours ? [
      { type: "bar", name: "Weekdays", data: s.hours.weekday, itemStyle: { color: cssVar("--series-1") } },
      { type: "line", name: "Weekends", data: s.hours.weekend, showSymbol: false, lineStyle: { width: 2, color: cssVar("--series-4") }, itemStyle: { color: cssVar("--series-4") } },
      ...(s.hours.weekday_mph ? [{ type: "line", name: "Average speed, weekdays", yAxisIndex: 1, data: s.hours.weekday_mph, showSymbol: false,
        lineStyle: { width: 1.4, type: "dashed", color: cssVar("--series-6") }, itemStyle: { color: cssVar("--series-6") } }] : []),
    ] : [{ type: "bar", name: "Average", data: s.weekdays ?? [], itemStyle: { color: cssVar("--series-1") } }],
  }) as never, [s]);
  return (
    <>
      <EChart height={260} label={`${s.name}: by ${s.hours ? "hour" : "day of the week"}`} option={hours} />
      <p className="caption">{s.hours ? `Average of the last eight weeks (${s.hours.from} to ${s.hours.to}). Where the speed falls at the busiest hours, the road is congested.`
        : "Average by day of the week over the last three months (NZTA gives daily totals, not hours)."}</p>
      {s.daily.length ? <EChart height={240} label={`${s.name}: vehicles each day`} option={days} /> : null}
    </>
  );
}

function Roads({ initial }: { initial?: string }) {
  const [st, setSt] = useState<RoadStatus | null>(null);
  const [id, setId] = useState(initial ?? "");
  const [s, setS] = useState<RoadSite | null>(null);
  const [typed, setTyped] = useState(initial ?? "");
  useEffect(() => { get<RoadStatus>("/congestion/roads/status").then(setSt).catch(() => setSt(null)); }, []);
  useEffect(() => { if (id) { setS(null); get<RoadSite>(`/congestion/roads/site/${encodeURIComponent(id)}`).then(setS).catch(() => setS(null)); } }, [id]);
  const read = () => send<{ started: boolean }>("POST", "/congestion/roads/fetch").then(() => get<RoadStatus>("/congestion/roads/status").then(setSt)).catch(() => {});
  return (
    <div className="grid two">
      <div className="card" style={{ gridColumn: "1 / -1" }}>
        <div className="map-box"><WorldMap fill values={[]} unit="" decimals={0} diverging={false} hideScale layers={["count_sites", "road_traffic"]} onPick={() => {}} /></div>
        <p className="caption">Counting sites on state highways (New Zealand, NZTA), England&apos;s motorways and main roads (National Highways WebTRIS, 300 picked across the country)
          and New South Wales (needs TFNSW_API_KEY), read once a week. Red: busier last week than the eight weeks before; blue: quieter. Click a site for its hours.
          {st?.tomtom_key ? " Live traffic (TomTom) is drawn on top when you zoom in; it is not saved." : " Add a free TOMTOM_API_KEY to see live traffic on top (not saved)."}
          {" "}Last read: {when(st?.round_ended)}{st?.error ? <span className="tone-bad"> · {st.error}</span> : null}. <button className="link" onClick={read}>Read now</button></p>
      </div>
      <div className="card" style={{ gridColumn: "1 / -1" }}>
        <div className="card-head"><span className="small ink-2">{s ? `${s.name} (${s.source_name})` : "One counting site"}</span>
          {s ? <CardAsk onAsk={() => ask(`${s.name} traffic`, "Day, vehicles", s.daily.slice(-120).map((r) => `${r.day}\t${r.vehicles}`).join("\n"))} /> : null}</div>
        <div className="chips-row small">
          <input placeholder="Site id, e.g. nzta:01N00419" value={typed} onChange={(e) => setTyped(e.target.value)} aria-label="Counting site" />
          <button onClick={() => setId(typed.trim())}>Show</button>
        </div>
        {s ? (
          <>
            <h3 className="finding">{s.vehicles_now != null ? `${n0(s.vehicles_now)} vehicles a day last week` : "No recent counts"}
              {s.vs_normal != null ? `, ${s.vs_normal > 0 ? "+" : ""}${s.vs_normal.toFixed(0)}% against the eight weeks before` : ""}</h3>
            <SiteCharts s={s} />
            <p className="caption">Source: <a href={s.link} target="_blank" rel="noreferrer">{s.source_name}</a>.</p>
          </>
        ) : <p className="small muted">{id ? "Loading…" : "Click a site on the map (its card links here) or type its id."}</p>}
      </div>
    </div>
  );
}

// ----------------------------------------------------------------------------- trains
function Trains({ initialFeed }: { initialFeed?: string }) {
  const [p, setP] = useState<TrainsPage | null>(null);
  const [days, setDays] = useState(7);
  const [net, setNet] = useState(initialFeed ?? "");
  useEffect(() => { get<TrainsPage>("/congestion/trains", { days }).then((x) => { setP(x); setNet((n) => n || x.networks.find((w) => w.lines.length)?.id || x.networks[0]?.id || ""); }).catch(() => setP(null)); }, [days]);
  const w = p?.networks.find((x) => x.id === net);
  const hours = useMemo(() => () => ({
    tooltip: { trigger: "axis" }, grid: { left: 48, right: 16, top: 24, bottom: 32 },
    xAxis: { type: "category", data: HOURS, axisLabel: { color: cssVar("--ink-2"), interval: 2 } },
    yAxis: { type: "value", name: "% late", ...axis() },
    series: [{ type: "bar", name: "Readings late", data: w?.hours.map((h) => h.late_pct) ?? [], itemStyle: { color: cssVar("--div-neg-2") } }],
  }) as never, [w]);
  const daily = useMemo(() => () => ({
    tooltip: { trigger: "axis" }, legend: { textStyle: { color: cssVar("--ink-2") } }, grid: { left: 48, right: 48, top: 36, bottom: 32 },
    xAxis: { type: "category", data: w?.daily.map((d) => d.day) ?? [], axisLabel: { color: cssVar("--ink-2") } },
    yAxis: [{ type: "value", name: "% late", ...axis() }, { type: "value", name: "minutes", axisLabel: { color: cssVar("--ink-2") }, splitLine: { show: false } }],
    series: [{ type: "bar", name: "Readings late", data: w?.daily.map((d) => d.late_pct) ?? [], itemStyle: { color: cssVar("--div-neg-2") } },
      { type: "line", name: "Average delay", yAxisIndex: 1, data: w?.daily.map((d) => d.avg_delay_min) ?? [], itemStyle: { color: cssVar("--series-1") } }],
  }) as never, [w]);
  const punct = useMemo(() => () => ({
    tooltip: { trigger: "axis" }, legend: { type: "scroll", textStyle: { color: cssVar("--ink-2") } }, grid: { left: 48, right: 16, top: 40, bottom: 32 },
    xAxis: { type: "category", data: [...new Set((p?.punctuality ?? []).flatMap((s) => s.points.map((x) => x[0])))].sort(), axisLabel: { color: cssVar("--ink-2") } },
    yAxis: { type: "value", name: "% on time", ...axis() },
    series: (p?.punctuality ?? []).map((s, i) => ({ type: "line", name: s.network, data: s.points.map((x) => [x[0], x[1]]), showSymbol: false,
      itemStyle: { color: cssVar(`--series-${(i % 8) + 1}`) }, lineStyle: { color: cssVar(`--series-${(i % 8) + 1}`) } })),
  }) as never, [p]);
  if (!p) return <p className="muted">Loading…</p>;
  return (
    <div className="grid two">
      <div className="card" style={{ gridColumn: "1 / -1" }}>
        <div className="map-box"><WorldMap fill values={[]} unit="" decimals={0} diverging={false} hideScale layers={["live_trains", "railways"]} onPick={() => {}} /></div>
        <p className="caption">Trains now from the operators&apos; live feeds, every 30 seconds: green on time, amber 2-5 minutes late, red later, grey when the feed gives no lateness.
          Zoom to Auckland, Wellington or Sydney. Click a train for its path over the last two hours.</p>
      </div>
      <div className="card">
        <div className="card-head"><span className="small ink-2">Feeds</span></div>
        <table className="small"><thead><tr><th>Network</th><th>Key</th><th className="num">Trains now</th><th>Last read</th></tr></thead>
          <tbody>{p.feeds.map((f) => (
            <tr key={f.id}><td>{f.name} <span className="muted">{f.operator}</span></td>
              <td>{f.has_key ? <code>{f.key}</code> : <span className="tone-bad">add {f.key}{f.signup ? <> (<a href={f.signup} target="_blank" rel="noreferrer">free</a>)</> : null}</span>}</td>
              <td className="num">{f.trains || ""}</td><td className="small">{f.read_at ? when(f.read_at) : ""}{f.error ? <span className="tone-bad"> {f.error}</span> : null}</td></tr>))}</tbody></table>
        <p className="caption">Keys go in <Link href="/data">Data status &gt; Keys</Link> or <code>.env</code>. Positions are saved by day while the save
          switch in <Link href="/settings#congestion">Settings &gt; Transport</Link> is on, so lateness builds up over time.</p>
      </div>
      <div className="card">
        <div className="card-head"><span className="small ink-2">Lines most often late</span>
          {w ? <CardAsk onAsk={() => ask(`${w.name} lateness by line`, "Line, % of readings late, average delay (min)",
            w.lines.map((l) => `${l.line}\t${l.late_pct}\t${l.avg_delay_min}`).join("\n"))} /> : null}</div>
        <div className="chips-row small">
          <label>Network <select value={net} onChange={(e) => setNet(e.target.value)}>{p.networks.map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}</select></label>
          <label>Days <select value={days} onChange={(e) => setDays(Number(e.target.value))}>{[1, 7, 14, 30, 60].map((d) => <option key={d} value={d}>{d}</option>)}</select></label>
        </div>
        {w?.lines.length ? (
          <div className="lbars">{w.lines.slice(0, 15).map((l) => (
            <div key={l.line} className="lbar"><span className="lbar-name">{l.line}</span>
              <span className="lbar-track"><span style={{ width: `${Math.max(1, l.late_pct)}%` }} /></span>
              <span className="mono">{l.late_pct.toFixed(0)}%</span><span className="mono muted">{l.avg_delay_min.toFixed(1)} min</span></div>))}</div>
        ) : <p className="small muted">Nothing saved yet for this network: lateness builds up while its feed is read.</p>}
        <p className="caption">Share of 30-second readings where a train was {p.late_minutes}+ minutes late (lines with 20+ readings), and the average delay.
          Readings, not trips: a train late for a long time counts many times.</p>
      </div>
      {w?.daily.length ? (
        <>
          <div className="card"><div className="card-head"><span className="small ink-2">{w.name}: late by hour of the day</span></div><EChart height={220} label="Late by hour" option={hours} /></div>
          <div className="card"><div className="card-head"><span className="small ink-2">{w.name}: each day</span></div><EChart height={220} label="Late each day" option={daily} /></div>
        </>
      ) : null}
      <div className="card" style={{ gridColumn: "1 / -1" }}>
        <div className="card-head"><span className="small ink-2">Monthly punctuality (operators&apos; own figures)</span></div>
        {p.punctuality.length ? <EChart height={260} label="Punctuality by month" option={punct} />
          : <p className="small muted">None saved. Drop CSV files with a network, a month and a % on time column into <code>var\manual\rail_punctuality</code>
            (for example from the ORR data portal, Auckland Transport&apos;s monthly reports or Transport for NSW&apos;s performance pages).</p>}
      </div>
    </div>
  );
}

// ----------------------------------------------------------------------------- the tab
type Part = "airports" | "roads" | "trains";
export default function CongestionView({ part: start, airport, site, feed }: { part?: string; airport?: string; site?: string; feed?: string }) {
  const [part, setPart] = useState<Part>((["airports", "roads", "trains"].includes(start ?? "") ? start : site ? "roads" : feed ? "trains" : "airports") as Part);
  const go = (p: Part) => {
    setPart(p);
    const u = new URL(window.location.href);
    u.searchParams.set("part", p);
    window.history.replaceState(null, "", u.toString());
  };
  return (
    <>
      <div className="chips-row small">{(["airports", "roads", "trains"] as Part[]).map((p) => (
        <button key={p} className={`chip${p === part ? " on" : ""}`} onClick={() => go(p)}>{p === "airports" ? "Airports" : p === "roads" ? "Roads" : "Trains"}</button>))}</div>
      {part === "airports" ? (
        <>
          <div className="card"><div className="map-box"><WorldMap fill values={[]} unit="" decimals={0} diverging={false} hideScale layers={["airport_busy"]} onPick={() => {}} /></div>
            <p className="caption">Airports counted, sized by flights a day and coloured by their busiest hour against the limit (or their own record): green under 75%, amber 75-95%, red above.</p></div>
          <Airports initial={airport} />
        </>
      ) : null}
      {part === "roads" ? <Roads initial={site} /> : null}
      {part === "trains" ? <Trains initialFeed={feed} /> : null}
    </>
  );
}
