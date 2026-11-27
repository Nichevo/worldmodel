"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { api, type Expiring, type Storage } from "@/lib/api";

const gb = (b: number) => `${+(b / 1024 ** 3).toFixed(b < 10 * 1024 ** 3 ? 1 : 0)} GB`;
const pct = (x: number) => `${Math.round(x * 100)}%`;
const when = (iso: string) => new Date(`${iso}T00:00:00`).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });

function expiryText(i: Expiring): string {
  if (i.unit === "backups") return `${i.label}: ${i.keep} of ${i.keep} kept, so ${i.what}.`;
  const kept = `kept ${i.keep} days, oldest from ${when(i.oldest)}`;
  if (i.days_left > 1) return `${i.label}: the oldest start to go on ${when(i.deletes_from!)}, in ${i.days_left} days (${kept}).`;
  if (i.days_left === 1) return `${i.label}: the oldest start to go tomorrow (${kept}).`;
  return `${i.label}: now being deleted as they pass ${i.keep} days old (oldest kept: ${when(i.oldest)}).`;
}

// Two warnings at the top of every page, so settings can be changed in time:
// 1. the data folder (or its pictures or map files) passing the warning shares of its limits in
//    Settings, or the drive it is on running low; nothing is deleted on its own for these.
// 2. saved data (planes, ships, schedules, news, History, backups) within Settings > expiry_warn_days
//    of the age its setting deletes it at. "Keep as is" hides one until its setting changes.
export default function StorageBanner() {
  const [st, setSt] = useState<Storage | null>(null);
  const [exp, setExp] = useState<Expiring[]>([]);
  const [more, setMore] = useState(false);
  const path = usePathname();
  useEffect(() => {
    api.storage().then(setSt).catch(() => setSt(null));
    api.expiring().then((r) => setExp(r.items)).catch(() => setExp([]));
  }, [path]);
  const keep = (key: string) => api.keepAsIs(key).then((r) => setExp(r.items)).catch(() => {});

  const over = st ? st.limits.filter((l) => l.level !== "ok") : [];
  const level = st?.level ?? "ok";
  const shown = more ? exp : exp.slice(0, 2);
  return (
    <>
      {over.length > 0 && st && (
        <div className={`banner ${level}`} role="status">
          {over.map((l) => l.key === "drive"
            ? `${l.label}: only ${gb(l.free ?? 0)} free of ${gb(l.limit)}`
            : `${l.label}: ${pct(l.used / l.limit)} of its ${gb(l.limit)} limit`).join("; ")}.{" "}
          {over.some((l) => l.key === "disk" && l.level === "full") ? "Refreshes now skip large downloads. " : ""}
          Review it on <Link href="/data#storage">Data status</Link> or change the limits in{" "}
          <Link href="/settings#storage-limits">Settings</Link>.
        </div>
      )}
      {exp.length > 0 && (
        <div className={`banner ${exp.some((i) => i.unit === "days" && i.days_left <= 0) ? "critical" : "warn"}`} role="status">
          <b>Saved data will soon be deleted.</b> Extend how long it is kept in Settings if you want it, or keep as is.
          {shown.map((i) => (
            <div key={i.key} title={`When it goes: ${i.what}.`}>
              {expiryText(i)}{" "}
              <Link href={i.href}>Review in Settings</Link>{" · "}
              <button className="link" onClick={() => keep(i.key)}
                title="No warning for this again until you change how long it is kept">Keep as is</button>
            </div>
          ))}
          {exp.length > shown.length && <button className="link" onClick={() => setMore(true)}>{exp.length - shown.length} more</button>}
        </div>
      )}
    </>
  );
}
