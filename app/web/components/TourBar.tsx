"use client";

import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { onTour, readTour, setTour, type TourState } from "@/lib/tour";

// The guided tour's bar along the bottom of the window: what this stop shows, and Back / Next.
// Each stop opens its page, scrolls to its card or section (waiting a few seconds for cards that
// load late) and outlines it. Leaving the tour's page by the menu keeps the tour; End closes it.
export default function TourBar() {
  const [t, setT] = useState<TourState | null>(null);
  const [missing, setMissing] = useState(false);
  const path = usePathname();
  const router = useRouter();
  useEffect(() => { setT(readTour()); return onTour(() => setT(readTour())); }, []);

  const stop = t ? t.tour.stops[t.step] : null;
  const here = !!stop && decodeURIComponent(path) === stop.path.split("?")[0];
  useEffect(() => {
    setMissing(false);
    if (!stop?.target || !here) {
      if (here && !stop?.target) window.scrollTo({ top: 0, behavior: "smooth" });
      return;
    }
    // Cards above it often load after it, pushing it down: follow it for a few seconds, until you scroll yourself.
    let tries = 0, el: Element | null = null, follow = 0, yours = false;
    const mine = () => { yours = true; };
    window.addEventListener("wheel", mine, { passive: true });
    window.addEventListener("touchmove", mine, { passive: true });
    window.addEventListener("keydown", mine);
    const timer = setInterval(() => {
      if (!el) {
        const found = document.querySelector(stop.target!);
        if (found && found.getBoundingClientRect().height > 0) el = found; // an empty wrapper (card with nothing to show) does not count
        if (el) { el.classList.add("tour-target"); el.scrollIntoView({ behavior: "smooth", block: "start" }); }
        else if (++tries > 40) { clearInterval(timer); setMissing(true); }
        return;
      }
      if (yours || ++follow > 25) { clearInterval(timer); return; }
      const top = el.getBoundingClientRect().top;
      if (Math.abs(top - 80) > 120) el.scrollIntoView({ behavior: "auto", block: "start" });
    }, 200);
    return () => {
      clearInterval(timer); (el as Element | null)?.classList.remove("tour-target");
      window.removeEventListener("wheel", mine); window.removeEventListener("touchmove", mine); window.removeEventListener("keydown", mine);
    };
  }, [stop?.target, stop?.path, here, t?.step]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!t || !stop) return null;
  const go = (step: number) => {
    const next = t.tour.stops[step];
    setTour({ ...t, step });
    if (next.path !== decodeURIComponent(path)) router.push(next.path);
  };
  const n = t.tour.stops.length;
  return (
    <div className="tour-bar" role="dialog" aria-label={`Tour: ${t.tour.name}`}>
      <div className="tour-head small muted">{t.tour.name}, stop {t.step + 1} of {n}</div>
      <p>{stop.text}</p>
      {!here && <p className="small"><button className="link small" onClick={() => router.push(stop.path)}>Back to this stop&apos;s page</button></p>}
      {here && missing && <p className="small muted">This card is not showing here (switched off, or no figures yet), so there is nothing to point at.</p>}
      <div className="chips-row small" style={{ margin: 0 }}>
        <button disabled={t.step === 0} onClick={() => go(t.step - 1)}>Back</button>
        {t.step < n - 1 ? <button className="primary" onClick={() => go(t.step + 1)}>Next</button>
          : <button className="primary" onClick={() => setTour(null)}>Finish</button>}
        <span className="spacer" />
        <button className="link small" onClick={() => setTour(null)}>End tour</button>
      </div>
    </div>
  );
}
