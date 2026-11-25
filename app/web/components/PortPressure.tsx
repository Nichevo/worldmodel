"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import CardAsk from "@/components/CardAsk";
import EChart from "@/components/EChart";
import { GoodsLink } from "@/components/GoodsByPort";
import { useKeys } from "@/components/PageLook";
import { openAsk } from "@/lib/ai";
import { api, type PressureCountry, type PressureDetail, type PressureImpact, type PressurePatterns, type PressurePlace } from "@/lib/api";
import { cssVar } from "@/lib/colors";
import { setLayerWindow } from "@/lib/osint";
import { compact } from "@/lib/format";

// Transport > Port pressure: a port or chokepoint each week against normal, the events that
// hit it and what they did, its ship types and connections, the biggest hits anywhere, and
// what usually happens after each kind of event. All worked out from IMF PortWatch's ship
// counts; nothing here measures queues directly.

const ask = (title: string, label: string, text: string) => openAsk({ title, parts: [{ key: title, kind: "data", label, text }] });
const pct = (v: number | null | undefined, d = 0) => (v == null ? "" : `${v > 0 ? "+" : ""}${v.toFixed(d)}%`);
const tone = (v: number | null | undefined) => (v == null ? "" : v <= -10 ? "tone-bad" : v >= 10 ? "tone-good" : "");
const HAZARD_LABEL: Record<string, string> = { cyclone: "Cyclone", earthquake: "Earthquake", flood: "Flood", drought: "Drought",
  volcano: "Volcano", wildfire: "Wildfire", tsunami: "Tsunami", other: "Other" };
const hz = (h: string) => HAZARD_LABEL[h] ?? h.charAt(0).toUpperCase() + h.slice(1);
const days = (d: number | null) => (d == null ? "not within 6 months" : d === 0 ? "same week" : `${d} days`);

function PlacePicker({ places, value, onChange }: { places: PressurePlace[]; value: string; onChange: (key: string) => void }) {
  const keys = useKeys().split(",");
  const [text, setText] = useState("");
  const label = (p: PressurePlace) => `${p.name}${p.kind === "chokepoint" ? " (chokepoint)" : p.entity_id ? ` (${p.entity_id})` : ""}`;
  const groups: [string, PressurePlace[]][] = [
    ["Your key countries' ports", places.filter((p) => p.kind === "port" && p.entity_id && keys.includes(p.entity_id))],
    ["Chokepoints", places.filter((p) => p.kind === "chokepoint")],
    ["Busiest ports in the world", places.filter((p) => p.kind === "port").slice(0, 100)],
    ["Every port", places.filter((p) => p.kind === "port")],
  ];
  const find = (t: string) => places.find((p) => label(p).toLowerCase() === t.toLowerCase())
    ?? places.find((p) => p.name.toLowerCase() === t.toLowerCase());
  return (
    <span className="chips-row small">
      <label className="small">Port or chokepoint{" "}
        <select value={value} onChange={(e) => onChange(e.target.value)} aria-label="Port or chokepoint">
          {groups.map(([g, ps]) => ps.length ? (
            <optgroup key={g} label={g}>{ps.map((p) => <option key={`${g}:${p.kind}:${p.id}`} value={`${p.kind}:${p.id}`}>{label(p)}</option>)}</optgroup>
          ) : null)}
        </select></label>
      <input list="pressure-places" placeholder="or type a name" value={text} style={{ width: 180 }} aria-label="Type a port or chokepoint"
        onChange={(e) => { setText(e.target.value); const p = find(e.target.value); if (p) { onChange(`${p.kind}:${p.id}`); setText(""); } }} />
      <datalist id="pressure-places">{places.map((p) => <option key={`${p.kind}:${p.id}`} value={label(p)} />)}</datalist>
    </span>
  );
}

