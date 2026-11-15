"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import CardAsk from "@/components/CardAsk";
import WorldMap, { type MapPoint } from "@/components/WorldMap";
import { openAsk } from "@/lib/ai";
import { api, type CityScoreRow, type CityScores } from "@/lib/api";
import { shortUnit, stressColor } from "@/lib/cities";
import { formatValue } from "@/lib/format";

// Cities > City stress: our own score from traffic, cost of living, health care, crime and
// air, set up in contract city_scores.yaml so parts can be added later. A ranked table with
// each part's figure (cell tinted by its 0-10 place), a map, and Remitly's published scores.
export default function CityStress() {
  const [year, setYear] = useState<number | null>(null);
  const [d, setD] = useState<CityScores | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [q, setQ] = useState("");
  const [sort, setSort] = useState<string>("score");
  const [flip, setFlip] = useState(false);
  useEffect(() => {
    let live = true;
    setError(null);
    api.cityScores("stress", year ?? undefined).then((x) => live && setD(x)).catch((e) => live && setError(String(e.message || e)));
    return () => { live = false; };
  }, [year]);

  const shown = useMemo(() => {
    if (!d) return [];
    const words = q.trim().toLowerCase();
    const list = d.rows.filter((r) => !words || `${r.name} ${r.country ?? r.country_id}`.toLowerCase().includes(words));
    const val = (r: CityScoreRow) => (sort === "score" ? r.score : r.parts[sort]?.points ?? -1);
    return [...list].sort((a, b) => (flip ? val(a) - val(b) : val(b) - val(a)) || a.rank - b.rank);
  }, [d, q, sort, flip]);
  const points: MapPoint[] = useMemo(() => (d?.rows ?? []).filter((r) => r.lat !== null && r.lon !== null).map((r) => ({
    id: r.city_id, name: r.name, lng: r.lon as number, lat: r.lat as number, size: 1, color: stressColor(r.score),
    text: `City stress ${r.score.toFixed(1)} of 10 · ${r.rank} of ${d!.rows.length}`,
  })), [d]);

  if (error) return <p className="error">{error}</p>;
  if (!d) return <p className="muted">Loading…</p>;
  const by = (k: string) => { if (sort === k) setFlip(!flip); else { setSort(k); setFlip(false); } };
  const arrow = (k: string) => (sort === k ? (flip ? " ▲" : " ▼") : "");
  const table = () => [
    ["Rank", "City", "Country", "City stress (0-10)", ...d.parts.map((p) => `${p.name} (${p.unit})`)].join(","),
    ...d.rows.map((r) => [r.rank, `"${r.name}"`, `"${r.country ?? r.country_id}"`, r.score,
      ...d.parts.map((p) => r.parts[p.indicator] ? `${r.parts[p.indicator].value} (${r.parts[p.indicator].year})` : "")].join(",")),
  ].join("\n");
  const ask = () => openAsk({ title: `${d.name}${year ? ` in ${year}` : ""}`, parts: [
    { key: "description", kind: "description", label: "How the score is made", text: `${d.about}\n${d.how}` },
    { key: "data", kind: "data", label: "Cities, most stressful first", text: table() }] });
  const top = d.rows.slice(0, 3).map((r) => r.name).join(", ");
  const calm = d.rows.slice(-3).reverse().map((r) => r.name).join(", ");

  return (
    <>
      <p className="ink-2" style={{ marginTop: 0, maxWidth: 900 }}>{d.about}</p>
      {d.rows.length > 2 && <p className="finding" style={{ margin: 0 }}>Most stressful: {top}. Calmest: {calm}.</p>}
      <div className="chips-row small">
        <select value={year ?? ""} onChange={(e) => setYear(e.target.value ? Number(e.target.value) : null)} aria-label="Year">
          <option value="">Latest figures</option>
          {[...d.years].reverse().map((y) => <option key={y} value={y}>Figures up to {y}</option>)}
        </select>
        <input type="search" placeholder="Find a city or country" value={q} onChange={(e) => setQ(e.target.value)} style={{ width: 200 }} />
        <span className="muted">{d.rows.length} cities with {d.min_parts} or more of the {d.parts.length} parts</span>
      </div>
      {d.missing_parts.length > 0 && (
        <p className="small ink-2">Not loaded yet: {d.missing_parts.join(", ")}. The Numbeo pages and the TomTom ranking are saved by hand
          (see <Link href="/data">Data</Link>, &quot;How each source is fetched&quot;); the WHO air file comes with refresh.bat.</p>)}
      {d.note ? <p className="ink-2">{d.note}</p> : (
        <>
          <section className="card stress-card">
            <div className="card-head"><h3>{d.name}{year ? `, figures up to ${year}` : ""}</h3><CardAsk onAsk={ask} /></div>
            <div className="stress-scroll">
              <table className="summary-table city-table stress-table">
                <thead><tr>
                  <th className="num">#</th><th>City</th>
                  <th className="num sortable" onClick={() => by("score")} title="Click to sort">Score{arrow("score")}</th>
                  {d.parts.map((p) => (
                    <th key={p.indicator} className="num sortable" onClick={() => by(p.indicator)}
                      title={`${p.full_name}: ${p.description} ${p.worse_when === "higher" ? "Higher" : "Lower"} is more stressful. ${p.cities} cities have it. Click to sort.`}>
                      {p.name}{arrow(p.indicator)}<br /><span className="muted small">{shortUnit(p.unit)}</span></th>))}
                </tr></thead>
                <tbody>{shown.map((r) => (
                  <tr key={r.city_id}>
                    <td className="num muted">{r.rank}</td>
                    <td className="name"><Link href={`/city/${r.city_id}`}>{r.name}</Link> <span className="small muted">{r.country ?? r.country_id}</span></td>
                    <td className="num"><span className="stress-score" style={{ background: stressColor(r.score) }}>{r.score.toFixed(1)}</span></td>
                    {d.parts.map((p) => {
                      const v = r.parts[p.indicator];
                      return v ? (
                        <td key={p.indicator} className="num" title={`${formatValue(v.value, "", p.decimals)} ${p.unit} (${v.year}); ${v.points.toFixed(1)} of 10 among ${p.cities} cities`}>
                          <i className="stress-dot" style={{ background: stressColor(v.points) }} />{formatValue(v.value, "", p.decimals)}</td>
                      ) : <td key={p.indicator} className="num muted">–</td>;
                    })}
                  </tr>))}</tbody>
              </table>
              {!shown.length && <p className="muted small">No city matches.</p>}
            </div>
            <p className="caption">{d.how} The dot by each figure shows its place among the cities (green calm, red stressful); hover for the year.
              To add a part, it goes in contract city_scores.yaml.</p>
          </section>
          <section className="card">
            <div className="city-map"><WorldMap fill values={[]} unit="" decimals={0} diverging={false} onPick={() => {}} points={points} /></div>
            <p className="caption">Each city coloured by its score: green calm, red most stressful. Click a dot for the city page. Also a layer on the Map (City stress).</p>
          </section>
        </>)}
      {d.published && (
        <section className="card">
          <div className="card-head"><h3>Compared with Remitly&apos;s published scores</h3>
            <CardAsk onAsk={() => openAsk({ title: "City stress: ours and Remitly's", parts: [
              { key: "description", kind: "description", label: "About Remitly's study", text: d.published!.note },
              { key: "data", kind: "data", label: "Scores", text: d.published!.cities.map((c) => `${c.name}: Remitly ${c.score}; ours ${c.ours ?? "not scored"}`).join("\n") }] })} /></div>
          <table className="summary-table small">
            <thead><tr><th>City</th><th className="num">Remitly (Oct 2025)</th><th className="num">Ours</th><th className="num">Our rank</th></tr></thead>
            <tbody>{d.published.cities.map((c) => (
              <tr key={c.name}><td>{c.city_id ? <Link href={`/city/${c.city_id}`}>{c.name}</Link> : c.name}</td>
                <td className="num">{c.score.toFixed(2)}</td><td className="num">{c.ours !== null ? c.ours.toFixed(1) : "–"}</td>
                <td className="num">{c.our_rank !== null ? `${c.our_rank} of ${d.rows.length}` : "–"}</td></tr>))}</tbody>
          </table>
          <p className="caption">{d.published.note} <a href={d.published.url} target="_blank" rel="noreferrer">{d.published.source}</a>.
            Both run 0 to 10, but theirs uses IQAir for air and its own weights, so expect the order to agree more than the numbers.</p>
        </section>)}
    </>
  );
}
