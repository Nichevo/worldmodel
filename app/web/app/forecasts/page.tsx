"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useMemo, useState } from "react";
import EChart from "@/components/EChart";
import { api, type Entity, type ForecastErrors, type TrackRecord, type WhatIf, type WhatIfLevers } from "@/lib/api";
import { inputOption, pyramidCompareOption, trackOption, whatifOption } from "@/lib/charts";
import { formatValue } from "@/lib/format";
import { logHistory } from "@/lib/history";

// Forecasts: the population what-if (move fertility, life expectancy and
// migration away from the UN projection and see the population and its age
// shape change), and the IMF's track record (how far its past growth and
// inflation forecasts were from what happened).
const DEFAULTS: WhatIfLevers = { tfr: 0, e0: 0, mig: 1, extra: 0, phase: 10 };
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
  const [tab, setTab] = useState<"whatif" | "track">(params.get("tab") === "track" ? "track" : "whatif");
  const [entity, setEntity] = useState(params.get("e") ?? "NZL");
  const [levers, setLevers] = useState<WhatIfLevers>({
    tfr: num(params.get("tfr"), 0), e0: num(params.get("e0"), 0), mig: num(params.get("mig"), 1),
    extra: num(params.get("extra"), 0), phase: num(params.get("phase"), 10),
  });
  const [indicator, setIndicator] = useState(params.get("ind") === "inflation" ? "inflation" : "gdp_growth");
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
    } else {
      for (const [k, v] of Object.entries(levers)) if (v !== DEFAULTS[k as keyof WhatIfLevers]) q.set(k, String(v));
    }
    return q.toString();
  }, [entity, levers, tab, indicator]);
  useEffect(() => {
    if (query !== window.location.search.slice(1)) window.history.replaceState(null, "", `?${query}`);
  }, [query]);

  const name = countries.find((c) => c.entity_id === entity)?.short_name ?? entity;
  useEffect(() => {
    const t = setTimeout(() => logHistory({ kind: "page", title: `${tab === "track" ? "IMF track record" : "Population what-if"}: ${name}`,
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
            : "How far the IMF's past forecasts of growth and inflation were from what happened."}
        </p>
      </div>
      <div className="controls">
        <div className="seg" role="tablist">
          <button role="tab" aria-selected={tab === "whatif"} className={tab === "whatif" ? "on" : ""} onClick={() => setTab("whatif")}>Population what-if</button>
          <button role="tab" aria-selected={tab === "track"} className={tab === "track" ? "on" : ""} onClick={() => setTab("track")}>IMF track record</button>
        </div>
        <select value={entity} onChange={(e) => setEntity(e.target.value)} aria-label="Country">
          {!countries.some((c) => c.entity_id === entity) && <option value={entity}>{entity}</option>}
          {countries.map((c) => <option key={c.entity_id} value={c.entity_id}>{c.short_name}</option>)}
        </select>
        <Link className="small" href={`/entity/${entity}`}>Profile</Link>
      </div>
      {tab === "whatif" ? <WhatIfView entity={entity} levers={levers} setLevers={setLevers} />
        : <TrackView entity={entity} indicator={indicator} setIndicator={setIndicator} />}
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
          <tr><th /> {data.summary.map((s) => <th key={s.year} className="num">{s.year}</th>)}</tr>
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

// ----------------------------------------------------------------------------- track record
const HORIZON = ["the year before", "the same year", "the next year", "2 years ahead", "3 years ahead", "4 years ahead", "5 years ahead"];

function TrackView({ entity, indicator, setIndicator }: { entity: string; indicator: string; setIndicator: (i: string) => void }) {
  const [one, setOne] = useState<TrackRecord | null>(null);
  const [all, setAll] = useState<TrackRecord | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [from, setFrom] = useState(2005);
  useEffect(() => {
    let live = true;
    Promise.all([api.trackRecord(indicator, entity), api.trackRecord(indicator)])
      .then(([a, b]) => { if (live) { setOne(a); setAll(b); setError(null); } })
      .catch((e) => live && setError(String(e.message || e)));
    return () => { live = false; };
  }, [entity, indicator]);
  const unit = "percent";
  const option = useCallback(() => trackOption(one?.actual ?? [], one?.paths ?? [], unit, 1, from), [one, from]);
  const label = indicator === "inflation" ? "inflation" : "GDP growth";
  const fewReleases = (one?.releases.length ?? 0) < 3;

  return (
    <>
      <div className="controls">
        <div className="seg" role="group" aria-label="What was forecast">
          <button className={indicator === "gdp_growth" ? "on" : ""} onClick={() => setIndicator("gdp_growth")}>GDP growth</button>
          <button className={indicator === "inflation" ? "on" : ""} onClick={() => setIndicator("inflation")}>Inflation</button>
        </div>
        <label className="small">From <select value={from} onChange={(e) => setFrom(+e.target.value)}>
          {[1990, 2000, 2005, 2010, 2015, 2020].map((y) => <option key={y} value={y}>{y}</option>)}
        </select></label>
      </div>
      {error && <p className="error">{error}</p>}
      {one && fewReleases && (
        <p className="small warn-note">
          Only {one.releases.length === 1 ? "one IMF release is" : `${one.releases.length} IMF releases are`} stored so far ({one.releases.join(", ") || "none"}).
          Run <code>.\refresh.bat</code> to load the IMF&apos;s file of every forecast since 1990; each refresh after a new
          WEO (April and October) adds that release too.
        </p>
      )}
      {one && (
        <div className="grid two">
          <section className="card">
            <h3>{one.name}: {label}, forecasts and what happened</h3>
            <EChart option={option} height={300} label={`${label} in ${one.name}: past IMF forecasts and outcomes`} />
            <p className="small muted" style={{ marginBottom: 0 }}>
              Thin lines are what each release forecast (darker is newer); the thick line is what happened, from the
              {one.outcomes_from ? ` ${one.outcomes_from}` : " latest"} release.
            </p>
          </section>
          <section className="card">
            <h3>How far off, on average</h3>
            <ErrorTable stats={one.stats} />
            {all && all.stats.length > 0 && (
              <>
                <h3 style={{ marginTop: 14 }}>All countries together</h3>
                <ErrorTable stats={all.stats} />
              </>
            )}
            <p className="small muted" style={{ marginBottom: 0 }}>
              Error is forecast minus outcome, in percentage points. Bias above zero means the IMF forecast too high on
              average; typical miss is the mean absolute error.
            </p>
          </section>
        </div>
      )}
      {all?.countries && all.countries.length > 0 && (
        <section className="card">
          <h3>Next-year {label} forecasts by country</h3>
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

function pts(v: number | null, signed = false): string {
  if (v === null) return "–";
  return `${signed && v > 0 ? "+" : ""}${v.toFixed(2)} pts`;
}

function ErrorTable({ stats }: { stats: ({ season: string; horizon: number } & ForecastErrors)[] }) {
  if (!stats.length) return <p className="small muted">No forecasts to score yet.</p>;
  const horizons = [...new Set(stats.map((s) => s.horizon))].sort((a, b) => a - b);
  const get = (season: string, h: number) => stats.find((s) => s.season === season && s.horizon === h);
  return (
    <table className="summary-table">
      <thead>
        <tr><th>Forecast for</th><th className="num">April: typical miss</th><th className="num">bias</th><th className="num">October: typical miss</th><th className="num">bias</th></tr>
      </thead>
      <tbody>
        {horizons.map((h) => {
          const a = get("April", h), o = get("October", h);
          return (
            <tr key={h}>
              <th scope="row">{HORIZON[h + 1] ?? `${h} years ahead`}</th>
              <td className="num" title={a ? `${a.n} forecasts` : ""}>{pts(a?.mae ?? null)}</td><td className="num">{pts(a?.bias ?? null, true)}</td>
              <td className="num" title={o ? `${o.n} forecasts` : ""}>{pts(o?.mae ?? null)}</td><td className="num">{pts(o?.bias ?? null, true)}</td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}
