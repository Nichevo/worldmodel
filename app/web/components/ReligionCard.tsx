"use client";

import CardAsk from "@/components/CardAsk";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import EChart from "@/components/EChart";
import { api, type EntityReligion } from "@/lib/api";
import { useSavePicture } from "@/lib/cards";
import { cardLinesOption } from "@/lib/charts";
import { religionLines, SOURCE_NOTE } from "@/lib/people";

// A country's religious mix over time, one source at a time (they count differently, so
// they are never mixed on one chart): Pew with projections, Correlates of War from 1945,
// and the CIA Factbook's own line in each edition.
export default function ReligionCard({ entity, name }: { entity: string; name: string }) {
  const [d, setD] = useState<EntityReligion | null>(null);
  const [pick, setPick] = useState<string | null>(null);
  const { onReady, save, ask } = useSavePicture();
  useEffect(() => {
    let live = true;
    api.entityReligion(entity).then((x) => live && setD(x)).catch(() => live && setD(null));
    return () => { live = false; };
  }, [entity]);
  const src = d?.sources.find((s) => s.id === pick) ?? d?.sources[0];
  const lines = useMemo(() => (src && d ? religionLines(src.points, d.groups) : []), [src, d]);
  const option = useCallback(() => cardLinesOption(lines, { unit: "%", decimals: 1, stack: true, max: 100 }), [lines]);
  if (!d || !src || !lines.length) return null;
  const title = `Religion: ${name} (${src.name})`;
  const note = SOURCE_NOTE[src.id] ?? src.name;
  const last = src.points.filter((p) => !p.projected).at(-1);
  return (
    <div className="card" id="religion">
      <div className="card-head">
        <h3>Religion</h3>
        <CardAsk onAsk={() => ask(title, note, [src.id], entity)} />
        <button className="link small" onClick={() => save(title, note, [src.id], "religion", src.id, entity)}>Save picture</button>
      </div>
      {d.sources.length > 1 && (
        <div className="seg small" role="group" aria-label="Source">
          {d.sources.map((s) => <button key={s.id} className={s === src ? "on" : ""} aria-pressed={s === src} onClick={() => setPick(s.id)}>{s.name}</button>)}
        </div>
      )}
      <EChart option={option} height={260} label={title} onReady={onReady} />
      {src.id === "cia_factbook" && last?.text && <p className="small"><span className="muted">{last.edition} edition:</span> {last.text}</p>}
      <p className="caption">{note} Sources count religion differently (censuses ask, surveys sample, models estimate), so switch between them rather than comparing across. <Link href="/religion">Religion around the world</Link></p>
    </div>
  );
}
