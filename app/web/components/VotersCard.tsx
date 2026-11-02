"use client";

import CardAsk from "@/components/CardAsk";
import Help from "@/components/Help";
import type { EChartsOption } from "echarts";
import { useCallback, useMemo, useState } from "react";
import EChart from "@/components/EChart";
import type { Indicator } from "@/lib/api";
import { points, useSavePicture, useSeries } from "@/lib/cards";
import { cardLinesOption, type CardLine } from "@/lib/charts";
import { cssVar, sequentialRamp, seriesColor } from "@/lib/colors";

// Who votes in one country: turnout by age group (light to dark, young to old), and by
// sex or group where the country reports it. With three or more elections the groups
// are lines over time; with fewer, bars for the latest election.
type Set = { key: string; label: string; lines: [string, string][]; ordered?: boolean };
type Country = { measures?: { key: string; label: string; prefix: string }[]; sets: Set[]; unit: string; note: string; midterms?: boolean };
type Which = "all" | "presidential" | "midterm";

const US_AGES: [string, string][] = [["18_24", "18 to 24"], ["25_44", "25 to 44"], ["45_64", "45 to 64"], ["65_plus", "65 and over"]];
const NZ_AGES: [string, string][] = [["18_24", "18–24"], ["25_29", "25–29"], ["30_34", "30–34"], ["35_39", "35–39"], ["40_44", "40–44"],
  ["45_49", "45–49"], ["50_54", "50–54"], ["55_59", "55–59"], ["60_64", "60–64"], ["65_69", "65–69"], ["70_plus", "70+"]];

const COUNTRIES: Record<string, Country> = {
  USA: {
    measures: [{ key: "voted", label: "Voted", prefix: "us_voted" }, { key: "registered", label: "Registered", prefix: "us_registered" }],
    unit: "% of residents of voting age",
    midterms: true,
    note: "US Census Bureau survey after each November election (table A-1); shares of everyone of that age living in the US.",
    sets: [
      { key: "age", label: "By age", ordered: true, lines: US_AGES.map(([k, l]) => [`_age_${k}`, l]) },
      { key: "sex", label: "Women and men", lines: [["_female", "Women"], ["_male", "Men"]] },
      { key: "group", label: "By group", lines: [["_white_nh", "White non-Hispanic"], ["_black", "Black"], ["_asian", "Asian"], ["_hispanic", "Hispanic"]] },
      { key: "all", label: "All and citizens", lines: [["", "Everyone 18+"], ["_citizens", "Citizens 18+"]] },
    ],
  },
  NZL: {
    unit: "% of enrolled",
    note: "Electoral Commission turnout statistics; shares of people enrolled.",
    sets: [
      { key: "age", label: "By age", ordered: true, lines: NZ_AGES.map(([k, l]) => [`nz_turnout_age_${k}`, l]) },
      { key: "descent", label: "Māori descent", lines: [["nz_turnout_maori", "Māori descent"], ["nz_turnout_non_maori", "Non-Māori descent"]] },
      { key: "age_descent", label: "Age and descent", lines: NZ_AGES.flatMap(([k, l]) =>
        [[`nz_turnout_age_${k}_maori`, `${l} Māori`], [`nz_turnout_age_${k}_non_maori`, `${l} non-Māori`]] as [string, string][]) },
    ],
  },
};

function barsOption(groups: { label: string; values: { name: string; value: number; color: string }[] }[], unit: string): EChartsOption {
  const names = [...new Set(groups.flatMap((g) => g.values.map((v) => v.name)))];
  return {
    backgroundColor: "transparent",
    textStyle: { fontFamily: "system-ui, -apple-system, 'Segoe UI', sans-serif", color: cssVar("--ink-2") },
    grid: { left: 8, right: 16, top: names.length > 1 ? 58 : 36, bottom: 8, containLabel: true },
    legend: names.length > 1 ? { top: 0, left: 0, icon: "roundRect", itemWidth: 12, itemHeight: 8, textStyle: { color: cssVar("--ink-2") } } : undefined,
    tooltip: { trigger: "axis", confine: true, backgroundColor: cssVar("--surface"), borderColor: cssVar("--border"), textStyle: { color: cssVar("--ink") },
      valueFormatter: (v) => `${(+(v as number)).toFixed(1)}%` },
    xAxis: { type: "category", data: groups.map((g) => g.label), axisLabel: { color: cssVar("--muted") }, axisLine: { lineStyle: { color: cssVar("--axis") } } },
    yAxis: { type: "value", name: unit, nameTextStyle: { color: cssVar("--muted"), align: "left" }, min: (x: { min: number }) => Math.max(0, Math.floor(x.min / 10) * 10 - 10),
      max: 100, axisLabel: { color: cssVar("--muted") }, splitLine: { lineStyle: { color: cssVar("--grid") } } },
    // One series: each bar keeps its group's own colour (light to dark by age).
    series: names.map((n) => ({ type: "bar", name: n, barMaxWidth: 28,
      itemStyle: { color: groups.flatMap((g) => g.values).find((v) => v.name === n)?.color, borderRadius: [2, 2, 0, 0] },
      data: groups.map((g) => {
        const v = g.values.find((x) => x.name === n);
        return v ? (names.length === 1 ? { value: v.value, itemStyle: { color: v.color } } : v.value) : null;
      }) })),
  };
}