function PressureChart({ d, picked, onPick, showEvents }: { d: PressureDetail; picked: string | null; onPick: (id: string) => void; showEvents: boolean }) {
  const unit = d.kind === "port" ? "ship calls a week" : "ships a week";
  const option = useMemo(() => () => {
    const lo = d.weeks.map((w) => [w.week, w.normal == null ? null : w.normal * 0.9]);
    const band = d.weeks.map((w) => [w.week, w.normal == null ? null : w.normal * 0.2]);
    const below = d.weeks.filter((w) => w.normal != null && w.value < w.normal * 0.9).map((w) => [w.week, w.value]);
    const events = showEvents ? d.impacts.map((i) => {
      const s = i.start_date;
      const e = i.end_date && i.end_date > s ? i.end_date : new Date(new Date(s).getTime() + 6 * 864e5).toISOString().slice(0, 10);
      return [{ name: `${hz(i.hazard)}: ${i.title}`, xAxis: s, itemStyle: { color: i.impact_id === picked ? cssVar("--div-neg-2") : cssVar("--series-4"), opacity: i.impact_id === picked ? 0.45 : 0.22 } }, { xAxis: e }];
    }) : [];
    return {
      tooltip: { trigger: "axis" },
      legend: { textStyle: { color: cssVar("--ink-2") }, data: ["Ships", "Normal ±10%", "Below normal", ...(d.expect ? ["What usually happens next"] : [])] },
      grid: { left: 52, right: 16, top: 36, bottom: 64 },
      xAxis: { type: "time", axisLabel: { color: cssVar("--ink-2") } },
      yAxis: { type: "value", name: unit, axisLabel: { color: cssVar("--ink-2") }, splitLine: { lineStyle: { color: cssVar("--border") } } },
      dataZoom: [{ type: "slider", bottom: 8, height: 18 }, { type: "inside", zoomOnMouseWheel: "shift" }],
      series: [
        { type: "line", name: "lo", stack: "band", data: lo, showSymbol: false, lineStyle: { opacity: 0 }, tooltip: { show: false }, silent: true },
        { type: "line", name: "Normal ±10%", stack: "band", data: band, showSymbol: false, lineStyle: { opacity: 0 },
          areaStyle: { color: cssVar("--ink-2"), opacity: 0.16 }, itemStyle: { color: cssVar("--ink-2") }, tooltip: { show: false } },
        { type: "line", name: "Ships", data: d.weeks.map((w) => [w.week, w.value]), showSymbol: false, lineStyle: { width: 1.8, color: cssVar("--series-1") },
          itemStyle: { color: cssVar("--series-1") }, markArea: { silent: false, data: events, label: { show: false } } },
        { type: "scatter", name: "Below normal", data: below, symbolSize: 5, itemStyle: { color: cssVar("--div-neg-3") } },
        ...(d.expect ? [{ type: "line", name: "What usually happens next", data: d.expect.weeks.map((w) => [w.week, w.value]), showSymbol: false,
          lineStyle: { type: "dashed", width: 1.6, color: cssVar("--series-2") }, itemStyle: { color: cssVar("--series-2") } }] : []),
      ],
    } as never;
  }, [d, picked, showEvents, unit]);
  return <EChart height={320} label={`${d.name}: ${unit} against normal`} option={option}
    onReady={(c) => c.on("click", (p: { componentType?: string; name?: string }) => {
      if (p.componentType !== "markArea") return;
      const hit = d.impacts.find((i) => `${hz(i.hazard)}: ${i.title}` === p.name);
      if (hit) onPick(hit.impact_id);
    })} />;
}

