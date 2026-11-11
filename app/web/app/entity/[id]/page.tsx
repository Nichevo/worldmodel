"use client";

import Help from "@/components/Help";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import AskButton from "@/components/AskButton";
import ChartCard from "@/components/ChartCard";
import CitiesCard from "@/components/CitiesCard";
import CountryAbout from "@/components/CountryAbout";
import DebtCard from "@/components/DebtCard";
import EducationCard from "@/components/EducationCard";
import EnergyFlowCard from "@/components/EnergyFlowCard";
import EnergyMix from "@/components/EnergyMix";
import FactbookCard from "@/components/FactbookCard";
import HousingCard from "@/components/HousingCard";
import MigrationCard from "@/components/MigrationCard";
import PlacesCard from "@/components/PlacesCard";
import ProfilePicker from "@/components/ProfilePicker";
import PricesPayCard from "@/components/PricesPayCard";
import VotersCard from "@/components/VotersCard";
import VotingCard from "@/components/VotingCard";
import BetweenCard from "@/components/BetweenCard";
import CrisisWatchCard from "@/components/CrisisWatchCard";
import LawsCard from "@/components/LawsCard";
import HolidaysCard from "@/components/HolidaysCard";
import CrimeCard from "@/components/CrimeCard";
import LanguagesCard from "@/components/LanguagesCard";
import ReadingCard from "@/components/ReadingCard";
import ReligionCard from "@/components/ReligionCard";
import LongViewCard from "@/components/long/LongViewCard";
import ClimateCard from "@/components/ClimateCard";
import InternetCard from "@/components/InternetCard";
import CurrencyCard from "@/components/CurrencyCard";
import RegionsCard from "@/components/RegionsCard";
import DiscoverCard from "@/components/DiscoverCard";
import Flag from "@/components/Flag";
import LatestOn from "@/components/LatestOn";
import Timeline from "@/components/Timeline";
import Pyramid from "@/components/Pyramid";
import { api, type Divergence, type EntityDetail, type Indicator, type ProfileRow } from "@/lib/api";
import { formatValue, SOURCE_LABEL, SOURCE_SHORT } from "@/lib/format";
import { KINDS, kindVar, useChartEvents, useProfileKinds } from "@/lib/events";
import { useGovernments } from "@/lib/parties";
import { saveSettings, useSettings } from "@/lib/settings";
import { logHistory } from "@/lib/history";
import { eventsText, type AskPart } from "@/lib/ai";

const CHARTS: { id: string; kind?: "line" | "bar" }[] = [
  { id: "pop_total" },
  { id: "tfr" },
  { id: "life_expectancy" },
  { id: "median_age" },
  { id: "pop_share_65_plus" },
  { id: "old_age_dependency_ratio" },
  { id: "net_migration_rate" },
  { id: "gdp_growth", kind: "bar" },
  { id: "gdp_per_capita_usd" },
  { id: "unemployment" },
  { id: "military_spending_gdp" },
  { id: "renewables_share_elec" },
  { id: "co2_per_capita" },
];

const CHART_KIND: Record<string, "line" | "bar"> = Object.fromEntries(CHARTS.filter((c) => c.kind).map((c) => [c.id, c.kind!]));

// The country page after the charts, in this order.
const SECTIONS = [
  { key: "people", title: "People" },
  { key: "money", title: "Money, prices and housing" },
  { key: "places", title: "Cities, places and the internet" },
  { key: "energy", title: "Energy" },
  { key: "climate", title: "Climate" },
  { key: "world", title: "In the world: votes, dealings and conflict watch" },
  { key: "laws", title: "Laws, holidays and crime" },
  { key: "history", title: "History, events and sources" },
];

const TYPE_LABEL: Record<string, string> = {
  country: "Country or area", historical_country: "Former state", world: "World", continent: "Continent",
  subregion: "UN sub-region", intermediate_region: "UN region", bloc: "Bloc", alliance: "Alliance", group: "Group", income_group: "Income group",
  zone: "Beyond borders", organisation: "International organisation", armed_group: "Armed group", subnational: "Region within a country",
};

