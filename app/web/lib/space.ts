// The solar system worked out on this PC: planet positions from JPL's approximate orbital
// elements (Standish, "Keplerian Elements for Approximate Positions of the Major Planets",
// table 1, good for 1800-2050), asteroid positions from their own orbits (JPL Small-Body
// Database), and fact cards from NASA's planetary fact sheets.

const RAD = Math.PI / 180;
export const J2000 = 2451545.0;
export const jd = (d: Date) => d.getTime() / 86_400_000 + 2440587.5;
export const dateOf = (j: number) => new Date((j - 2440587.5) * 86_400_000);

// a (AU), e, I, L, long. perihelion, long. node (deg); then their rates per century.
type El = [number, number, number, number, number, number];
export const PLANETS: { id: string; name: string; colour: string; el: El; rate: El }[] = [
  { id: "mercury", name: "Mercury", colour: "#9c9a96", el: [0.38709927, 0.20563593, 7.00497902, 252.2503235, 77.45779628, 48.33076593], rate: [0.00000037, 0.00001906, -0.00594749, 149472.67411175, 0.16047689, -0.12534081] },
  { id: "venus", name: "Venus", colour: "#d9b26f", el: [0.72333566, 0.00677672, 3.39467605, 181.9790995, 131.60246718, 76.67984255], rate: [0.0000039, -0.00004107, -0.0007889, 58517.81538729, 0.00268329, -0.27769418] },
  { id: "earth", name: "Earth", colour: "#3f7fd0", el: [1.00000261, 0.01671123, -0.00001531, 100.46457166, 102.93768193, 0], rate: [0.00000562, -0.00004392, -0.01294668, 35999.37244981, 0.32327364, 0] },
  { id: "mars", name: "Mars", colour: "#c4553b", el: [1.52371034, 0.0933941, 1.84969142, -4.55343205, -23.94362959, 49.55953891], rate: [0.00001847, 0.00007882, -0.00813131, 19140.30268499, 0.44441088, -0.29257343] },
  { id: "jupiter", name: "Jupiter", colour: "#c99a6c", el: [5.202887, 0.04838624, 1.30439695, 34.39644051, 14.72847983, 100.47390909], rate: [-0.00011607, -0.00013253, -0.00183714, 3034.74612775, 0.21252668, 0.20469106] },
  { id: "saturn", name: "Saturn", colour: "#d8c27e", el: [9.53667594, 0.05386179, 2.48599187, 49.95424423, 92.59887831, 113.66242448], rate: [-0.0012506, -0.00050991, 0.00193609, 1222.49362201, -0.41897216, -0.28867794] },
  { id: "uranus", name: "Uranus", colour: "#8fd0d8", el: [19.18916464, 0.04725744, 0.77263783, 313.23810451, 170.9542763, 74.01692503], rate: [-0.00196176, -0.00004397, -0.00242939, 428.48202785, 0.40805281, 0.04240589] },
  { id: "neptune", name: "Neptune", colour: "#4f6fd6", el: [30.06992276, 0.00859048, 1.77004347, -55.12002969, 44.96476227, 131.78422574], rate: [0.00026291, 0.00005105, 0.00035372, 218.45945325, -0.32241464, -0.00508664] },
  { id: "pluto", name: "Pluto", colour: "#b8a48f", el: [39.48211675, 0.2488273, 17.14001206, 238.92903833, 224.06891629, 110.30393684], rate: [-0.00031596, 0.0000517, 0.00004818, 145.20780515, -0.04062942, -0.01183482] },
];

function kepler(M: number, e: number): number {
  let E = M + e * Math.sin(M);
  for (let k = 0; k < 8; k++) E -= (E - e * Math.sin(E) - M) / (1 - e * Math.cos(E));
  return E;
}

// Position (AU, ecliptic, Sun at 0) from a, e, I, node, argument of perihelion and mean anomaly (degrees).
export function position(a: number, e: number, I: number, node: number, peri: number, M: number): [number, number, number] {
  const E = kepler((((M % 360) + 540) % 360 - 180) * RAD, e);
  const xp = a * (Math.cos(E) - e), yp = a * Math.sqrt(1 - e * e) * Math.sin(E);
  const cw = Math.cos(peri * RAD), sw = Math.sin(peri * RAD), cO = Math.cos(node * RAD), sO = Math.sin(node * RAD), ci = Math.cos(I * RAD), si = Math.sin(I * RAD);
  return [
    (cw * cO - sw * sO * ci) * xp + (-sw * cO - cw * sO * ci) * yp,
    (cw * sO + sw * cO * ci) * xp + (-sw * sO + cw * cO * ci) * yp,
    sw * si * xp + cw * si * yp,
  ];
}

