"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api, type Indicator, type Topic } from "@/lib/api";

// Every topic page, with its introduction and the indicators it covers.
export default function TopicsPage() {
  const [topics, setTopics] = useState<Topic[] | null>(null);
  const [inds, setInds] = useState<Map<string, Indicator>>(new Map());
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    api.topics().then(setTopics).catch((e) => setError(String(e.message || e)));
    api.indicators().then((l) => setInds(new Map(l.map((i) => [i.indicator_id, i])))).catch(() => {});
  }, []);
  return (
    <div className="grid">
      <div>
        <h1>Topics</h1>
        <p className="ink-2" style={{ marginTop: 0 }}>
          A page for each subject: a short introduction, a map, the key countries against the world, and every indicator
          linked to its own page. For a single indicator, open it from the Indicators page.
        </p>
      </div>
      {error && <p className="error">{error}</p>}
      <div className="topic-grid">
        {(topics ?? []).map((t) => (
          <Link key={t.id} href={`/topic/${t.id}`} className="card topic-card">
            <h3>{t.name}</h3>
            <p className="small ink-2">{t.intro}</p>
            <p className="small muted" style={{ marginBottom: 0 }}>
              {t.indicators.map((i) => inds.get(i)?.name ?? i).join(" · ") || "Nothing loaded yet"}
              {t.missing.length ? ` (${t.missing.length} more once loaded)` : ""}
            </p>
          </Link>
        ))}
      </div>
    </div>
  );
}