function ImpactTiles({ i, kind }: { i: PressureImpact; kind: string }) {
  return (
    <div className="climate-strip">
      <div className="card tile htile"><span className="label">Worst week</span><span className={`value ${tone(i.worst_pct)}`}>{pct(i.worst_pct)}</span>
        <span className="meta">against expected{i.worst_week ? `, week of ${i.worst_week}` : ""}</span></div>
      <div className="card tile htile"><span className="label">{kind === "port" ? "Ship calls lost" : "Transits lost"}</span>
        <span className="value">{i.lost_calls == null ? "" : Math.max(0, Math.round(i.lost_calls)).toLocaleString()}</span>
        <span className="meta">until back to normal</span></div>
      {kind === "port" ? <div className="card tile htile"><span className="label">Tonnes lost</span>
        <span className="value">{i.lost_tonnes == null ? "" : compact(Math.max(0, i.lost_tonnes))}</span><span className="meta">in and out, estimated</span></div> : null}
      <div className="card tile htile"><span className="label">Back to normal</span><span className="value">{days(i.recover_days)}</span>
        <span className="meta">{i.catchup_pct != null && i.catchup_pct > 10 ? `then a catch-up of ${pct(i.catchup_pct)}` : "two weeks within 10%"}</span></div>
    </div>
  );
}

