// Helpers for the hand-drawn SVG pictures (value bands, share of world): mixing colours
// read from the theme, a box that reports its size, and saving the drawing as a PNG with
// its flags inlined (a drawing turned into an image cannot fetch them itself).

import { useEffect, useState } from "react";
import { titledPng } from "@/lib/download";

function rgb(c: string): [number, number, number] {
  const s = c.trim();
  if (s.startsWith("#")) {
    const h = s.length === 4 ? s.slice(1).split("").map((x) => x + x).join("") : s.slice(1, 7);
    return [parseInt(h.slice(0, 2), 16), parseInt(h.slice(2, 4), 16), parseInt(h.slice(4, 6), 16)];
  }
  const m = s.match(/[\d.]+/g);
  return m && m.length >= 3 ? [+m[0], +m[1], +m[2]] : [128, 128, 128];
}

// `t` of colour a, the rest of colour b.
export function mix(a: string, b: string, t: number): string {
  const x = rgb(a), y = rgb(b);
  const v = x.map((p, i) => Math.round(p * t + y[i] * (1 - t)));
  return `rgb(${v[0]}, ${v[1]}, ${v[2]})`;
}

// Roughly how light a colour is (0 dark to 1 light), to pick ink that reads on it.
export function lightness(c: string): number {
  const [r, g, b] = rgb(c);
  return (0.299 * r + 0.587 * g + 0.114 * b) / 255;
}

// A box's width and height, kept up to date. Returns a ref callback, so it also works
// for a box that appears only after loading.
export function useBoxSize<T extends HTMLElement>(): [(el: T | null) => void, { w: number; h: number }] {
  const [el, setEl] = useState<T | null>(null);
  const [size, setSize] = useState({ w: 0, h: 0 });
  useEffect(() => {
    if (!el) return;
    const read = () => setSize((s) => {
      const w = Math.round(el.clientWidth), h = Math.round(el.clientHeight);
      return s.w === w && s.h === h ? s : { w, h };
    });
    const ro = new ResizeObserver(read);
    ro.observe(el);
    read();
    return () => ro.disconnect();
  }, [el]);
  return [setEl, size];
}

const flagData = new Map<string, Promise<string | null>>();
function inlineFlag(href: string): Promise<string | null> {
  if (!flagData.has(href)) {
    flagData.set(href, fetch(href).then((r) => (r.ok ? r.text() : null))
      .then((t) => (t ? `data:image/svg+xml;base64,${btoa(unescape(encodeURIComponent(t)))}` : null)).catch(() => null));
  }
  return flagData.get(href)!;
}

// The drawing as a PNG under a title, with every flag image inlined first.
export async function svgPng(svg: SVGSVGElement, title: string, note = "", footer: string[] = []): Promise<string> {
  const copy = svg.cloneNode(true) as SVGSVGElement;
  copy.setAttribute("xmlns", "http://www.w3.org/2000/svg");
  copy.setAttribute("xmlns:xlink", "http://www.w3.org/1999/xlink");
  const w = svg.viewBox.baseVal?.width || svg.clientWidth, h = svg.viewBox.baseVal?.height || svg.clientHeight;
  copy.setAttribute("width", String(w));
  copy.setAttribute("height", String(h));
  const css = getComputedStyle(svg);
  copy.setAttribute("style", `font-family: ${css.fontFamily}`);
  await Promise.all([...copy.querySelectorAll("image")].map(async (img) => {
    const href = img.getAttribute("href") ?? "";
    if (!href || href.startsWith("data:")) return;
    const data = await inlineFlag(new URL(href, location.href).href);
    if (data) img.setAttribute("href", data); else img.remove();
  }));
  const text = new XMLSerializer().serializeToString(copy);
  const src = `data:image/svg+xml;base64,${btoa(unescape(encodeURIComponent(text)))}`;
  return titledPng(src, w, h, title, note, footer);
}

// How wide a piece of text draws at a size and weight, in the page's font.
let measurer: CanvasRenderingContext2D | null = null;
let family = "";
export function textWidth(text: string, size: number, weight = 400): number {
  if (typeof document === "undefined") return text.length * size * 0.55;
  measurer ??= document.createElement("canvas").getContext("2d");
  if (!measurer) return text.length * size * 0.55;
  family ||= getComputedStyle(document.body).fontFamily || "sans-serif";
  const font = `${weight} ${size}px ${family}`;
  if (measurer.font !== font) measurer.font = font;
  return measurer.measureText(text).width;
}