export default function EntityPage() {
  const { id } = useParams<{ id: string }>();
  const [entity, setEntity] = useState<EntityDetail | null>(null);
  const [profile, setProfile] = useState<ProfileRow[]>([]);
  const [indicators, setIndicators] = useState<Indicator[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setEntity(null);
    api.entity(id).then((e) => {
      setEntity(e);
      logHistory({ kind: "page", title: e.short_name, url: `/entity/${e.entity_id}`, entity: e.entity_id, detail: "profile" });
    }).catch((e) => setError(String(e.message || e)));
    api.profile(id).then(setProfile).catch(() => setProfile([]));
  }, [id]);
  useEffect(() => {
    api.indicators().then(setIndicators);
  }, []);

  const named = useMemo(() => (entity ? [{ id: entity.entity_id, name: entity.short_name }] : []), [entity]);
  const byId = useMemo(() => new Map(indicators.map((i) => [i.indicator_id, i])), [indicators]);
  const settings = useSettings();
  const [profileKinds, setProfileKinds] = useProfileKinds();
  const [picker, setPicker] = useState(false);
  const chartEvents = useChartEvents(entity ? [entity.entity_id] : [], profileKinds ?? undefined);
  const terms = useGovernments(entity?.entity_id ?? null, settings.party_colours, settings.party_office);

  if (error) return <p className="error">{error}</p>;
  if (!entity) return <p className="muted">Loading…</p>;
  // The chosen group's average beside the country, on charts of rates and shares only: a group's
  // total (its population, say) would flatten the country's line.
  const avg = !["country", "historical_country"].includes(entity.type) ? null
    : averageChoices(entity).find((g) => g.id === settings.profile_average) ?? null;
  const withAverage = (ind: Indicator) => (avg && avg.id !== entity.entity_id && ind.agg_method !== "sum" && ind.agg_method !== "none"
    ? [...named, { id: avg.id, name: `${avg.name} average` }] : named);
  const isGroup = !["country", "historical_country"].includes(entity.type);
  // The cards below the charts, by section; each hides itself when there is nothing to show,
  // and the "Choose charts and cards" panel can switch any of them off.
  const e = entity.entity_id, nm = entity.short_name;
  const cards: { key: string; title: string; section: string; on: boolean; el: React.ReactNode }[] = [
    { key: "migration", title: "Migration in and out", section: "people", on: true, el: <MigrationCard entity={e} name={nm} indicators={byId} /> },
    { key: "education", title: "Education", section: "people", on: true, el: <EducationCard entity={e} name={nm} indicators={byId} /> },
    { key: "religion", title: "Religion", section: "people", on: !isGroup, el: <ReligionCard entity={e} name={nm} /> },
    { key: "languages", title: "Languages", section: "people", on: !isGroup, el: <LanguagesCard entity={e} name={nm} /> },
    { key: "voters", title: "Who votes", section: "people", on: !isGroup, el: <VotersCard entity={e} name={nm} indicators={byId} /> },
    { key: "currency", title: "Currency", section: "money", on: !isGroup || e === "eu", el: <CurrencyCard entity={e} name={nm} /> },
    { key: "debt", title: "Debt", section: "money", on: !isGroup, el: <DebtCard entity={e} name={nm} indicators={byId} /> },
    { key: "housing", title: "House prices and household debt", section: "money", on: true, el: <HousingCard entity={e} name={nm} indicators={byId} /> },
    { key: "prices", title: "Prices and pay", section: "money", on: !isGroup, el: <PricesPayCard entity={e} name={nm} indicators={byId} /> },
    { key: "regions", title: "Regions", section: "places", on: !isGroup, el: <RegionsCard entity={e} name={nm} /> },
    { key: "cities", title: "Major cities", section: "places", on: !isGroup, el: <CitiesCard entity={e} name={nm} /> },
    { key: "places", title: "Transport, universities and companies", section: "places", on: !isGroup, el: <PlacesCard country={e} name={nm} /> },
    { key: "internet", title: "Internet", section: "places", on: true, el: <InternetCard entity={e} name={nm} indicators={byId} /> },
    { key: "energy_mix", title: "Energy mix", section: "energy", on: true, el: <EnergyMix entity={e} name={nm} indicators={byId} /> },
    { key: "energy_flow", title: "Energy flow", section: "energy", on: !isGroup && !!byId.get("energy_balance_pj")?.available, el: <EnergyFlowCard entity={e} name={nm} /> },
    { key: "climate", title: "Climate", section: "climate", on: !isGroup || e === "world", el: <ClimateCard entity={e} name={nm} /> },
    { key: "voting", title: "UN voting", section: "world", on: !isGroup, el: <VotingCard entity={e} name={nm} /> },
    { key: "between", title: "Between countries", section: "world", on: !isGroup || e === "eu", el: <BetweenCard entity={e} name={nm} /> },
    { key: "crisiswatch", title: "CrisisWatch", section: "world", on: !isGroup, el: <CrisisWatchCard entity={e} name={nm} /> },
    { key: "laws", title: "Laws and rules", section: "laws", on: !isGroup, el: <LawsCard entity={e} name={nm} /> },
    { key: "holidays", title: "Public holidays", section: "laws", on: !isGroup, el: <HolidaysCard entity={e} name={nm} /> },
    { key: "crime", title: "Crime and prisons", section: "laws", on: !isGroup, el: <CrimeCard entity={e} name={nm} indicators={byId} /> },
    { key: "timeline", title: "Timeline of events", section: "history", on: true, el: <Timeline entity={e} name={nm} isGroup={isGroup} /> },
    { key: "long_view", title: "The long view", section: "history", on: !isGroup || e === "world", el: <LongViewCard entity={e} name={nm} /> },
    { key: "factbook", title: "CIA World Factbook", section: "history", on: !isGroup, el: <FactbookCard entity={e} /> },
    { key: "sources_differ", title: "Where sources disagree", section: "history", on: !isGroup, el: <SourcesDiffer entity={e} /> },
    { key: "reading", title: "Reading list", section: "history", on: entity.type === "country", el: <ReadingCard entity={entity} /> },
  ];
  const hidden = (settings.profile_cards_hidden ?? "").split(",").filter(Boolean);
  const show = (key: string) => !hidden.includes(key);
  const chartIds = settings.profile_charts === "none" ? [] : settings.profile_charts ? settings.profile_charts.split(",") : CHARTS.map((c) => c.id);

  return (
    <div className="grid">
      <div>
        <div className="title-row">
          <h1><Flag id={entity.entity_id} size={30} />{entity.short_name}</h1>
          <AskButton title={entity.short_name} entity={entity.entity_id} parts={() => {
            const parts: AskPart[] = [{ key: "data", kind: "data", label: "Key figures (latest of each)",
              text: ["Indicator,Value,Unit,Year,Source", ...profile.map((p) => `"${p.name}",${+p.value.toPrecision(6)},"${p.unit}",${p.period},${SOURCE_LABEL[p.source_id] ?? p.source_id}`)].join("\n") }];
            parts.push({ key: "description", kind: "description", label: `About ${entity.short_name}`,
              text: [`${entity.name} (${TYPE_LABEL[entity.type] ?? entity.type}).`, entity.description ?? "",
                entity.groups.length ? `Member of: ${entity.groups.map((g) => g.short_name).join(", ")}.` : "",
                entity.members.length ? `Members: ${entity.members.map((m) => m.short_name).join(", ")}.` : ""].filter(Boolean).join("\n") });
            if (chartEvents.length) parts.push({ key: "events", kind: "events", label: "Events", text: eventsText(chartEvents) });
            return parts;
          }} />
        </div>
        <div className="ink-2">
          {TYPE_LABEL[entity.type] ?? entity.type}
          {entity.name !== entity.short_name ? ` · ${entity.name}` : ""}
          {entity.valid_to ? ` · existed until ${entity.valid_to}` : ""}
          {!entity.valid_to && (entity.type === "country" || entity.type === "world") && (
            <> · <Link href={`/forecasts?e=${entity.entity_id}`}>Population what-if</Link>
              {" · "}<Link href={`/forecasts?e=${entity.entity_id}&tab=track`}>Forecast track record</Link>{" · "}<Link href={`/forecasts?e=${entity.entity_id}&tab=stat`}>Statistical forecast</Link></>
          )}
        </div>
        {entity.description && <p className="ink-2 small">{entity.description}</p>}
        {entity.groups.length > 0 && (
          <div style={{ marginTop: 8 }}>
            {entity.groups.map((g) => (
              <Link key={g.entity_id} href={`/entity/${g.entity_id}`} className="chip"><Flag id={g.entity_id} size={12} />{g.short_name}</Link>
            ))}
          </div>
        )}
        {entity.successions.length > 0 && (
          <p className="small ink-2">
            {entity.successions.map((s, i) => (
              <span key={i}>
                {s.predecessor_id === entity.entity_id
                  ? <>Succeeded by <Link href={`/entity/${s.successor_id}`}>{s.successor_id}</Link></>
                  : <>Formed from <Link href={`/entity/${s.predecessor_id}`}>{s.predecessor_id}</Link></>}
                {` (${s.kind}, ${s.date})`}{i < entity.successions.length - 1 ? "; " : ""}
              </span>
            ))}
          </p>
        )}
        <p style={{ marginTop: 8 }}>
          <Link href={`/compare?ids=${entity.entity_id}`}>Compare with others →</Link>
        </p>
      </div>

      {!isGroup && settings.profile_cards_hidden.split(",").indexOf("latest") < 0 && <LatestOn entity={entity.entity_id} name={entity.short_name} />}

      <CountryAbout entity={entity.entity_id} />

      {profile.length > 0 && (
        <div className="tiles">
          {profile.map((p) => (
            <div className="card tile" key={p.indicator_id}>
              <div className="label">{p.name}</div>
              <div className="value">{formatValue(p.value, p.unit, p.decimals)}</div>
              <div className="meta">{p.period} · {SOURCE_SHORT[p.source_id] ?? p.source_id}{p.is_aggregate ? " · built from members" : ""}</div>
            </div>
          ))}
        </div>
      )}

      {isGroup && entity.members.length > 0 && (
        <div className="card">
          <h3>Members today ({entity.members.length}) <Help note="members" /></h3>
          <div>
            {entity.members.map((m) => (
              <Link key={m.entity_id} href={`/entity/${m.entity_id}`} className="chip"><Flag id={m.entity_id} size={12} />{m.short_name}</Link>
            ))}
          </div>
          {entity.membership_history.length > 0 && (
            <details style={{ marginTop: 8 }}>
              <summary className="small">Membership changes over time</summary>
              <table>
                <thead><tr><th>Member</th><th>Joined</th><th>Left</th></tr></thead>
                <tbody>
                  {entity.membership_history.map((m, i) => (
                    <tr key={i}><td>{m.short_name}</td><td>{m.valid_from ?? ""}</td><td>{m.valid_to ?? ""}</td></tr>
                  ))}
                </tbody>
              </table>
            </details>
          )}
          <p className="caption">Group values are built from the members of each year, so a 1990 value uses the members of 1990.</p>
        </div>
      )}

      {show("discover") && <DiscoverCard entity={e} name={nm} />}

      <h2 className="section-head" id="charts">Charts</h2>
      <div className="charts-bar small">
        <button onClick={() => setPicker(true)} title="Tick which charts and cards this page shows">Choose charts and cards…</button>
        <label title="Recession bands, election lines and the other events on these charts (Settings: Events on charts)">
          <input type="checkbox" checked={settings.events_on_charts} onChange={(e) => saveSettings({ events_on_charts: e.target.checked })} />
          {" "}Show events on charts
        </label>
        <label title="Years after the latest estimate, drawn dashed (Settings: Events on charts)">
          <input type="checkbox" checked={settings.projections_on_charts} onChange={(e) => saveSettings({ projections_on_charts: e.target.checked })} />
          {" "}Show projected years
        </label>
        {!isGroup && (
          <label title="Colour these charts by the party in office (Settings: Governing party)">
            <input type="checkbox" checked={settings.party_colours} onChange={(e) => saveSettings({ party_colours: e.target.checked })} />
            {" "}Colour by governing party
          </label>
        )}
        {!isGroup && settings.party_colours && (
          <span className="seg" role="group" aria-label="Whose party">
            <button className={settings.party_office === "government" ? "on" : ""} aria-pressed={settings.party_office === "government"}
              onClick={() => saveSettings({ party_office: "government" })}>Head of government</button>
            <button className={settings.party_office === "state" ? "on" : ""} aria-pressed={settings.party_office === "state"}
              onClick={() => saveSettings({ party_office: "state" })}>Head of state</button>
          </span>
        )}
        {!isGroup && (
          <label title="Add a group's average to the charts of rates and shares (totals such as population are left alone)">
            Add the average of{" "}
            <select value={settings.profile_average} onChange={(e) => saveSettings({ profile_average: e.target.value })}>
              <option value="">no group</option>
              {averageChoices(entity).map((g) => <option key={g.id} value={g.id}>{g.name}</option>)}
            </select>
          </label>
        )}
        {!isGroup && settings.party_colours && !terms.length && <span className="muted">No leaders stored for {entity.short_name} yet; a refresh loads them from Wikidata.</span>}
        {!isGroup && settings.party_colours && terms.length > 0 && !terms.some((t) => t.party !== "No party") &&
          <span className="muted">Wikidata gives no party for these leaders{settings.party_office === "state" ? " (heads of state are often non-party)" : ""}.</span>}
      </div>
      {settings.events_on_charts && (
        <EventChips kinds={profileKinds ?? settings.event_kinds} own={profileKinds !== null} set={setProfileKinds} />
      )}
      <div className="grid two">
        {chartIds.map((id) => {
          const ind = byId.get(id);
          return ind && ind.available
            ? <ChartCard key={id} indicator={ind} entities={withAverage(ind)} kind={CHART_KIND[id]} events={chartEvents}
              parties={isGroup || withAverage(ind).length > 1 ? [] : terms} /> : null;
        })}
        {show("pyramid") && byId.get("pop_by_age_sex")?.available && (
          <div className="card">
            <h3>Population by age and sex <Help note="pyramid" /></h3>
            <Pyramid entity={entity.entity_id} name={entity.short_name} />
            <p className="caption">Source: {SOURCE_LABEL.un_wpp}. Five-year age groups on 1 July.</p>
          </div>
        )}
      </div>

      {SECTIONS.map((sec) => {
        const here = cards.filter((c) => c.section === sec.key && c.on && show(c.key));
        if (!here.length) return null;
        return (
          <section key={sec.key} className="profile-section" id={sec.key}>
            <h2 className="section-head">{sec.title}</h2>
            {here.map((c) => <div key={c.key}>{c.el}</div>)}
          </section>
        );
      })}

      <ProfilePicker open={picker} onClose={() => setPicker(false)} indicators={indicators} charts={chartIds}
        defaults={CHARTS.map((c) => c.id)} setCharts={(ids) => saveSettings({ profile_charts: ids.join(",") || "none" })}
        cards={[{ key: "discover", title: "Discover: top finds" }, { key: "pyramid", title: "Population by age and sex" }, ...cards.filter((c) => c.on).map(({ key, title }) => ({ key, title }))]}
        hidden={hidden} setHidden={(keys) => saveSettings({ profile_cards_hidden: keys.join(",") })} />
    </div>
  );
}

