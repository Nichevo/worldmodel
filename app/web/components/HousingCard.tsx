"use client";

import { useCallback, useMemo, useState } from "react";
import EChart from "@/components/EChart";
import type { Indicator } from "@/lib/api";
import { firstWith, indexed, points, useSavePicture, useSeries } from "@/lib/cards";
import { cardLinesOption, type CardLine } from "@/lib/charts";
import { seriesColor } from "@/lib/colors";

// House prices against incomes for one country: both as an index on a common base
// year (one axis, so the gap between the lines is the story), their ratio against
// its own average, and household debt. Each line comes from the first source with
// figures; the house price source can be switched.
// House price series and the incomes to set them against, by preference. Nominal
// prices go with nominal incomes in local currency; real (after inflation) prices
// with real incomes, where GDP per person can be chained from its yearly growth.
type Income = { id: string; label: string; growth?: boolean };
const PAIRS: Record<"nominal" | "real", { id: string; label: string; income: Income[] }[]> = {
  nominal: [
    { id: "dfed_house_price_nominal", label: "Dallas Fed", income: [{ id: "dfed_income_nominal", label: "Disposable income per person" }] },
    { id: "oecd_house_price_nominal", label: "OECD", income: [{ id: "gni_per_capita_lcu", label: "Income per person (GNI)" }, { id: "gdp_per_capita_lcu", label: "GDP per person" }] },
    { id: "bis_house_price_nominal", label: "BIS", income: [{ id: "gni_per_capita_lcu", label: "Income per person (GNI)" }, { id: "gdp_per_capita_lcu", label: "GDP per person" }] },
  ],
  real: [
    { id: "dfed_house_price_real", label: "Dallas Fed", income: [{ id: "dfed_income_real", label: "Real disposable income per person" }] },
    { id: "oecd_house_price_real", label: "OECD", income: [{ id: "gdp_per_capita_constant_usd", label: "Real GDP per person" }, { id: "gdp_per_capita_growth", label: "Real GDP per person", growth: true }] },
    { id: "bis_house_price_real", label: "BIS", income: [{ id: "gdp_per_capita_constant_usd", label: "Real GDP per person" }, { id: "gdp_per_capita_growth", label: "Real GDP per person", growth: true }] },
  ],
};
const DEBT = [
  { id: "oecd_household_debt_income", label: "% of disposable income", unit: "% of disposable income" },
  { id: "bis_household_credit_gdp", label: "% of GDP (BIS)", unit: "% of GDP" },
  { id: "imf_household_debt_gdp", label: "% of GDP (IMF)", unit: "% of GDP" },
];
const ALL = [...new Set([...Object.values(PAIRS).flat().flatMap((h) => [h.id, ...h.income.map((i) => i.id)]), ...DEBT.map((d) => d.id)])];

// An index from yearly growth rates (%), 100 in the first year.
function chained(pts: [number, number, string][]): [number, number, string][] {
  const out: [number, number, string][] = [];
  let level = 100;
  for (const [i, p] of pts.entries()) {
    if (i > 0 && p[0] !== pts[i - 1][0] + 1) {  // start again after a gap
      out.length = 0;
      level = 100;
    }
    if (out.length) level *= 1 + p[1] / 100;
    out.push([p[0], level, p[2]]);
  }
  return out;
}
type View = "index" | "ratio" | "debt";

