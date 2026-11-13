"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useMemo, useState } from "react";
import EChart from "@/components/EChart";
import Flag from "@/components/Flag";
import WorldMap, { type Scale } from "@/components/WorldMap";
import ReligionCountry from "@/components/ReligionTop";
import { api, type Religion } from "@/lib/api";
import { useEntityNames } from "@/lib/flags";
import { cardLinesOption } from "@/lib/charts";
import { people, relColor, religionLines, SOURCE_NOTE } from "@/lib/people";

// Religion around the world: each religion's share of the world over time (one source at a
// time), and a map of the largest religion, any one religion's share, or its change.
type Mode = "largest" | "share" | "change";

function ReligionPage() {
  const router = useRouter();
  const params = useSearchParams();
  const nameOf = useEntityNames();
  const [d, setD] = useState<Religion | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [src, setSrc] = useState<string | null>(null);
  const [mode, setMode] = useState<Mode>((params.get("mode") as Mode) || "largest");
  const [group, setGroup] = useState(params.get("group") || "none");
  const [year, setYear] = useState<number | undefined>(params.get("year") ? +params.get("year")! : undefined);
  const [since, setSince] = useState<number | undefined>(params.get("since") ? +params.get("since")! : undefined);
  useEffect(() => {
    let live = true;
    api.religion(year, group, mode === "change" ? since ?? 1990 : undefined)
      .then((x) => { if (live) { setD(x); setError(null); } }).catch((e) => live && setError(String(e.message || e)));
    return () => { live = false; };
  }, [year, group, since, mode]);
  useEffect(() => {
    const q = new URLSearchParams({ mode, group, ...(year ? { year: String(year) } : {}), ...(since ? { since: String(since) } : {}) });
    router.replace(`/religion?${q}`, { scroll: false });
  }, [mode, group, year, since]); // eslint-disable-line react-hooks/exhaustive-deps
  const source = d?.sources.find((s) => s.id === src) ?? d?.sources[0];
  const lines = useMemo(() => (d && source ? religionLines(d.world[source.id] ?? [], d.groups) : []), [d, source]);
  const option = useCallback(() => cardLinesOption(lines, { unit: "%", decimals: 1, stack: true, max: 100 }), [lines]);
  if (error) return <p className="error">{error}</p>;
  if (!d) return <p className="muted">Loading…</p>;
  const names = Object.fromEntries(d.groups.map((g) => [g.id, g.name]));
  if (!d.sources.length) {
    return (
      <div>
        <h1>Religion</h1>
        <p>No religion figures loaded yet. Run <code>.\refresh.bat</code> for the Correlates of War data, and save Pew&apos;s table of
          religious composition by country into <code>var\manual\pew_religion</code> (Data status has the link). Each country page
          still shows what the CIA Factbook says in each edition.</p>
      </div>
    );
  }
  const order = d.groups.map((g) => g.id);
  const rows = d.map.rows;
  const values = rows.map((r) => ({ entity_id: r.entity_id, status: "E",
    value: mode === "largest" ? order.indexOf(r.largest) : mode === "share" ? r.share : r.change ?? null }))
    .filter((v) => v.value !== null) as { entity_id: string; value: number; status: string }[];
  const scale: Scale | undefined = mode === "largest" ? { breaks: order.slice(1).map((_, i) => i + 0.5), colors: order.map(relColor) } : undefined;
  const latest = d.world[source?.id ?? ""]?.filter((p) => !p.projected).at(-1);
  const sorted = [...rows].sort((a, b) => mode === "change" ? (b.change ?? -1e9) - (a.change ?? -1e9) : b.share - a.share);
  return (
    <div className="grid">
      <div className="title-row">
        <h1>Religion</h1>
        <span className="muted small">Each religion&apos;s share of the world over time, and by country</span>
      </div>
      <ReligionCountry world={d.world} groups={d.groups} />
      <div className="card">
        <div className="card-head">
          <h3>The world{latest ? `, ${latest.year}: ${people(latest.people ?? 0)} people counted` : ""}</h3>
          <div className="seg small" role="group" aria-label="Source">
            {d.sources.map((s) => <button key={s.id} className={s === source ? "on" : ""} aria-pressed={s === source} onClick={() => setSrc(s.id)}>{s.name}</button>)}
          </div>
        </div>
        <EChart option={option} height={300} label="Religion: share of the world" />
        <p className="caption">{SOURCE_NOTE[source?.id ?? ""]} Countries weighted by their people. Sources count differently, so each has its own chart.</p>
      </div>
      <div className="card">
        <div className="chips-row small">
          <div className="seg" role="group" aria-label="Colour the map by">
            {([["largest", "Largest religion"], ["share", "Share of one religion"], ["change", "Change since"]] as [Mode, string][]).map(([m, label]) => (
              <button key={m} className={mode === m ? "on" : ""} aria-pressed={mode === m} onClick={() => setMode(m)}>{label}</button>
            ))}
          </div>
          {mode !== "largest" && (
            <label>Religion <select value={group} onChange={(e) => setGroup(e.target.value)}>
              {d.groups.map((g) => <option key={g.id} value={g.id}>{g.name}</option>)}</select></label>
          )}
          {mode === "change" && (
            <label>since <select value={since ?? 1990} onChange={(e) => setSince(+e.target.value)}>
              {d.years.filter((y) => y < (d.map.year ?? 9999)).map((y) => <option key={y} value={y}>{y}</option>)}</select></label>
          )}
          <label>Year <select value={d.map.year ?? ""} onChange={(e) => setYear(+e.target.value)}>
            {d.years.map((y) => <option key={y} value={y}>{y}</option>)}</select></label>
        </div>
        {mode === "largest" && (
          <div className="chips-row small">
            {d.groups.map((g) => <span key={g.id}><i className="dot" style={{ background: relColor(g.id) }} /> {g.name} ({rows.filter((r) => r.largest === g.id).length})</span>)}
          </div>
        )}
        <div className="map-box">
          <WorldMap fill values={values} unit={mode === "largest" ? "" : "%"} decimals={1} diverging={mode === "change"} scale={scale} hideScale={mode === "largest"}
            onPick={(iso3) => router.push(`/entity/${iso3}#religion`)} />
        </div>
        <p className="caption">{mode === "largest" ? "Each country's largest religious group" : mode === "share" ? `${names[group]}: share of each country's people`
          : `${names[group]}: change in share since ${since ?? 1990}, in percentage points`}, {d.map.year}. Best source each country has that year (Pew, then Correlates of War).</p>
      </div>
      <div className="card">
        <h3>{mode === "largest" ? `${names[group]} by country` : mode === "share" ? `${names[group]} by country` : `Biggest changes: ${names[group]}`}, {d.map.year}</h3>
        <table className="small">
          <thead><tr><th>Country</th><th>{names[group]}</th>{mode === "change" && <th>Change</th>}<th>Largest</th></tr></thead>
          <tbody>
            {sorted.slice(0, 30).map((r) => (
              <tr key={r.entity_id}>
                <td><Link href={`/entity/${r.entity_id}#religion`}><Flag id={r.entity_id} />{nameOf(r.entity_id)}</Link></td>
                <td>{r.share.toFixed(1)}%</td>
                {mode === "change" && <td>{r.change !== undefined ? `${r.change > 0 ? "+" : ""}${r.change.toFixed(1)}` : "–"}</td>}
                <td><i className="dot" style={{ background: relColor(r.largest) }} /> {names[r.largest]} {r.largest_share.toFixed(0)}%</td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="caption">Moving together is not cause and effect: the relationship scan can test religion against fertility, income and schooling.</p>
      </div>
    </div>
  );
}

export default function Page() {
  return <Suspense fallback={<p className="muted">Loading…</p>}><ReligionPage /></Suspense>;
}
