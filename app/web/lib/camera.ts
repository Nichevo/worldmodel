// Keeps linked maps looking at the same place. A map publishes its camera when
// it moves; the others in its group jump there. Jumps made here are flagged so
// a follower's own move event is not sent back round the loop.

export type Camera = { center: [number, number]; zoom: number };
type Listener = { id: string; group: string; jump: (c: Camera) => void };

export class CameraBus {
  private listeners = new Set<Listener>();
  private applying = false;
  last = new Map<string, Camera>();
  // Where each map (by panel id) looked last, linked or not; seeded from what the browser kept.
  own: Map<string, Camera>;
  private onKeep?: (own: Map<string, Camera>) => void;

  constructor(own?: Map<string, Camera>, onKeep?: (own: Map<string, Camera>) => void) {
    this.own = own ?? new Map();
    this.onKeep = onKeep;
  }

  /** Notes where one map is looking now (after it moved). */
  keep(id: string, cam: Camera) {
    this.own.set(id, cam);
    this.onKeep?.(this.own);
  }

  subscribe(id: string, group: string, jump: (c: Camera) => void): () => void {
    const l = { id, group, jump };
    this.listeners.add(l);
    return () => { this.listeners.delete(l); };
  }

  publish(id: string, group: string, cam: Camera) {
    if (this.applying) return;
    this.last.set(group, cam);
    this.applying = true;
    try {
      for (const l of this.listeners) if (l.group === group && l.id !== id) l.jump(cam);
    } finally {
      this.applying = false;
    }
  }
}
