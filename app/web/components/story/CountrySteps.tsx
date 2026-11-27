"use client";

// Story steps for the "How countries changed" stories: one country then and now.

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { Frame, notLoaded, type Props } from "@/components/story/Frame";
import { api, type Indicator } from "@/lib/api";
import { shortValue } from "@/lib/look";
import { fmtOf, type Step, type ThenNowData, type ThenNowPoint } from "@/lib/story";

// How many years after `from` an early figure may come from (surveys and censuses skip years).
const SLACK = 5;

// Rank (1 = highest) of a value among a year's values.
const rankOf = (v: number, all: number[]) => 1 + all.filter((x) => x > v).length;
// Where a rank sits on a lowest (0) to highest (100) track.
const place = (q: ThenNowPoint) => (q.of > 1 ? (100 * (q.of - q.rank)) / (q.of - 1) : 50);

export function ThenNowStep(p: Props & { step: Extract<Step, { kind: "thennow" }> }) {
  const st = p.step;
  const [got, setGot] = useState<ThenNowData["rows"] | null>(null);
  useEffect(() => {
    let live = true;
    const want = st.indicators.map((id) => p.inds.get(id)).filter((x): x is Indicator => !!x?.available);
    Promise.all(want.map(async (ind) => {
      const [early, latest] = await Promise.all([
        api.mapRange(ind.indicator_id, st.from, st.from + SLACK).catch(() => null),
        api.ranking(ind.indicator_id).catch(() => null),
      ]);
      let then: ThenNowPoint | null = null;
      if (early) {
        const mine = early.rows[st.entity] ?? [];
        const k = early.years.findIndex((_, i) => mine[i] !== null && mine[i] !== undefined);
        if (k >= 0) {
          const all = Object.values(early.rows).map((r) => r[k]).filter((x): x is number => x !== null && x !== undefined);
          then = { year: early.years[k], value: mine[k]!, rank: rankOf(mine[k]!, all), of: all.length };
        }
      }
      const row = latest?.rows.find((r) => r.entity_id === st.entity);
      const now: ThenNowPoint | null = row && latest?.year ? { year: latest.year, value: row.value, rank: row.rank, of: latest.rows.length } : null;
      return then || now ? { ind, then, now } : null;
    })).then((xs) => { if (live) setGot(xs.filter((x): x is ThenNowData["rows"][number] => !!x)); });
    return () => { live = false; };
  }, [st.entity, st.from, st.indicators.join(","), p.inds]); // eslint-disable-line react-hooks/exhaustive-deps
  const d = useMemo((): ThenNowData | null => (got ? { entity: st.entity, from: st.from, rows: got,
    get: (id) => got.find((r) => r.ind.indicator_id === id), fmt: (ind, v) => fmtOf(ind)(v) } : null), [got, st.entity, st.from]);
  if (got && !got.length) return <Frame {...p} sentence={null} data="" missing={notLoaded(["the headline figures"])} />;
  const csv = got ? ["Measure,Unit,Year then,Value then,Rank then,Of,Year now,Value now,Rank now,Of",
    ...got.map((g) => `"${g.ind.name}","${g.ind.unit}",${g.then?.year ?? ""},${g.then?.value ?? ""},${g.then?.rank ?? ""},${g.then?.of ?? ""},${g.now?.year ?? ""},${g.now?.value ?? ""},${g.now?.rank ?? ""},${g.now?.of ?? ""}`)].join("\n") : "";
  return (
    <Frame {...p} sentence={d ? st.say(d) : null} data={csv}>
      <div className="thennow">
        {(got ?? []).map((g) => {
          const a = g.then ? place(g.then) : null, b = g.now ? place(g.now) : null;
          const lo = Math.min(a ?? b ?? 0, b ?? a ?? 0), hi = Math.max(a ?? b ?? 0, b ?? a ?? 0);
          return (
            <Link key={g.ind.indicator_id} href={`/indicator/${g.ind.indicator_id}`} className="thennow-row">
              <span className="label">{g.ind.name}</span>
              <span className="then mono">{g.then ? <>{shortValue(g.then.value, g.ind.unit, g.ind.decimals)}<small> {g.then.year}</small></> : "–"}</span>
              <span className="track" title={`${g.then ? `#${g.then.rank} of ${g.then.of} in ${g.then.year}` : "no early figure"}; ${g.now ? `#${g.now.rank} of ${g.now.of} in ${g.now.year}` : "no recent figure"} (highest first)`}>
                {a !== null && b !== null && <i className="span" style={{ left: `${lo}%`, width: `${hi - lo}%` }} />}
                {a !== null && <i className="dot then" style={{ left: `${a}%` }} />}
                {b !== null && <i className="dot now" style={{ left: `${b}%` }} />}
              </span>
              <span className="now mono">{g.now ? <>{shortValue(g.now.value, g.ind.unit, g.ind.decimals)}<small> {g.now.year}</small></> : "–"}</span>
            </Link>
          );
        })}
      </div>
      <p className="caption">Each figure in {st.from} (or the first year after it with a figure) and in its latest year. The track runs from the lowest country
        (left) to the highest (right): the hollow dot is then, the filled dot now. Higher is not always better (infant deaths). Click a row for its page.</p>
    </Frame>
  );
}
