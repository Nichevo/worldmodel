"use client";

import Link from "next/link";
import type * as maplibregl from "maplibre-gl";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useRef, useState } from "react";
import AskButton from "@/components/AskButton";
import CountryChoice from "@/components/CountryChoice";
import WorldMap, { type MapMark } from "@/components/WorldMap";
import { logHistory } from "@/lib/history";
import { saveSettings, useSettings } from "@/lib/settings";
import {
  askHere, CHANGE_LEGEND, changeLayer, createScan, deleteScan, estimateScan, type Found, foundPicture, markFound, scanAction,
  scanFound, type Scan, type ScanReq, scans as listScans, spotTerms, type SpotTerms, startSummary, type Summary, type SummaryJob,
  summaries, type SummaryReq, summaryKey, visionModels, type VisionModels, WATER_LEGEND, waterTiles, type HitRate,
} from "@/lib/spotting";

// Spotting: layers the app works out itself from the satellite pictures and land cover maps,
// and local AI looking at the pictures.

type Tab = "change" | "water" | "ask" | "scans";
const TABS: [Tab, string][] = [["change", "Land change"], ["water", "Water gained and lost"], ["ask", "Ask the picture"], ["scans", "Area scans"]];
const INTRO: Record<Tab, string> = {
  change: "Land whose cover changed between two years, read pixel by pixel from the land cover maps (Esri 10 m every year since 2017, or ESA 300 m since 1992). A change only counts if it already held the year before the last year, and specks of a pixel or two are dropped, because the yearly maps flicker. Map layer 8 shows the same.",
  water: "Water that appeared or disappeared between 1984-1999 and 2000-2021, from every Landsat picture (EC Joint Research Centre, Global Surface Water, 30 m). Blue is water gained, red is water lost, orange and yellow are lakes that became seasonal or all-year. Map layer 9 shows the same.",
  ask: "Right-click any place on any map in the app (or this one) and pick \"What is here?\". Your local AI gets the satellite picture, what the land cover map says is there, and the app's own places nearby, so it can name what it sees rather than guess.",
  scans: "Your local AI looks at an area square by square (about 4-5 km each) for the things you tick, or checks the map's own places (power plants, airports …) against the picture. Scans run in the background, one at a time, only when you start them, and can be paused. What they report is map layer 0, Spotted by AI; mark each find right or wrong and the hit rates show how far to trust it.",
};
const ha = (v: number) => (v >= 1e5 ? `${Math.round(v / 100).toLocaleString()} km²` : `${Math.round(v).toLocaleString()} ha`);
const mins = (n: number) => (n < 90 ? `${Math.max(1, Math.round(n))} min` : `${(n / 60).toFixed(n < 600 ? 1 : 0)} hours`);
const errText = (e: unknown) => String((e as Error).message || e).replace(/^\d+: /, "");

function useMapBox() {
  const map = useRef<maplibregl.Map | null>(null);
  const bbox = (): number[] | null => {
    const m = map.current;
    if (!m) return null;
    const b = m.getBounds();
    const w = Math.max(-180, b.getWest()), e = Math.min(180, b.getEast());
    return [w, Math.max(-85, b.getSouth()), e, Math.min(85, b.getNorth())].map((v) => Math.round(v * 1000) / 1000);
  };
  const fly = (lon: number, lat: number, zoom = 11) => map.current?.flyTo({ center: [lon, lat], zoom });
  return { map, bbox, fly };
}