export function planetElements(p: (typeof PLANETS)[number], j: number) {
  const T = (j - J2000) / 36525;
  const [a, e, I, L, wbar, node] = p.el.map((v, i) => v + p.rate[i] * T);
  return { a, e, I, node, peri: wbar - node, M: L - wbar };
}

export function planetAt(p: (typeof PLANETS)[number], j: number): [number, number, number] {
  const k = planetElements(p, j);
  return position(k.a, k.e, k.I, k.node, k.peri, k.M);
}

// The whole orbit as points (for drawing the ellipse).
export function orbit(a: number, e: number, I: number, node: number, peri: number, n = 160): [number, number, number][] {
  return Array.from({ length: n + 1 }, (_, i) => position(a, e, I, node, peri, (i / n) * 360));
}

// An asteroid row from the server: [name, a, e, i, om, w, ma, epoch, type, measured, neo, class, diameter, group].
export type AsteroidRow = [string, number, number, number, number, number, number, number, string | null, boolean, boolean, string, number | null, string];
export function asteroidAt(r: AsteroidRow, j: number): [number, number, number] {
  const n = 0.9856076686 / Math.pow(r[1], 1.5); // degrees a day
  return position(r[1], r[2], r[3], r[4], r[5], r[6] + n * (j - r[7]));
}

export const TYPE_INFO: Record<string, { label: string; colour: string; holds: string }> = {
  C: { label: "C: carbon-rich", colour: "#5f6b7a", holds: "dark, carbon-rich, often with water bound in clay; about three quarters of known asteroids" },
  S: { label: "S: stony", colour: "#c79b62", holds: "silicate rock with some iron and nickel; common in the inner belt" },
  X: { label: "M/X: metal-rich", colour: "#b9c2cc", holds: "many are iron-nickel metal, perhaps the cores of broken worlds (Psyche); platinum-group metals" },
  V: { label: "V: basalt (Vesta)", colour: "#c44e6a", holds: "basalt lava rock, pieces of Vesta's crust" },
};

