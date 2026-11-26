"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useState } from "react";
import { get } from "@/lib/api";
import { PLANE_GROUPS, SHIP_GROUPS } from "@/lib/mapIcons";
import { journeyText, planeJourney, shipJourney, useShipStatus, type Journey } from "@/lib/ships";
import { mapLayersHref } from "@/lib/workspace";

// Ships and planes: every ship the collector has seen (saved details from aisstream.io) and the
// planes from the last OpenSky request, as tables; a row opens all its details, with where it
// came from and where it is going.
type Ship = {
  id: number; name: string | null; imo: number | null; callsign: string | null; flag: string | null; flag_code: string | null;
  kind: number | null; type: string | null; group: string; length_m: number | null; width_m: number | null; draught_m: number | null;
  destination: string | null; eta: string | null; status: string | null; speed_kn: number | null; heading: number | null;
  lat: number | null; lon: number | null; first_seen: number | null; last_seen: number | null; sanctioned?: boolean;
  links?: { label: string; href: string }[];
};
type Plane = {
  id: string; callsign: string | null; country: string | null; altitude_m: number | null; speed_kmh: number | null; heading: number | null;
  climb_ms: number | null; squawk: string | null; seen: number | null; category: number | null; category_name: string | null; group: string;
  lat: number; lon: number;
};

const when = (t?: number | null) => (t ? new Date(t * 1000).toLocaleString(undefined, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }) : "");
const n = (v?: number | null, d = 0) => (typeof v === "number" ? v.toLocaleString(undefined, { maximumFractionDigits: d }) : "");
const dot = (groups: { id: string; color: string }[], g: string) => (
  <i style={{ background: groups.find((x) => x.id === g)?.color ?? "#adb5bd", display: "inline-block", width: 9, height: 9, borderRadius: 5, marginRight: 6 }} />
);

function LivePage() {
  const sp = useSearchParams();
  const router = useRouter();
  const tab = sp.get("tab") === "planes" ? "planes" : "ships";
  const open = sp.get("id");
  const setParams = (p: Record<string, string | null>) => {
    const q = new URLSearchParams(sp.toString());
    for (const [k, v] of Object.entries(p)) { if (v === null) q.delete(k); else q.set(k, v); }
    router.replace(`/live?${q.toString()}`, { scroll: false });
  };
  return (
    <div className="grid">
      <div className="title-row"><h1>Ships and planes</h1></div>
      <div className="tabs" role="tablist">
        <button aria-pressed={tab === "ships"} onClick={() => setParams({ tab: "ships", id: null })}>Ships</button>
        <button aria-pressed={tab === "planes"} onClick={() => setParams({ tab: "planes", id: null })}>Planes</button>
      </div>
      {tab === "ships"
        ? <Ships open={open} setOpen={(id) => setParams({ id })} />
        : <Planes open={open} setOpen={(id) => setParams({ id })} />}
    </div>
  );
}

