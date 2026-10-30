"use client";

import { useCallback, useMemo, useState } from "react";
import EChart from "@/components/EChart";
import type { Indicator } from "@/lib/api";
import { points, useSavePicture, useSeries } from "@/lib/cards";
import { cardLinesOption, type CardLine } from "@/lib/charts";
import { sequentialRamp, seriesColor } from "@/lib/colors";

// Schooling of adults in one country: average years of schooling for women and men
// since 1950 with the Wittgenstein Centre's projection to 2100, and the shares of
// adults by highest level of education (ordered levels, so one light-to-dark ramp).
const YEARS = [
  { sets: [["wic_mys", "All adults"], ["wic_mys_female", "Women"], ["wic_mys_male", "Men"]] },
  { sets: [["hdr_mean_years_schooling", "All adults"], ["hdr_mean_years_schooling_female", "Women"], ["hdr_mean_years_schooling_male", "Men"]] },
];
const LEVELS: { label: string; ids: string[] }[] = [
  { label: "Less than primary", ids: ["wic_edu_none", "wic_edu_incomplete_primary"] },
  { label: "Primary", ids: ["wic_edu_primary"] },
  { label: "Lower secondary", ids: ["wic_edu_lower_secondary"] },
  { label: "Upper secondary", ids: ["wic_edu_upper_secondary"] },
  { label: "Short post-secondary", ids: ["wic_edu_short_post_secondary"] },
  { label: "Bachelor's", ids: ["wic_edu_bachelor"] },
  { label: "Master's or higher", ids: ["wic_edu_master"] },
];
const ALL = [...YEARS.flatMap((y) => y.sets.map((s) => s[0])), ...LEVELS.flatMap((l) => l.ids)];
type View = "years" | "levels";

export default function EducationCard({ entity, name, indicators }: { entity: string; name: string; indicators: Map<string, Indicator> }) {
  const { data, error } = useSeries(entity, ALL, indicators);
  const [pick, setPick] = useState<View>("years");
  const { onReady, save } = useSavePicture();
  const yearsSet = YEARS.find((y) => data?.get(y.sets[0][0])?.length);
  const hasLevels = LEVELS.some((l) => l.ids.some((id) => data?.get(id)?.length));
  const view: View = pick === "levels" && hasLevels ? "levels" : yearsSet ? "years" : "levels";

  const lines: CardLine[] = useMemo(() => {
    if (!data) return [];
    if (view === "years") {
      return (yearsSet?.sets ?? []).filter(([id]) => data.get(id)?.length)
        .map(([id, label], i) => ({ key: id, label, color: seriesColor(i === 0 ? 6 : i === 1 ? 4 : 0), points: points(data.get(id)) }));
    }
    const ramp = sequentialRamp();
    return LEVELS.map((l, i) => {
      const sum = new Map<number, [number, string]>();
      for (const id of l.ids) for (const p of points(data.get(id))) {
        const prev = sum.get(p[0]);
        sum.set(p[0], [(prev?.[0] ?? 0) + p[1], p[2]]);
      }
      return { key: l.label, label: l.label, color: ramp[i], points: [...sum].map(([y, [v, s]]) => [y, v, s] as [number, number, string]).sort((a, b) => a[0] - b[0]) };
    }).filter((l) => l.points.length);
  }, [data, view, yearsSet]);

  const lastEstimate = Math.max(0, ...lines.flatMap((l) => l.points.filter((p) => p[2] !== "P").map((p) => p[0])));
  const hasProjection = lines.some((l) => l.points.some((p) => p[2] === "P"));
  const option = useCallback(() => cardLinesOption(lines, view === "years"
    ? { unit: "years", decimals: 1, refX: hasProjection && lastEstimate ? { value: lastEstimate, label: "Projection →" } : undefined }
    : { unit: "% of people 25+", decimals: 1, stack: true, max: 100 }), [lines, view, hasProjection, lastEstimate]);

  if (!data || (!yearsSet && !hasLevels)) {
    return error ? <div className="card"><h3>Education</h3><p className="error">{error}</p></div> : null;
  }
  const ids = view === "years" ? (yearsSet?.sets ?? []).map((s) => s[0]) : LEVELS.flatMap((l) => l.ids);
  const sources = ids.map((id) => indicators.get(id)?.sources[0]?.source_id);
  const title = view === "years" ? "Average years of schooling, adults 25 and over" : "Highest level of education, adults 25 and over";
  return (
    <div className="card" id="education">
      <div className="card-head">
        <h3>Education</h3>
        {lines.length > 0 && <button className="link small" title="Save this chart as a picture, with its sources"
          onClick={() => save(`${title}: ${name}`, hasProjection ? "Dashed or paler: projection (middle-of-the-road scenario)." : "", sources, "education", view, entity)}>Save picture</button>}
      </div>
      <div className="chips-row small">
        <div className="seg">
          <button className={view === "years" ? "on" : ""} aria-pressed={view === "years"} disabled={!yearsSet} onClick={() => setPick("years")}>Years of schooling</button>
          <button className={view === "levels" ? "on" : ""} aria-pressed={view === "levels"} disabled={!hasLevels} onClick={() => setPick("levels")}>Highest level</button>
        </div>
      </div>
      {error && <p className="error">{error}</p>}
      {lines.length > 0 && <EChart option={option} height={300} label={`${title} in ${name}`} onReady={onReady} />}
      <p className="caption">
        {title}. {hasProjection ? "Projections (dashed lines, paler areas) follow the Wittgenstein Centre's middle-of-the-road scenario. " : ""}
        Sources: {[...new Set(ids.map((id) => indicators.get(id)?.sources[0]?.source_name).filter(Boolean))].join("; ")}.
      </p>
    </div>
  );
}
