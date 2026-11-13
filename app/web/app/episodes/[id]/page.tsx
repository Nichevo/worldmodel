"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import CardAsk from "@/components/CardAsk";
import EChart from "@/components/EChart";
import Flag from "@/components/Flag";
import WorldMap from "@/components/WorldMap";
import { openAsk } from "@/lib/ai";
import { useSavePicture } from "@/lib/cards";
import { type Episode, type EpisodeChart, cyclesApi, episodeOption, fmt1 } from "@/lib/cycles";
import { logHistory } from "@/lib/history";

// One big episode: what happened when, the key charts with the episode shaded, who was hit,
// figures before, during and after, and does today look like the run-up.
export default function EpisodePage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const [d, setD] = useState<Episode | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let live = true;
    setD(null);
    cyclesApi.episode(id).then((x) => { if (!live) return; setD(x); logHistory({ kind: "page", title: x.episode.title, url: `/episodes/${id}`, detail: "episode" }); })
      .catch((e) => live && setError(String(e)));
    return () => { live = false; };
  }, [id]);
  if (error) return <p className="error">{error}</p>;
  if (!d) return <p className="muted">Loading…</p>;
  const e = d.episode;
  const centre = e.countries;
  const span = e.years[0] === e.years[1] ? `${e.years[0]}` : `${e.years[0]}–${e.years[1]}`;
  return (
    <div className="grid sector-page">
      <p className="small"><Link href="/episodes">Episodes</Link> · {e.kind_name}{e.nz ? " · touches New Zealand" : ""}</p>
      <div className="title-row"><h1>{e.title}, {span}</h1></div>
      <p className="ink-2" style={{ marginTop: 0, maxWidth: 860 }}>{e.summary}</p>
      <p className="small">{e.countries.map((c, i) => <span key={c} className="chip small"><Flag id={c} />{e.country_names[i]}</span>)}
        {" "}Read more: {e.links.map((l, i) => <span key={l.url}>{i ? " · " : ""}<a href={l.url} target="_blank" rel="noreferrer">{l.title}</a></span>)}</p>

      <div className="card">
        <div className="card-head"><h3>Timeline</h3>
          <CardAsk onAsk={() => openAsk({ title: `${e.title}: timeline`, parts: [
            { key: "data", kind: "data", label: "Timeline", text: e.timeline.map((t) => `${t.date}: ${t.text}`).join("\n") },
            { key: "description", kind: "description", label: "Summary", text: e.summary }] })} /></div>
        <ol className="episode-timeline">{e.timeline.map((t) => <li key={t.date + t.text}><b>{t.date}</b> {t.text}</li>)}</ol>
      </div>

      <div className="cards-2">
        {d.charts.map((c) => <EpisodeChartCard key={c.indicator} c={c} d={d} />)}
      </div>

      <div className="card">
        <div className="card-head"><h3>Who was hit: the fall in output</h3>
          <CardAsk onAsk={() => openAsk({ title: `${e.title}: who was hit`, parts: [
            { key: "description", kind: "description", label: "How", text: d.hit_how },
            { key: "data", kind: "data", label: "Fall in output, worst first", text: d.hit.slice(0, 40).map((h) => `${h.name}: ${h.value}%`).join("\n") }] })} /></div>
        {!d.hit.length ? <p className="muted small">No output figures for these years yet.</p> : <>
          <div className="map-box"><WorldMap fill values={d.hit.map((h) => ({ entity_id: h.entity_id, value: h.value, status: "E" }))} unit="%" decimals={1}
            diverging onPick={(iso3) => router.push(`/entity/${iso3}`)} /></div>
          <p className="small">Worst hit: {d.hit.slice(0, 8).map((h, i) => <span key={h.entity_id}>{i ? ", " : ""}<Link href={`/entity/${h.entity_id}`}>{h.name}</Link> {h.value}%</span>)}.
            {" "}{["NZL", "AUS", "GBR", "USA"].map((k) => d.hit.find((h) => h.entity_id === k)).filter(Boolean).map((h) => `${h!.name} ${h!.value}%`).join(", ")}.</p>
        </>}
        <p className="caption">{d.hit_how}</p>
      </div>

      <div className="card">
        <div className="card-head"><h3>Before, during and after</h3>
          <CardAsk onAsk={() => openAsk({ title: `${e.title}: before, during and after`, parts: [
            { key: "data", kind: "data", label: "Averages", text: d.table.map((r) => `${r.name}: ${d.table_measures.map((m) => `${m.name} ${fmt1(r.values[m.id]?.before)} / ${fmt1(r.values[m.id]?.during)} / ${fmt1(r.values[m.id]?.after)}`).join("; ")}`).join("\n") },
            { key: "description", kind: "description", label: "How", text: d.table_how }] })} /></div>
        {!d.table.length ? <p className="muted small">No yearly figures for these years yet{e.years[0] < 1960 ? " (the World Bank series start about 1960)" : ""}.</p> : (
          <div className="ep-scroll"><table className="small summary-table episode-table">
            <thead><tr><th rowSpan={2}>Country</th>{d.table_measures.map((m) => <th key={m.id} colSpan={3}>{m.name} ({m.unit})</th>)}</tr>
              <tr>{d.table_measures.map((m) => ["before", "during", "after"].map((k) => <th key={m.id + k} className="muted">{k}</th>))}</tr></thead>
            <tbody>{d.table.map((r) => (
              <tr key={r.entity} className={r.centre ? "" : "muted-row"}><td><Flag id={r.entity} />{r.name}</td>
                {d.table_measures.map((m) => (["before", "during", "after"] as const).map((k) => <td key={m.id + k} className="num">{fmt1(r.values[m.id]?.[k])}</td>))}</tr>))}</tbody>
          </table></div>)}
        <p className="caption">{d.table_how} The episode&apos;s own countries first; New Zealand, Australia, the UK and the US for comparison.</p>
      </div>

      <LikeToday d={d} />
    </div>
  );
}