// ----------------------------------------------------------------------------- area summaries (land and water)
function AreaSummary({ kind, req, bbox, fly, labels, onSpots }: {
  kind: "land" | "water"; req: Omit<SummaryReq, "entity" | "bbox" | "kind" | "detail">; bbox: () => number[] | null;
  fly: (lon: number, lat: number) => void; labels: Record<string, [string, string]>; onSpots: (m: MapMark[]) => void;
}) {
  const [area, setArea] = useState<"country" | "view">("country");
  const [country, setCountry] = useState("NZL");
  const [detail, setDetail] = useState<"quick" | "fine">("quick");
  const [job, setJob] = useState<SummaryJob | null>(null);
  const [saved, setSaved] = useState<Record<string, Summary>>({});
  const [err, setErr] = useState<string | null>(null);
  const [lastKey, setLastKey] = useState<string | null>(null);
  const load = () => summaries().then((d) => { setJob(d.job); setSaved(d.saved); }).catch((e) => setErr(errText(e)));
  useEffect(() => { load(); }, []);
  useEffect(() => {
    if (job?.state !== "running") return;
    const t = setInterval(load, 2000);
    return () => clearInterval(t);
  }, [job?.state]);
  const full: SummaryReq = { kind, ...req, detail, entity: area === "country" ? country : null, bbox: area === "view" ? bbox() : null };
  const key = lastKey ?? summaryKey({ ...full, bbox: null, entity: country });
  const res = saved[key] ?? Object.values(saved).filter((s) => s.kind === kind && (kind === "water" || (s.src === req.src && s.from === req.from && s.to === req.to)))
    .sort((a, b) => b.worked_out.localeCompare(a.worked_out))[0];
  useEffect(() => {
    onSpots((res?.hot_spots ?? []).map((h, i) => ({ key: `hot:${i}`, lng: h.lon, lat: h.lat, color: labels[h.main]?.[1] ?? "#862e9c", hollow: true, r: 7,
      label: `<b>${labels[h.main]?.[0] ?? h.main}</b><br/>${ha(h.ha)} changed in this square`, text: i < 5 ? String(i + 1) : undefined })));
  }, [res?.worked_out]); // eslint-disable-line react-hooks/exhaustive-deps
  const start = async () => {
    setErr(null);
    if (area === "view" && !full.bbox) { setErr("The map isn't ready yet."); return; }
    try {
      const d = await startSummary(full);
      setJob(d.job);
      setLastKey(d.job.key ?? null);
    } catch (e) { setErr(errText(e)); }
  };
  const total = res ? Object.entries(res.ha).filter(([k]) => kind === "land" || ["2", "3", "5", "6", "7", "8"].includes(k)).reduce((a, [, v]) => a + v, 0) : 0;
  return (
    <div className="card">
      <h3>How much, where</h3>
      <div className="chips-row small">
        <button className={area === "country" ? "on" : ""} onClick={() => setArea("country")}>A country</button>
        <button className={area === "view" ? "on" : ""} onClick={() => setArea("view")}>The area in view</button>
        {area === "country" && <CountryChoice value={country} onChange={setCountry} />}
        <span className="muted"> · Detail</span>
        <button className={detail === "quick" ? "on" : ""} onClick={() => setDetail("quick")} title="About 150 map squares: a minute or two">Quick</button>
        <button className={detail === "fine" ? "on" : ""} onClick={() => setDetail("fine")} title="About 1,500 map squares: closer to the real pixels, 10-20 minutes">Fine</button>
        <button onClick={start} disabled={job?.state === "running"}>Work it out</button>
      </div>
      {job?.state === "running" && <p className="small">{job.step} <span className="progress"><span style={{ width: `${job.total ? (job.done ?? 0) / job.total * 100 : 3}%` }} /></span></p>}
      {job?.state === "error" && <p className="small error">{job.error}</p>}
      {err && <p className="small error">{err}</p>}
      {res ? (
        <>
          <p className="small muted">{res.name}{kind === "land" ? `, ${res.from} to ${res.to}` : ""}: read from {res.read.toLocaleString()} map squares at about {res.pixel_m.toLocaleString()} m a pixel
            {res.missing ? ` (${res.missing} could not be had)` : ""}, worked out {res.worked_out.slice(0, 10)}. Coarser than the map, so treat the totals as estimates.</p>
          <table className="summary-table small">
            <thead><tr><th>{kind === "land" ? "Kind of change" : "Water"}</th><th style={{ textAlign: "right" }}>Area</th></tr></thead>
            <tbody>{Object.entries(res.ha).filter(([, v]) => v > 0).sort((a, b) => b[1] - a[1]).map(([k, v]) => (
              <tr key={k}><td><i className="lp-swatch" style={{ background: labels[k]?.[1], display: "inline-block", width: 10, height: 10, marginRight: 6 }} />{labels[k]?.[0] ?? k}</td>
                <td style={{ textAlign: "right" }}>{ha(v)}</td></tr>))}
              {kind === "land" && <tr><td><b>All changes</b></td><td style={{ textAlign: "right" }}><b>{ha(total)}</b></td></tr>}
            </tbody>
          </table>
          {res.hot_spots.length > 0 && <>
            <h4>Squares with the most change</h4>
            <ol className="small">{res.hot_spots.slice(0, 12).map((h, i) => (
              <li key={i}><button className="link" onClick={() => fly(h.lon, h.lat)}>{h.lat.toFixed(3)}, {h.lon.toFixed(3)}</button>: {ha(h.ha)}, mostly {labels[h.main]?.[0] ?? h.main}
                {" "}<button className="link small" onClick={() => void askHere(h.lon, h.lat, 13, `This square changed between ${kind === "land" ? `${res.from} and ${res.to}` : "the 1980s and 2021"}: mostly "${labels[h.main]?.[0] ?? h.main}". What can you see in the picture that fits that, and what might have caused it?`)}>Ask AI</button></li>))}</ol>
          </>}
        </>
      ) : <p className="small muted">Pick a country or the area in view and press Work it out. It runs in the background; you can leave the page.</p>}
    </div>
  );
}

