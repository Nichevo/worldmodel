// Planets and their moons, packed around each planet so the counts read at a glance.
//
// Until JPL's satellite table has downloaded (Settings > Maps > Solar system downloads), the page
// uses the built-in list below: the named moons with their mean radius in km. Big and mid-sized
// moons are from JPL's planetary satellite physical parameters; small outer moons (a few km
// across) are rounded estimates from their brightness, as JPL gives them. Known totals are as
// counted by the IAU Minor Planet Center in 2026; moons without a name yet are drawn as plain dots.

export type Host = { id: string; name: string; kind: "planet" | "dwarf planet"; radius: number; colour: string; total: number; angle: number };

// angle: where the planet sits around the Sun on the page (degrees, 0 = right, counter-clockwise).
export const HOSTS: Host[] = [
  { id: "mercury", name: "Mercury", kind: "planet", radius: 2440, colour: "#9c9a96", total: 0, angle: 345 },
  { id: "venus", name: "Venus", kind: "planet", radius: 6052, colour: "#d9b26f", total: 0, angle: 110 },
  { id: "earth", name: "Earth", kind: "planet", radius: 6371, colour: "#3f7fd0", total: 1, angle: 200 },
  { id: "mars", name: "Mars", kind: "planet", radius: 3390, colour: "#c4553b", total: 2, angle: 35 },
  { id: "ceres", name: "Ceres", kind: "dwarf planet", radius: 470, colour: "#8d8a84", total: 0, angle: 160 },
  { id: "jupiter", name: "Jupiter", kind: "planet", radius: 69911, colour: "#c99a6c", total: 97, angle: 305 },
  { id: "saturn", name: "Saturn", kind: "planet", radius: 58232, colour: "#d8c27e", total: 274, angle: 55 },
  { id: "uranus", name: "Uranus", kind: "planet", radius: 25362, colour: "#8fd0d8", total: 29, angle: 145 },
  { id: "neptune", name: "Neptune", kind: "planet", radius: 24622, colour: "#4f6fd6", total: 16, angle: 225 },
  { id: "pluto", name: "Pluto", kind: "dwarf planet", radius: 1188, colour: "#b8a48f", total: 5, angle: 5 },
  { id: "haumea", name: "Haumea", kind: "dwarf planet", radius: 780, colour: "#c9c4bc", total: 2, angle: 180 },
  { id: "makemake", name: "Makemake", kind: "dwarf planet", radius: 715, colour: "#b77a63", total: 1, angle: 335 },
  { id: "eris", name: "Eris", kind: "dwarf planet", radius: 1163, colour: "#d6d3cf", total: 1, angle: 270 },
  { id: "orcus", name: "Orcus", kind: "dwarf planet", radius: 455, colour: "#9b9fa6", total: 1, angle: 200 },
  { id: "quaoar", name: "Quaoar", kind: "dwarf planet", radius: 545, colour: "#a5826b", total: 1, angle: 320 },
  { id: "gonggong", name: "Gonggong", kind: "dwarf planet", radius: 615, colour: "#a0574a", total: 1, angle: 95 },
];

const L = (s: string): [string, number][] => s.split(";").map((p) => { const [n, r] = p.split(":"); return [n.trim(), Number(r)]; });

