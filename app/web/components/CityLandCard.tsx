"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import CardAsk from "@/components/CardAsk";
import EChart from "@/components/EChart";
import { openAsk } from "@/lib/ai";
import { compact } from "@/lib/format";
import { type CentreDetail, land, linesOption } from "@/lib/land";
import { LAND_COVER } from "@/lib/maplook";
import { useSettings } from "@/lib/settings";

// A city's urban centre (GHSL): people and built-up land since 1975, its outline, and what
// covers it (trees, grass, built-up) from the land cover pictures, with an estimated tree count.

const CLASS_COLOUR: Record<string, string> = Object.fromEntries(
  [["10", 0], ["20", 1], ["30", 2], ["40", 3], ["50", 4], ["60", 5], ["70", 6], ["80", 7], ["90", 8], ["95", 9], ["100", 10]]
    .map(([k, i]) => [k, LAND_COVER[i as number]?.[1] ?? "#999"]));
const CLASS_NAME: Record<string, string> = Object.fromEntries(
  ["10", "20", "30", "40", "50", "60", "70", "80", "90", "95", "100"].map((k, i) => [k, LAND_COVER[i]?.[0] ?? k]));

export default function CityLandCard({ cityId, name }: { cityId: string; name: string }) {
  const [c, setC] = useState<CentreDetail | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const settings = useSettings();
  const load = useCallback(() => land.city(cityId).then(setC).catch(() => setC(null)), [cityId]);
  useEffect(() => { setC(null); load(); }, [load]);
  const chart = useCallback(() => linesOption([
    { label: "People", pts: Object.entries(c?.pop ?? {}).map(([y, v]) => [+y, v]) },
    { label: "Built-up km²", pts: Object.entries(c?.built ?? {}).map(([y, v]) => [+y, v]), axis: 1 },
  ], ["people", "km²"]), [c]);
  if (!c) return null;
  const work = () => {
    setBusy(true); setErr(null);
    land.coverStart({ ids: [c.id] }).then(() => {
      const poll = () => land.cover().then((l) => { if (l.job.state === "running") setTimeout(poll, 3000); else { setBusy(false); setErr(l.job.error ?? null); load(); } });
      setTimeout(poll, 2000);
    }).catch((e) => { setBusy(false); setErr(String(e.message || e)); });
  };
  const shares = Object.entries(c.cover?.shares ?? {}).sort((a, b) => b[1] - a[1]);
  const ask = () => openAsk({ title: `${name}: how it grew and what covers it`, parts: [
    { key: "data", kind: "data", label: "Urban centre (GHSL)", text: `People: ${Object.entries(c.pop).map(([y, v]) => `${y} ${compact(v)}`).join(", ")}\n`
      + `Built-up km²: ${Object.entries(c.built).map(([y, v]) => `${y} ${v.toFixed(0)}`).join(", ")}` },
    ...(c.cover ? [{ key: "cover", kind: "data" as const, label: "Land cover", text: shares.map(([k, v]) => `${CLASS_NAME[k]}: ${v.toFixed(1)}%`).join("\n") }] : [])] });
  return (
    <section className="card" id="city-land">
      <div className="card-head"><h3>How {name} spread, and its trees</h3><span><CardAsk onAsk={ask} /> <Link className="small" href="/land?tab=cities">Compare cities</Link></span></div>
      <div className="grid two">
        <div><EChart option={chart} height={240} label="People and built-up area" />
          <p className="caption">The urban centre &quot;{c.name}&quot; (GHSL): {compact(c.people ?? 0)} people in {c.now}
            {c.growth !== null ? `, ${c.growth > 0 ? "+" : ""}${c.growth.toFixed(0)}% since ${c.first}` : ""}; built-up land
            {c.built_growth !== null ? ` ${c.built_growth > 0 ? "+" : ""}${c.built_growth.toFixed(0)}%` : ""}. 2030 is a projection.</p></div>
        <div>
          {c.cover ? (
            <>
              <div style={{ display: "flex", height: 18, borderRadius: 4, overflow: "hidden" }}>
                {shares.map(([k, v]) => <span key={k} title={`${CLASS_NAME[k]}: ${v.toFixed(1)}%`} style={{ width: `${v}%`, background: CLASS_COLOUR[k] }} />)}</div>
              <table className="small"><tbody>{shares.slice(0, 6).map(([k, v]) => <tr key={k}><td><span className="legend-item"><i style={{ background: CLASS_COLOUR[k] }} />{CLASS_NAME[k]}</span></td>
                <td className="num">{v.toFixed(1)}%</td></tr>)}</tbody></table>
              <p className="small">Tree cover about <b>{c.cover.tree_km2.toFixed(0)} km²</b>: roughly <b>{compact(c.cover.trees_estimate)}</b> trees
                {c.cover.trees_per_person ? <>, about <b>{c.cover.trees_per_person.toFixed(1)}</b> a person</> : null} (an estimate).</p>
              <p className="caption">ESA WorldCover {c.cover.year} pictures inside the outline, worked out {c.cover.worked_out.slice(0, 10)}. Tree count: canopy area times 150 trees a hectare.</p>
            </>
          ) : (
            <>
              <p className="small">What covers {name} (trees, grass, built-up land) is worked out from the land cover pictures on request: a few dozen pictures, once.</p>
              <button onClick={work} disabled={busy || !settings.land_city_cover}>{busy ? "Working out…" : "Work out tree cover"}</button>
              {!settings.land_city_cover ? <p className="caption">Switched off in <Link href="/settings#land">Settings &gt; Land</Link>.</p> : null}
              {err ? <p className="small error">{err}</p> : null}
            </>
          )}
        </div>
      </div>
    </section>
  );
}
