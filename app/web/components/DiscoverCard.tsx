"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { TONE_LABEL, openHref } from "@/components/FindCard";
import { api, type Find } from "@/lib/api";

// A country's top Discover finds, at the top of its page; hidden when there are none.
export default function DiscoverCard({ entity, name }: { entity: string; name: string }) {
  const [items, setItems] = useState<Find[] | null>(null);
  const [total, setTotal] = useState(0);
  useEffect(() => {
    let live = true;
    api.discoverEntity(entity, 5).then((d) => { if (live) { setItems(d.items); setTotal(d.total); } }).catch(() => live && setItems([]));
    return () => { live = false; };
  }, [entity]);
  if (!items?.length) return null;
  return (
    <div className="card" id="discover">
      <div className="card-head">
        <h3>Discover: {name}</h3>
        <Link className="small" href={`/discover?entity=${entity}`}>All {total} finds</Link>
      </div>
      <ul className="small plain" style={{ listStyle: "none", paddingLeft: 0, margin: 0 }}>
        {items.map((f) => {
          const href = openHref(f);
          return (
            <li key={f.key} style={{ margin: "4px 0" }}>
              <span className={`tone ${f.tone}`} title={TONE_LABEL[f.tone]}>{TONE_LABEL[f.tone].slice(0, 1)}</span>{" "}
              {href ? <Link href={href}>{f.headline}</Link> : f.headline}
              {f.detail && <span className="muted"> {f.detail}</span>}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
