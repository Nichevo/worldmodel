"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import BriefCard from "@/components/BriefCard";
import { CW_LABEL } from "@/components/CrisisWatchCard";
import { api, type EntityLatest } from "@/lib/api";
import { monthName } from "@/lib/briefing";

// The top of a country page: a CrisisWatch banner when Crisis Group rated it worse, better
// or on alert this month, and "Latest on" with its news, events and finds of the last 30 days
// as the Briefing's cards.
export default function LatestOn({ entity, name }: { entity: string; name: string }) {
  const [d, setD] = useState<EntityLatest | null>(null);
  useEffect(() => {
    let live = true;
    setD(null);
    api.entityLatest(entity).then((x) => live && setD(x)).catch(() => live && setD(null));
    return () => { live = false; };
  }, [entity]);
  if (!d) return null;
  const cw = d.crisiswatch;
  const tone = !cw ? "" : cw.subkind === "deteriorated" ? "bad" : cw.subkind === "risk_alert" ? "alert"
    : cw.subkind === "improved" || cw.subkind === "resolution_opportunity" ? "good" : "";
  const names = { ...d.names, [entity]: name };
  return (
    <div id="latest">
      {cw && tone && (
        <div className={`cw-banner ${tone}`} role="note">
          <b>CrisisWatch, {monthName(cw.month)}: {cw.label}</b>
          {cw.previous && cw.previous !== cw.subkind && <span className="muted small">(last month: {CW_LABEL[cw.previous] ?? cw.previous})</span>}
          {cw.place && <span className="muted small">{cw.place}</span>}
          <span className="small">{cw.detail ? `${cw.detail.slice(0, 260)}${cw.detail.length > 260 ? "…" : ""}` : ""}</span>
          <Link href="#crisiswatch" className="small">Every month since 2003</Link>
        </div>
      )}
      {d.cards.length > 0 && (
        <section className="latest">
          <h3 className="brief-group-head">Latest on {name} <span className="muted small">last {d.days} days</span></h3>
          <div className="latest-strip">
            {d.cards.slice(0, 12).map((c) => <BriefCard key={c.key} card={c} names={names} compact />)}
          </div>
        </section>
      )}
    </div>
  );
}