export function PressureView({ initial }: { initial?: string }) {
  const [places, setPlaces] = useState<PressurePlace[] | null>(null);
  const [key, setKey] = useState<string>(initial ?? "");
  const [d, setD] = useState<PressureDetail | null>(null);
  const [picked, setPicked] = useState<string | null>(null);
  const [showEvents, setShowEvents] = useState(true);
  const home = useKeys().split(",")[0] || "NZL";
  useEffect(() => {
    api.pressurePlaces().then((ps) => {
      setPlaces(ps);
      setKey((k) => k || (() => { const p = ps.find((x) => x.kind === "port" && x.entity_id === home) ?? ps[0]; return p ? `${p.kind}:${p.id}` : ""; })());
    }).catch(() => setPlaces([]));
  }, [home]);
  useEffect(() => {
    if (!key) return;
    const [kind, id] = [key.split(":")[0], key.slice(key.indexOf(":") + 1)];
    api.pressure(kind, id, picked ?? undefined).then((x) => { setD(x); if (!picked && x.impacts.length) setPicked(x.impacts.filter((i) => i.clear).at(-1)?.impact_id ?? null); })
      .catch(() => setD(null));
  }, [key, picked]);
  if (!places) return <p className="muted">Loading…</p>;
  if (!places.length) return (
    <div className="card"><h3>Port pressure</h3><p>Nothing stored yet. Run <code>.\update.bat</code> then <code>.\refresh.bat</code>: the first
      refresh reads about 3 million daily port figures from IMF PortWatch (a few minutes), and the build works out each port&apos;s normal and the impacts of events.</p></div>);
  const imp = d?.impacts.find((i) => i.impact_id === picked) ?? null;
  const pick = (k: string) => { setPicked(null); setD(null); setKey(k); };
  return (
    <>
      <div className="chips-row small"><PlacePicker places={places} value={key} onChange={pick} />
        <label className="small"><input type="checkbox" checked={showEvents} onChange={(e) => setShowEvents(e.target.checked)} /> Events on chart</label></div>
      {!d ? <p className="muted">Loading…</p> : (
        <div className="grid two">
          <div className="card" style={{ gridColumn: "1 / -1" }}>
            <div className="card-head"><span className="small ink-2">{d.name}: {d.kind === "port" ? "ship calls" : "ships through"} each week against normal</span>
              <CardAsk onAsk={() => ask(`${d.name} against normal`, "Week, ships, normal",
                d.weeks.map((w) => `${w.week}\t${w.value}\t${w.normal ?? ""}`).join("\n") + "\nEvents:\n" + d.impacts.map((i) => `${i.start_date} ${i.title}: worst ${i.worst_pct}%, back in ${days(i.recover_days)}`).join("\n"))} /></div>
            {d.fact ? <p className="small" style={{ margin: "0 0 4px" }}>{d.fact}{d.top ? `. Main trade: ${d.top}` : ""}.</p> : null}
            {d.weeks.length ? <PressureChart d={d} picked={picked} onPick={setPicked} showEvents={showEvents} /> : <p className="small muted">No weekly figures for {d.name}.</p>}
            <p className="caption">Normal is the same weeks of up to three years before, scaled by how busy {d.name} was in the eight weeks before (IMF PortWatch,
              from satellite ship tracking). A long disruption slowly becomes its own normal on this chart; the impacts below hold the level from before each event.
              {d.expect ? ` Dashed: what usually followed ${d.expect.n} other ${hz(d.expect.hazard).toLowerCase()}s, scaled to this place.` : ""}</p>
          </div>
          <div className="card">
            <div className="card-head"><span className="small ink-2">Events that reached {d.name}</span>
              <CardAsk onAsk={() => ask(`Events at ${d.name}`, "Event, worst week, calls lost, days to recover",
                d.impacts.map((i) => `${i.start_date} ${i.title}\t${i.worst_pct}%\t${i.lost_calls ?? ""}\t${i.recover_days ?? "not recovered"}`).join("\n"))} /></div>
            {imp ? <><h3 className="finding">{imp.title}: {imp.worst_pct <= -5 ? `${Math.abs(imp.worst_pct).toFixed(0)}% below expected at worst` : "no clear fall"}</h3>
              <ImpactTiles i={imp} kind={d.kind} />
              {!imp.clear ? <p className="small muted">{imp.base_weekly < 20 ? "Too small to tell: under 20 ships a week before." : "The fall was under 20%, within the usual ups and downs."}</p> : null}</> : null}
            {d.impacts.length ? (
              <table className="small"><thead><tr><th>Event</th><th>Kind</th><th className="num">Worst</th><th className="num">Back in</th></tr></thead>
                <tbody>{[...d.impacts].reverse().map((i) => (
                  <tr key={i.impact_id} className={i.impact_id === picked ? "on" : ""} style={{ cursor: "pointer" }} onClick={() => setPicked(i.impact_id)}>
                    <td>{i.start_date} {i.title}{i.origin === "portwatch" ? <span className="muted"> (PortWatch)</span> : null}</td><td>{hz(i.hazard)}</td>
                    <td className={`num ${tone(i.worst_pct)}`}>{pct(i.worst_pct)}</td><td className="num">{i.recover_days == null ? "–" : `${i.recover_days} d`}</td></tr>))}</tbody></table>
            ) : <p className="small muted">No events since 2019 matched to {d.name}.</p>}
            <p className="caption">Events: disasters PortWatch tracked near the port, and the app&apos;s own disasters, epidemics, conflicts and shipping blockages in the country
              (matched to its three busiest ports) or at the chokepoint. A fall at the same time is not proof the event caused it.</p>
          </div>
          {d.kind === "port" ? (
            <div className="card">
              <div className="card-head"><span className="small ink-2">What goes through {d.name}</span>
                <CardAsk onAsk={() => ask(`Ships at ${d.name}`, "Ship type, share of calls in the last year", d.mix.map((m) => `${m.name}\t${m.share}%`).join("\n"))} /></div>
              {d.mix.length ? <div className="lbars">{d.mix.map((m) => (
                <div key={m.type} className="lbar"><span className="lbar-name">{m.name}</span>
                  <span className="lbar-track"><span style={{ width: `${Math.max(1, m.share)}%` }} /></span><span className="mono">{m.share.toFixed(0)}%</span><span /></div>))}</div>
                : <p className="small muted">No ship types stored.</p>}
              {d.year_calls ? <p className="small">Last 12 months: {Math.round(d.year_calls).toLocaleString()} ship calls,
                {" "}{compact(d.year_import_t ?? 0)} tonnes in and {compact(d.year_export_t ?? 0)} tonnes out (estimated).</p> : null}
              <GoodsLink portId={d.id} name={d.name} />
              <p className="caption">Share of ship calls by type of ship (IMF PortWatch). The goods themselves come from national statistics (Goods by port tab) where they are published.</p>
            </div>
          ) : null}
          {d.links.length ? (
            <div className="card">
              <div className="card-head"><span className="small ink-2">{d.name}&apos;s connections by ship</span>
                <CardAsk onAsk={() => ask(`${d.name} connections`, "Direction, port, sailing days, share of its capacity",
                  d.links.map((l) => `${l.direction}\t${l.name}\t${l.days ?? ""}\t${l.share ?? ""}%`).join("\n"))} /></div>
              <table className="small"><thead><tr><th /><th>Port</th><th className="num">Days at sea</th><th className="num">Capacity tied</th>
                {d.knock_on?.length ? <th className="num">During event</th> : null}</tr></thead>
                <tbody>{d.links.map((l) => {
                  const k = d.knock_on?.find((x) => x.port_id === l.port_id && x.direction === l.direction);
                  return (
                    <tr key={`${l.direction}${l.port_id}`}><td className="muted">{l.direction === "out" ? "to" : "from"}</td>
                      <td><button className="link" onClick={() => pick(`port:${l.port_id}`)}>{l.name}</button> {l.entity_id ? <span className="muted">{l.entity_id}</span> : null}</td>
                      <td className="num">{l.days ?? ""}</td><td className="num">{l.capacity_t == null ? "" : `${compact(l.capacity_t)} t/day`}{l.share != null ? ` (${l.share}%)` : ""}</td>
                      {d.knock_on?.length ? <td className={`num ${tone(k?.vs_normal)}`}>{k ? pct(k.vs_normal) : ""}</td> : null}</tr>);
                })}</tbody></table>
              <p className="caption">Where ships from {d.name} sail next (to) and where ships calling there came from (from), by the cargo capacity a day that depends on the link
                (IMF PortWatch spillovers).{d.knock_on?.length ? " During event: those ports' ships against normal over the picked event and two weeks after; a rise can mean ships went there instead." : ""}</p>
            </div>
          ) : null}
        </div>
      )}
    </>
  );
}

