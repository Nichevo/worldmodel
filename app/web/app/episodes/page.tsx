"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useState } from "react";
import CardAsk from "@/components/CardAsk";
import CountryChoice from "@/components/CountryChoice";
import Flag from "@/components/Flag";
import { openAsk } from "@/lib/ai";
import { type EpisodeList, type Found, cyclesApi } from "@/lib/cycles";
import { kindLabel, kindVar } from "@/lib/events";
import { logHistory } from "@/lib/history";

// Episodes: the big ones typed in from economic histories, each with its own page, and the
// recessions, booms and crises the app finds in the data itself. Explore > Episodes.
type Tab = "typed" | "found";

function EpisodesView() {
  const router = useRouter();
  const params = useSearchParams();
  const tab: Tab = params.get("tab") === "found" ? "found" : "typed";
  const go = (t: Tab) => router.replace(t === "typed" ? "/episodes" : "/episodes?tab=found", { scroll: false });
  useEffect(() => { logHistory({ kind: "page", title: "Episodes", url: "/episodes", detail: "page" }); }, []);
  return (
    <div className="grid sector-page">
      <div className="title-row"><h1>Episodes</h1></div>
      <div className="seg" role="tablist">
        <button role="tab" aria-selected={tab === "typed"} className={tab === "typed" ? "on" : ""} onClick={() => go("typed")}>Big episodes</button>
        <button role="tab" aria-selected={tab === "found"} className={tab === "found" ? "on" : ""} onClick={() => go("found")}>Found in the data</button>
      </div>
      {tab === "typed" ? <Typed /> : <FoundTab />}
    </div>
  );
}

function Typed() {
  const [d, setD] = useState<EpisodeList | null>(null);
  const [kind, setKind] = useState<string>("all");
  useEffect(() => { cyclesApi.episodes().then(setD).catch(() => setD({ kinds: {}, episodes: [] })); }, []);
  if (!d) return <p className="muted">Loading…</p>;
  const shown = d.episodes.filter((e) => kind === "all" || (kind === "nz" ? e.nz : e.kind === kind));
  const ask = () => openAsk({ title: "Big economic episodes", parts: [
    { key: "data", kind: "data", label: "Episodes", text: d.episodes.map((e) => `${e.years[0]}-${e.years[1]} ${e.title} (${e.kind_name}): ${e.summary}`).join("\n") }] });
  return (
    <>
      <p className="ink-2" style={{ marginTop: 0, maxWidth: 860 }}>Big episodes typed in from economic histories, from the Great Depression to the
        recent inflation, with New Zealand&apos;s own. Each page has a timeline, the key charts with the episode shaded, who was hit,
        figures before, during and after, and how today compares with the run-up.</p>
      <div className="long-tools">
        <div className="chips-row small">
          {[["all", "All"], ...Object.entries(d.kinds), ["nz", "Touches NZ"]].map(([k, label]) => (
            <button key={k} className={`chip${kind === k ? " on" : ""}`} aria-pressed={kind === k} onClick={() => setKind(k)}>{label}</button>))}
        </div>
        <CardAsk onAsk={ask} />
      </div>
      <div className="episode-grid">
        {shown.map((e) => (
          <Link key={e.id} href={`/episodes/${e.id}`} className="card episode-card">
            <span className="small muted">{e.years[0] === e.years[1] ? e.years[0] : `${e.years[0]}–${e.years[1]}`} · {e.kind_name}{e.nz ? " · NZ" : ""}</span>
            <b>{e.title}</b>
            <span className="small">{e.summary.length > 190 ? `${e.summary.slice(0, 189)}…` : e.summary}</span>
            <span className="small muted">{e.countries.filter((c) => c !== "world").slice(0, 6).map((c) => <Flag key={c} id={c} />)}
              {e.worst && <> Worst hit: {e.worst.name}, output down {Math.abs(e.worst.fall).toFixed(0)}%</>}</span>
          </Link>))}
      </div>
      <p className="caption">The list is typed in (contract episodes.yaml) from economic histories; Wikipedia has the full stories and each page
        links them. &quot;Worst hit&quot; is the deepest fall in output among the episode&apos;s main countries. Bands for these episodes show on
        charts when &quot;Big episodes&quot; is ticked in <Link href="/settings#events">Settings &gt; Events on charts</Link>; clicking a band opens its page.</p>
    </>
  );
}

const FOUND_KINDS = ["recession", "crisis", "boom", "inflation", "debt"];

