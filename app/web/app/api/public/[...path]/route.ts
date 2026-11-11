// The public API (/api/public/v1), passed on to the local API like every other /api call, but naming
// the PC the request came from (x-forwarded-for, which the plain rewrite in next.config.mjs leaves out),
// so the API can tell this PC (no key needed) from others on the network (key needed). The header is
// only a label: the app's own pages are open to the home network as before, so keys count and limit
// other PCs' scripts rather than lock the data away.
const API = process.env.WORLDMODEL_API_URL || "http://127.0.0.1:8000";
const PASS = ["authorization", "x-api-key", "content-type", "accept", "x-forwarded-for", "user-agent"];

async function pass(req: Request): Promise<Response> {
  const url = new URL(req.url);
  const headers = new Headers();
  for (const h of PASS) {
    const v = req.headers.get(h);
    if (v) headers.set(h, v);
  }
  try {
    const res = await fetch(`${API}${url.pathname}${url.search}`, {
      method: req.method, headers, body: req.method === "GET" || req.method === "HEAD" ? undefined : await req.text(), cache: "no-store",
    });
    const out = new Headers();
    for (const h of ["content-type", "content-disposition"]) {
      const v = res.headers.get(h);
      if (v) out.set(h, v);
    }
    return new Response(res.body, { status: res.status, headers: out });
  } catch {
    return Response.json({ detail: "The app's data service is not running: start it with start.bat." }, { status: 502 });
  }
}

export const dynamic = "force-dynamic";
export const GET = pass;
export const POST = pass;
