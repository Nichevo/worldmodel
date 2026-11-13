"use client";

import Link from "next/link";
import type * as maplibregl from "maplibre-gl";
import { useCallback, useEffect, useRef, useState } from "react";
import CountryChoice from "@/components/CountryChoice";
import IndicatorSet from "@/components/IndicatorSet";
import NatureCard from "@/components/NatureCard";
import NatureEvents from "@/components/NatureEvents";
import WorldMap from "@/components/WorldMap";
import { RankedCard, TargetTiles, useKeys } from "@/components/PageLook";
import { api, type NaturePage } from "@/lib/api";
import { cssVar } from "@/lib/colors";

// The Climate page's Nature tab: what is being lost, what is arriving (invasive species,
// pests, animal disease), and what is recovering (protected areas, comebacks, restoration).

type View = "losing" | "arriving" | "recovering";
const VIEWS: [View, string][] = [["losing", "Being lost"], ["arriving", "Arriving: invasive species, pests, disease"], ["recovering", "Recovering"]];
const NOT_LOADED = <p>Nothing stored for this yet. The nature sources come with <code>.\refresh.bat</code> (switches in <Link href="/settings#nature">Settings: Nature and pollution</Link>; IUCN and EPPO need free keys, see Data status).</p>;
const esc = (s: unknown) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c] ?? c));

function ProtectedMap({ count }: { count: number }) {
  const [areas, setAreas] = useState<{ key: string; data: GeoJSON.FeatureCollection } | null>(null);
  const [shown, setShown] = useState(0);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const load = useCallback((m: maplibregl.Map) => {
    const b = m.getBounds();
    const z = m.getZoom();
    // Zoomed out, the largest areas only; zoomed in, smaller ones too.
    const limit = z < 3 ? 400 : z < 5 ? 1200 : 2500;
    api.protectedAreas({ west: b.getWest(), south: b.getSouth(), east: b.getEast(), north: b.getNorth(), limit }).then((fc) => {
      const land = cssVar("--div-pos-2"), sea = cssVar("--series-2");
      for (const f of fc.features) {
        const p = (f.properties ?? {}) as Record<string, unknown>;
        Object.assign(p, { color: p.marine === "2" ? sea : land, opacity: 0.45, sort: -Number(p.area_km2 ?? 0),
          label: `<b>${esc(p.name)}</b><br/>${esc(p.designation)}${p.iucn_cat && p.iucn_cat !== "Not Reported" ? ` (IUCN ${esc(p.iucn_cat)})` : ""}`
            + `<br/>${Number(p.area_km2 ?? 0).toLocaleString(undefined, { maximumFractionDigits: 0 })} km²${p.year ? `, protected ${esc(p.year)}` : ""}` });
      }
      setShown(fc.features.length);
      setAreas({ key: `${b.getWest().toFixed(1)},${b.getSouth().toFixed(1)},${z.toFixed(1)}:${fc.features.length}`, data: fc });
    }).catch(() => {});
  }, []);
  const onMap = useCallback((m: maplibregl.Map | null) => {
    if (!m) return;
    const go = () => { if (timer.current) clearTimeout(timer.current); timer.current = setTimeout(() => load(m), 400); };
    m.on("moveend", go);
    if (m.loaded()) go(); else m.once("load", go);
  }, [load]);
  if (!count) return <div className="card"><h3>Protected areas</h3><p className="small">No protected areas stored yet. They come with <code>.\refresh.bat</code> from the World Database on Protected Areas
    (about 900 MB twice a year, cut to areas of 10 km² or more and every area in New Zealand; switch in <Link href="/settings#nature">Settings</Link>).</p></div>;
  return (
    <div className="card">
      <h3>Protected areas</h3>
      <div className="map-box"><WorldMap fill values={[]} unit="" decimals={0} diverging={false} hideScale areas={areas} onMap={onMap} onPick={() => {}}
        legend={[{ label: "On land", color: cssVar("--div-pos-2"), shape: "dot" }, { label: "At sea", color: cssVar("--series-2"), shape: "dot" }]} /></div>
      <p className="caption">{count.toLocaleString()} protected areas stored (World Database on Protected Areas, UNEP-WCMC and IUCN); the {shown.toLocaleString()} largest
        in view are drawn. Zoom in for smaller ones. Hover for the name, kind and year protected.</p>
    </div>
  );
}

