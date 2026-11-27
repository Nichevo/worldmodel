"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Fragment, Suspense, useEffect, useState } from "react";
import AskButton from "@/components/AskButton";
import Flag from "@/components/Flag";
import PlacePicker, { type Place } from "@/components/PlacePicker";
import { entityVar } from "@/lib/look";
import { BY_HAND, STEPS, cellText, scorecardApi, stepOf, type ScoreRow, type Scorecard } from "@/lib/scorecard";

// The Scorecard: life in the countries you pick, measure by measure, in groups (health, health
// care, water and sanitation, environment, work and safety). Each cell is coloured by its rank
// among the countries shown, the best (and any tied with it) starred, and a bar chart counts
// how many measures each country is best at. Which way is better is set per measure.
function ScorecardPage() {
  const router = useRouter();
  const params = useSearchParams();
  const [ids, setIds] = useState<string[]>(() => (params.get("c") ?? "").split(",").filter((x) => /^[A-Za-z0-9_-]{2,20}$/.test(x)));
  const [d, setD] = useState<Scorecard | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [years, setYears] = useState(false);

  useEffect(() => {
    let live = true;
    setErr(null);
    scorecardApi.get(ids).then((x) => live && setD(x)).catch((e) => live && setErr(String(e.message || e)));
    return () => { live = false; };
  }, [ids.join(",")]); // eslint-disable-line react-hooks/exhaustive-deps

  const go = (next: string[]) => {
    setIds(next);
    router.replace(next.length ? `/scorecard?c=${next.join(",")}` : "/scorecard", { scroll: false });
  };

  if (err) return <p className="error">{err}</p>;
  if (!d) return <p className="muted">Loading…</p>;

  const cs = d.countries;
  const places: Place[] = cs.map((c) => ({ id: c.entity_id, name: c.name, group: c.entity_id !== c.entity_id.toUpperCase() }));
  const shown = d.groups.flatMap((g) => g.rows).filter((r) => r.indicator_id).length;
  const most = Math.max(1, ...cs.map((c) => c.wins));
  const title = `Life in ${cs.length <= 3 ? cs.map((c) => c.name).join(", ") : `${cs.length} countries`}`;

  const ask = () => [
    { key: "table", kind: "data" as const, label: "Scorecard",
      text: ["Measure (better)," + cs.map((c) => c.name).join(","),
        ...d.groups.flatMap((g) => g.rows.filter((r) => r.indicator_id).map((r) =>
          `${r.label}, ${r.unit} (${r.better} is better),` + cs.map((c) => { const v = r.cells[c.entity_id]; return v ? `${cellText(r, v.value)} (${v.year})${v.best ? " best" : ""}` : "no data"; }).join(",")))].join("\n") },
    { key: "wins", kind: "data" as const, label: "Measures won", text: cs.map((c) => `${c.name} ${c.wins} of ${c.measures}`).join("; ") },
    { key: "how", kind: "description" as const, label: "How", text: "Each country's latest figure, ranked among the countries shown; ties share a rank and every tied best counts as a win." },
  ];

  const cell = (r: ScoreRow, id: string) => {
    const v = r.cells[id];
    if (!v) return <td key={id} className="sc-cell none">no data</td>;
    const step = stepOf(v.position);
    const tip = [`${cellText(r, v.value)} ${r.percent ? "" : r.unit} in ${v.year}`.replace(/\s+/g, " "),
      `#${v.rank} of ${Object.keys(r.cells).length} shown`, v.world_rank ? `#${v.world_rank} of ${r.world_of} countries` : "",
      r.indicator_name ? `${r.indicator_name} (${r.source})` : ""].filter(Boolean).join("\n");
    return (
      <td key={id} className={`sc-cell sc-${step}${v.best ? " best" : ""}`} title={tip}>
        {cellText(r, v.value)}{v.best ? " ★" : ""}
        {(v.world_rank || (years && v.year) || (r.year && v.year < r.year - 1)) ? (
          <span className="sc-sub">{v.world_rank ? `#${v.world_rank} in world` : ""}{v.world_rank && (years || (r.year && v.year < r.year - 1)) ? " · " : ""}
            {years || (r.year && v.year < r.year - 1) ? v.year : ""}</span>) : null}
      </td>);
  };

  return (
    <div className="grid">
      <div className="title-row">
        <h1>Scorecard</h1>
        <AskButton title={title} parts={ask} />
      </div>
      <p className="muted" style={{ marginTop: -6 }}>
        {d.measures} measures of how people live. Colour is the rank among the countries shown; ★ marks the best (ties count for everyone).
      </p>
      <div className="chips-row small">
        <div style={{ minWidth: 320, flex: "1 1 320px" }}>
          <PlacePicker value={places} placeholder="Type a country or a group" onChange={(ps) => go(ps.map((p) => p.id).slice(0, 12))} />
        </div>
        {d.sets.map((s) => <button key={s.name} className="small" onClick={() => go(s.ids)}>{s.name}</button>)}
        <label className="small"><input type="checkbox" checked={years} onChange={(e) => setYears(e.target.checked)} /> Show years</label>
      </div>

      <div className="card">
        <div className="sc-scroll">
          <table className="sc-table">
            <thead>
              <tr><th />{cs.map((c, i) => (
                <th key={c.entity_id} style={{ ["--colour" as string]: entityVar(c.entity_id, i) }}>
                  <Link href={`/entity/${c.entity_id}`}><Flag id={c.entity_id} />{c.name}</Link></th>))}</tr>
            </thead>
            <tbody>
              {d.groups.map((g) => (
                <Fragment key={g.name}>
                  <tr className="sc-group"><th colSpan={cs.length + 1}>{g.name}</th></tr>
                  {g.rows.map((r) => (
                    <tr key={r.id}>
                      <td className="sc-label" title={`${r.better === "lower" ? "Lower" : "Higher"} is better. ${r.source ?? ""}${r.indicator_id ? ` (${r.indicator_id})` : ""}`}>
                        {r.indicator_id ? <Link href={`/indicator/${r.indicator_id}`}>{r.label}</Link> : r.label}{" "}
                        <span className="muted">{r.unit}{r.better === "lower" ? ", lower is better" : ""}</span></td>
                      {cs.map((c) => (r.indicator_id ? cell(r, c.entity_id) : <td key={c.entity_id} className="sc-cell none">not loaded</td>))}
                    </tr>))}
                </Fragment>))}
            </tbody>
          </table>
        </div>
        <p className="caption">
          Worst<span className="sc-key">{Array.from({ length: STEPS }, (_, i) => <i key={i} className={`sc-${i}`} />)}</span>best.
          Each country&apos;s latest figure; a figure more than six years older than the row&apos;s newest is left out. Hover a cell for its year, source and rank.
          Sources: UN, World Bank (WHO, UNICEF, UNODC), WHO Global Health Estimates and World Happiness Report through Our World in Data, ILO, Walk Free, World Inequality Database, UNDP.
        </p>
      </div>

      <div className="card">
        <div className="card-head"><h3>Measures won</h3><span className="muted small">best or tied best, of the {shown} measures with figures</span></div>
        <div className="sc-wins">
          {cs.map((c, i) => (
            <div key={c.entity_id} className="sc-win">
              <b>{c.wins}</b>
              <div className="bar" style={{ height: `${(c.wins / most) * 100}px`, background: entityVar(c.entity_id, i) }} />
              <span>{c.name}</span>
            </div>))}
        </div>
      </div>

      {d.missing.length > 0 && (
        <div className="card">
          <div className="card-head"><h3>Not loaded yet ({d.missing.length})</h3></div>
          <ul className="small">
            {d.missing.map((m) => (
              <li key={m.id}><b>{m.label}</b> ({m.source}):{" "}
                {m.get && BY_HAND.has(m.get)
                  ? <>save the file by hand in <code>var\manual\{m.get}</code> (<code>.\get.bat</code> opens the page; <Link href="/todo">To do</Link> has the steps), then <code>.\load.bat {m.get}</code></>
                  : <>run <code>.\refresh.bat{m.get ? ` --only ${m.get}` : ""}</code></>}
              </li>))}
          </ul>
        </div>)}
    </div>
  );
}

export default function Page() {
  return <Suspense fallback={<p className="muted">Loading…</p>}><ScorecardPage /></Suspense>;
}
