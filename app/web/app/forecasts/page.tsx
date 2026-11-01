"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Fragment, Suspense, useCallback, useEffect, useMemo, useState } from "react";
import ChartCard from "@/components/ChartCard";
import EChart from "@/components/EChart";
import { api, type Entity, type Forecast, type ForecastErrors, type Forecaster, type Indicator, type TrackRecord, type WhatIf,
  type WhatIfLevers } from "@/lib/api";
import { inputOption, pyramidCompareOption, trackOption, whatifOption } from "@/lib/charts";
import { formatValue } from "@/lib/format";
import { logHistory } from "@/lib/history";
import { useSettings } from "@/lib/settings";

// Forecasts: the population what-if (move fertility, life expectancy and
// migration away from the UN projection and see the population and its age
// shape change), a statistical forecast of any indicator, and forecasters' track
// records (how far the IMF's, OECD's and World Bank's past forecasts were from
// what happened, and who forecasts best).
const DEFAULTS: WhatIfLevers = { tfr: 0, e0: 0, mig: 1, extra: 0, phase: 10, hold: 0 };
// Ready-made scenarios, after the UN's own variants where there is one.
const PRESETS: { label: string; title: string; levers: WhatIfLevers }[] = [
  { label: "Low fertility", title: "The UN's low variant: half a child fewer per woman, reached within 5 years",
    levers: { ...DEFAULTS, tfr: -0.5, phase: 5 } },
  { label: "High fertility", title: "The UN's high variant: half a child more per woman, reached within 5 years",
    levers: { ...DEFAULTS, tfr: 0.5, phase: 5 } },
  { label: "Fertility stays as today", title: "The UN's constant-fertility idea: births per woman stay at this year's level",
    levers: { ...DEFAULTS, hold: 1 } },
  { label: "No migration", title: "The UN's zero-migration variant: no one moves in or out",
    levers: { ...DEFAULTS, mig: 0 } },
  { label: "Double migration", title: "Twice the UN's migration, in or out", levers: { ...DEFAULTS, mig: 2 } },
  { label: "Longer lives", title: "Five more years of life expectancy, built up over 25 years",
    levers: { ...DEFAULTS, e0: 5, phase: 25 } },
];
const FORECASTERS = [["imf_weo", "IMF"], ["oecd_eo", "OECD"], ["wb_gep", "World Bank"]] as const;
type Tab = "whatif" | "stat" | "track";
const HELD_LABEL: Record<string, string> = {
  tfr: "fertility", e0_male: "men's life expectancy", e0_female: "women's life expectancy", net_migration: "migration",
};

export default function ForecastsPage() {
  return (
    <Suspense fallback={<p className="muted">Loading…</p>}>
      <Forecasts />
    </Suspense>
  );
}

function num(v: string | null, d: number): number {
  const n = v === null ? NaN : Number(v);
  return Number.isFinite(n) ? n : d;
}

