// Smoke test of the running app in a real browser: every page, and the map with every layer on
// (a few at a time), failing on any page error, React hydration warning or MapLibre style error.
// Catches what the type check and unit tests can't: a layer whose paint is not valid MapLibre,
// a layer style removed by mistake, a page that throws once its data arrives.
//
//   node scripts/smoke.mjs [http://localhost:3030]       (the API and web app must be running)
//
// Network failures of outside services (map tiles, live feeds) are not counted: only errors
// the app's own code makes.
import { readFileSync, readdirSync, statSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const { chromium } = require("playwright");

const BASE = (process.argv[2] || process.env.SMOKE_BASE || "http://localhost:3030").replace(/\/$/, "");
const WEB = join(dirname(fileURLToPath(import.meta.url)), "..");
const WAIT = +(process.env.SMOKE_WAIT_MS || 6000);

// Every map layer letter, from the list the app itself uses.
const workspace = readFileSync(join(WEB, "lib", "workspace.ts"), "utf8");
const letters = [...workspace.matchAll(/\{ letter: "([^"]+)", id: "([^"]+)"/g)].map((m) => ({ letter: m[1], id: m[2] }));
const GROUP = 8;
const mapUrls = [];
for (let i = 0; i < letters.length; i += GROUP) {
  const part = letters.slice(i, i + GROUP);
  mapUrls.push({ url: `/?l=1&p=map.none.........${encodeURIComponent(part.map((l) => l.letter).join(""))}`, what: `map layers ${part.map((l) => l.id).join(", ")}` });
}

// Every page without a [parameter] in its path, plus a country page.
const pages = readdirSync(join(WEB, "app")).filter((d) => !d.startsWith("[") && !d.startsWith("_") && d !== "api"
  && statSync(join(WEB, "app", d)).isDirectory() && readdirSync(join(WEB, "app", d)).some((f) => /^page\.(t|j)sx?$/.test(f)));
const pageUrls = [...pages.map((p) => ({ url: `/${p}`, what: `page /${p}` })), { url: "/entity/NZL", what: "page /entity/NZL" }];

const IGNORE = [
  /Failed to load resource/i, // outside services and 404s the page handles
  /net::ERR_/i,
  /Download the React DevTools/i,
  /\[HMR\]/,
];
const BAD = (text) => !IGNORE.some((re) => re.test(text));

const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 1280, height: 860 } });
const failures = [];
for (const { url, what } of [...mapUrls, ...pageUrls]) {
  const page = await ctx.newPage();
  const errs = [];
  page.on("pageerror", (e) => errs.push(`page error: ${e.message}`));
  page.on("console", (m) => { if (m.type() === "error" && BAD(m.text())) errs.push(m.text().split("\n")[0].slice(0, 300)); });
  try {
    const r = await page.goto(BASE + url, { waitUntil: "domcontentloaded", timeout: 60_000 });
    if (!r || r.status() >= 500) errs.push(`HTTP ${r ? r.status() : "no answer"}`);
    await page.waitForTimeout(WAIT);
  } catch (e) {
    errs.push(`could not open: ${e.message.split("\n")[0]}`);
  }
  console.log(`${errs.length ? "FAIL" : "ok  "} ${what}`);
  for (const e of errs) console.log(`       ${e}`);
  if (errs.length) failures.push(what);
  await page.close();
}
// The Self check page: map layer styles against MapLibre's rules, every API call, every page.
// Collectors and sources are left out here (a test machine has no live data or downloads).
{
  const page = await ctx.newPage();
  const errs = [];
  page.on("pageerror", (e) => errs.push(`page error: ${e.message}`));
  try {
    await page.goto(`${BASE}/selfcheck`, { waitUntil: "domcontentloaded", timeout: 60_000 });
    // In dev mode the page can show before React has hooked up the button, and a click then does
    // nothing (the run waited 15 minutes for a check that never started): click until it starts.
    for (let i = 0; ; i++) {
      await page.getByRole("button", { name: /Run the self check/ }).click();
      try {
        await page.getByRole("button", { name: /Checking/ }).or(page.locator("[data-selfcheck]")).first().waitFor({ timeout: 10_000 });
        break;
      } catch (e) {
        if (i >= 5) throw e;
      }
    }
    await page.locator("[data-selfcheck]").waitFor({ timeout: 15 * 60_000 });
    const bad = await page.$$eval("table tbody tr", (trs) => trs.map((tr) => [...tr.querySelectorAll("td")].map((td) => td.textContent ?? ""))
      .filter(([status, part]) => status === "Problem" && ["Map layers", "API", "Pages"].includes(part)));
    for (const [, part, what, detail] of bad) errs.push(`${part}: ${what}: ${detail}`);
  } catch (e) {
    errs.push(`self check did not finish: ${e.message.split("\n")[0]}`);
  }
  console.log(`${errs.length ? "FAIL" : "ok  "} self check (map layer styles, API, pages)`);
  for (const e of errs) console.log(`       ${e}`);
  if (errs.length) failures.push("self check");
  await page.close();
}
await browser.close();
console.log(failures.length ? `\n${failures.length} failed.` : "\nAll pages and map layers opened without errors.");
process.exit(failures.length ? 1 : 0);
