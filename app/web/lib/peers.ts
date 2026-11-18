// How a country ranks among a group (the API's /peers).
import { get } from "@/lib/api";

export type PeerCell = { entity_id: string; name: string; value: number; year: number };
export type PeerRow = {
  indicator_id: string; name: string; unit: string; decimals: number; better: "higher" | "lower"; year: number; of: number;
  best: PeerCell & { tied: number }; worst: PeerCell & { tied: number }; middle: number;
  me: (PeerCell & { rank: number; position: number }) | null;
  ranked: (PeerCell & { rank: number })[];
};
export type PeerGroup = { id: string; name: string; type: string };
export type Peers = {
  entity_id: string; name: string; group: string; groups: PeerGroup[];
  members: { entity_id: string; name: string; km?: number | null }[];
  rows: PeerRow[]; default_measures: { indicator_id: string; better: "higher" | "lower" }[];
};

export const peersApi = {
  get: (entity: string, group?: string, measures?: string[], countries?: string[]) =>
    get<Peers>(`/peers/${entity}`, {
      group, measures: measures?.length ? measures.join(",") : undefined,
      countries: countries?.length ? countries.join(",") : undefined,
    }),
};

// Green for the best placed, through amber, to red for the worst (position 1 to 0).
export const placeColour = (position: number, alpha = 0.22) => `hsla(${Math.round(position * 120)}, 62%, 42%, ${alpha})`;