function Forecasts() {
  const params = useSearchParams();
  const [tab, setTab] = useState<Tab>(params.get("tab") === "track" ? "track" : params.get("tab") === "stat" ? "stat" : "whatif");
  const [entity, setEntity] = useState(params.get("e") ?? "NZL");
  const [levers, setLevers] = useState<WhatIfLevers>({
    tfr: num(params.get("tfr"), 0), e0: num(params.get("e0"), 0), mig: num(params.get("mig"), 1),
    extra: num(params.get("extra"), 0), phase: num(params.get("phase"), 10), hold: num(params.get("hold"), 0) ? 1 : 0,
  });
  const [indicator, setIndicator] = useState(params.get("ind") ?? "gdp_growth");
  const [forecaster, setForecaster] = useState(params.get("src") ?? "imf_weo");
  const [countries, setCountries] = useState<Entity[]>([]);

  useEffect(() => {
    Promise.all([api.entities("country"), api.entities()]).then(([c, all]) => {
      const groups = all.filter((e) => ["world", "continent"].includes(e.type));
      setCountries([...groups, ...c.sort((a, b) => a.short_name.localeCompare(b.short_name))]);
    }).catch(() => {});
  }, []);

  // The page's state lives in its address, so a what-if can be bookmarked or found in History.
  const query = useMemo(() => {
    const q = new URLSearchParams({ e: entity });
    if (tab === "track") {
      q.set("tab", "track");
      q.set("ind", indicator);
      if (forecaster !== "imf_weo") q.set("src", forecaster);
    } else if (tab === "stat") {
      q.set("tab", "stat");
      q.set("ind", indicator);
    } else {
      for (const [k, v] of Object.entries(levers)) if (v !== DEFAULTS[k as keyof WhatIfLevers]) q.set(k, String(v));
    }
    return q.toString();
  }, [entity, levers, tab, indicator, forecaster]);
  useEffect(() => {
    if (query !== window.location.search.slice(1)) window.history.replaceState(null, "", `?${query}`);
  }, [query]);

  const name = countries.find((c) => c.entity_id === entity)?.short_name ?? entity;
  useEffect(() => {
    const what = tab === "track" ? "Forecast track record" : tab === "stat" ? "Statistical forecast" : "Population what-if";
    const t = setTimeout(() => logHistory({ kind: "page", title: `${what}: ${name}`,
      url: `/forecasts?${query}`, entity, detail: "forecasts" }), 3000);
    return () => clearTimeout(t);
  }, [query, name, entity, tab]);

  return (
    <div className="grid forecasts">
      <div>
        <h1>Forecasts</h1>
        <p className="ink-2" style={{ marginTop: 0 }}>
          {tab === "whatif"
            ? "Change fertility, life expectancy or migration and see how the population and its ages would differ from the UN projection."
            : tab === "stat" ? "A statistical forecast of any indicator: simple models tried against the past, the best one used, with the ranges it fell inside."
            : "How far forecasters' past forecasts of growth and inflation were from what happened, and who forecasts best."}
        </p>
      </div>
      <div className="controls">
        <div className="seg" role="tablist">
          <button role="tab" aria-selected={tab === "whatif"} className={tab === "whatif" ? "on" : ""} onClick={() => setTab("whatif")}>Population what-if</button>
          <button role="tab" aria-selected={tab === "stat"} className={tab === "stat" ? "on" : ""}
            onClick={() => setTab("stat")}>Statistical forecast</button>
          <button role="tab" aria-selected={tab === "track"} className={tab === "track" ? "on" : ""}
            onClick={() => { setTab("track"); if (!["gdp_growth", "inflation"].includes(indicator)) setIndicator("gdp_growth"); }}>Track record</button>
        </div>
        <select value={entity} onChange={(e) => setEntity(e.target.value)} aria-label="Country">
          {!countries.some((c) => c.entity_id === entity) && <option value={entity}>{entity}</option>}
          {countries.map((c) => <option key={c.entity_id} value={c.entity_id}>{c.short_name}</option>)}
        </select>
        <Link className="small" href={`/entity/${entity}`}>Profile</Link>
      </div>
      {tab === "whatif" ? <WhatIfView entity={entity} levers={levers} setLevers={setLevers} />
        : tab === "stat" ? <StatView entity={entity} name={name} indicator={indicator} setIndicator={setIndicator} />
        : <TrackView entity={entity} indicator={indicator} setIndicator={setIndicator} source={forecaster} setSource={setForecaster} />}
    </div>
  );
}

