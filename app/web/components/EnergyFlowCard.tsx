"use client";

import CardAsk from "@/components/CardAsk";
import Help from "@/components/Help";
import type { EChartsOption } from "echarts";
import { useCallback, useEffect, useState } from "react";
import EChart from "@/components/EChart";
import { api, type EnergyFlow } from "@/lib/api";
import { useSavePicture } from "@/lib/cards";
import { cssVar, seriesColor } from "@/lib/colors";
import { formatValue } from "@/lib/format";

const pj = (v: number, d = v < 10 ? 1 : 0) => `${formatValue(v, "", d)} PJ`;

// Where a country's (or a group's) energy comes from and where it goes, for one year of its
// energy balance: fuels on the left, electricity generation in the middle, the sectors that
// use the energy on the right, and the losses on the way. Every country from the UN's energy
// statistics; New Zealand also from MBIE's own balance (the default there), with a switch.
// Shown in petajoules, as a share of primary supply, or per person (gigajoules).
// Fuel colours match the energy mix chart's and the Grid now card's.
export const FUEL_COLOR: Record<string, number> = {
  Coal: 7, Oil: 5, "Natural gas": 2, Hydro: 0, Wind: 3, Solar: 6, Bioenergy: 1, Geothermal: 4,
};
// Beyond the eight series colours: fixed ones that read the same in light and dark.
const FUEL_FIXED: Record<string, string> = { Nuclear: "#8e6cc0", Waste: "#8a8a5c", Battery: "#d6336c", "Pumped storage": "#4c6ef5", Imports: "#868e96", Other: "#adb5bd" };

export function fuelColor(name: string): string | null {
  if (name in FUEL_COLOR) return seriesColor(FUEL_COLOR[name]);
  return FUEL_FIXED[name] ?? null;
}
type Scale = "pj" | "share" | "person";
const SOURCE_NOTE: Record<string, string> = {
  mbie_energy: "MBIE energy balance tables",
  unsd_energy: "UN Statistics Division energy statistics, grouped by fuel here",
};

function nodeColor(name: string, kind: string): string {
  const fixed = fuelColor(name);
  if (fixed && kind === "source") return fixed;
  if (name in FUEL_COLOR) return seriesColor(FUEL_COLOR[name]);
  if (kind === "electricity") return cssVar("--ink-2");
  if (kind === "loss") return cssVar("--axis");
  if (kind === "source") return cssVar("--muted");
  return cssVar("--accent") || seriesColor(0);
}

function scaler(f: EnergyFlow, scale: Scale): [(v: number) => number, (v: number) => string] {
  const total = f.totals?.primary_supply || 0;
  if (scale === "share" && total) return [(v) => (100 * v) / total, (v) => `${v < 1 ? v.toFixed(1) : v.toFixed(0)}%`];
  if (scale === "person" && f.population) {
    const per = 1e6 / f.population; // PJ to GJ is 1e6
    return [(v) => v * per, (v) => `${formatValue(v, "", v < 10 ? 1 : 0)} GJ`];
  }
  return [(v) => v, (v) => pj(v)];
}

export function energyFlowOption(f: EnergyFlow, scale: Scale = "pj"): EChartsOption {
  const [conv, show] = scaler(f, scale);
  const fmt = (v: number) => show(v);
  const kinds = new Map(f.nodes.map((n) => [n.name, n.kind]));
  return {
    backgroundColor: "transparent",
    textStyle: { fontFamily: "system-ui, -apple-system, 'Segoe UI', sans-serif", color: cssVar("--ink-2") },
    tooltip: {
      trigger: "item", confine: true, backgroundColor: cssVar("--surface"), borderColor: cssVar("--border"),
      textStyle: { color: cssVar("--ink") },
      formatter: (p: unknown) => {
        const q = p as { dataType: string; data: { source?: string; target?: string; value?: number; name?: string }; value: number };
        return q.dataType === "edge" ? `${q.data.source} → ${q.data.target}: <b>${fmt(q.data.value ?? 0)}</b>`
          : `${q.data.name}: <b>${fmt(q.value ?? 0)}</b>`;
      },
    },
    series: [{
      type: "sankey", left: 8, right: 210, top: 8, bottom: 8, nodeWidth: 12, nodeGap: 8, layoutIterations: 64,
      nodeAlign: "justify", draggable: false,
      emphasis: { focus: "adjacency" },
      label: { color: cssVar("--ink"), fontSize: 11, formatter: (p: { name: string; value: number }) => `${p.name}  ${fmt(p.value)}` },
      lineStyle: { color: "gradient", opacity: 0.35, curveness: 0.5 },
      data: f.nodes.map((n) => ({ name: n.name, itemStyle: { color: nodeColor(n.name, n.kind), borderWidth: 0 } })),
      links: f.links.map((l) => ({ ...l, value: conv(l.value), lineStyle: kinds.get(l.target) === "loss" ? { opacity: 0.18 } : undefined })),
    }],
  } as EChartsOption;
}

