"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import CardAsk from "@/components/CardAsk";
import EChart from "@/components/EChart";
import { openAsk } from "@/lib/ai";
import { monthsOption, osintApi, type OsintCountry } from "@/lib/osint";
import { mapLayersHref } from "@/lib/workspace";

// A country's last months from the OSINT sources: deaths in fighting (UCDP and ACLED side by side,
// never added), protests and riots (ACLED), internet outages (IODA, Cloudflare Radar, KeepItOn) and
// sanctions newly listed. Hidden when none of them has anything for the country.
export default function FightingCard({ entity, name }: { entity: string; name: string }) {
  const [d, setD] = useState<OsintCountry | null>(null);
  const [months, setMonths] = useState(24);
  useEffect(() => {
    let live = true;
    osintApi.country(entity, months).then((x) => live && setD(x)).catch(() => live && setD(null));
    return () => { live = false; };
  }, [entity, months]);
  const deaths = useCallback(() => monthsOption(d?.months ?? [], "deaths"), [d]);
  const unrest = useCallback(() => monthsOption(d?.months ?? [], "unrest"), [d]);
  if (!d || !(d.has.ucdp || d.has.acled || d.has.outages || d.has.sanctions)) return null;
  const sum = (k: "ucdp_deaths" | "acled_deaths" | "protests" | "riots" | "outages" | "sanctions_added") =>
    d.months.reduce((a, m) => a + (m[k] ?? 0), 0);
  const flagged = d.months.filter((m) => m.mismatch);
  const causes = [...new Set(d.months.flatMap((m) => m.outage_causes))];
  return (
    <div className="card" id="fighting">
      <div className="card-head">
        <h3>Fighting, unrest and outages by month</h3>
        <CardAsk onAsk={() => openAsk({ title: `Fighting, unrest and outages: ${name}`, entity, parts: [{ key: "data", kind: "data",
          label: "Months (UCDP deaths, ACLED deaths, ACLED violent events, protests, riots, internet outages, new sanctions listings, CrisisWatch)",
          text: ["Month,UCDP deaths,ACLED deaths,Violent events,Protests,Riots,Outages,New sanctions,CrisisWatch",
            ...d.months.map((m) => [m.month, m.ucdp_deaths ?? "", m.acled_deaths ?? "", m.violence, m.protests, m.riots, m.outages, m.sanctions_added, m.crisiswatch ?? ""].join(","))].join("\n") }] })} />
        <select className="small" value={months} onChange={(e) => setMonths(+e.target.value)} aria-label="How many months">
          {[12, 24, 60, 120].map((n) => <option key={n} value={n}>Last {n >= 24 ? `${n / 12} years` : `${n} months`}</option>)}
        </select>
        <Link href={mapLayersHref("3", "1y")} className="small">On the map →</Link>
      </div>
      <div className="chips-row small">
        {d.has.ucdp && <span><b>{sum("ucdp_deaths").toLocaleString()}</b> killed in fighting (UCDP)</span>}
        {d.has.acled && <span><b>{sum("acled_deaths").toLocaleString()}</b> (ACLED)</span>}
        {d.has.acled && <span><b>{sum("protests").toLocaleString()}</b> protests · <b>{sum("riots").toLocaleString()}</b> riots</span>}
        {d.has.outages && <span><b>{sum("outages")}</b> internet outages{causes.length ? ` (${causes.slice(0, 3).join(", ")})` : ""}</span>}
        {d.has.sanctions && <span><b>{sum("sanctions_added").toLocaleString()}</b> newly sanctioned names or ships</span>}
      </div>
      {(d.has.ucdp || d.has.acled) && <EChart option={deaths} height={210} label={`Deaths in fighting by month, ${name}`} />}
      {sum("protests") + sum("riots") + sum("outages") > 0 && <EChart option={unrest} height={170} label={`Protests, riots and internet outages by month, ${name}`} />}
      {flagged.length > 0 && (
        <p className="small"><b>CrisisWatch and the events differ</b>: {flagged.map((m) => `${m.month} (${m.mismatch?.toLowerCase()})`).join("; ")}.{" "}
          <a href="#crisiswatch">See CrisisWatch</a></p>
      )}
      <p className="caption">UCDP counts deaths it can confirm (best estimate; this year's months are candidates, one or two months behind).
        ACLED counts reported deaths and every protest and riot. The two are shown side by side, never added: they count differently,
        and they disagree most where reporting is thin.</p>
    </div>
  );
}
