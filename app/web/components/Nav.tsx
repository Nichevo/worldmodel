"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useState } from "react";
import { pageEntity } from "@/components/AIHost";
import Search from "@/components/Search";
import { openAsk } from "@/lib/ai";
import { useSettings } from "@/lib/settings";

const LINKS = [
  { href: "/", label: "Map" },
  { href: "/compare", label: "Compare" },
  { href: "/forecasts", label: "Forecasts" },
  { href: "/relationships", label: "Relationships" },
  { href: "/sectors", label: "Sectors" },
  { href: "/storage", label: "Storage" },
  { href: "/climate", label: "Climate" },
  { href: "/cities", label: "Cities" },
  { href: "/topics", label: "Topics" },
  { href: "/events", label: "Events" },
  { href: "/zones", label: "Beyond borders" },
  { href: "/laws", label: "Laws" },
  { href: "/indicators", label: "Indicators" },
  { href: "/sources", label: "Sources" },
  { href: "/data", label: "Data status" },
  { href: "/ai", label: "AI notes" },
  { href: "/highlights", label: "Highlights" },
  { href: "/history", label: "History" },
  { href: "/settings", label: "Settings" },
];

export default function Nav() {
  const path = usePathname();
  const router = useRouter();
  const s = useSettings();
  const [q, setQ] = useState("");
  // A question not about any one chart: opens the Ask AI box and asks at once. On a country
  // page, the country goes with it so the answer can use what the app knows.
  const ask = () => {
    const question = q.trim();
    if (!question) return;
    openAsk({ title: document.querySelector("h1")?.textContent?.trim() || "a general question", parts: [], entity: pageEntity(), question, send: true });
    setQ("");
  };
  return (
    <nav className="nav">
      <Link href="/" className="brand">Worldmodel</Link>
      {LINKS.map((l) => (
        <Link key={l.href} href={l.href} className={path === l.href ? "active" : ""}>{l.label}</Link>
      ))}
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
