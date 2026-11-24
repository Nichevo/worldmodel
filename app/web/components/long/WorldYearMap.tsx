"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import CardAsk from "@/components/CardAsk";
import WorldMap from "@/components/WorldMap";
import { EventDetail, heldBy, RulersStrip, YearEventList, YearEventTools } from "@/components/long/YearEvents";
import type { LongEvent, LongOverview } from "@/lib/api";
import { openAsk } from "@/lib/ai";
import { GROUP_LABEL, KIND_GROUP, kindColor, yl } from "@/lib/long";
import { setMapYear, useMapYear, useWorldIn, useYearEvents, yearMarks } from "@/lib/longYear";
import { useSettings } from "@/lib/settings";

const PICKS = [-3000, -1000, -500, 1, 500, 1000, 1250, 1500, 1700, 1800, 1900, 1914, 1939, 1960, 2024];
const MIN = -3400, MAX = 2024;
const clamp = (y: number) => Math.max(MIN, Math.min(MAX, Math.round(y))) || 1;

// The world's states in any year from 3400 BC to now, from Cliopatria's borders, with a
// slider, quick picks, steps and Play. It shares its year with the main Map's "World in
// year" layer, so either one picks up where the other left off. Click a state for its card.
// Events and beginnings from the years around show as dots (click one for more), with the
// rulers of the biggest states under the map.
export default function WorldYearMap({ o }: { o: LongOverview }) {
  const router = useRouter();
  const year = useMapYear();
  const [playing, setPlaying] = useState(0); // years a second, 0 when stopped
  const areas = useWorldIn(true, year);
  const { events, window: win } = useYearEvents(true, year);
  const labels = useSettings().history_map_labels ?? 10;
  const [picked, setPicked] = useState<LongEvent | null>(null);
  const marks = useMemo(() => yearMarks(events, year, win, playing ? Math.min(labels, 5) : labels), [events, year, win, labels, playing]);
  const onMark = (key: string) => setPicked(events.find((e) => e.event_id === key) ?? null);
  const groups = useMemo(() => [...new Set(events.map((e) => KIND_GROUP[e.kind]))].filter(Boolean), [events]);
  useEffect(() => {
    if (!playing) return;
    const t = setInterval(() => {
      const next = clamp(year + playing / 2);
      setMapYear(next);
      if (next >= MAX) setPlaying(0);
    }, 500);
    return () => clearInterval(t);
  }, [playing, year]);
  // A state's empire (its "whole") to the power with a card, by name.
  const powerOf = useMemo(() => new Map(o.powers.filter((p) => p.has_borders).map((p) => [p.name.toLowerCase(), p.id])), [o]);
  const onArea = (key: string) => {
    const f = areas?.data.features.find((x) => x.properties?.key === key);
    const whole = String(f?.properties?.whole ?? f?.properties?.name ?? "").toLowerCase();
    const id = powerOf.get(whole);
    if (id) router.push(`/long/empire/${id}`);
  };
  if (!o.counts.polities) {
    return <div className="card"><h3>The world in any year</h3><p className="small">No borders stored yet. They come with <code>.\refresh.bat</code> (Seshat&apos;s
      Cliopatria; switch in <Link href="/settings#long-history">Settings &gt; Long history</Link>).</p></div>;
  }
  const names = (areas?.data.features ?? []).map((f) => String(f.properties?.whole ?? f.properties?.name ?? ""));
  const states = [...new Set(names)].slice(0, 40).join(", ");
  const known = [...events].sort((a, b) => (b.links ?? 0) - (a.links ?? 0)).slice(0, 25).map((e) => `${e.when}: ${e.title}`).join("; ");
  return (
    <div className="card">
      <div className="card-head">
        <h3>The world in {yl(year)}</h3>
        <CardAsk onAsk={() => openAsk({ title: `The world in ${yl(year)}`, parts: [
          { key: "description", kind: "description", label: "What the map shows", text: `States and empires with known borders in ${yl(year)}, from Seshat's Cliopatria.` },
          { key: "data", kind: "data", label: "States on the map", text: states },
          ...(known ? [{ key: "events", kind: "data" as const, label: `Events within ${win} years`, text: known }] : []),
        ] })} />
      </div>
      <div className="long-tools">
        <label className="small">Jump to <select value={PICKS.includes(year) ? year : ""} onChange={(e) => e.target.value && setMapYear(+e.target.value)}>
          <option value="">…</option>
          {PICKS.map((y) => <option key={y} value={y}>{yl(y)}</option>)}
        </select></label>
        {[-100, -10, 10, 100].map((d) => (
          <button key={d} className="chip small" onClick={() => setMapYear(clamp(year + d))}>{d > 0 ? `+${d}` : `−${-d}`} years</button>
        ))}
      </div>
      <YearEventTools />
      <WorldMap values={[]} unit="" decimals={0} diverging={false} hideScale onPick={() => {}} areas={areas} onArea={onArea}
        marks={marks} onMark={onMark}
        legend={groups.map((g) => ({ label: GROUP_LABEL[g], color: kindColor(Object.keys(KIND_GROUP).find((k) => KIND_GROUP[k] === g)!), shape: "dot" as const }))} />
      <div className="long-slider">
        <button onClick={() => setPlaying(playing ? 0 : 25)} aria-pressed={!!playing}>{playing ? "Pause" : "Play"}</button>
        <select value={playing || 25} onChange={(e) => playing && setPlaying(+e.target.value)} aria-label="Speed">
          <option value={10}>10 years a second</option><option value={25}>25 years a second</option><option value={100}>100 years a second</option>
        </select>
        <input type="range" min={MIN} max={MAX} value={year} onChange={(e) => setMapYear(+e.target.value)} aria-label="Year" style={{ flex: 1 }} />
        <b style={{ minWidth: 90 }}>{yl(year)}</b>
        <span className="small muted">{areas ? `${areas.count.toLocaleString("en")} states` : "Loading…"}{events.length ? ` · ${events.length} events` : ""}</span>
      </div>
      <RulersStrip year={year} />
      {(picked || events.length > 0) && (
        <div className="long-year-below">
          {picked ? <EventDetail e={picked} year={year} held={heldBy(areas?.data, picked)} onClose={() => setPicked(null)} />
            : <p className="small muted">Click a dot, or a name in the list, for more about it.</p>}
          <YearEventList events={events} pick={setPicked} picked={picked?.event_id ?? null} />
        </div>
      )}
      <p className="caption">Each state&apos;s borders in that year from Seshat&apos;s Cliopatria, coloured by the empire it belonged to. Hover for its name,
        years and ruler; click for the empire&apos;s card where it has one. Thin before 500 BC, and the Pacific only from the 1870s. Dots are
        events and beginnings from {win} years either side, fainter the further from {yl(year)}, bigger for the better known: battles, wars and
        treaties, famous buildings and great works, cities founded (Wikidata, by articles in enough Wikipedias), religions, writing and
        languages (Wikidata and a typed-in list, many dates rough), and disasters and disease (NOAA, Wikidata) when ticked. Rulers are
        Wikidata&apos;s kings, queens, emperors and others with articles in 25+ Wikipedias. The same year shows on the
        main <Link href="/">Map</Link> under Layers &gt; World in year.</p>
    </div>
  );
}