function ChangeTab({ terms }: { terms: SpotTerms | null }) {
  const s = useSettings();
  const lc = changeLayer(s);
  const { map, bbox, fly } = useMapBox();
  const [kinds, setKinds] = useState<string[]>([]);
  const [spots, setSpots] = useState<MapMark[]>([]);
  const changes = terms?.changes ?? CHANGE_LEGEND.map(([label, colour], i) => ({ id: String(i), label, colour, hint: "" }));
  const range = lc.src === "lcyears" ? [1992, 2020] : [2017, 2025];
  const years = Array.from({ length: range[1] - range[0] + 1 }, (_, i) => range[0] + i);
  const raster = useMemo(() => ({ tiles: kinds.length ? `${lc.tiles}&kinds=${kinds.join(",")}` : lc.tiles, attribution: lc.attribution, maxzoom: lc.maxzoom, over: true, opacity: 0.9 }),
    [lc.tiles, kinds]); // eslint-disable-line react-hooks/exhaustive-deps
  const labels = Object.fromEntries(changes.map((c) => [c.id, [c.label, c.colour] as [string, string]]));
  return (
    <>
      <div className="card">
        <div className="chips-row small">
          <select value={lc.src} onChange={(e) => {
            const src = e.target.value as "lc10" | "lcyears";
            void saveSettings(src === "lcyears" ? { spot_change_source: src, spot_change_from: 1992, spot_change_to: 2020 } : { spot_change_source: src, spot_change_from: 2017, spot_change_to: 2025 });
          }} aria-label="Land cover maps">
            <option value="lc10">Esri 10 m (2017-2025)</option><option value="lcyears">ESA 300 m (1992-2020)</option>
          </select>
          From <select value={lc.from} onChange={(e) => void saveSettings({ spot_change_from: +e.target.value })} aria-label="First year">
            {years.slice(0, -1).map((y) => <option key={y}>{y}</option>)}</select>
          to <select value={lc.to} onChange={(e) => void saveSettings({ spot_change_to: +e.target.value })} aria-label="Last year">
            {years.filter((y) => y > lc.from).map((y) => <option key={y}>{y}</option>)}</select>
          <span className="muted"> · Show</span>
          {changes.map((c) => (
            <span key={c.id} className={`chip kind${kinds.length && !kinds.includes(c.id) ? " off" : ""}`} title={c.hint} role="button" tabIndex={0}
              onClick={() => setKinds((k) => (k.includes(c.id) ? k.filter((x) => x !== c.id) : [...k, c.id]))}>
              <i style={{ background: c.colour }} /> {c.label}</span>))}
          {kinds.length > 0 && <button className="link small" onClick={() => setKinds([])}>All</button>}
        </div>
        <div className="map-box"><WorldMap fill values={[]} unit="" decimals={0} diverging={false} raster={raster} marks={spots} onPick={() => {}}
          onMap={(m) => { map.current = m; }} hideScale legend={changes.filter((c) => !kinds.length || kinds.includes(c.id)).map((c) => ({ label: c.label, color: c.colour, shape: "dot" as const }))} /></div>
        <p className="caption">Zoom in to see it in detail: the 10 m maps show single fields and streets from about zoom 12. Each place is worked out the first time it is looked at
          (three years of pictures), then kept, so the first look at a new area is slow. Right-click a patch and pick &quot;What is here?&quot; to ask your local AI about it.
          Esri&apos;s maps are made by a computer model too, so some changes are its mistakes, often at field edges or between grass and crops.</p>
      </div>
      <AreaSummary kind="land" req={{ src: lc.src, from: lc.from, to: lc.to }} bbox={bbox} fly={(lo, la) => fly(lo, la)} labels={labels} onSpots={setSpots} />
    </>
  );
}

