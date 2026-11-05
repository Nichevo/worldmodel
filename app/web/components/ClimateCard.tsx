"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import CardAsk from "@/components/CardAsk";
import EChart from "@/components/EChart";
import Help from "@/components/Help";
import { api, type ClimateCountry } from "@/lib/api";
import { openAsk } from "@/lib/ai";
import { fanOption, lines, stripesOption } from "@/lib/climate";

// A country's climate on its page: how much warmer it has got, its emissions by gas and
// sector (with the net zero line), what the models project, its biggest disasters and
// what El Niño and La Niña usually bring.

const SSP_NAME: Record<string, string> = { ssp126: "Low emissions (SSP1-2.6)", ssp245: "Middle (SSP2-4.5)", ssp370: "High (SSP3-7.0)", ssp585: "Very high (SSP5-8.5)" };
const STATUS: Record<number, string> = { 4: "achieved", 3: "in law", 2: "in a policy document", 1: "a pledge", 0.5: "proposed" };

export default function ClimateCard({ entity, name }: { entity: string; name: string }) {
  const [d, setD] = useState<ClimateCountry | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [proj, setProj] = useState<"proj_temp" | "proj_rain">("proj_temp");
  useEffect(() => {
    let live = true;
    api.climateCountry(entity).then((r) => live && setD(r)).catch((e) => live && setError(String(e.message || e)));
    return () => { live = false; };
  }, [entity]);
  const nm = (i: string) => d?.names[i]?.name ?? i;
  const temp = d?.temperature.temp_anomaly ?? d?.temperature.nz_temp_anomaly_7station ?? [];
  const tempOpt = useCallback(() => lines(Object.entries(d?.temperature ?? {}).map(([i, pts]) => ({ name: nm(i), points: pts })), "°C", { zero: true }), [d]); // eslint-disable-line react-hooks/exhaustive-deps
  const stripes = useCallback(() => stripesOption(temp), [temp]);
  const gases = useCallback(() => {
    const o = lines(Object.entries(d?.gases ?? {}).map(([i, pts]) => ({ name: nm(i).replace(/ \(.*\)$/, ""), points: pts })), "Mt CO2e", { stack: true, decimals: 1 });
    const nz = d?.net_zero;
    const tot = Object.values(d?.gases ?? {});
    if (nz && tot.length) {
      const lastYear = Math.max(...tot.map((p) => p[p.length - 1]?.[0] ?? 0));
      const sum = tot.reduce((s, p) => s + (p.find((x) => x[0] === lastYear)?.[1] ?? 0), 0);
      (o.series as object[]).push({ type: "line", name: `Straight line to net zero by ${nz.year}`, data: [[lastYear, sum], [nz.year, 0]],
        symbol: "none", lineStyle: { type: "dotted", width: 2 } });
    }
    return o;
  }, [d]); // eslint-disable-line react-hooks/exhaustive-deps
  const sectors = useCallback(() => lines(Object.entries(d?.sectors ?? {}).map(([i, pts]) => ({ name: nm(i).replace(/^Greenhouse gases from |^New Zealand greenhouse gases from /, ""), points: pts })),
    d?.names[Object.keys(d?.sectors ?? {})[0]]?.unit ?? "", { decimals: 1 }), [d]); // eslint-disable-line react-hooks/exhaustive-deps
  const cons = useCallback(() => lines(["co2_gcp", "co2_consumption"].filter((i) => d?.consumption[i]).map((i) => ({ name: i === "co2_gcp" ? "Made at home" : "Counted where goods are used", points: d!.consumption[i] })),
    "Mt CO2", { decimals: 1 }), [d]);
  const fan = useCallback(() => fanOption(Object.keys(SSP_NAME).filter((s) => d?.projections[`${proj}_${s}`]).map((s) => ({ name: SSP_NAME[s], points: d!.projections[`${proj}_${s}`] })),
    proj === "proj_temp" ? "°C" : "mm"), [d, proj]);
  if (error) return <div className="card"><h3>Climate</h3><p className="error">{error}</p></div>;
  if (!d) return null;
  const any = temp.length || Object.keys(d.gases).length || Object.keys(d.projections).length || d.disasters.length;
  if (!any) return null;
  const hasProj = Object.keys(d.projections).some((k) => k.startsWith(proj));
  const ask = () => openAsk({ title: `${name}: climate`, entity, parts: [{ key: "data", kind: "data", label: "Temperature against normal",
    text: temp.map(([y, v]) => `${y}: ${v.toFixed(2)} °C`).join("\n") }] });
  return (
    <div className="card" id="climate-card">
      <div className="card-head"><h3>Climate <Help note="climate_country" /></h3><span><CardAsk onAsk={ask} /> <Link className="small" href="/climate">Climate page</Link></span></div>
      <div className="grid two">
        {temp.length ? (
          <div>
            <h4>How much warmer</h4>
            <EChart option={tempOpt} height={220} label={`${name} temperature against normal`} />
            <EChart option={stripes} height={60} label={`${name} warming stripes`} />
            <p className="caption">Each year&apos;s temperature against normal; in the stripes, blue is cooler and red warmer than the average of the years shown.</p>
          </div>
        ) : null}
        {Object.keys(d.gases).length ? (
          <div>
            <h4>Emissions by gas{d.net_zero ? `, and net zero by ${d.net_zero.year}` : ""}</h4>
            <EChart option={gases} height={240} label={`${name} greenhouse gas emissions`} />
            {d.net_zero ? <p className="caption">Net zero target {d.net_zero.year}{d.net_zero.status != null && STATUS[d.net_zero.status] ? `, ${STATUS[d.net_zero.status]}` : ""}. The dotted line is a straight path to it, for comparison, not the country&apos;s own plan.
              {d.carbon_price.length ? ` Carbon price ${d.carbon_price[d.carbon_price.length - 1][1].toFixed(0)} US$ a tonne (${d.carbon_price[d.carbon_price.length - 1][0]}).` : ""}</p> : null}
          </div>
        ) : null}
        {Object.keys(d.sectors).length ? (
          <div><h4>Emissions by sector</h4><EChart option={sectors} height={240} label={`${name} emissions by sector`} /></div>
        ) : null}
        {d.consumption.co2_consumption ? (
          <div><h4>Made at home, or counted where goods are used <Help note="climate_consumption" /></h4><EChart option={cons} height={240} label={`${name} production and consumption CO2`} /></div>
        ) : null}
        {hasProj || Object.keys(d.projections).length ? (
          <div>
            <div className="card-head"><h4>Projected to 2100</h4>
              <div className="seg small" role="group" aria-label="Projection">
                <button className={proj === "proj_temp" ? "on" : ""} aria-pressed={proj === "proj_temp"} onClick={() => setProj("proj_temp")}>Temperature</button>
                <button className={proj === "proj_rain" ? "on" : ""} aria-pressed={proj === "proj_rain"} onClick={() => setProj("proj_rain")}>Rainfall</button>
              </div></div>
            {hasProj ? <EChart option={fan} height={240} label={`${name} projections`} /> : <p className="muted small">No projections of this kind stored.</p>}
            <p className="caption">Yearly mean across the country, the median of the climate models (CMIP6) with the middle 80% of them shaded. World Bank Climate Change Knowledge Portal.</p>
          </div>
        ) : null}
        {d.enso && (d.enso.el_nino || d.enso.temp_r != null) ? (
          <div>
            <h4>El Niño and La Niña <Help note="climate_enso" /></h4>
            {d.enso.el_nino ? <p className="small"><b>El Niño:</b> {d.enso.el_nino}</p> : null}
            {d.enso.la_nina ? <p className="small"><b>La Niña:</b> {d.enso.la_nina}</p> : null}
            {d.enso.temp_r != null ? <p className="small ink-2">Over {d.enso.years} years, {name}&apos;s temperature (warming trend taken out) moved with the El Niño index at r = {d.enso.temp_r}
              {Math.abs(d.enso.temp_r) < 0.2 ? ": little link." : d.enso.temp_r > 0 ? ": warmer in El Niño years." : ": cooler in El Niño years."}</p> : null}
          </div>
        ) : null}
      </div>
      {d.disasters.length ? (
        <>
          <h4>Largest disasters</h4>
          <table className="small">
            <thead><tr><th>When</th><th>What</th><th className="num">Deaths</th><th className="num">Damage</th></tr></thead>
            <tbody>{d.disasters.slice(0, 8).map((x, i) => <tr key={i}><td>{x.start_date.slice(0, 7)}</td><td>{x.title}</td>
              <td className="num">{x.deaths != null ? Math.round(x.deaths).toLocaleString() : ""}</td>
              <td className="num">{x.damage_usd ? `US$ ${(x.damage_usd / 1e9).toFixed(1)} billion` : ""}</td></tr>)}</tbody>
          </table>
        </>
      ) : null}
    </div>
  );
}
