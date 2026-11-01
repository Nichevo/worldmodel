"use client";

import { useCallback, useMemo, useState } from "react";
import EChart from "@/components/EChart";
import Help from "@/components/Help";
import type { Indicator, SeriesRow } from "@/lib/api";
import { useSavePicture, useSeries } from "@/lib/cards";
import { cssVar, seriesColor } from "@/lib/colors";
import { formatValue } from "@/lib/format";

// Debt per person by sector for one country: what the government, households and
// companies owe, stacked so the top is total debt. Each sector's debt as a share of
// GDP times GDP per person gives an amount per person (US dollars or local
// currency); "% of GDP" shows the shares themselves. Only estimates are drawn, not
// projections, and only years where a sector has a figure.
const SECTORS = [
  { key: "govt", label: "Government", ids: ["govt_debt_gdp", "central_govt_debt_gdp"], color: 0 },
  { key: "household", label: "Households", ids: ["imf_household_debt_gdp"], color: 1 },
  { key: "company", label: "Companies", ids: ["imf_corporate_debt_gdp"], color: 2 },
] as const;
const PER_PERSON = { usd: "gdp_per_capita_usd", lcu: "gdp_per_capita_lcu" } as const;
type Unit = "usd" | "lcu" | "gdp";
const ALL = [...SECTORS.flatMap((s) => s.ids), ...Object.values(PER_PERSON)];

// Yearly estimates of the first id with any (the order is the order of preference).
function yearly(data: Map<string, SeriesRow[]> | null, ids: readonly string[]): { id: string; by: Map<number, number> } | null {
  for (const id of ids) {
    const rows = (data?.get(id) ?? []).filter((r) => r.status === "E");
    if (rows.length) return { id, by: new Map(rows.map((r) => [+r.period.slice(0, 4), r.value])) };
  }
  return null;
}

export default function DebtCard({ entity, name, indicators }: { entity: string; name: string; indicators: Map<string, Indicator> }) {
  const { data, error } = useSeries(entity, ALL, indicators);
  const [unit, setUnit] = useState<Unit>("usd");
  const { onReady, save } = useSavePicture();

  const model = useMemo(() => {
    const sectors = SECTORS.map((s) => ({ ...s, found: yearly(data, s.ids) })).filter((s) => s.found);
    const scale = unit === "gdp" ? null : yearly(data, [PER_PERSON[unit]]);
    const years = [...new Set(sectors.flatMap((s) => [...s.found!.by.keys()]))]
      .filter((y) => !scale || scale.by.has(y)).sort((a, b) => a - b);
    const value = (s: (typeof sectors)[number], y: number) => {
      const share = s.found!.by.get(y);
      if (share === undefined) return null;
      return scale ? (share / 100) * scale.by.get(y)! : share;
    };
    return { sectors, years, value, perPersonFrom: scale?.id ?? null };
  }, [data, unit]);

  const valueUnit = unit === "gdp" ? "% of GDP" : unit === "usd" ? "US dollars per person" : "local currency per person";
  const fmt = (v: number) => (unit === "gdp" ? formatValue(v, "%", 0) : unit === "usd" ? `$${formatValue(v, "", 0)}` : formatValue(v, "", 0));
  const option = useCallback(() => {
    const series = model.sectors.map((s) => ({
      type: "bar" as const, name: s.label, stack: "debt", color: seriesColor(s.color), barMaxWidth: 14,
      emphasis: { focus: "series" as const },
      data: model.years.map((y) => model.value(s, y)),
    }));
    return {
      backgroundColor: "transparent",
      textStyle: { fontFamily: "system-ui, -apple-system, 'Segoe UI', sans-serif", color: cssVar("--ink-2") },
      grid: { left: 8, right: 16, top: 36, bottom: 8, containLabel: true },
      legend: { top: 0, left: 0, icon: "roundRect", itemWidth: 12, itemHeight: 8, textStyle: { color: cssVar("--ink-2") } },
      xAxis: { type: "category" as const, data: model.years.map(String), axisLabel: { color: cssVar("--muted") },
        axisLine: { lineStyle: { color: cssVar("--axis") } } },
      yAxis: { type: "value" as const, name: valueUnit, nameTextStyle: { color: cssVar("--muted"), align: "left" as const },
        axisLabel: { color: cssVar("--muted"), formatter: (v: number) => fmt(v) }, splitLine: { lineStyle: { color: cssVar("--border") } } },
      tooltip: {
        trigger: "axis" as const, axisPointer: { type: "shadow" as const }, backgroundColor: cssVar("--surface"),
        borderColor: cssVar("--border"), textStyle: { color: cssVar("--ink") },
        formatter: (params: unknown) => {
          const ps = params as { axisValue: string; seriesName: string; value: number | null; color: string }[];
          const lines = ps.map((p) => `<span style="display:inline-block;width:8px;height:8px;border-radius:2px;background:${p.color};margin-right:6px"></span>`
            + `${p.seriesName}: <b>${p.value === null || p.value === undefined ? "no figure" : fmt(p.value)}</b>`);
          const all = ps.every((p) => p.value !== null && p.value !== undefined) && ps.length === SECTORS.length;
          const total = ps.reduce((t, p) => t + (p.value ?? 0), 0);
          return `<b>${ps[0]?.axisValue}</b><br/>${lines.join("<br/>")}<br/>${all ? "Total" : "Total of those with figures"}: <b>${fmt(total)}</b>`;
        },
      },
      series,
    };
  }, [model, unit]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!data || !model.sectors.length) {
    return error ? <div className="card"><h3>Debt per person</h3><p className="error">{error}</p></div> : null;
  }
  const govt = model.sectors.find((s) => s.key === "govt")?.found?.id;
  const sources = [...model.sectors.map((s) => indicators.get(s.found!.id)?.sources[0]?.source_id),
    model.perPersonFrom ? indicators.get(model.perPersonFrom)?.sources[0]?.source_id : null];
  const missing = SECTORS.filter((s) => !model.sectors.some((m) => m.key === s.key)).map((s) => s.label.toLowerCase());
  return (
    <div className="card" id="debt">
      <div className="card-head">
        <h3>Debt per person <Help note="debt" /></h3>
        {model.years.length > 0 && <button className="link small" title="Save this chart as a picture, with its sources"
          onClick={() => save(`Debt by sector: ${name}`, `${valueUnit}.`, sources, "debt", unit, entity)}>Save picture</button>}
      </div>
      <div className="chips-row small">
        <div className="seg" role="group" aria-label="Units">
          {([["usd", "US$ per person"], ["lcu", "Local currency per person"], ["gdp", "% of GDP"]] as [Unit, string][]).map(([u, label]) => (
            <button key={u} className={unit === u ? "on" : ""} aria-pressed={unit === u} onClick={() => setUnit(u)}>{label}</button>
          ))}
        </div>
      </div>
      {error && <p className="error">{error}</p>}
      {model.years.length === 0 && <p className="muted">No figures in these units for {name} yet.</p>}
      {model.years.length > 0 && <EChart option={option} height={280} label={`Debt by sector in ${name}`} onReady={onReady} />}
      <p className="caption">
        Each sector&apos;s debt as a share of GDP{unit === "gdp" ? "" : ", times GDP per person"}. Government is
        {govt === "central_govt_debt_gdp" ? " central government only (World Bank), as the IMF figure for all government is not loaded" : " all government (IMF World Economic Outlook)"};
        households and companies come from the IMF Global Debt Database.
        {missing.length ? ` No figures for ${missing.join(" or ")}.` : ""} Hover a bar for each sector and the total.
      </p>
    </div>
  );
}