function FoundTab() {
  const [entity, setEntity] = useState("NZL");
  const [kinds, setKinds] = useState<string[]>(FOUND_KINDS);
  const [d, setD] = useState<Found | null>(null);
  useEffect(() => {
    let live = true;
    setD(null);
    cyclesApi.found(entity || undefined, kinds).then((x) => live && setD(x)).catch(() => live && setD({ events: [], waves: [] }));
    return () => { live = false; };
  }, [entity, kinds.join(",")]); // eslint-disable-line react-hooks/exhaustive-deps
  const waves = useMemo(() => {
    const by = new Map<number, { year: number; recession: number; crisis: number; episode: { id: string; title: string } | null }>();
    for (const w of d?.waves ?? []) {
      const r = by.get(w.year) ?? { year: w.year, recession: 0, crisis: 0, episode: null };
      if (w.kind === "recession") r.recession = w.n; else r.crisis = w.n;
      r.episode = r.episode ?? w.episode;
      by.set(w.year, r);
    }
    return [...by.values()].sort((a, b) => b.year - a.year);
  }, [d]);
  const top = Math.max(1, ...waves.map((w) => w.recession + w.crisis));
  const toggle = (k: string) => setKinds(kinds.includes(k) ? kinds.filter((x) => x !== k) : [...kinds, k]);
  const ask = () => openAsk({ title: `Episodes found in the data: ${entity}`, entity, parts: [
    { key: "data", kind: "data", label: "Episodes", text: (d?.events ?? []).map((e) => `${e.start_date.slice(0, 4)} ${e.title}${e.size !== null ? ` (${e.size.toFixed(1)} ${e.size_unit ?? ""})` : ""}`).join("\n") }] });
  return (
    <>
      <p className="ink-2" style={{ marginTop: 0, maxWidth: 860 }}>Recessions, booms, inflation spikes and debt surges the app works out from yearly
        figures (rules on the Data page), and banking, debt and currency crises from Reinhart and Rogoff&apos;s list.</p>
      <div className="card">
        <div className="card-head"><h3>Years when many countries were hit at once</h3></div>
        {!d ? <p className="muted">Loading…</p> : !waves.length ? <p className="muted small">{d.note ?? "No year with eight or more countries starting a recession or crisis."}</p> : (
          <div className="wave-list">{waves.slice(0, 30).map((w) => (
            <div key={w.year} className="wave-line small">
              <span>{w.year}</span>
              <span className="wave-bar"><i style={{ width: `${(100 * w.recession) / top}%`, background: "var(--div-neg-3)" }} /><i style={{ width: `${(100 * w.crisis) / top}%`, background: "var(--div-neg-2)" }} /></span>
              <span>{w.recession ? `${w.recession} recessions` : ""}{w.recession && w.crisis ? ", " : ""}{w.crisis ? `${w.crisis} crises` : ""}</span>
              <span>{w.episode && <Link href={`/episodes/${w.episode.id}`}>{w.episode.title}</Link>}</span>
            </div>))}</div>)}
        <p className="caption">Countries starting a recession (dark) or a crisis (light) that year, where eight or more did; linked to a typed-in episode when one covers it.</p>
      </div>
      <div className="card">
        <div className="card-head"><h3>Found for one country</h3><CardAsk onAsk={ask} /></div>
        <div className="long-tools">
          <CountryChoice value={entity} onChange={setEntity} />
          <div className="chips-row small">{FOUND_KINDS.map((k) => (
            <button key={k} className={`chip${kinds.includes(k) ? " on" : ""}`} aria-pressed={kinds.includes(k)} onClick={() => toggle(k)}>
              <i className="swatch" style={{ background: kindVar(k) }} />{kindLabel(k)}</button>))}</div>
        </div>
        {!d ? <p className="muted">Loading…</p> : !d.events.length ? <p className="muted small">{d.note ?? "Nothing found for this country."}</p> : (
          <table className="small summary-table">
            <thead><tr><th>When</th><th>What</th><th>Size</th></tr></thead>
            <tbody>{d.events.map((e) => (
              <tr key={e.event_id}><td>{e.start_date.slice(0, 4)}{e.end_date && e.end_date.slice(0, 4) !== e.start_date.slice(0, 4) ? `–${e.end_date.slice(0, 4)}` : ""}</td>
                <td><i className="swatch" style={{ background: kindVar(e.kind) }} />{e.title}{e.subkind ? ` (${e.subkind.replace(/_/g, " ")})` : ""}</td>
                <td>{e.size !== null ? `${e.size.toFixed(1)} ${e.size_unit ?? ""}` : ""}</td></tr>))}</tbody>
          </table>)}
      </div>
    </>
  );
}

export default function Page() {
  return <Suspense fallback={<p className="muted">Loading…</p>}><EpisodesView /></Suspense>;
}
