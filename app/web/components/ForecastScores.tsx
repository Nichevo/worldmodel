"use client";

// Forecasts > Scores: how good the app's own forecasts have been. Each kind of forecast is
// made again from the past using only the figures there were then (a rolling-origin
// back-test) and scored against what came and against simple baselines; the running record
// scores the forecasts saved after each refresh as their figures come in. The API works it
// all out in the background after each new build, so this view polls until a part is ready.
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import IndicatorSelect from "@/components/IndicatorSelect";
import { api, type Indicator, type LiveScores, type ScoreRow, type ScoresPart, type ScoreTable } from "@/lib/api";
import { formatValue } from "@/lib/format";

type Family = "disease" | "stat" | "nowcast" | "recession" | "live";
const FAMILIES: [Family, string][] = [
  ["disease", "Flu and RSV"], ["stat", "Yearly figures"], ["nowcast", "Nowcasts"], ["recession", "Recession odds"],
  ["live", "Running record"],
];
const STAT_DEFAULT = ["gdp_growth", "inflation", "unemployment", "pop_total", "life_expectancy", "tfr", "govt_debt_gdp", "gdp_per_capita_usd"];
const BASES: Record<string, string> = {
  last: "Same as last week", usual: "Usual for the week", naive: "Last value carries on", prev: "Last quarter's growth again",
};
const UNIT: Record<string, [string, string]> = { disease: ["week", "weeks"], stat: ["year", "years"], nowcast: ["", ""], recession: ["month", "months"] };

const pct = (v: number | null | undefined, d = 0) => (v === null || v === undefined ? "–" : `${(100 * v).toFixed(d)}%`);
const ahead = (fam: string, h: number) => (fam === "nowcast" ? "This quarter" : `${h} ${h === 1 ? UNIT[fam][0] : UNIT[fam][1]} ahead`);

function Skill({ v }: { v: number | null | undefined }) {
  if (v === null || v === undefined) return <>–</>;
  const s = Math.round(100 * v);
  return <span className={`tone ${s > 2 ? "good" : s < -2 ? "bad" : ""}`} title="How much smaller the typical miss is than the better baseline's">
    {s > 0 ? `${s}% better` : s < 0 ? `${-s}% worse` : "same"}</span>;
}

function Cover({ v, aim = 0.8 }: { v: number | null | undefined; aim?: number }) {
  if (v === null || v === undefined) return <>–</>;
  const off = v - aim;
  return <span className={`tone ${Math.abs(off) <= 0.07 ? "good" : off < -0.15 ? "bad" : ""}`}
    title={`Should be about ${Math.round(aim * 100)}%. Less means the ranges were too narrow; more, too wide.`}>{pct(v)}</span>;
}

// Poll one part until the API has worked it out.
function usePart(part: string | null) {
  const [held, setGot] = useState<{ part: string; r: ScoresPart } | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    if (!part) return;
    let live = true, timer: ReturnType<typeof setTimeout> | undefined;
    setGot(null);
    setErr(null);
    const ask = () => api.forecastScores(part).then((r) => {
      if (!live) return;
      setGot({ part, r });
      if (r.status === "working") timer = setTimeout(ask, 4000);
    }).catch((e) => live && setErr(String(e.message || e)));
    ask();
    return () => { live = false; if (timer) clearTimeout(timer); };
  }, [part]);
  // Only this part's answer: a switch shows "Loading" until the new part's arrives.
  return { got: held && held.part === part ? held.r : null, err };
}

function Waiting({ got, err }: { got: ScoresPart | null; err: string | null }) {
  if (err) return <p className="error">{err}</p>;
  if (!got) return <p className="muted">Loading…</p>;
  if (got.status === "failed") return <p className="error">Could not work this out: {got.error}</p>;
  return (
    <p className="muted">
      Working this out in the background: every forecast is made again from the past, which takes a few minutes after each
      refresh{got.working_on ? ` (now: ${got.working_on.replace("stat:", "yearly ")}${got.queued ? `, ${got.queued} more waiting` : ""})` : ""}.
      This page fills in by itself when it is ready.
    </p>
  );
}

