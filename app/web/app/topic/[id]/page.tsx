"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import ChartCard from "@/components/ChartCard";
import IndicatorMap from "@/components/IndicatorMap";
import { api, type Indicator, type Topic } from "@/lib/api";
import { logHistory } from "@/lib/history";
import { KEY_COUNTRIES, WORLD } from "@/lib/topics";

// A topic: its introduction, a map of one of its indicators, and a chart of each
// indicator for the key countries against the world, each linked to its own page.
export default function TopicPage() {
  const { id } = useParams<{ id: string }>();
  const [topic, setTopic] = useState<Topic | null>(null);
  const [inds, setInds] = useState<Map<string, Indicator>>(new Map());
  const [mapInd, setMapInd] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    setTopic(null); setError(null);
    api.topic(id).then((t) => {
      setTopic(t);
      setMapInd(t.indicators.includes(t.map) ? t.map : t.indicators[0] ?? null);
      logHistory({ kind: "page", title: `Topic: ${t.name}`, url: `/topic/${id}`, detail: "topic" });
    }).catch((e) => setError(String(e.message || e)));
    api.indicators().then((l) => setInds(new Map(l.map((i) => [i.indicator_id, i])))).catch(() => {});
  }, [id]);
  if (error) return <p className="error">{error}</p>;
  if (!topic) return <p className="muted">Loading…</p>;
  const mapped = mapInd ? inds.get(mapInd) : undefined;
  return (
    <div className="grid">
      <div>
        <p className="small muted" style={{ margin: 0 }}><Link href="/topics">Topics</Link></p>
        <h1 style={{ marginBottom: 4 }}>{topic.name}</h1>
        <p className="ink-2" style={{ marginTop: 0, maxWidth: 820 }}>{topic.intro}</p>
        {topic.missing.length > 0 && (
          <p className="small warn-note">
            Not loaded yet: {topic.missing.map((m) => inds.get(m)?.name ?? m).join(", ")}.
            {id === "ai" ? <> Eurostat and the Anthropic Economic Index come with <code>.\refresh.bat</code>; Microsoft&apos;s
              AI Diffusion table is loaded by hand with <code>.\load.bat ms_ai_diffusion &lt;file&gt;</code>.</> : <> Run <code>.\refresh.bat</code> to load them.</>}
          </p>
        )}
      </div>
      {mapped && (
        <section className="card">
          <div className="card-head">
            <h3><Link href={`/indicator/${mapped.indicator_id}`}>{mapped.name}</Link></h3>
            <select className="small" value={mapInd ?? ""} onChange={(e) => setMapInd(e.target.value)} aria-label="Indicator on the map">
              {topic.indicators.map((i) => <option key={i} value={i}>{inds.get(i)?.name ?? i}</option>)}
            </select>
          </div>
          <IndicatorMap indicator={mapped} />
        </section>
      )}
      <div className="grid two">
        {topic.indicators.map((i) => inds.get(i)).filter((i): i is Indicator => !!i).map((i) => (
          <div key={i.indicator_id}>
            <ChartCard indicator={i} entities={[WORLD, ...KEY_COUNTRIES]} />
            <p className="small" style={{ marginTop: -6 }}><Link href={`/indicator/${i.indicator_id}`}>{i.name}: every country, sources and map →</Link></p>
          </div>
        ))}
      </div>
    </div>
  );
}