export function BiggestHits() {
  const [rows, setRows] = useState<PressureImpact[] | null>(null);
  const [hazard, setHazard] = useState("");
  const [since, setSince] = useState(2019);
  const [kind, setKind] = useState("");
  const [filter, setFilter] = useState("");
  useEffect(() => { api.pressureImpacts({ hazard: hazard || undefined, since, kind: kind || undefined }).then(setRows).catch(() => setRows([])); }, [hazard, since, kind]);
  const hazards = useMemo(() => [...new Set((rows ?? []).map((r) => r.hazard))].sort(), [rows]);
  if (!rows) return <p className="muted">Loading…</p>;
  const shown = rows.filter((r) => !filter || `${r.title} ${r.place_name} ${r.entity_id}`.toLowerCase().includes(filter.toLowerCase()));
  return (
    <div className="card">
      <div className="card-head"><span className="small ink-2">Biggest hits: events and the ships they cost</span>
        <CardAsk onAsk={() => ask("Biggest hits to ports", "Event, place, worst week, calls lost, days to recover",
          shown.slice(0, 60).map((r) => `${r.start_date} ${r.title}\t${r.place_name}\t${r.worst_pct}%\t${r.lost_calls}\t${r.recover_days ?? "not recovered"}`).join("\n"))} /></div>
      <div className="chips-row small">
        <label>Kind of event <select value={hazard} onChange={(e) => setHazard(e.target.value)}><option value="">Any</option>
          {hazards.map((h) => <option key={h} value={h}>{hz(h)}</option>)}</select></label>
        <label>Place <select value={kind} onChange={(e) => setKind(e.target.value)}><option value="">Ports and chokepoints</option>
          <option value="port">Ports</option><option value="chokepoint">Chokepoints</option></select></label>
        <label>Since <select value={since} onChange={(e) => setSince(Number(e.target.value))}>
          {[2019, 2020, 2021, 2022, 2023, 2024, 2025, 2026].map((y) => <option key={y} value={y}>{y}</option>)}</select></label>
        <input placeholder="Filter by name or country" value={filter} onChange={(e) => setFilter(e.target.value)} aria-label="Filter" />
      </div>
      {shown.length ? (
        <div style={{ overflowX: "auto", maxHeight: 520 }}>
          <table className="small"><thead><tr><th>Event</th><th>Port or chokepoint</th><th className="num">Worst week</th><th className="num">Calls lost</th>
            <th className="num">Tonnes lost</th><th className="num">Back in</th></tr></thead>
            <tbody>{shown.map((r) => (
              <tr key={r.impact_id}><td>{r.start_date} {r.title} <span className="muted">{hz(r.hazard)}</span></td>
                <td>{r.place_name} {r.entity_id ? <Link className="muted" href={`/entity/${r.entity_id}`}>{r.entity_id}</Link> : null}</td>
                <td className={`num ${tone(r.worst_pct)}`}>{pct(r.worst_pct)}</td>
                <td className="num">{r.lost_calls == null ? "" : Math.max(0, Math.round(r.lost_calls)).toLocaleString()}</td>
                <td className="num">{r.lost_tonnes == null ? "" : compact(Math.max(0, r.lost_tonnes))}</td>
                <td className="num">{r.recover_days == null ? "not yet" : `${r.recover_days} d`}</td></tr>))}</tbody></table>
        </div>
      ) : <p className="small muted">No clear hits for these choices.</p>}
      <p className="caption">Only clear hits: places with 20 or more ships a week and a fall of 20% or more against expected. Calls and tonnes lost add up the shortfall
        until two weeks are back within 10% (up to 26 weeks).</p>
    </div>
  );
}

