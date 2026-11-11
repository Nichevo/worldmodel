"use client";

import type * as echarts from "echarts";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import CardAsk from "@/components/CardAsk";
import EChart from "@/components/EChart";
import { openAsk } from "@/lib/ai";
import { dayOf, dayToDate, fmtDay, ICE_COLOR, iceImage, iceStripOption, MONTHS, seaIceApi, seaIceOption, type SeaIce } from "@/lib/climate";

// Sea ice through the year: every year since 1978 round a circle (January at the top), the chosen year
// in gold, the 1981-2010 median dashed inside its usual range, and NSIDC's map of the ice for the month
// in the middle. Under it the lowest (or highest) day of each year: click a year, drag the slider or Play.
export default function SeaIceCard() {
  const [pole, setPole] = useState<"arctic" | "ATA">("arctic");
  const [d, setD] = useState<SeaIce | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [year, setYear] = useState<number | null>(null);
  const [circle, setCircle] = useState(true);
  const [which, setWhich] = useState<"low" | "high">("low");
  const [hover, setHover] = useState<number | null>(null); // day of the year under the pointer
  const [playing, setPlaying] = useState(false);
  const [hole, setHole] = useState<{ x: number; y: number; r: number } | null>(null);
  const [imgV, setImgV] = useState<"4.0" | "3.0" | null>("4.0");
  const chart = useRef<echarts.ECharts | null>(null);
  const live = useRef({ d, year, circle });
  live.current = { d, year, circle };

  useEffect(() => {
    let on = true;
    setD(null); setErr(null);
    seaIceApi(pole).then((x) => {
      if (!on) return;
      setD(x);
      const ys = Object.keys(x.years).map(Number);
      setYear(ys.length ? Math.max(...ys) : null);
    }).catch((e) => on && setErr(String(e.message || e)));
    return () => { on = false; };
  }, [pole]);

  const years = useMemo(() => (d ? Object.keys(d.years).map(Number).sort((a, b) => a - b) : []), [d]);
  const low = d && year ? d[which].find((r) => r.year === year) : undefined;
  const day = hover ?? (low ? dayOf(low.day) : null);
  const pts = d && year ? d.years[String(year)] ?? [] : [];
  const near = (p: [number, number][], x: number) => p.reduce<[number, number] | null>((b, q) => (b === null || Math.abs(q[0] - x) < Math.abs(b[0] - x) ? q : b), null);
  const at = day !== null ? near(pts, day) : null;
  const med = d && day !== null ? d.median.find((m) => m[0] === day) ?? near(d.median.map((m) => [m[0], m[1]] as [number, number]), day) : null;
  const sameDay = d && day !== null
    ? years.map((y) => { const q = near(d.years[String(y)], day); return q && Math.abs(q[0] - day) <= 2 ? { y, v: q[1] } : null; })
      .filter((x): x is { y: number; v: number } => x !== null).sort((a, b) => a.v - b.v)
    : [];
  const rank = sameDay.findIndex((s) => s.y === year) + 1;
  const month = at ? dayToDate(year ?? 2000, at[0]).getUTCMonth() + 1 : 9;
  useEffect(() => setImgV("4.0"), [pole, year, month]);

  useEffect(() => {
    if (!playing || !years.length) return;
    const t = setInterval(() => setYear((y) => {
      const i = years.indexOf(y ?? years[0]);
      if (i >= years.length - 1) { setPlaying(false); return y; }
      return years[i + 1];
    }), 650);
    return () => clearInterval(t);
  }, [playing, years]);

  const option = useCallback(() => (d && year ? seaIceOption(d, year, circle) : {}), [d, year, circle]);
  const strip = useCallback(() => (d && year ? iceStripOption(d, year, which) : {}), [d, year, which]);

  // the marker under the pointer, moved in place (redrawing every line on each move would be slow)
  useEffect(() => {
    const c = chart.current;
    if (!c || !at) return;
    c.setOption({ series: [{ id: "hover", data: [circle ? [at[1], at[0]] : at] }] });
  }, [at?.[0], at?.[1], circle]); // eslint-disable-line react-hooks/exhaustive-deps

  const measure = () => {
    const c = chart.current;
    const { d: dd, circle: cc } = live.current;
    if (!c || !dd || !cc) { setHole(null); return; }
    try {
      const o = c.convertToPixel({ polarIndex: 0 } as never, [0, 1]) as unknown as number[];
      const top = c.convertToPixel({ polarIndex: 0 } as never, [0, 92]) as unknown as number[];
      const w = c.getWidth(), h = c.getHeight();
      const cx = w / 2, cy = h * 0.47;
      const r = Math.max(Math.hypot(o[0] - cx, o[1] - cy), Math.hypot(top[0] - cx, top[1] - cy));
      setHole({ x: cx, y: cy, r: r - 2 });
    } catch { setHole(null); }
  };
  const ready = (c: echarts.ECharts) => {
    chart.current = c;
    c.on("finished", measure);
    c.getZr().on("mousemove", (e: { offsetX: number; offsetY: number }) => {
      const { circle: cc } = live.current;
      try {
        const v = cc ? c.convertFromPixel({ polarIndex: 0 } as never, [e.offsetX, e.offsetY]) as unknown as number[]
          : c.convertFromPixel({ gridIndex: 0 } as never, [e.offsetX, e.offsetY]) as unknown as number[];
        const x = cc ? v[1] : v[0];
        if (Number.isFinite(x)) setHover(Math.min(365, Math.max(1, Math.round(x))));
      } catch { /* outside the chart */ }
    });
    c.getZr().on("globalout", () => setHover(null));
  };
  const stripReady = (c: echarts.ECharts) => {
    c.getZr().on("click", (e: { offsetX: number; offsetY: number }) => {
      const { d: dd } = live.current;
      if (!dd) return;
      try {
        const v = c.convertFromPixel({ gridIndex: 0 } as never, [e.offsetX, e.offsetY]) as unknown as number[];
        const r = dd.low[Math.round(v[0])];
        if (r) { setPlaying(false); setYear(r.year); }
      } catch { /* outside */ }
    });
  };

  const name = pole === "ATA" ? "Antarctic" : "Arctic";
  const ask = () => d && openAsk({ title: `${name} sea ice through the year`, parts: [{
    key: "ice", kind: "data" as const, label: `${name} sea ice extent, lowest and highest day of each year (million km²)`,
    text: ["Year\tLowest\tDay\tHighest\tDay", ...d.low.map((l, i) => `${l.year}${l.partial ? " (part)" : ""}\t${l.value.toFixed(2)}\t${l.day}\t${d.high[i]?.value.toFixed(2)}\t${d.high[i]?.day}`),
      d.latest ? `Newest: ${d.latest.day} ${d.latest.value.toFixed(2)} (median that day ${d.latest.median?.toFixed(2) ?? "?"})` : ""].join("\n"),
  }] });

  const head = (
    <div className="card-head">
      <h3>{name} sea ice through the year</h3>
      <span className="card-actions">
        <span className="seg small" role="group" aria-label="Pole">
          {(["arctic", "ATA"] as const).map((p) => <button key={p} className={pole === p ? "on" : ""} aria-pressed={pole === p} onClick={() => { setPlaying(false); setPole(p); }}>{p === "ATA" ? "Antarctic" : "Arctic"}</button>)}
        </span>
        <span className="seg small" role="group" aria-label="Chart">
          <button className={circle ? "on" : ""} aria-pressed={circle} onClick={() => setCircle(true)}>Circle</button>
          <button className={!circle ? "on" : ""} aria-pressed={!circle} onClick={() => { setCircle(false); setHole(null); }}>Lines</button>
        </span>
        <CardAsk onAsk={ask} />
      </span>
    </div>
  );
  if (err) return <div className="card">{head}<p className="error">{err}</p></div>;
  if (!d) return <div className="card">{head}<p className="muted small">Loading…</p></div>;
  if (!d.kind || !year) return (
    <div className="card" id="sea-ice">{head}
      <p className="muted small">No sea ice figures yet: <code>.\refresh.bat</code> loads them from NSIDC (two daily files of about 1.5 MB, and 24 small monthly ones).</p></div>
  );
  const diff = at && med ? at[1] - med[1] : null;
  const ord = (n: number) => `${n}${n % 10 === 1 && n % 100 !== 11 ? "st" : n % 10 === 2 && n % 100 !== 12 ? "nd" : n % 10 === 3 && n % 100 !== 13 ? "rd" : "th"}`;
  return (
    <div className="card" id="sea-ice">
      {head}
      <div className="ice-wrap" style={{ position: "relative", display: "flex", flexDirection: circle ? "column" : "column-reverse" }}>
        <EChart option={option} height={circle ? 600 : 420} label={`${name} sea ice extent through each year since 1978`} onReady={ready} />
        {circle && hole && imgV && (
          <a href={iceImage(pole, year, month, imgV)} target="_blank" rel="noreferrer" title={`NSIDC's map of the ice, ${MONTHS[month - 1]} ${year} (opens the full picture)`}
            className="ice-map" style={{ left: hole.x - hole.r, top: hole.y - hole.r, width: hole.r * 2, height: hole.r * 2 }}>
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={iceImage(pole, year, month, imgV)} alt={`${name} sea ice, ${MONTHS[month - 1]} ${year}`}
              onError={() => setImgV(imgV === "4.0" ? "3.0" : null)} />
            <span className="ice-map-cap">sea ice, {MONTHS[month - 1]} {year} (month)</span>
          </a>
        )}
        {at && (
          <div className={circle ? "ice-readout" : "ice-readout flat"}>
            <div className="ice-date">{fmtDay(dayToDate(year, at[0]))}</div>
            <div className="ice-value">{at[1].toFixed(2)} million km²</div>
            {med && <div className="small muted">{d.base} median: {med[1].toFixed(2)}{diff !== null ? ` (${diff >= 0 ? "+" : ""}${diff.toFixed(2)})` : ""}</div>}
            {rank > 0 && <div className="small muted">{rank === 1 ? "The lowest" : `${ord(rank)} lowest`} of {sameDay.length} years for the day</div>}
          </div>
        )}
      </div>
      <div className="chips-row small ice-years">
        <button className="link" onClick={() => { if (!playing && year === years[years.length - 1]) setYear(years[0]); setPlaying(!playing); }}>{playing ? "Pause" : "Play"}</button>
        <input type="range" min={years[0]} max={years[years.length - 1]} step={1} value={year} aria-label="Year"
          onChange={(e) => { setPlaying(false); const v = Number(e.target.value); setYear(years.reduce((b, y) => (Math.abs(y - v) < Math.abs(b - v) ? y : b), years[0])); }} />
        <b style={{ color: ICE_COLOR }}>{year}</b>
        <span className="seg small" role="group" aria-label="Strip shows">
          {(["low", "high"] as const).map((k) => <button key={k} className={which === k ? "on" : ""} aria-pressed={which === k} onClick={() => setWhich(k)}>{k === "low" ? "Lowest day per year" : "Highest day per year"}</button>)}
        </span>
      </div>
      <EChart option={strip} height={140} label={`${which === "low" ? "Lowest" : "Highest"} ${name} sea ice extent each year: click a year`} onReady={stripReady} />
      <p className="caption">
        Extent is the ocean area with at least 15% ice cover. {d.kind === "monthly" ? "Monthly averages (the daily file is not loaded yet). " : "Daily (five-day averages), every other day before July 1987. "}
        {d.latest ? <>Newest day {d.latest.day}: {d.latest.value.toFixed(2)} million km²{d.latest.median !== null ? `, ${d.latest.median.toFixed(2)} is the ${d.base} median for the day` : ""}{d.latest.rank ? `, ${d.latest.rank === 1 ? "the lowest" : `${ord(d.latest.rank)} lowest`} of ${d.latest.of} years for the day` : ""}. </> : null}
        The map in the middle is NSIDC&apos;s picture for the month (median edge marked), loaded from their site. Data: {d.source}.
      </p>
    </div>
  );
}