// ----------------------------------------------------------------------------- what-if
function WhatIfView({ entity, levers, setLevers }: { entity: string; levers: WhatIfLevers; setLevers: (l: WhatIfLevers) => void }) {
  const [data, setData] = useState<WhatIf | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [year, setYear] = useState<number | null>(2050);

  useEffect(() => {
    let live = true;
    const t = setTimeout(() => {
      api.whatif(entity, levers).then((d) => { if (live) { setData(d); setError(null); } })
        .catch((e) => { if (live) { setError(String(e.message || e)); setData(null); } });
    }, 150);
    return () => { live = false; clearTimeout(t); };
  }, [entity, levers]);

  const set = (patch: Partial<WhatIfLevers>) => setLevers({ ...levers, ...patch });
  const changed = Object.entries(levers).some(([k, v]) => k !== "phase" && v !== DEFAULTS[k as keyof WhatIfLevers]);
  const preset = PRESETS.find((p) => Object.entries(p.levers).every(([k, v]) => levers[k as keyof WhatIfLevers] === v));
  const shownYear = data ? Math.min(data.years[data.years.length - 1], Math.max(data.base_year, year ?? 2050)) : null;
  const total = useCallback(() => whatifOption(data?.years ?? [], data?.baseline ?? [], data?.scenario ?? [], data?.ranges ?? {}, changed),
    [data, changed]);
  const pyr = data && shownYear !== null ? data.pyramids[String(shownYear)] : null;
  const pyramid = useCallback(() => {
    const side = (s: { male: number[]; female: number[] }) => data!.groups.map((age, i) => ({ age, male: s.male[i], female: s.female[i] }));
    return pyramidCompareOption({ label: changed ? `Your scenario, ${shownYear}` : `UN projection, ${shownYear}`, groups: side(changed ? pyr!.scenario : pyr!.baseline) },
      changed ? { label: "UN projection", groups: side(pyr!.baseline) } : null, true);
  }, [data, pyr, changed, shownYear]);

  const last = data ? data.years.length - 1 : 0;
  const heldFrom = (keys: string[]) => {
    const ys = keys.map((k) => data?.held[k]).filter((y): y is number => y !== undefined);
    return ys.length ? Math.min(...ys) : null;
  };
  const held = Object.entries(data?.held ?? {}).filter(([k]) => HELD_LABEL[k]);

  return (
    <>
      <div className="chips-row small" role="group" aria-label="Ready-made scenarios">
        <span className="muted">Scenarios:</span>
        {PRESETS.map((p) => (
          <button key={p.label} className={`chip${preset === p ? " on" : ""}`} aria-pressed={preset === p} title={p.title}
            onClick={() => setLevers(p.levers)}>{p.label}</button>
        ))}
      </div>
      <section className="card levers">
        <div className="lever">
          <label htmlFor="l-tfr">Fertility <b>{levers.tfr > 0 ? "+" : ""}{levers.tfr.toFixed(1)}</b> children per woman</label>
          <input id="l-tfr" type="range" min={-2} max={2} step={0.1} value={levers.tfr} onChange={(e) => set({ tfr: +e.target.value })} />
        </div>
        <div className="lever">
          <label htmlFor="l-e0">Life expectancy <b>{levers.e0 > 0 ? "+" : ""}{levers.e0.toFixed(1)}</b> years</label>
          <input id="l-e0" type="range" min={-10} max={10} step={0.5} value={levers.e0} onChange={(e) => set({ e0: +e.target.value })} />
        </div>
        <div className="lever">
          <label htmlFor="l-mig">Migration <b>{Math.round(levers.mig * 100)}%</b> of the UN&apos;s</label>
          <input id="l-mig" type="range" min={0} max={3} step={0.1} value={levers.mig} onChange={(e) => set({ mig: +e.target.value })} />
        </div>
        <div className="lever">
          <label htmlFor="l-extra">Extra migrants a year</label>
          <input id="l-extra" type="number" step={1000} value={levers.extra} onChange={(e) => set({ extra: Math.max(-5e6, Math.min(5e6, +e.target.value || 0)) })} />
        </div>
        <div className="lever">
          <label htmlFor="l-phase">Phased in over <b>{levers.phase}</b> {levers.phase === 1 ? "year" : "years"}</label>
          <input id="l-phase" type="range" min={0} max={30} step={1} value={levers.phase} onChange={(e) => set({ phase: +e.target.value })} />
        </div>
        <div className="lever">
          <label><input type="checkbox" checked={!!levers.hold} onChange={(e) => set({ hold: e.target.checked ? 1 : 0 })} /> Fertility stays at {"today's"} level</label>
          <span className="small muted">Instead of following the UN path; the fertility slider then moves it from there.</span>
        </div>
        <div className="lever-actions">
          <button onClick={() => setLevers(DEFAULTS)} disabled={!changed && levers.phase === DEFAULTS.phase}>Back to the UN projection</button>
          <span className="small muted">Fertility and life expectancy changes build up evenly over the phase-in; migration changes apply at once.</span>
        </div>
      </section>
      {error && <p className="error">{error}</p>}
      {data && (
        <>
          {held.length > 0 && (
            <p className="small warn-note">
              The UN&apos;s projected {held.map(([k]) => HELD_LABEL[k]).join(", ")} {held.length === 1 ? "is" : "are"} not loaded past {Math.min(...held.map(([, y]) => y))},
              so {held.length === 1 ? "it is" : "they are"} held at that level (shaded on the small charts). Run <code>.\refresh.bat</code> to load the full UN projection.
            </p>
          )}
          <div className="grid two">
            <section className="card">
              <h3>Population of {data.name}</h3>
              <div style={{ height: 300 }}><EChart option={total} height={300} label={`Population of ${data.name}, UN projection${changed ? " and your scenario" : ""}`} /></div>
              <p className="small muted" style={{ marginBottom: 0 }}>
                {changed
                  ? <>In {data.years[last]}: <b>{formatValue(data.scenario[last], "persons")}</b> against the UN&apos;s {formatValue(data.baseline[last], "persons")} ({pct(data.scenario[last], data.baseline[last])}).</>
                  : <>The UN projection from {data.base_year}. Move a slider to compare.</>}
                {Object.keys(data.ranges).length === 0 && " The UN's ranges show here once a refresh has loaded them."}
              </p>
            </section>
            <section className="card">
              <div className="pyr-head">
                <h3>Ages in {shownYear}</h3>
                <input type="range" min={data.base_year} max={data.years[last]} value={shownYear ?? data.base_year}
                  onChange={(e) => setYear(+e.target.value)} aria-label="Year for the age pyramid" />
              </div>
              {pyr && <div style={{ height: 300 }}><EChart option={pyramid} height={300} update="merge" label={`Population by age and sex in ${shownYear}`} /></div>}
            </section>
          </div>
          <div className="grid three">
            <InputChart title="Fertility (children per woman)" years={data.years} s={data.inputs.tfr} unit="" decimals={2} held={heldFrom(["tfr"])} />
            <InputChart title="Life expectancy at birth (years)" years={data.years} s={data.inputs.e0} unit="" decimals={1} held={heldFrom(["e0_male", "e0_female"])} />
            <InputChart title="Net migration (people a year)" years={data.years} s={data.inputs.net_migration} unit="persons" decimals={0} held={heldFrom(["net_migration"])} />
          </div>
          <section className="card">
            <h3>Key numbers</h3>
            <SummaryTable data={data} changed={changed} />
            <p className="small muted" style={{ marginBottom: 0 }}>
              How this works: the model ages the {data.base_year} population a year at a time by single year of age and sex, with
              births from the fertility path, deaths from life tables matching the life expectancy path, and net migrants
              spread over ages, mostly young adults. What you see is the UN projection plus the difference your changes make in
              the model, so at the default settings it is exactly the UN&apos;s.
              {data.raw_error.worst_total_pct !== null && <> On its own the model lands within {data.raw_error.worst_total_pct.toFixed(1)}% of the UN total for {data.name} in every year.</>}
            </p>
          </section>
        </>
      )}
    </>
  );
}

