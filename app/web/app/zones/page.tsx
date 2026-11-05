"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import ChartCard from "@/components/ChartCard";
import WorldMap, { type MapPoint } from "@/components/WorldMap";
import { api, get, type BeyondOther, type Indicator, type Ranking, type Zone } from "@/lib/api";
import { formatValue } from "@/lib/format";

// Places beyond any one country: Antarctica, the Arctic, space and the high seas.
const INTRO: Record<string, string> = {
  ATA: "No country owns Antarctica: seven claims were frozen by the Antarctic Treaty of 1959, which keeps the continent for peaceful science. New Zealand's claim is the Ross Dependency, with Scott Base beside the US McMurdo Station.",
  arctic: "The Arctic Ocean and the lands around it, shared by eight Arctic countries. Its sea ice is smallest each September; the low point has fallen by about a third since satellite records began in 1978.",
  space: "Everything tracked in orbit since Sputnik in 1957: working and dead satellites, spent rocket stages and debris, and who owns them.",
  high_seas: "The ocean beyond any country's 200-mile zone, nearly two thirds of the sea. The Law of the Sea governs it, and the High Seas Treaty of 2023 adds marine protected areas there.",
};
const TREATY_NAME: Record<string, string> = { unclos: "UN Convention on the Law of the Sea", bbnj: "High Seas Treaty (Biodiversity Beyond National Jurisdiction)" };

export default function ZonesPage() {
  const router = useRouter();
  const [zones, setZones] = useState<Zone[] | null>(null);
  const [indicators, setIndicators] = useState<Indicator[]>([]);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    api.zones().then(setZones).catch((e) => setError(String(e.message || e)));
    api.indicators().then(setIndicators).catch(() => setIndicators([]));
  }, []);
  const byId = useMemo(() => new Map(indicators.map((i) => [i.indicator_id, i])), [indicators]);
  if (error) return <p className="error">{error}</p>;
  if (!zones) return <p className="muted">Loading…</p>;
  return (
    <div className="grid">
      <div>
        <h1>Beyond borders</h1>
        <p className="ink-2">Places no one country owns. Each has its own page too (the links below), where its events and figures sit like a country&apos;s.</p>
      </div>
      {zones.map((z) => (
        <section key={z.entity_id} className="profile-section">
          <h2 className="section-head"><Link href={`/entity/${z.entity_id}`}>{z.short_name}</Link></h2>
          <p className="ink-2 small">{INTRO[z.entity_id] ?? z.description}</p>
          <div className="zone-grid">
            {z.indicators.filter((id) => id !== "sea_ice_extent").map((id) => {
              const ind = byId.get(id);
              return ind?.available ? <ChartCard key={id} indicator={ind} entities={[{ id: z.entity_id, name: z.short_name }]} /> : null;
            })}
            {z.layers.length > 0 && (
              <div className="card">
                <h3>Claims and research stations</h3>
                <div className="map-box" style={{ height: 380 }}>
                  <StationsMap layers={z.layers} onPick={(iso3) => router.push(`/entity/${iso3}`)} />
                </div>
                <p className="caption">Claims hand-entered from the treaty-era sector lines; stations from Wikidata. The map&apos;s projection stretches the far south.</p>
              </div>
            )}
            {z.by_country.map((id) => byId.get(id)?.available ? <TopCountries key={id} indicator={byId.get(id)!} /> : null)}
            {z.treaties.map((t) => (
              <div key={t.treaty} className="card">
                <h3>{TREATY_NAME[t.treaty] ?? t.title ?? t.treaty}</h3>
                <p><b>{t.joined}</b> countries have joined{t.signed_only ? <>, and <b>{t.signed_only}</b> more have signed but not yet ratified</> : ""}.</p>
                <p className="caption">UN Treaty Collection. Each country&apos;s date is on its page (Between countries card) and on the Events page.</p>
              </div>
            ))}
          </div>
          {!z.indicators.length && !z.layers.length && !z.treaties.some((t) => t.joined) && !z.by_country.length && (
            <p className="small muted">Nothing stored yet for {z.short_name}; a refresh loads it.</p>
          )}
        </section>
      ))}
      <Others />
    </div>
  );
}

const KIND: Record<BeyondOther["type"], string> = { organisation: "Organisation", bloc: "Bloc", alliance: "Alliance", armed_group: "Armed group" };