export default function ForecastScores({ entity, name }: { entity: string; name: string }) {
  const [fam, setFam] = useState<Family>("disease");
  const [indicator, setIndicator] = useState("gdp_growth");
  const part = fam === "stat" ? `stat:${indicator}` : fam;
  const { got, err } = usePart(part);
  return (
    <>
      <section className="card">
        <p className="small ink-2" style={{ marginTop: 0 }}>
          Each forecast the app makes is made again at points in the past using only the figures there were then, and set
          against what came. <b>Typical miss</b> is the average distance from what came. <b>Skill</b> compares it with the
          better of two or so plain guesses that need no model (a forecast should beat them to be worth anything).
          <b> Inside 80% range</b> should be about 80%: less means the shaded ranges are too narrow. The <b>running record</b>{" "}
          scores the forecasts saved after each refresh, as their figures come in.{" "}
          <Link href="/settings">Settings</Link> can stop the saving or change how many years of flu and RSV are back-tested.
        </p>
        <div className="seg" role="tablist" aria-label="Kind of forecast">
          {FAMILIES.map(([f, label]) => (
            <button key={f} role="tab" aria-selected={fam === f} className={fam === f ? "on" : ""} onClick={() => setFam(f)}>{label}</button>
          ))}
        </div>
      </section>
      {fam === "stat" && <StatPicker value={indicator} onChange={setIndicator} />}
      {got?.status !== "ready" ? <Waiting got={got} err={err} />
        : fam === "disease" ? <DiseaseScores res={got.result as Record<string, ScoreTable>} entity={entity} at={got.computed_at} />
        : fam === "live" ? <LiveView res={got.result as LiveScores} entity={entity} />
        : !got.result ? <p className="muted">No figures to back-test this with.</p>
        : <Scores fam={fam} t={got.result as ScoreTable} entity={entity} at={got.computed_at} />}
      <p className="caption">Selected country: {name}. It is listed first under each country table when it has scores.</p>
    </>
  );
}

function StatPicker({ value, onChange }: { value: string; onChange: (id: string) => void }) {
  const [inds, setInds] = useState<Indicator[]>([]);
  useEffect(() => { api.indicators().then(setInds).catch(() => {}); }, []);
  const list = useMemo(() => {
    const top = STAT_DEFAULT.map((id) => inds.find((i) => i.indicator_id === id)).filter((i): i is Indicator => !!i);
    const rest = inds.filter((i) => i.enabled && i.available && !STAT_DEFAULT.includes(i.indicator_id)).sort((a, b) => a.name.localeCompare(b.name));
    return [...top, ...rest];
  }, [inds]);
  return (
    <div className="controls">
      <IndicatorSelect indicators={list} value={value} onChange={onChange} />
      <span className="small muted">The eight headline figures are worked out after each refresh; any other takes a minute or two when picked.</span>
    </div>
  );
}

function DiseaseScores({ res, entity, at }: { res: Record<string, ScoreTable>; entity: string; at?: string }) {
  const ids = Object.keys(res || {});
  const [m, setM] = useState<string>(ids[0] ?? "");
  useEffect(() => { if (!ids.includes(m) && ids.length) setM(ids[0]); }, [ids.join(","), m]); // eslint-disable-line react-hooks/exhaustive-deps
  if (!ids.length) return <p className="muted">No weekly flu or RSV figures with enough past seasons to back-test.</p>;
  const t = res[m] ?? res[ids[0]];
  return (
    <>
      <div className="controls">
        <select value={m} onChange={(e) => setM(e.target.value)} aria-label="Measure">
          {ids.map((id) => <option key={id} value={id}>{res[id].label}</option>)}
        </select>
      </div>
      <Scores fam="disease" t={t} entity={entity} at={at} />
    </>
  );
}

