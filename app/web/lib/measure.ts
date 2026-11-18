// Measure distance on any map: click places (or city dots) to lay out a route; each leg is
// drawn along the great circle (the shortest path over the globe), with a label along it
// giving the distance and the bearing each way, like a flight plan. Points can be dragged.
import * as maplibregl from "maplibre-gl";
import type { GeoJSONSource } from "maplibre-gl";
import { cssVar } from "@/lib/colors";

const R_KM = 6371.0088;
const rad = (d: number) => (d * Math.PI) / 180;
const deg = (r: number) => (r * 180) / Math.PI;

export type Units = "km" | "nm" | "mi";
export const UNIT_LABEL: Record<Units, string> = { km: "km", nm: "NM", mi: "mi" };
const PER_KM: Record<Units, number> = { km: 1, nm: 1 / 1.852, mi: 1 / 1.609344 };
export const CRUISE_KMH = 850; // a jet airliner's usual cruising speed, for a rough flight time

// Great-circle distance in km between two [lng, lat] points (haversine).
export function distanceKm(a: [number, number], b: [number, number]): number {
  const [lo1, la1] = a.map(rad);
  const [lo2, la2] = b.map(rad);
  const h = Math.sin((la2 - la1) / 2) ** 2 + Math.cos(la1) * Math.cos(la2) * Math.sin((lo2 - lo1) / 2) ** 2;
  return 2 * R_KM * Math.asin(Math.min(1, Math.sqrt(h)));
}

// The initial bearing from a to b, degrees clockwise from true north (0-359).
export function bearing(a: [number, number], b: [number, number]): number {
  const [lo1, la1] = a.map(rad);
  const [lo2, la2] = b.map(rad);
  const y = Math.sin(lo2 - lo1) * Math.cos(la2);
  const x = Math.cos(la1) * Math.sin(la2) - Math.sin(la1) * Math.cos(la2) * Math.cos(lo2 - lo1);
  return (deg(Math.atan2(y, x)) + 360) % 360;
}

// Points along the great circle from a to b, with longitudes kept continuous (no jump at
// the date line) so the line draws as one smooth curve on the Pacific-centred map.
export function greatCircle(a: [number, number], b: [number, number], steps = 64): [number, number][] {
  const [lo1, la1] = a.map(rad);
  const [lo2, la2] = b.map(rad);
  const d = distanceKm(a, b) / R_KM;
  if (d < 1e-9) return [a, b];
  const out: [number, number][] = [];
  let prev = a[0];
  for (let i = 0; i <= steps; i++) {
    const f = i / steps;
    const A = Math.sin((1 - f) * d) / Math.sin(d), B = Math.sin(f * d) / Math.sin(d);
    const x = A * Math.cos(la1) * Math.cos(lo1) + B * Math.cos(la2) * Math.cos(lo2);
    const y = A * Math.cos(la1) * Math.sin(lo1) + B * Math.cos(la2) * Math.sin(lo2);
    const z = A * Math.sin(la1) + B * Math.sin(la2);
    let lng = deg(Math.atan2(y, x));
    while (lng - prev > 180) lng -= 360;
    while (lng - prev < -180) lng += 360;
    prev = lng;
    out.push([lng, deg(Math.atan2(z, Math.sqrt(x * x + y * y)))]);
  }
  return out;
}

export function fmtDistance(km: number, units: Units): string {
  const v = km * PER_KM[units];
  return `${v >= 100 ? Math.round(v).toLocaleString() : v.toFixed(1)} ${UNIT_LABEL[units]}`;
}

export function flightTime(km: number): string {
  const h = km / CRUISE_KMH + 0.5; // half an hour for take-off, climb and landing
  return `${Math.floor(h)} h ${String(Math.round((h % 1) * 60)).padStart(2, "0")} min`;
}

// A leg's label text, arrows pointing along the line as it sits on screen: the bearing
// to travel left, then the distance, then the bearing to travel right.
export function legText(a: [number, number], b: [number, number], units: Units, aOnLeft: boolean): string {
  const fwd = Math.round(bearing(a, b)) % 360, back = Math.round(bearing(b, a)) % 360;
  const d = fmtDistance(distanceKm(a, b), units);
  const [left, right] = aOnLeft ? [back, fwd] : [fwd, back];
  return `← ${String(left).padStart(3, "0")}° · ${d} · ${String(right).padStart(3, "0")}° →`;
}

