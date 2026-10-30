// The map page's workspace: a layout of up to six panels, each a map, chart,
// table, pyramid or scatter of one indicator, plus the countries selected across all of them.
// Panels in the same link group (A or B) can share their map position, hover,
// year, indicator and colour scale; selection is shared by every panel that
// links it. The whole state round-trips through the URL so any view can be
// bookmarked. Countries can also be pinned as popups (up to four, on their
// panel) and sent to the side panel's pinboard; both are saved with the layout.

export type View = "map" | "chart" | "table" | "pyramid" | "scatter";
export type Layout = "1" | "2h" | "2v" | "3" | "3h" | "4" | "5" | "6";
export type Group = "A" | "B";
export type LinkKey = "camera" | "hover" | "select" | "year" | "indicator" | "scale" | "range";
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
  pyr: string; // pyramid options: "" overlays the second selected country, "-" none, "1975" that year; "a" suffix = absolute
  xy: string; // scatter options: "y,size,flags,colour" (the panel's indicator is x; see scatterOptions); flags "o" (trim outliers) and "g" (governing party) also apply to charts
  range: string; // chart years: "" all, "h10f5" ten years back and five ahead of today, "1990-2030" a dragged span (see chartRange)
  layers: string; // map overlays, one letter each (see MAP_LAYERS): "pv" plate boundaries and volcanoes
};

// A popup pinned open: on a map it sits at lng/lat and moves with the map; elsewhere in its panel's corner.
export type Pin = { entity: string; panel: string; lng?: number; lat?: number };
// A card on the side panel's pinboard: one country and indicator.
export type BoardItem = { entity: string; indicator: string };

export type Workspace = {
  layout: Layout;
  panels: Panel[];
  selection: string[];
  maximised: string | null;
  split: [number, number]; // column and row divider positions, as fractions
  pins: Pin[];
  board: BoardItem[];
  side: boolean; // pinboard shown (when the side panel is on in Settings)
};

export const LAYOUTS: { id: Layout; label: string; panels: number }[] = [
  { id: "1", label: "One", panels: 1 },
  { id: "2h", label: "Two side by side", panels: 2 },
  { id: "2v", label: "Two stacked", panels: 2 },
  { id: "3", label: "One large, two small", panels: 3 },
  { id: "3h", label: "Three side by side", panels: 3 },
  { id: "4", label: "Two by two", panels: 4 },
  { id: "5", label: "One large, four small", panels: 5 },
  { id: "6", label: "Three by two", panels: 6 },
];

// Letters are the URL form; the order is the order shown in the links menu.
export const LINKS: { key: LinkKey; letter: string; label: string; hint: string }[] = [
  { key: "camera", letter: "c", label: "Map position", hint: "Pan and zoom together" },
  { key: "hover", letter: "h", label: "Hover", hint: "Highlight the hovered country everywhere" },
  { key: "select", letter: "s", label: "Selection", hint: "Share the selected countries" },
  { key: "year", letter: "y", label: "Year", hint: "One year slider for the group" },
  { key: "indicator", letter: "i", label: "Indicator", hint: "Change the indicator together" },
  { key: "scale", letter: "k", label: "Colour scale", hint: "Same colours for the same values when the indicator matches" },
  { key: "range", letter: "r", label: "Chart years", hint: "Charts in the group show the same span of years" },
];

// The table column for the change in the panel's indicator over ten years.
export const CHANGE_COL = "chg10";

export const DEFAULT_LINKS: Links = { camera: true, hover: true, select: true, year: false, indicator: false, scale: true, range: false };

const VIEWS: View[] = ["map", "chart", "table", "pyramid", "scatter"];
export const MAX_PANELS = 6;
export const MAX_SELECTION = 8; // one categorical colour each
export const MAX_PINS = 4;
export const MAX_BOARD = 12;

