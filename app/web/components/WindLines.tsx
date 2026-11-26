"use client";

import type * as maplibregl from "maplibre-gl";
import { useEffect, useRef, useState } from "react";
import { windGrid, type WindGrid } from "@/lib/weather";

// Moving wind lines over a map: thousands of short-lived specks carried by the forecast wind for the
// hour on the weather bar, each leaving a fading trail (drawn in the browser on a canvas over the map).
// Speed on screen is the same at every zoom, so the pattern of the flow stays readable.
export default function WindLines({ map, run, step, light }: {
  map: maplibregl.Map; run: string; step: number; light: boolean; // light: white lines (over the wind shading)
}) {
  const canvas = useRef<HTMLCanvasElement | null>(null);
  const [grid, setGrid] = useState<WindGrid | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let live = true;
    windGrid(run, step).then((g) => { if (live) { setGrid(g); setError(null); } })
      .catch((e) => live && setError(String(e.message || e)));
    return () => { live = false; };
  }, [run, step]);

  useEffect(() => {
    const c = canvas.current;
    if (!c || !grid) return;
    const ctx = c.getContext("2d");
    if (!ctx) return;
    const still = typeof matchMedia !== "undefined" && matchMedia("(prefers-reduced-motion: reduce)").matches;
    const box = map.getContainer();
    let w = 0, h = 0, ratio = 1;
    type Speck = { x: number; y: number; age: number; life: number };
    let specks: Speck[] = [];
    const seed = (p: Speck) => { p.x = Math.random() * w; p.y = Math.random() * h; p.age = 0; p.life = 40 + Math.random() * 70; };
    const size = () => {
      ratio = window.devicePixelRatio || 1;
      w = box.clientWidth; h = box.clientHeight;
      c.width = Math.round(w * ratio); c.height = Math.round(h * ratio);
      c.style.width = `${w}px`; c.style.height = `${h}px`;
      ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
      const n = Math.max(600, Math.min(4500, Math.round((w * h) / 380)));
      specks = Array.from({ length: n }, () => { const p = { x: 0, y: 0, age: 0, life: 0 }; seed(p); p.age = Math.random() * p.life; return p; });
      ctx.clearRect(0, 0, w, h);
    };
    // Bilinear wind (m/s) at a place; rows from 90°N down, columns from 0°E.
    const wind = (lng: number, lat: number): [number, number] | null => {
      if (lat > 90 || lat < -90) return null;
      const fi = (grid.lat0 - lat) / grid.d;
      const fj = ((((lng - grid.lon0) % 360) + 360) % 360) / grid.d;
      const i0 = Math.min(grid.nj - 1, Math.floor(fi)), i1 = Math.min(grid.nj - 1, i0 + 1);
      const j0 = Math.floor(fj) % grid.ni, j1 = (j0 + 1) % grid.ni;
      const ti = fi - Math.floor(fi), tj = fj - Math.floor(fj);
      const at = (a: Float32Array) => a[i0 * grid.ni + j0] * (1 - ti) * (1 - tj) + a[i0 * grid.ni + j1] * (1 - ti) * tj
        + a[i1 * grid.ni + j0] * ti * (1 - tj) + a[i1 * grid.ni + j1] * ti * tj;
      return [at(grid.u), at(grid.v)];
    };
    const ink = light ? "255,255,255" : "28,38,58";
    let frame = 0;
    let moving = false;
    const segs: number[][] = [[], [], []]; // per strength band: x0, y0, x1, y1, ...
    const draw = () => {
      if (moving || !w) return;
      // Fade what is there, then move each speck one step and draw that step.
      ctx.globalCompositeOperation = "destination-in";
      ctx.fillStyle = "rgba(0,0,0,0.92)";
      ctx.fillRect(0, 0, w, h);
      ctx.globalCompositeOperation = "source-over";
      segs.forEach((b) => { b.length = 0; });
      for (const p of specks) {
        if (p.age++ > p.life) { seed(p); continue; }
        const ll = map.unproject([p.x, p.y]);
        const uv = wind(ll.lng, ll.lat);
        const ms = uv ? Math.hypot(uv[0], uv[1]) : 0;
        if (!uv || ms <= 0.3) { seed(p); continue; }
        const k = 0.11; // pixels a frame per m/s
        const nx = p.x + uv[0] * k, ny = p.y - uv[1] * k;
        segs[ms < 6 ? 0 : ms < 14 ? 1 : 2].push(p.x, p.y, nx, ny);
        p.x = nx; p.y = ny;
        if (nx < 0 || ny < 0 || nx > w || ny > h) seed(p);
      }
      ctx.lineWidth = 1.1;
      segs.forEach((b, i) => {
        if (!b.length) return;
        ctx.beginPath();
        ctx.strokeStyle = `rgba(${ink},${[0.45, 0.7, 0.95][i]})`;
        for (let j = 0; j < b.length; j += 4) { ctx.moveTo(b[j], b[j + 1]); ctx.lineTo(b[j + 2], b[j + 3]); }
        ctx.stroke();
      });
    };
    const tick = () => { draw(); frame = requestAnimationFrame(tick); };
    const still_ = () => { for (let n = 0; n < 25; n++) draw(); }; // reduced motion: one still picture of short trails
    const start = () => { moving = false; ctx.clearRect(0, 0, w, h); if (still) still_(); };
    const stop = () => { moving = true; ctx.clearRect(0, 0, w, h); };
    size();
    if (still) still_();
    else frame = requestAnimationFrame(tick);
    const ro = new ResizeObserver(() => { size(); if (still) still_(); });
    ro.observe(box);
    map.on("movestart", stop);
    map.on("moveend", start);
    return () => {
      cancelAnimationFrame(frame);
      ro.disconnect();
      map.off("movestart", stop);
      map.off("moveend", start);
    };
  }, [grid, map, light]);

  return (
    <>
      <canvas ref={canvas} className="wx-windlines" aria-hidden="true" />
      {error && <span className="wx-windlines-error small error">Wind lines did not load: {error}</span>}
    </>
  );
}
