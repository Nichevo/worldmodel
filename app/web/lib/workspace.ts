// The map page's workspace: a layout of up to four panels, each a map, chart or
// table of one indicator, plus the countries selected across all of them.
// Panels in the same link group (A or B) can share their map position, hover,
// year, indicator and colour scale; selection is shared by every panel that
// links it. The whole state round-trips through the URL so any view can be
// bookmarked.

export type View = "map" | "chart" | "table";
export type Layout = "1" | "2h" | "2v" | "3" | "4";
export type Group = "A" | "B";
export type LinkKey = "camera" | "hover" | "select" | "year" | "indicator" | "scale";
export type Links = Record<LinkKey, boolean>;

export type Panel = {
  id: string;
  view: View;
  indicator: string;
  year: number | null;
  links: Links;
  group: Group;
  offset: number; // years added to the group's year when year is linked
  selection: string[]; // used only while selection is unlinked
  cols: string[]; // extra table columns: other indicators' ids, or CHANGE_COL
};

export type Workspace = {
  layout: Layout;
  panels: Panel[];
  selection: string[];
  maximised: string | null;
  split: [number, number]; // column and row divider positions, as fractions
};

export const LAYOUTS: { id: Layout; label: string; panels: number }[] = [
  { id: "1", label: "One", panels: 1 },
  { id: "2h", label: "Two side by side", panels: 2 },
  { id: "2v", label: "Two stacked", panels: 2 },
  { id: "3", label: "One large, two small", panels: 3 },
  { id: "4", label: "Two by two", panels: 4 },
];

// Letters are the URL form; the order is the order shown in the links menu.
export const LINKS: { key: LinkKey; letter: string; label: string; hint: string }[] = [
  { key: "camera", letter: "c", label: "Map position", hint: "Pan and zoom together" },
  { key: "hover", letter: "h", label: "Hover", hint: "Highlight the hovered country everywhere" },
  { key: "select", letter: "s", label: "Selection", hint: "Share the selected countries" },
  { key: "year", letter: "y", label: "Year", hint: "One year slider for the group" },
  { key: "indicator", letter: "i", label: "Indicator", hint: "Change the indicator together" },
  { key: "scale", letter: "k", label: "Colour scale", hint: "Same colours for the same values when the indicator matches" },
];

// The table column for the change in the panel's indicator over ten years.
export const CHANGE_COL = "chg10";

export const DEFAULT_LINKS: Links = { camera: true, hover: true, select: true, year: false, indicator: false, scale: true };

const VIEWS: View[] = ["map", "chart", "table"];
export const MAX_PANELS = 4;
export const MAX_SELECTION = 8; // one categorical colour each

const count = (layout: Layout) => LAYOUTS.find((l) => l.id === layout)!.panels;
const layoutFor = (n: number, current: Layout): Layout =>
  count(current) === n ? current : n <= 1 ? "1" : n === 2 ? (current === "2v" ? "2v" : "2h") : n === 3 ? "3" : "4";

let nextId = 0;
const newId = () => `p${Date.now().toString(36)}${(nextId++).toString(36)}`;

const panel = (id: string, p: Partial<Panel> = {}): Panel => ({
  id, view: "map", indicator: "tfr", year: null, links: { ...DEFAULT_LINKS }, group: "A", offset: 0, selection: [], cols: [], ...p,
});

export const DEFAULT: Workspace = {
  layout: "1",
  panels: [panel("p0")],
  selection: [],
  maximised: null,
  split: [0.5, 0.5],
};

export type Action =
  | { type: "layout"; layout: Layout }
  | { type: "panel"; id: string; patch: Partial<Pick<Panel, "view" | "indicator" | "year" | "group" | "offset" | "cols">> }
  | { type: "link"; id: string; key: LinkKey; on: boolean }
  | { type: "duplicate"; id: string }
  | { type: "close"; id: string }
  | { type: "maximise"; id: string | null }
  | { type: "split"; split: [number, number] }
  | { type: "toggleSelect"; entity: string; panel?: string }
  | { type: "select"; selection: string[] };