export default function NatureTab({ country, onCountry }: { country: string; onCountry: (c: string) => void }) {
  const [view, setView] = useState<View>("losing");
  const [d, setD] = useState<NaturePage | null>(null);
  const [error, setError] = useState<string | null>(null);
  const keys = useKeys();
  useEffect(() => { api.nature().then(setD).catch((e) => setError(String(e.message || e))); }, []);
  if (error) return <p className="error">{error}</p>;
  if (!d) return <p className="muted">Loading…</p>;
  return (
    <>
      <div className="seg small" role="group" aria-label="Nature view">{VIEWS.map(([v, label]) =>
        <button key={v} className={view === v ? "on" : ""} aria-pressed={view === v} onClick={() => setView(v)}>{label}</button>)}</div>
      {view === "losing" ? (
        <>
          <p className="ink-2" style={{ marginTop: 0, maxWidth: 860 }}>Wildlife numbers (the Living Planet Index follows about 35,000 populations of animals since 1970),
            how close species are to extinction (the Red List Index), threatened species by country, and forest lost.</p>
          <div className="grid two">{d.losing.filter((i) => ["threatened_birds", "red_list_index"].includes(i)).map((i) => <RankedCard key={i} indicator={i} keys={keys} />)}</div>
          <IndicatorSet ids={d.losing} empty={NOT_LOADED} />
        </>
      ) : view === "arriving" ? (
        <>
          <p className="ink-2" style={{ marginTop: 0, maxWidth: 860 }}>Species people brought that now live wild, pests and plant diseases on the move, and animal disease outbreaks.
            New Zealand&apos;s border biosecurity comes first in the lists.</p>
          <IndicatorSet ids={d.invasive} empty={NOT_LOADED} />
          <div className="card">
            <h3>Pests and plant diseases watched</h3>
            <table className="small"><thead><tr><th>Pest</th><th>What it does</th><th className="num">Countries with it</th></tr></thead>
              <tbody>{d.pests.map((p) => <tr key={p.code}><td><b>{p.name}</b> <span className="muted">({p.kind})</span></td><td>{p.note}</td>
                <td className="num">{p.loaded ? p.countries : "—"}</td></tr>)}</tbody></table>
            <p className="caption">Where each is found comes from the EPPO Global Database (needs a free EPPO_API_KEY; see Data status: Keys you can add). The list is in nature.yaml.</p>
          </div>
          <div className="grid two">
            <div className="card"><h3>Pests and plant diseases arriving</h3><NatureEvents events={d.pest_events} /></div>
            <div className="card"><h3>Animal disease outbreaks</h3><NatureEvents events={d.disease} />
              <p className="caption">Hand-checked list. For every reported outbreak, load a WAHIS export (Data status: files you save by hand).</p></div>
          </div>
        </>
      ) : (
        <>
          <TargetTiles ids={d.recovering.filter((i) => ["protected_land_share", "protected_sea_share", "kba_land_protected", "kba_sea_protected"].includes(i))} keys={keys} />
          <ProtectedMap count={d.protected.n} />
          <IndicatorSet ids={d.recovering} empty={NOT_LOADED} />
          <div className="grid two">
            <div className="card"><h3>Species coming back</h3>
              <ul className="nature-list small">{d.comebacks.map((c) => <li key={c.name}><a href={c.url} target="_blank" rel="noreferrer"><b>{c.name}</b></a>
                {c.countries.length ? <span className="muted"> ({c.countries.join(", ")})</span> : null}: from {c.from} to {c.to}. <span className="muted">{c.how}</span></li>)}</ul></div>
            <div className="card"><h3>Restoration</h3>
              <ul className="nature-list small">{d.restoration.map((r) => <li key={r.name}><a href={r.url} target="_blank" rel="noreferrer"><b>{r.name}</b></a>
                <span className="muted"> ({r.countries.join(", ")}, from {r.start})</span>: {r.what}</li>)}</ul></div>
          </div>
        </>
      )}
      <div className="chips-row small"><CountryChoice value={country} onChange={onCountry} /></div>
      <NatureCard entity={country} name={country} showLink={false} />
    </>
  );
}