export function Patterns() {
  const [p, setP] = useState<PressurePatterns | null>(null);
  const [focus, setFocus] = useState<string | null>(null);
  useEffect(() => { api.pressurePatterns().then((x) => { setP(x); setFocus(x.curves[0]?.hazard ?? null); }).catch(() => setP({ curves: [], resilience: [], weeks_before: 4 })); }, []);
  const option = useMemo(() => () => {
    if (!p) return {};
    const colours = ["--series-1", "--series-2", "--series-3", "--series-4", "--series-5", "--series-6", "--series-7", "--series-8"];
    const x = (k: number) => k - (p.weeks_before ?? 4);
    const f = p.curves.find((c) => c.hazard === focus);
    return {
      tooltip: { trigger: "axis" }, legend: { textStyle: { color: cssVar("--ink-2") }, type: "scroll" },
      grid: { left: 52, right: 16, top: 40, bottom: 36 },
      xAxis: { type: "value", name: "weeks from start", nameLocation: "middle", nameGap: 24, min: -(p.weeks_before ?? 4), max: 16, axisLabel: { color: cssVar("--ink-2") } },
      yAxis: { type: "value", name: "% of expected", axisLabel: { color: cssVar("--ink-2"), formatter: (v: number) => `${Math.round(v * 100)}` },
        splitLine: { lineStyle: { color: cssVar("--border") } } },
      series: [
        ...(f ? [
          { type: "line", name: "lo", stack: "iq", data: f.p25.map((v, k) => [x(k), v]), showSymbol: false, lineStyle: { opacity: 0 }, silent: true, tooltip: { show: false } },
          { type: "line", name: `${f.name}: middle half`, stack: "iq", data: f.p75.map((v, k) => [x(k), v == null || f.p25[k] == null ? null : v - (f.p25[k] as number)]),
            showSymbol: false, lineStyle: { opacity: 0 }, areaStyle: { color: cssVar("--ink-2"), opacity: 0.14 }, tooltip: { show: false } }] : []),
        ...p.curves.map((c, i) => ({ type: "line", name: `${c.name} (${c.n})`, data: c.mean.map((v, k) => [x(k), v]), showSymbol: false,
          lineStyle: { width: c.hazard === focus ? 2.6 : 1.2, color: cssVar(colours[i % colours.length]) }, itemStyle: { color: cssVar(colours[i % colours.length]) } })),
      ],
    } as never;
  }, [p, focus]);
  if (!p) return <p className="muted">Loading…</p>;
  if (!p.curves.length) return <div className="card"><h3>Patterns</h3><p className="small muted">Not enough clear hits stored yet to show patterns. They come with a refresh.</p></div>;
  const ranked = p.resilience.filter((r) => r.events >= 2 && r.kind === "port");
  return (
    <div className="grid two">
      <div className="card" style={{ gridColumn: "1 / -1" }}>
        <div className="card-head"><span className="small ink-2">What usually happens to ships after each kind of event</span>
          <CardAsk onAsk={() => ask("Typical hits by kind of event", "Kind, events, median worst week, median days back",
            p.curves.map((c) => `${c.name}\t${c.n}\t${c.worst_median}%\t${c.recover_median ?? "not recovered"}`).join("\n"))} /></div>
        <div className="chips-row small">{p.curves.map((c) => (
          <button key={c.hazard} className={`chip${c.hazard === focus ? " on" : ""}`} onClick={() => setFocus(c.hazard)}>{c.name}</button>))}</div>
        <EChart height={320} label="Average ships against expected, by kind of event" option={option} />
        <table className="small"><thead><tr><th>Kind of event</th><th className="num">Clear hits</th><th className="num">Typical worst week</th><th className="num">Typical time back</th><th className="num">Not back in 6 months</th></tr></thead>
          <tbody>{p.curves.map((c) => (
            <tr key={c.hazard}><td>{c.name}</td><td className="num">{c.n}</td><td className={`num ${tone(c.worst_median)}`}>{pct(c.worst_median)}</td>
              <td className="num">{c.recover_median == null ? "" : `${Math.round(c.recover_median)} days`}</td><td className="num">{c.not_recovered || ""}</td></tr>))}</tbody></table>
        <p className="caption">Each line is the average of every clear hit of that kind since 2019 (ships against what was expected from the eight weeks before), week by week;
          the grey band is the middle half of those events for the one picked. Typical = median.</p>
      </div>
      <div className="card">
        <div className="card-head"><span className="small ink-2">Ports that get back fastest</span></div>
        <table className="small"><thead><tr><th>Port</th><th className="num">Hits</th><th className="num">Typical time back</th></tr></thead>
          <tbody>{ranked.slice(0, 15).map((r) => (
            <tr key={r.id}><td>{r.name} <span className="muted">{r.entity_id}</span></td><td className="num">{r.events}</td>
              <td className="num">{r.recover_median == null ? "not yet" : `${Math.round(r.recover_median)} d`}</td></tr>))}</tbody></table>
      </div>
      <div className="card">
        <div className="card-head"><span className="small ink-2">Ports that take longest</span></div>
        <table className="small"><thead><tr><th>Port</th><th className="num">Hits</th><th className="num">Typical time back</th></tr></thead>
          <tbody>{[...ranked].reverse().slice(0, 15).map((r) => (
            <tr key={r.id}><td>{r.name} <span className="muted">{r.entity_id}</span></td><td className="num">{r.events}</td>
              <td className="num">{r.recover_median == null ? "not yet" : `${Math.round(r.recover_median)} d`}</td></tr>))}</tbody></table>
        <p className="caption">Ports with two or more clear hits since 2019. Size matters: bigger ports often have more ways to catch up.</p>
      </div>
    </div>
  );
}

