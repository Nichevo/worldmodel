"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import RegionsCard from "@/components/RegionsCard";
import { api } from "@/lib/api";

// Regions inside a country: the US states (or every county) and New Zealand's regions on a map
// of their own outlines, one figure at a time. Region figures are kept apart from country
// figures, so the world map is unchanged. ?country=USA picks the country.
function RegionsPage() {
  const params = useSearchParams();
  const router = useRouter();
  const [list, setList] = useState<{ entity_id: string; name: string; regions: number; level: string; below: number }[] | null>(null);
  useEffect(() => { api.regionCountries().then(setList).catch(() => setList([])); }, []);
  const country = params.get("country") ?? list?.find((c) => c.entity_id === "USA")?.entity_id ?? list?.[0]?.entity_id ?? null;
  const here = list?.find((c) => c.entity_id === country);
  return (
    <div>
      <div className="title-row">
        <h1>Regions inside a country</h1>
      </div>
      <p className="ink-2">The states, counties or regions inside a country, on a map of their own outlines. Pick a figure; click a place for
        its page, where each figure is ranked against the places beside it. These figures are kept apart from the country figures, so the
        world map does not change.</p>
      {list && !list.length && <p className="muted">No regions yet: they come with a refresh (Settings &gt; Data, &ldquo;US states and counties&rdquo;).</p>}
      {list && list.length > 0 && (
        <div className="chips-row small">
          <span className="seg" role="group" aria-label="Country">
            {list.map((c) => (
              <button key={c.entity_id} className={c.entity_id === country ? "on" : ""} aria-pressed={c.entity_id === country}
                onClick={() => router.replace(`/regions?country=${c.entity_id}`)}>{c.name} ({c.regions}{c.below ? ` and ${c.below.toLocaleString()} below` : ""})</button>))}
          </span>
          {country && <Link href={`/entity/${country}`}>Country page</Link>}
        </div>
      )}
      {country && here && <RegionsCard key={country} entity={country} name={here.name} levels={here.below ? [here.level, "county"] : undefined}
        emptyNote={country === "NZL" ? "No figures for New Zealand's regions yet: they come from Stats NZ, which needs STATSNZ_API_KEY (Settings > Keys), then a refresh."
          : "No figures for these regions yet: they come with a refresh (Settings > Data, \u201cUS states and counties\u201d)."} />}
    </div>
  );
}

export default function Page() {
  return <Suspense fallback={<p className="muted">Loading…</p>}><RegionsPage /></Suspense>;
}
