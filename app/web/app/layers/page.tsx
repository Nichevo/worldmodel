"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { fmt, layerApi, layerName, showOnMapHref, type LayerOverview } from "@/lib/layerDetails";
import { LAYER_GROUPS, MAP_LAYERS } from "@/lib/workspace";

// Every map layer whose items can be counted, grouped as in the map's Layers list, each with
// how many items and countries it has now and what its Details page can show.
export default function LayersIndex() {
  const [list, setList] = useState<LayerOverview[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => { layerApi.list().then(setList).catch((e) => setErr(String(e.message || e))); }, []);
  if (err) return <p className="error">{err}</p>;
  if (!list) return <p className="muted">Loading…</p>;
  const by = new Map(list.map((l) => [l.id, l]));
  return (
    <div className="grid">
      <h1>Map layers in detail</h1>
      <p className="ink-2" style={{ margin: 0, maxWidth: 860 }}>Each layer on the map, counted: how many each country has, per million people and per area,
        the size figures its source gives (beds, megawatts, ship calls), and every item in a table you can sort and download.</p>
      {LAYER_GROUPS.map((g) => {
        const rows = MAP_LAYERS.filter((m) => m.group === g.id && by.has(m.id));
        if (!rows.length) return null;
        return (
          <div key={g.id} className="card">
            <h3>{g.label}</h3>
            <table className="small">
              <thead><tr><th>Layer</th><th style={{ textAlign: "right" }}>Items</th><th style={{ textAlign: "right" }}>Countries</th>
                <th>Size figure</th><th>Grouped by</th><th></th></tr></thead>
              <tbody>{rows.map((m) => {
                const l = by.get(m.id)!;
                const map = showOnMapHref(m.id);
                return (
                  <tr key={m.id}>
                    <td>{l.available ? <Link href={`/layers/${m.id}`}>{layerName(m.id)}</Link> : <span className="muted">{layerName(m.id)}</span>}</td>
                    <td style={{ textAlign: "right" }}>{l.kind === "live" ? <span className="muted">counted live</span> : l.count === null ? <span className="muted">not loaded</span> : fmt(l.count)}</td>
                    <td style={{ textAlign: "right" }}>{l.countries === null ? "" : fmt(l.countries)}</td>
                    <td>{l.size ?? <span className="muted">none in the source</span>}</td>
                    <td>{l.category ?? ""}</td>
                    <td>{map && <Link className="small" href={map}>Map</Link>}</td>
                  </tr>
                );
              })}</tbody>
            </table>
          </div>
        );
      })}
      <p className="caption">Not counted: planes, ships and military planes now (fetched only for the area in view), and lines such as rivers, railways and
        power lines, which have no split by country yet. A layer marked &quot;not loaded&quot; fills in after <code>.\refresh.bat</code>.</p>
    </div>
  );
}
