"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import EChart from "@/components/EChart";
import { api, type Indicator, type SeriesRow } from "@/lib/api";
import { lineOption, type Named } from "@/lib/charts";
import { entityColors, shortValue } from "@/lib/look";

// One small chart per country on the same scale, instead of a tangle of lines:
// the shapes compare at a glance, and each chart's latest value sits in its title.
export default function SmallMultiples({ indicator, entities }: { indicator: Indicator; entities: Named[] }) {
  const [rows, setRows] = useState<SeriesRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const ids = entities.map((e) => e.id).join(",");
  useEffect(() => {
    setRows(null);
    api.series(indicator.indicator_id, ids.split(",")).then(setRows).catch((e) => setError(String(e.message || e)));
  }, [indicator.indicator_id, ids]);
  const colours = entityColors(entities.map((e) => e.id));
  const range = useMemo(() => {
    const vs = (rows ?? []).map((r) => r.value), ys = (rows ?? []).map((r) => +r.period);
    if (!vs.length) return null;
    const lo = Math.min(...vs), hi = Math.max(...vs), pad = (hi - lo) * 0.06 || 1;
    return { min: lo >= 0 && lo - pad < 0 ? 0 : lo - pad, max: hi + pad, x0: Math.min(...ys), x1: Math.max(...ys) };
  }, [rows]);
  if (error) return <p className="error">{error}</p>;
  if (!rows) return <p className="muted small">Loading…</p>;
  return (
    <div className="multiples">
      {entities.map((e, i) => {
        const mine = rows.filter((r) => r.entity_id === e.id);
        const last = mine.filter((r) => r.status === "E").at(-1);
        return (
          <div className="card mini" key={e.id}>
            <h4><Link href={`/entity/${e.id}`} style={{ color: colours[i] }}>{e.name}</Link>
              {last && <span className="num">{shortValue(last.value, indicator.unit, indicator.decimals)} <span className="muted small">{last.period}</span></span>}</h4>
            {mine.length ? <Mini rows={mine} e={e} color={colours[i]} indicator={indicator} range={range} /> : <p className="muted small">No figures.</p>}
          </div>
        );
      })}
    </div>
  );
}

function Mini({ rows, e, color, indicator, range }: { rows: SeriesRow[]; e: Named; color: string; indicator: Indicator;
  range: { min: number; max: number; x0: number; x1: number } | null }) {
  const option = useCallback(() => {
    const o = lineOption(rows, [e], indicator.unit, indicator.decimals);
    const series = (o.series as { color?: string; endLabel?: unknown; markArea?: unknown }[]).map((s) => ({ ...s, color, endLabel: undefined, areaStyle: { opacity: 0.08 } }));
    return { ...o, series, legend: undefined, grid: { left: 4, right: 10, top: 8, bottom: 4, containLabel: true },
      yAxis: { ...(o.yAxis as object), min: range?.min, max: range?.max, scale: false, name: "",
        axisLabel: { ...((o.yAxis as { axisLabel?: object }).axisLabel ?? {}), showMinLabel: false, showMaxLabel: false, fontSize: 10 } },
      xAxis: { ...(o.xAxis as object), min: range?.x0, max: range?.x1, axisLabel: { ...((o.xAxis as { axisLabel?: object }).axisLabel ?? {}), fontSize: 10 } } } as typeof o;
  }, [rows, e, color, indicator, range]);
  return <EChart option={option} height={150} label={`${indicator.name}: ${e.name}`} />;
}