export default function HousingCard({ entity, name, indicators }: { entity: string; name: string; indicators: Map<string, Indicator> }) {
  const { data, error } = useSeries(entity, ALL, indicators);
  const [view, setView] = useState<View>("index");
  const [termsPick, setTerms] = useState<"nominal" | "real" | null>(null);
  const [pick, setPick] = useState<string | null>(null);
  const [baseChoice, setBaseChoice] = useState<number | null>(null);
  const [debtPick, setDebtPick] = useState<string | null>(null);
  const { onReady, save } = useSavePicture();

  const options = (t: "nominal" | "real") => PAIRS[t].filter((h) => data?.get(h.id)?.length)
    .map((h) => ({ ...h, inc: h.income.find((i) => data?.get(i.id)?.length) ?? null }));
  const terms = termsPick ?? (options("nominal").some((h) => h.inc) ? "nominal" : "real");
  const houses = options(terms);
  const house = houses.find((h) => h.label === pick && h.inc) ?? houses.find((h) => h.inc) ?? houses[0];
  const income = house?.inc ?? null;
  const incomeId = income?.id ?? null;
  const debts = DEBT.filter((d) => data?.get(d.id)?.length);
  const debt = debts.find((d) => d.id === debtPick) ?? debts[0];

  const pair = useMemo(() => {
    if (!house || !income || !data) return null;
    const hp = points(data.get(house.id)).filter((p) => p[2] === "E");
    const raw = points(data.get(income.id)).filter((p) => p[2] === "E");
    const inc = income.growth ? chained(raw) : raw;
    const both = hp.map((p) => p[0]).filter((y) => inc.some((q) => q[0] === y));
    return both.length >= 2 ? { hp, inc, years: both } : null;
  }, [house, income, data]);
  const base = pair ? (baseChoice && pair.years.includes(baseChoice) ? baseChoice : pair.years[0]) : null;

  const lines: CardLine[] = useMemo(() => {
    if (view === "debt") {
      return debt && data ? [{ key: debt.id, label: `Household debt, ${debt.label}`, color: seriesColor(7), points: points(data.get(debt.id)) }] : [];
    }
    if (!pair || base === null) return [];
    const hp = indexed(pair.hp, base).filter((p) => pair.years.includes(p[0]));
    const inc = indexed(pair.inc, base).filter((p) => pair.years.includes(p[0]));
    if (view === "index") {
      return [
        { key: "hp", label: "House prices", color: seriesColor(1), points: hp },
        { key: "inc", label: income!.label, color: seriesColor(0), points: inc },
      ];
    }
    const incAt = new Map(inc.map((p) => [p[0], p[1]]));
    const ratio = hp.map((p) => [p[0], (100 * p[1]) / incAt.get(p[0])!, "E"] as [number, number, string]);
    return [{ key: "ratio", label: "House prices to income", color: seriesColor(1), points: ratio }];
  }, [view, pair, base, debt, data, income]);

  const average = view === "ratio" && lines[0]?.points.length
    ? lines[0].points.reduce((t, p) => t + p[1], 0) / lines[0].points.length : null;
  const option = useCallback(() => cardLinesOption(lines, view === "debt"
    ? { unit: debt?.unit ?? "%", decimals: 1 }
    : { unit: `index, ${base} = 100`, decimals: 1,
        refY: view === "ratio" && average !== null ? { value: average, label: `Average ${average.toFixed(0)}` } : { value: 100, label: String(base) } }),
  [lines, view, debt, base, average]);

  if (!data || (!options("nominal").length && !options("real").length && !debts.length)) {
    return error ? <div className="card"><h3>House prices and incomes</h3><p className="error">{error}</p></div> : null;
  }
  const title = view === "debt" ? "Household debt" : view === "ratio" ? "House prices to income" : "House prices and incomes";
  const sources = view === "debt" ? [indicators.get(debt?.id ?? "")?.sources[0]?.source_id]
    : [indicators.get(house?.id ?? "")?.sources[0]?.source_id, indicators.get(incomeId ?? "")?.sources[0]?.source_id];
  const note = view === "debt" ? (debt?.unit ?? "")
    : `Both as an index, ${base} = 100; ${terms === "real" ? "after inflation" : "nominal, in local currency"}.${view === "ratio" ? " Dashed line: the average of the years shown." : ""}`;
  const choices = pair ? [pair.years[0], 1990, 2000, 2010].filter((y, i, a) => pair.years.includes(y) && a.indexOf(y) === i) : [];

  return (
    <div className="card" id="housing">
      <div className="card-head">
        <h3>House prices and incomes</h3>
        {lines.length > 0 && <button className="link small" title="Save this chart as a picture, with its sources"
          onClick={() => save(`${title}: ${name}`, note, sources, "housing", view, entity)}>Save picture</button>}
      </div>
      <div className="chips-row small">
        <div className="seg">
          <button className={view === "index" ? "on" : ""} aria-pressed={view === "index"} disabled={!pair} onClick={() => setView("index")}>Prices and income</button>
          <button className={view === "ratio" ? "on" : ""} aria-pressed={view === "ratio"} disabled={!pair} onClick={() => setView("ratio")}>Price to income</button>
          <button className={view === "debt" ? "on" : ""} aria-pressed={view === "debt"} disabled={!debts.length} onClick={() => setView("debt")}>Household debt</button>
        </div>
        {view !== "debt" && (
          <div className="seg">
            {(["nominal", "real"] as const).map((t) => (
              <button key={t} className={terms === t ? "on" : ""} aria-pressed={terms === t} disabled={!options(t).some((h) => h.inc)}
                onClick={() => setTerms(t)}>{t === "nominal" ? "Nominal" : "After inflation"}</button>
            ))}
          </div>
        )}
        {view !== "debt" && houses.filter((h) => h.inc).length > 1 && (
          <label>House prices from{" "}
            <select value={house?.label} onChange={(e) => setPick(e.target.value)}>
              {houses.filter((h) => h.inc).map((h) => <option key={h.id} value={h.label}>{h.label}</option>)}
            </select>
          </label>
        )}
        {view !== "debt" && choices.length > 1 && (
          <label>Base year{" "}
            <select value={base ?? ""} onChange={(e) => setBaseChoice(+e.target.value)}>
              {choices.map((y) => <option key={y} value={y}>{y}</option>)}
            </select>
          </label>
        )}
        {view === "debt" && debts.length > 1 && (
          <div className="seg">
            {debts.map((d) => <button key={d.id} className={debt?.id === d.id ? "on" : ""} aria-pressed={debt?.id === d.id} onClick={() => setDebtPick(d.id)}>{d.label}</button>)}
          </div>
        )}
      </div>
      {error && <p className="error">{error}</p>}
      {view !== "debt" && !pair && <p className="muted">No house prices and incomes over the same years for {name} yet.</p>}
      {lines.length > 0 && <EChart option={option} height={300} label={`${title} in ${name}`} onReady={onReady} />}
      <p className="caption">
        {view === "index" && <>When the house price line climbs above the income line, homes cost more years of income than in {base}. </>}
        {view === "ratio" && <>House prices divided by {income ? income.label.charAt(0).toLowerCase() + income.label.slice(1) : "income"}, {base} = 100: above the dashed average, homes are less affordable than usual. </>}
        {view === "debt" && <>Debt of households, mostly mortgages. </>}
        Sources: {[...new Set((view === "debt" ? [debt?.id] : [house?.id, incomeId])
          .map((id) => indicators.get(id ?? "")?.sources[0]?.source_name).filter(Boolean))].join("; ")}.
      </p>
    </div>
  );
}
