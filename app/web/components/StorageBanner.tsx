"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { api, type Storage } from "@/lib/api";

// Warns when the data folder (or its pictures) passes 80% or 95% of the limit set
// in Settings. Nothing is deleted on its own; the Data status page can free space.
export default function StorageBanner() {
  const [st, setSt] = useState<Storage | null>(null);
  const path = usePathname();
  useEffect(() => { api.storage().then(setSt).catch(() => setSt(null)); }, [path]);
  if (!st || st.level === "ok") return null;
  const worst = st.limits.filter((l) => l.level !== "ok");
  return (
    <div className={`banner ${st.level}`} role="status">
      {worst.map((l) => `${l.label}: ${Math.round((l.used / l.limit) * 100)}% of its ${+(l.limit / 1024 ** 3).toFixed(1)} GB limit`).join("; ")}.{" "}
      {st.level === "full" ? "Refreshes now skip large downloads. " : ""}
      Review it on <Link href="/data#storage">Data status</Link> or change the limit in <Link href="/settings">Settings</Link>.
    </div>
  );
}
