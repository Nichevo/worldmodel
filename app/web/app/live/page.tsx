"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense } from "react";
import { Counts, Planes, ShipCard, Ships, Sweeps } from "@/components/LiveTables";
import { SchedulesBoard } from "@/components/ShipSchedule";

function LivePage() {
  const sp = useSearchParams();
  const router = useRouter();
  const tabs = ["ships", "ship-counts", "schedules", "planes", "plane-counts"] as const;
  const tab = tabs.find((t) => t === sp.get("tab")) ?? "ships";
  const init = (k: string) => sp.get(k) ?? "";
  // A counts row opens the list with that filter (the list keeps it until changed).
  const drill = (t: "ships" | "planes", f: Record<string, string>) => {
    const q = new URLSearchParams({ tab: t, ...f });
    router.push(`/live?${q.toString()}`, { scroll: false });
  };
  const key = ["group", "q", "to", "came", "airline", "from", "ontime"].map(init).join("|");
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
        <button aria-pressed={tab === "ships"} onClick={() => router.replace("/live?tab=ships", { scroll: false })}>Ships</button>
        <button aria-pressed={tab === "ship-counts"} onClick={() => router.replace("/live?tab=ship-counts", { scroll: false })}>Ship counts</button>
        <button aria-pressed={tab === "schedules"} onClick={() => router.replace("/live?tab=schedules", { scroll: false })}>Schedules</button>
        <button aria-pressed={tab === "planes"} onClick={() => router.replace("/live?tab=planes", { scroll: false })}>Planes</button>
        <button aria-pressed={tab === "plane-counts"} onClick={() => router.replace("/live?tab=plane-counts", { scroll: false })}>Plane counts</button>
      </div>
      {tab === "ships" && <><Ships key={key} init={init} open={open} setOpen={(id) => setParams({ id })} /><Sweeps /></>}
      {tab === "planes" && <Planes key={key} init={init} open={open} setOpen={(id) => setParams({ id })} />}
      {tab === "ship-counts" && <Counts what="ships" drill={drill} />}
      {tab === "schedules" && <><SchedulesBoard openShip={(id) => setParams({ id })} />{open && <ShipCard id={open} onClose={() => setParams({ id: null })} />}</>}
      {tab === "plane-counts" && <Counts what="planes" drill={drill} />}
    </div>
  );
}

export default function Page() {
  return <Suspense fallback={<p className="muted">Loading…</p>}><LivePage /></Suspense>;
}