// Named moons, mean radius in km.
export const BUILT_IN: Record<string, [string, number][]> = {
  earth: L("Moon:1737.4"),
  mars: L("Phobos:11.1;Deimos:6.2"),
  jupiter: L(
    "Ganymede:2634.1;Callisto:2410.3;Io:1821.6;Europa:1560.8;Amalthea:83.5;Himalia:69.8;Thebe:49.3;Elara:43;Pasiphae:30;" +
    "Carme:23;Metis:21.5;Sinope:19;Lysithea:18;Ananke:14;Leda:10;Adrastea:8.2;Callirrhoe:4.3;Themisto:4;Praxidike:3.4;" +
    "Megaclite:2.7;Kalyke:2.6;Iocaste:2.6;Taygete:2.5;Harpalyke:2.2;Autonoe:2;Thyone:2;Hermippe:2;Aoede:2;Helike:2;" +
    "Eukelade:2;Dia:2;Eirene:2;Chaldene:1.9;Isonoe:1.9;Erinome:1.6;Aitne:1.5;Eurydome:1.5;Euanthe:1.5;Hegemone:1.5;" +
    "Arche:1.5;Carpo:1.5;Ersa:1.5;Pandia:1.5;Euporie:1;Orthosie:1;Sponde:1;Kale:1;Pasithee:1;Mneme:1;Thelxinoe:1;" +
    "Kallichore:1;Cyllene:1;Kore:1;Herse:1;Eupheme:1;Philophrosyne:1;Valetudo:0.5"),
  saturn: L(
    "Titan:2574.7;Rhea:763.8;Iapetus:734.5;Dione:561.4;Tethys:531.1;Enceladus:252.1;Mimas:198.2;Hyperion:135;Phoebe:106.5;" +
    "Janus:89.5;Epimetheus:58.1;Prometheus:43;Pandora:40;Siarnaq:20;Helene:18;Albiorix:16;Atlas:15;Pan:14;Telesto:12;" +
    "Paaliaq:11;Calypso:10.7;Ymir:9;Kiviuq:8;Tarvos:7.5;Ijiraq:6;Erriapus:5;Skathi:4;Hyrrokkin:4;Daphnis:3.8;" +
    "Mundilfari:3.5;Suttungr:3.5;Thrymr:3.5;Narvi:3.5;Bestla:3.5;Tarqeq:3.5;Kari:3.5;Skoll:3;Bergelmir:3;Bebhionn:3;" +
    "Hati:3;Greip:3;Jarnsaxa:3;Aegir:3;Loge:3;Surtur:3;Fornjot:3;Eggther:3;Alvaldi:3;Farbauti:2.5;Pallene:2.5;Fenrir:2;" +
    "Gridr:2;Angrboda:2;Skrymir:2;Gerd:2;Gunnlod:2;Thiazzi:2;Geirrod:2;Methone:1.6;Polydeuces:1.3;Beli:1;Anthe:0.9;Aegaeon:0.3"),
  uranus: L(
    "Titania:788.9;Oberon:761.4;Umbriel:584.7;Ariel:578.9;Miranda:235.8;Puck:81;Sycorax:75;Portia:67.6;Juliet:46.8;" +
    "Belinda:40.3;Cressida:39.6;Caliban:36;Rosalind:36;Desdemona:32;Bianca:25.7;Prospero:25;Setebos:24;Ophelia:21.4;" +
    "Cordelia:20.1;Stephano:16;Perdita:15;Mab:12;Francisco:11;Margaret:10;Ferdinand:10;Cupid:9;Trinculo:9"),
  neptune: L("Triton:1353.4;Proteus:210;Nereid:170;Larissa:97;Galatea:88;Despina:75;Thalassa:41;Naiad:33;Halimede:31;Neso:30;Sao:22;Laomedeia:21;Psamathe:20;Hippocamp:17"),
  pluto: L("Charon:606;Nix:19;Hydra:19;Kerberos:6;Styx:5"),
  haumea: L("Hi'iaka:160;Namaka:85"),
  makemake: L("S/2015 (136472) 1:88"),
  eris: L("Dysnomia:350"),
  orcus: L("Vanth:221"),
  quaoar: L("Weywot:100"),
  gonggong: L("Xiangliu:50"),
};

export type Moon = { name: string; host: string; radius: number | null; named: boolean };