const count = (layout: Layout) => LAYOUTS.find((l) => l.id === layout)!.panels;
const layoutFor = (n: number, current: Layout): Layout =>
  count(current) === n ? current : n <= 1 ? "1" : n === 2 ? (current === "2v" ? "2v" : "2h")
    : n === 3 ? (current === "3h" ? "3h" : "3") : n === 4 ? "4" : n === 5 ? "5" : "6";

let nextId = 0;
const newId = () => `p${Date.now().toString(36)}${(nextId++).toString(36)}`;

const panel = (id: string, p: Partial<Panel> = {}): Panel => ({
  id, view: "map", indicator: "tfr", year: null, links: { ...DEFAULT_LINKS }, group: "A", offset: 0, selection: [], cols: [], pyr: "", xy: "", range: "", layers: "", ...p,
});

export const DEFAULT: Workspace = {
  layout: "1",
  panels: [panel("p0")],
  selection: [],
  maximised: null,
  split: [0.5, 0.5],
  pins: [],
  board: [],
  side: true,
};

export type Action =
  | { type: "layout"; layout: Layout }
  | { type: "panel"; id: string; patch: Partial<Pick<Panel, "view" | "indicator" | "year" | "group" | "offset" | "cols" | "pyr" | "xy" | "range" | "layers">> }
  | { type: "load"; ws: Workspace }
  | { type: "link"; id: string; key: LinkKey; on: boolean }
  | { type: "duplicate"; id: string }
  | { type: "close"; id: string }
  | { type: "maximise"; id: string | null }
  | { type: "split"; split: [number, number] }
  | { type: "toggleSelect"; entity: string; panel?: string }
  | { type: "select"; selection: string[] }
  | { type: "pin"; pin: Pin }
  | { type: "unpin"; entity: string; panel: string }
  | { type: "board"; item: BoardItem; on: boolean }
  | { type: "clearBoard" }
  | { type: "side"; on: boolean };

// Other panels in the same group that link this setting.
const peers = (ws: Workspace, p: Panel, key: LinkKey) =>
  ws.panels.filter((q) => q.id !== p.id && q.group === p.group && q.links[key] && p.links[key]);

type Shared = "year" | "indicator" | "range";

// Copy a panel's year, indicator and chart years to its linked peers.
function propagate(ws: Workspace, id: string, keys: Shared[]): Workspace {
  const src = ws.panels.find((p) => p.id === id);
  if (!src) return ws;
  const year = new Set(keys.includes("year") ? peers(ws, src, "year").map((p) => p.id) : []);
  const ind = new Set(keys.includes("indicator") ? peers(ws, src, "indicator").map((p) => p.id) : []);
  const range = new Set(keys.includes("range") ? peers(ws, src, "range").map((p) => p.id) : []);
  if (!year.size && !ind.size && !range.size) return ws;
  return {
    ...ws,
    panels: ws.panels.map((p) => ({
      ...p,
      ...(year.has(p.id) && src.year !== null ? { year: src.year - src.offset + p.offset } : {}),
      ...(ind.has(p.id) ? { indicator: src.indicator } : {}),
      ...(range.has(p.id) ? { range: src.range } : {}),
    })),
  };
}

