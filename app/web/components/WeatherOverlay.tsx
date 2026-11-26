"use client";

import Link from "next/link";
import type * as maplibregl from "maplibre-gl";
import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import ForecastCard from "@/components/ForecastCard";
import WindLines from "@/components/WindLines";
import { get } from "@/lib/api";
import {
  atLine, forecastFields, fmtHour, fromNow, hasWaves, nowStep, setWeatherStep, useRadar, useWeatherStatus, useWeatherStep, validTime,
  WAVE_FIELDS, waveStep, windyLink, type WeatherAt, type WeatherField,
} from "@/lib/weather";

// The weather bar over a map with a weather layer on: the forecast hour (slider, play, now), the colour
// keys, the values under the pointer, and the forecast for a clicked place.
export default function WeatherOverlay({ map, letters, point, onClosePoint }: {
  map: maplibregl.Map | null; letters: string; point: [number, number] | null; onClosePoint: () => void;
}) {
  const fields = forecastFields(letters);
  const lines = letters.includes("^");
  const timed = fields.length > 0 || lines; // layers that follow the forecast hour
  const waves = hasWaves(letters);
  const mainFields = fields.filter((f) => !WAVE_FIELDS.includes(f));
  const { status: st, error } = useWeatherStatus(true, waves);
  const chosen = useWeatherStep();
  const radar = useRadar(letters.includes("@"));
  const [box, setBox] = useState<HTMLElement | null>(null);
  const [open, setOpen] = useState(true);
  const [playing, setPlaying] = useState(false);
  const [under, setUnder] = useState<WeatherAt | null>(null);
  useEffect(() => { setBox(map ? map.getContainer() : null); }, [map]);

  const steps = st?.steps ?? [];
  const step = chosen !== null && steps.includes(chosen) ? chosen : st ? nowStep(st) : null;
  const idx = step === null ? -1 : steps.indexOf(step);
  const wstep = waves ? waveStep(st, step) : null;

  // Play: an hour step every 0.8 seconds to the end.
  const stepRef = useRef(step);
  stepRef.current = step;
  useEffect(() => {
    if (!playing) return;
    const t = setInterval(() => {
      const i = steps.indexOf(stepRef.current ?? -1);
      if (i < 0 || i >= steps.length - 1) { setPlaying(false); return; }
      setWeatherStep(steps[i + 1]);
    }, 800);
    return () => clearInterval(t);
  }, [playing, steps]);

  // The values under the pointer, asked for a moment after it stops.
  useEffect(() => {
    if (!map || !timed || step === null) { setUnder(null); return; }
    let timer: ReturnType<typeof setTimeout> | undefined;
    let live = true;
    const move = (e: maplibregl.MapMouseEvent) => {
      clearTimeout(timer);
      const w = e.lngLat.wrap();
      timer = setTimeout(() => {
        get<WeatherAt>("/weather/at", { lat: w.lat.toFixed(3), lon: w.lng.toFixed(3), step, ...(wstep !== null ? { wave_step: wstep } : {}) })
          .then((a) => live && setUnder(a)).catch(() => live && setUnder(null));
      }, 220);
    };
    const leave = () => { clearTimeout(timer); setUnder(null); };
    map.on("mousemove", move);
    map.getCanvas().addEventListener("mouseleave", leave);
    return () => { live = false; clearTimeout(timer); map.off("mousemove", move); map.getCanvas().removeEventListener("mouseleave", leave); };
  }, [map, timed, step, wstep]);

  if (!box) return null;
  const when = st && step !== null ? validTime(st, step) : null;
  const lastRadar = radar.radar?.frames.at(-1);
  const bar = (
    <div className={`wx-bar${open ? "" : " shut"}`} onMouseDown={(e) => e.stopPropagation()} onWheel={(e) => e.stopPropagation()}>
      <div className="wx-head">
        <b>Weather</b>
        {when && timed && <span className="small">{fmtHour(when)} <span className="muted">({fromNow(when)})</span></span>}
        <button className="small" onClick={() => setOpen(!open)} aria-expanded={open}>{open ? "Hide" : "Show"}</button>
      </div>
      {open && <>
        {st && !st.on && <p className="small">Weather is switched off in <Link href="/settings#weather">Settings &gt; Climate</Link>.</p>}
        {error && <p className="error small">The weather status did not load: {error}</p>}
        {st?.error && <p className="error small">{st.error}</p>}
        {timed && st?.on && !st.run && (
          <p className="small">{st.fetching ? `Downloading ${st.model === "ecmwf" ? "ECMWF's" : "NOAA's"} forecast: hour ${st.fetching.step} (${st.fetching.done + 1} of ${st.fetching.of}).`
            : st.note || `Looking for ${st.model === "ecmwf" ? "ECMWF's" : "NOAA's"} latest forecast run…`} The maps appear as soon as the first hours are in.</p>
        )}
        {timed && st?.run && steps.length > 0 && (
          <div className="wx-time">
            <button className="small" onClick={() => setPlaying(!playing)} aria-pressed={playing}>{playing ? "Pause" : "Play"}</button>
            <input type="range" min={0} max={steps.length - 1} value={Math.max(0, idx)} aria-label="Forecast hour"
              aria-valuetext={when ? `${fmtHour(when)}, ${fromNow(when)}` : ""}
              onChange={(e) => { setPlaying(false); setWeatherStep(steps[+e.target.value]); }} />
            <button className="small" onClick={() => { setPlaying(false); setWeatherStep(null); }}>Now</button>
          </div>
        )}
        {timed && st?.fetching && st.run && (
          <span className="caption">Downloading a newer run: {st.fetching.done + 1} of {st.fetching.of} hours. The maps switch over when it is complete.</span>
        )}
        {waves && st?.on && !st.waves.on && <p className="small">Waves and swell are switched off in <Link href="/settings#weather">Settings &gt; Climate</Link>.</p>}
        {waves && st?.waves.on && st.waves.error && <p className="error small">{st.waves.error}</p>}
        {waves && st?.waves.on && (!st.waves.run || st.waves.fetching) && (
          <span className="caption">{st.waves.fetching
            ? `Downloading NOAA's wave forecast: ${st.waves.fetching.done + 1} of ${st.waves.fetching.of} steps (about ${st.waves.mb_per_run} MB a run).`
            : st.waves.note || "Looking for NOAA's latest wave forecast…"}</span>
        )}
        {fields.map((f) => <Key key={f} field={f} st={st} />)}
        {lines && <span className="small">Wind lines: moving specks carried by the wind{st?.run ? "" : " (once the forecast is in)"}; brighter = stronger.</span>}
        {letters.includes("@") && (
          <span className="small">{radar.error ? <span className="error">{radar.error}</span>
            : lastRadar ? <>Rain radar, {fmtHour(new Date(lastRadar.time * 1000))} <span className="muted">(RainViewer; only where there are radars)</span></>
              : "Loading the rain radar…"}</span>
        )}
        {letters.includes(":") && <span className="small">Clouds from satellite: the latest infrared, about an hour old. <span className="muted">No picture over Europe, Africa and the Middle East (NASA has no free Meteosat tiles).</span></span>}
        {timed && <span className="small wx-under">{under ? atLine(under) || "No forecast here" : "Point at the map for the values there."}</span>}
        <span className="caption">Click the map for that place&apos;s forecast (shift-click: the country).
          {st?.run_time && (mainFields.length > 0 || lines) ? ` ${st.model_name} run of ${fmtHour(new Date(st.run_time))}${st.model === "ecmwf" ? " (ECMWF open data, CC BY 4.0)" : ""}.` : ""}
          {waves && st?.waves.run_time ? ` NOAA GFS-Wave run of ${fmtHour(new Date(st.waves.run_time))}.` : ""}
          {map && <> <a href={windyLink(map.getCenter().lat, map.getCenter().wrap().lng, map.getZoom() + 1)} target="_blank" rel="noreferrer">Open this view in Windy</a></>}
        </span>
      </>}
    </div>
  );
  const card = point ? (
    <div className="wx-card" onMouseDown={(e) => e.stopPropagation()} onWheel={(e) => e.stopPropagation()}>
      <ForecastCard lat={point[1]} lon={point[0]} onClose={onClosePoint} hours={72} />
    </div>
  ) : null;
  const flow = lines && map && st?.on && st.run && step !== null
    ? <WindLines map={map} run={st.run} step={step} light={letters.includes(")") || letters.includes("!")} /> : null;
  return createPortal(<>{flow}{bar}{card}</>, box);
}

function Key({ field, st }: { field: WeatherField; st: ReturnType<typeof useWeatherStatus>["status"] }) {
  if (!st) return null;
  if (field === "pressure") return <span className="small">Pressure lines every {st.isobar_hpa} hPa, darker every {st.isobar_hpa * 5} hPa</span>;
  const stops = st.legends[field];
  if (!stops?.length) return null;
  // Stops evenly spaced (rain's run from 0.05 to 50 mm/h would crowd at one end on a straight scale).
  const at = (i: number) => (i / (stops.length - 1)) * 100;
  const grad = `linear-gradient(90deg, ${stops.map(([, c], i) => `${c} ${at(i).toFixed(1)}%`).join(", ")})`;
  const ticks = stops.map(([v], i) => ({ v, i })).filter(({ i }) => i % Math.ceil(stops.length / 5) === 0 || i === stops.length - 1);
  return (
    <div className="wx-key">
      <span className="small">{st.fields[field].label}, {st.fields[field].unit}</span>
      <div className="wx-ramp" style={{ background: grad }} />
      <div className="wx-ticks mono">{ticks.map(({ v, i }) => <span key={v} style={{ left: `${at(i)}%` }}>{v}</span>)}</div>
    </div>
  );
}
