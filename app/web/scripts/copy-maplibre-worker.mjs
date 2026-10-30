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
