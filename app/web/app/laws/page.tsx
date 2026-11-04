"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useState } from "react";
import Help from "@/components/Help";
import WorldMap, { type Scale } from "@/components/WorldMap";
import { api, type LawMap, type LawRule } from "@/lib/api";
import { cssVar } from "@/lib/colors";
import { formatValue } from "@/lib/format";

// One rule on a world map, a year at a time: the slider shows when countries changed.
function LawsPage() {
  const router = useRouter();
  const params = useSearchParams();
  const [rules, setRules] = useState<LawRule[] | null>(null);
  const [rule, setRule] = useState<string | null>(params.get("rule"));
  const [year, setYear] = useState<number | undefined>(params.get("y") ? +params.get("y")! : undefined);
  const [data, setData] = useState<LawMap | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { api.laws().then(setRules).catch((e) => setError(String(e.message || e))); }, []);
  const current = rule ?? rules?.find((r) => r.unit === "yes/no")?.indicator_id ?? rules?.[0]?.indicator_id ?? null;
  useEffect(() => {
    if (!current) return;
    let live = true;
    api.lawMap(current, year).then((d) => live && setData(d)).catch((e) => live && setError(String(e.message || e)));
    return () => { live = false; };
  }, [current, year]);
  const yesNo = data?.indicator.unit === "yes/no";
  // Yes and No in two colours; numbers get the map's own scale.
  const scale: Scale | undefined = useMemo(() => (yesNo ? { breaks: [0.5], colors: [cssVar("--div-neg-1"), cssVar("--div-pos-2")] } : undefined), [yesNo]);
  const go = (r: string | null, y?: number) => {
    setRule(r); setYear(y);
    router.replace(`/laws?${new URLSearchParams({ ...(r ? { rule: r } : {}), ...(y ? { y: String(y) } : {}) })}`, { scroll: false });
  };
  if (error) return <p className="error">{error}</p>;
  if (!rules) return <p className="muted">Loading…</p>;
  if (!rules.length) {
    return <div><h1>Laws and rules</h1><p>No rules stored yet. Run <code>.\refresh.bat</code> to load Women, Business and the Law, crime figures and holidays.</p></div>;
  }
  const i = data ? data.years.indexOf(data.year ?? 0) : -1;
  const grouped = [["laws", "Laws and rules"], ["crime", "Crime and prisons"]] as const;
  const yes = data?.rows.filter((r) => r.value >= 0.5).length ?? 0;
  return (
    <div className="grid">
      <div className="title-row"><h1>Laws and rules</h1> <Help note="laws" /></div>
      <div className="chips-row small">
        <label>Rule <select value={current ?? ""} onChange={(e) => go(e.target.value, year)}>
          {grouped.map(([d, label]) => (
            <optgroup key={d} label={label}>
              {rules.filter((r) => r.domain === d).map((r) => <option key={r.indicator_id} value={r.indicator_id}>{r.name} ({r.countries} countries, {r.first}–{r.last})</option>)}
            </optgroup>
          ))}
        </select></label>
      </div>
      {data && data.years.length > 0 && (
        <>
          <p className="ink-2 small" style={{ margin: 0 }}>{data.indicator.description}</p>
          <div className="chips-row small">
            <button onClick={() => i > 0 && go(current, data.years[i - 1])} disabled={i <= 0} aria-label="Year before">◀</button>
            <input type="range" min={0} max={data.years.length - 1} value={i} onChange={(e) => go(current, data.years[+e.target.value])}
              aria-label="Year" style={{ flex: 1, minWidth: 200 }} />
            <button onClick={() => i < data.years.length - 1 && go(current, data.years[i + 1])} disabled={i >= data.years.length - 1} aria-label="Year after">▶</button>
            <b>{data.year}</b>
            {yesNo && <span><i className="dot" style={{ background: "var(--div-pos-2)" }} /> Yes {yes} · <i className="dot" style={{ background: "var(--div-neg-1)" }} /> No {data.rows.length - yes}</span>}
          </div>
          <div className="map-box">
            <WorldMap fill values={data.rows.map((r) => ({ entity_id: r.entity_id, value: r.value, status: "E" }))} unit={data.indicator.unit}
              decimals={data.indicator.decimals} diverging={false} scale={scale} onPick={(iso3) => router.push(`/entity/${iso3}#laws`)} />
          </div>
          <div className="card">
            <h3>{data.indicator.name}, {data.year}</h3>
            <div style={{ overflowX: "auto", maxHeight: 480 }}>
              <table className="small">
                <thead><tr><th>Country</th><th className="num">{data.year}</th><th className="num">Since</th></tr></thead>
                <tbody>
                  {data.rows.map((r) => (
                    <tr key={r.entity_id}>
                      <td><Link href={`/entity/${r.entity_id}#laws`}>{r.name}</Link></td>
                      <td className="num">{formatValue(r.value, data.indicator.unit, data.indicator.decimals)}</td>
                      <td className="num">{r.since === data.years[0] ? `${r.since} or earlier` : r.since}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="caption">&ldquo;Since&rdquo; is the first year of the current value (as far back as the source goes).</p>
          </div>
        </>
      )}
    </div>
  );
}

export default function Page() {
  return <Suspense fallback={<p className="muted">Loading…</p>}><LawsPage /></Suspense>;
}
