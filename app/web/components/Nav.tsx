"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import Search from "@/components/Search";

const LINKS = [
  { href: "/", label: "Map" },
  { href: "/compare", label: "Compare" },
  { href: "/forecasts", label: "Forecasts" },
  { href: "/topics", label: "Topics" },
  { href: "/events", label: "Events" },
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
  return (
    <nav className="nav">
      <Link href="/" className="brand">Worldmodel</Link>
      {LINKS.map((l) => (
        <Link key={l.href} href={l.href} className={path === l.href ? "active" : ""}>{l.label}</Link>
      ))}
      <span className="spacer" />
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
