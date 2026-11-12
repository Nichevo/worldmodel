"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { pageEntity } from "@/components/AIHost";
import Search from "@/components/Search";
import { openAsk } from "@/lib/ai";
import { api } from "@/lib/api";
import { useSettings } from "@/lib/settings";

// The menu in five groups. Each group opens a short list; the group holding the page
// you are on is marked. The Map link always opens the map (the start page setting
// only decides what the app itself opens on).
export const GROUPS: { label: string; hint: string; links: { href: string; label: string; hint?: string }[] }[] = [
  { label: "Today", hint: "What is new: the Briefing, Discover, events and CrisisWatch", links: [
    { href: "/briefing", label: "Briefing", hint: "Everything new since the last refresh, in four lanes" },
    { href: "/discover", label: "Discover", hint: "Interesting finds in the data, and the news" },
    { href: "/events", label: "Events", hint: "Elections, coups, disasters and other dated events" },
    { href: "/crisiswatch", label: "CrisisWatch", hint: "Crisis Group's monthly ratings, on a map" },
  ] },
  { label: "Explore", hint: "Maps, comparisons and topic pages", links: [
    { href: "/", label: "Map" },
    { href: "/shapes", label: "Map shapes", hint: "True size, the equal-area map, cartograms and totals told in countries" },
    { href: "/compare", label: "Compare" },
    { href: "/stories", label: "Stories", hint: "Short visual stories from your own figures: the fertility fall, electricity, exploding cities, the Arctic, NZ in numbers" },
    { href: "/topics", label: "Topics" },
    { href: "/religion", label: "Religion" },
    { href: "/languages", label: "Languages" },
    { href: "/crises", label: "Financial crises" },
    { href: "/long", label: "Long history", hint: "Empires, borders over time, people since 10,000 BC, the eight factors and the big cycle" },
    { href: "/indicators", label: "Indicators" },
    { href: "/sectors", label: "Sectors" },
    { href: "/storage", label: "Storage" },
    { href: "/climate", label: "Climate", hint: "Vital signs, climate zones now and ahead, storms, El Niño, nature lost and recovering" },
    { href: "/pollution", label: "Pollution", hint: "Air, water, the ocean, and pollution that crosses borders" },
    { href: "/transport", label: "Transport", hint: "Ports, chokepoints, airports, rivers, cables, pipelines and accidents" },
    { href: "/tourism", label: "Tourism", hint: "Visitors, what they spend, World Heritage sites" },
    { href: "/land", label: "Land", hint: "Land use since 1700, city outlines, trees, New Zealand land cover" },
    { href: "/cities", label: "Cities" },
    { href: "/laws", label: "Laws" },
    { href: "/zones", label: "Beyond borders" },
    { href: "/space", label: "Solar system", hint: "Planets on any date, asteroids by what they are made of, and where spacecraft have flown" },
    { href: "/relationships", label: "Relationships" },
  ] },
  { label: "Predict", hint: "Your predictions, crowd forecasts, forecasts and what-if", links: [
    { href: "/predictions", label: "Predictions", hint: "Your log of calls, scored when they come due; base rates; the watchlist" },
    { href: "/crowd", label: "Crowd forecasts", hint: "Polymarket, Metaculus and Manifold questions by country, and ViEWS conflict forecasts" },
    { href: "/forecasts", label: "Forecasts", hint: "Population what-if, statistical forecasts, track records and the synthetic comparison" },
    { href: "/alike", label: "Countries like this one", hint: "The nearest countries on a set of figures, decade by decade, and countries that move alike" },
    { href: "/api-access", label: "API", hint: "Use the app's data from scripts, Python, Excel or an AI assistant" },
  ] },
  { label: "Mine", hint: "What you kept, looked at and asked", links: [
    { href: "/highlights", label: "Highlights" },
    { href: "/history", label: "History" },
    { href: "/ai", label: "AI notes" },
  ] },
  { label: "Data", hint: "Sources, what is loaded, and settings", links: [
    { href: "/todo", label: "To do", hint: "Files to save, sources failing, keys and forms: what the data needs from you" },
    { href: "/sources", label: "Sources" },
    { href: "/glossary", label: "Glossary", hint: "The terms the charts use" },
    { href: "/data", label: "Data status" },
    { href: "/settings", label: "Settings" },
  ] },
];

const isOn = (path: string, href: string) => (href === "/" ? path === "/" : path === href || path.startsWith(`${href}/`));

export default function Nav() {
  const path = usePathname();
  const router = useRouter();
  const s = useSettings();
  const [q, setQ] = useState("");
  const [open, setOpen] = useState<string | null>(null);
  const bar = useRef<HTMLElement>(null);
  useEffect(() => setOpen(null), [path]);
  // How many things on the To do list need you, shown on the Data menu (asked again on each page change).
  const [todo, setTodo] = useState(0);
  useEffect(() => { api.todo().then((d) => setTodo(d.count)).catch(() => {}); }, [path]);
  useEffect(() => {
    const close = (e: MouseEvent) => { if (bar.current && !bar.current.contains(e.target as Node)) setOpen(null); };
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(null); };
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", esc);
    return () => { document.removeEventListener("mousedown", close); document.removeEventListener("keydown", esc); };
  }, []);
  // A question not about any one chart: opens the Ask AI box and asks at once. On a country
  // page, the country goes with it so the answer can use what the app knows.
  const ask = () => {
    const question = q.trim();
    if (!question) return;
    openAsk({ title: document.querySelector("h1")?.textContent?.trim() || "a general question", parts: [], entity: pageEntity(), question, send: true });
    setQ("");
  };
  return (
    <nav className="nav" ref={bar}>
      <Link href={s.start_page === "map" ? "/" : "/briefing"} className="brand">Worldmodel</Link>
      {GROUPS.map((g) => {
        const here = g.links.some((l) => isOn(path, l.href));
        return (
          <div key={g.label} className={`nav-group${open === g.label ? " open" : ""}`}>
            <button className={`nav-group-btn${here ? " active" : ""}`} aria-expanded={open === g.label} title={g.hint}
              onClick={() => setOpen(open === g.label ? null : g.label)}>
              {g.label}{g.label === "Data" && todo > 0 && <span className="badge" title={`${todo} things on the To do list`}>{todo}</span>}
              {" "}<span aria-hidden="true" className="caret">▾</span>
            </button>
            {open === g.label && (
              <div className="nav-menu" role="menu">
                {g.links.filter((l) => l.href !== "/shapes" || s.map_true_size).map((l) => (
                  <Link key={l.href} href={l.href} role="menuitem" className={isOn(path, l.href) ? "active" : ""} title={l.hint}>
                    {l.label}{l.href === "/todo" && todo > 0 && <span className="badge">{todo}</span>}
                  </Link>
                ))}
              </div>
            )}
          </div>
        );
      })}
      <Link href="/" className={`nav-quick${path === "/" ? " active" : ""}`} title="The world map">Map</Link>
      <Link href="/briefing" className={`nav-quick${path === "/briefing" ? " active" : ""}`} title="Everything new since the last refresh">Briefing</Link>
      <span className="spacer" />
      {s.ai_enabled && (
        <input className="nav-ask" type="search" value={q} placeholder="Ask AI…" aria-label="Ask the local AI"
          title="Ask the local AI anything; press Enter" onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") ask(); }} />
      )}
      <div style={{ width: 280 }}>
        <Search
          placeholder="Find a country, region or bloc"
          kinds={["entity"]}
          onPick={(hit) => router.push(`/entity/${hit.id}`)}
        />
      </div>
    </nav>
  );
}