function WaterTab({ terms }: { terms: SpotTerms | null }) {
  const s = useSettings();
  const { map, bbox, fly } = useMapBox();
  const [spots, setSpots] = useState<MapMark[]>([]);
  const show = s.spot_water_show ?? "changes";
  const raster = useMemo(() => ({ tiles: waterTiles(show), attribution: terms?.water_attribution ?? "EC JRC / Google, Global Surface Water", maxzoom: 13, over: true, opacity: 0.95 }), [show, terms]);
  const labels = Object.fromEntries((terms?.water ?? []).map((w) => [String(w.code), [w.label, w.draw] as [string, string]]));
  return (
    <>
      <div className="card">
        <div className="chips-row small">
          <button className={show === "changes" ? "on" : ""} onClick={() => void saveSettings({ spot_water_show: "changes" })}>Only changes</button>
          <button className={show === "all" ? "on" : ""} onClick={() => void saveSettings({ spot_water_show: "all" })}>Also water that stayed</button>
          <span className="muted"> · Try</span>
          {[["Aral Sea", 59.6, 45.2, 7], ["Lake Poopó", -67.0, -18.8, 9], ["Three Gorges", 110.3, 30.8, 8], ["Lake Pukaki", 170.17, -44.0, 10]].map(([n, lo, la, z]) => (
            <button key={n as string} className="link small" onClick={() => map.current?.flyTo({ center: [lo as number, la as number], zoom: z as number })}>{n as string}</button>))}
        </div>
        <div className="map-box"><WorldMap fill values={[]} unit="" decimals={0} diverging={false} raster={raster} marks={spots} onPick={() => {}}
          onMap={(m) => { map.current = m; }} hideScale legend={(terms?.water ?? []).filter((w) => show === "all" || w.group !== "same").map((w) => ({ label: w.label, color: w.draw, shape: "dot" as const }))
            .concat(terms ? [] : WATER_LEGEND.map(([label, color]) => ({ label, color, shape: "dot" as const })))} /></div>
        <p className="caption">{terms?.water_attribution ?? "EC JRC / Google, Global Surface Water"}. &quot;Seasonal&quot; means under water for part of the year. Changes
          over a few months (floods) are not here; this compares the two halves of 1984-2021.</p>
      </div>
      <AreaSummary kind="water" req={{}} bbox={bbox} fly={(lo, la) => fly(lo, la)} labels={labels} onSpots={setSpots} />
    </>
  );
}

function ModelsLine({ models }: { models: VisionModels | null }) {
  if (!models) return <p className="small muted">Checking your models…</p>;
  if (models.error) return <p className="small error">{models.error}</p>;
  return <p className="small">Your models that can see pictures: {models.models.map((m) => m.name).join(", ")}. Asking uses <b>{models.ask}</b>, scans use <b>{models.scan}</b>
    {" "}(change them in <Link href="/settings#spotting">Settings &gt; Spotting</Link>).</p>;
}

