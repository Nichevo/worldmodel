"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import CardAsk from "@/components/CardAsk";
import { openAsk } from "@/lib/ai";
import { detailsHref, fmt, layerApi, type CountryLayer } from "@/lib/layerDetails";

// A country page's "On the map": how many of each counted map layer's items it has (hospitals,
// ports, power plants...), its rank among countries and the size total where the layer has one,
// each a link to the layer's Details page for this country.
export default function OnTheMapCard({ entity, name }: { entity: string; name: string }) {
  const [rows, setRows] = useState<CountryLayer[] | null>(null);
  useEffect(() => {
    let live = true;
    layerApi.country(entity).then((r) => live && setRows(r)).catch(() => live && setRows([]));
    return () => { live = false; };
  }, [entity]);
  if (!rows?.length) return null;
  const sizeText = (r: CountryLayer) => (r.size && r.size.value !== null
    ? `${fmt(r.size.value, r.size.unit === "mm a year" ? 1 : 0)} ${r.size.unit === "beds" || r.size.unit === "students" ? r.size.unit : `${r.size.label.toLowerCase()}${r.size.unit ? ` (${r.size.unit})` : ""}`}` : "");
  const ask = () => openAsk({ title: `${name}: on the map`, entity, parts: [{ key: "data", kind: "data", label: "Items on the map's layers",
    text: rows.map((r) => `${r.many}: ${r.count} (#${r.rank} of ${r.of} countries)${sizeText(r) ? `, ${sizeText(r)}` : ""}`).join("\n") }] });
  return (
    <div className="card" id="on-the-map">
      <div className="card-head"><h3>On the map</h3>
        <span><CardAsk onAsk={ask} /> <Link className="small" href="/layers">All layers</Link></span></div>
      <table className="small">
        <thead><tr><th>Layer</th><th className="num">Here</th><th className="num">Rank</th><th>Size</th></tr></thead>
        <tbody>{rows.map((r) => (
          <tr key={r.layer_id}>
            <td><Link href={detailsHref(r.layer_id, entity)}>{r.many.charAt(0).toUpperCase() + r.many.slice(1)}</Link></td>
            <td className="num">{fmt(r.count)}</td>
            <td className="num muted">#{r.rank} of {r.of}</td>
            <td className="muted">{sizeText(r)}</td>
          </tr>
        ))}</tbody>
      </table>
      <p className="caption">What each map layer lists here, not every one there is: some layers&apos; sources are patchy. Click a layer for the full list and
        how {name} compares.</p>
    </div>
  );
}