// Other panels in the same group that link this setting.
const peers = (ws: Workspace, p: Panel, key: LinkKey) =>
  ws.panels.filter((q) => q.id !== p.id && q.group === p.group && q.links[key] && p.links[key]);

// Copy a panel's year and indicator to its linked peers.
function propagate(ws: Workspace, id: string, keys: ("year" | "indicator")[]): Workspace {
  const src = ws.panels.find((p) => p.id === id);
  if (!src) return ws;
  const year = new Set(keys.includes("year") ? peers(ws, src, "year").map((p) => p.id) : []);
  const ind = new Set(keys.includes("indicator") ? peers(ws, src, "indicator").map((p) => p.id) : []);
  if (!year.size && !ind.size) return ws;
  return {
    ...ws,
    panels: ws.panels.map((p) => ({
      ...p,
      ...(year.has(p.id) && src.year !== null ? { year: src.year - src.offset + p.offset } : {}),
      ...(ind.has(p.id) ? { indicator: src.indicator } : {}),
    })),
  };
}

// Take a linked setting from the group when a panel joins it.
function adopt(ws: Workspace, id: string, keys: ("year" | "indicator")[]): Workspace {
  const p = ws.panels.find((q) => q.id === id);
  if (!p) return ws;
  let patch: Partial<Panel> = {};
  for (const key of keys) {
    const from = peers(ws, p, key)[0];
    if (!from) continue;
    if (key === "year" && from.year !== null) patch = { ...patch, year: from.year - from.offset + p.offset };
    if (key === "indicator") patch = { ...patch, indicator: from.indicator };
  }
  return { ...ws, panels: ws.panels.map((q) => (q.id === id ? { ...q, ...patch } : q)) };
}

export function reducer(ws: Workspace, a: Action): Workspace {
  switch (a.type) {
    case "layout": {
      const n = count(a.layout);
      const panels = ws.panels.slice(0, n);
      while (panels.length < n) panels.push({ ...panels[panels.length - 1], id: newId() });
      return { ...ws, layout: a.layout, panels, maximised: null };
    }
    case "panel": {
      const next = { ...ws, panels: ws.panels.map((p) => (p.id === a.id ? { ...p, ...a.patch } : p)) };
      if (a.patch.group !== undefined) return adopt(next, a.id, ["year", "indicator"]);
      if (a.patch.offset !== undefined) return adopt(next, a.id, ["year"]);
      const keys: ("year" | "indicator")[] = [];
      if (a.patch.year !== undefined) keys.push("year");
      if (a.patch.indicator !== undefined) keys.push("indicator");
      return propagate(next, a.id, keys);
    }
    case "link": {
      const next = {
        ...ws,
        panels: ws.panels.map((p) => {
          if (p.id !== a.id) return p;
          // A panel leaving the shared selection keeps a copy to start from.
          const selection = a.key === "select" && !a.on ? [...ws.selection] : p.selection;
          return { ...p, links: { ...p.links, [a.key]: a.on }, selection };
        }),
      };
      return a.on && (a.key === "year" || a.key === "indicator") ? adopt(next, a.id, [a.key]) : next;
    }
    case "duplicate": {
      if (ws.panels.length >= MAX_PANELS) return ws;
      const i = ws.panels.findIndex((p) => p.id === a.id);
      if (i < 0) return ws;
      const panels = [...ws.panels.slice(0, i + 1), { ...ws.panels[i], id: newId() }, ...ws.panels.slice(i + 1)];
      return { ...ws, panels, layout: layoutFor(panels.length, ws.layout), maximised: null };
    }
    case "close": {
      if (ws.panels.length <= 1) return ws;
      const panels = ws.panels.filter((p) => p.id !== a.id);
      return { ...ws, panels, layout: layoutFor(panels.length, ws.layout), maximised: null };
    }
    case "maximise":
      return { ...ws, maximised: a.id };
    case "split":
      return { ...ws, split: a.split };
    case "toggleSelect": {
      const own = ws.panels.find((p) => p.id === a.panel && !p.links.select);
      const current = own ? own.selection : ws.selection;
      const has = current.includes(a.entity);
      if (!has && current.length >= MAX_SELECTION) return ws;
      const selection = has ? current.filter((e) => e !== a.entity) : [...current, a.entity];
      if (own) return { ...ws, panels: ws.panels.map((p) => (p.id === own.id ? { ...p, selection } : p)) };
      return { ...ws, selection };
    }
    case "select":
      return { ...ws, selection: a.selection.slice(0, MAX_SELECTION) };
  }
}

