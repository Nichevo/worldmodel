"use client";

// One public camera from the map's Cameras layer: its latest picture (asked for again every
// minute while the card is open), a short clip or live video where the owner offers one, and
// for Windy webcams their own live or timelapse player. Pictures load straight from the owner.

import { useEffect, useRef, useState } from "react";
import { get } from "@/lib/api";
import { CAMERA_KIND, CAMERA_SOURCE } from "@/lib/layers";
import { toggleWall, useCameraWall, WALL_MAX } from "@/lib/cameraWall";

export type CameraProps = {
  id: string; name?: string; kind?: string; source?: string; about?: string; direction?: string; offline?: boolean;
  image?: string; images?: string[]; video?: string; stream?: string; player?: string; page?: string; categories?: string[];
  lng?: number; lat?: number;
};

const SOURCE: Record<string, { name: string; page?: string }> = Object.fromEntries(CAMERA_SOURCE.map((x) => [x.id, x]));
const REFRESH = 60_000;

// wallButton: an Add to wall button (the map's card). compact: a tile on the camera wall (no
// description line, smaller credit).
export default function CameraView({ cam, wallButton = false, compact = false }: { cam: CameraProps; wallButton?: boolean; compact?: boolean }) {
  const wall = useCameraWall();
  const onWall = wall.some((c) => c.id === cam.id);
  const windy = cam.source === "windy";
  const [fresh, setFresh] = useState<{ image?: string; player?: string; page?: string; error?: string; updated?: string } | null>(null);
  const [view, setView] = useState(0); // which of a station's pictures (Finland has several per station)
  const [mode, setMode] = useState<"picture" | "clip" | "live">("picture");
  const [tick, setTick] = useState(0);
  const [broken, setBroken] = useState(false);
  const [at, setAt] = useState(() => new Date());

  // Windy's picture links last ten minutes, so ask for a fresh one each time the card opens.
  // On the camera wall a tile stays open, so ask again every nine minutes.
  useEffect(() => {
    if (!windy) return;
    const n = String(cam.id).split(":")[1];
    const ask = () => get<{ image?: string; player?: string; page?: string; error?: string; updated?: string }>(`/live/cameras/windy/${encodeURIComponent(n)}`)
      .then(setFresh).catch(() => setFresh({ error: "Windy did not answer." }));
    ask();
    const t = setInterval(() => { if (!document.hidden) ask(); }, 9 * 60_000);
    return () => clearInterval(t);
  }, [cam.id, windy]);

  // Agency pictures: ask again every minute (a new query string gets past the browser's copy).
  useEffect(() => {
    if (windy || mode !== "picture") return;
    const t = setInterval(() => { if (!document.hidden) { setTick((n) => n + 1); setAt(new Date()); } }, REFRESH);
    return () => clearInterval(t);
  }, [windy, mode]);
  useEffect(() => setBroken(false), [tick, view]);

  const pictures = Array.isArray(cam.images) && cam.images.length ? cam.images : cam.image ? [cam.image] : [];
  const base = windy ? (fresh?.image ?? null) : pictures[view] ?? null;
  const src = base && !windy && tick ? `${base}${base.includes("?") ? "&" : "?"}t=${tick}` : base;
  const player = fresh?.player ?? cam.player;
  const src0 = SOURCE[cam.source ?? ""];
  const kind = CAMERA_KIND[cam.kind ?? ""]?.label;

  return (
    <div className={`camera-view${compact ? " compact" : ""}`}>
      {!compact && <p className="small muted" style={{ margin: "0 0 4px" }}>
        {[kind, cam.direction, cam.about, Array.isArray(cam.categories) ? cam.categories.join(", ") : null].filter(Boolean).join(" · ")}
        {cam.offline ? " · the owner marks it offline" : ""}
      </p>}
      {wallButton && (
        <p className="small" style={{ margin: "0 0 4px" }}>
          <button className="small" onClick={() => toggleWall(cam)}
            title={onWall ? "Take this camera off the camera wall" : `Watch this camera beside others on the camera wall (up to ${WALL_MAX}; ctrl-click a camera on the map does the same)`}>
            {onWall ? "On the wall ✓ (take off)" : "Add to wall"}</button>
          {wall.length > 0 && <span className="muted"> {wall.length} on the wall</span>}
        </p>
      )}
      {(cam.video || cam.stream || (windy && player)) && (
        <div className="small" style={{ display: "flex", flexWrap: "wrap", gap: 12, marginBottom: 4 }}>
          <button className={`link small${mode === "picture" ? " on" : ""}`} onClick={() => setMode("picture")}>Latest picture</button>
          {cam.video && <button className={`link small${mode === "clip" ? " on" : ""}`} onClick={() => setMode("clip")}>Short clip</button>}
          {(cam.stream || (windy && player)) && (
            <button className={`link small${mode === "live" ? " on" : ""}`} onClick={() => setMode("live")}>{windy ? "Live and timelapse player" : "Live video"}</button>
          )}
        </div>
      )}
      {mode === "clip" && cam.video ? (
        <video className="camera-media" src={cam.video} poster={cam.image} controls autoPlay muted loop playsInline />
      ) : mode === "live" && cam.stream ? (
        <LiveStream url={cam.stream} poster={cam.image} />
      ) : mode === "live" && windy && player ? (
        <iframe className="camera-media" src={player} title={cam.name ?? "Webcam"} allow="autoplay; fullscreen" allowFullScreen
          referrerPolicy="no-referrer-when-downgrade" style={{ border: 0, aspectRatio: "16 / 9" }} />
      ) : windy && !fresh ? (
        <p className="small muted">Asking Windy for the latest picture…</p>
      ) : fresh?.error ? (
        <p className="small">{fresh.error}</p>
      ) : src && !broken ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img className="camera-media" src={src} alt={`Latest picture from ${cam.name ?? "the camera"}`} referrerPolicy="no-referrer"
          onError={() => setBroken(true)} />
      ) : (
        <p className="small">The picture did not load: the camera may be offline or its owner may be updating it. Try again in a minute.</p>
      )}
      {pictures.length > 1 && mode === "picture" && (
        <div className="small" style={{ display: "flex", gap: 8, marginTop: 4 }}>View:{pictures.map((_, i) => (
          <button key={i} className={`link small${i === view ? " on" : ""}`} onClick={() => setView(i)}>{i + 1}</button>))}</div>
      )}
      <p className="small muted" style={{ margin: "4px 0 0", fontSize: compact ? 11 : undefined }}>
        {!windy && mode === "picture" ? `${compact ? "" : "Checked "}${at.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}${compact ? "" : ", again every minute"}. ` : ""}
        {windy && fresh?.updated ? `Picture from ${new Date(fresh.updated).toLocaleString([], { dateStyle: "medium", timeStyle: "short" })}. ` : ""}
        {src0 && (src0.page ? <a href={windy ? (fresh?.page ?? cam.page ?? src0.page) : src0.page} target="_blank" rel="noreferrer">{src0.name}</a> : src0.name)}
      </p>
    </div>
  );
}

// An HLS live stream (Caltrans): the browser's own player where it has one, else hls.js, loaded only when asked for.
function LiveStream({ url, poster }: { url: string; poster?: string }) {
  const ref = useRef<HTMLVideoElement>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    const v = ref.current;
    if (!v) return;
    if (v.canPlayType("application/vnd.apple.mpegurl")) { v.src = url; return; }
    let hls: { destroy: () => void } | null = null;
    let gone = false;
    import("hls.js").then(({ default: Hls }) => {
      if (gone) return;
      if (!Hls.isSupported()) { setError("This browser cannot play the live stream."); return; }
      const h = new Hls({ lowLatencyMode: true });
      h.on(Hls.Events.ERROR, (_e, d) => { if (d.fatal) setError("The live stream stopped or would not start; the camera may be offline."); });
      h.loadSource(url);
      h.attachMedia(v);
      hls = h;
    }).catch(() => setError("The video player did not load."));
    return () => { gone = true; hls?.destroy(); };
  }, [url]);
  return (
    <>
      <video ref={ref} className="camera-media" poster={poster} controls autoPlay muted playsInline />
      {error && <p className="small">{error} <a href={url} target="_blank" rel="noreferrer">Stream link</a></p>}
    </>
  );
}
