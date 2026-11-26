"use client";

// Timelapse since 1984: one Landsat picture a year for a box, played as a film, with the water,
// green and built-up land measured from the same pictures underneath.

import type * as maplibregl from "maplibre-gl";
import type { EChartsOption } from "echarts";
import { useEffect, useMemo, useRef, useState } from "react";
import EChart from "@/components/EChart";
import WorldMap from "@/components/WorldMap";
import { openAsk } from "@/lib/ai";
import { saveSettings, useSettings } from "@/lib/settings";
import { deleteTimelapse, frameUrl, makeTimelapse, type Timelapse, TIMELAPSE_PLACES, timelapses } from "@/lib/thennow";

const KINDS: [keyof Pick<Required<Timelapse["years"][number]>, "water" | "green" | "built">, string, string][] = [
  ["water", "Water", "#1c7ed6"], ["green", "Green land (trees, grass, crops)", "#2b8a3e"], ["built", "Built-up or bare", "#c92a2a"]];
const ha = (v: number) => (v >= 1e5 ? `${Math.round(v / 100).toLocaleString()} km²` : `${Math.round(v).toLocaleString()} ha`);

export default function TimelapseView({ start }: { start?: { bbox: number[]; name: string } | null }) {
  const s = useSettings();
  const map = useRef<maplibregl.Map | null>(null);
  const [list, setList] = useState<{ running: string | null; timelapses: Timelapse[] } | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const [name, setName] = useState(start?.name ?? "");
  const [box, setBox] = useState<number[] | null>(start?.bbox ?? null);
  const [err, setErr] = useState<string | null>(null);
  const [year, setYear] = useState<number | null>(null);
  const [playing, setPlaying] = useState(false);
  const load = () => timelapses().then((d) => { setList(d); setOpen((o) => o ?? d.timelapses[0]?.id ?? null); }).catch((e) => setErr(String(e.message || e)));
  useEffect(() => { load(); }, []); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!list?.timelapses.some((t) => t.state === "running" || t.state === "queued")) return;
    const t = setInterval(load, 4000);
    return () => clearInterval(t);
  }, [list]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (start?.bbox) { setBox(start.bbox); setName(start.name); } }, [start]);
  useEffect(() => {
    const m = map.current;
    if (m && box) m.fitBounds([[box[0], box[1]], [box[2], box[3]]], { padding: 10, animate: false });
  }, [box]);

  const tl = list?.timelapses.find((t) => t.id === open) ?? null;
  const frames = useMemo(() => (tl?.years ?? []).filter((y) => y.scene), [tl]);
  useEffect(() => { setYear(frames.length ? frames[0].year : null); setPlaying(false); }, [tl?.id]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (year == null && frames.length) setYear(frames[0].year); }, [frames.length]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!playing || !frames.length) return;
    const t = setInterval(() => setYear((y) => {
      const i = frames.findIndex((f) => f.year === y);
      return frames[(i + 1) % frames.length].year;
    }), 700);
    return () => clearInterval(t);
  }, [playing, frames]);
  const cur = frames.find((f) => f.year === year) ?? null;

  const chart = useMemo<EChartsOption | null>(() => {
    if (!frames.length) return null;
    return {
      grid: { left: 64, right: 16, top: 28, bottom: 28 },
      legend: { top: 0, data: KINDS.map(([, label]) => label) },
      tooltip: { trigger: "axis", valueFormatter: (v) => ha(Number(v)) },
      xAxis: { type: "value", min: frames[0].year, max: frames.at(-1)!.year, axisLabel: { formatter: (v: number) => String(v) } },
      yAxis: { type: "value", axisLabel: { formatter: (v: number) => ha(v) } },
      series: [
        ...KINDS.map(([k, label, colour]) => ({ name: label, type: "line" as const, color: colour, showSymbol: true, symbolSize: 4,
          data: frames.map((f) => [f.year, f[k] ?? null]), endLabel: { show: true, formatter: () => "" } })),
        { name: "year", type: "line" as const, data: [], markLine: { silent: true, symbol: "none", lineStyle: { color: "#868e96", type: "dashed" as const },
          data: year ? [{ xAxis: year }] : [] } },
      ],
    };
  }, [frames, year]);

  const make = async () => {
    setErr(null);
    const m = map.current;
    const bb = box ?? (m ? (() => { const b = m.getBounds(); return [b.getWest(), b.getSouth(), b.getEast(), b.getNorth()]; })() : null);
    if (!bb) return;
    try {
      const t = await makeTimelapse(bb.map((v) => Math.round(v * 1000) / 1000), name || "My box", s.timelapse_summers);
      setOpen(t.id);
      setBox(null);
      load();
    } catch (e) { setErr(String((e as Error).message || e).replace(/^\d+: /, "")); }
  };
  const ask = () => {
    if (!tl) return;
    const rows = frames.map((f) => `${f.year}: water ${Math.round(f.water ?? 0)} ha, green ${Math.round(f.green ?? 0)} ha, built-up or bare ${Math.round(f.built ?? 0)} ha (picture of ${f.date}, ${f.platform}, ${f.cloud}% cloud in the scene)`);
    openAsk({ title: `Timelapse: ${tl.name}`, parts: [
      { key: "box", kind: "page", label: "The box", text: `${tl.name}: ${tl.km[0]} by ${tl.km[1]} km (west ${tl.bbox[0]}, south ${tl.bbox[1]}, east ${tl.bbox[2]}, north ${tl.bbox[3]}). `
        + "Figures are measured from one Landsat picture a year (30 m pixels): water where NDWI > 0.1, green where NDVI > 0.3, built-up or bare where NDBI > 0 and NDVI < 0.2. "
        + "Clouds, snow, season and tide move the figures from year to year." },
      { key: "years", kind: "data", label: "Each year", text: rows.join("\n") },
    ], question: "What are the big changes in this place since 1984, when did they happen, and what probably caused them? Separate real trends from noise." });
  };
  return (
    <>
      <div className="card">
        <h3 style={{ marginTop: 0 }}>Make a timelapse</h3>
        <div className="chips-row small">
          <span className="muted">Try</span>
          {TIMELAPSE_PLACES.map(([n, bb]) => <button key={n} className="link small" onClick={() => { setBox(bb); setName(n); }}>{n}</button>)}
        </div>
        <div className="map-box" style={{ height: 320 }}><WorldMap fill values={[]} unit="" decimals={0} diverging={false} onPick={() => {}} onMap={(m) => { map.current = m; }} hideScale
          boxes={box ? [{ name: name || "Box", west: box[0], south: box[1], east: box[2], north: box[3] }] : undefined} /></div>
        <div className="chips-row small">
          <label>Name <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Lake Pukaki" style={{ width: 200 }} /></label>
          <label><input type="checkbox" checked={s.timelapse_summers} onChange={(e) => void saveSettings({ timelapse_summers: e.target.checked })} /> Summers only</label>
          <button onClick={make}>{box ? "Make a timelapse of the box" : "Make a timelapse of this view"}</button>
          {box && <button className="link small" onClick={() => setBox(null)}>Use the map&apos;s view instead</button>}
        </div>
        {err && <p className="small warn-text">{err}</p>}
        <p className="caption">Made on this PC from Microsoft Planetary Computer&apos;s Landsat copies: about 40 pictures, a few minutes, 5-20 MB, kept until you delete it.
          At most 120 km across; 30 m pixels show lakes, coasts, mines, towns, forests and glaciers, not single buildings. Landsat 5 to 2011, Landsat 7 for 2012
          (its pictures have stripes), Landsat 8 and 9 after.</p>
      </div>
      {list && list.timelapses.length > 0 && (
        <div className="card">
          <div className="chips-row small">
            {list.timelapses.map((t) => (
              <button key={t.id} className={open === t.id ? "on" : ""} onClick={() => setOpen(t.id)}>
                {t.name}{t.state === "done" ? "" : t.state === "error" ? " (stopped)" : ` (${t.done} of ${t.total})`}</button>))}
          </div>
          {tl && (
            <>
              <div className="chips-row small">
                <button onClick={() => setPlaying((p) => !p)} disabled={frames.length < 2}>{playing ? "❚❚ Pause" : "▶ Play"}</button>
                {frames.length > 0 && <input type="range" min={0} max={frames.length - 1} value={Math.max(0, frames.findIndex((f) => f.year === year))}
                  onChange={(e) => { setPlaying(false); setYear(frames[+e.target.value].year); }} style={{ width: 320 }} aria-label="Year" />}
                <b>{cur ? cur.year : ""}</b>
                {cur && <span className="muted">{cur.date} · {cur.platform} · {cur.cloud}% cloud in the scene</span>}
                <button className="link small" onClick={ask} disabled={!frames.length}>Ask AI about the changes</button>
                <button className="link small" onClick={() => { if (confirm(`Delete the timelapse "${tl.name}"?`)) void deleteTimelapse(tl.id).then(() => { setOpen(null); load(); }); }}>Delete</button>
              </div>
              {tl.state === "error" && <p className="small warn-text">Stopped: {tl.error}</p>}
              {(tl.state === "running" || tl.state === "queued") && <p className="small">Making it: {tl.done} of {tl.total} years so far. You can leave this page.</p>}
              {cur ? (
                <div style={{ display: "flex", justifyContent: "center", background: "#111", borderRadius: 6 }}>
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img src={frameUrl(tl.id, cur.year)} alt={`${tl.name} in ${cur.year}`} style={{ maxWidth: "100%", maxHeight: 560, imageRendering: "auto" }} />
                </div>) : <p className="small muted">No pictures yet.</p>}
              {chart && <EChart option={() => chart} height={240} label={`Water, green and built-up land in ${tl.name}`} />}
              {cur && <p className="small">{cur.year}: water {ha(cur.water ?? 0)}, green {ha(cur.green ?? 0)}, built-up or bare {ha(cur.built ?? 0)}
                {cur.seen != null && cur.seen < 0.95 ? ` (only ${Math.round(cur.seen * 100)}% of the box was in that picture)` : ""}.</p>}
              {tl.years.some((y) => y.missing) && <p className="caption">No picture for {tl.years.filter((y) => y.missing).map((y) => y.year).join(", ")} (no clear picture that
                {tl.summers ? " summer" : " year"}, or it could not be read).</p>}
              <p className="caption">{tl.attribution}. Each year is the least cloudy picture {tl.summers ? "from the summer months " : ""}that covers the box; the chart is
                measured from the same picture, so clouds, snow, season and tide make it wobble. Look at the trend, not single years.</p>
            </>
          )}
        </div>
      )}
    </>
  );
}
