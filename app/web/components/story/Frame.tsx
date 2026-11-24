"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import CardAsk from "@/components/CardAsk";
import { openAsk } from "@/lib/ai";
import { api, type Indicator } from "@/lib/api";
import { cssVar } from "@/lib/colors";
import type { Band, Step } from "@/lib/story";

export type Props = { step: Step & { kicker?: string }; i: number; total: number; inds: Map<string, Indicator>; colour: string; title: string };

// The frame round every story step: its number, kicker and sentence, Ask AI, then the chart.
export function Frame({ i, total, colour, title, step, sentence, data, missing, children }: Props & { sentence: string | null; data: string; missing?: string | null;
  children?: React.ReactNode }) {
  const box = useRef<HTMLElement>(null);
  const [seen, setSeen] = useState(false);
  useEffect(() => { // fade in as it scrolls into view
    const el = box.current;
    if (!el || typeof IntersectionObserver === "undefined") { setSeen(true); return; }
    const io = new IntersectionObserver((es) => { if (es.some((e) => e.isIntersecting)) { setSeen(true); io.disconnect(); } }, { threshold: 0.15 });
    io.observe(el);
    return () => io.disconnect();
  }, []);
  const ask = () => openAsk({ title: `${title}, step ${i + 1}`, parts: [
    { key: "say", kind: "highlight", label: "What this step says", text: sentence ?? "" },
    ...(data ? [{ key: "data", kind: "data" as const, label: "The figures behind it", text: data }] : []),
  ] });
  return (
    <section ref={box} className={`story-step${seen ? " seen" : ""}`} style={{ ["--story" as string]: colour }}>
      <div className="story-say">
        <span className="story-num">{i + 1}<span>/{total}</span></span>
        <div>
          {step.kicker && <div className="story-kicker">{step.kicker}</div>}
          <p className="story-sentence">{missing ? <span className="muted">{missing}</span> : sentence ?? <span className="muted">Working it out…</span>}</p>
        </div>
        <span className="story-ask"><CardAsk onAsk={ask} /></span>
      </div>
      {!missing && <div className="story-visual">{children}</div>}
    </section>
  );
}

export const notLoaded = (ids: string[]) => `Not loaded yet: ${ids.join(", ")}. A refresh fetches it, and this step fills in by itself.`;

// Shaded periods for a line chart: the story's own (wars) and, when asked, the app's Big episodes
// for the places on the chart. Years as numbers; a band covers its first year to the end of its last.
// The story's own bands are always named; episodes only when there are ten or fewer.
export function useStoryBands(own: Band[] | undefined, episodesFor: string[]): (Band & { url?: string | null })[] {
  const [eps, setEps] = useState<(Band & { url?: string | null })[]>([]);
  const key = episodesFor.join(",");
  useEffect(() => {
    if (!key) { setEps([]); return; }
    let live = true;
    api.events({ entities: [...key.split(","), "world"], kinds: ["episode"] }).then((rows) => {
      if (!live) return;
      const seen = new Set<string>();
      setEps(rows.filter((e) => !seen.has(e.title) && seen.add(e.title)).map((e) => ({ from: +e.start_date.slice(0, 4),
        to: +(e.end_date ?? e.start_date).slice(0, 4), label: e.title, url: e.url })));
    }).catch(() => live && setEps([]));
    return () => { live = false; };
  }, [key]);
  return useMemo(() => [...(own ?? []), ...eps], [own, eps]);
}

export function bandMarks(bands: (Band & { url?: string | null })[]) {
  const col = cssVar("--div-neg-2");
  const many = bands.length > 10;
  return {
    type: "line" as const, id: "bands", data: [] as number[], silent: false, tooltip: { show: false },
    markArea: { silent: false, data: bands.map((b) => [
      { xAxis: b.from - 0.5, name: b.label, url: b.url ?? null, itemStyle: { color: col, opacity: 0.1 },
        label: { show: !many || !b.url, position: "insideTopLeft", rotate: 90, align: "right", verticalAlign: "top", offset: [2, 4], fontSize: 10, color: cssVar("--muted"),
          formatter: () => (b.label.length > 24 ? `${b.label.slice(0, 23)}…` : b.label) } },
      { xAxis: b.to + 0.5 }]),
      emphasis: { label: { show: true, color: cssVar("--ink"), backgroundColor: cssVar("--surface"), padding: [2, 4], position: "insideTop" } } },
  };
}