function missText(fam: string, t: ScoreTable, r: ScoreRow, base?: string): string {
  const b = base ? r.base?.[base] : undefined;
  const v = base ? b : { mae: r.mae, rel: r.rel };
  if (!v || v.mae === undefined) return "–";
  if (r.group) { // pooled across countries: in a common scale
    if (fam === "disease") return `${pct(v.rel, 1)} of usual peak`;
    if (t.rel_is_share) return pct(v.rel, 1);
  }
  return formatValue(v.mae, t.unit ?? "", t.decimals ?? 2);
}

function Scores({ fam, t, entity, at, live }: { fam: string; t: ScoreTable; entity: string; at?: string; live?: boolean }) {
  const hs = useMemo(() => Array.from(new Set(t.pooled.map((r) => r.h))).sort((a, b) => a - b), [t]);
  const [h, setH] = useState<number>(hs[0] ?? 1);
  const [filter, setFilter] = useState("");
  const odds = fam === "recession";
  const bases = fam === "disease" ? ["last", "usual"] : fam === "stat" ? ["naive"] : fam === "nowcast" ? ["prev"] : [];
  const cH = hs.includes(h) ? h : hs[0];
  const rows = t.countries.filter((r) => r.h === cH && (!filter || (r.name ?? r.e ?? "").toLowerCase().includes(filter.toLowerCase())))
    .sort((a, b) => (b.e === entity ? 1 : 0) - (a.e === entity ? 1 : 0));
  const span = t.from && t.to ? `${t.from} to ${t.to}` : "";
  const head = odds
    ? <tr><th>{live ? "" : "Who"}</th><th className="num">Checked</th><th className="num">Recessions</th><th className="num">Brier score</th>
        <th className="num">Base rate&apos;s</th><th className="num">Skill</th><th className="num">Mean chance before a recession</th><th className="num">… before none</th></tr>
    : <tr><th></th><th className="num">Checked</th><th className="num">Typical miss</th>{bases.map((b) => <th key={b} className="num">{BASES[b]}</th>)}
        <th className="num">Skill</th><th className="num">Inside 80% range</th>{fam === "stat" && <th className="num">Inside 95%</th>}</tr>;
  const cells = (r: ScoreRow) => odds
    ? <><td className="num">{r.n}</td><td className="num">{r.events}</td><td className="num">{r.brier?.toFixed(3)}</td>
        <td className="num">{r.base_brier?.toFixed(3)}</td><td className="num"><Skill v={r.skill} /></td>
        <td className="num">{pct(r.mean_p_events)}</td><td className="num">{pct(r.mean_p_none)}</td></>
    : <><td className="num">{r.n}</td><td className="num">{missText(fam, t, r)}</td>
        {bases.map((b) => <td key={b} className="num">{missText(fam, t, r, b)}</td>)}
        <td className="num"><Skill v={r.skill} /></td><td className="num"><Cover v={r.cover} /></td>
        {fam === "stat" && <td className="num"><Cover v={r.cover95} aim={0.95} /></td>}</>;
  return (
    <>
      <section className="card">
        <h3>{t.label}{live ? ": forecasts saved after each refresh" : ": made again from the past"}</h3>
        <p className="small ink-2" style={{ marginTop: 0 }}>
          {live ? `${t.n} scored${t.waiting ? `, ${t.waiting} waiting for their figures` : ""}${t.first ? `; saved since ${t.first.slice(0, 10)}` : ""}.`
            : fam === "disease" ? `Forecasts made after every week of the last ${t.years} years (${span}), each from the weeks before it only.`
            : fam === "stat" ? `Forecasts made from each of the last ${t.origins} years of each country's figures, each from the years before it only (target years ${span}).`
            : fam === "nowcast" ? `Each of the last 20 quarters estimated from the quarters before it (${span}). The 80% range uses the misses before each quarter only.`
            : `The model refitted every third month of the last ${t.years} years on the recessions known by then, and its odds of a recession starting within a year (to ${span.split(" to ")[1] ?? ""}).`}
          {!live && at ? ` Worked out ${at.slice(0, 16).replace("T", " ")} UTC.` : ""}
        </p>
        {t.n === 0 ? <p className="muted">Nothing to score yet.</p> : (
          <div className="table-wrap">
            <table className="summary-table">
              <thead>{head}</thead>
              <tbody>
                {t.pooled.map((r) => (
                  <tr key={`${r.h}-${r.group}`}>
                    <td>{hs.length > 1 ? `${ahead(fam, r.h)}, ` : ""}{r.group === "all" ? "all countries" : "NZ, Australia, UK, US"}</td>
                    {cells(r)}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {!odds && t.n > 0 && (
          <p className="caption">
            {fam === "disease" ? "Pooled misses are shown as a share of each country's usual peak, so countries can be added up; country rows are in the measure's own units."
              : fam === "stat" && t.rel_is_share ? "Pooled misses are shown as a share of the figure, so countries of different sizes can be added up."
              : "Misses are in the figure's own units."}
          </p>
        )}
      </section>
      {t.countries.length > 0 && (
        <section className="card">
          <h3>By country{!odds && t.unit && t.unit !== "chance" ? ` (misses in ${t.unit === "%" ? "percentage points" : t.unit})` : ""}</h3>
          <div className="controls">
            {hs.length > 1 && (
              <div className="seg" role="group" aria-label="How far ahead">
                {hs.map((x) => <button key={x} className={x === cH ? "on" : ""} onClick={() => setH(x)}>{ahead(fam, x)}</button>)}
              </div>
            )}
            <input type="search" placeholder="Filter countries" value={filter} onChange={(e) => setFilter(e.target.value)} aria-label="Filter countries" />
          </div>
          <div className="table-wrap" style={{ maxHeight: 520, overflowY: "auto" }}>
            <table className="summary-table">
              <thead>{head}</thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.e} className={r.e === entity ? "selected" : ""}>
                    <td>{r.name}</td>{cells(r)}
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

const FAMILY_NAME: Record<string, string> = { disease: "Flu and RSV", stat: "Yearly figures", nowcast: "Nowcasts", recession: "Recession odds" };

function LiveView({ res, entity }: { res: LiveScores; entity: string }) {
  const list = useMemo(() => Object.entries(res?.families ?? {}).flatMap(([f, ms]) => Object.entries(ms).map(([m, t]) => ({ f, m, t }))), [res]);
  const [pick, setPick] = useState(0);
  if (!res) return <p className="muted">No record yet.</p>;
  const cur = list[Math.min(pick, list.length - 1)];
  return (
    <>
      <section className="card">
        <p className="small ink-2" style={{ margin: 0 }}>
          {res.saved ? `${res.saved.toLocaleString()} forecasts saved${res.first ? ` since ${res.first.slice(0, 10)}` : ""}` : "No forecasts saved yet"}
          {res.keeping ? `; ${res.added.toLocaleString()} new after the latest refresh.` : ". Saving is off in Settings > Forecasts."}{" "}
          Only the first forecast made from each set of figures is kept, so a refresh that brings nothing new adds nothing.
          Weekly flu and RSV forecasts are scored within weeks; yearly figures, nowcasts and recession odds take months to years.
        </p>
      </section>
      {cur && (
        <>
          <div className="controls">
            <select value={pick} onChange={(e) => setPick(Number(e.target.value))} aria-label="Forecast">
              {list.map((x, i) => <option key={`${x.f}-${x.m}`} value={i}>{FAMILY_NAME[x.f] ?? x.f}: {x.t.label ?? x.m}{x.t.n ? ` (${x.t.n} scored)` : ""}</option>)}
            </select>
          </div>
          <Scores fam={cur.f} t={{ ...cur.t, label: cur.t.label ?? `${FAMILY_NAME[cur.f]}: ${cur.m}` }} entity={entity} live />
        </>
      )}
    </>
  );
}
