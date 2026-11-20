"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useState } from "react";
import AskButton from "@/components/AskButton";
import CountryChoice from "@/components/CountryChoice";
import Flag from "@/components/Flag";
import WorldMap from "@/components/WorldMap";
import { fmtMeasure } from "@/components/MilitaryCard";
import { entityVar } from "@/lib/look";
import { osintApi, type Military } from "@/lib/osint";

// Military strength: Global Firepower's counts side by side for the countries you pick, each with
// its rank among all countries and the change since the edition before; a second source where the
// app has one; and any measure as the map's colour.
const SETS: { name: string; ids: string[] }[] = [
  { name: "Key countries", ids: ["NZL", "AUS", "GBR", "USA"] },
  { name: "Five Eyes", ids: ["NZL", "AUS", "GBR", "USA", "CAN"] },
  { name: "Big powers", ids: ["USA", "CHN", "RUS", "IND", "GBR", "FRA"] },
  { name: "Asia-Pacific", ids: ["AUS", "NZL", "JPN", "KOR", "CHN", "IDN", "IND"] },
  { name: "Russia and Ukraine", ids: ["RUS", "UKR"] },
];

function MilitaryPage() {
  const router = useRouter();
  const params = useSearchParams();
  const [ids, setIds] = useState<string[]>(() => {
    const c = (params.get("c") ?? "").split(",").filter((x) => /^[A-Za-z0-9_]{2,12}$/.test(x));
    return c.length ? [...new Set([...c, ...(c.length === 1 ? ["NZL", "AUS", "GBR", "USA"].filter((k) => k !== c[0]) : [])])] : SETS[1].ids;
  });
  const [d, setD] = useState<Military | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [measure, setMeasure] = useState(params.get("m") ?? "gfp_personnel_active");
  const [mapVals, setMapVals] = useState<{ values: Record<string, number>; edition: number | null } | null>(null);
  const [group, setGroup] = useState("all");
  useEffect(() => {
    let live = true;
    osintApi.military(ids).then((x) => live && setD(x)).catch((e) => live && setErr(String(e.message || e)));
    return () => { live = false; };
  }, [ids.join(",")]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    let live = true;
    osintApi.militaryMap(measure).then((x) => live && setMapVals(x)).catch(() => live && setMapVals(null));
    return () => { live = false; };
  }, [measure]);
  const go = (next: string[], m = measure) => {
    setIds(next);
    router.replace(`/military?c=${next.join(",")}&m=${m}`, { scroll: false });
  };
  const values = useMemo(() => Object.entries(mapVals?.values ?? {}).map(([entity_id, value]) => ({ entity_id, value, status: "E" as const })), [mapVals]);
  if (err) return <p className="error">{err}</p>;
  if (!d) return <p className="muted">Loading…</p>;
  const m = d.measures.find((x) => x.id === measure);
  const groups = [...new Map(d.measures.map((x) => [x.group, x.group_name])).entries()];
  const shown = d.measures.filter((x) => group === "all" || x.group === group).filter((x) => d.countries.some((c) => c.values[x.id]));
  return (
    <div className="grid">
      <div className="title-row">
        <h1>Military strength</h1>
        <AskButton title="Military strength" parts={() => [{ key: "data", kind: "data", label: `Global Firepower ${d.edition} counts`,
          text: ["Measure," + d.countries.map((c) => c.name).join(","), ...shown.map((x) => `${x.name},${d.countries.map((c) => c.values[x.id]?.value ?? "").join(",")}`)].join("\n") }]} />
      </div>
      {!d.loaded && (
        <p className="card">Nothing loaded yet. Run <code>.\refresh.bat</code> (Settings &gt; Fighting, wars…: Military strength on): it reads Global Firepower&apos;s listing and
          a few country pages each time, New Zealand, Australia, the UK and the US first. If the site refuses, <code>.\verify.bat</code> opens the pages for you to save.</p>
      )}
      <div className="chips-row small">
        {d.countries.map((c, i) => (
          <span key={c.entity_id} className="chip"><i className="dot" style={{ background: entityVar(c.entity_id, i) }} />
            <Link href={`/entity/${c.entity_id}#military`}><Flag id={c.entity_id} />{c.name}</Link>
            {ids.length > 1 && <button aria-label={`Remove ${c.name}`} onClick={() => go(ids.filter((x) => x !== c.entity_id))}>×</button>}</span>
        ))}
        <CountryChoice value="" onChange={(id) => id && !ids.includes(id) && go([...ids, id].slice(0, 12))} label="Add a country" />
        {SETS.map((s) => <button key={s.name} className="small" onClick={() => go(s.ids)}>{s.name}</button>)}
      </div>
      {d.loaded && (
        <div className="card">
          <div className="card-head">
            <h3>Counts, Global Firepower {d.edition}</h3>
            <select className="small" value={group} onChange={(e) => setGroup(e.target.value)} aria-label="Which measures">
              <option value="all">All measures</option>{groups.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
            </select>
          </div>
          <div style={{ overflowX: "auto" }}>
            <table className="small">
              <thead><tr><th>Measure</th>{d.countries.map((c) => <th key={c.entity_id} style={{ textAlign: "right" }}><Flag id={c.entity_id} />{c.name}</th>)}<th /></tr></thead>
              <tbody>
                {shown.map((x) => (
                  <tr key={x.id} className={x.id === measure ? "on" : undefined}>
                    <td>{x.name}</td>
                    {d.countries.map((c) => {
                      const v = c.values[x.id];
                      return (
                        <td key={c.entity_id} style={{ textAlign: "right", whiteSpace: "nowrap" }}>
                          {v ? <><b>{fmtMeasure(v.value, x.unit)}</b>
                            {v.before != null && v.before !== v.value ? <span className={x.id === "gfp_power_index" ? "muted" : v.value > v.before ? "up" : "down"}> {v.value > v.before ? "▲" : "▼"}</span> : null}
                            <div className="muted">#{v.rank} of {v.of}{v.also ? ` · ${fmtMeasure(v.also.value, x.unit)} ${x.id === "gfp_budget_usd" ? "SIPRI" : "WB"} ${v.also.year}` : ""}</div></> : "–"}
                        </td>
                      );
                    })}
                    <td><button className="link small" onClick={() => { setMeasure(x.id); router.replace(`/military?c=${ids.join(",")}&m=${x.id}`, { scroll: false }); }}>Map</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="caption">Ranks are among the countries Global Firepower lists (lower PowerIndex is stronger; for every count, higher is more).
            ▲▼ change since its edition before. The second figure is the World Bank&apos;s armed forces personnel (from IISS) or SIPRI&apos;s military spending, where loaded.
            PowerIndex is Global Firepower&apos;s own score from an unpublished formula: read it as one outlet&apos;s view, not a measurement.</p>
        </div>
      )}
      {d.loaded && m && (
        <div className="card">
          <div className="card-head"><h3>{m.name} on the map</h3>
            <select className="small" value={measure} onChange={(e) => { setMeasure(e.target.value); router.replace(`/military?c=${ids.join(",")}&m=${e.target.value}`, { scroll: false }); }} aria-label="Measure">
              {d.measures.map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}
            </select></div>
          <div className="map-box">
            <WorldMap values={values} unit={m.unit === "US$" ? "US dollars" : m.unit} decimals={m.unit === "score" ? 3 : 0} diverging={false}
              onPick={(iso3) => !ids.includes(iso3) && go([...ids, iso3].slice(0, 12))} selected={ids} />
          </div>
          <p className="caption">Click a country to add it to the table. Global Firepower {mapVals?.edition ?? ""}; {values.length} countries.</p>
        </div>
      )}
      <p className="caption">Also on each country&apos;s page: Military strength and arms (who it buys weapons from and sells them to, SIPRI) and nuclear warheads (Federation of American Scientists).</p>
    </div>
  );
}

export default function Page() {
  return <Suspense fallback={<p className="muted">Loading…</p>}><MilitaryPage /></Suspense>;
}
