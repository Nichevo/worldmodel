// Small shapes for the map's ship and plane layers, drawn once per map on a canvas and added as
// SDF images so each layer can colour them (by kind) and turn them (by heading). They point
// north; icon-rotate turns them to the heading.
import type { ExpressionSpecification, Map as MlMap } from "maplibre-gl";

const SIZE = 48;
// SVG path data on a 48 x 48 grid, nose or bow at the top.
const SHAPES: Record<string, string> = {
  // a hull: pointed bow, square stern, with a bridge block
  "wm-ship": "M24 2 L33 16 L33 45 L15 45 L15 16 Z",
  // an airliner: fuselage, swept wings, tailplane
  "wm-plane": "M24 2 C26 2 27 5 27 8 L27 18 L45 28 L45 32 L27 26 L27 37 L33 42 L33 45 L24 43 L15 45 L15 42 L21 37 L21 26 L3 32 L3 28 L21 18 L21 8 C21 5 22 2 24 2 Z",
  // a light aircraft: straight wings, short body
  "wm-plane-light": "M24 4 C26 4 26.5 7 26.5 10 L26.5 16 L44 17 L44 22 L26.5 22 L26 34 L32 36 L32 40 L24 39 L16 40 L16 36 L22 34 L21.5 22 L4 22 L4 17 L21.5 16 L21.5 10 C21.5 7 22 4 24 4 Z",
  // a helicopter: round body, two rotor blades, tail boom
  "wm-heli": "M22.5 2 L25.5 2 L25.5 15 L44 15 L44 18 L28.5 18 A7 7 0 0 1 27 30 L25.5 30 L25.5 41 L31 43 L31 46 L17 46 L17 43 L22.5 41 L22.5 30 L21 30 A7 7 0 0 1 19.5 18 L4 18 L4 15 L22.5 15 Z",
  // a glider: long thin wings
  "wm-glider": "M24 6 C25.5 6 26 8 26 10 L26 18 L47 20 L47 23 L26 23 L25.5 38 L30 39 L30 42 L18 42 L18 39 L22.5 38 L22 23 L1 23 L1 20 L22 18 L22 10 C22 8 22.5 6 24 6 Z",
};

export function ensureMapIcons(m: MlMap) {
  for (const [id, d] of Object.entries(SHAPES)) {
    if (m.hasImage(id)) continue;
    const c = document.createElement("canvas");
    c.width = SIZE;
    c.height = SIZE;
    const g = c.getContext("2d");
    if (!g) continue;
    g.fillStyle = "#fff";
    g.fill(new Path2D(d));
    const img = g.getImageData(0, 0, SIZE, SIZE);
    m.addImage(id, { width: SIZE, height: SIZE, data: new Uint8Array(img.data.buffer) }, { sdf: true, pixelRatio: 2 });
  }
}

// Ship kinds (from the AIS type code, worked out on the server) and their colours.
export const SHIP_GROUPS: { id: string; label: string; color: string }[] = [
  { id: "cargo", label: "Cargo", color: "#2b8a3e" },
  { id: "tanker", label: "Tanker", color: "#c92a2a" },
  { id: "passenger", label: "Passenger and ferries", color: "#1c7ed6" },
  { id: "fishing", label: "Fishing", color: "#e8590c" },
  { id: "tug", label: "Tugs, pilots and tenders", color: "#5f3dc4" },
  { id: "leisure", label: "Yachts and pleasure craft", color: "#d6336c" },
  { id: "fast", label: "High-speed craft", color: "#0c8599" },
  { id: "official", label: "Navy, coastguard, rescue", color: "#212529" },
  { id: "other", label: "Other", color: "#868e96" },
  { id: "unknown", label: "Not said yet", color: "#adb5bd" },
];
export const PLANE_GROUPS: { id: string; label: string; color: string; icon: string }[] = [
  { id: "airliner", label: "Airliners and big jets", color: "#1864ab", icon: "wm-plane" },
  { id: "light", label: "Light and small planes", color: "#2f9e44", icon: "wm-plane-light" },
  { id: "helicopter", label: "Helicopters", color: "#e67700", icon: "wm-heli" },
  { id: "glider", label: "Gliders and balloons", color: "#9c36b5", icon: "wm-glider" },
  { id: "fast", label: "High performance", color: "#c92a2a", icon: "wm-plane" },
  { id: "drone", label: "Drones", color: "#495057", icon: "wm-plane-light" },
  { id: "unknown", label: "Type not sent", color: "#5c7cfa", icon: "wm-plane" },
];

export const groupColor = (groups: { id: string; color: string }[], fallback: string) =>
  ["match", ["get", "group"], ...groups.flatMap((g) => [g.id, g.color]), fallback] as unknown as ExpressionSpecification;
