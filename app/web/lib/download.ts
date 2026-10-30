// Downloads from a panel: its data as CSV and a picture as PNG. Everything is
// made in the browser from what the panel already shows. Every picture carries a
// footer naming each dataset in it, with its licence and the day it was saved.

import { api, type Indicator, type Source } from "@/lib/api";

export type Exporter = {
  name?: string; // file name without extension
  csv?: () => string; // the panel's data
  png?: () => Promise<string>; // a PNG data URL of the panel's picture
};

export function csvText(header: string[], rows: (string | number | null | undefined)[][]): string {
  const cell = (v: string | number | null | undefined) => {
    if (v === null || v === undefined) return "";
    const s = String(v);
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  return [header, ...rows].map((r) => r.map(cell).join(",")).join("\r\n") + "\r\n";
}

export function saveUrl(url: string, filename: string) {
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
}

export function saveText(text: string, filename: string, type = "text/csv") {
  const url = URL.createObjectURL(new Blob([text], { type: `${type};charset=utf-8` }));
  saveUrl(url, filename);
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function fileName(...parts: (string | number | null | undefined)[]): string {
  return parts.filter((p) => p !== null && p !== undefined && p !== "").join("-").toLowerCase().replace(/[^a-z0-9._-]+/g, "-");
}

let sourceList: Promise<Map<string, Source>> | null = null;
function sourceInfo(): Promise<Map<string, Source>> {
  sourceList ??= api.sources().then((r) => new Map(r.map((s) => [s.source_id, s])))
    .catch(() => { sourceList = null; return new Map(); });
  return sourceList;
}

// The sources an indicator's values come from: its first-ranked source, or every
// source of the rows actually drawn when they are known. Your ratios' rows say
// "user"; they are credited to the sources of their two parts.
export function sourcesOf(ind: Indicator | null | undefined, rows?: { source_id?: string | null }[]): string[] {
  const used = [...new Set((rows ?? []).map((r) => r.source_id).filter((s): s is string => !!s && s !== "user"))];
  if (used.length) return used;
  return ind?.sources.filter((s) => s.rank === 1).map((s) => s.source_id) ?? [];
}

// The footer lines of a picture: one per source (its credit line and licence), any
// extra credits (map borders), and the day it was saved.
export async function credits(sourceIds: (string | null | undefined)[], extra: string[] = []): Promise<string[]> {
  const info = await sourceInfo();
  const ids = [...new Set(sourceIds.filter((s): s is string => !!s))];
  const lines = ids.map((id) => {
    const s = info.get(id);
    if (!s) return id === "user" ? "Your own milestones." : id;
    const licence = s.licence.split(";")[0].trim();
    return `${s.attribution.replace(/\.$/, "")}.${licence ? ` Licence: ${licence}.` : ""}`;
  });
  return [...lines.map((l, i) => (i === 0 ? `Sources: ${l}` : l)), ...extra,
    `Saved from Worldmodel on ${new Date().toISOString().slice(0, 10)}.`];
}

const FOOT_FONT = "11px system-ui, -apple-system, 'Segoe UI', sans-serif";
const FOOT_LINE = 15;

// Break footer lines to fit a width (in the footer font).
function wrapLines(ctx: CanvasRenderingContext2D, lines: string[], width: number): string[] {
  ctx.font = FOOT_FONT;
  return lines.flatMap((line) => {
    const out: string[] = [];
    let cur = "";
    for (const word of line.split(" ")) {
      const next = cur ? `${cur} ${word}` : word;
      if (cur && ctx.measureText(next).width > width) { out.push(cur); cur = word; } else cur = next;
    }
    return cur ? [...out, cur] : out;
  });
}

function drawFooter(ctx: CanvasRenderingContext2D, lines: string[], top: number) {
  const css = getComputedStyle(document.documentElement);
  ctx.fillStyle = css.getPropertyValue("--muted").trim() || "#666";
  ctx.font = FOOT_FONT;
  ctx.textAlign = "left";
  lines.forEach((l, i) => ctx.fillText(l, 8, top + 13 + i * FOOT_LINE));
}

function loadImage(src: string): Promise<HTMLImageElement> {
  return new Promise((ok, fail) => {
    const img = new Image();
    img.onload = () => ok(img);
    img.onerror = () => fail(new Error("could not draw the picture"));
    img.src = src;
  });
}

// Draw an image (an SVG chart or the map's canvas) under a title line, at twice
// the screen size, on the page background so it reads anywhere.
export async function titledPng(src: string, width: number, height: number, title: string, note = "", footer: string[] = []): Promise<string> {
  const img = await loadImage(src);
  const scale = 2, head = note ? 46 : 30;
  const canvas = document.createElement("canvas");
  const foot = wrapLines(canvas.getContext("2d")!, footer, width - 16);
  const footH = foot.length ? foot.length * FOOT_LINE + 10 : 0;
  canvas.width = width * scale;
  canvas.height = (height + head + footH) * scale;
  const ctx = canvas.getContext("2d")!;
  ctx.scale(scale, scale);
  const css = getComputedStyle(document.documentElement);
  ctx.fillStyle = css.getPropertyValue("--surface").trim() || "#fff";
  ctx.fillRect(0, 0, width, height + head + footH);
  ctx.fillStyle = css.getPropertyValue("--ink").trim() || "#000";
  ctx.font = "600 14px system-ui, -apple-system, 'Segoe UI', sans-serif";
  ctx.fillText(title, 8, 19);
  if (note) {
    ctx.fillStyle = css.getPropertyValue("--muted").trim() || "#666";
    ctx.font = "11px system-ui, -apple-system, 'Segoe UI', sans-serif";
    ctx.fillText(note, 8, 36);
  }
  ctx.drawImage(img, 0, head, width, height);
  if (foot.length) drawFooter(ctx, foot, head + height + 4);
  return canvas.toDataURL("image/png");
}

// A plain picture of a table's first rows, for panels with no drawing of their own.
export function tablePng(title: string, header: string[], rows: string[][], max = 40, footer: string[] = []): string {
  const shown = rows.slice(0, max);
  const css = getComputedStyle(document.documentElement);
  const scale = 2, lineH = 20, top = 34;
  const canvas = document.createElement("canvas");
  const ctx = canvas.getContext("2d")!;
  ctx.font = "13px system-ui, -apple-system, 'Segoe UI', sans-serif";
  const widths = header.map((h, i) => Math.min(260, Math.max(ctx.measureText(h).width, ...shown.map((r) => ctx.measureText(r[i] ?? "").width)) + 18));
  const width = Math.max(320, widths.reduce((a, b) => a + b, 16));
  const foot = wrapLines(ctx, footer, width - 16);
  const body = top + lineH * (shown.length + 1) + (rows.length > max ? lineH : 0) + 8;
  const height = body + (foot.length ? foot.length * FOOT_LINE + 10 : 0);
  canvas.width = width * scale;
  canvas.height = height * scale;
  ctx.scale(scale, scale);
  ctx.fillStyle = css.getPropertyValue("--surface").trim() || "#fff";
  ctx.fillRect(0, 0, width, height);
  ctx.fillStyle = css.getPropertyValue("--ink").trim() || "#000";
  ctx.font = "600 14px system-ui, -apple-system, 'Segoe UI', sans-serif";
  ctx.fillText(title, 8, 19);
  const line = (cells: string[], y: number, bold: boolean) => {
    ctx.font = `${bold ? "600 " : ""}13px system-ui, -apple-system, 'Segoe UI', sans-serif`;
    let x = 8;
    cells.forEach((c, i) => {
      const right = i > 1 || /^[-+\d]/.test(c);
      ctx.textAlign = right ? "right" : "left";
      ctx.fillText(c, right ? x + widths[i] - 10 : x, y);
      x += widths[i];
    });
    ctx.textAlign = "left";
  };
  line(header, top + 14, true);
  ctx.fillStyle = css.getPropertyValue("--ink-2").trim() || "#333";
  shown.forEach((r, i) => line(r, top + 14 + lineH * (i + 1), false));
  if (rows.length > max) {
    ctx.fillStyle = css.getPropertyValue("--muted").trim() || "#666";
    ctx.fillText(`… and ${rows.length - max} more rows (the CSV has them all)`, 8, top + 14 + lineH * (shown.length + 1));
  }
  if (foot.length) drawFooter(ctx, foot, body);
  return canvas.toDataURL("image/png");
}
