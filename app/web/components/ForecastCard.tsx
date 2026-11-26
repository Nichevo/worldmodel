"use client";

import { useEffect, useMemo, useState } from "react";
import {
  aqiColour, aqiWords, compass, hourDate, MODEL_COLOURS, placeAir, placeForecast, placeModels, placeSkill, r0, r1, SKILL_ENOUGH_DAYS, type SkillNear, windyLink,
  type AirNow, type ModelsAgree, type PlaceForecast, type RainSoon,
} from "@/lib/weather";

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
      {f?.rain_soon && <RainSoonLine r={f.rain_soon} f={f} />}
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
      <ModelsLine lat={lat} lon={lon} />
      <AirLine lat={lat} lon={lon} />
      {f?.source_name && (
        <span className="caption">
          {f.source_name}{f.source === "open_meteo" && f.timezone ? `, times in ${f.timezone}` : ", times in your time zone"}.{" "}
          Rain chance is the day&apos;s highest hourly chance. <a href={f.link} target="_blank" rel="noreferrer">Source</a>
          {" · "}<a href={windyLink(lat, lon, 9)} target="_blank" rel="noreferrer">Open in Windy</a>
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

// "Rain from 2:15 pm" from the next 8 hours in quarter-hours (Open-Meteo).
function RainSoonLine({ r, f }: { r: RainSoon; f: PlaceForecast }) {
  const at = (t: string) => hourDate(f, t).toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit", ...(f.timezone ? { timeZone: f.timezone } : {}) });
  const text = r.now ? (r.ends ? `Raining now, easing about ${at(r.ends)}` : `Raining now, for the next ${r.hours} hours or more`)
    : r.starts ? `Rain from about ${at(r.starts)}${r.ends ? ` to ${at(r.ends)}` : ""}${r.mm ? ` (${r1(r.mm)} mm)` : ""}`
      : `No rain in the next ${r.hours} hours`;
  return <span className="small"><b>{text}</b> <span className="muted">(15-minute forecast)</span></span>;
}

// Today's and tomorrow's high and rain from six models side by side, and whether they agree.
function ModelsLine({ lat, lon }: { lat: number; lon: number }) {
  const [m, setM] = useState<ModelsAgree | null>(null);
  const [best, setBest] = useState<SkillNear | null>(null);
  useEffect(() => {
    let live = true;
    setM(null);
    setBest(null);
    placeModels(lat, lon).then((d) => live && setM(d)).catch(() => live && setM(null));
    placeSkill(lat, lon).then((d) => live && setBest(d)).catch(() => live && setBest(null));
    return () => { live = false; };
  }, [lat, lon]);
  if (!m?.days?.length) return null;
  const label = (i: number) => (i === 0 ? "Today" : "Tomorrow");
  // The model most right lately near here goes first, the rest in its city's order.
  const order = best?.order ?? [];
  const pos = (id: string) => { const i = order.indexOf(id); return i < 0 ? 99 : i; };
  const rows = m.days[0].models.map((x, j) => ({ x, j })).sort((a, b) => pos(a.x.model) - pos(b.x.model));
  return (
    <details className="wx-models small">
      <summary>
        {m.days.map((d, i) => (
          <span key={d.date}>{i > 0 ? " · " : ""}{label(i)}: {d.n} models, high {r0(d.high_lo)} to {r0(d.high_hi)}°
            {d.rain_hi !== null ? `, rain ${r1(d.rain_lo)} to ${r1(d.rain_hi)} mm` : ""}{" "}
            {d.agree ? <span className="muted">(agree)</span> : <b className="wx-disagree">(disagree: {d.why})</b>}</span>
        ))}
        {best?.city && best.best_name && (
          <span className="wx-best">
            <span className="skill-swatch" style={{ background: MODEL_COLOURS[best.best ?? ""] ?? "#ced4da" }} aria-hidden="true" />
            Most right lately{best.km && best.km > 30 ? ` in ${best.city} (${best.km} km away)` : ""}: <b>{best.best_name}</b>
            <span className="muted">{typeof best.temp === "number" ? `, about ${best.temp.toFixed(1)}° off` : ""}, {best.n} checks
              {typeof best.airport_share === "number" && best.airport_share > 0 ? " against airport reports" : ""}
              {best.days < SKILL_ENOUGH_DAYS ? ` (only ${best.days} days in)` : ""}</span>
          </span>
        )}
      </summary>
      <table>
        <thead><tr><th>Model</th>{m.days.map((d, i) => <th key={d.date} colSpan={2}>{label(i)}</th>)}</tr></thead>
        <tbody>
          {rows.map(({ x, j }) => (
            <tr key={x.model}>
              <td>{x.name}{best?.best === x.model ? <b> (most right lately)</b> : ""}</td>
              {m.days!.map((d) => [<td key={`${d.date}h`}>{r1(d.models[j]?.high)}°</td>, <td key={`${d.date}r`}>{r1(d.models[j]?.rain)} mm</td>])}
            </tr>
          ))}
        </tbody>
      </table>
      {best?.city && <p className="caption"><a href="/climate?tab=skill">Forecast accuracy</a> scores the models in {best.city} every 6 hours.</p>}
    </details>
  );
}

// The air now and the worst hour of the next days (Open-Meteo, CAMS).
function AirLine({ lat, lon }: { lat: number; lon: number }) {
  const [a, setA] = useState<AirNow | null>(null);
  useEffect(() => {
    let live = true;
    setA(null);
    placeAir(lat, lon).then((d) => live && setA(d)).catch(() => live && setA(null));
    return () => { live = false; };
  }, [lat, lon]);
  const n = a?.now;
  if (!n || n.us_aqi === null) return null;
  const worst = (a.days ?? []).slice(1).reduce<{ date: string; us_aqi: number } | null>((b, d) => (!b || d.us_aqi > b.us_aqi ? d : b), null);
  return (
    <span className="small wx-air">
      Air now <span className="wx-aqi" style={{ background: aqiColour(n.us_aqi) }} title="US air quality index">{r0(n.us_aqi)}</span> {aqiWords(n.us_aqi)}
      <span className="muted">
        {n.pm2_5 !== null ? ` · PM2.5 ${r1(n.pm2_5)} µg/m³` : ""}{n.dust ? ` · dust ${r0(n.dust)}` : ""}{n.ozone !== null ? ` · ozone ${r0(n.ozone)}` : ""}
        {n.uv_index !== null ? ` · UV ${r1(n.uv_index)}` : ""}
        {worst && worst.us_aqi > 100 ? ` · worst ahead ${r0(worst.us_aqi)} on ${new Date(`${worst.date}T12:00:00Z`).toLocaleDateString(undefined, { weekday: "short", timeZone: "UTC" })}` : ""}
      </span>
    </span>
  );
}
