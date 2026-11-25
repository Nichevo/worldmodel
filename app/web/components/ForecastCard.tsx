"use client";

import { useEffect, useMemo, useState } from "react";
import { compass, hourDate, placeForecast, r0, r1, type PlaceForecast } from "@/lib/weather";

// A place's weather now, the days ahead and an hourly chart (temperature line, rain bars), from
// Open-Meteo or MET Norway (Settings > Climate > Weather). Used by the map's click-for-forecast
// and the city page.
export default function ForecastCard({ lat, lon, title, hours = 72, onClose }: {
  lat: number; lon: number; title?: string; hours?: number; onClose?: () => void;
}) {
  const [f, setF] = useState<PlaceForecast | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    let live = true;
    setF(null);
    setErr(null);
    placeForecast(lat, lon).then((d) => live && setF(d)).catch((e) => live && setErr(String(e.message || e)));
    return () => { live = false; };
  }, [lat, lon]);
  const name = title ?? `${Math.abs(lat).toFixed(2)}°${lat < 0 ? "S" : "N"}, ${Math.abs(lon).toFixed(2)}°${lon < 0 ? "W" : "E"}`;
  const n = f?.now;
  return (
    <div className="wx-forecast">
      <div className="wx-head">
        <b>{name}</b>
        {onClose && <button className="small" onClick={onClose} aria-label="Close the forecast">×</button>}
      </div>
      {err && <p className="error small">{err}</p>}
      {f?.error && <p className="error small">{f.error}</p>}
      {!f && !err && <p className="small muted">Asking for the forecast…</p>}
      {n && (
        <div className="wx-now">
          <span className="wx-big">{r0(n.temp)}°</span>
          <span className="small">
            <b>{n.words ?? ""}</b>{n.feels != null ? ` · feels ${r0(n.feels)}°` : ""}<br />
            Wind {r0(n.wind)} km/h {compass(n.from_deg)}{n.gust != null ? `, gusts ${r0(n.gust)}` : ""} · cloud {r0(n.cloud)}%
            {n.humidity != null ? ` · humidity ${r0(n.humidity)}%` : ""}{n.rain ? ` · rain ${r1(n.rain)} mm` : ""}
          </span>
        </div>
      )}
      {f?.daily && f.daily.length > 0 && (
        <div className="wx-days" role="list">
          {f.daily.map((d) => (
            <div key={d.date} className="wx-day" role="listitem" title={d.words ?? ""}>
              <span className="muted">{new Date(`${d.date}T12:00:00Z`).toLocaleDateString(undefined, { weekday: "short", timeZone: "UTC" })}</span>
              <b>{r0(d.high)}°</b><span className="muted">{r0(d.low)}°</span>
              <span className="wx-rain">{d.rain ? `${r1(d.rain)} mm` : "dry"}{d.rain_chance != null ? ` ${r0(d.rain_chance)}%` : ""}</span>
              <span className="muted">{r0(d.wind)} {compass(d.from_deg)}</span>
            </div>
          ))}
        </div>
      )}
      {f?.hourly && <HourChart f={f} hours={hours} />}
      {f?.source_name && (
        <span className="caption">
          {f.source_name}{f.source === "open_meteo" && f.timezone ? `, times in ${f.timezone}` : ", times in your time zone"}.{" "}
          Rain chance is the day&apos;s highest hourly chance. <a href={f.link} target="_blank" rel="noreferrer">Source</a>
        </span>
      )}
    </div>
  );
}

// Temperature as a line, rain as bars, the next `hours` hours.
function HourChart({ f, hours }: { f: PlaceForecast; hours: number }) {
  const h = f.hourly!;
  const pts = useMemo(() => {
    const now = Date.now() - 3_600_000;
    const out: { t: Date; temp: number | null; rain: number | null; label: string }[] = [];
    h.time.forEach((s, i) => {
      const t = hourDate(f, s);
      if (t.getTime() >= now && out.length < hours) out.push({ t, temp: h.temp[i], rain: h.rain[i], label: s });
    });
    return out;
  }, [f, h, hours]);
  if (pts.length < 2) return null;
  const W = 320, H = 92, top = 12, bottom = 16;
  const temps = pts.map((p) => p.temp).filter((v): v is number => v !== null);
  const lo = Math.floor(Math.min(...temps)) - 1, hi = Math.ceil(Math.max(...temps)) + 1;
  const maxRain = Math.max(2, ...pts.map((p) => p.rain ?? 0));
  const x = (i: number) => (i / (pts.length - 1)) * (W - 2) + 1;
  const y = (v: number) => top + (1 - (v - lo) / (hi - lo || 1)) * (H - top - bottom);
  const line = pts.map((p, i) => (p.temp === null ? "" : `${i === 0 ? "M" : "L"}${x(i).toFixed(1)} ${y(p.temp).toFixed(1)}`)).join(" ");
  const bw = Math.max(1, (W - 2) / pts.length - 0.5);
  // A tick at each local midnight (the place's day for Open-Meteo, yours for MET Norway).
  const days = pts.map((p, i) => ({ i, d: p.label.slice(11, 13) === "00" || (f.source !== "open_meteo" && p.t.getHours() === 0) }))
    .filter((p) => p.d && p.i > 0);
  const hiAt = temps.indexOf(Math.max(...temps));
  const loAt = temps.indexOf(Math.min(...temps));
  return (
    <svg className="wx-chart" viewBox={`0 0 ${W} ${H}`} role="img"
      aria-label={`Next ${pts.length} hours: ${Math.round(Math.min(...temps))} to ${Math.round(Math.max(...temps))} °C, up to ${r1(Math.max(...pts.map((p) => p.rain ?? 0)))} mm of rain an hour`}>
      {pts.map((p, i) => (p.rain ? (
        <rect key={i} x={x(i) - bw / 2} y={H - bottom - (p.rain / maxRain) * (H - top - bottom)} width={bw}
          height={(p.rain / maxRain) * (H - top - bottom)} fill="#2878e6" opacity={0.55} />
      ) : null))}
      {days.map((d) => <line key={d.i} x1={x(d.i)} x2={x(d.i)} y1={top - 4} y2={H - bottom} stroke="var(--border)" />)}
      {days.map((d) => (
        <text key={`t${d.i}`} x={x(d.i) + 2} y={H - 4} fontSize="9" fill="var(--muted)">
          {pts[d.i].t.toLocaleDateString(undefined, { weekday: "short", ...(f.source === "open_meteo" ? { timeZone: f.timezone } : {}) })}
        </text>
      ))}
      <path d={line} fill="none" stroke="#e8590c" strokeWidth={1.8} />
      {[hiAt, loAt].filter((i) => i >= 0).map((k) => {
        const idx = pts.findIndex((p) => p.temp === temps[k]);
        return <text key={`v${k}`} x={Math.min(W - 18, Math.max(2, x(idx) - 6))} y={y(temps[k]) - 3} fontSize="9" fill="var(--ink)">{Math.round(temps[k])}°</text>;
      })}
    </svg>
  );
}
