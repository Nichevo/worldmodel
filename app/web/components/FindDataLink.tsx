"use client";

import Link from "next/link";
import { useSettings } from "@/lib/settings";

// "Find data on this": where the app has nothing to show, a link to the Find data page with
// the topic (and the country, when there is one) already filled in. Hidden when Find data is
// switched off in Settings.
export function findHref(topic: string, country?: string | null): string {
  const qs = new URLSearchParams({ q: topic.trim() });
  if (country) qs.set("country", country);
  return `/find?${qs}`;
}

export default function FindDataLink({ topic, country, label = "Find data on this" }: { topic: string; country?: string | null; label?: string }) {
  const s = useSettings();
  if (!s.find_data || !topic.trim()) return null;
  return (
    <Link href={findHref(topic, country)} className="small" title="Search open data portals worldwide (Dateno) for datasets on this">
      {label}</Link>
  );
}
