"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import CardAsk from "@/components/CardAsk";
import { openAsk } from "@/lib/ai";
import { type Card, diseaseApi, fmt, LEVEL_TONE, sparkPoints, trendWord, weekLabel } from "@/lib/disease";

// A country's infections now: one tile per weekly measure it has had in the last four months
// (flu, COVID, RSV…), each against the usual for the week, with the last half year as a small
// line; then the latest yearly measles and whooping cough counts and how they rank since 2000.
export default function DiseaseCard({ entity, name }: { entity: string; name: string }) {
  const [d, setD] = useState<Card | null>(null);
  useEffect(() => {
    let live = true;
    diseaseApi.card(entity).then((x) => live && setD(x)).catch(() => live && setD(null));
    return () => { live = false; };
  }, [entity]);
  if (!d || (!d.tiles.length && !d.yearly.length)) return null;
  return (
    <div className="card" id="disease">
      <div className="card-head"><h3>Disease now</h3>
        <span>
          <CardAsk onAsk={() => openAsk({ title: `Disease now: ${name}`, entity, parts: [{ key: "data", kind: "data", label: "Latest weeks",
            text: [...d.tiles.map((t) => `${t.measure.label}: ${fmt(t.value, t.measure)} in the week of ${t.week} (usual ${fmt(t.usual, t.measure)}, ${d.levels[t.level]}, ${t.trend ?? ""})`),
              ...d.yearly.map((y) => `${y.label} ${y.year}: ${Math.round(y.value).toLocaleString()} (#${y.rank} of ${y.of} years since ${y.since})`)].join("\n") }] })} />{" "}
          <Link href={`/disease?tab=seasons&country=${entity}`} className="small">Seasons</Link>
        </span>
      </div>
      <div className="disease-tiles">
        {d.tiles.map((t) => (
          <Link key={t.measure.id} href={`/disease?tab=seasons&country=${entity}&measure=${t.measure.id}`} className="disease-tile">
            <span className="small muted">{t.measure.label}</span>
            <b>{fmt(t.value, t.measure)}</b>
            <svg width="120" height="28" aria-hidden><path d={sparkPoints(t.spark, 120, 28)} fill="none" stroke={`var(${LEVEL_TONE[t.level]})`} strokeWidth="1.5" /></svg>
            <span className="small"><span style={{ color: `var(${LEVEL_TONE[t.level]})`, fontWeight: 600 }}>{d.levels[t.level]}</span>
              {t.trend ? `, ${trendWord(t.trend)}` : ""}</span>
            <span className="small muted">Week of {weekLabel(t.week)}{t.usual !== null ? `; usual ${fmt(t.usual, t.measure)}` : ""}</span>
          </Link>
        ))}
      </div>
      {d.yearly.length > 0 && (
        <p className="small" style={{ marginBottom: 0 }}>
          {d.yearly.map((y) => (
            <span key={y.indicator} style={{ marginRight: 16 }}>{y.label} {y.year}: <b>{Math.round(y.value).toLocaleString()}</b>
              {y.of > 1 ? <span className="muted"> (#{y.rank} of {y.of} years since {y.since})</span> : null}</span>
          ))}
          <Link href="/disease?tab=long" className="muted">Long view</Link>
        </p>
      )}
    </div>
  );
}
