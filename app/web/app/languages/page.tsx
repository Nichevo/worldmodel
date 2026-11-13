"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useMemo, useState } from "react";
import type { EChartsOption } from "echarts";
import EChart from "@/components/EChart";
import Flag from "@/components/Flag";
import WorldMap from "@/components/WorldMap";
import { api, type EntityLanguages, type Languages } from "@/lib/api";
import CardAsk from "@/components/CardAsk";
import { useKeys } from "@/components/PageLook";
import { openAsk } from "@/lib/ai";
import { chrome } from "@/lib/charts";
import { cssVar, seriesColor } from "@/lib/colors";
import { useEntityNames } from "@/lib/flags";
import { people } from "@/lib/people";

// Languages of the world: the most spoken (first and second language together), where any
// one is spoken and official, and how many languages each country has and is losing.
type Mode = "share" | "count" | "endangered";
const OFFICIAL: Record<number, string> = { 4: "official", 3: "official in practice", 2: "official in a region", 1: "official for a minority" };

function LanguagesPage() {
  const router = useRouter();
  const params = useSearchParams();
  const nameOf = useEntityNames();
  const [d, setD] = useState<Languages | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [lang, setLang] = useState<string | undefined>(params.get("lang") ?? undefined);
  const [mode, setMode] = useState<Mode>((params.get("mode") as Mode) || "share");
  const [typed, setTyped] = useState("");
  const home = useKeys().split(",")[0] || "NZL";
  const [mine, setMine] = useState<EntityLanguages | null>(null);
  useEffect(() => { api.entityLanguages(home).then(setMine).catch(() => setMine(null)); }, [home]);
  useEffect(() => {
    let live = true;
    api.languages(lang, 20).then((x) => { if (live) { setD(x); setError(null); } }).catch((e) => live && setError(String(e.message || e)));
    return () => { live = false; };
  }, [lang]);
  useEffect(() => {
    router.replace(`/languages?${new URLSearchParams({ mode, ...(lang ? { lang } : {}) })}`, { scroll: false });
  }, [lang, mode]); // eslint-disable-line react-hooks/exhaustive-deps
  const top = d?.top ?? [];
  const option = useCallback((): EChartsOption => {
    const base = chrome();
    const rows = [...top].reverse();
    const split = rows.some((r) => r.home != null);
    const dark = (r: (typeof rows)[number]) => (r.code === d?.lang ? seriesColor(2) : seriesColor(0));
    return { ...base, grid: { left: 120, right: 70, top: split ? 28 : 8, bottom: 24 },
      legend: split ? { top: 0, left: 0, textStyle: { color: cssVar("--ink-2") }, data: ["Where it is the main language", "Elsewhere"] } : undefined,
      xAxis: { type: "value", axisLabel: { color: cssVar("--muted"), formatter: (v: number) => people(v).replace(" million", "m").replace(" billion", "bn") },
        splitLine: { lineStyle: { color: cssVar("--grid") } } },
      yAxis: { type: "category", data: rows.map((r) => r.name), axisLabel: { color: cssVar("--ink-2") } },
      tooltip: { ...(base.tooltip as object), trigger: "item", formatter: (p: unknown) => {
        const r = rows[(p as { dataIndex: number }).dataIndex];
        const h = r.home ?? 0;
        return `<b>${r.name}</b><br/>${people(r.speakers)} speakers in ${r.countries} countries<br/>`
          + (split ? `${people(h)} where it is the main language, ${people(r.speakers - h)} elsewhere<br/>` : "") + `official in ${r.official_in}`;
      } },
      series: split ? [
        { type: "bar", name: "Where it is the main language", stack: "s", itemStyle: { color: seriesColor(0) },
          data: rows.map((r) => ({ value: r.home ?? 0, itemStyle: { color: dark(r) } })) },
        { type: "bar", name: "Elsewhere", stack: "s", itemStyle: { color: seriesColor(0), opacity: 0.35 },
          data: rows.map((r) => ({ value: r.speakers - (r.home ?? 0), itemStyle: { color: dark(r), opacity: 0.35 } })),
          label: { show: true, position: "right", color: cssVar("--muted"), formatter: (p: { dataIndex: number }) => people(rows[p.dataIndex].speakers) } },
      ] : [{ type: "bar", data: rows.map((r) => ({ value: r.speakers, itemStyle: { color: dark(r) } })),
        label: { show: true, position: "right", color: cssVar("--muted"), formatter: (p: { value?: unknown }) => people(Number(p.value)) } }] };
  }, [top, d?.lang]);
  const values = useMemo(() => {
    if (!d) return [];
    if (mode === "share") return d.map.map((r) => ({ entity_id: r.entity_id, value: r.share, status: "E" }));
    const k = mode === "count" ? "lang_count" : "lang_endangered";
    return d.counts.filter((c) => c[k] !== undefined).map((c) => ({ entity_id: c.entity_id, value: c[k] as number, status: "E" }));
  }, [d, mode]);
  if (error) return <p className="error">{error}</p>;
  if (!d) return <p className="muted">Loading…</p>;
  if (!top.length && !d.counts.length) {
    return (<div><h1>Languages</h1><p>No language figures loaded yet. Run <code>.\refresh.bat</code>: they come from Unicode CLDR and Glottolog.</p></div>);
  }
  const pick = (v: string) => {
    const hit = d.languages.find((l) => l.name.toLowerCase() === v.toLowerCase() || l.code === v);
    if (hit) { setLang(hit.code); setMode("share"); setTyped(""); }
  };
  const table = mode === "share" ? d.map.slice(0, 40) : [];
  const first = top[0];
  const away = first?.home != null && first.speakers ? Math.round(100 * (1 - first.home / first.speakers)) : null;
  const finding = !first ? "The most spoken languages" : away != null && away >= 50
    ? `${first.name} has the most speakers, but most of them (${away}%) live where it isn't the main language`
    : `${first.name} has the most speakers: ${people(first.speakers)}`;
  const homeNote = mine?.languages.length ? `${home === "NZL" ? "In New Zealand" : `In ${nameOf(home)}`}: ${[...mine.languages].sort((a, b) => (b.share ?? 0) - (a.share ?? 0)).slice(0, 4).map((l) =>
    `${l.name}${l.share != null ? ` ${l.share < 10 ? l.share.toFixed(1) : Math.round(l.share)}%` : ""}${l.official ? ` (${l.official})` : ""}`).join(", ")}.` : "";
  return (
    <div className="grid">
      <div className="title-row">
        <h1>Languages</h1>
        <span className="muted small">Who speaks what, in each country and in the world</span>
      </div>
      <div className="card">
        <div className="card-head"><h3 className="finding">{finding}</h3>
          <CardAsk onAsk={() => openAsk({ title: "The most spoken languages", parts: [{ key: "top", kind: "data", label: "Language, speakers, where main language, countries",
            text: top.map((r) => `${r.name} | ${Math.round(r.speakers)} | ${Math.round(r.home ?? 0)} | ${r.countries}`).join("\n") }] })} /></div>
        <EChart option={option} height={Math.max(240, top.length * 22)} label="The most spoken languages" />
        {homeNote && <p className="small">{homeNote}{mine?.endangered.length ? ` Endangered here: ${mine.endangered.slice(0, 3).map((e) => e.name).join(", ")}.` : ""}</p>}
        <p className="caption">Dark: speakers in countries where it is the main language (mostly people who grew up with it). Light: speakers elsewhere
          (mostly people who learned it; CLDR has no first and second language split of its own, so this is the nearest it allows). First and second language speakers together, from Unicode CLDR&apos;s share of each country&apos;s people times its population.
          Second-language counts vary a lot between sources, so treat these as estimates. Click a bar&apos;s language in the list below to map it.</p>
      </div>
      <div className="card">
        <div className="chips-row small">
          <div className="seg" role="group" aria-label="Colour the map by">
            {([["share", `Who speaks ${d.lang_name}`], ["count", "Languages spoken"], ["endangered", "Endangered languages"]] as [Mode, string][]).map(([m, label]) => (
              <button key={m} className={mode === m ? "on" : ""} aria-pressed={mode === m} onClick={() => setMode(m)}>{label}</button>
            ))}
          </div>
          <label>Language <input list="lang-list" value={typed} placeholder={d.lang_name} onChange={(e) => { setTyped(e.target.value); pick(e.target.value); }}
            aria-label="Pick a language" style={{ width: 160 }} /></label>
          <datalist id="lang-list">{d.languages.map((l) => <option key={l.code} value={l.name} />)}</datalist>
          {top.slice(0, 8).map((l) => <button key={l.code} className={`chip${l.code === d.lang ? " on" : ""}`} onClick={() => { setLang(l.code); setMode("share"); }}>{l.name}</button>)}
        </div>
        <div className="map-box">
          <WorldMap fill values={values} unit={mode === "share" ? "%" : ""} decimals={mode === "share" ? 1 : 0} diverging={false}
            onPick={(iso3) => router.push(`/entity/${iso3}#languages`)} />
        </div>
        <p className="caption">{mode === "share" ? `Share of each country's people who speak ${d.lang_name}, first or second language (CLDR).`
          : mode === "count" ? "Languages spoken in each country (Glottolog); a language spoken in several countries counts in each."
          : "Languages that children no longer learn, or only the oldest people speak (Glottolog, from UNESCO and others)."}</p>
      </div>
      {table.length > 0 && (
        <div className="card">
          <h3>Where {d.lang_name} is spoken</h3>
          <table className="small">
            <thead><tr><th>Country</th><th>Share who speak it</th><th>Status</th></tr></thead>
            <tbody>
              {table.map((r) => (
                <tr key={r.entity_id}>
                  <td><Link href={`/entity/${r.entity_id}#languages`}><Flag id={r.entity_id} />{nameOf(r.entity_id)}</Link></td>
                  <td>{r.share.toFixed(r.share < 10 ? 1 : 0)}%</td>
                  <td className="muted">{r.official ? OFFICIAL[r.official] : ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

export default function Page() {
  return <Suspense fallback={<p className="muted">Loading…</p>}><LanguagesPage /></Suspense>;
}