type Point = { lng: number; lat: number; name?: string };

// The tool on one map. `cityAt` finds a city dot under the pointer, so a click on one snaps to it.
export class MeasureTool {
  on = false;
  private points: Point[] = [];
  private units: Units = "km";
  private markers: maplibregl.Marker[] = [];
  private labels: maplibregl.Marker[] = [];
  private panel: HTMLDivElement;
  private button: HTMLButtonElement;

  constructor(private m: maplibregl.Map, private cityAt: (p: maplibregl.Point) => { lng: number; lat: number; name: string } | null) {
    const box = document.createElement("div");
    box.className = "maplibregl-ctrl maplibregl-ctrl-group";
    this.button = document.createElement("button");
    this.button.type = "button";
    this.button.className = "measure-btn";
    this.button.title = "Measure distance: click places on the map (Esc to stop)";
    this.button.setAttribute("aria-label", "Measure distance");
    this.button.setAttribute("aria-pressed", "false");
    this.button.innerHTML = '<svg viewBox="0 0 20 20" width="18" height="18" aria-hidden="true"><path d="M3 14 L14 3 L17 6 L6 17 Z" fill="none" stroke="currentColor" stroke-width="1.6"/><path d="M6 11 l1.5 1.5 M8.5 8.5 l1.5 1.5 M11 6 l1.5 1.5" stroke="currentColor" stroke-width="1.4"/></svg>';
    this.button.onclick = () => this.toggle();
    box.appendChild(this.button);
    m.addControl({ onAdd: () => box, onRemove: () => box.remove() }, "top-right");
    this.panel = document.createElement("div");
    this.panel.className = "measure-panel";
    this.panel.hidden = true;
    m.getContainer().appendChild(this.panel);
    m.on("click", (e) => {
      if (!this.on) return;
      const city = this.cityAt(e.point);
      this.points.push(city ?? { lng: e.lngLat.lng, lat: e.lngLat.lat });
      this.draw();
    });
    m.getContainer().addEventListener("keydown", (e) => {
      if (!this.on) return;
      if (e.key === "Escape") this.toggle(false);
      if (e.key === "Backspace") { this.points.pop(); this.draw(); }
    });
  }

  toggle(on = !this.on) {
    this.on = on;
    this.button.classList.toggle("on", on);
    this.button.setAttribute("aria-pressed", String(on));
    this.m.getCanvas().style.cursor = on ? "crosshair" : "";
    if (on) this.m.getContainer().focus();
    if (!on) { this.points = []; }
    this.draw();
  }