// For a country card: its busiest ports over the last 26 weeks against normal.
export function PortPressureStrip({ entity, name }: { entity: string; name: string }) {
  const [d, setD] = useState<PressureCountry | null>(null);
  useEffect(() => { api.pressureCountry(entity).then(setD).catch(() => setD(null)); }, [entity]);
  if (!d?.ports.length) return null;
  const W = 120, H = 34;
  return (
    <div>
      <b className="small">Ports against normal, last 26 weeks</b>
      <div className="port-grid">
        {d.ports.map((p) => {
          const r = p.weeks.map((w) => w.ratio ?? 1);
          const top = Math.max(1.4, ...r), bot = Math.min(0.6, ...r);
          const y = (v: number) => H - ((v - bot) / (top - bot)) * H;
          const path = r.map((v, i) => `${i ? "L" : "M"}${(i / Math.max(r.length - 1, 1)) * W},${y(v)}`).join("");
          return (
            <Link key={p.id} href={`/transport?tab=pressure&place=port:${encodeURIComponent(p.id)}`} className="port-tile">
              <b className="small">{p.name}</b>
              <svg width="100%" height={H} viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" aria-label={`${p.name} against normal`}>
                <rect x={0} y={y(1.1)} width={W} height={y(0.9) - y(1.1)} fill="var(--ink-2)" opacity={0.15} />
                <path d={path} fill="none" stroke="var(--ink)" strokeWidth={1.5} vectorEffect="non-scaling-stroke" /></svg>
              <span className={`small mono ${tone(p.vs_normal)}`}>{p.vs_normal == null ? "" : `${pct(p.vs_normal)} last 4 weeks`}</span>
            </Link>);
        })}
      </div>
      {d.impacts.length ? <p className="small">Biggest hit: {d.impacts[0].title} ({d.impacts[0].start_date.slice(0, 7)}) at {d.impacts[0].place_name},
        {" "}{pct(d.impacts[0].worst_pct)} at worst, back in {days(d.impacts[0].recover_days)}.</p> : null}
      <p className="caption">Ship calls each week as a share of normal for {name}&apos;s busiest ports (grey band: within 10%). Click one for its Port pressure chart.</p>
    </div>
  );
}