function AskTab({ models }: { models: VisionModels | null }) {
  const [where, setWhere] = useState("-43.53, 172.64");
  const [zoom, setZoom] = useState(15);
  const go = () => {
    const m = where.match(/(-?\d+(?:\.\d+)?)\s*[,\s]\s*(-?\d+(?:\.\d+)?)/);
    if (m) void askHere(+m[2], +m[1], zoom);
  };
  return (
    <>
      <div className="card">
        <ModelsLine models={models} />
        <div className="chips-row small">
          <label>Latitude, longitude <input value={where} onChange={(e) => setWhere(e.target.value)} style={{ width: 170 }} aria-label="Latitude, longitude" /></label>
          <select value={zoom} onChange={(e) => setZoom(+e.target.value)} aria-label="How close">
            <option value={15}>Close (about 2 km across)</option><option value={13}>Medium (about 8 km)</option><option value={11}>Wide (about 30 km)</option></select>
          <button onClick={go}>What is here?</button>
        </div>
        <div className="map-box"><WorldMap fill values={[]} unit="" decimals={0} diverging={false} onPick={() => {}} /></div>
        <p className="caption">Right-click anywhere on this map (or any map in the app) for &quot;What is here?&quot;. The picture is the 2020 cloud-free Sentinel-2 mosaic at 10 m a pixel:
          fields, towns, mines, ports, airports and dams show; cars, small boats and most single houses do not. A model&apos;s answer is a second opinion, not a measurement.
          Answers are kept on the <Link href="/ai">AI notes</Link> page.</p>
      </div>
    </>
  );
}