function pct(a: number, b: number): string {
  const d = (100 * (a - b)) / b;
  return `${d > 0 ? "+" : ""}${d.toFixed(1)}%`;
}

function InputChart({ title, years, s, unit, decimals, held }: {
  title: string; years: number[]; s: { baseline: number[]; scenario: number[] }; unit: string; decimals: number; held: number | null;
}) {
  const option = useCallback(() => inputOption(years, s.baseline, s.scenario, unit, decimals, held), [years, s, unit, decimals, held]);
  return (
    <section className="card">
      <h3>{title}</h3>
      <EChart option={option} height={130} label={title} />
    </section>
  );
}

const ROWS: { key: keyof WhatIf["summary"][number]["baseline"]; label: string; fmt: (v: number | null) => string }[] = [
  { key: "total", label: "Population", fmt: (v) => formatValue(v, "persons") },
  { key: "share_0_14", label: "Under 15", fmt: (v) => formatValue(v, "percent", 1) },
  { key: "share_65_plus", label: "65 and over", fmt: (v) => formatValue(v, "percent", 1) },
  { key: "old_age_dependency", label: "65+ per 100 aged 15-64", fmt: (v) => formatValue(v, "", 1) },
  { key: "median_age", label: "Median age", fmt: (v) => formatValue(v, "", 1) },
];

