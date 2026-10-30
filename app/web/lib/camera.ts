// Keeps linked maps looking at the same place. A map publishes its camera when
// it moves; the others in its group jump there. Jumps made here are flagged so
// a follower's own move event is not sent back round the loop.

export type Camera = { center: [number, number]; zoom: number };
type Listener = { id: string; group: string; jump: (c: Camera) => void };

export class CameraBus {
  private listeners = new Set<Listener>();
  private applying = false;
  last = new Map<string, Camera>();

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
