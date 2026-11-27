// The colour of each kind of power plant: the Power plants dots, their grounds, the legend and the
// Places in view table all use these (fuel names as WRI's database and lib/power.py give them).
import type { ExpressionSpecification } from "maplibre-gl";

export const FUEL_COLOURS: [fuel: string, colour: string][] = [
  ["Coal", "#343a40"], ["Gas", "#868e96"], ["Oil", "#5c3d2e"], ["Nuclear", "#7048e8"], ["Hydro", "#1c7ed6"],
  ["Geothermal", "#e8590c"], ["Wind", "#37b24d"], ["Solar", "#f59f00"], ["Biomass", "#82c91e"], ["Waste", "#a9a9a9"],
  ["Storage", "#e64980"], ["Wave and Tidal", "#15aabf"],
];
export const OTHER_FUEL = "#adb5bd";
const BY_FUEL = new Map(FUEL_COLOURS);
export const fuelColour = (fuel?: string | null) => BY_FUEL.get(fuel ?? "") ?? OTHER_FUEL;

// A MapLibre expression colouring a feature by its "fuel" property.
export const fuelColourExpr = (): ExpressionSpecification =>
  ["match", ["get", "fuel"], ...FUEL_COLOURS.flat(), OTHER_FUEL] as unknown as ExpressionSpecification;
