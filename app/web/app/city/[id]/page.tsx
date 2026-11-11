"use client";

import Link from "next/link";
import CityLandCard from "@/components/CityLandCard";
import PlacesCard from "@/components/PlacesCard";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";
import AskButton from "@/components/AskButton";
import { Picture } from "@/components/CountryAbout";
import EChart from "@/components/EChart";
import NumbeoPrices from "@/components/NumbeoPrices";
import WorldMap from "@/components/WorldMap";
import { api, type CityDetail, type CitySeries, type Wikipedia } from "@/lib/api";
import { cityPoints, cityPopulation, people } from "@/lib/cities";
import { cssVar, seriesColor } from "@/lib/colors";
import { formatValue } from "@/lib/format";
import { logHistory } from "@/lib/history";

// One city: Wikipedia's introduction and photo, population since 1950 with the UN
// projection to 2035, cost of living and quality figures, Numbeo's everyday prices on
// request, and the country's other big cities.
export default function CityPage() {
  const { id } = useParams<{ id: string }>();
  const [d, setD] = useState<CityDetail | null>(null);
  const [wiki, setWiki] = useState<Wikipedia | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setD(null); setWiki(null); setError(null);
    api.city(id).then((x) => {
      setD(x);
      logHistory({ kind: "page", title: `${x.city.name}, ${x.city.country ?? x.city.country_id}`, url: `/city/${id}`, entity: x.city.country_id, detail: "city" });
    }).catch((e) => setError(String(e.message || e)));
    api.cityWikipedia(id).then(setWiki).catch(() => setWiki(null));
  }, [id]);

  const pop = d?.series.find((s) => s.indicator_id === "city_population");
  const facts = d?.series.filter((s) => s.indicator_id !== "city_population" && !s.indicator_id.startsWith("ghsl_")) ?? [];
  const points = useMemo(() => (d ? cityPoints([d.city, ...d.others], d.city.city_id) : []), [d]);

  if (error) return <p className="error">{error.replace(/^404: /, "")}</p>;
  if (!d) return <p className="muted">Loading…</p>;
  const c = d.city;
  const best = cityPopulation(c);
  const page = wiki?.page;
  const photo = page?.images.find((i) => i.role === "photo" && i.src);
  const latest = (s: CitySeries) => s.points[s.points.length - 1];
  const title = `${c.name}, ${c.country ?? c.country_id}`;

  return (
    <div className="grid">
      <div>
        <p className="small muted" style={{ margin: 0 }}>
          <Link href="/cities">Cities</Link> · <Link href={`/cities?country=${c.country_id}`}>{c.country ?? c.country_id}</Link>
          {c.admin1 ? ` · ${c.admin1}` : ""}
        </p>
        <div className="title-row">
          <h1 style={{ marginBottom: 4 }}>{c.name}{c.capital === "national" && <span className="city-tag">capital</span>}</h1>
          <AskButton title={title} entity={c.country_id} parts={() => [
            { key: "facts", kind: "data", label: `${title}: figures`, text: [
              `City,${title}`, `Population,${best.value ?? ""} (${best.note})`,
              ...d.series.flatMap((s) => s.points.map((p) => `${s.name} (${s.unit}),${p.year},${+p.value.toPrecision(6)}${p.status === "P" ? ",projection" : ""}`))].join("\n") },
            ...(page ? [{ key: "wiki", kind: "page" as const, label: "Wikipedia introduction", text: page.extract }] : []),
          ]} />
        </div>
        <div className="ind-facts">
          <div><b>People</b>{people(best.value)} <span className="small muted">({best.note})</span></div>
          {c.population_2035 && <div><b>2035 (UN projection)</b>{people(c.population_2035)}</div>}
          {c.elevation !== null && <div><b>Height</b>{Math.round(c.elevation)} m</div>}
          {c.timezone && <div><b>Time zone</b>{c.timezone.replace(/_/g, " ")}</div>}
          <div><b>Location</b>{c.lat.toFixed(2)}, {c.lon.toFixed(2)}</div>
        </div>
      </div>

      <div className="card about">
        <div className="about-text">
          <h3>About{page?.description ? <span className="small ink-2"> · {page.description}</span> : null}</h3>
          {page ? (
            <>
              {page.extract.split(/\n+/).filter(Boolean).map((p, i) => <p key={i}>{p}</p>)}
              <p className="caption">
                {page.url && <><a href={page.url} target="_blank" rel="noreferrer">Read more on Wikipedia</a> · </>}
                {page.licence} · copy from {page.fetched_at.slice(0, 10)}, refreshed monthly
              </p>
            </>
          ) : (
            <p className="small ink-2">{wiki?.message ?? (wiki ? "No Wikipedia introduction stored yet." : "Loading…")}</p>
          )}
          {wiki?.message && page && <p className="caption">{wiki.message}</p>}
          {wiki && <p className="caption">Wikipedia city pages: {wiki.budget.used} of today&apos;s {wiki.budget.limit} fetched (Settings).</p>}
        </div>
        <div className="about-side">
          {photo && <Picture img={photo} wide />}
          <div className="city-map small">
            <WorldMap fill values={[]} unit="" decimals={0} diverging={false} onPick={() => {}} points={points} fitPoints />
          </div>
        </div>
      </div>

      <div className="grid two">
        {pop && pop.points.length > 1 && <PopulationChart s={pop} name={c.name} />}
        {facts.length > 0 && (
          <section className="card">
            <h3>Cost of living and quality</h3>
            <table className="summary-table">
              <tbody>
                {facts.map((s) => (
                  <tr key={s.indicator_id} title={s.description}>
                    <td>{s.name}</td>
                    <td className="num"><b>{formatValue(latest(s).value, "", s.decimals)}</b>{s.unit === "US$" ? " US$" : ""}</td>
                    <td className="small muted">{latest(s).year}{s.source_name && s.source_name !== c.name ? ` · as "${s.source_name}"` : ""}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="caption">Hover a row for what it measures. Numbeo indices: New York = 100.</p>
          </section>
        )}
      </div>

      <CityLandCard cityId={c.city_id} name={c.name} />

      <section className="card">
        <h3>Everyday prices</h3>
        <NumbeoPrices kind="cities" id={c.city_id} place={c.name} />
      </section>

      {d.places && d.places.length > 0 && <PlacesCard city={c.city_id} rows={d.places} name={c.name} />}

      {d.others.length > 0 && (
        <section className="card">
          <h3>Other cities in {c.country ?? c.country_id}</h3>
          <p>
            {d.others.map((o, i) => (
              <span key={o.city_id}>{i > 0 && " · "}<Link href={`/city/${o.city_id}`}>{o.name}</Link>
                <span className="small muted"> {people(cityPopulation(o).value)}</span></span>
            ))}
          </p>
          <p className="caption"><Link href={`/cities?country=${c.country_id}`}>Every city in {c.country ?? c.country_id}</Link> · <Link href={`/entity/${c.country_id}`}>Country page</Link></p>
        </section>
      )}
    </div>
  );
}

function PopulationChart({ s, name }: { s: CitySeries; name: string }) {
  const option = useCallback(() => {
    const est = s.points.map((p) => (p.status === "P" ? null : p.value));
    // The projection starts from the last estimate, so the two lines join.
    const lastE = s.points.map((p) => p.status).lastIndexOf("E");
    const proj = s.points.map((p, i) => (p.status === "P" || i === lastE ? p.value : null));
    return {
      backgroundColor: "transparent",
      textStyle: { fontFamily: "system-ui, -apple-system, 'Segoe UI', sans-serif", color: cssVar("--ink-2") },
      grid: { left: 8, right: 16, top: 20, bottom: 8, containLabel: true },
      xAxis: { type: "category" as const, data: s.points.map((p) => String(p.year)), axisLabel: { color: cssVar("--muted") },
        axisLine: { lineStyle: { color: cssVar("--axis") } } },
      yAxis: { type: "value" as const, axisLabel: { color: cssVar("--muted"), formatter: (v: number) => people(v) },
        splitLine: { lineStyle: { color: cssVar("--border") } } },
      tooltip: { trigger: "axis" as const, backgroundColor: cssVar("--surface"), borderColor: cssVar("--border"), textStyle: { color: cssVar("--ink") },
        valueFormatter: (v: unknown) => (typeof v === "number" ? `${people(v)} people` : "") },
      series: [
        { type: "line" as const, name: "Estimate", data: est, color: seriesColor(0), symbolSize: 5, connectNulls: false },
        { type: "line" as const, name: "UN projection", data: proj, color: seriesColor(0), symbolSize: 5, lineStyle: { type: "dashed" as const } },
      ],
    };
  }, [s]);
  return (
    <section className="card">
      <h3>People in {name} and its suburbs</h3>
      <EChart option={option} height={260} label={`Population of ${name}`} />
      <p className="caption">{s.description} Dashed: projection. Source: {s.source}.</p>
    </section>
  );
}
