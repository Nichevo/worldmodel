"use client";

import type { ECharts } from "echarts";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import EChart from "@/components/EChart";
import { api, type Indicator } from "@/lib/api";
import { energyMixOption, mixYears, type MixPart } from "@/lib/charts";
import { seriesColor } from "@/lib/colors";
import { credits, fileName, saveUrl, titledPng } from "@/lib/download";

// A country's energy mix: electricity generation and primary energy by fuel, as
// stacked areas in TWh or as shares. Eight groups at most, each with a fixed colour
// (fossil fuels first, then nuclear and the renewables), so a fuel looks the same
// on every country's chart.
type Group = { key: string; label: string; ids: string[]; color: number };
const MIXES: { key: string; title: string; groups: Group[]; note: string }[] = [
  { key: "elec", title: "Electricity generation by source", note: "Electricity generated in the country, by fuel.", groups: [
    { key: "coal", label: "Coal", ids: ["coal_electricity"], color: 7 },
    { key: "oil", label: "Oil", ids: ["oil_electricity"], color: 5 },
    { key: "gas", label: "Gas", ids: ["gas_electricity"], color: 2 },
    { key: "nuclear", label: "Nuclear", ids: ["nuclear_electricity"], color: 4 },
    { key: "hydro", label: "Hydro", ids: ["hydro_electricity"], color: 0 },
    { key: "wind", label: "Wind", ids: ["wind_electricity"], color: 3 },
    { key: "solar", label: "Solar", ids: ["solar_electricity"], color: 6 },
    { key: "other", label: "Bioenergy, geothermal and other renewables", ids: ["other_renewable_electricity"], color: 1 },
  ] },
  { key: "energy", title: "Primary energy by source", note: "All energy used, by fuel; nuclear and renewable electricity counted as the fossil fuel it replaces (substitution method).", groups: [
    { key: "coal", label: "Coal", ids: ["coal_consumption"], color: 7 },
    { key: "oil", label: "Oil", ids: ["oil_consumption"], color: 5 },
    { key: "gas", label: "Gas", ids: ["gas_consumption"], color: 2 },
    { key: "nuclear", label: "Nuclear", ids: ["nuclear_consumption"], color: 4 },
    { key: "hydro", label: "Hydro", ids: ["hydro_consumption"], color: 0 },
    { key: "wind", label: "Wind", ids: ["wind_consumption"], color: 3 },
    { key: "solar", label: "Solar", ids: ["solar_consumption"], color: 6 },
    { key: "other", label: "Biofuels, geothermal and other renewables", ids: ["biofuel_consumption", "other_renewable_consumption"], color: 1 },
  ] },
];

export default function EnergyMix({ entity, name, indicators }: { entity: string; name: string; indicators: Map<string, Indicator> }) {
  const [mix, setMix] = useState("elec");
  const [share, setShare] = useState(false);
  const [parts, setParts] = useState<MixPart[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const def = MIXES.find((m) => m.key === mix)!;
  const ids = def.groups.flatMap((g) => g.ids).filter((id) => indicators.get(id)?.available);
  const idKey = ids.join(",");

  useEffect(() => {
    if (!idKey) { setParts([]); return; }
    let live = true;
    setParts(null);
    Promise.all(idKey.split(",").map((id) => api.series(id, [entity]).then((rows) => [id, rows] as const)))
      .then((found) => {
        if (!live) return;
        const byId = new Map(found);
        setParts(def.groups.map((g) => {
          const values = new Map<number, number>();
          for (const id of g.ids) for (const r of byId.get(id) ?? []) {
            if (r.status !== "E") continue;
            values.set(+r.period, (values.get(+r.period) ?? 0) + r.value);
          }
          return { key: g.key, label: g.label, color: seriesColor(g.color), values };
        }).filter((p) => p.values.size && [...p.values.values()].some((v) => v > 0)));
        setError(null);
      })
      .catch((e) => live && setError(String(e.message || e)));
    return () => { live = false; };
  }, [entity, idKey]); // eslint-disable-line react-hooks/exhaustive-deps

  const option = useCallback(() => energyMixOption(parts ?? [], share), [parts, share]);
  const years = useMemo(() => {
    const ys = mixYears(parts ?? []);
    return ys.length ? [ys[0], ys[ys.length - 1]] : null;
  }, [parts]);
  const chart = useRef<ECharts | null>(null);
  const onReady = useCallback((c: ECharts) => { chart.current = c; }, []);
  const savePicture = async () => {
    const c = chart.current;
    if (!c || c.isDisposed()) return;
    try {
      const url = await titledPng(c.getDataURL({ type: "svg" }), c.getWidth(), c.getHeight(), `${def.title}: ${name}`,
        `${share ? "Share of the total" : "TWh"}${years ? `, ${years[0]}–${years[1]}` : ""}.`, await credits(["owid_energy"]));
      saveUrl(url, `${fileName("energy-mix", mix, entity)}.png`);
    } catch (e) {
      setError(String((e as Error).message || e));
    }
  };
  if (!ids.length && mix === "elec" && !MIXES[1].groups.some((g) => g.ids.some((id) => indicators.get(id)?.available))) return null;

  return (
    <div className="card" id="energy-mix">
      <div className="card-head">
        <h3>Energy mix</h3>
        {parts && parts.length > 0 && <button className="link small" onClick={savePicture} title="Save this chart as a picture, with its sources">Save picture</button>}
      </div>
      <div className="chips-row small">
        <div className="seg">
          {MIXES.map((m) => (
            <button key={m.key} className={mix === m.key ? "on" : ""} aria-pressed={mix === m.key} onClick={() => setMix(m.key)}>{m.title}</button>
          ))}
        </div>
        <div className="seg">
          <button className={!share ? "on" : ""} aria-pressed={!share} onClick={() => setShare(false)}>TWh</button>
          <button className={share ? "on" : ""} aria-pressed={share} onClick={() => setShare(true)}>Share</button>
        </div>
      </div>
      {error && <p className="error">{error}</p>}
      {parts && parts.length === 0 && <p className="muted">No figures by fuel for {name} yet.</p>}
      {parts && parts.length > 0 && <EChart option={option} height={320} label={`${def.title} in ${name}`} onReady={onReady} />}
      <p className="caption">
        {def.note} Source: Our World in Data energy dataset (Ember for electricity, Energy Institute for primary energy). Hover for each fuel&apos;s figure.
      </p>
    </div>
  );
}