export default function EnergyFlowCard({ entity, name }: { entity: string; name: string }) {
  const [flow, setFlow] = useState<EnergyFlow | null>(null);
  const [year, setYear] = useState<number | undefined>(undefined);
  const [source, setSource] = useState<string | undefined>(undefined);
  const [scale, setScale] = useState<Scale>("pj");
  const [error, setError] = useState<string | null>(null);
  const { onReady, save, ask } = useSavePicture();
  useEffect(() => {
    let live = true;
    api.energyFlow(entity, year, source).then((f) => { if (live) { setFlow(f); setError(null); } })
      .catch((e) => live && setError(String(e.message || e)));
    return () => { live = false; };
  }, [entity, year, source]);
  const option = useCallback(() => (flow ? energyFlowOption(flow, scale) : {}), [flow, scale]);
  if (error) return <div className="card"><h3>Energy flow</h3><p className="error">{error}</p></div>;
  if (!flow || !flow.years.length || !flow.links.length) return null;
  const t = flow.totals;
  const share = t && t.primary_supply ? (100 * ["Hydro", "Geothermal", "Wind", "Solar", "Bioenergy"]
    .reduce((s, g) => s + (t.supply_by_group[g] ?? 0), 0)) / t.primary_supply : null;
  const title = `Energy flow, ${flow.year}`;
  const unitNote = scale === "share" ? "Share of primary energy supply (%)." : scale === "person" ? "Gigajoules (GJ) per person."
    : "Petajoules (PJ), gross calorific value.";
  const srcName = flow.sources?.find((x) => x.source_id === flow.source_id)?.name ?? flow.source_id ?? "";
  return (
    <div className="card" id="energy-flow">
      <div className="card-head">
        <h3>Where energy comes from and goes <Help note="energyflow" /></h3>
        <CardAsk onAsk={() => ask(`${title}: ${name}`, unitNote, [flow.source_id], entity)} />
        <button className="link small" title="Save this chart as a picture, with its sources"
          onClick={() => save(`${title}: ${name}`, unitNote, [flow.source_id], "energy-flow", String(flow.year), entity)}>Save picture</button>
      </div>
      <div className="chips-row small">
        <label>Year{" "}
          <input type="range" min={flow.years[0]} max={flow.years[flow.years.length - 1]} value={flow.year ?? 0}
            onChange={(e) => setYear(+e.target.value)} aria-label="Year" />
        </label>
        <b>{flow.year}</b>
        <button className="link small" disabled={flow.year === flow.years[flow.years.length - 1]}
          onClick={() => setYear(flow.years[flow.years.length - 1])}>Latest</button>
        <div className="seg" role="group" aria-label="Units">
          {([["pj", "PJ"], ["share", "% of supply"], ["person", "Per person"]] as [Scale, string][]).map(([k, l]) => (
            <button key={k} className={scale === k ? "on" : ""} aria-pressed={scale === k} disabled={k === "person" && !flow.population}
              onClick={() => setScale(k)}>{l}</button>))}
        </div>
        {(flow.sources?.length ?? 0) > 1 && (
          <label>Source{" "}
            <select value={flow.source_id ?? ""} onChange={(e) => { setSource(e.target.value); setYear(undefined); }}>
              {flow.sources!.map((x) => <option key={x.source_id} value={x.source_id}>{x.name} ({x.first}–{x.last})</option>)}
            </select>
          </label>
        )}
      </div>
      <EChart option={option} height={460} label={`${title} in ${name}`} onReady={onReady} update="merge" />
      <p className="caption">
        {t ? `Primary energy ${pj(t.primary_supply, 0)}${share != null ? `, ${share.toFixed(0)}% of it renewable` : ""}; `
          + `electricity generated ${pj(t.electricity_generated, 0)}. ` : ""}
        Fuels on the left are what the country produced or imported and kept; exports are left out. Conversion losses are
        the heat that does not become electricity (large for geothermal and nuclear, which count at their heat).
        {flow.coverage != null && flow.coverage < 0.999 ? ` The sum covers countries with ${Math.round(flow.coverage * 100)}% of the group's people.` : ""}
        {" "}Source: {SOURCE_NOTE[flow.source_id ?? ""] ?? srcName}.
      </p>
    </div>
  );
}
