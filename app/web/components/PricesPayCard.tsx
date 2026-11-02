"use client";

import Link from "next/link";
import Help from "@/components/Help";
import NumbeoPrices from "@/components/NumbeoPrices";
import type { Indicator, SeriesRow } from "@/lib/api";
import { useSeries } from "@/lib/cards";
import { formatValue } from "@/lib/format";

// Prices and pay in one country: price level against the US, cost of living,
// earnings and the minimum wage (each the latest figure), the gap between women's and
// men's pay, and Numbeo's everyday prices on request.
const ROWS = [
  "price_level_ratio", "wn_cost_index", "wn_monthly_cost_usd", "wn_rent_index",
  "ilo_earnings_usd", "ilo_earnings_ppp", "wn_median_net_usd", "wn_median_net_ppp", "wn_take_home_share",
  "ilo_min_wage_usd", "ilo_min_wage_ppp",
];
const GAP = ["ilo_earnings_lcu_women", "ilo_earnings_lcu_men"];

function last(rows: SeriesRow[] | undefined): SeriesRow | null {
  const est = (rows ?? []).filter((r) => r.status !== "P");
  return est.length ? est[est.length - 1] : null;
}

export default function PricesPayCard({ entity, name, indicators }: { entity: string; name: string; indicators: Map<string, Indicator> }) {
  const { data } = useSeries(entity, [...ROWS, ...GAP], indicators);
  const shown = ROWS.map((id) => ({ id, ind: indicators.get(id), r: last(data?.get(id)) })).filter((x) => x.ind && x.r);
  const women = last(data?.get(GAP[0]));
  const men = last(data?.get(GAP[1]));
  const gap = women && men && women.period === men.period && men.value ? (1 - women.value / men.value) * 100 : null;
  return (
    <div className="card" id="prices">
      <h3>Prices and pay <Help note="prices" /></h3>
      {data && shown.length === 0 && <p className="small ink-2">No price or pay figures for {name} yet (a refresh loads WhereNext and ILOSTAT).</p>}
      {shown.length > 0 && (
        <table className="summary-table">
          <tbody>
            {shown.map(({ id, ind, r }) => (
              <tr key={id} title={ind!.description}>
                <td><Link href={`/indicator/${id}`}>{ind!.name}</Link></td>
                <td className="num"><b>{formatValue(r!.value, ind!.unit, ind!.decimals)}</b></td>
                <td className="small muted">{r!.period.slice(0, 4)}</td>
              </tr>
            ))}
            {gap !== null && (
              <tr title="How much less women earn than men on average, from ILOSTAT's mean monthly earnings by sex">
                <td>Gap between women&apos;s and men&apos;s average pay</td>
                <td className="num"><b>{gap.toFixed(1)}%</b></td>
                <td className="small muted">{women!.period.slice(0, 4)}</td>
              </tr>
            )}
          </tbody>
        </table>
      )}
      <p className="caption">Hover a row for what it measures. More on the <Link href="/topic/living">Cost of living and pay</Link> topic page.</p>
      <h4 style={{ marginBottom: 4 }}>Everyday prices</h4>
      <NumbeoPrices kind="entities" id={entity} place={name} />
    </div>
  );
}