// The countries a panel shows: the shared selection, or its own while unlinked.
export const selectionOf = (ws: Workspace, p: Panel) => (p.links.select ? ws.selection : p.selection);

// URL form, kept readable:
//   ?l=4&p=map.tfr.1970~chart.tfr~table.gdp_growth.2023.chsyk.B.-20&s=NZL,AUS&s2=FRA
// Each panel is view.indicator[.year[.links[.group[.offset[.cols]]]]], trailing defaults dropped,
// with extra table columns joined by ",";
// sN holds panel N's own selection while its selection is unlinked.
const DEFAULT_LETTERS = LINKS.filter((l) => DEFAULT_LINKS[l.key]).map((l) => l.letter).join("");

function panelToken(p: Panel): string {
  const letters = LINKS.filter((l) => p.links[l.key]).map((l) => l.letter).join("") || "-";
  const parts = [p.view, p.indicator, p.year ?? "", letters === DEFAULT_LETTERS ? "" : letters, p.group === "A" ? "" : p.group,
    p.offset ? String(p.offset) : "", p.cols.join(",")];
  while (parts.length > 2 && parts[parts.length - 1] === "") parts.pop();
  return parts.join(".");
}

export function toQuery(ws: Workspace): string {
  const q = new URLSearchParams();
  q.set("l", ws.layout);
  q.set("p", ws.panels.map(panelToken).join("~"));
  if (ws.selection.length) q.set("s", ws.selection.join(","));
  ws.panels.forEach((p, i) => { if (!p.links.select && p.selection.length) q.set(`s${i}`, p.selection.join(",")); });
  if (ws.maximised) q.set("max", String(ws.panels.findIndex((p) => p.id === ws.maximised)));
  if (ws.split[0] !== 0.5 || ws.split[1] !== 0.5) q.set("split", ws.split.map((f) => Math.round(f * 100)).join("."));
  return q.toString().replace(/%7E/g, "~").replace(/%2C/g, ",");
}

const list = (s: string | null) => (s || "").split(",").filter(Boolean).slice(0, MAX_SELECTION);

export function fromQuery(q: URLSearchParams): Workspace {
  const panels: Panel[] = (q.get("p") || "")
    .split("~")
    .filter(Boolean)
    .slice(0, MAX_PANELS)
    .map((s, i) => {
      const [view, indicator, year, letters, group, offset, cols] = s.split(".");
      const l = letters === undefined || letters === "" ? DEFAULT_LETTERS : letters;
      return panel(`p${i}`, {
        view: VIEWS.includes(view as View) ? (view as View) : "map",
        indicator: indicator || "tfr",
        year: year && /^\d{4}$/.test(year) ? +year : null,
        links: Object.fromEntries(LINKS.map((k) => [k.key, l.includes(k.letter)])) as Links,
        group: group === "B" ? "B" : "A",
        offset: offset && /^-?\d{1,3}$/.test(offset) ? +offset : 0,
        selection: list(q.get(`s${i}`)),
        cols: (cols || "").split(",").filter((c) => /^[a-z0-9_]+$/.test(c)).slice(0, 8),
      });
    });
  if (!panels.length) return DEFAULT;
  const wanted = LAYOUTS.find((l) => l.id === q.get("l"))?.id ?? "1";
  const layout = layoutFor(panels.length, wanted);
  const max = q.get("max");
  const split = (q.get("split") || "").split(".").map(Number);
  const frac = (n: number) => (n >= 20 && n <= 80 ? n / 100 : 0.5);
  return {
    layout,
    panels,
    selection: list(q.get("s")),
    maximised: max !== null && panels[+max] ? panels[+max].id : null,
    split: [frac(split[0]), frac(split[1])],
  };
}
