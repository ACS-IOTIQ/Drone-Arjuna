import { useEffect, useState } from "react";
import { Download } from "lucide-react";
import { useFleetStore } from "@/store/fleetStore";
import { useTelemetryStore, TelemetryFrame } from "@/store/telemetryStore";
import GaugeDashboard from "./GaugeDashboard";
import TelemetryChart from "./TelemetryChart";
import SystemLog from "./SystemLog";

export default function MonitorWorkspace() {
  const { instances, connections, fetchInstances, fetchConnections } =
    useFleetStore();
  const { subscribe, unsubscribe } = useTelemetryStore();
  const [selDrone, setSelDrone] = useState<number | null>(null);

  // Fetch data on mount and poll every 5 s for connection changes
  useEffect(() => {
    fetchInstances();
    fetchConnections();
    const poll = setInterval(fetchConnections, 5000);
    return () => clearInterval(poll);
  }, []);

  const connectedDrones = instances.filter((d) => connections[d.id]?.connected);
  const connectedIds = connectedDrones.map((d) => d.id);
  const activeDroneId =
    selDrone != null && connections[selDrone]?.connected
      ? selDrone
      : (connectedIds[0] ?? null);

  // Subscribe to live telemetry WebSocket for the active drone
  useEffect(() => {
    if (!activeDroneId) return;
    subscribe(activeDroneId);
    return () => unsubscribe(activeDroneId);
  }, [activeDroneId]);

  return (
    // Pinned selector + a single scroll region, so the drone strip stays intact
    // and never pushes the dashboard out of view when many drones connect.
    <div className="flex h-full min-h-0 flex-col overflow-hidden">
      {/* Drone selector — only visible when multiple connected.
          Scrolls horizontally instead of stretching the workspace. */}
      {connectedIds.length > 1 && (
        <div className="da-scroll-strip flex shrink-0 items-center gap-2 px-5 pt-5">
          {connectedDrones.map((d) => (
            <button
              key={d.id}
              onClick={() => setSelDrone(d.id)}
              className={`da-btn da-monitor-selector shrink-0 text-xs ${d.id === activeDroneId ? "is-active" : ""}`}
            >
              {d.call_sign}
            </button>
          ))}
        </div>
      )}

      <div className="min-h-0 flex-1 overflow-y-auto overflow-x-hidden p-5">
        {!activeDroneId ? (
          <div className="flex min-h-[240px] items-center justify-center">
            <p style={{ color: "#374151" }}>
              No drones connected. Connect a drone in the Fleet workspace.
            </p>
          </div>
        ) : (
          <div className="flex flex-col gap-4">
            <GaugeDashboard droneId={activeDroneId} />
            <TelemetryChart droneId={activeDroneId} />

            {/* Raw telemetry + system log side by side on wide screens */}
            <div className="grid min-w-0 grid-cols-1 gap-4 xl:grid-cols-2">
              <RawTelemetry droneId={activeDroneId} />
              <SystemLog droneId={activeDroneId} />
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function RawTelemetry({ droneId }: { droneId: number }) {
  const frame = useTelemetryStore((s) => s.frames[droneId]);
  const history = useTelemetryStore((s) => s.history[droneId] ?? []);

  const exportCsv = () => {
    const rows = history.length ? history : frame ? [frame] : [];
    if (rows.length === 0) return;
    const keys = Array.from(
      new Set(rows.flatMap((row) => Object.keys(row))),
    ).sort();
    const escape = (value: unknown) =>
      `"${String(value ?? "").replace(/"/g, '""')}"`;
    const csv = [
      keys.join(","),
      ...rows.map((row) =>
        keys.map((key) => escape((row as any)[key])).join(","),
      ),
    ].join("\n");
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `drone-${droneId}-telemetry.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="da-card min-w-0 p-4">
      <div className="mb-3 flex items-center justify-between gap-2">
        <div className="min-w-0">
          <h3 className="text-sm font-semibold">Raw Telemetry</h3>
          <p className="text-[11px]" style={{ color: "#64748b" }}>
            {history.length} buffered frames
          </p>
        </div>
        <button
          className="da-btn da-btn-ghost shrink-0 text-xs"
          onClick={exportCsv}
          disabled={!frame && history.length === 0}
        >
          <Download size={13} /> CSV
        </button>
      </div>
      <div
        className="mono grid grid-cols-1 gap-x-6 gap-y-0.5 overflow-auto text-xs sm:grid-cols-2"
        style={{ maxHeight: 280 }}
      >
        {frame ? (
          Object.entries(frame)
            .filter(([k]) => !["call_sign", "connected"].includes(k))
            .map(([k, v]) => (
              <div
                key={k}
                className="flex min-w-0 justify-between gap-2 py-0.5"
                style={{ borderBottom: "1px solid var(--da-border)" }}
              >
                <span className="truncate" style={{ color: "#4b5563" }}>
                  {k}
                </span>
                <span className="shrink-0" style={{ color: "#94a3b8" }}>
                  {typeof v === "number" ? (v as number).toFixed(2) : String(v)}
                </span>
              </div>
            ))
        ) : (
          <p style={{ color: "#374151" }}>Waiting for telemetry…</p>
        )}
      </div>
    </div>
  );
}
