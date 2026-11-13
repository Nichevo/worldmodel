"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import type { EChartsOption, SeriesOption } from "echarts";
import CardAsk from "@/components/CardAsk";
import EChart from "@/components/EChart";
import { useKeys } from "@/components/PageLook";
import { openAsk } from "@/lib/ai";
import { api, type EntityReligion, type RelPoint } from "@/lib/api";
import { cardLinesOption } from "@/lib/charts";
import { useEntityNames } from "@/lib/flags";
import { religionLines, SOURCE_NOTE } from "@/lib/people";

// One country's religious mix over time as stacked bands, with the share written inside each
// big band at the first and last year, a finding title (which group is largest, and since
// when), and chips to switch to the other key countries or the world.

const PREFER = ["pew_religion", "cow_religion", "cia_factbook"];
const rank = (id: string) => (PREFER.includes(id) ? PREFER.indexOf(id) : 99);
const pick = (sources: { id: string; points: RelPoint[] }[]) =>
  [...sources].sort((a, b) => rank(a.id) - rank(b.id)).find((s) => s.points.length > 1) ?? sources[0];

function finding(points: RelPoint[], names: Record<string, string>, place: string): string {
  const est = points.filter((p) => !p.projected && Object.keys(p.shares).length);
  if (!est.length) return "";
  const top = (p: RelPoint) => Object.entries(p.shares).sort((a, b) => b[1] - a[1])[0];
  const [g, v] = top(est[est.length - 1]);
  let i = est.length - 1;
  while (i > 0 && top(est[i - 1])[0] === g) i--;
  const name = names[g] ?? g;
  const q = name === "No religion" ? "'No religion'" : name;
  const last = est[est.length - 1].year;
  return i > 0 ? `${q} became ${place}'s largest group by ${est[i].year}; now ${Math.round(v)}% (${last})`
    : `${q} is ${place}'s largest group: ${Math.round(v)}% in ${last}`;
}

export default function ReligionCountry({ world, groups }: { world: Record<string, RelPoint[]>; groups: { id: string; name: string }[] }) {
  const keys = useKeys().split(",").filter(Boolean);
  const nameOf = useEntityNames();
  const [who, setWho] = useState(keys[0] ?? "NZL");
  const [d, setD] = useState<EntityReligion | null>(null);
  useEffect(() => {
    if (who === "world") { setD(null); return; }
    let live = true;
    api.entityReligion(who).then((x) => live && setD(x)).catch(() => live && setD(null));
    return () => { live = false; };
  }, [who]);
  const names = useMemo(() => Object.fromEntries(groups.map((g) => [g.id, g.name])), [groups]);
  const src = useMemo(() => {
    if (who === "world") return pick(Object.entries(world).map(([id, points]) => ({ id, points })));
    return d?.sources.length ? pick(d.sources) : undefined;
  }, [who, world, d]);
  const place = who === "world" ? "the world" : nameOf(who);
  const lines = useMemo(() => (src ? religionLines(src.points, groups) : []), [src, groups]);
  const option = useCallback((): EChartsOption => {
    const o = cardLinesOption(lines, { unit: "%", decimals: 1, stack: true, max: 100 });
    const est = (src?.points ?? []).filter((p) => !p.projected);
    if (est.length < 2) return o;
    // Labels in the middle of each band big enough to hold one, at the first and last year.
    const labels: { value: [number, number]; label: object }[] = [];
    for (const [p, side] of [[est[0], "right"], [est[est.length - 1], "left"]] as const) {
      let base = 0;
      for (const g of groups) {
        const v = p.shares[g.id] ?? 0;
        if (v >= 9) labels.push({ value: [p.year, base + v / 2], label: { position: side, formatter: `${names[g.id]} ${Math.round(v)}%${side === "right" ? ` (${p.year})` : ""}` } });
        base += v;
      }
    }
    const tag: SeriesOption = { type: "scatter", id: "band-labels", data: labels, symbolSize: 0, silent: true, tooltip: { show: false }, z: 10,
      label: { show: true, color: "#fff", fontSize: 11, fontWeight: 600, textBorderColor: "rgba(0,0,0,.35)", textBorderWidth: 2 } };
    return { ...o, series: [...(o.series as SeriesOption[]), tag] };
  }, [lines, src, groups, names]);
  const title = src ? finding(src.points, names, place) : "";
  return (
    <div className="card">
      <div className="card-head"><h3 className="finding">{title || `Religion in ${place}`}</h3>
        <CardAsk onAsk={() => openAsk({ title: `Religion in ${place}`, parts: [{ key: who, kind: "data", label: `Shares by year (${src?.id ?? ""})`,
          text: (src?.points ?? []).map((p) => `${p.year}${p.projected ? " (projected)" : ""}: ${Object.entries(p.shares).map(([g, v]) => `${names[g] ?? g} ${v.toFixed(1)}%`).join(", ")}`).join("\n") }] })} />
      </div>
      <div className="chips-row small" role="group" aria-label="Country">
        <span className="muted">Compare with:</span>
        {[...keys, "world"].map((e) => (
          <button key={e} className={`chip-btn${who === e ? " on" : ""}`} aria-pressed={who === e} onClick={() => setWho(e)}>{e === "world" ? "World" : nameOf(e)}</button>
        ))}
      </div>
      {lines.length ? <EChart option={option} height={300} label={`Religion in ${place}`} />
        : <p className="muted">No religion figures for {place} yet.</p>}
      <p className="caption">{SOURCE_NOTE[src?.id ?? ""] ?? ""} Shares of all people; each band is one group.</p>
    </div>
  );
}