// Fact cards (NASA planetary fact sheets; moons from JPL's planetary satellite tables).
export type Fact = { id: string; name: string; kind: "star" | "planet" | "dwarf planet" | "moon" | "spacecraft"; of?: string; facts: [string, string][]; note: string };
export const FACTS: Fact[] = [
  { id: "sun", name: "Sun", kind: "star", facts: [["Diameter", "1,392,700 km (109 Earths)"], ["Mass", "333,000 Earths (99.86% of the solar system)"], ["Surface", "5,500 °C"], ["Age", "4.6 billion years"]], note: "A middle-aged yellow dwarf star; light takes 8 minutes 20 seconds to reach Earth." },
  { id: "mercury", name: "Mercury", kind: "planet", facts: [["Diameter", "4,879 km"], ["Gravity", "0.38 g"], ["Day (sunrise to sunrise)", "176 Earth days"], ["Year", "88 days"], ["Temperature", "-180 to 430 °C"], ["Moons", "0"]], note: "Ice sits in craters at its poles that never see the Sun (MESSENGER, 2012)." },
  { id: "venus", name: "Venus", kind: "planet", facts: [["Diameter", "12,104 km"], ["Gravity", "0.90 g"], ["Day", "117 Earth days (turns backwards)"], ["Year", "225 days"], ["Surface", "465 °C, 92 times Earth's air pressure"], ["Moons", "0"]], note: "The hottest planet: a runaway greenhouse under thick carbon dioxide." },
  { id: "earth", name: "Earth", kind: "planet", facts: [["Diameter", "12,756 km"], ["Gravity", "1 g"], ["Day", "24 hours"], ["Year", "365.25 days"], ["Average temperature", "15 °C"], ["Moons", "1"]], note: "The only place known to have life; 71% of the surface is ocean." },
  { id: "moon", name: "Moon", kind: "moon", of: "Earth", facts: [["Diameter", "3,475 km"], ["Gravity", "0.17 g"], ["Distance", "384,400 km"], ["Month", "29.5 days"]], note: "Water ice in permanently shadowed polar craters (Lunar Prospector 1998, LCROSS 2009, Chandrayaan-1); helium-3 in the soil. The south pole is where Artemis, China and India are aiming." },
  { id: "mars", name: "Mars", kind: "planet", facts: [["Diameter", "6,792 km"], ["Gravity", "0.38 g"], ["Day", "24 h 40 min"], ["Year", "687 days"], ["Average temperature", "-65 °C"], ["Moons", "2 (Phobos, Deimos)"]], note: "Ice caps and buried ice; clays, sulfates and carbonates mapped from orbit (MRO's CRISM) show it was once wet." },
  { id: "ceres", name: "Ceres", kind: "dwarf planet", facts: [["Diameter", "939 km"], ["Distance from the Sun", "2.8 AU"], ["Year", "4.6 years"]], note: "The largest body in the asteroid belt, a third of its mass; salty water once reached its surface (Dawn)." },
  { id: "jupiter", name: "Jupiter", kind: "planet", facts: [["Diameter", "142,984 km (11 Earths)"], ["Mass", "318 Earths"], ["Day", "9 h 56 min"], ["Year", "11.9 years"], ["Moons", "95 known"]], note: "Its gravity shapes the asteroid belt and holds the Trojan asteroids in its orbit, 60° ahead and behind." },
  { id: "io", name: "Io", kind: "moon", of: "Jupiter", facts: [["Diameter", "3,643 km"], ["Orbit", "1.8 days"]], note: "The most volcanic place in the solar system." },
  { id: "europa", name: "Europa", kind: "moon", of: "Jupiter", facts: [["Diameter", "3,122 km"], ["Orbit", "3.6 days"]], note: "A salty ocean under 15-25 km of ice, with perhaps twice Earth's water: a prime place to look for life (Europa Clipper)." },
  { id: "ganymede", name: "Ganymede", kind: "moon", of: "Jupiter", facts: [["Diameter", "5,268 km (bigger than Mercury)"], ["Orbit", "7.2 days"]], note: "The largest moon, with its own magnetic field and a buried ocean (JUICE will orbit it)." },
  { id: "callisto", name: "Callisto", kind: "moon", of: "Jupiter", facts: [["Diameter", "4,821 km"], ["Orbit", "16.7 days"]], note: "The most cratered surface known; possibly an ocean deep down." },
  { id: "saturn", name: "Saturn", kind: "planet", facts: [["Diameter", "120,536 km"], ["Mass", "95 Earths"], ["Day", "10 h 34 min"], ["Year", "29.4 years"], ["Moons", "274 known"]], note: "Lighter than water on average; its rings are mostly water ice, 280,000 km across but tens of metres thick." },
  { id: "titan", name: "Titan", kind: "moon", of: "Saturn", facts: [["Diameter", "5,150 km"], ["Orbit", "16 days"], ["Air pressure", "1.5 times Earth's"]], note: "Lakes and rain of liquid methane under a thick haze; Dragonfly is due to fly there in 2034." },
  { id: "enceladus", name: "Enceladus", kind: "moon", of: "Saturn", facts: [["Diameter", "504 km"], ["Orbit", "1.4 days"]], note: "Jets of salty water from a buried ocean, with the chemistry life could use (Cassini)." },
  { id: "uranus", name: "Uranus", kind: "planet", facts: [["Diameter", "51,118 km"], ["Day", "17 h 14 min"], ["Year", "84 years"], ["Tilt", "98° (rolls on its side)"], ["Moons", "28"]], note: "An ice giant visited once, by Voyager 2 in 1986." },
  { id: "neptune", name: "Neptune", kind: "planet", facts: [["Diameter", "49,528 km"], ["Day", "16 h 6 min"], ["Year", "165 years"], ["Winds", "up to 2,100 km/h"], ["Moons", "16"]], note: "Found by maths in 1846 before anyone saw it; Triton, its big moon, orbits backwards." },
  { id: "pluto", name: "Pluto", kind: "dwarf planet", facts: [["Diameter", "2,377 km"], ["Year", "248 years"], ["Distance", "30-49 AU"]], note: "A heart-shaped plain of nitrogen ice (New Horizons, 2015); a planet until 2006." },
];