function Ships({ open, setOpen }: { open: string | null; setOpen: (id: string | null) => void }) {
  const [q, setQ] = useState("");
  const [group, setGroup] = useState("");
  const [hours, setHours] = useState(0);
  const [sort, setSort] = useState("last_seen");
  const [limit, setLimit] = useState(200);
  const [d, setD] = useState<{ rows: Ship[]; total: number; groups: Record<string, number>; collecting: boolean } | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const st = useShipStatus(true);
  useEffect(() => {
    let live = true;
    const qs = new URLSearchParams({ q, group, sort, limit: String(limit), hours: String(hours) });
    const t = setTimeout(() => get<typeof d>(`/live/ships/table?${qs}`).then((x) => live && setD(x)).catch((e) => live && setErr(String(e.message ?? e))), 250);
    return () => { live = false; clearTimeout(t); };
  }, [q, group, sort, limit, hours]);
  if (err) return <p className="error">{err}</p>;
  const head = (key: string, label: string) => (
    <th><button className="link small" onClick={() => setSort(sort === key ? `-${key}` : key)}>{label}{sort.replace("-", "") === key ? (sort.startsWith("-") ? " ▲" : " ▼") : ""}</button></th>
  );
  return (
    <section className="card">
      <p className="caption">
        {st?.collecting
          ? <>Every ship seen while collecting for {st.area}{st.world_every_hours ? ` (and the world every ${st.world_every_hours} hours)` : ""}, kept {st.keep_days} days.
            Names, types, sizes and destinations are what each ship&apos;s crew set in its AIS radio; the flag comes from its MMSI number.</>
          : <>Ships are not being saved, so this lists only those the map has seen in the last 20 minutes. Turn on Collect ships in <Link href="/settings#transport">Settings</Link>.</>}
      </p>
      <div className="table-tools small">
        <label>Find <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Name, MMSI, IMO, call sign, port, flag" style={{ width: 260 }} /></label>
        <label>Kind <select value={group} onChange={(e) => setGroup(e.target.value)}>
          <option value="">All ({n(d ? Object.values(d.groups).reduce((a, b) => a + b, 0) : 0)})</option>
          {SHIP_GROUPS.map((g) => <option key={g.id} value={g.id}>{g.label}{d?.groups[g.id] ? ` (${n(d.groups[g.id])})` : ""}</option>)}
        </select></label>
        <label>Seen <select value={hours} onChange={(e) => setHours(+e.target.value)}>
          <option value={0}>Any time</option><option value={1}>In the last hour</option><option value={24}>In the last day</option><option value={168}>In the last week</option>
        </select></label>
        <span className="muted">{d ? `${n(d.total)} ships` : "Loading…"}</span>
      </div>
      <div style={{ overflowX: "auto" }}>
        <table className="small">
          <thead><tr>{head("name", "Name")}{head("type", "Kind")}{head("flag", "Flag")}{head("length_m", "Length")}{head("speed_kn", "Speed")}
            {head("destination", "Going to")}<th>Doing</th>{head("last_seen", "Last seen")}</tr></thead>
          <tbody>
            {(d?.rows ?? []).map((r) => (
              <tr key={r.id} onClick={() => setOpen(String(r.id))} style={{ cursor: "pointer" }} className={open === String(r.id) ? "selected" : undefined}>
                <td>{dot(SHIP_GROUPS, r.group)}{r.name ?? <span className="muted">MMSI {r.id}</span>}{r.sanctioned ? <b style={{ color: "#c92a2a" }}> sanctioned</b> : null}</td>
                <td>{r.type ?? <span className="muted">not said</span>}</td>
                <td>{r.flag ?? ""}</td>
                <td>{r.length_m ? `${r.length_m} m` : ""}</td>
                <td>{typeof r.speed_kn === "number" ? `${r.speed_kn} kn` : ""}</td>
                <td>{r.destination ?? ""}</td>
                <td>{r.status ?? ""}</td>
                <td>{when(r.last_seen)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {d && d.total > limit && <button className="small" onClick={() => setLimit(limit + 500)}>Show more ({n(d.total - limit)} not shown)</button>}
      {open && <ShipCard id={open} onClose={() => setOpen(null)} />}
    </section>
  );
}

function ShipCard({ id, onClose }: { id: string; onClose: () => void }) {
  const [s, setS] = useState<Ship | null>(null);
  const [j, setJ] = useState<Journey | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    let live = true;
    get<Ship>(`/live/ships/detail/${encodeURIComponent(id)}`).then((x) => live && setS(x)).catch((e) => live && setErr(String(e.message ?? e)));
    shipJourney(id).then((x) => live && setJ(x)).catch(() => {});
    return () => { live = false; };
  }, [id]);
  const rows: [string, React.ReactNode][] = s ? [
    ["MMSI", s.id], ["IMO", s.imo ?? ""], ["Call sign", s.callsign ?? ""], ["Flag", s.flag ? `${s.flag} (${s.flag_code})` : ""],
    ["Kind", s.type ? `${s.type}${s.kind ? ` (AIS type ${s.kind})` : ""}` : "Not said yet"],
    ["Size", s.length_m ? `${s.length_m} m long, ${s.width_m ?? "?"} m wide` : ""], ["Draught", s.draught_m ? `${s.draught_m} m` : ""],
    ["Doing", s.status ?? ""], ["Speed", typeof s.speed_kn === "number" ? `${s.speed_kn} knots, heading ${n(s.heading)}°` : ""],
    ["Where", s.lat != null && s.lon != null ? `${s.lat.toFixed(3)}, ${s.lon.toFixed(3)}` : ""],
    ["Going to", [s.destination, s.eta ? `due ${s.eta}` : ""].filter(Boolean).join(", ")],
    ["First seen", when(s.first_seen)], ["Last seen", when(s.last_seen)],
  ] : [];
  return (
    <div className="find-big-back" onClick={onClose}>
      <div className="find-big card" role="dialog" aria-modal="true" aria-label={s?.name ?? `Ship ${id}`} style={{ maxWidth: 560 }} onClick={(e) => e.stopPropagation()}>
        <div className="row"><h2 style={{ margin: 0 }}>{s?.name ?? `Ship ${id}`}</h2><span className="spacer" /><button className="link" onClick={onClose} aria-label="Close">×</button></div>
        {err ? <p className="error">{err}</p> : !s ? <p className="muted">Loading…</p> : (
          <>
            {s.sanctioned && <p><b style={{ color: "#c92a2a" }}>On a sanctions list</b> (OpenSanctions); see <Link href="/sanctions">Sanctions now</Link>.</p>}
            <table className="small"><tbody>{rows.filter(([, v]) => v !== "" && v != null).map(([k, v]) => <tr key={k}><th style={{ textAlign: "left", paddingRight: 12 }}>{k}</th><td>{v}</td></tr>)}</tbody></table>
            <h3 className="small" style={{ marginBottom: 2 }}>Where from and to</h3>
            {j ? journeyText(j, false).map((l) => <p key={l} className="small" style={{ margin: "2px 0" }}>{l}</p>) : <p className="small muted">Loading…</p>}
            <p className="small"><Link href={mapLayersHref("S")}>Ships on the map</Link> (click the ship there to draw its path)
              {(s.links ?? []).map((l) => <span key={l.href}> · <a href={l.href} target="_blank" rel="noreferrer">{l.label}</a></span>)}</p>
          </>
        )}
      </div>
    </div>
  );
}

function Planes({ open, setOpen }: { open: string | null; setOpen: (id: string | null) => void }) {
  const [d, setD] = useState<{ planes: Plane[]; at: number | null; note: string } | null>(null);
  const [q, setQ] = useState("");
  const [group, setGroup] = useState("");
  const [sort, setSort] = useState<keyof Plane>("altitude_m");
  useEffect(() => {
    let live = true;
    const load = () => get<NonNullable<typeof d>>("/live/planes/table").then((x) => live && setD(x)).catch(() => {});
    load();
    const t = setInterval(load, 60_000);
    return () => { live = false; clearInterval(t); };
  }, []);
  const rows = useMemo(() => {
    const ql = q.trim().toLowerCase();
    return (d?.planes ?? []).filter((p) => (!group || p.group === group) && (!ql || [p.callsign, p.id, p.country].some((x) => String(x ?? "").toLowerCase().includes(ql))))
      .sort((a, b) => {
        const x = a[sort], y = b[sort];
        return typeof x === "number" || typeof y === "number" ? ((y as number) ?? -1e9) - ((x as number) ?? -1e9) : String(x ?? "").localeCompare(String(y ?? ""));
      });
  }, [d, q, group, sort]);
  const picked = rows.find((p) => p.id === open) ?? d?.planes.find((p) => p.id === open);
  const head = (key: keyof Plane, label: string) => <th><button className="link small" onClick={() => setSort(key)}>{label}{sort === key ? " ▼" : ""}</button></th>;
  return (
    <section className="card">
      <p className="caption">{d?.note ?? "Loading…"} {d?.at ? `Read ${when(d.at)}.` : ""} Turn on Planes now on <Link href={mapLayersHref("F")}>the map</Link> and move it to where you want planes listed.</p>
      <div className="table-tools small">
        <label>Find <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Callsign, hex code, country" /></label>
        <label>Type <select value={group} onChange={(e) => setGroup(e.target.value)}>
          <option value="">All</option>{PLANE_GROUPS.map((g) => <option key={g.id} value={g.id}>{g.label}</option>)}
        </select></label>
        <span className="muted">{n(rows.length)} planes</span>
      </div>
      <div style={{ overflowX: "auto" }}>
        <table className="small">
          <thead><tr>{head("callsign", "Callsign")}{head("category_name", "Type")}{head("country", "Registered in")}{head("altitude_m", "Height")}
            {head("speed_kmh", "Speed")}{head("climb_ms", "Climbing")}{head("squawk", "Squawk")}</tr></thead>
          <tbody>
            {rows.slice(0, 1000).map((p) => (
              <tr key={p.id} onClick={() => setOpen(p.id)} style={{ cursor: "pointer" }} className={open === p.id ? "selected" : undefined}>
                <td>{dot(PLANE_GROUPS, p.group)}{p.callsign ?? <span className="muted">{p.id}</span>}</td>
                <td>{p.category_name ?? <span className="muted">not sent</span>}</td>
                <td>{p.country ?? ""}</td>
                <td>{p.altitude_m != null ? `${n(p.altitude_m)} m` : ""}</td>
                <td>{p.speed_kmh != null ? `${n(p.speed_kmh)} km/h` : ""}</td>
                <td>{p.climb_ms != null ? `${p.climb_ms > 0 ? "+" : ""}${p.climb_ms} m/s` : ""}</td>
                <td>{p.squawk ?? ""}{["7500", "7600", "7700"].includes(String(p.squawk)) ? <b style={{ color: "#c92a2a" }}> emergency</b> : null}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {open && <PlaneCard id={open} plane={picked} onClose={() => setOpen(null)} />}
    </section>
  );
}

function PlaneCard({ id, plane, onClose }: { id: string; plane?: Plane; onClose: () => void }) {
  const [j, setJ] = useState<Journey | null>(null);
  useEffect(() => {
    let live = true;
    planeJourney(id, plane?.callsign, plane?.lon, plane?.lat).then((x) => live && setJ(x)).catch(() => {});
    return () => { live = false; };
  }, [id]); // eslint-disable-line react-hooks/exhaustive-deps
  const a = j?.aircraft;
  const rows: [string, React.ReactNode][] = [
    ["Hex code (ICAO 24-bit)", id], ["Callsign", plane?.callsign ?? ""], ["Registered in", plane?.country ?? ""],
    ["Registration", a?.registration ?? ""], ["Aircraft", [a?.description, a?.type].filter(Boolean).join(" ")], ["Operator", a?.operator ?? ""],
    ["Built", a?.year ?? ""], ["Type (ADS-B)", plane?.category_name ?? ""],
    ["Height", plane?.altitude_m != null ? `${n(plane.altitude_m)} m` : ""], ["Speed", plane?.speed_kmh != null ? `${n(plane.speed_kmh)} km/h, heading ${n(plane.heading)}°` : ""],
    ["Climbing", plane?.climb_ms != null ? `${plane.climb_ms} m/s` : ""], ["Squawk", plane?.squawk ?? a?.squawk ?? ""],
    ["Where", plane ? `${plane.lat.toFixed(3)}, ${plane.lon.toFixed(3)}` : ""], ["Last heard", when(plane?.seen)],
  ];
  return (
    <div className="find-big-back" onClick={onClose}>
      <div className="find-big card" role="dialog" aria-modal="true" aria-label={plane?.callsign ?? id} style={{ maxWidth: 560 }} onClick={(e) => e.stopPropagation()}>
        <div className="row"><h2 style={{ margin: 0 }}>{plane?.callsign ?? id}</h2><span className="spacer" /><button className="link" onClick={onClose} aria-label="Close">×</button></div>
        <table className="small"><tbody>{rows.filter(([, v]) => v !== "" && v != null).map(([k, v]) => <tr key={k}><th style={{ textAlign: "left", paddingRight: 12 }}>{k}</th><td>{v}</td></tr>)}</tbody></table>
        <h3 className="small" style={{ marginBottom: 2 }}>Where from and to</h3>
        {j ? journeyText(j, true).map((l) => <p key={l} className="small" style={{ margin: "2px 0" }}>{l}</p>) : <p className="small muted">Asking OpenSky and adsb.lol…</p>}
        <p className="small"><Link href={mapLayersHref("F")}>Planes on the map</Link> (click the plane there to draw its path)
          {" · "}<a href={`https://globe.adsb.lol/?icao=${id}`} target="_blank" rel="noreferrer">adsb.lol</a>
          {" · "}<a href={`https://opensky-network.org/aircraft-profile?icao24=${id}`} target="_blank" rel="noreferrer">OpenSky</a></p>
      </div>
    </div>
  );
}

export default function Page() {
  return <Suspense fallback={<p className="muted">Loading…</p>}><LivePage /></Suspense>;
}
