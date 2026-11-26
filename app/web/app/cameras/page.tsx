"use client";

import { useEffect } from "react";
import CameraWall from "@/components/CameraWall";
import { logHistory } from "@/lib/history";

// The camera wall on a page of its own: the cameras put on the wall from the map, side by side.
export default function CamerasPage() {
  useEffect(() => { logHistory({ kind: "page", title: "Camera wall", url: "/cameras", detail: "page" }); }, []);
  return (
    <div className="grid">
      <h1>Camera wall</h1>
      <p className="muted small">Cameras you put on the wall from the map&apos;s Cameras layer, kept in this browser. Pictures refresh every minute.</p>
      <CameraWall page />
    </div>
  );
}