// Take a linked setting from the group when a panel joins it.
function adopt(ws: Workspace, id: string, keys: Shared[]): Workspace {
  const p = ws.panels.find((q) => q.id === id);
  if (!p) return ws;
  let patch: Partial<Panel> = {};
  for (const key of keys) {
    const from = peers(ws, p, key)[0];
    if (!from) continue;
    if (key === "year" && from.year !== null) patch = { ...patch, year: from.year - from.offset + p.offset };
    if (key === "indicator") patch = { ...patch, indicator: from.indicator };
    if (key === "range") patch = { ...patch, range: from.range };
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
      if (a.patch.group !== undefined) return adopt(next, a.id, ["year", "indicator", "range"]);
      if (a.patch.offset !== undefined) return adopt(next, a.id, ["year"]);
      const keys: Shared[] = [];
      if (a.patch.year !== undefined) keys.push("year");
      if (a.patch.indicator !== undefined) keys.push("indicator");
      if (a.patch.range !== undefined) keys.push("range");
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
      return a.on && (a.key === "year" || a.key === "indicator" || a.key === "range") ? adopt(next, a.id, [a.key]) : next;
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
      return { ...ws, panels, layout: layoutFor(panels.length, ws.layout), maximised: null, pins: ws.pins.filter((p) => p.panel !== a.id) };
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
    case "load":
      return a.ws;
    case "select":
      return { ...ws, selection: a.selection.slice(0, MAX_SELECTION) };
    case "pin": {
      // Pinning a country again on the same panel moves it; past the limit the oldest pin goes.
      const rest = ws.pins.filter((p) => !(p.entity === a.pin.entity && p.panel === a.pin.panel));
      return { ...ws, pins: [...rest, a.pin].slice(-MAX_PINS) };
    }
    case "unpin":
      return { ...ws, pins: ws.pins.filter((p) => !(p.entity === a.entity && p.panel === a.panel)) };
    case "board": {
      const rest = ws.board.filter((b) => !(b.entity === a.item.entity && b.indicator === a.item.indicator));
      return { ...ws, board: a.on ? [a.item, ...rest].slice(0, MAX_BOARD) : rest, side: a.on ? true : ws.side };
    }
    case "clearBoard":
      return { ...ws, board: [] };
    case "side":
      return { ...ws, side: a.on };
  }
}

// The countries a panel shows: the shared selection, or its own while unlinked.
export const selectionOf = (ws: Workspace, p: Panel) => (p.links.select ? ws.selection : p.selection);

// Overlays a map panel can draw over the countries, from the warehouse's layers table.
export const MAP_LAYERS = [
  { letter: "p", id: "plate_boundaries", label: "Tectonic plate boundaries" },
  { letter: "f", id: "active_faults", label: "Active faults" },
  { letter: "v", id: "volcanoes", label: "Volcanoes" },
  { letter: "q", id: "earthquakes", label: "Earthquakes (magnitude 6+)" },
] as const;

// URL form, kept readable:
//   ?l=4&p=map.tfr.1970~chart.tfr~table.gdp_growth.2023.chsyk.B.-20&s=NZL,AUS&s2=FRA
// Each panel is view.indicator[.year[.links[.group[.offset[.cols[.pyr[.xy[.range[.layers]]]]]]]]], trailing defaults dropped,
// with extra table columns joined by ",";
// sN holds panel N's own selection while its selection is unlinked;
// pin=NZL:0:174.8:-41.3,AUS:1 holds pinned popups (country:panel number[:lng:lat]);
// b=NZL:tfr,AUS:gdp_growth the pinboard; side=0 a hidden pinboard.
const DEFAULT_LETTERS = LINKS.filter((l) => DEFAULT_LINKS[l.key]).map((l) => l.letter).join("");

function panelToken(p: Panel): string {
  const letters = LINKS.filter((l) => p.links[l.key]).map((l) => l.letter).join("") || "-";
  const parts = [p.view, p.indicator, p.year ?? "", letters === DEFAULT_LETTERS ? "" : letters, p.group === "A" ? "" : p.group,
    p.offset ? String(p.offset) : "", p.cols.join(","), p.pyr, p.xy, p.range, p.layers];
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
  const pins = ws.pins.map((p) => {
    const i = ws.panels.findIndex((x) => x.id === p.panel);
    return i < 0 ? "" : [p.entity, i, ...(p.lng !== undefined && p.lat !== undefined ? [p.lng.toFixed(2), p.lat.toFixed(2)] : [])].join(":");
  }).filter(Boolean);
  if (pins.length) q.set("pin", pins.join(","));
  if (ws.board.length) q.set("b", ws.board.map((b) => `${b.entity}:${b.indicator}`).join(","));
  if (!ws.side) q.set("side", "0");
  return q.toString().replace(/%7E/g, "~").replace(/%2C/g, ",").replace(/%3A/g, ":");
}

