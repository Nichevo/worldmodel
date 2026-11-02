"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api, type Meta } from "@/lib/api";

// Says plainly when the app is showing the bundled sample rather than a local refresh,
// when the API cannot be reached, and when the stored warehouse is in an older format.
export default function SampleBanner() {
  const [meta, setMeta] = useState<Meta | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.meta().then(setMeta).catch((e) => setError(String(e.message || e)));
  }, []);

  if (error && /has schema|older format/.test(error))
    return (
      <div className="banner">
        The stored data is in an older format than this version of the app reads, so most pages can&apos;t load
        yet. Nothing is lost: close the app, run <code>.\update.bat</code> (it rebuilds the warehouse from the
        data already downloaded, which takes a few minutes), then <code>.\start.bat</code>. If update.bat says the
        warehouse could not be rebuilt, run <code>.\refresh.bat</code>. <span className="muted small">({error})</span>
      </div>
    );
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
      release), a selection of World Bank indicators and OWID energy data, and a handful of example events. Run <code>.\refresh.bat</code> to load
      everything, up to date. <Link href="/data">Details</Link>
    </div>
  );
}