export default function VotersCard({ entity, name, indicators }: { entity: string; name: string; indicators: Map<string, Indicator> }) {
  const country = COUNTRIES[entity];
  const [measure, setMeasure] = useState(0);
  const [pick, setPick] = useState("age");
  // US turnout swings between presidential and midterm years; one kind at a time reads easier.
  const [which, setWhich] = useState<Which>("presidential");
  const prefix = country?.measures?.[measure]?.prefix ?? "";
  const all = useMemo(() => (country ? country.sets.flatMap((s) => s.lines.map(([id]) => prefix + id)) : []), [country, prefix]);
  const { data, error } = useSeries(entity, all, indicators);
  const { onReady, save, ask } = useSavePicture();
  const has = (s: Set) => s.lines.some(([id]) => data?.get(prefix + id)?.length);
  const sets = country?.sets.filter(has) ?? [];
  const set = sets.find((s) => s.key === pick) ?? sets[0];

  const lines: CardLine[] = useMemo(() => {
    if (!set || !data) return [];
    const ramp = sequentialRamp();
    const n = set.lines.length;
    return set.lines.filter(([id]) => data.get(prefix + id)?.length).map(([id, label], i) => ({
      key: id, label,
      color: set.ordered ? ramp[Math.min(ramp.length - 1, Math.round(1 + (i * (ramp.length - 2)) / Math.max(1, n - 1)))] : seriesColor([6, 4, 0, 2][i % 4]),
      points: points(data.get(prefix + id)).filter((p) => !country?.midterms || which === "all"
        || (which === "presidential") === (p[0] % 4 === 0)),
    }));
  }, [set, data, prefix, country, which]);
  const years = [...new Set(lines.flatMap((l) => l.points.map((p) => p[0])))].sort((a, b) => a - b);
  const asBars = years.length > 0 && years.length < 3;
  const latest = years[years.length - 1];

  const option = useCallback((): EChartsOption => {
    if (!asBars) return cardLinesOption(lines, { unit: country?.unit ?? "%", decimals: 1 });
    if (set?.key === "age_descent") {  // pairs: Māori and non-Māori bars per age band
      return barsOption(NZ_AGES.map(([k, l]) => ({ label: l, values: lines.filter((x) => x.key.startsWith(`nz_turnout_age_${k}_`)).map((x) => ({
        name: x.key.endsWith("_non_maori") ? "Non-Māori descent" : "Māori descent",
        color: seriesColor(x.key.endsWith("_non_maori") ? 4 : 6), value: x.points.find((p) => p[0] === latest)?.[1] ?? NaN })) }))
        .filter((g) => g.values.length), country?.unit ?? "%");
    }
    return barsOption(lines.map((x) => ({ label: x.label, values: [{ name: String(latest), color: x.color, value: x.points.find((p) => p[0] === latest)?.[1] ?? NaN }] })),
      country?.unit ?? "%");
  }, [asBars, lines, set, latest, country]);

  if (!country || !data || !sets.length) {
    return error && country ? <div className="card"><h3>Who votes</h3><p className="error">{error}</p></div> : null;
  }
  const verb = country.measures?.[measure]?.label ?? "Voted";
  const title = `${verb} ${set.label.toLowerCase()}${asBars ? `, ${latest}` : ""}${country.midterms && which !== "all" ? `, ${which === "presidential" ? "presidential" : "midterm"} elections` : ""}`;
  const sources = lines.map((l) => indicators.get(prefix + l.key)?.sources[0]?.source_id);
  return (
    <div className="card" id="voters">
      <div className="card-head">
        <h3>Who votes <Help note="voters" /></h3>
        <CardAsk onAsk={() => ask(`${title}: ${name}`, country.note, sources, entity)} />
        <button className="link small" title="Save this chart as a picture, with its sources"
          onClick={() => save(`${title}: ${name}`, country.note, sources, "voters", set.key, entity)}>Save picture</button>
      </div>
      <div className="chips-row small">
        {country.measures && (
          <div className="seg">
            {country.measures.map((m, i) => <button key={m.key} className={i === measure ? "on" : ""} aria-pressed={i === measure} onClick={() => setMeasure(i)}>{m.label}</button>)}
          </div>
        )}
        {country.midterms && (
          <div className="seg">
            {(["presidential", "midterm", "all"] as Which[]).map((w) => <button key={w} className={w === which ? "on" : ""} aria-pressed={w === which}
              onClick={() => setWhich(w)}>{w === "all" ? "All elections" : w === "presidential" ? "Presidential years" : "Midterms"}</button>)}
          </div>
        )}
        <div className="seg">
          {sets.map((s) => <button key={s.key} className={s === set ? "on" : ""} aria-pressed={s === set} onClick={() => setPick(s.key)}>{s.label}</button>)}
        </div>
      </div>
      {error && <p className="error">{error}</p>}
      <EChart option={option} height={300} label={`${title} in ${name}`} onReady={onReady} />
      <p className="caption">
        {country.note}{asBars ? ` ${years.length === 1 ? "One election" : "Two elections"} loaded (latest ${latest}); load earlier elections' files to see the change over time.` : ""}
        {entity === "USA" && set.key === "age" ? " Before 1972 the youngest group is 21 to 24 in most states." : ""}
      </p>
    </div>
  );
}
