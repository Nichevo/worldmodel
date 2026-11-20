"use client";

import Flag from "@/components/Flag";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useState } from "react";
import Help from "@/components/Help";
import WorldMap, { type Scale } from "@/components/WorldMap";
import { CW_COLOR, CW_LABEL, monthDetail } from "@/components/CrisisWatchCard";
import { osintApi, type OsintCwMonth } from "@/lib/osint";
import { api, type CrisisWatchMonth } from "@/lib/api";
import { cssVar } from "@/lib/colors";
import { mapLayersHref } from "@/lib/workspace";

// CrisisWatch on a world map, a month at a time: drag the slider through the months since 2003.
const ORDER = ["deteriorated", "risk_alert", "unchanged", "improved", "resolution_opportunity"];

function CrisisWatchPage() {
  const router = useRouter();
  const params = useSearchParams();
  const [data, setData] = useState<CrisisWatchMonth | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [month, setMonth] = useState<string | undefined>(params.get("m") ?? undefined);
  const [detail, setDetail] = useState<OsintCwMonth | null>(null);
  useEffect(() => {
    let live = true;
    api.crisiswatch(month).then((d) => live && setData(d)).catch((e) => live && setError(String(e.message || e)));
    return () => { live = false; };
  }, [month]);
  useEffect(() => {
    let live = true;
    if (data?.month) osintApi.cwMonth(data.month).then((d) => live && setDetail(d)).catch(() => live && setDetail(null));
    return () => { live = false; };
  }, [data?.month]);
  // Scores -2..2 (deteriorated .. resolution opportunity), one colour each.
  const scale: Scale = useMemo(() => ({ breaks: [-1.5, -0.5, 0.5, 1.5],
    colors: ORDER.map((k) => cssVar(CW_COLOR[k].slice(4, -1))) }), []);
  if (error) return <p className="error">{error}</p>;
  if (!data) return <p className="muted">Loading…</p>;
  if (!data.months.length) {
    return (
      <div>
        <h1>CrisisWatch</h1>
        <p>No CrisisWatch months stored yet. Run <code>.\refresh.bat</code> (Settings: CrisisWatch must be on), or save a month&apos;s page from
          crisisgroup.org/crisiswatch into <code>var\manual\crisiswatch</code> and run <code>.\load.bat</code>.</p>
      </div>
    );
  }
  const i = data.months.indexOf(data.month ?? "");
  const values = data.rows.map((r) => ({ entity_id: r.entity_id, value: r.score, status: "E" }));
  const go = (m: string) => { setMonth(m); router.replace(`/crisiswatch?m=${m}`, { scroll: false }); };
  return (
    <div className="grid">
      <div className="title-row">
        <h1>CrisisWatch by month</h1> <Help note="crisiswatch" />
      </div>
      <div className="chips-row small">
        <button onClick={() => i > 0 && go(data.months[i - 1])} disabled={i <= 0} aria-label="Month before">◀</button>
        <input type="range" min={0} max={data.months.length - 1} value={i} onChange={(e) => go(data.months[+e.target.value])}
          aria-label="Month" style={{ flex: 1, minWidth: 200 }} />
        <button onClick={() => i < data.months.length - 1 && go(data.months[i + 1])} disabled={i >= data.months.length - 1} aria-label="Month after">▶</button>
        <b>{data.month}</b>
        <span className="muted">{data.months.length} months stored, {data.months[0]} to {data.months[data.months.length - 1]}</span>
      </div>
      <div className="chips-row small cw-legend">
        {ORDER.map((k) => <span key={k}><i className="dot" style={{ background: CW_COLOR[k] }} /> {CW_LABEL[k]} ({data.rows.filter((r) => r.subkind === k).length})</span>)}
        <span className="muted">Grey land: not rated that month</span>
      </div>
      <div className="map-box">
        <WorldMap fill values={values} unit="" decimals={0} diverging scale={scale} onPick={(iso3) => router.push(`/entity/${iso3}#crisiswatch`)} />
      </div>
      <div className="card">
        <h3>{data.month}: {data.rows.length} situations rated</h3>
        <table className="small">
          <tbody>
            {[...data.rows].sort((a, b) => a.score - b.score || a.name.localeCompare(b.name)).map((r) => (
              <tr key={r.entity_id + (r.place ?? "")}>
                <td style={{ whiteSpace: "nowrap" }}><i className="dot" style={{ background: CW_COLOR[r.subkind] }} /> <Link href={`/entity/${r.entity_id}#crisiswatch`}><Flag id={r.entity_id} />{r.name}</Link>
                  {r.place ? <span className="muted"> ({r.place})</span> : null}</td>
                <td style={{ whiteSpace: "nowrap" }}>{CW_LABEL[r.subkind] ?? r.subkind}</td>
                <td>{r.detail}
                  {detail?.countries[r.entity_id] && (
                    <div className="muted" style={{ marginTop: 3, paddingLeft: 8, borderLeft: "3px solid var(--grid)" }}>
                      Recorded that month: {monthDetail(detail.countries[r.entity_id]) || "nothing in the event sources"}
                      {detail.countries[r.entity_id].mismatch ? <> · <b style={{ color: "var(--ink)" }}>Worth a second look: {detail.countries[r.entity_id].mismatch!.toLowerCase()}</b></> : null}
                    </div>
                  )}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="caption">International Crisis Group, CrisisWatch. An entry covering two countries (Israel/Palestine, say) shows on both.
          Under each rating, what UCDP, ACLED, the internet-outage monitors and OpenSanctions recorded in the same month; &quot;worth a second look&quot;
          marks a rating that points the other way from the recorded violence against the three months before.
          {" "}<Link href={mapLayersHref("34w", `${data.month}-01~${new Date(Date.UTC(+data.month!.slice(0, 4), +data.month!.slice(5, 7), 0)).toISOString().slice(0, 10)}`)}>This month&apos;s fighting and unrest on the map →</Link></p>
      </div>
    </div>
  );
}

export default function Page() {
  return <Suspense fallback={<p className="muted">Loading…</p>}><CrisisWatchPage /></Suspense>;
}