// Organisations and armed groups: not places, but they impose sanctions or are under them.
function Others() {
  const [list, setList] = useState<BeyondOther[] | null>(null);
  useEffect(() => { api.beyondOthers().then(setList).catch(() => setList([])); }, []);
  if (!list?.length) return null;
  const years = (o: BeyondOther) => o.valid_to ? `${o.valid_from?.slice(0, 4) ?? "?"}–${o.valid_to.slice(0, 4)}` : o.valid_from ? `since ${o.valid_from.slice(0, 4)}` : "";
  return (
    <section className="profile-section">
      <h2 className="section-head">Organisations and armed groups</h2>
      <p className="ink-2 small">Not countries: international organisations, the blocs and alliances the app already knows (EU, NATO, OPEC and others), and armed groups.
        Sanctions counts are from the Global Sanctions Data Base. Each has its own page with its events and figures.</p>
      {(["organisation", "armed_group"] as const).map((t) => {
        const some = list.filter((o) => (o.type === "armed_group") === (t === "armed_group"));
        return some.length ? (
          <div key={t} className="card">
            <h3>{t === "armed_group" ? "Armed groups under sanctions" : "International organisations, blocs and alliances"}</h3>
            <table className="small">
              <thead><tr><th>Name</th>{t !== "armed_group" && <th>Kind</th>}<th>Years</th><th className="num">Sanctions on it</th><th className="num" title="The most sanctions it had in force on others in one year">Most it imposed in a year</th></tr></thead>
              <tbody>
                {some.map((o) => (
                  <tr key={o.entity_id}>
                    <td><Link href={`/entity/${o.entity_id}`} title={o.description ?? undefined}>{o.short_name}</Link></td>
                    {t !== "armed_group" && <td>{KIND[o.type]}</td>}
                    <td>{years(o)}</td>
                    <td className="num">{o.sanctions_on || "–"}</td>
                    <td className="num">{o.most_imposed ?? "–"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null;
      })}
    </section>
  );
}

function TopCountries({ indicator }: { indicator: Indicator }) {
  const [r, setR] = useState<Ranking | null>(null);
  useEffect(() => { api.ranking(indicator.indicator_id).then(setR).catch(() => setR(null)); }, [indicator.indicator_id]);
  if (!r?.rows.length) return null;
  const top = r.rows.slice(0, 12);
  const max = top[0]?.value || 1;
  return (
    <div className="card">
      <h3>{indicator.name}, {r.year}</h3>
      <table className="small">
        <tbody>
          {top.map((x) => (
            <tr key={x.entity_id}>
              <td><Link href={`/entity/${x.entity_id}`}>{x.name}</Link></td>
              <td style={{ width: "50%" }}><div style={{ background: "var(--series-1)", height: 10, width: `${(100 * x.value) / max}%`, borderRadius: 2 }} /></td>
              <td className="num">{formatValue(x.value, indicator.unit, indicator.decimals)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="caption">{indicator.description} <Link href={`/indicator/${indicator.indicator_id}`}>All countries →</Link></p>
    </div>
  );
}

// The claims as a layer, and the stations as marked places so the map zooms to them.
function StationsMap({ layers, onPick }: { layers: string[]; onPick: (iso3: string) => void }) {
  const [points, setPoints] = useState<MapPoint[]>([]);
  useEffect(() => {
    if (!layers.includes("antarctic_stations")) return;
    get<{ features: { geometry: { coordinates: [number, number] }; properties: { id: string; name: string; operator?: string; country?: string } }[] }>("/layers/antarctic_stations").then((g: { features: { geometry: { coordinates: [number, number] };
      properties: { id: string; name: string; operator?: string; country?: string } }[] }) => setPoints(g.features.map((f) => ({
      id: f.properties.id, name: f.properties.name, lng: f.geometry.coordinates[0], lat: f.geometry.coordinates[1], size: 1,
      text: [f.properties.operator, f.properties.country].filter(Boolean).join(" · ") })))).catch(() => setPoints([]));
  }, [layers]);
  return <WorldMap fill values={[]} unit="" decimals={0} diverging={false} layers={layers.filter((l) => l !== "antarctic_stations")}
    points={points} fitPoints={points.length > 0} onPick={onPick} onCity={() => undefined} />;
}
