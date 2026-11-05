"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import EChart from "@/components/EChart";
import { api, type Driver, type Forecast } from "@/lib/api";
import { cardLinesOption, type CardLine } from "@/lib/charts";
import { seriesColor } from "@/lib/colors";

// What-if drivers kept from the Relationships page: move a driver's yearly change
// above or below what it would otherwise be, and see the target's forecast shift by
// the size the scan estimated (after income and time), starting after its lag.
export default function DriversCard({ indicator, name, fc }: { indicator: string; name: string; fc: Forecast | null }) {
  const [all, setAll] = useState<Driver[] | null>(null);
  const [shift, setShift] = useState<Record<string, number>>({});
  useEffect(() => { api.drivers().then(setAll).catch(() => setAll([])); }, []);
  const mine = useMemo(() => (all ?? []).filter((d) => d.target === indicator), [all, indicator]);
  const path = useMemo(() => {
    if (!fc) return [];
    return fc.points.map((p, i) => {
      let cum = 0;
      for (const d of mine) cum += d.slope * (shift[d.id] ?? 0) * Math.max(0, i + 1 - d.lag);
      const kind = mine[0]?.target_kind ?? "diff";
      return [p.year, kind === "pct" ? p.mean * Math.exp(cum / 100) : p.mean + cum] as [number, number];
    });
  }, [fc, mine, shift]);
  const option = useCallback(() => {
    if (!fc) return {};
    const last: [number, number, string] = [fc.history_end, fc.last_value, "E"];
    const lines: CardLine[] = [
      { key: "base", label: "Forecast", color: seriesColor(0), points: [last, ...fc.points.map((p) => [p.year, p.mean, "P"] as [number, number, string])] },
      { key: "what", label: "With your driver changes", color: seriesColor(1), points: [last, ...path.map(([y, v]) => [y, v, "P"] as [number, number, string])] },
    ];
    return cardLinesOption(lines, { unit: fc.unit, decimals: fc.decimals });
  }, [fc, path]);
  if (!all) return null;
  if (!mine.length) {
    return (
      <p className="small muted">
        No what-if drivers for this figure yet. <Link href={`/relationships?indicator=${indicator}&label=holds`}>Find pairs that hold after income and time</Link> and
        keep one as a driver.
      </p>
    );
  }
  const remove = (id: string) => api.deleteDriver(id).then(() => setAll((a) => (a ?? []).filter((d) => d.id !== id)));
  return (
    <section className="card">
      <h3>What-if drivers for {name}</h3>
      <table className="small">
        <thead><tr><th>Driver</th><th>Extra change each year</th><th>Effect</th><th /></tr></thead>
        <tbody>
          {mine.map((d) => (
            <tr key={d.id}>
              <td><Link href={`/relationships?x=${d.driver}&y=${d.target}`}>{d.driver_name}</Link></td>
              <td><input type="number" step="0.1" value={shift[d.id] ?? 0} style={{ width: 80 }} aria-label={`Extra change in ${d.driver_name}`}
                onChange={(e) => setShift({ ...shift, [d.id]: +e.target.value || 0 })} /> {d.driver_unit.replace(/^change in /, "")}</td>
              <td className="small">{d.slope.toPrecision(3)} {d.target_unit.replace(/^change in /, "")} for each 1 {d.driver_unit.replace(/^change in /, "")}{d.lag ? `, from ${d.lag} year${d.lag > 1 ? "s" : ""} later` : ", same year"}</td>
              <td><button className="link small" onClick={() => remove(d.id)}>Remove</button></td>
            </tr>
          ))}
        </tbody>
      </table>
      {fc && <EChart option={option} height={260} label={`What-if drivers: ${name}`} />}
      <p className="caption">A rough reading: each year the driver changes by the extra amount above its usual path, the target moves by the
        size the relationship scan estimated across countries, building up year on year. It is an average link, not a proven cause, and
        ignores everything else the change would bring.</p>
    </section>
  );
}