// ----------------------------------------------------------------------------- area scans
function ScansTab({ terms, models }: { terms: SpotTerms | null; models: VisionModels | null }) {
  const params = useSearchParams();
  const { map, bbox, fly } = useMapBox();
  const [list, setList] = useState<{ running: string | null; scans: Scan[]; hit_rates: HitRate[] } | null>(null);
  const [mode, setMode] = useState<"scan" | "check">("scan");
  const [area, setArea] = useState<"country" | "view">("country");
  const [country, setCountry] = useState("NZL");
  const [tags, setTags] = useState<string[]>([]);
  const [layers, setLayers] = useState<string[]>(["power_plants", "airports"]);
  const [model, setModel] = useState("");
  const [est, setEst] = useState<{ count: number; minutes: number; note: string } | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [open, setOpen] = useState<string | null>(params.get("scan"));
  const [found, setFound] = useState<Found[]>([]);
  const [filter, setFilter] = useState<"all" | "unmarked" | "yes" | "no">("all");
  const focus = params.get("item");
  const load = () => listScans().then(setList).catch((e) => setErr(errText(e)));
  useEffect(() => { load(); }, []);
  useEffect(() => { if (terms && !tags.length) setTags(terms.tags.map((t) => t.id)); }, [terms]); // eslint-disable-line react-hooks/exhaustive-deps
  const busy = list?.scans.some((s) => s.state === "running" || s.state === "queued");
  useEffect(() => {
    if (!busy) return;
    const t = setInterval(load, 4000);
    return () => clearInterval(t);
  }, [busy]);
  const openScan = list?.scans.find((s) => s.id === open) ?? null;
  useEffect(() => {
    if (!open) { setFound([]); return; }
    scanFound(open).then(setFound).catch(() => setFound([]));
  }, [open, openScan?.found]);
  useEffect(() => {
    const f = found.find((x) => x.id === focus);
    if (f) setTimeout(() => fly(f.lon, f.lat, 12), 500);
  }, [found.length]); // eslint-disable-line react-hooks/exhaustive-deps
  const req = (): ScanReq => ({ mode, entity: area === "country" ? country : null, bbox: area === "view" ? bbox() : null,
    tags: mode === "scan" ? tags : [], layers: mode === "check" ? layers : [], model: model || undefined });
  useEffect(() => { setEst(null); }, [mode, area, country, layers.join()]);
  const estimate = () => { setErr(null); estimateScan(req()).then(setEst).catch((e) => setErr(errText(e))); };
  const start = async () => {
    setErr(null);
    try { const s = await createScan(req()); setOpen(s.id); load(); } catch (e) { setErr(errText(e)); }
  };
  const act = (id: string, a: "pause" | "resume" | "stop") => scanAction(id, a).then(load).catch((e) => setErr(errText(e)));
  const drop = (id: string) => deleteScan(id).then(() => { if (open === id) setOpen(null); load(); }).catch((e) => setErr(errText(e)));
  const setMark = async (f: Found, v: "yes" | "no" | null) => {
    if (!open) return;
    const r = await markFound(open, f.id, v).catch(() => null);
    if (r) setFound((all) => all.map((x) => (x.id === f.id ? r : x)));
  };
  const tagOf = new Map((terms?.tags ?? []).map((t) => [t.id, t]));
  const shown = found.filter((f) => filter === "all" || (filter === "unmarked" ? !f.mark : f.mark === filter))
    .sort((a, b) => (a.id === focus ? -1 : b.id === focus ? 1 : b.sure - a.sure));
  const marks: MapMark[] = found.map((f) => ({ key: f.id, lng: f.lon, lat: f.lat, r: 5, hollow: f.mark !== "yes",
    color: f.layer ? (f.verdict === "no" ? "#c92a2a" : f.verdict === "yes" ? "#2b8a3e" : "#868e96") : tagOf.get(f.tag ?? "")?.colour ?? "#862e9c",
    label: `<b>${f.name ?? tagOf.get(f.tag ?? "")?.label ?? f.tag}</b><br/>${Math.round(f.sure * 100)}% sure${f.note ? `<br/>${f.note.replace(/[<>&]/g, "")}` : ""}` }));
  return (
    <>
      <div className="card">
        <h3>New scan</h3>
        <ModelsLine models={models} />
        <div className="chips-row small">
          <button className={mode === "scan" ? "on" : ""} onClick={() => setMode("scan")} title="Every square of the area, for the things you tick">Look for things</button>
          <button className={mode === "check" ? "on" : ""} onClick={() => setMode("check")} title="The map's own places in the area: does the picture show what the map says?">Check the map&apos;s places</button>
          <span className="muted"> · in</span>
          <button className={area === "country" ? "on" : ""} onClick={() => setArea("country")}>A country</button>
          <button className={area === "view" ? "on" : ""} onClick={() => setArea("view")}>The area in view</button>
          {area === "country" && <CountryChoice value={country} onChange={setCountry} />}
        </div>
        {mode === "scan" ? (
          <div className="chips-row small">{(terms?.tags ?? []).map((t) => (
            <span key={t.id} className={`chip kind${tags.includes(t.id) ? "" : " off"}`} title={`Looks like ${t.looks}`} role="button" tabIndex={0}
              onClick={() => setTags((x) => (x.includes(t.id) ? x.filter((y) => y !== t.id) : [...x, t.id]))}><i style={{ background: t.colour }} /> {t.label}</span>))}
          </div>
        ) : (
          <div className="chips-row small">{Object.keys(terms?.checkable ?? {}).map((l) => (
            <span key={l} className={`chip kind${layers.includes(l) ? "" : " off"}`} title={terms?.checkable[l]} role="button" tabIndex={0}
              onClick={() => setLayers((x) => (x.includes(l) ? x.filter((y) => y !== l) : [...x, l]))}>{l.replace(/_/g, " ")}</span>))}
          </div>
        )}
        <div className="chips-row small">
          <select value={model} onChange={(e) => setModel(e.target.value)} aria-label="Model">
            <option value="">{models?.scan ? `${models.scan} (fastest)` : "Model"}</option>
            {(models?.models ?? []).filter((m) => m.name !== models?.scan).map((m) => <option key={m.name} value={m.name}>{m.name}</option>)}
          </select>
          <button onClick={estimate}>How long?</button>
          <button onClick={start} disabled={!models?.scan && !model}>Start</button>
          {est && <span>{est.count.toLocaleString()} {mode === "check" ? "places" : "squares"}, about {mins(est.minutes)} at {est.count ? "1-2 s each" : ""} (less where it&apos;s mostly sea)</span>}
        </div>
        <p className="caption">New Zealand is about 21,000 squares: a night with a small model. Bigger models are surer but two or three times slower. Only one scan runs at a time;
          others wait their turn. Scans stop when the app stops and wait, paused, for you to resume them. Nothing runs unless you start it.</p>
        {err && <p className="small error">{err}</p>}
      </div>

      <div className="card">
        <h3>Scans</h3>
        {!list?.scans.length ? <p className="small muted">No scans yet.</p> : (
          <table className="summary-table small">
            <thead><tr><th>Scan</th><th>Model</th><th>Progress</th><th>Found</th><th /></tr></thead>
            <tbody>{list.scans.map((s) => (
              <tr key={s.id} className={open === s.id ? "on" : ""}>
                <td><button className="link" onClick={() => setOpen(s.id)}>{s.name}</button><br /><span className="muted">{s.created.slice(0, 16).replace("T", " ")} · {s.state}</span>
                  {s.error && <><br /><span className="error">{s.error}</span></>}{s.note && <><br /><span className="muted">{s.note}</span></>}</td>
                <td>{s.model}</td>
                <td style={{ minWidth: 140 }}>{s.done.toLocaleString()} of {s.total.toLocaleString()}{s.skipped ? ` (${s.skipped.toLocaleString()} sea)` : ""}
                  <span className="progress"><span style={{ width: `${s.total ? s.done / s.total * 100 : 0}%` }} /></span>
                  {s.state === "running" && s.done > s.skipped && s.seconds > 0 && <span className="muted">about {mins((s.total - s.done) * s.seconds / Math.max(1, s.done - s.skipped) / 60)} to go</span>}
                  {s.errors > 0 && <span className="muted"> · {s.errors} failed</span>}</td>
                <td>{s.found.toLocaleString()}</td>
                <td>{["queued", "running"].includes(s.state) && <button className="link small" onClick={() => act(s.id, "pause")}>Pause</button>}
                  {["paused", "error", "stopped"].includes(s.state) && s.done < s.total && <button className="link small" onClick={() => act(s.id, "resume")}>Resume</button>}
                  {" "}<button className="link small" onClick={() => drop(s.id)}>Delete</button></td>
              </tr>))}</tbody>
          </table>
        )}
        {!!list?.hit_rates.length && <>
          <h4>How often the model was right (your marks)</h4>
          <table className="summary-table small"><thead><tr><th>Thing</th><th>Reported</th><th>Right</th><th>Wrong</th><th>Right share</th></tr></thead>
            <tbody>{list.hit_rates.map((h) => <tr key={h.tag}><td>{h.label}</td><td>{h.found}</td><td>{h.yes}</td><td>{h.no}</td><td>{h.right_pct == null ? "–" : `${h.right_pct}%`}</td></tr>)}</tbody></table>
        </>}
      </div>

      {openScan && (
        <div className="card">
          <h3>{openScan.name}: what it found</h3>
          <div className="map-box"><WorldMap fill values={[]} unit="" decimals={0} diverging={false} marks={marks} onPick={() => {}} onMap={(m) => { map.current = m; }}
            onMark={(k) => { const f = found.find((x) => x.id === k); if (f) document.getElementById(`found-${f.id}`)?.scrollIntoView({ behavior: "smooth", block: "center" }); }} /></div>
          <div className="chips-row small">{(["all", "unmarked", "yes", "no"] as const).map((f) => (
            <button key={f} className={filter === f ? "on" : ""} onClick={() => setFilter(f)}>{f === "all" ? `All (${found.length})` : f === "unmarked" ? "Not marked" : f === "yes" ? "Marked right" : "Marked wrong"}</button>))}</div>
          {!found.length && <p className="small muted">Nothing found yet.</p>}
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(230px, 1fr))", gap: 10 }}>
            {shown.slice(0, 120).map((f) => (
              <div key={f.id} id={`found-${f.id}`} className="card" style={{ padding: 8, outline: f.id === focus ? "2px solid var(--accent)" : undefined }}>
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img src={foundPicture(openScan.id, f)} alt="" loading="lazy" style={{ width: "100%", aspectRatio: "1", objectFit: "cover", borderRadius: 4 }} />
                <div className="small"><b>{f.layer ? f.name : tagOf.get(f.tag ?? "")?.label ?? f.tag}</b>
                  {f.layer ? <> · looks like it: <b>{f.verdict}</b></> : f.where ? <span className="muted"> · {f.where}</span> : null}
                  <span className="muted"> · {Math.round(f.sure * 100)}% sure</span></div>
                {f.note && <div className="small muted">{f.note}</div>}
                <div className="chips-row small" style={{ marginTop: 4 }}>
                  <button className={f.mark === "yes" ? "on" : ""} onClick={() => setMark(f, f.mark === "yes" ? null : "yes")} title="The model was right">✓ Right</button>
                  <button className={f.mark === "no" ? "on" : ""} onClick={() => setMark(f, f.mark === "no" ? null : "no")} title="The model was wrong">✗ Wrong</button>
                  <button className="link small" onClick={() => fly(f.lon, f.lat, 13)}>Map</button>
                  <button className="link small" onClick={() => void askHere(f.lon, f.lat, 15)}>Ask AI</button>
                </div>
              </div>))}
          </div>
          {shown.length > 120 && <p className="small muted">Showing the 120 it was surest of; mark some to narrow the list.</p>}
        </div>
      )}
    </>
  );
}