const list = (s: string | null) => (s || "").split(",").filter(Boolean).slice(0, MAX_SELECTION);

export function fromQuery(q: URLSearchParams): Workspace {
  const panels: Panel[] = (q.get("p") || "")
    .split("~")
    .filter(Boolean)
    .slice(0, MAX_PANELS)
    .map((s, i) => {
      const [view, indicator, year, letters, group, offset, cols, pyr, xy, range, layers] = s.split(".");
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
        pyr: pyr && /^(-|\d{4})?a?$/.test(pyr) ? pyr : "",
        xy: xy && /^[a-z0-9_]*(,[a-z0-9_]*(,[xymaog]{0,6}(,[a-z0-9_-]*)?)?)?$/.test(xy) ? xy : "",
        range: range && RANGE_RE.test(range) ? range : "",
        layers: layers ? [...new Set(layers)].filter((c) => MAP_LAYERS.some((m) => m.letter === c)).join("") : "",
      });
    });
  if (!panels.length) return DEFAULT;
  const wanted = LAYOUTS.find((l) => l.id === q.get("l"))?.id ?? "1";
  const layout = layoutFor(panels.length, wanted);
  const max = q.get("max");
  const split = (q.get("split") || "").split(".").map(Number);
  const frac = (n: number) => (n >= 20 && n <= 80 ? n / 100 : 0.5);
  const ENTITY = /^[A-Za-z0-9_-]{1,60}$/;
  const pins: Pin[] = (q.get("pin") || "").split(",").map((t) => t.split(":")).flatMap(([entity, i, lng, lat]) => {
    const p = panels[+i];
    if (!entity || !ENTITY.test(entity) || !p) return [];
    const ll = lng !== undefined && lat !== undefined && Number.isFinite(+lng) && Number.isFinite(+lat) ? { lng: +lng, lat: +lat } : {};
    return [{ entity, panel: p.id, ...ll }];
  }).slice(-MAX_PINS);
  const board: BoardItem[] = (q.get("b") || "").split(",").map((t) => t.split(":"))
    .filter(([e, i]) => e && i && ENTITY.test(e) && /^[a-z0-9_]+$/.test(i))
    .map(([entity, indicator]) => ({ entity, indicator })).slice(0, MAX_BOARD);
  return {
    layout,
    panels,
    selection: list(q.get("s")),
    maximised: max !== null && panels[+max] ? panels[+max].id : null,
    split: [frac(split[0]), frac(split[1])],
    pins,
    board,
    side: q.get("side") !== "0",
  };
}

// Chart year spans. Quick choices count from this year: history 5/10/25/50 years
// back or all, forecast none/5/10/25 years ahead or all. A dragged span is "1990-2030".
const RANGE_RE = /^((h(5|10|25|50|a))?(f(0|5|10|25|a))?|\d{4}-\d{4})$/;
export const HISTORY_CHOICES = ["5", "10", "25", "50", "a"] as const;
export const FORECAST_CHOICES = ["0", "5", "10", "25", "a"] as const;

export type ChartRange = { history: string; forecast: string; custom: [number, number] | null };

export function parseRange(range: string): ChartRange {
  const m = range.match(/^(\d{4})-(\d{4})$/);
  if (m) return { history: "", forecast: "", custom: [+m[1], +m[2]] };
  return { history: range.match(/h(\d+|a)/)?.[1] ?? "a", forecast: range.match(/f(\d+|a)/)?.[1] ?? "a", custom: null };
}

export function rangeString(r: { history: string; forecast: string }): string {
  return `${r.history === "a" ? "" : `h${r.history}`}${r.forecast === "a" ? "" : `f${r.forecast}`}`;
}

// The years to show, or null for everything.
export function chartSpan(range: string, today = new Date().getFullYear()): [number | null, number | null] {
  const r = parseRange(range);
  if (r.custom) return r.custom;
  return [r.history === "a" ? null : today - +r.history, r.forecast === "a" ? null : today + +r.forecast];
}