  private ensureLayers() {
    if (this.m.getSource("measure")) return;
    this.m.addSource("measure", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
    this.m.addLayer({ id: "measure-casing", type: "line", source: "measure", layout: { "line-cap": "round" },
      paint: { "line-color": cssVar("--surface"), "line-width": 6, "line-opacity": 0.9 } });
    this.m.addLayer({ id: "measure-line", type: "line", source: "measure", layout: { "line-cap": "round" },
      paint: { "line-color": cssVar("--ink"), "line-width": 2.8 } });
  }

  private draw() {
    if (!this.m.isStyleLoaded() && !this.m.getSource("measure")) { this.m.once("idle", () => this.draw()); return; }
    this.ensureLayers();
    const pts = this.points;
    const legs: [number, number][][] = [];
    for (let i = 1; i < pts.length; i++) {
      // Each leg starts where the last ended, longitude kept continuous across the date line.
      const prevEnd = legs.length ? legs[legs.length - 1][legs[legs.length - 1].length - 1] : [pts[0].lng, pts[0].lat] as [number, number];
      const a: [number, number] = [pts[i - 1].lng, pts[i - 1].lat], b: [number, number] = [pts[i].lng, pts[i].lat];
      const line = greatCircle(a, b);
      const shift = Math.round((prevEnd[0] - line[0][0]) / 360) * 360;
      legs.push(line.map(([x, y]) => [x + shift, y]));
    }
    (this.m.getSource("measure") as GeoJSONSource).setData({ type: "FeatureCollection",
      features: legs.map((c) => ({ type: "Feature", geometry: { type: "LineString", coordinates: c }, properties: {} })) });
    this.markers.forEach((mk) => mk.remove());
    this.labels.forEach((mk) => mk.remove());
    this.markers = pts.map((p, i) => {
      const el = document.createElement("div");
      el.className = "measure-pt";
      el.title = p.name ?? "Drag to move";
      const mk = new maplibregl.Marker({ element: el, draggable: true }).setLngLat([p.lng, p.lat]).addTo(this.m);
      mk.on("dragend", () => { const ll = mk.getLngLat(); this.points[i] = { lng: ll.lng, lat: ll.lat }; this.draw(); });
      return mk;
    });
    this.labels = legs.map((line, i) => this.label(line, [pts[i].lng, pts[i].lat], [pts[i + 1].lng, pts[i + 1].lat]));
    this.panelHtml();
  }

  // The label along a leg, at its middle, turned to follow the line and kept upright.
  private label(line: [number, number][], a: [number, number], b: [number, number]) {
    const mid = Math.floor(line.length / 2);
    const p1 = this.m.project(line[Math.max(0, mid - 2)] as [number, number]);
    const p2 = this.m.project(line[Math.min(line.length - 1, mid + 2)] as [number, number]);
    let angle = deg(Math.atan2(p2.y - p1.y, p2.x - p1.x));
    const aOnLeft = angle > -90 && angle < 90;
    if (!aOnLeft) angle += 180;
    const el = document.createElement("div");
    el.className = "measure-label";
    el.textContent = legText(a, b, this.units, aOnLeft);
    return new maplibregl.Marker({ element: el, rotation: angle, rotationAlignment: "map", offset: [0, -16] })
      .setLngLat(line[mid] as [number, number]).addTo(this.m);
  }

  private panelHtml() {
    const pts = this.points;
    this.panel.hidden = !this.on;
    if (!this.on) return;
    let total = 0;
    const rows: string[] = [];
    for (let i = 1; i < pts.length; i++) {
      const km = distanceKm([pts[i - 1].lng, pts[i - 1].lat], [pts[i].lng, pts[i].lat]);
      total += km;
      const name = (p: Point, n: number) => p.name ?? `Point ${n + 1}`;
      rows.push(`<li>${esc(name(pts[i - 1], i - 1))} to ${esc(name(pts[i], i))}: <b>${fmtDistance(km, this.units)}</b></li>`);
    }
    const unitBtns = (["km", "nm", "mi"] as Units[]).map((u) =>
      `<button type="button" data-u="${u}" class="${u === this.units ? "on" : ""}">${UNIT_LABEL[u]}</button>`).join("");
    this.panel.innerHTML = `<div class="measure-head"><b>Measure distance</b><span class="measure-units">${unitBtns}</span></div>`
      + (pts.length < 2 ? `<p>Click two or more places, or city dots. Drag a point to move it; Backspace removes the last one.</p>`
        : `<ol>${rows.join("")}</ol>${pts.length > 2 ? `<p>Total <b>${fmtDistance(total, this.units)}</b></p>` : ""}`
          + `<p class="muted">By air about ${flightTime(total)} at ${CRUISE_KMH} km/h. Bearings are from true north.</p>`)
      + `<div class="measure-actions"><button type="button" data-a="undo">Undo</button><button type="button" data-a="clear">Clear</button><button type="button" data-a="done">Done</button></div>`;
    this.panel.querySelectorAll<HTMLButtonElement>("button[data-u]").forEach((b) => {
      b.onclick = () => { this.units = b.dataset.u as Units; this.draw(); };
    });
    this.panel.querySelectorAll<HTMLButtonElement>("button[data-a]").forEach((b) => {
      b.onclick = () => {
        if (b.dataset.a === "undo") this.points.pop();
        if (b.dataset.a === "clear") this.points = [];
        if (b.dataset.a === "done") { this.toggle(false); return; }
        this.draw();
      };
    });
  }
}

function esc(s: string): string {
  return s.replace(/[&<>"]/g, (c) => `&#${c.charCodeAt(0)};`);
}