// Indicators where this country's sources disagree in their latest common year.
function SourcesDiffer({ entity }: { entity: string }) {
  const [rows, setRows] = useState<Divergence[] | null>(null);
  useEffect(() => {
    setRows(null);
    api.divergence({ entity, flagged: true }).then(setRows).catch(() => setRows([]));
  }, [entity]);
  if (!rows?.length) return null;
  return (
    <details className="card">
      <summary><b>Where sources disagree</b> <Help note="sources_differ" /> <span className="small ink-2">({rows.length} indicator{rows.length > 1 ? "s" : ""})</span></summary>
      <div style={{ overflowX: "auto" }}>
        <table>
          <thead><tr><th>Indicator</th><th className="num">Year</th><th className="num">Default source</th><th className="num">Other</th><th className="num">Apart</th></tr></thead>
          <tbody>
            {rows.map((r) => (
              <tr key={`${r.indicator_id}-${r.source_b}`}>
                <td><Link href={`/sources?ind=${r.indicator_id}&e=${entity}`}>{r.indicator_name}</Link></td>
                <td className="num">{r.year}</td>
                <td className="num" title={r.source_a_name}>{formatValue(r.value_a, r.unit, r.decimals)}</td>
                <td className="num" title={r.source_b_name}>{formatValue(r.value_b, r.unit, r.decimals)}</td>
                <td className="num">{r.rel === null ? "" : `${Math.round(r.rel * 100)}%`}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="caption">Each indicator&apos;s latest year with figures from both sources. Open one to see the sources side by side.</p>
    </details>
  );
}

// Which kinds of event show as bands on this page's charts. The choice is kept in
// this browser for every country page; "As in Settings" goes back to the default.
function EventChips({ kinds, own, set }: { kinds: string; own: boolean; set: (k: string | null) => void }) {
  const picked = kinds.split(",").filter(Boolean);
  return (
    <div className="chips-row small event-chips" role="group" aria-label="Events shown on charts">
      <span className="ink-2">Which events:</span>
      {KINDS.map((k) => {
        const lit = picked.includes(k.kind);
        const next = (lit ? picked.filter((x) => x !== k.kind) : [...picked, k.kind]).join(",");
        return (
          <button key={k.kind} className={`chip kind ${lit ? "" : "off"}`} aria-pressed={lit} style={{ borderColor: kindVar(k.kind) }}
            onClick={() => set(next)}>
            <i style={{ background: kindVar(k.kind) }} />{k.label}
          </button>
        );
      })}
      <button className="link" onClick={() => set("")} disabled={!picked.length}>None</button>
      {own && <button className="link" onClick={() => set(null)} title="Use the kinds ticked in Settings">As in Settings</button>}
    </div>
  );
}

// Groups whose average a country page can show: the world, the OECD and G20, and the
// country's own regions, blocs and income group.
const AVERAGE_FIRST = [{ id: "world", name: "World" }, { id: "oecd", name: "OECD" }, { id: "g20", name: "G20" }];
function averageChoices(entity: EntityDetail): { id: string; name: string }[] {
  const own = entity.groups.filter((g) => !AVERAGE_FIRST.some((f) => f.id === g.entity_id)).map((g) => ({ id: g.entity_id, name: g.short_name }));
  return [...AVERAGE_FIRST, ...own];
}