function SpottingView() {
  const router = useRouter();
  const params = useSearchParams();
  const [tab, setTab] = useState<Tab>((params.get("tab") as Tab) || "change");
  const [terms, setTerms] = useState<SpotTerms | null>(null);
  const [models, setModels] = useState<VisionModels | null>(null);
  const urlTab = params.get("tab") as Tab | null;
  useEffect(() => { if (urlTab && TABS.some(([t]) => t === urlTab)) setTab(urlTab); }, [urlTab]);
  useEffect(() => { logHistory({ kind: "page", title: "Spotting", url: "/spotting", detail: "page" }); spotTerms().then(setTerms).catch(() => undefined); }, []);
  useEffect(() => { if ((tab === "ask" || tab === "scans") && !models) visionModels().then(setModels).catch((e) => setModels({ models: [], ask: null, scan: null, error: errText(e) })); }, [tab]); // eslint-disable-line react-hooks/exhaustive-deps
  const go = (t: Tab) => { setTab(t); router.replace(`/spotting?tab=${t}`, { scroll: false }); };
  return (
    <div className="grid sector-page">
      <div className="title-row"><h1>Spotting</h1>
        <AskButton title={`Spotting: ${TABS.find((t) => t[0] === tab)?.[1]}`} parts={async () => [
          { key: "description", kind: "description", label: "What this tab shows", text: INTRO[tab] }]} /></div>
      <div className="seg" role="tablist">{TABS.map(([t, label]) => <button key={t} role="tab" aria-selected={tab === t} className={tab === t ? "on" : ""} onClick={() => go(t)}>{label}</button>)}</div>
      <p className="ink-2" style={{ marginTop: 0, maxWidth: 860 }}>{INTRO[tab]}</p>
      {tab === "change" && <ChangeTab terms={terms} />}
      {tab === "water" && <WaterTab terms={terms} />}
      {tab === "ask" && <AskTab models={models} />}
      {tab === "scans" && <ScansTab terms={terms} models={models} />}
    </div>
  );
}

export default function SpottingPage() {
  return <Suspense fallback={null}><SpottingView /></Suspense>;
}
