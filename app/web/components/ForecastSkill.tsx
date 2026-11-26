"use client";

import Link from "next/link";
import { Fragment, useEffect, useMemo, useState } from "react";
import { get } from "@/lib/api";
import { useSettings } from "@/lib/settings";
import { MODEL_COLOURS, SKILL_ENOUGH_DAYS, type SkillModel, type SkillTable } from "@/lib/weather";

// Forecast accuracy: which weather model has been most right, region by region and city by city.
// The scores are built up on this PC every 6 hours (api forecast_skill.py), so the page starts empty.

const r1 = (v: number | null | undefined) => (v === null || v === undefined ? "–" : v.toFixed(1));
const r2 = (v: number | null | undefined) => (v === null || v === undefined ? "–" : v.toFixed(2));
const mean = (xs: (number | null)[]) => { const ok = xs.filter((x): x is number => x !== null); return ok.length ? ok.reduce((a, b) => a + b, 0) / ok.length : null; };

function Swatch({ model }: { model: string }) {
  return <span className="skill-swatch" style={{ background: MODEL_COLOURS[model] ?? "#ced4da" }} aria-hidden="true" />;
}

function ModelsTable({ models }: { models: SkillModel[] }) {
  return (
    <table className="indicators skill-models">
      <thead><tr><th>Model</th><th title="Mean rank over temperature, wind and rain (1 = best)">Rank</th><th>Temperature off by</th><th>Wind off by</th>
        <th title="Balanced Brier score of the rain chance: 0 perfect, 0.25 no better than a coin">Rain score</th><th>Checks</th></tr></thead>
      <tbody>{models.map((m) => (
        <tr key={m.model} className={m.mean_rank === null ? "muted" : ""}>
          <td><Swatch model={m.model} /> {m.name}</td><td>{m.mean_rank === null ? "too few" : r1(m.mean_rank)}</td>
          <td>{r1(m.temp)} °C</td><td>{r1(m.wind)} km/h</td><td>{r2(m.rain)}{m.wet_hours ? <span className="muted"> ({m.wet_hours} wet)</span> : null}</td><td>{m.n}</td>
        </tr>
      ))}</tbody>
    </table>
  );
}