function EpisodeChartCard({ c, d }: { c: EpisodeChart; d: Episode }) {
  const e = d.episode;
  const { onReady, save, ask } = useSavePicture();
  const option = useCallback(() => episodeOption(c, e.from, e.to, e.timeline, e.countries), [c, e]);
  const title = `${e.title}: ${c.name}`;
  const note = `${c.unit ? `${c.unit}. ` : ""}Shaded: ${e.start} to ${e.end}. Dotted lines: the timeline.`;
  return (
    <div className="card">
      <div className="card-head"><h3>{c.name}{c.unit ? <span className="small muted"> ({c.unit})</span> : null}</h3>
        <CardAsk onAsk={() => ask(title, note, [])} />
        <button className="link small" onClick={() => save(title, note, [], "episode", e.id, c.indicator)}>Save picture</button></div>
      {c.lines.length ? <EChart option={option} height={260} label={`${c.name} around ${e.title}`} onReady={onReady} />
        : <p className="muted small">No figures loaded for this yet.</p>}
    </div>
  );
}

function LikeToday({ d }: { d: Episode }) {
  const L = d.like;
  const keys = Object.keys(L.today);
  const shown = L.measures.filter((m) => m.id in L.run_up);
  const ask = () => openAsk({ title: `Does today look like the run-up to ${d.episode.title}?`, parts: [
    { key: "description", kind: "description", label: "How", text: L.how },
    { key: "data", kind: "data", label: "Run-up and today", text: shown.map((m) => `${m.name}: run-up ${L.run_up[m.id]}; ${keys.map((k) => `${L.today[k].name} ${L.today[k].values[m.id] ?? "–"}`).join(", ")}`).join("\n") }] });
  return (
    <div className="card">
      <div className="card-head"><h3>Does today look like this?</h3><CardAsk onAsk={ask} /></div>
      {!shown.length ? <p className="muted small">No figures for the run-up ({L.run_up_years[0]}–{L.run_up_years[1]}) to compare with.</p> : <>
        <div className="ep-scroll"><table className="small summary-table">
          <thead><tr><th>Measure</th><th className="num">Run-up {L.run_up_years[0]}–{L.run_up_years[1]}</th>
            {keys.map((k) => <th key={k} className="num"><Flag id={k} />{L.today[k].name} {L.today[k].years[0]}–{L.today[k].years[1]}</th>)}</tr></thead>
          <tbody>{shown.map((m) => (
            <tr key={m.id}><td>{m.name} <span className="muted">({m.unit})</span></td><td className="num"><b>{L.run_up[m.id]}</b></td>
              {keys.map((k) => {
                const v = L.today[k].values[m.id];
                const close = L.today[k].close.includes(m.id);
                return <td key={k} className={`num${close ? " close-cell" : ""}`} title={close ? `Within ${m.close_within} of the run-up` : undefined}>{v ?? "–"}</td>;
              })}</tr>))}
            <tr><td><b>Likeness</b></td><td />{keys.map((k) => <td key={k} className="num"><b>{L.today[k].likeness ?? "–"}</b>{L.today[k].likeness !== null && <span className="muted"> /100</span>}</td>)}</tr>
          </tbody>
        </table></div>
        {L.similar.length > 0 && <p className="small">Episodes with the most similar run-up: {L.similar.map((s, i) => (
          <span key={s.id}>{i ? ", " : ""}<Link href={`/episodes/${s.id}`}>{s.title}</Link> ({s.likeness})</span>))}.</p>}
      </>}
      <p className="caption">The run-up is the three years before the start, averaged over the episode&apos;s countries; today is each country&apos;s last three
        years. Shaded cells are close to the run-up. {L.how}</p>
    </div>
  );
}
