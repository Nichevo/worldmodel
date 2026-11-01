"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import WorldMap from "@/components/WorldMap";
import { api, type Indicator, type Ranking } from "@/lib/api";

// A world map of one indicator in one year (by default its main year); clicking a
// country opens its page. Used on the indicator and topic pages.
export default function IndicatorMap({ indicator, ranking: given }: { indicator: Indicator; ranking?: Ranking | null }) {
  const router = useRouter();
  const [own, setOwn] = useState<Ranking | null>(null);
  useEffect(() => {
    if (given !== undefined) return;
    setOwn(null);
    api.ranking(indicator.indicator_id).then(setOwn).catch(() => setOwn(null));
  }, [indicator.indicator_id, given]);
  const ranking = given ?? own;
  const values = (ranking?.rows ?? []).map((r) => ({ entity_id: r.entity_id, value: r.value, status: r.status }));
  return (
    <div className="map-box">
      <WorldMap fill values={values} unit={indicator.unit} decimals={indicator.decimals}
        diverging={/growth|change|balance|net_/.test(indicator.indicator_id)}
        onPick={(iso3) => router.push(`/entity/${iso3}`)} />
    </div>
  );
}
