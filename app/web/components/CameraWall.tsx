"use client";

// The camera wall: several cameras from the map's Cameras layer side by side, each with its latest
// picture (or clip or live video). Over the map when `onGo` is given (click a name to fly there),
// or as a whole page at /cameras.

import Link from "next/link";
import CameraView from "@/components/CameraView";
import { clearWall, moveOnWall, showCameraWall, toggleWall, useCameraWall, useCameraWallOpen, WALL_MAX } from "@/lib/cameraWall";
import { useState } from "react";

export default function CameraWall({ onGo, page = false }: { onGo?: (lng: number, lat: number) => void; page?: boolean }) {
  const wall = useCameraWall();
  const open = useCameraWallOpen();
  const [big, setBig] = useState(false);
  if (!wall.length && !page) return null;
  if (!page && !open) {
    return (
      <button className="camera-wall-tab small" onClick={() => showCameraWall(true)} title="Show the cameras you put on the wall">
        Camera wall ({wall.length})</button>
    );
  }
  return (
    <div className={page ? "camera-wall page" : `camera-wall${big ? " big" : ""}`} role="region" aria-label="Camera wall">
      <div className="row small" style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 6 }}>
        <b>Camera wall</b><span className="muted">{wall.length} of {WALL_MAX}</span><span className="spacer" />
        {!page && <button className="link small" onClick={() => setBig(!big)}>{big ? "Smaller" : "Fill the map"}</button>}
        {!page && <Link className="small" href="/cameras" target="_blank" title="The wall on a page of its own, in a new tab">Own page</Link>}
        {wall.length > 0 && <button className="link small" onClick={clearWall} title="Take every camera off the wall">Clear</button>}
        {!page && <button className="link small" onClick={() => showCameraWall(false)} aria-label="Hide the camera wall">×</button>}
      </div>
      {!wall.length ? (
        <p className="small">No cameras on the wall yet. On the map, turn on the Cameras layer, click a camera and press <b>Add to wall</b> (or ctrl-click it).
          {" "}<Link href="/?l=1&p=map.none.........-">Open the map with cameras</Link></p>
      ) : (
        <div className="camera-wall-grid">
          {wall.map((c, i) => (
            <div key={c.id} className="camera-wall-tile">
              <div className="row small" style={{ display: "flex", alignItems: "center", gap: 6 }}>
                {onGo && c.lng != null && c.lat != null
                  ? <button className="link small camera-wall-name" title="Show it on the map" onClick={() => onGo(c.lng!, c.lat!)}>{c.name ?? "Camera"}</button>
                  : <span className="camera-wall-name" title={c.about ?? undefined}>{c.name ?? "Camera"}</span>}
                <span className="spacer" />
                <button className="link small" disabled={i === 0} onClick={() => moveOnWall(c.id, -1)} aria-label="Move earlier" title="Move earlier">‹</button>
                <button className="link small" disabled={i === wall.length - 1} onClick={() => moveOnWall(c.id, 1)} aria-label="Move later" title="Move later">›</button>
                <button className="link small" onClick={() => toggleWall(c)} aria-label="Take off the wall" title="Take off the wall">×</button>
              </div>
              <CameraView cam={c} compact />
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