export default function ForecastSkill() {
  const s = useSettings();
  const [lead, setLead] = useState<"day1" | "day2">("day1");
  const [t, setT] = useState<SkillTable | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [region, setRegion] = useState("");
  const [q, setQ] = useState("");
  const [open, setOpen] = useState<string | null>(null);
  useEffect(() => {
    let live = true;
    get<SkillTable>(`/weather/skill?lead=${lead}`).then((d) => { if (live) { setT(d); setError(null); } })
      .catch((e) => live && setError(String(e.message || e)));
    return () => { live = false; };
  }, [lead]);

  // Each model over all scored cities: how often it is best, and its average errors.
  const overall = useMemo(() => {
    if (!t) return [];
    const ids = Object.keys(t.models ?? MODEL_COLOURS);
    return ids.map((id) => {
      const rows = t.cities.flatMap((c) => c.models.filter((m) => m.model === id && m.mean_rank !== null));
      return { model: id, name: t.models?.[id] ?? id, wins: t.cities.filter((c) => c.best === id).length, cities: rows.length,
        temp: mean(rows.map((m) => m.temp)), wind: mean(rows.map((m) => m.wind)), rain: mean(rows.map((m) => m.rain)) };
    }).filter((m) => m.cities > 0).sort((a, b) => b.wins - a.wins || (a.temp ?? 99) - (b.temp ?? 99));
  }, [t]);

  if (error) return <div className="card"><p className="error">Forecast accuracy did not load: {error}</p></div>;
  if (!t) return <p className="muted">Loading…</p>;
  const off = !s.weather_maps || !s.weather_skill;
  const scored = t.cities.filter((c) => c.best).length;
  const early = t.days < SKILL_ENOUGH_DAYS;
  const shown = t.cities.filter((c) => (!region || c.region === region) && (!q || `${c.name} ${c.country} ${c.icao ?? ""}`.toLowerCase().includes(q.toLowerCase())));
  return (
    <>
      <div className="card">
        <h3>Which forecast has been most right</h3>
        <p className="small">Every 6 hours this PC stores what eight weather models say for the next two days in {t.cities.length} key cities, then checks
          each forecast against what happened: the city airport&apos;s own weather reports, or Open-Meteo&apos;s analysis where there are none.
          A model&apos;s rank in a city is the average of its ranks on temperature, wind and rain over the last 60 days.</p>
        <p className="small">
          {t.rounds ? <><b>{t.days} days in</b> ({t.rounds} rounds, last {t.last_round ? new Date(t.last_round).toLocaleString() : "–"}); {scored} of {t.cities.length} cities ranked.</>
            : <b>Nothing recorded yet.</b>}{" "}
          {t.running ? "Recording now… " : ""}
          {early && <span className="muted">Rankings settle after about three weeks; until then a model can lead by luck.</span>}
        </p>
        {off && <p className="small error">Scoring is switched off in <Link href="/settings#climate">Settings &gt; Climate &gt; Weather</Link>, so nothing new is recorded.</p>}
        {t.error && <p className="small error">Last round: {t.error}</p>}
        {!t.error && t.note && <p className="small muted">Last round: {t.note}</p>}
        <div className="seg" role="tablist" aria-label="How far ahead">
          {([["day1", "Next 24 hours"], ["day2", "24 to 48 hours ahead"]] as const).map(([k, label]) => (
            <button key={k} role="tab" aria-selected={lead === k} className={lead === k ? "on" : ""} onClick={() => setLead(k)}>{label}</button>
          ))}
        </div>
      </div>

      {overall.length > 0 && (
        <div className="card">
          <h3>Best model by region</h3>
          <div className="skill-regions">
            {t.regions.map((r) => {
              const won = r.wins.reduce((a, w) => a + w.cities, 0);
              return (
                <div key={r.region} className="skill-region">
                  <b>{r.region}</b> <span className="muted small">{won} of {r.cities} cities ranked</span>
                  <div className="skill-bar" aria-hidden="true">
                    {r.wins.map((w) => <span key={w.model} style={{ flex: w.cities, background: MODEL_COLOURS[w.model] ?? "#ced4da" }} title={`${w.name}: ${w.cities}`} />)}
                    {r.cities - won > 0 && <span style={{ flex: r.cities - won }} className="skill-bar-empty" />}
                  </div>
                  <span className="small">{r.wins.length ? r.wins.map((w) => `${w.name} ${w.cities}`).join(" · ") : <span className="muted">not enough checks yet</span>}</span>
                </div>
              );
            })}
          </div>
          <h3>All {scored} ranked cities together</h3>
          <table className="indicators">
            <thead><tr><th>Model</th><th>Best in</th><th>Temperature off by (average)</th><th>Wind off by</th><th>Rain score</th></tr></thead>
            <tbody>{overall.map((m) => (
              <tr key={m.model}><td><Swatch model={m.model} /> {m.name}</td><td>{m.wins} {m.wins === 1 ? "city" : "cities"}</td>
                <td>{r1(m.temp)} °C</td><td>{r1(m.wind)} km/h</td><td>{r2(m.rain)}</td></tr>
            ))}</tbody>
          </table>
          <p className="caption">Rain score: balanced Brier score of a rain chance taken from the forecast amount (0 perfect, lower is better), wet and dry hours counted equally.
            Airport temperatures are reported in whole degrees, so no model gets much below 0.4 °C. The map layer &quot;Best forecast model&quot; shows the same cities.</p>
        </div>
      )}

      <div className="card">
        <h3>City by city</h3>
        <div className="chips-row small">
          <select value={region} onChange={(e) => setRegion(e.target.value)} aria-label="Region">
            <option value="">All regions</option>
            {t.regions.map((r) => <option key={r.region} value={r.region}>{r.region}</option>)}
          </select>
          <input type="search" placeholder="Find a city" value={q} onChange={(e) => setQ(e.target.value)} style={{ width: 180 }} />
        </div>
        <table className="indicators click-rows">
          <thead><tr><th>City</th><th>Checked against</th><th>Best lately</th><th>Off by</th><th>Next best</th><th>Checks</th></tr></thead>
          <tbody>{shown.map((c) => {
            const top = c.best ? c.models[0] : null;
            const next = top && c.models[1]?.mean_rank !== null ? c.models[1] : null;
            return (
              <Fragment key={c.id}>
                <tr onClick={() => setOpen(open === c.id ? null : c.id)} aria-expanded={open === c.id}>
                  <td>{c.name} <span className="muted">{c.country}</span></td>
                  <td>{c.icao ? <>{c.icao}{top ? <span className="muted"> ({Math.round(top.airport_share * 100)}% of hours)</span> : null}</> : <span className="muted">analysis only</span>}</td>
                  <td>{top ? <><Swatch model={top.model} /> {top.name}</> : <span className="muted">too few checks</span>}</td>
                  <td>{top ? `${r1(top.temp)} °C · ${r1(top.wind)} km/h` : ""}</td>
                  <td>{next?.name ?? ""}</td>
                  <td>{c.models.reduce((a, m) => Math.max(a, m.n), 0)}</td>
                </tr>
                {open === c.id && <tr className="detail"><td colSpan={6}>{c.models.length ? <ModelsTable models={c.models} /> : <span className="muted">No forecasts checked here yet.</span>}</td></tr>}
              </Fragment>
            );
          })}</tbody>
        </table>
        <p className="caption">Click a city for every model&apos;s scores. Forecasts are for the airport&apos;s own spot once its reports have told us where it is. Kyiv&apos;s airports are closed, so it is checked against the analysis only.</p>
      </div>
    </>
  );
}
