// The map page's workspace: a layout of up to four panels, each a map, chart or
// table of one indicator, plus the countries selected across all of them.
// The whole state round-trips through the URL so any view can be bookmarked.

export type View = "map" | "chart" | "table";
export type Layout = "1" | "2h" | "2v" | "3" | "4";

export type Panel = { id: string; view: View; indicator: string; year: number | null };

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

const VIEWS: View[] = ["map", "chart", "table"];
export const MAX_PANELS = 4;
export const MAX_SELECTION = 8; // one categorical colour each

const count = (layout: Layout) => LAYOUTS.find((l) => l.id === layout)!.panels;
const layoutFor = (n: number, current: Layout): Layout =>
  count(current) === n ? current : n <= 1 ? "1" : n === 2 ? (current === "2v" ? "2v" : "2h") : n === 3 ? "3" : "4";

let nextId = 0;
const newId = () => `p${Date.now().toString(36)}${(nextId++).toString(36)}`;

export const DEFAULT: Workspace = {
  layout: "1",
  panels: [{ id: "p0", view: "map", indicator: "tfr", year: null }],
  selection: [],
  maximised: null,
  split: [0.5, 0.5],
};

export type Action =
  | { type: "layout"; layout: Layout }
  | { type: "panel"; id: string; patch: Partial<Omit<Panel, "id">> }
  | { type: "duplicate"; id: string }
  | { type: "close"; id: string }
  | { type: "maximise"; id: string | null }
  | { type: "split"; split: [number, number] }
  | { type: "toggleSelect"; entity: string }
  | { type: "select"; selection: string[] };

export function reducer(ws: Workspace, a: Action): Workspace {
  switch (a.type) {
    case "layout": {
      const n = count(a.layout);
      const panels = ws.panels.slice(0, n);
      while (panels.length < n) panels.push({ ...panels[panels.length - 1], id: newId() });
      return { ...ws, layout: a.layout, panels, maximised: null };
    }
    case "panel":
      return { ...ws, panels: ws.panels.map((p) => (p.id === a.id ? { ...p, ...a.patch } : p)) };
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
      const has = ws.selection.includes(a.entity);
      if (!has && ws.selection.length >= MAX_SELECTION) return ws;
      return { ...ws, selection: has ? ws.selection.filter((e) => e !== a.entity) : [...ws.selection, a.entity] };
    }
    case "select":
      return { ...ws, selection: a.selection.slice(0, MAX_SELECTION) };
  }
}

// URL form, kept readable: ?l=4&p=map.tfr.1970~chart.tfr~table.gdp_growth.2023&s=NZL,AUS&split=50.50
export function toQuery(ws: Workspace): string {
  const q = new URLSearchParams();
  q.set("l", ws.layout);
  q.set("p", ws.panels.map((p) => [p.view, p.indicator, p.year ?? ""].join(".").replace(/\.$/, "")).join("~"));
  if (ws.selection.length) q.set("s", ws.selection.join(","));
  if (ws.maximised) q.set("max", String(ws.panels.findIndex((p) => p.id === ws.maximised)));
  if (ws.split[0] !== 0.5 || ws.split[1] !== 0.5) q.set("split", ws.split.map((f) => Math.round(f * 100)).join("."));
  return q.toString().replace(/%7E/g, "~").replace(/%2C/g, ",");
}

export function fromQuery(q: URLSearchParams): Workspace {
  const panels: Panel[] = (q.get("p") || "")
    .split("~")
    .filter(Boolean)
    .slice(0, MAX_PANELS)
    .map((s, i) => {
      const [view, indicator, year] = s.split(".");
      return {
        id: `p${i}`,
        view: VIEWS.includes(view as View) ? (view as View) : "map",
        indicator: indicator || "tfr",
        year: year && /^\d{4}$/.test(year) ? +year : null,
      };
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
    selection: (q.get("s") || "").split(",").filter(Boolean).slice(0, MAX_SELECTION),
    maximised: max !== null && panels[+max] ? panels[+max].id : null,
    split: [frac(split[0]), frac(split[1])],
  };
}
