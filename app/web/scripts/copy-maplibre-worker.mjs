// MapLibre 6 runs its tile parsing in a module worker shipped as a separate
// file. Bundlers don't pick that file up, so copy it next to the app's static
// files; WorldMap points MapLibre at it. Runs after every npm install.
import { copyFileSync, mkdirSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const pkg = createRequire(import.meta.url).resolve("maplibre-gl/package.json");
const out = join(here, "..", "public", "maplibre");
mkdirSync(out, { recursive: true });
copyFileSync(join(dirname(pkg), "dist", "maplibre-gl-worker.mjs"), join(out, "maplibre-gl-worker.mjs"));

// Flags (flag-icons, MIT): one small SVG per country, served from public/flags so
// they work without the internet and only the ones on screen are loaded.
import { readdirSync } from "node:fs";
const flags = join(dirname(createRequire(import.meta.url).resolve("flag-icons/package.json")), "flags", "4x3");
const flagsOut = join(here, "..", "public", "flags");
mkdirSync(flagsOut, { recursive: true });
for (const f of readdirSync(flags)) if (f.endsWith(".svg")) copyFileSync(join(flags, f), join(flagsOut, f));
