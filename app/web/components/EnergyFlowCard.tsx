"use client";

import Help from "@/components/Help";
import type { EChartsOption } from "echarts";
import { useCallback, useEffect, useState } from "react";
import EChart from "@/components/EChart";
import { api, type EnergyFlow } from "@/lib/api";
import { useSavePicture } from "@/lib/cards";
import { cssVar, seriesColor } from "@/lib/colors";
import { formatValue } from "@/lib/format";

const pj = (v: number, d = v < 10 ? 1 : 0) => `${formatValue(v, "", d)} PJ`;

// Where a country's energy comes from and where it goes, for one year of its energy
// balance: fuels on the left, electricity generation in the middle, the sectors that
// use the energy on the right, and the losses on the way. Only countries with an
// energy balance stored have it (New Zealand, from MBIE, in the New Zealand pack).
// Fuel colours match the energy mix chart's.
const FUEL_COLOR: Record<string, number> = {
  Coal: 7, Oil: 5, "Natural gas": 2, Hydro: 0, Wind: 3, Solar: 6, Bioenergy: 1, Geothermal: 4,
};

function nodeColor(name: string, kind: string): string {
  if (name in FUEL_COLOR) return seriesColor(FUEL_COLOR[name]);
  if (kind === "electricity") return cssVar("--ink-2");
  if (kind === "loss") return cssVar("--axis");
  if (kind === "source") return cssVar("--muted");
  return cssVar("--accent") || seriesColor(0);
}

export function energyFlowOption(f: EnergyFlow): EChartsOption {
  const fmt = (v: number) => pj(v);
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
      links: f.links.map((l) => ({ ...l, lineStyle: kinds.get(l.target) === "loss" ? { opacity: 0.18 } : undefined })),
    }],
  } as EChartsOption;
}

export default function EnergyFlowCard({ entity, name }: { entity: string; name: string }) {
  const [flow, setFlow] = useState<EnergyFlow | null>(null);
  const [year, setYear] = useState<number | undefined>(undefined);
  const [error, setError] = useState<string | null>(null);
  const { onReady, save } = useSavePicture();
  useEffect(() => {
    let live = true;
    api.energyFlow(entity, year).then((f) => { if (live) { setFlow(f); setError(null); } })
      .catch((e) => live && setError(String(e.message || e)));
    return () => { live = false; };
  }, [entity, year]);
  const option = useCallback(() => (flow ? energyFlowOption(flow) : {}), [flow]);
  if (error) return <div className="card"><h3>Energy flow</h3><p className="error">{error}</p></div>;
  if (!flow || !flow.years.length || !flow.links.length) return null;
  const t = flow.totals;
  const share = t && t.primary_supply ? (100 * ["Hydro", "Geothermal", "Wind", "Solar", "Bioenergy"]
    .reduce((s, g) => s + (t.supply_by_group[g] ?? 0), 0)) / t.primary_supply : null;
  const title = `Energy flow, ${flow.year}`;
  return (
    <div className="card" id="energy-flow">
      <div className="card-head">
        <h3>Where energy comes from and goes <Help note="energyflow" /></h3>
        <button className="link small" title="Save this chart as a picture, with its sources"
          onClick={() => save(`${title}: ${name}`, "Petajoules (PJ), gross calorific value.", [flow.source_id], "energy-flow", String(flow.year), entity)}>Save picture</button>
      </div>
      <div className="chips-row small">
        <label>Year{" "}
          <input type="range" min={flow.years[0]} max={flow.years[flow.years.length - 1]} value={flow.year ?? 0}
            onChange={(e) => setYear(+e.target.value)} aria-label="Year" />
        </label>
        <b>{flow.year}</b>
        <button className="link small" disabled={flow.year === flow.years[flow.years.length - 1]}
          onClick={() => setYear(flow.years[flow.years.length - 1])}>Latest</button>
      </div>
      <EChart option={option} height={460} label={`${title} in ${name}`} onReady={onReady} update="merge" />
      <p className="caption">
        {t ? `Primary energy ${pj(t.primary_supply, 0)}${share != null ? `, ${share.toFixed(0)}% of it renewable` : ""}; `
          + `electricity generated ${pj(t.electricity_generated, 0)}. ` : ""}
        Fuels on the left are what the country produced or imported and kept; exports are left out. Conversion losses are
        the heat that does not become electricity (large for geothermal, which counts at its heat). Source: MBIE energy balance tables.
      </p>
    </div>
  );
}