// Pyramid options, unpacked from the panel's pyr string.
export function pyramidOptions(pyr: string): { compare: "auto" | "none" | number; absolute: boolean } {
  const absolute = pyr.endsWith("a");
  const head = absolute ? pyr.slice(0, -1) : pyr;
  return { compare: head === "-" ? "none" : /^\d{4}$/.test(head) ? +head : "auto", absolute };
}

export function pyramidString(o: { compare: "auto" | "none" | number; absolute: boolean }): string {
  return `${o.compare === "none" ? "-" : o.compare === "auto" ? "" : o.compare}${o.absolute ? "a" : ""}`;
}

// Scatter options. colour: "" = only selected countries stand out, "continent" or
// "subregion" = one colour per region, any other id = members of that group.
// labels: names next to selected dots only, the biggest ("major") or all.
// trim: fit the axes to the bulk of the countries, outliers drawn at the edge.
export type ScatterOptions = {
  y: string; size: string; logX: boolean; logY: boolean; colour: string; labels: "selected" | "major" | "all"; trim: boolean;
  party: boolean; // line charts of one country: coloured by the party in government
};

export function scatterOptions(xy: string): ScatterOptions {
  const [y = "", size = "", flags = "", colour = ""] = xy.split(",");
  return { y, size, logX: flags.includes("x"), logY: flags.includes("y"), colour, trim: flags.includes("o"), party: flags.includes("g"),
    labels: flags.includes("a") ? "all" : flags.includes("m") ? "major" : "selected" };
}

export function scatterString(o: ScatterOptions): string {
  const flags = `${o.logX ? "x" : ""}${o.logY ? "y" : ""}${o.labels === "all" ? "a" : o.labels === "major" ? "m" : ""}${o.trim ? "o" : ""}${o.party ? "g" : ""}`;
  const s = [o.y, o.size, flags, o.colour];
  while (s.length && s[s.length - 1] === "") s.pop();
  return s.join(",");
}

// Starting points offered in the Layouts menu, built from the same parts as the URL.
function starter(layout: Layout, panels: Partial<Panel>[], selection: string[] = []): string {
  return toQuery({ ...DEFAULT, layout, panels: panels.map((p, i) => panel(`p${i}`, p)), selection });
}