function SummaryTable({ data, changed }: { data: WhatIf; changed: boolean }) {
  return (
    <div style={{ overflowX: "auto" }}>
      <table className="summary-table">
        <thead>
          <tr><th />{data.summary.map((s) => <th key={s.year} className="num">{s.year}</th>)}</tr>
        </thead>
        <tbody>
          {ROWS.map((r) => (
            <tr key={r.key}>
              <th scope="row">{r.label}</th>
              {data.summary.map((s) => (
                <td key={s.year} className="num">
                  {r.fmt(changed ? s.scenario[r.key] : s.baseline[r.key])}
                  {changed && s.year !== data.base_year && <div className="small muted">UN {r.fmt(s.baseline[r.key])}</div>}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ----------------------------------------------------------------------------- statistical forecast
const STAT_CHOICES = ["gdp_growth", "inflation", "pop_total", "gdp_per_capita_usd", "life_expectancy", "tfr", "unemployment",
  "co2_per_capita", "govt_debt_gdp", "median_age"];

function StatView({ entity, name, indicator, setIndicator }: { entity: string; name: string; indicator: string; setIndicator: (i: string) => void }) {
  const [inds, setInds] = useState<Indicator[]>([]);
  const [fc, setFc] = useState<Forecast | null>(null);
  const [error, setError] = useState<string | null>(null);
  const s = useSettings();
  useEffect(() => { api.indicators().then(setInds).catch(() => {}); }, []);
  useEffect(() => {
    let live = true;
    setFc(null);
    api.forecast(indicator, entity, s.forecast_horizon, false).then((f) => { if (live) { setFc(f); setError(null); } })
      .catch((e) => live && setError(String(e.message || e)));
    return () => { live = false; };
  }, [indicator, entity, s.forecast_horizon]);
  const ind = inds.find((i) => i.indicator_id === indicator);
  const picks = useMemo(() => {
    const top = STAT_CHOICES.map((id) => inds.find((i) => i.indicator_id === id)).filter((i): i is Indicator => !!i);
    const rest = inds.filter((i) => i.enabled && !STAT_CHOICES.includes(i.indicator_id))
      .sort((a, b) => a.name.localeCompare(b.name));
    return { top, rest };
  }, [inds]);
  return (
    <>
      <div className="controls">
        <select value={indicator} onChange={(e) => setIndicator(e.target.value)} aria-label="Indicator">
          {!ind && <option value={indicator}>{indicator}</option>}
          <optgroup label="Often forecast">{picks.top.map((i) => <option key={i.indicator_id} value={i.indicator_id}>{i.name}</option>)}</optgroup>
          <optgroup label="All switched-on indicators">{picks.rest.map((i) => <option key={i.indicator_id} value={i.indicator_id}>{i.name}</option>)}</optgroup>
        </select>
        <Link className="small" href="/settings">Forecast settings</Link>
      </div>
      {ind && <ChartCard indicator={ind} entities={[{ id: entity, name }]} height={320} forecast />}
      {error && <p className="error">{error}</p>}
      {fc && (
        <section className="card">
          <h3>Models tried for {name}</h3>
          <table className="summary-table">
            <thead><tr><th>Model</th><th className="num">Typical miss</th><th className="num">Forecasts scored</th></tr></thead>
            <tbody>
              {fc.models.map((m) => (
                <tr key={m.id} className={m.id === fc.model ? "selected" : ""}>
                  <td>{m.name}{m.id === fc.model ? " (used)" : ""}</td>
                  <td className="num">{m.mae === null ? "–" : formatValue(m.mae, fc.unit, fc.decimals)}</td>
                  <td className="num">{m.n}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="small muted" style={{ marginBottom: 0 }}>
            Each model was refitted on the figures up to each of the last {fc.backtest_origins} years and asked to forecast
            up to {fc.backtest_depth} {fc.backtest_depth === 1 ? "year" : "years"} on; typical miss is the average distance from
            what happened. The simplest model within 5% of the best is used, as a small edge over a few years is more often
            luck than skill.{fc.transform === "log" ? " This series is modelled in percentage changes, so it cannot fall below zero." : ""}
            {" "}The UN, IMF and other sources&apos; own projections, where they exist, are the dashed lines.
          </p>
        </section>
      )}
    </>
  );
}

// ----------------------------------------------------------------------------- track record
const HORIZON = ["the year before", "the same year", "the next year", "2 years ahead", "3 years ahead", "4 years ahead", "5 years ahead"];

function TrackView({ entity, indicator, setIndicator, source, setSource }: {
  entity: string; indicator: string; setIndicator: (i: string) => void; source: string; setSource: (s: string) => void;
}) {
  const [one, setOne] = useState<TrackRecord | null>(null);
  const [all, setAll] = useState<TrackRecord | null>(null);
  const [best, setBest] = useState<Forecaster[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [from, setFrom] = useState(2005);
  const src = indicator === "inflation" && source === "wb_gep" ? "imf_weo" : source;
  useEffect(() => {
    let live = true;
    setOne(null); setAll(null);
    Promise.all([api.trackRecord(indicator, entity, src), api.trackRecord(indicator, undefined, src)])
      .then(([a, b]) => { if (live) { setOne(a); setAll(b); setError(null); } })
      .catch((e) => live && setError(String(e.message || e)));
    api.compareForecasters(indicator, entity).then((r) => live && setBest(r.forecasters)).catch(() => live && setBest(null));
    return () => { live = false; };
  }, [entity, indicator, src]);
  const unit = "percent";
  const option = useCallback(() => trackOption(one?.actual ?? [], one?.paths ?? [], unit, 1, from), [one, from]);
  const label = indicator === "inflation" ? "inflation" : "GDP growth";
  const who = one?.source_name ?? "IMF";
  const fewReleases = (one?.releases.length ?? 0) < 3;

  return (
    <>
      <div className="controls">
        <div className="seg" role="group" aria-label="What was forecast">
          <button className={indicator === "gdp_growth" ? "on" : ""} onClick={() => setIndicator("gdp_growth")}>GDP growth</button>
          <button className={indicator === "inflation" ? "on" : ""} onClick={() => setIndicator("inflation")}>Inflation</button>
        </div>
        <div className="seg" role="group" aria-label="Forecaster">
          {FORECASTERS.map(([id, name]) => (
            <button key={id} className={src === id ? "on" : ""} aria-pressed={src === id}
              disabled={indicator === "inflation" && id === "wb_gep"} title={indicator === "inflation" && id === "wb_gep" ? "The World Bank's outlook forecasts growth only" : ""}
              onClick={() => setSource(id)}>{name}</button>
          ))}
        </div>
        <label className="small">From <select value={from} onChange={(e) => setFrom(+e.target.value)}>
          {[1990, 2000, 2005, 2010, 2015, 2020].map((y) => <option key={y} value={y}>{y}</option>)}
        </select></label>
      </div>
      {error && <p className="error">{error}</p>}
      {one && fewReleases && (
        <p className="small warn-note">
          Only {one.releases.length === 1 ? `one ${who} release is` : `${one.releases.length} ${who} releases are`} stored so far ({one.releases.join(", ") || "none"}).
          {src === "imf_weo"
            ? <> Run <code>.\refresh.bat</code> to load the IMF&apos;s file of every forecast since 1990; each refresh after a new WEO (April and October) adds that release too.</>
            : <> The record builds up as <code>.\refresh.bat</code> stores each new edition ({src === "oecd_eo" ? "June and December" : "January and June"}); the first can be scored once the next year&apos;s figures are in.</>}
        </p>
      )}
      {best && best.length > 0 && <BestTable rows={best} label={label} />}
      {one && (
        <div className="grid two">
          <section className="card">
            <h3>{one.name}: {label}, {who} forecasts and what happened</h3>
            <EChart option={option} height={300} label={`${label} in ${one.name}: past ${who} forecasts and outcomes`} />
            <p className="small muted" style={{ marginBottom: 0 }}>
              Thin lines are what each release forecast (darker is newer); the thick line is what happened, from the
              {one.outcomes_from ? ` ${one.outcomes_from}` : " latest"} release.
            </p>
          </section>
          <section className="card">
            <h3>How far off, on average</h3>
            <ErrorTable stats={one.stats} seasons={one.seasons} />
            {all && all.stats.length > 0 && (
              <>
                <h3 style={{ marginTop: 14 }}>All countries together</h3>
                <ErrorTable stats={all.stats} seasons={all.seasons} />
              </>
            )}
            <p className="small muted" style={{ marginBottom: 0 }}>
              Error is forecast minus outcome, in percentage points. Bias above zero means {who} forecast too high on
              average; typical miss is the mean absolute error.
            </p>
          </section>
        </div>
      )}
      {all?.countries && all.countries.length > 0 && (
        <section className="card">
          <h3>Next-year {label} forecasts by country ({who})</h3>
          <div style={{ maxHeight: 360, overflow: "auto" }}>
            <table className="summary-table">
              <thead><tr><th>Country</th><th className="num">Forecasts</th><th className="num">Typical miss</th><th className="num">Bias</th></tr></thead>
              <tbody>
                {all.countries.map((c) => (
                  <tr key={c.entity_id} className={c.entity_id === entity ? "selected" : ""}>
                    <td>{c.name}</td><td className="num">{c.n}</td><td className="num">{pts(c.mae)}</td><td className="num">{pts(c.bias, true)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </>
  );
}

// Who forecasts best: each forecaster's typical miss over the years all of them were scored.
function BestTable({ rows, label }: { rows: Forecaster[]; label: string }) {
  const scored = rows.filter((r) => r.this_year.n || r.next_year.n);
  const fair = (r: Forecaster, k: "this_year" | "next_year") => r[`${k}_common`].mae;
  const winner = (k: "this_year" | "next_year") => {
    const c = scored.filter((r) => fair(r, k) !== null);
    return c.length > 1 ? c.reduce((a, b) => (fair(a, k)! <= fair(b, k)! ? a : b)).source_id : null;
  };
  const w0 = winner("this_year"), w1 = winner("next_year");
  return (
    <section className="card">
      <h3>Who forecasts {label} best here</h3>
      <table className="summary-table">
        <thead>
          <tr><th>Forecaster</th><th className="num">This year: typical miss</th><th className="num">over shared years</th>
            <th className="num">Next year: typical miss</th><th className="num">over shared years</th></tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.source_id}>
              <td>{r.name}{r.releases !== null ? <span className="small muted"> ({r.releases} {r.releases === 1 ? "release" : "releases"} scored)</span> : null}</td>
              <td className="num" title={`${r.this_year.n} forecasts`}>{pts(r.this_year.mae)}</td>
              <td className="num" title={`${r.this_year_common.n} forecasts over ${r.this_year_common_years} shared years`}>
                {w0 === r.source_id ? <b>{pts(fair(r, "this_year"))}</b> : pts(fair(r, "this_year"))}</td>
              <td className="num" title={`${r.next_year.n} forecasts`}>{pts(r.next_year.mae)}</td>
              <td className="num" title={`${r.next_year_common.n} forecasts over ${r.next_year_common_years} shared years`}>
                {w1 === r.source_id ? <b>{pts(fair(r, "next_year"))}</b> : pts(fair(r, "next_year"))}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="small muted" style={{ marginBottom: 0 }}>
        Typical miss is the average distance between forecast and outcome, in percentage points. The fair comparison is
        over shared years, the years every forecaster with a record forecast; bold is the closest. Worldmodel is the
        statistical forecast on this page, tried on the past with only the figures known before each year. Forecasters
        with no scored releases yet build a record as each edition is stored.
      </p>
    </section>
  );
}

function pts(v: number | null, signed = false): string {
  if (v === null) return "–";
  return `${signed && v > 0 ? "+" : ""}${v.toFixed(2)} pts`;
}

function ErrorTable({ stats, seasons }: { stats: ({ season: string; horizon: number } & ForecastErrors)[]; seasons: string[] }) {
  if (!stats.length) return <p className="small muted">No forecasts to score yet.</p>;
  const horizons = [...new Set(stats.map((s) => s.horizon))].sort((a, b) => a - b);
  const cols = seasons.filter((x) => stats.some((s) => s.season === x));
  const get = (season: string, h: number) => stats.find((s) => s.season === season && s.horizon === h);
  return (
    <table className="summary-table">
      <thead>
        <tr><th>Forecast for</th>{cols.map((c) => <Fragment key={c}><th className="num">{c}: typical miss</th><th className="num">bias</th></Fragment>)}</tr>
      </thead>
      <tbody>
        {horizons.map((h) => (
          <tr key={h}>
            <th scope="row">{HORIZON[h + 1] ?? `${h} years ahead`}</th>
            {cols.map((c) => {
              const x = get(c, h);
              return <Fragment key={c}><td className="num" title={x ? `${x.n} forecasts` : ""}>{pts(x?.mae ?? null)}</td><td className="num">{pts(x?.bias ?? null, true)}</td></Fragment>;
            })}
          </tr>
        ))}
      </tbody>
    </table>
  );
}