const provisional = (n: string) => /^(S\/|\(|\d)/.test(n) || /^[A-Z][a-z]+ [LXVI]+$/.test(n);

// The moons to draw: JPL's table when it has downloaded ([host, name, radius]), else the built-in
// list plus a plain dot for each known moon not named yet.
export function moonList(jpl: [string, string, number | null][] | null): { moons: Moon[]; from: "jpl" | "built-in" } {
  if (jpl?.length) {
    const known = new Map(Object.values(BUILT_IN).flat());
    return {
      from: "jpl",
      moons: jpl.filter(([h]) => HOSTS.some((x) => x.name === h)).map(([h, n, r]) => {
        const host = HOSTS.find((x) => x.name === h)!.id;
        const name = n.replace(/^[IVXL]+\s+/, ""); // "XIII Leda" -> "Leda"
        return { name, host, radius: r ?? known.get(name) ?? null, named: !provisional(name) };
      }),
    };
  }
  const moons: Moon[] = [];
  for (const h of HOSTS) {
    const list = BUILT_IN[h.id] ?? [];
    list.forEach(([name, radius]) => moons.push({ name, host: h.id, radius, named: !provisional(name) }));
    for (let i = list.length; i < h.total; i++) moons.push({ name: `Not named yet (${i - list.length + 1})`, host: h.id, radius: null, named: false });
  }
  return { moons, from: "built-in" };
}

// ----------------------------------------------------------------------------- packing
export type Circle = { x: number; y: number; r: number };

// Pack circles around a centre one: each new circle goes where it touches two already placed
// ones (or the centre), as close to the centre as it can without overlapping anything.
export function packAround(centreR: number, radii: number[], gap = 1.2): Circle[] {
  const placed: Circle[] = [{ x: 0, y: 0, r: centreR }];
  const free = (c: Circle) => placed.every((p) => Math.hypot(p.x - c.x, p.y - c.y) >= p.r + c.r + gap - 1e-6);
  for (const r of radii) {
    let best: Circle | null = null, bestD = Infinity;
    const consider = (c: Circle) => {
      const d = Math.hypot(c.x, c.y);
      if (d < bestD && free(c)) { best = c; bestD = d; }
    };
    if (placed.length === 1) consider({ x: centreR + r + gap, y: 0, r });
    else if (placed.length === 2) {
      const a = placed[0], b = placed[1];
      tangent(a, b, r, gap).forEach(consider);
    } else {
      // Only circles near the outside can touch a new one: skip pairs too far apart to share it.
      for (let i = 0; i < placed.length; i++) for (let j = i + 1; j < placed.length; j++) {
        const a = placed[i], b = placed[j];
        if (Math.hypot(a.x - b.x, a.y - b.y) > a.r + b.r + 2 * (r + gap)) continue;
        tangent(a, b, r, gap).forEach(consider);
      }
    }
    if (!best) { // nowhere snug: go outside everything
      const out = Math.max(...placed.map((p) => Math.hypot(p.x, p.y) + p.r));
      best = { x: out + r + gap, y: 0, r };
    }
    placed.push(best);
  }
  return placed.slice(1);
}

// The two spots where a circle of radius r touches both a and b.
function tangent(a: Circle, b: Circle, r: number, gap: number): Circle[] {
  const ra = a.r + r + gap, rb = b.r + r + gap;
  const dx = b.x - a.x, dy = b.y - a.y, d = Math.hypot(dx, dy);
  if (d > ra + rb || d < Math.abs(ra - rb) || d === 0) return [];
  const k = (ra * ra - rb * rb + d * d) / (2 * d), h = Math.sqrt(Math.max(0, ra * ra - k * k));
  const mx = a.x + (dx * k) / d, my = a.y + (dy * k) / d;
  return [{ x: mx - (dy * h) / d, y: my + (dx * h) / d, r }, { x: mx + (dy * h) / d, y: my - (dx * h) / d, r }];
}

// Sizes on the page. "readable": every moon big enough to see and label, bigger moons still
// bigger; "true": everything to one scale (Jupiter 110 px), so most moons are specks.
export function sizeOf(km: number | null, kind: "host" | "moon", scale: "readable" | "true"): number {
  if (scale === "true") return Math.max(kind === "host" ? 2 : 0.7, ((km ?? 1) / 69911) * 110);
  if (kind === "host") return 16 + 42 * Math.sqrt(km! / 69911);
  return km == null ? 3.2 : 5 + 4.6 * Math.log10(1 + km);
}

export type Cluster = { host: Host; x: number; y: number; r: number; enclose: number; moons: (Circle & { moon: Moon })[] };

// Every planet with its moons packed round it, set around the Sun on rings, pushed apart where they overlap.
export function layout(moons: Moon[], scale: "readable" | "true", unnamed: boolean): { clusters: Cluster[]; sun: number; rings: number[] } {
  const sun = scale === "true" ? 40 : 34;
  const clusters: Cluster[] = HOSTS.map((host) => {
    const mine = moons.filter((m) => m.host === host.id && (unnamed || m.named))
      .sort((a, b) => (b.radius ?? 0) - (a.radius ?? 0) || Number(b.named) - Number(a.named));
    const r = sizeOf(host.radius, "host", scale);
    const circles = packAround(r, mine.map((m) => sizeOf(m.radius, "moon", scale)), scale === "true" ? 2 : 1.2);
    const enclose = Math.max(r, ...circles.map((c) => Math.hypot(c.x, c.y) + c.r));
    return { host, x: 0, y: 0, r, enclose, moons: circles.map((c, i) => ({ ...c, moon: mine[i] })) };
  });
  // Out from the Sun in order, each ring a little beyond the last.
  let dist = sun + 18;
  clusters.forEach((c, i) => {
    dist += i === 0 ? c.enclose : Math.max(10, c.enclose * 0.25);
    const a = (c.host.angle * Math.PI) / 180;
    c.x = Math.cos(a) * dist; c.y = -Math.sin(a) * dist;
  });
  // Push apart overlaps (and away from the Sun), keeping each cluster on its side of the Sun.
  for (let it = 0; it < 300; it++) {
    let moved = false;
    for (let i = 0; i < clusters.length; i++) {
      const a = clusters[i];
      const ds = Math.hypot(a.x, a.y), needS = sun + a.enclose + 10;
      if (ds < needS) { a.x *= needS / ds; a.y *= needS / ds; moved = true; }
      for (let j = i + 1; j < clusters.length; j++) {
        const b = clusters[j];
        const dx = b.x - a.x, dy = b.y - a.y, d = Math.hypot(dx, dy) || 1, need = a.enclose + b.enclose + 10;
        if (d < need) {
          const push = (need - d) / 2, wa = b.enclose / (a.enclose + b.enclose), wb = 1 - wa;
          a.x -= (dx / d) * push * 2 * wa; a.y -= (dy / d) * push * 2 * wa;
          b.x += (dx / d) * push * 2 * wb; b.y += (dy / d) * push * 2 * wb;
          moved = true;
        }
      }
    }
    if (!moved) break;
  }
  return { clusters, sun, rings: clusters.map((c) => Math.hypot(c.x, c.y)) };
}
