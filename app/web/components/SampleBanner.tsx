"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api, type Meta } from "@/lib/api";

// Says plainly when the app is showing the bundled sample rather than a local refresh,
// and when the API cannot be reached.
export default function SampleBanner() {
  const [meta, setMeta] = useState<Meta | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.meta().then(setMeta).catch((e) => setError(String(e.message || e)));
  }, []);

  if (error)
    return (
      <div className="banner">
        Can&apos;t reach the worldmodel API ({error}). Start it with <code>.\start.bat</code>, then reload.
      </div>
    );
  if (!meta?.is_sample) return null;
  const weo = meta.vintages.find((v) => v.source_id === "imf_weo" && v.is_latest);
  return (
    <div className="banner">
      Showing the sample warehouse that ships with the app: UN WPP 2024, IMF WEO {weo?.vintage ?? ""} (an old
      release), a selection of World Bank indicators and OWID energy data. Run <code>.\refresh.bat</code> to load
      everything, up to date. <Link href="/data">Details</Link>
    </div>
  );
}
