"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import AskButton from "@/components/AskButton";
import ChartCard from "@/components/ChartCard";
import IndicatorMap from "@/components/IndicatorMap";
import { QualityCard } from "@/components/Quality";
import { api, type Indicator, type IndicatorQuality, type Ranking, type Topic } from "@/lib/api";
import { formatValue } from "@/lib/format";
import { logHistory } from "@/lib/history";
import { KEY_COUNTRIES, WORLD } from "@/lib/topics";

// One indicator: what it is, a map, the key countries against the world (with the
// Forecast button), every country ranked, and where the figures come from.
export default function IndicatorPage() {
  const { id } = useParams<{ id: string }>();
  const [ind, setInd] = useState<Indicator | null>(null);
  const [ranking, setRanking] = useState<Ranking | null>(null);
  const [topics, setTopics] = useState<Topic[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [show, setShow] = useState<"top" | "bottom" | "all">("top");
  const [q, setQ] = useState("");
  const [year, setYear] = useState<number | null>(null);
  const [quality, setQuality] = useState<IndicatorQuality | undefined>(undefined);

  useEffect(() => {
    setInd(null); setError(null); setYear(null);
    api.indicators().then((list) => {
      const found = list.find((i) => i.indicator_id === id);
      if (!found) { setError(`No indicator called ${id}.`); return; }
      setInd(found);
      logHistory({ kind: "page", title: found.name, url: `/indicator/${id}`, indicator: id, detail: "indicator" });
    }).catch((e) => setError(String(e.message || e)));
    api.topics().then((t) => setTopics(t.filter((x) => x.indicators.includes(id)))).catch(() => {});
    setQuality(undefined);
    api.quality().then((q) => setQuality(q.indicators[id])).catch(() => {});
  }, [id]);
  useEffect(() => {
    setRanking(null);
    api.ranking(id, year ?? undefined).then(setRanking).catch(() => setRanking(null));
  }, [id, year]);

  const rows = useMemo(() => {
    const all = ranking?.rows ?? [];
    if (q) return all.filter((r) => r.name.toLowerCase().includes(q.toLowerCase()));
    return show === "all" ? all : show === "top" ? all.slice(0, 15) : all.slice(-15).reverse();
  }, [ranking, show, q]);
  const keyRanks = (ranking?.rows ?? []).filter((r) => KEY_COUNTRIES.some((k) => k.id === r.entity_id));

  if (error) return <p className="error">{error}</p>;
  if (!ind) return <p className="muted">Loading…</p>;
  const fmt = (v: number | null) => (v === null ? "–" : formatValue(v, ind.unit, ind.decimals));
  const years = ind.first_year && ind.last_estimate_year ? Array.from({ length: ind.last_estimate_year - ind.first_year + 1 }, (_, i) => ind.last_estimate_year! - i) : [];
  return (
    <div className="grid">
      <div>
        <p className="small muted" style={{ margin: 0 }}>
          <Link href="/indicators">Indicators</Link> · {ind.domain}
          {topics.map((t) => <span key={t.id}> · <Link href={`/topic/${t.id}`}>{t.name}</Link></span>)}
        </p>
        <div className="title-row">
          <h1 style={{ marginBottom: 4 }}>{ind.name}</h1>
          <AskButton title={ind.name} indicator={ind.indicator_id} parts={() => [
            { key: "data", kind: "data", label: `Every country${ranking?.year ? `, ${ranking.year}` : ""} (${ind.unit})`,
              text: [`Rank,Country,Value (${ind.unit}),Ten years before`, ...(ranking?.rows ?? []).map((r) =>
                `${r.rank},"${r.name}",${+r.value.toPrecision(6)},${r.ten_years_before === null ? "" : +r.ten_years_before.toPrecision(6)}`),
                ...(ranking?.world ? [`,World,${+ranking.world.value.toPrecision(6)},`] : [])].join("\n") },
            { key: "description", kind: "description", label: `What "${ind.name}" measures`,
              text: `${ind.description || ""}\nUnit: ${ind.unit}. Years ${ind.first_year ?? "?"}–${ind.last_year ?? "?"}. Sources: ${ind.sources.map((x) => x.source_name ?? x.source_id).join("; ")}.` },
          ]} />
        </div>
        <p className="ink-2" style={{ marginTop: 0 }}>{ind.description || "No description in the catalogue yet."}</p>
        <div className="ind-facts">
          <div><b>Unit</b>{ind.unit || "–"}</div>
          <div><b>Years</b>{ind.first_year ?? "–"}–{ind.last_year ?? "–"}{ind.last_year && ind.last_estimate_year && ind.last_year > ind.last_estimate_year ? ` (projections from ${ind.last_estimate_year + 1})` : ""}</div>
          <div><b>Countries</b>{ind.countries}</div>
          <div><b>Regions and blocs</b>{!ind.agg_method || ind.agg_method === "none" ? "As published" : `From member countries (${ind.agg_method.replace("_", " ")})`}</div>
          <div><b>In menus</b>{ind.enabled ? "Switched on" : <>Switched off (<Link href={`/indicators?ind=${ind.indicator_id}`}>change</Link>)</>}</div>
        </div>
      </div>
      <div className="grid two">
        <section className="card">
          <div className="card-head">
            <h3>Map{ranking?.year ? `, ${ranking.year}` : ""}</h3>
            {years.length > 0 && (
              <select className="small" value={ranking?.year ?? ""} onChange={(e) => setYear(+e.target.value)} aria-label="Year">
                {years.map((y) => <option key={y} value={y}>{y}</option>)}
              </select>
            )}
          </div>
          <IndicatorMap indicator={ind} ranking={ranking} />
          <p className="caption">Click a country for its page.{ranking?.world ? ` World: ${fmt(ranking.world.value)}.` : ""}</p>
        </section>
        <ChartCard indicator={ind} entities={[WORLD, ...KEY_COUNTRIES]} height={360} />
      </div>
      <div className="grid two">
        <section className="card">
          <div className="card-head">
            <h3>Every country{ranking?.year ? `, ${ranking.year}` : ""}</h3>
            <div className="seg small" role="group" aria-label="Which countries">
              {(["top", "bottom", "all"] as const).map((k) => (
                <button key={k} className={show === k && !q ? "on" : ""} onClick={() => { setShow(k); setQ(""); }}>
                  {k === "top" ? "Highest 15" : k === "bottom" ? "Lowest 15" : "All"}</button>
              ))}
            </div>
          </div>
          <input type="search" placeholder="Find a country" value={q} onChange={(e) => setQ(e.target.value)} style={{ marginBottom: 8 }} />
          <div style={{ maxHeight: 420, overflow: "auto" }}>
            <table className="summary-table rank-table">
              <thead><tr><th className="num">Rank</th><th>Country</th><th className="num">{ind.unit || "Value"}</th><th className="num">10 years before</th></tr></thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.entity_id} className={KEY_COUNTRIES.some((k) => k.id === r.entity_id) ? "selected" : ""}>
                    <td className="num">{r.rank}</td>
                    <td><Link href={`/entity/${r.entity_id}`}>{r.name}</Link>{r.status === "P" ? <span className="small muted"> (projection)</span> : null}</td>
                    <td className="num">{fmt(r.value)}</td>
                    <td className="num muted">{fmt(r.ten_years_before)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {keyRanks.length > 0 && (
            <p className="caption">{keyRanks.map((r) => `${r.name} ${r.rank} of ${ranking!.rows.length}`).join("; ")}.</p>
          )}
        </section>
        <section className="card">
          <h3>Where the figures come from</h3>
          <ul className="plain">
            {ind.sources.map((s) => (
              <li key={s.source_id} style={{ marginBottom: 8 }}>
                <b>{s.source_name ?? s.source_id}</b>{s.rank === 1 ? " (used first)" : ""}
                <div className="small muted">Series {s.series}{s.licence ? ` · ${s.licence}` : ""}</div>
                {s.notes && <div className="small ink-2">{s.notes}</div>}
              </li>
            ))}
          </ul>
          <p className="small muted" style={{ marginBottom: 0 }}>
            Where two sources have the same figure, the first is shown and the others can be compared on the{" "}
            <Link href="/sources">Sources</Link> page. Forecasts and their track records are on the <Link href="/forecasts">Forecasts</Link> page.
          </p>
        </section>
        {quality && <QualityCard key={id} id={id} q={quality} />}
      </div>
    </div>
  );
}