// The weeks the 'Ports against normal' map shows: any run of weeks since 2019, picked on a slider.
export function PressureMapWeeks() {
  const [span, setSpan] = useState<{ first: string | null; last: string | null } | null>(null);
  const [i, setI] = useState<number | null>(null);
  const [weeks, setWeeks] = useState(4);
  useEffect(() => { api.pressureSpan().then(setSpan).catch(() => setSpan(null)); }, []);
  const total = span?.first && span.last ? Math.round((Date.parse(span.last) - Date.parse(span.first)) / (7 * 86_400_000)) : 0;
  const at = i ?? total;
  const end = span?.first ? new Date(Date.parse(span.first) + (at * 7 + 6) * 86_400_000).toISOString().slice(0, 10) : "";
  const start = end ? new Date(Date.parse(end) - weeks * 7 * 86_400_000).toISOString().slice(0, 10) : "";
  useEffect(() => {
    if (!end) return;
    const t = setTimeout(() => setLayerWindow(start, end), 300);
    return () => clearTimeout(t);
  }, [start, end]);
  if (!total) return null;
  return (
    <div className="chips-row small" style={{ alignItems: "center" }}>
      <label className="small">Weeks{" "}
        <select value={weeks} onChange={(e) => setWeeks(Number(e.target.value))} aria-label="Weeks against normal">
          {[1, 4, 13, 26].map((w) => <option key={w} value={w}>{w}</option>)}</select></label>
      <input type="range" min={0} max={total} value={at} onChange={(e) => setI(Number(e.target.value))} style={{ flex: 1, minWidth: 160 }}
        aria-label="Week the map shows" />
      <span className="mono">{weeks === 1 ? "week" : `${weeks} weeks`} to {end}</span>
      {i != null && i !== total ? <button className="link" onClick={() => setI(null)}>Latest</button> : null}
    </div>
  );
}
