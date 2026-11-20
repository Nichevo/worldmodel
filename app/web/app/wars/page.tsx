"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import type * as maplibregl from "maplibre-gl";
import AskButton from "@/components/AskButton";
import EChart from "@/components/EChart";
import Flag from "@/components/Flag";
import Tile from "@/components/Tile";
import WorldMap from "@/components/WorldMap";
import { compact } from "@/lib/format";
import { areaOption, lossesOption, osintApi, SIDE_COLOR, STATUS_LABEL, type FrontLine, type WarDetail, type WarSummary } from "@/lib/osint";
import { mapLayersHref } from "@/lib/workspace";

// War trackers: equipment lost (seen in photos and videos, Oryx) against what the other side claims,
// ground held (DeepState's front line, a day at a time) and aid given (Kiel). Built for Russia and
// Ukraine first; another war is a row in the contract's wars.yaml.
const NAMES: Record<string, string> = { RUS: "Russia", UKR: "Ukraine" };

function WarsPage() {
  const router = useRouter();
  const params = useSearchParams();
  const [wars, setWars] = useState<WarSummary[] | null>(null);
  const [id, setId] = useState(params.get("war") ?? "");
  const [w, setW] = useState<WarDetail | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [cat, setCat] = useState("tanks");
  const [front, setFront] = useState<FrontLine | null>(null);
  const [dayIdx, setDayIdx] = useState<number | null>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);

  useEffect(() => {
    osintApi.wars().then((d) => { setWars(d.wars); setId((cur) => cur || d.wars[0]?.id || ""); }).catch((e) => setErr(String(e.message || e)));
  }, []);
  useEffect(() => {
    if (!id) return;
    let live = true;
    setW(null);
    osintApi.war(id).then((d) => live && setW(d)).catch((e) => live && setErr(String(e.message || e)));
    osintApi.front(id).then((f) => { if (!live) return; setFront(f); setDayIdx(f.days?.length ? f.days.length - 1 : null); }).catch(() => live && setFront(null));
    return () => { live = false; };
  }, [id]);
  const days = front?.days ?? [];
  const day = dayIdx !== null ? days[dayIdx] : undefined;
  useEffect(() => {
    if (!id || !day || front?.features[0]?.properties?.day === day) return;
    let live = true;
    const t = setTimeout(() => osintApi.front(id, day).then((f) => live && setFront((cur) => ({ ...f, days: cur?.days ?? f.days }))).catch(() => {}), 200);
    return () => { live = false; clearTimeout(t); };
  }, [id, day]); // eslint-disable-line react-hooks/exhaustive-deps

  const names = useMemo(() => ({ ...NAMES }), []);
  const losses = useCallback(() => (w ? lossesOption(w, cat, names) : {}), [w, cat, names]);
  const area = useCallback(() => (w ? areaOption(w.areas, `Land held by ${names[w.front?.holder ?? ""] ?? "the occupier"}`) : {}), [w, names]);
  const areas = useMemo(() => (front?.features.length ? { key: `front:${front.features[0].properties?.day}`, data: { type: "FeatureCollection" as const,
    features: front.features.map((f) => ({ ...f, properties: { ...f.properties, color: "#c92a2a", opacity: 0.3,
      label: `<b>Held by ${names[String(f.properties?.holder)] ?? f.properties?.holder}</b> on ${f.properties?.day}<br/>${Math.round(Number(f.properties?.area_km2 ?? 0)).toLocaleString()} km² (DeepStateMap)` } })) } } : null),
  [front, names]);
  const fit = useCallback((m: maplibregl.Map | null) => {
    mapRef.current = m;
    const b = w?.map;
    if (m && b) m.fitBounds([[b.west, b.south], [b.east, b.north]], { duration: 0, padding: 20 });
  }, [w?.map]);
  useEffect(() => { const b = w?.map; if (mapRef.current && b) mapRef.current.fitBounds([[b.west, b.south], [b.east, b.north]], { duration: 0, padding: 20 }); }, [w?.map]);

  if (err) return <p className="error">{err}</p>;
  if (!wars) return <p className="muted">Loading…</p>;
  if (!w) return <p className="muted">Loading…</p>;
  const cats = w.latest.filter((l) => l.category !== "total");
  const seen = (side: string, c = "total") => w.latest.find((l) => l.category === c)?.[`${side}_seen`] as number | undefined;
  const claimed = (side: string, c: string) => w.latest.find((l) => l.category === c)?.[`${side}_claimed`] as number | undefined;
  const lastArea = w.areas[w.areas.length - 1];
  const areaAgo = (n: number) => { if (!lastArea) return null; const cut = new Date(Date.parse(lastArea[0]) - n * 86_400_000).toISOString().slice(0, 10);
    const a = [...w.areas].reverse().find((x) => x[0] <= cut); return a ? lastArea[1] - a[1] : null; };
  const a30 = areaAgo(30);
  const aidMax = Math.max(1, ...w.aid.map((a) => a.total ?? 0));
  const fightBy = new Map<string, { ucdp?: number; acled?: number }>();
  for (const f of w.fighting) {
    const r = fightBy.get(f.month) ?? {};
    if (f.source.startsWith("ucdp")) r.ucdp = (r.ucdp ?? 0) + (f.deaths ?? 0); else r.acled = (r.acled ?? 0) + (f.deaths ?? 0);
    fightBy.set(f.month, r);
  }
  const fightRecent = [...fightBy.entries()].sort((a, b) => b[0].localeCompare(a[0])).slice(0, 6);
  const nothing = !w.series.length && !w.areas.length && !w.aid.length;
  const pick = (v: string) => { setId(v); router.replace(`/wars?war=${v}`, { scroll: false }); };
  return (
    <div className="grid">
      <div className="title-row">
        <h1>War trackers</h1>
        {wars.length > 1 && (
          <select value={id} onChange={(e) => pick(e.target.value)} aria-label="War">{wars.map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}</select>
        )}
        <AskButton title={`War trackers: ${w.name}`} parts={() => [{ key: "data", kind: "data", label: "Latest losses, seen and claimed, and land held",
          text: [`War: ${w.name} (since ${w.began})`, ...w.latest.map((l) => `${l.label}: ${w.sides.map((s) => `${names[s] ?? s} seen ${l[`${s}_seen`] ?? "-"}${l[`${s}_claimed`] != null ? `, claimed ${l[`${s}_claimed`]}` : ""}`).join("; ")}`),
            lastArea ? `Land held on ${lastArea[0]}: ${Math.round(lastArea[1])} km²` : ""].join("\n") }]} />
      </div>
      <p className="ink-2">{w.name}{w.began ? `, since ${w.began}` : ""}. {w.note}</p>
      {nothing && <p className="card">Nothing loaded yet for this war. Run <code>.\refresh.bat</code> (Settings &gt; Fighting, wars…: War trackers on).
        Oryx is read from its two pages once a day; the claimed losses and front line come from GitHub.</p>}

      {!nothing && (
        <div className="tiles">
          {w.sides.map((s) => seen(s, "tanks") != null && (
            <Tile key={`t${s}`} label={`${names[s] ?? s}: tanks lost, seen (Oryx)`} value={(seen(s, "tanks") ?? 0).toLocaleString()}
              note={`All equipment: ${(seen(s) ?? 0).toLocaleString()}`} />
          ))}
          {w.sides.map((s) => claimed(s, "tanks") != null && (
            <Tile key={`c${s}`} label={`${names[s] ?? s}: tanks, claimed by the other side`} value={(claimed(s, "tanks") ?? 0).toLocaleString()}
              note={seen(s, "tanks") ? `${((claimed(s, "tanks") ?? 0) / (seen(s, "tanks") ?? 1)).toFixed(1)} times what is seen` : ""} />
          ))}
          {lastArea && (
            <Tile label={`Land held by ${names[w.front?.holder ?? ""] ?? "the occupier"} (DeepState)`} value={`${compact(lastArea[1])} km²`}
              note={a30 != null ? `${a30 >= 0 ? "+" : ""}${Math.round(a30).toLocaleString()} km² in 30 days` : lastArea[0]} />
          )}
        </div>
      )}

      {w.series.length > 0 && (
        <div className="card">
          <div className="card-head">
            <h3>Equipment lost, running total</h3>
            <select className="small" value={cat} onChange={(e) => setCat(e.target.value)} aria-label="What was lost">
              {[...w.latest.map((l) => [l.category, l.label] as const)].map(([k, l]) => <option key={k} value={k}>{l}</option>)}
            </select>
          </div>
          <EChart option={losses} height={300} label={`Running total of ${cat} lost`} />
          <p className="caption">Solid: losses Oryx has seen in a photo or video (a floor, not the whole count). Dashed: what the other side&apos;s government
            claims (Ukraine&apos;s General Staff for Russian losses). The gap between the two is part of the story.</p>
        </div>
      )}

      {cats.length > 0 && (
        <div className="card">
          <h3>Latest, by kind of equipment</h3>
          <table className="small">
            <thead><tr><th>Kind</th>{w.sides.map((s) => <th key={s} style={{ textAlign: "right" }}><Flag id={s} />{names[s] ?? s}, seen</th>)}
              <th style={{ textAlign: "right" }}>Last 30 days</th>{w.sides.some((s) => cats.some((c) => c[`${s}_claimed`] != null)) && <th style={{ textAlign: "right" }}>Claimed</th>}</tr></thead>
            <tbody>
              {[...cats, ...w.latest.filter((l) => l.category === "total")].map((l) => (
                <tr key={l.category} style={l.category === "total" ? { fontWeight: 600 } : undefined}>
                  <td><button className="link" onClick={() => setCat(l.category)}>{l.label}</button></td>
                  {w.sides.map((s) => <td key={s} style={{ textAlign: "right" }}>{l[`${s}_seen`] != null ? Number(l[`${s}_seen`]).toLocaleString() : "–"}</td>)}
                  <td style={{ textAlign: "right" }} className="muted">{w.sides.map((s) => l[`${s}_seen_30d`] != null ? `+${Number(l[`${s}_seen_30d`]).toLocaleString()}` : "–").join(" / ")}</td>
                  {w.sides.some((s) => cats.some((c) => c[`${s}_claimed`] != null)) && (
                    <td style={{ textAlign: "right" }}>{w.sides.map((s) => l[`${s}_claimed`] != null ? `${names[s]} ${Number(l[`${s}_claimed`]).toLocaleString()}` : "").filter(Boolean).join(", ") || "–"}</td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
          {Object.keys(w.statuses).length > 0 && (
            <p className="small">{Object.entries(w.statuses).map(([s, st]) => (
              <span key={s} style={{ marginRight: 16 }}><i className="dot" style={{ background: SIDE_COLOR[s] }} /> <b>{names[s] ?? s}</b>:{" "}
                {["destroyed", "damaged", "abandoned", "captured"].filter((k) => st[k] != null).map((k) => `${STATUS_LABEL[k].toLowerCase()} ${st[k].toLocaleString()}`).join(", ")}</span>
            ))}</p>
          )}
          {w.oryx && <p className="caption">Oryx&apos;s lists: {Object.entries(w.oryx).map(([s, u], i) => <span key={s}>{i ? " · " : ""}<a href={u} target="_blank" rel="noreferrer">{names[s] ?? s}</a></span>)}.
            Personnel figures are claims only; nobody can count them from photos.</p>}
        </div>
      )}

      {(w.areas.length > 0 || days.length > 0) && (
        <div className="card">
          <div className="card-head">
            <h3>Front line and land held</h3>
            <Link className="small" href={mapLayersHref("4d", "7d")}>Fires near the front this week →</Link>
          </div>
          {days.length > 0 && (
            <div className="chips-row small">
              <button onClick={() => dayIdx !== null && dayIdx > 0 && setDayIdx(dayIdx - 1)} disabled={!dayIdx} aria-label="Day before">◀</button>
              <input type="range" min={0} max={days.length - 1} value={dayIdx ?? 0} onChange={(e) => setDayIdx(+e.target.value)} aria-label="Day" style={{ flex: 1, minWidth: 200 }} />
              <button onClick={() => dayIdx !== null && dayIdx < days.length - 1 && setDayIdx(dayIdx + 1)} disabled={dayIdx === null || dayIdx >= days.length - 1} aria-label="Day after">▶</button>
              <b>{day}</b><span className="muted">{days.length} days kept (Mondays, the last 90 days and the latest)</span>
            </div>
          )}
          {areas && (
            <div className="map-box">
              <WorldMap values={[]} unit="" decimals={0} diverging={false} hideScale onPick={(iso3) => router.push(`/entity/${iso3}`)} areas={areas} onMap={fit} pictures={false} />
            </div>
          )}
          {w.areas.length > 1 && <EChart option={area} height={220} label="Land held, square kilometres, by day" />}
          <p className="caption">DeepStateMap&apos;s daily map of the front, saved on GitHub by a volunteer project; the area is worked out here on an
            equal-area projection. Includes Crimea and the parts of Donetsk and Luhansk held before 2022.</p>
        </div>
      )}

      {fightRecent.length > 0 && (
        <div className="card">
          <h3>Deaths in fighting, latest months</h3>
          <table className="small">
            <thead><tr><th>Month</th><th style={{ textAlign: "right" }}>UCDP best estimate</th><th style={{ textAlign: "right" }}>ACLED reported</th></tr></thead>
            <tbody>{fightRecent.map(([m, r]) => <tr key={m}><td>{m}</td><td style={{ textAlign: "right" }}>{r.ucdp?.toLocaleString() ?? "–"}</td>
              <td style={{ textAlign: "right" }}>{r.acled?.toLocaleString() ?? "–"}</td></tr>)}</tbody>
          </table>
          <p className="caption">In {w.sides.map((s) => names[s] ?? s).join(" and ")}, from the located events (shown side by side, never added). Each country&apos;s page
            has the full chart; the map&apos;s <Link href={mapLayersHref("34", "30d")}>Fighting and unrest</Link> layer shows where.</p>
        </div>
      )}

      {w.aid.length > 0 && (
        <div className="card">
          <h3>Aid given (Kiel Ukraine Support Tracker)</h3>
          <table className="small">
            <thead><tr><th>Donor</th><th style={{ textAlign: "right" }}>Military</th><th style={{ textAlign: "right" }}>Financial</th>
              <th style={{ textAlign: "right" }}>Humanitarian</th><th style={{ textAlign: "right" }}>Total, € bn</th><th /></tr></thead>
            <tbody>
              {w.aid.slice(0, 25).map((a) => (
                <tr key={a.entity_id} style={["NZL", "AUS", "GBR", "USA"].includes(a.entity_id) ? { fontWeight: 600 } : undefined}>
                  <td><Link href={`/entity/${a.entity_id}`}><Flag id={a.entity_id} />{a.name}</Link></td>
                  {(["military", "financial", "humanitarian", "total"] as const).map((k) => <td key={k} style={{ textAlign: "right" }}>{a[k] != null ? a[k]!.toFixed(2) : "–"}</td>)}
                  <td style={{ width: 120 }}><div style={{ height: 8, width: `${100 * (a.total ?? 0) / aidMax}%`, background: "var(--series-1)", borderRadius: 2 }} /></td>
                </tr>
              ))}
              {["NZL", "AUS"].filter((k) => !w.aid.slice(0, 25).some((a) => a.entity_id === k)).map((k) => {
                const a = w.aid.find((x) => x.entity_id === k);
                return a ? <tr key={k} style={{ fontWeight: 600 }}><td><Link href={`/entity/${k}`}><Flag id={k} />{a.name}</Link></td>
                  {(["military", "financial", "humanitarian", "total"] as const).map((x) => <td key={x} style={{ textAlign: "right" }}>{a[x] != null ? a[x]!.toFixed(2) : "–"}</td>)}<td /></tr> : null;
              })}
            </tbody>
          </table>
          <p className="caption">Commitments in billions of euros since January 2022, from the Kiel Institute&apos;s file you save in <code>var\manual\kiel_ukraine</code>.</p>
        </div>
      )}
      <p className="caption">Sources: Oryx (seen losses), Ukraine&apos;s General Staff via the russian-casualties project on GitHub (claimed), DeepStateMap via GitHub (front line),
        Kiel Institute (aid), UCDP and ACLED (deaths). <Link href="/settings#osint">Settings</Link></p>
    </div>
  );
}

export default function Page() {
  return <Suspense fallback={<p className="muted">Loading…</p>}><WarsPage /></Suspense>;
}
