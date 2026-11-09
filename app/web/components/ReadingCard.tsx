"use client";

import type { EntityDetail } from "@/lib/api";
import { openAsk } from "@/lib/ai";
import { useSettings } from "@/lib/settings";

// A country's reading list: the reports economists read first, linked at their sources
// (the IMF's yearly Article IV review, the OECD's Economic Survey for its members, the
// World Bank's country page), each with an Ask AI button that asks the local AI to find
// and summarise the latest one (it needs web search on in Settings > AI to read it).
const slug = (name: string) => name.toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "").replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");

export default function ReadingCard({ entity }: { entity: EntityDetail }) {
  const s = useSettings();
  const iso3 = entity.iso3 ?? entity.entity_id;
  const name = entity.short_name;
  const oecd = entity.groups.some((g) => g.entity_id === "oecd" && !g.valid_to);
  const q = encodeURIComponent(name);
  const items: { title: string; who: string; href: string; what: string; ask?: string }[] = [
    { title: `${name}: Article IV consultation`, who: "IMF", href: `https://www.imf.org/en/Countries/${iso3}`,
      what: "The IMF's yearly health check of the economy: growth, inflation, public debt, banks and the risks ahead, with the government's answer.",
      ask: `Find the latest IMF Article IV staff report for ${name} and summarise its main points: the outlook, the risks, and what the IMF advises.` },
    ...(oecd ? [{ title: `${name}: OECD Economic Survey`, who: "OECD", href: `https://www.oecd.org/en/countries/${slug(name)}.html`,
      what: "Every two years or so: a deeper look at the economy with one or two special chapters (housing, productivity, climate).",
      ask: `Find the latest OECD Economic Survey of ${name} and summarise its key recommendations and its special chapters.` }] : []),
    { title: `${name} at the World Bank`, who: "World Bank", href: `https://data.worldbank.org/country/${(entity.iso2 ?? iso3).toLowerCase()}`,
      what: "The country's figures at a glance and the Bank's reports and projects there." },
    { title: "Country reports search", who: "IMF", href: `https://www.imf.org/en/Publications/Search?series=IMF%20Staff%20Country%20Reports&title=${q}`,
      what: "Every IMF staff report on the country, newest first: Article IVs, programme reviews and selected issues papers." },
  ];
  return (
    <div className="card" id="reading">
      <div className="card-head"><h3>Reading list</h3></div>
      <ul className="reading">
        {items.map((it) => (
          <li key={it.href}>
            <a href={it.href} target="_blank" rel="noreferrer">{it.title}</a> <span className="muted small">{it.who}</span>
            {it.ask && s.ai_enabled && (
              <button className="link small" style={{ marginLeft: 8 }} title="Ask your local AI to find the latest report and summarise it"
                onClick={() => openAsk({ title: it.title, parts: [], entity: entity.entity_id, question: it.ask, send: true })}>Summarise with AI</button>
            )}
            <div className="small ink-2">{it.what}</div>
          </li>
        ))}
      </ul>
      <p className="caption">Links open the publisher&apos;s own pages. The AI summary reads the report only with web search on
        (Settings: AI); without it, the answer says what it cannot see.</p>
    </div>
  );
}
