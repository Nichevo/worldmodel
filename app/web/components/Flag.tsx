"use client";

import { useEffect, useState } from "react";
import { flagIndex, flagUrl, type FlagInfo } from "@/lib/flags";
import { useSettings } from "@/lib/settings";

// A small flag before a country's name (Settings > Look: flags). Groups without a flag,
// regions and old countries get a lettered badge so lists still line up.
let known: Map<string, FlagInfo> | null = null;

export default function Flag({ id, size = 14, title }: { id: string; size?: number; title?: string }) {
  const { flags_on: on } = useSettings();
  const [info, setInfo] = useState<FlagInfo | null>(known?.get(id) ?? null);
  const [broken, setBroken] = useState(false);
  useEffect(() => {
    if (!on) return;
    let live = true;
    flagIndex().then((m) => { known = m; if (live) setInfo(m.get(id) ?? null); }).catch(() => {});
    return () => { live = false; };
  }, [id, on]);
  if (!on || !info) return null;
  const h = Math.round(size * 0.75);
  if (info.code && !broken) {
    return <img className="flag" src={flagUrl(info.code)} width={size} height={h} alt="" title={title ?? info.name} loading="lazy"
      onError={() => setBroken(true)} />;
  }
  if (info.type === "subnational") return null;
  return <span className="flag-badge" style={{ minWidth: size, fontSize: size >= 24 ? "0.8rem" : "0.6rem" }} title={title ?? info.name}>{info.badge}</span>;
}
