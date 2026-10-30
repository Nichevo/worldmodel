"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import EChart from "@/components/EChart";
import { api, type Indicator, type Partners } from "@/lib/api";
import { points, useSavePicture, useSeries } from "@/lib/cards";
import { cardLinesOption, type CardLine } from "@/lib/charts";
import { seriesColor } from "@/lib/colors";
import { formatValue } from "@/lib/format";

// Migration in and out of one country: people born abroad living here against
// people born here living abroad (UN migrant stock), or refugees hosted against
// refugees who fled (UNHCR), with the ten largest countries on each side.
const VIEWS = {
  migrants: {
    label: "Migrants",
    lines: [
      { id: "migrant_stock", label: "Born abroad, living here", color: 0 },
      { id: "emigrant_stock", label: "Born here, living abroad", color: 1 },
    ],
    bilateral: "migrant_stock_by_origin",
    inTitle: "Where immigrants were born", outTitle: "Where emigrants live",
    note: "People living outside the country they were born in, at mid-year (UN migrant stock, every five years).",
  },
  refugees: {
    label: "Refugees",
    lines: [
      { id: "refugees_hosted", label: "Refugees hosted here", color: 0 },
      { id: "refugees_from", label: "Refugees who fled from here", color: 1 },
      { id: "asylum_seekers_hosted", label: "Asylum seekers here", color: 2 },
    ],
    bilateral: "refugees_by_origin",
    inTitle: "Where refugees here fled from", outTitle: "Where refugees from here live",
    note: "Refugees under UNHCR's mandate and asylum seekers, at the end of each year.",
  },
} as const;
type View = keyof typeof VIEWS;
const ALL = Object.values(VIEWS).flatMap((v) => v.lines.map((l) => l.id));

export default function MigrationCard({ entity, name, indicators }: { entity: string; name: string; indicators: Map<string, Indicator> }) {
  const { data, error } = useSeries(entity, ALL, indicators);
  const [pick, setPick] = useState<View | null>(null);
  const { onReady, save } = useSavePicture();
  const has = (v: View) => VIEWS[v].lines.some((l) => data?.get(l.id)?.length);
  const view: View = pick && has(pick) ? pick : has("migrants") ? "migrants" : "refugees";
  const def = VIEWS[view];

  const lines: CardLine[] = useMemo(() => def.lines.filter((l) => data?.get(l.id)?.length)
    .map((l) => ({ key: l.id, label: l.label, color: seriesColor(l.color), points: points(data!.get(l.id)) })), [def, data]);
  const option = useCallback(() => cardLinesOption(lines, { unit: "persons", decimals: 0 }), [lines]);
  const bilateral = indicators.get(def.bilateral)?.available ? def.bilateral : null;

  if (!data || (!has("migrants") && !has("refugees"))) {
    return error ? <div className="card"><h3>Migration in and out</h3><p className="error">{error}</p></div> : null;
  }
  const sources = def.lines.map((l) => indicators.get(l.id)?.sources[0]?.source_id);
  return (
    <div className="card" id="migration">
      <div className="card-head">
        <h3>Migration in and out</h3>
        {lines.length > 0 && <button className="link small" title="Save this chart as a picture, with its sources"
          onClick={() => save(`${def.label} in and out: ${name}`, def.note, sources, "migration", view, entity)}>Save picture</button>}
      </div>
      <div className="chips-row small">
        <div className="seg">
          {(Object.keys(VIEWS) as View[]).map((v) => (
            <button key={v} className={view === v ? "on" : ""} aria-pressed={view === v} disabled={!has(v)} onClick={() => setPick(v)}>{VIEWS[v].label}</button>
          ))}
        </div>
      </div>
      {error && <p className="error">{error}</p>}
      {lines.length > 0 && <EChart option={option} height={260} label={`${def.label} in and out of ${name}`} onReady={onReady} />}
      {bilateral && (
        <div className="grid two partners">
          <PartnerList indicator={bilateral} entity={entity} direction="in" title={def.inTitle} />
          <PartnerList indicator={bilateral} entity={entity} direction="out" title={def.outTitle} />
        </div>
      )}
      <p className="caption">{def.note} Net migration (arrivals minus departures each year) is in the UN WPP chart below.</p>
    </div>
  );
}

// The ten largest partner countries as a list with bars, for the latest year (or one picked).
function PartnerList({ indicator, entity, direction, title }: { indicator: string; entity: string; direction: "in" | "out"; title: string }) {
  const [year, setYear] = useState<number | undefined>(undefined);
  const [res, setRes] = useState<Partners | null>(null);
  useEffect(() => { setYear(undefined); }, [entity, indicator]);
  useEffect(() => {
    let live = true;
    api.partners(indicator, entity, direction, year).then((r) => live && setRes(r)).catch(() => live && setRes(null));
    return () => { live = false; };
  }, [indicator, entity, direction, year]);
  if (!res || !res.rows.length) return <div><h4>{title}</h4><p className="muted small">No figures by country.</p></div>;
  const top = res.rows[0].value;
  const shown = res.rows.reduce((t, r) => t + r.value, 0);
  return (
    <div>
      <div className="card-head">
        <h4>{title}</h4>
        {res.years.length > 1 && (
          <select className="small" value={res.year ?? ""} onChange={(e) => setYear(+e.target.value)} aria-label={`${title}: year`}>
            {[...res.years].reverse().map((y) => <option key={y} value={y}>{y}</option>)}
          </select>
        )}
      </div>
      <ol className="bar-list">
        {res.rows.map((r) => (
          <li key={r.entity_id}>
            <Link href={`/entity/${r.entity_id}`}>{r.name}</Link>
            <span className="bar"><i style={{ width: `${(100 * r.value) / top}%` }} /></span>
            <span className="num">{formatValue(r.value, "persons", 0)}</span>
          </li>
        ))}
      </ol>
      {res.total ? <p className="caption">These {res.rows.length} make up {Math.round((100 * shown) / res.total)}% of {formatValue(res.total, "persons", 0)} in {res.year}.</p> : null}
    </div>
  );
}
