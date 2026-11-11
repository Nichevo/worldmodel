"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import CountryChoice from "@/components/CountryChoice";
import WorldMap from "@/components/WorldMap";
import ZonesCard, { PATHS } from "@/components/ZonesCard";
import { api, type ZonesInfo } from "@/lib/api";
import { zoneTiles } from "@/lib/climate";
import { useSettings } from "@/lib/settings";

// The Climate page's Zones tab: a map of the Köppen-Geiger zones for any period (and path
// ahead), its legend, and one country's zones with its cities' climate twins.

export default function ZonesTab({ country, onCountry }: { country: string; onCountry: (c: string) => void }) {
  const s = useSettings();
  const [info, setInfo] = useState<ZonesInfo | null>(null);
  const [period, setPeriod] = useState("1991-2020");
  const [path, setPath] = useState(s.zones_scenario || "ssp245");
  const [groups, setGroups] = useState(true);
  useEffect(() => { api.climateZones().then(setInfo).catch(() => setInfo(null)); }, []);
  const periods = useMemo(() => [...new Set((info?.periods ?? []).map((p) => p.period))].sort(), [info]);
  const future = +period.slice(0, 4) > 2020;
  const paths = PATHS.filter((p) => (info?.periods ?? []).some((x) => x.period === period && x.scenario === p.id));
  const raster = useMemo(() => (periods.includes(period)
    ? { tiles: zoneTiles(period, future ? path : "historical", groups), attribution: "Climate zones: Beck et al. 2023 (CC BY 4.0)", maxzoom: 6, over: true, opacity: 0.8 }
    : null), [period, path, groups, future, periods]);
  if (!info) return <p className="muted">Loading…</p>;
  if (!periods.length) {
    return <div className="card"><p>No climate zones stored yet. They come with <code>.\refresh.bat</code> (one download of about 1 GB from figshare, read once and
      cut to about 20 MB; switch in <Link href="/settings#nature">Settings: Nature and pollution</Link>). If the download fails, Data status says which files to save by hand.</p></div>;
  }
  return (
    <>
      <div className="card">
        <div className="card-head"><h3>Climate zones, {period}{future ? ` (${PATHS.find((p) => p.id === path)?.label})` : ""}</h3></div>
        <div className="chips-row small">
          <label>Period <select value={period} onChange={(e) => setPeriod(e.target.value)}>{periods.map((p) =>
            <option key={p} value={p}>{p}{+p.slice(0, 4) > 2020 ? " (projected)" : ""}</option>)}</select></label>
          {future ? <div className="seg small" role="group" aria-label="Emissions path">{(paths.length ? paths : PATHS).map((p) =>
            <button key={p.id} className={path === p.id ? "on" : ""} aria-pressed={path === p.id} onClick={() => setPath(p.id)}>{p.label}</button>)}</div> : null}
          <div className="seg small" role="group" aria-label="Detail">
            <button className={groups ? "on" : ""} aria-pressed={groups} onClick={() => setGroups(true)}>Five main groups</button>
            <button className={!groups ? "on" : ""} aria-pressed={!groups} onClick={() => setGroups(false)}>All 30 zones</button></div>
        </div>
        <div className="map-box"><WorldMap fill values={[]} unit="" decimals={0} diverging={false} hideScale raster={raster} onPick={(iso) => onCountry(iso)} /></div>
        <div className="zone-legend small">
          {(groups ? info.groups.map((g) => ({ k: g.code, label: `${g.code} ${g.name}`, colour: g.colour, title: g.name }))
            : info.zones.map((z) => ({ k: z.code, label: z.code, colour: z.colour, title: z.name }))).map((x) =>
            <span key={x.k} title={x.title}><i style={{ background: x.colour }} />{x.label}</span>)}
        </div>
        <p className="caption">Köppen-Geiger zones from temperature and rainfall through the year: A tropical, B dry, C temperate, D cold, E polar.
          Future periods are the average of climate models held to observed warming (Beck et al. 2023), for the emissions path chosen; the default path is in
          <Link href="/settings#nature"> Settings</Link>. Click a country for its breakdown below.</p>
      </div>
      <div className="chips-row small"><CountryChoice value={country} onChange={onCountry} /></div>
      <ZonesCard entity={country} name={country} showLink={false} />
    </>
  );
}