export const STARTERS: { name: string; query: string }[] = [
  { name: "Fertility across time",
    query: starter("4", [1970, 1995, 2023, 2050].map((year) => ({ view: "map" as View, indicator: "tfr", year }))) },
  { name: "Ageing: two pyramids",
    query: starter("2h", [
      { view: "pyramid", year: 2023, links: { ...DEFAULT_LINKS, year: true } },
      { view: "pyramid", year: 2023, pyr: "1975", links: { ...DEFAULT_LINKS, year: true } },
    ], ["JPN", "NER"]) },
  { name: "Country focus",
    query: starter("3", [
      { view: "map", indicator: "tfr" },
      { view: "chart", indicator: "tfr" },
      { view: "table", indicator: "tfr", cols: [CHANGE_COL, "life_expectancy", "gdp_growth"] },
    ], ["NZL", "AUS"]) },
  { name: "Wealth and health (bubbles)",
    query: starter("1", [{ view: "scatter", indicator: "gdp_ppp_per_capita", xy: "life_expectancy,pop_total,xm,continent" }], ["CHN", "IND", "USA"]) },
  { name: "Fertility and growth",
    query: starter("2h", [{ view: "map", indicator: "tfr" }, { view: "map", indicator: "gdp_growth" }]) },
  { name: "Life expectancy across time",
    query: starter("6", [1960, 1975, 1990, 2005, 2023, 2050].map((year) => ({ view: "map" as View, indicator: "life_expectancy", year }))) },
  { name: "New Zealand by governing party",
    query: starter("4", ["gdp_growth", "unemployment", "inflation", "net_migration_rate"].map((indicator) =>
      ({ view: "chart" as View, indicator, xy: ",,g", range: "h50f0" })), ["NZL"]) },
  { name: "UK growth by governing party",
    query: starter("2v", [
      { view: "chart", indicator: "gdp_growth", xy: ",,g", range: "h50f0" },
      { view: "chart", indicator: "gdp_per_capita_usd", xy: ",,g", range: "h50f0" },
    ], ["GBR"]) },
  { name: "Energy transition",
    query: starter("3", [
      { view: "map", indicator: "renewables_share_elec" },
      { view: "chart", indicator: "renewables_share_elec", cols: ["coal_share_elec"] },
      { view: "scatter", indicator: "gdp_ppp_per_capita", xy: "co2_per_capita,pop_total,xm,continent" },
    ], ["DEU", "GBR", "CHN"]) },
  { name: "Rich and old (bubbles)",
    query: starter("2h", [
      { view: "scatter", indicator: "gdp_ppp_per_capita", xy: "median_age,pop_total,xm,continent" },
      { view: "map", indicator: "pop_share_65_plus" },
    ], ["JPN", "NGA", "USA"]) },
  { name: "Growth and inflation, three crises",
    query: starter("6", [
      ...[1998, 2009, 2020].map((year) => ({ view: "map" as View, indicator: "gdp_growth", year })),
      ...[1998, 2009, 2022].map((year) => ({ view: "map" as View, indicator: "inflation", year })),
    ]) },
  { name: "Military spending",
    query: starter("3", [
      { view: "map", indicator: "military_spending_gdp" },
      { view: "chart", indicator: "military_spending_gdp", range: "h50f0" },
      { view: "table", indicator: "military_spending_gdp", cols: [CHANGE_COL, "gdp_ppp_per_capita"] },
    ], ["USA", "CHN", "RUS"]) },
  { name: "Debt and credit",
    query: starter("2h", [
      { view: "map", indicator: "central_govt_debt_gdp" },
      { view: "chart", indicator: "private_credit_gdp", cols: ["central_govt_debt_gdp"], range: "h50f0" },
    ], ["USA", "JPN"]) },
  { name: "Migration and ageing",
    query: starter("3", [
      { view: "map", indicator: "net_migration_rate" },
      { view: "map", indicator: "median_age" },
      { view: "scatter", indicator: "median_age", xy: "net_migration_rate,pop_total,,continent" },
    ]) },
  { name: "Price levels and income",
    query: starter("2h", [
      { view: "map", indicator: "price_level_ratio" },
      { view: "scatter", indicator: "gdp_ppp_per_capita", xy: "price_level_ratio,pop_total,xm,continent" },
    ], ["NZL", "CHE", "IND"]) },
  { name: "House prices and debt",
    query: starter("3", [
      { view: "map", indicator: "oecd_price_to_income_vs_avg" },
      { view: "chart", indicator: "bis_house_price_real", range: "h50f0" },
      { view: "chart", indicator: "bis_household_credit_gdp", range: "h50f0" },
    ], ["NZL", "AUS", "GBR", "USA"]) },
  { name: "Migration in and out",
    query: starter("3", [
      { view: "map", indicator: "migrant_stock" },
      { view: "map", indicator: "emigrant_stock" },
      { view: "chart", indicator: "migrant_stock", cols: ["emigrant_stock"] },
    ], ["NZL"]) },
  { name: "Refugees",
    query: starter("2h", [
      { view: "map", indicator: "refugees_hosted" },
      { view: "map", indicator: "refugees_from" },
    ]) },
  { name: "Schooling to 2100",
    query: starter("3", [
      { view: "map", indicator: "wic_mys", year: 2020 },
      { view: "map", indicator: "wic_mys", year: 2060 },
      { view: "chart", indicator: "wic_mys", range: "1950-2100" },
    ], ["NZL", "IND", "NGA"]) },
  { name: "Voter turnout",
    query: starter("2h", [
      { view: "map", indicator: "turnout_parliamentary" },
      { view: "chart", indicator: "turnout_parliamentary", range: "h50f0" },
    ], ["NZL", "GBR", "AUS"]) },
];
