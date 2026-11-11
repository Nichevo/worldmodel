"use client";

import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { ECharts, EChartsOption } from "echarts";
import type * as maplibregl from "maplibre-gl";
import CardAsk from "@/components/CardAsk";
import EChart from "@/components/EChart";
import WorldMap, { type MapMark, type MapPath } from "@/components/WorldMap";
import { api, type GeoCollection, type GeoFeature, type LongEvent, type LongOverview, type LongPowerCard, type LongSize, type LongVoyage, type Wikipedia } from "@/lib/api";
import { useSavePicture } from "@/lib/cards";
import { chrome } from "@/lib/charts";
import { cssVar, sequentialRamp, seriesColor } from "@/lib/colors";
import { axisYear, eventLine, GROUP_LABEL, KIND_GROUP, kindColor, SQ_KM, yl } from "@/lib/long";

// One power's card: its borders on a map with a year slider (or the expansion view, land
// coloured by when it was first held), its size over time linked to the slider, the
// Wikipedia introduction, events in its lands and years, and voyages it sent.
function EmpireCard() {
  const { id } = useParams<{ id: string }>();
  const params = useSearchParams();
  const [card, setCard] = useState<LongPowerCard | null>(null);
  const [o, setO] = useState<LongOverview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [year, setYear] = useState<number | null>(null);
  const [view, setView] = useState<"year" | "expansion">("year");
  const [playing, setPlaying] = useState(0); // years a second, 0 = stopped
  const [showEvents, setShowEvents] = useState(true);
  const [showVoyages, setShowVoyages] = useState(true);
  const [extraVoyage, setExtraVoyage] = useState<LongVoyage | null>(null);
  const [shape, setShape] = useState<GeoFeature | null>(null);
  const [expansion, setExpansion] = useState<GeoCollection | null>(null);
  const [compare, setCompare] = useState("");
  const [other, setOther] = useState<LongSize | null>(null);
  const shapes = useRef(new Map<string, GeoFeature>());
  const mapRef = useRef<maplibregl.Map | null>(null);
  const fitted = useRef(false);

  useEffect(() => {
    let live = true;
    setCard(null); setYear(null); fitted.current = false; shapes.current.clear();
    api.longPower(id).then((c) => { if (!live) return; setCard(c); setYear(c.peak?.from ?? c.from ?? null); })
      .catch((e) => live && setError(String(e.message || e)));
    api.longOverview().then((x) => live && setO(x)).catch(() => {});
    return () => { live = false; };
  }, [id]);
  useEffect(() => {
    const v = params.get("voyage");
    if (!v) { setExtraVoyage(null); return; }
    api.longVoyages().then((all) => setExtraVoyage(all.find((x) => x.id === v) ?? null)).catch(() => {});
  }, [params]);
  useEffect(() => {
    if (!compare) { setOther(null); return; }
    api.longSizes([compare]).then((s) => setOther(s[0] ?? null)).catch(() => setOther(null));
  }, [compare]);

  const frame = useMemo(() => (card && year !== null ? card.frames.find((f) => f.from <= year && year <= f.to) ?? null : null), [card, year]);
  useEffect(() => {
    if (!frame) { setShape(null); return; }
    const have = shapes.current.get(frame.key);
    if (have) { setShape(have); return; }
    let live = true;
    api.longShape(frame.key).then((f) => { shapes.current.set(frame.key, f); if (live) setShape(f); }).catch(() => live && setShape(null));
    return () => { live = false; };
  }, [frame]);
  useEffect(() => {
    if (view !== "expansion" || expansion || !card) return;
    api.longExpansion(card.id).then(setExpansion).catch(() => setExpansion({ type: "FeatureCollection", features: [] }));
  }, [view, expansion, card]);

  // Play: move the slider on, a tenth of a second at a time; stop at the end.
  useEffect(() => {
    if (!playing || !card || card.to === null) return;
    const t = setInterval(() => setYear((y) => {
      const next = Math.min(card.to!, (y ?? card.from!) + Math.max(1, Math.round(playing / 10)));
      if (next >= card.to!) setPlaying(0);
      return next;
    }), 100);
    return () => clearInterval(t);
  }, [playing, card]);

  // Zoom to the power's lands once (not for powers spread round the world).
  const onMap = useCallback((m: maplibregl.Map | null) => { mapRef.current = m; }, []);
  useEffect(() => {
    const m = mapRef.current;
    if (!m || !card?.bbox || fitted.current) return;
    const [w, s, e, n] = card.bbox;
    if (e - w > 300) return;
    const fit = () => { m.fitBounds([[w, Math.max(-80, s)], [e, Math.min(84, n)]], { padding: 30, duration: 0, maxZoom: 5 }); fitted.current = true; };
    if (m.loaded()) fit(); else m.once("load", fit);
  }, [card]);

  const colour = card?.colour ?? seriesColor(0);
  const areas = useMemo(() => {
    if (view === "expansion" && expansion) {
      const ramp = sequentialRamp();
      const yrs = expansion.features.map((f) => f.properties.from as number);
      const lo = Math.min(...yrs), hi = Math.max(...yrs);
      return { key: `exp:${card?.id}:${expansion.features.length}`, data: { type: "FeatureCollection" as const, features: expansion.features.map((f) => {
        const t = hi > lo ? ((f.properties.from as number) - lo) / (hi - lo) : 0;
        return { ...f, properties: { ...f.properties, color: ramp[Math.round((1 - t) * (ramp.length - 1))], opacity: 0.85,
          label: `${f.properties.label}<br/>Held from ${yl(f.properties.from as number)}` } } as GeoJSON.Feature;
      }) } };
    }
    if (!shape) return null;
    return { key: `y:${shape.properties.key}`, data: { type: "FeatureCollection" as const,
      features: [{ ...shape, properties: { ...shape.properties, color: colour, opacity: 0.55 } } as GeoJSON.Feature] } };
  }, [view, expansion, shape, colour, card]);

  const voyages = useMemo(() => {
    const list = [...(card?.voyages ?? [])];
    if (extraVoyage && !list.some((v) => v.id === extraVoyage.id)) list.push(extraVoyage);
    return list;
  }, [card, extraVoyage]);
  const paths: MapPath[] = useMemo(() => (showVoyages ? voyages.map((v, i) => ({
    key: v.id, color: seriesColor(i + 2), label: `<b>${v.name}</b><br/>${v.who}`,
    stops: v.stops.map((s) => ({ lng: s.lon, lat: s.lat, label: `<b>${s.place}</b>, ${yl(s.year)}<br/>${v.name}` })),
  })) : []), [voyages, showVoyages]);
  const marks: MapMark[] = useMemo(() => (showEvents && card && year !== null ? card.events
    .filter((e) => e.lat !== null && e.lon !== null && e.year <= year && (e.end_year ?? e.year) >= (card.from ?? -1e5))
    .map((e) => ({ key: e.event_id, lng: e.lon!, lat: e.lat!, color: kindColor(e.kind), r: 4 + Math.min(6, Math.log10(1 + (e.deaths ?? 0))),
      opacity: year - e.year <= 25 ? 1 : 0.35, label: eventLine(e), href: e.url ?? undefined })) : []), [showEvents, card, year]);

  if (error) return <p className="error">{error}</p>;
  if (!card) return <p className="muted">Loading…</p>;
  if (!card.frames.length) {
    return (
      <div className="grid long">
        <p><Link href="/long?tab=empires">Long history</Link> &gt;</p>
        <h1>{card.name}</h1>
        <p>No borders for {card.name} {o?.counts.polities ? "in the source (it has none drawn for it)" : "yet: run .\\refresh.bat to load them"}.</p>
        <WikiCard id={card.id} />
      </div>
    );
  }
  const others = (o?.powers ?? []).filter((p) => p.has_borders && p.id !== card.id);
  return (
    <div className="grid long">
      <p className="small"><Link href="/long?tab=empires">Long history &gt; Age of empires</Link> &gt;</p>
      <div className="title-row">
        <h1>{card.name}</h1>
        <span className="muted">{yl(card.from)} to {card.to && card.to >= 2024 ? "now" : yl(card.to)}
          {card.peak ? ` · largest ${SQ_KM(card.peak.area_km2)}, ${yl(card.peak.from)}${card.peak.to > card.peak.from ? ` to ${yl(card.peak.to)}` : ""}` : ""}</span>
        <label className="small">Compare with <select value={compare} onChange={(e) => setCompare(e.target.value)}>
          <option value="">nobody</option>
          {others.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
        </select></label>
      </div>
      <div className="card">
        <div className="long-tools">
          <div className="seg small" role="group" aria-label="Map view">
            <button className={view === "year" ? "on" : ""} onClick={() => setView("year")}>Borders that year</button>
            <button className={view === "expansion" ? "on" : ""} onClick={() => setView("expansion")}>Expansion (when each area was held)</button>
          </div>
          <label className="small"><input type="checkbox" checked={showEvents} onChange={(e) => setShowEvents(e.target.checked)} /> Events</label>
          {voyages.length > 0 && <label className="small"><input type="checkbox" checked={showVoyages} onChange={(e) => setShowVoyages(e.target.checked)} /> Voyages</label>}
        </div>
        <WorldMap values={[]} unit="" decimals={0} diverging={false} onPick={() => {}} hideScale onMap={onMap}
          areas={areas} paths={paths} marks={marks}
          legend={[{ label: view === "year" ? `${card.name} in ${yl(year)}` : "Darker: held earlier", color: colour, shape: "dot" },
            ...(showEvents ? (Object.keys(GROUP_LABEL) as (keyof typeof GROUP_LABEL)[]).map((g) => ({ label: GROUP_LABEL[g],
              color: kindColor(Object.keys(KIND_GROUP).find((k) => KIND_GROUP[k] === g)!), shape: "ring" as const })) : [])]} />
        {view === "year" && (
          <div className="long-slider">
            <button onClick={() => setPlaying(playing ? 0 : 10)} aria-pressed={!!playing}>{playing ? "Pause" : "Play"}</button>
            <select value={playing || 10} onChange={(e) => playing && setPlaying(+e.target.value)} aria-label="Speed">
              <option value={10}>10 years a second</option><option value={25}>25 years a second</option><option value={100}>100 years a second</option>
            </select>
            <input type="range" min={card.from ?? 0} max={card.to ?? 0} value={year ?? 0} onChange={(e) => setYear(+e.target.value)}
              aria-label="Year" style={{ flex: 1 }} />
            <b style={{ minWidth: 90 }}>{yl(year)}</b>
            <span className="small muted">{frame ? SQ_KM(frame.area_km2) : "no borders this year"}</span>
          </div>
        )}
        <p className="caption">Borders from Seshat&apos;s Cliopatria, for the stretch of years the slider is in (a new shape each time
          they changed). &quot;Expansion&quot; shows {card.name}&apos;s shapes over its life with the earliest on top, darker for earlier,
          so the colour is roughly when the land was first held. Events are the best-known in its lands up to the year on the slider
          (faded if more than 25 years before); click one for its article. Voyages are dated stops joined by straight lines (rough).</p>
      </div>
      <SizeChart card={card} year={year} setYear={setYear} other={other} />
      <div className="long-two">
        <WikiCard id={card.id} />
        <EventsCard card={card} setYear={setYear} />
      </div>
    </div>
  );
}

function SizeChart({ card, year, setYear, other }: { card: LongPowerCard; year: number | null; setYear: (y: number) => void; other: LongSize | null }) {
  const { onReady: keep, save, ask } = useSavePicture();
  const option = useCallback((): EChartsOption => {
    const base = chrome();
    const line = (name: string, pts: [number, number | null][], color: string, mark: boolean) => ({
      type: "line", name, step: "end", showSymbol: false, lineStyle: { width: 2, color }, itemStyle: { color }, areaStyle: { opacity: 0.1, color },
      data: pts.map(([y, v]) => [y, v === null ? null : v / 1e6]),
      markLine: mark && year !== null ? { symbol: "none", silent: true, lineStyle: { color: cssVar("--ink"), type: "solid", width: 1.5 },
        label: { formatter: yl(year), color: cssVar("--ink") }, data: [{ xAxis: year }] } : undefined,
    });
    return {
      ...base,
      legend: other ? { top: 0, left: 0, textStyle: { color: cssVar("--ink-2") } } : undefined,
      grid: { left: 8, right: 16, top: other ? 56 : 30, bottom: 8, containLabel: true },
      xAxis: { ...(base.xAxis as object), axisLabel: { color: cssVar("--muted"), formatter: (v: number) => axisYear(v) } },
      yAxis: { axisLine: { onZero: false }, type: "value", name: "million km²", nameTextStyle: { color: cssVar("--muted"), align: "left" }, axisLabel: { color: cssVar("--muted") },
        splitLine: { lineStyle: { color: cssVar("--grid") } } },
      tooltip: { ...(base.tooltip as object), formatter: (ps: unknown) => {
        const list = (Array.isArray(ps) ? ps : [ps]) as { seriesName: string; value: [number, number]; color: string }[];
        return list.length ? [`<b>${yl(list[0].value[0])}</b>`, ...list.map((p) => `<span style="color:${p.color}">●</span> ${p.seriesName}: <b>${p.value[1]?.toFixed(2)}</b> million km²`)].join("<br/>") : "";
      } },
      series: [line(card.name, card.sizes, card.colour ?? seriesColor(0), true),
        ...(other ? [line(other.name, other.points, other.colour ?? seriesColor(1), false)] : [])],
    } as EChartsOption;
  }, [card, year, other]);
  const onReady = useCallback((c: ECharts) => {
    keep(c);
    c.getZr().on("click", (e) => {
      const p = c.convertFromPixel({ gridIndex: 0 }, [e.offsetX, e.offsetY]) as number[] | null;
      if (p && Number.isFinite(p[0])) setYear(Math.round(Math.min(card.to ?? p[0], Math.max(card.from ?? p[0], p[0]))));
    });
  }, [keep, setYear, card]);
  const title = `${card.name}: land ruled`;
  const note = "Land ruled year by year from Seshat's Cliopatria borders.";
  return (
    <div className="card">
      <div className="card-head">
        <h3>Land ruled, linked to the map</h3>
        <CardAsk onAsk={() => ask(title, note, ["cliopatria"])} />
        <button className="link small" onClick={() => save(title, note, ["cliopatria"], "land-ruled", card.id)}>Save picture</button>
      </div>
      <EChart option={option} height={240} label={`${card.name}: land ruled over time`} onReady={onReady} />
      <p className="caption">The black line is the year on the map; click the chart to move the map to that year.</p>
    </div>
  );
}

function WikiCard({ id }: { id: string }) {
  const [w, setW] = useState<Wikipedia | null>(null);
  useEffect(() => { api.longWikipedia(id).then(setW).catch(() => setW(null)); }, [id]);
  if (!w) return <div className="card"><h3>About it</h3><p className="muted">Loading…</p></div>;
  const p = w.page;
  return (
    <div className="card">
      <h3>About it</h3>
      {p ? (
        <>
          {p.description && <p className="muted small">{p.description}</p>}
          {p.extract.split("\n").filter(Boolean).slice(0, 3).map((para, i) => <p key={i}>{para}</p>)}
          <p className="small">{p.url && <a href={p.url} target="_blank" rel="noreferrer">Read on Wikipedia</a>} · {p.licence}</p>
        </>
      ) : <p className="muted">{w.message ?? "No Wikipedia page stored yet."}</p>}
      <p className="caption">{w.budget.used} of {w.budget.limit} empire articles read today (<Link href="/settings#long-history">Settings &gt; Long history</Link>).
        A page is read the first time its card is opened and kept for a month.</p>
    </div>
  );
}

function EventsCard({ card, setYear }: { card: LongPowerCard; setYear: (y: number) => void }) {
  const [group, setGroup] = useState<string>("");
  const list = card.events.filter((e) => !group || KIND_GROUP[e.kind] === group);
  return (
    <div className="card">
      <h3>Events in its lands and years</h3>
      <div className="seg small" role="group" aria-label="Kind">
        <button className={!group ? "on" : ""} onClick={() => setGroup("")}>All</button>
        {(Object.keys(GROUP_LABEL) as (keyof typeof GROUP_LABEL)[]).map((g) => (
          <button key={g} className={group === g ? "on" : ""} onClick={() => setGroup(g)}>{GROUP_LABEL[g]}</button>
        ))}
      </div>
      {!list.length ? <p className="muted">{card.events.length ? "None of this kind." : "No events loaded for its lands and years (or none well known enough)."}</p> : (
        <ul className="long-events">
          {list.map((e: LongEvent) => (
            <li key={e.event_id}>
              <button className="link" onClick={() => setYear(Math.max(card.from ?? e.year, Math.min(card.to ?? e.year, e.year)))}>{e.when}</button>{" "}
              <i className="dot" style={{ background: kindColor(e.kind) }} /> {e.url ? <a href={e.url} target="_blank" rel="noreferrer">{e.title}</a> : e.title}
              {e.deaths ? <span className="muted small"> · about {Math.round(e.deaths).toLocaleString("en")} deaths</span> : null}
            </li>
          ))}
        </ul>
      )}
      <p className="caption">The best-known events inside its widest borders during its years, from Wikidata (articles in enough
        Wikipedias; Settings sets how many) and NOAA&apos;s hazards database. Click a date to move the map there.</p>
    </div>
  );
}

export default function Page() {
  return <Suspense fallback={<p className="muted">Loading…</p>}><EmpireCard /></Suspense>;
}
