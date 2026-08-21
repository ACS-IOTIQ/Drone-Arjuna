// ═══════════════════════════════════════════
// FleetWorkspace.tsx
// ═══════════════════════════════════════════
import { useCallback, useEffect, useState, type CSSProperties } from "react";
import { droneControlApi } from "@/api/droneControl";
import {
  Plus,
  RefreshCw,
  Anchor,
  Package,
  Cloud,
  Droplets,
  Thermometer,
  Wind,
  MapPin,
  CloudRain,
  Cable,
} from "lucide-react";
import {
  isDroneStale,
  useFleetStore,
  type DroneInstance,
} from "@/store/fleetStore";
import { useTelemetryStore } from "@/store/telemetryStore";
import { useVesselStore } from "@/store/vesselStore";
import { useAuthStore } from "@/store/authStore";
import { droneMasterApi } from "@/api/droneMaster";
import { payloadApi, type PayloadType } from "@/api/payload";
import { ConfirmModal } from "@/components/common/ConfirmModal";
import DroneCard from "./DroneCard";
import ConnectModal from "./ConnectModal";

const PAYLOAD_CACHE_KEY = "da_payload_types_fallback";
const PAYLOAD_ASSIGNMENT_KEY = "da_payload_assignments";
const INITIAL_DRONE_LIMIT = 6;

interface WeatherSnapshot {
  temperatureC: number;
  humidity: number;
  rainfallChance: number;
  windSpeedKph: number;
  label: string;
  icon: string;
}

function readCachedPayloads(): PayloadType[] {
  try {
    return JSON.parse(localStorage.getItem(PAYLOAD_CACHE_KEY) || "[]");
  } catch {
    return [];
  }
}

function readAssignments(): Record<number, number | null> {
  try {
    return JSON.parse(localStorage.getItem(PAYLOAD_ASSIGNMENT_KEY) || "{}");
  } catch {
    return {};
  }
}

export default function FleetWorkspace() {
  const { instances, connections, fetchInstances, fetchConnections } =
    useFleetStore();
  const role = useAuthStore((s) => s.role);
  const subscribe = useTelemetryStore((s) => s.subscribe);
  const { vessels, fetchVessels } = useVesselStore();
  const [showConnect, setShowConnect] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [quickConnecting, setQuickConnecting] = useState(false);
  const [quickConnectStatus, setQuickConnectStatus] = useState<
    "idle" | "connecting" | "ok" | "fail"
  >("idle");
  const [bridgeReady, setBridgeReady] = useState(false);
  const [showAllDrones, setShowAllDrones] = useState(false);
  const [payloads, setPayloads] = useState<PayloadType[]>([]);
  const [payloadAssignments, setPayloadAssignments] = useState<
    Record<number, number | null>
  >({});
  const [payloadErr, setPayloadErr] = useState("");
  const [weather, setWeather] = useState<WeatherSnapshot | null>(null);
  const [weatherNote, setWeatherNote] = useState("Checking local weather...");
  const [weatherLocation, setWeatherLocation] = useState<{
    lat: number;
    lon: number;
  } | null>(null);
  const [removeCandidate, setRemoveCandidate] = useState<DroneInstance | null>(
    null,
  );
  const [removingDrone, setRemovingDrone] = useState(false);
  const [removeError, setRemoveError] = useState("");

  const connectedCount = Object.values(connections).filter(
    (c) => c.connected,
  ).length;
  const canRemoveStaleDrones = ["mission_commander", "admin"].includes(role);

  const refresh = async () => {
    setRefreshing(true);
    try {
      await Promise.all([
        fetchInstances(),
        fetchConnections(),
        fetchVessels(),
        fetchPayloads(),
      ]);
    } finally {
      setRefreshing(false);
    }
  };

  // Poll bridge status every 3s to show Quick Connect button when cable is plugged in
  useEffect(() => {
    let active = true;
    const poll = async () => {
      try {
        const res = await droneControlApi.ports();
        if (active) setBridgeReady(res.data.bridge_connected ?? false);
      } catch {
        if (active) setBridgeReady(false);
      }
    };
    poll();
    const id = setInterval(poll, 3000);
    return () => {
      active = false;
      clearInterval(id);
    };
  }, []);

  const quickConnect = useCallback(async () => {
    if (instances.length === 0) return;
    setQuickConnecting(true);
    setQuickConnectStatus("connecting");
    try {
      await droneControlApi.autoconnect({ drone_instance_id: instances[0].id });
      await fetchConnections();
      setQuickConnectStatus("ok");
      setTimeout(() => setQuickConnectStatus("idle"), 3000);
    } catch {
      setQuickConnectStatus("fail");
      setTimeout(() => setQuickConnectStatus("idle"), 4000);
    } finally {
      setQuickConnecting(false);
    }
  }, [instances, fetchConnections]);

  const fetchPayloads = async () => {
    setPayloadErr("");
    try {
      const { data } = await payloadApi.listTypes();
      setPayloads(data);
    } catch {
      setPayloads(readCachedPayloads());
      setPayloadErr("Payload API unavailable; showing cached payloads.");
    }
  };

  useEffect(() => {
    setPayloadAssignments(readAssignments());
    refresh();
  }, []);

  // Keep online state and active-first ordering current while this workspace is open.
  useEffect(() => {
    const id = setInterval(fetchConnections, 5000);
    return () => clearInterval(id);
  }, [fetchConnections]);

  useEffect(() => {
    let active = true;

    const mapWeatherCode = (code: number) => {
      if (code === 0) return { label: "Clear sky", icon: "☀️" };
      if (code <= 2) return { label: "Mostly clear", icon: "🌤️" };
      if (code === 3) return { label: "Overcast", icon: "☁️" };
      if ([45, 48].includes(code)) return { label: "Fog", icon: "🌫️" };
      if ([51, 53, 55].includes(code)) return { label: "Drizzle", icon: "🌦️" };
      if ([61, 63, 65].includes(code)) return { label: "Rain", icon: "🌧️" };
      if ([71, 73, 75].includes(code)) return { label: "Snow", icon: "❄️" };
      if ([80, 81, 82].includes(code)) return { label: "Showers", icon: "🌦️" };
      if ([95, 96, 99].includes(code))
        return { label: "Storm risk", icon: "⛈️" };
      return { label: "Variable", icon: "🌤️" };
    };

    const fetchWeather = async (lat: number, lon: number) => {
      try {
        const url = `https://api.open-meteo.com/v1/forecast?latitude=${lat.toFixed(4)}&longitude=${lon.toFixed(4)}&current=temperature_2m,relative_humidity_2m,precipitation_probability,wind_speed_10m,weather_code&timezone=auto`;
        const res = await fetch(url);
        if (!res.ok) throw new Error("Weather unavailable");
        const data = await res.json();
        if (!active) return;
        const current = data.current;
        const meta = mapWeatherCode(current.weather_code);
        setWeather({
          temperatureC: current.temperature_2m,
          humidity: current.relative_humidity_2m,
          rainfallChance: current.precipitation_probability,
          windSpeedKph: current.wind_speed_10m,
          label: meta.label,
          icon: meta.icon,
        });
        setWeatherNote("Live weather for your current position");
      } catch {
        if (active) {
          setWeather(null);
          setWeatherNote("Weather service unavailable right now");
        }
      }
    };

    if (typeof navigator !== "undefined" && navigator.geolocation) {
      navigator.geolocation.getCurrentPosition(
        (position) => {
          const nextLocation = {
            lat: position.coords.latitude,
            lon: position.coords.longitude,
          };
          setWeatherLocation(nextLocation);
          void fetchWeather(nextLocation.lat, nextLocation.lon);
        },
        () => {
          if (active) {
            setWeatherLocation(null);
            setWeatherNote("Enable location to view live weather");
          }
        },
        { enableHighAccuracy: true, timeout: 10000 },
      );
    } else {
      setWeatherNote("Location unavailable in this browser");
    }

    return () => {
      active = false;
    };
  }, []);

  // Subscribe to telemetry for connected drones
  useEffect(() => {
    instances.forEach((d) => {
      if (connections[d.id]?.connected) subscribe(d.id);
    });
  }, [connections, instances]);

  // Build vessel lookup by id for card rendering
  const vesselById = Object.fromEntries(vessels.map((v) => [v.id, v]));

  const payloadById = Object.fromEntries(
    payloads.filter((p) => p.id != null).map((p) => [p.id!, p]),
  );

  const assignPayload = async (droneId: number, payloadId: number | null) => {
    const previous = payloadAssignments;
    const next = { ...payloadAssignments, [droneId]: payloadId };
    setPayloadAssignments(next);
    localStorage.setItem(PAYLOAD_ASSIGNMENT_KEY, JSON.stringify(next));
    setPayloadErr("");

    try {
      await payloadApi.assignToDrone(droneId, payloadId);
    } catch (e: any) {
      setPayloadErr(
        e.response?.data?.detail ??
          "Payload assignment saved locally; backend route is not reachable.",
      );
      setPayloadAssignments(next || previous);
    }
  };

  const removeStaleDrone = async () => {
    if (!removeCandidate) return;
    setRemovingDrone(true);
    setRemoveError("");
    try {
      await droneMasterApi.removeStaleDrone(removeCandidate.id);
      const nextAssignments = { ...payloadAssignments };
      delete nextAssignments[removeCandidate.id];
      setPayloadAssignments(nextAssignments);
      localStorage.setItem(
        PAYLOAD_ASSIGNMENT_KEY,
        JSON.stringify(nextAssignments),
      );
      setRemoveCandidate(null);
      await Promise.all([fetchInstances(), fetchConnections()]);
    } catch (e: any) {
      setRemoveError(
        e.response?.data?.detail ?? "Unable to remove inactive drone",
      );
    } finally {
      setRemovingDrone(false);
    }
  };

  return (
    // The workspace is a fixed-height shell: a pinned header plus a single
    // scroll region. Nothing inside the scroll region can be compressed, so
    // the weather bar (and every other section) stays fully intact no matter
    // how many drones are registered.
    <div className="flex h-full min-h-0 flex-col overflow-hidden">
      {/* Header row — pinned, never scrolls away, never shrinks */}
      <div className="da-workspace-header flex shrink-0 flex-wrap items-start justify-between gap-3 px-5 pb-4 pt-5">
        <div className="min-w-0">
          <h2 className="text-lg font-semibold">Fleet Overview</h2>
          <p className="text-xs mt-0.5" style={{ color: "#6b7280" }}>
            {instances.length} registered · {connectedCount} connected
          </p>
        </div>
        <div className="flex gap-2 flex-wrap">
          <button onClick={refresh} className="da-btn da-btn-ghost">
            <RefreshCw size={14} className={refreshing ? "animate-spin" : ""} />
            Refresh
          </button>

          {/* Quick Connect — visible when com_bridge has a cable plugged in */}
          {bridgeReady && (
            <button
              onClick={quickConnect}
              disabled={quickConnecting || connectedCount > 0}
              className="da-btn"
              style={{
                background:
                  quickConnectStatus === "ok"
                    ? "rgba(34,197,94,0.15)"
                    : quickConnectStatus === "fail"
                      ? "rgba(239,68,68,0.15)"
                      : "rgba(34,197,94,0.1)",
                color:
                  quickConnectStatus === "ok"
                    ? "#22c55e"
                    : quickConnectStatus === "fail"
                      ? "#ef4444"
                      : "#22c55e",
                border: "1px solid rgba(34,197,94,0.3)",
              }}
            >
              <Cable
                size={14}
                className={quickConnecting ? "animate-pulse" : ""}
              />
              {quickConnectStatus === "connecting"
                ? "Connecting…"
                : quickConnectStatus === "ok"
                  ? "Connected!"
                  : quickConnectStatus === "fail"
                    ? "Failed — retry"
                    : "Quick Connect (Cable)"}
            </button>
          )}

          <button
            onClick={() => setShowConnect(true)}
            className="da-btn da-btn-primary"
          >
            <Plus size={14} /> Connect Drone
          </button>
        </div>
      </div>

      {/* Single scroll region for all fleet content */}
      <div className="da-workspace-scroll min-h-0 flex-1 overflow-y-auto overflow-x-hidden px-5 pb-5">
        {/* Local weather card */}
        <div className="da-weather-panel mb-4 shrink-0 rounded-lg border px-3 py-2 shadow-sm">
          <div className="flex flex-wrap items-center gap-3">
            <div className="flex min-w-[210px] flex-1 items-center gap-2">
              <Cloud size={14} className="text-sky-200 shrink-0" />
              <div className="text-2xl font-semibold leading-none">
                {weather ? `${weather.temperatureC.toFixed(0)}C` : "--"}
              </div>
              <div className="min-w-0">
                <div className="truncate text-xs font-semibold text-slate-100">
                  {weather
                    ? `${weather.icon} ${weather.label}`
                    : "Checking local conditions"}
                </div>
                <div className="flex items-center gap-1 truncate text-[10px] text-slate-300">
                  <MapPin size={10} className="shrink-0" />
                  <span className="truncate">
                    {weatherLocation
                      ? `${weatherLocation.lat.toFixed(2)}, ${weatherLocation.lon.toFixed(2)}`
                      : weatherNote}
                  </span>
                </div>
              </div>
            </div>
            <div className="grid min-w-0 flex-1 gap-1.5 sm:grid-cols-2 xl:grid-cols-4">
              {[
                {
                  label: "Rain",
                  value: weather ? `${weather.rainfallChance}%` : "--",
                  icon: <CloudRain size={12} />,
                },
                {
                  label: "Humidity",
                  value: weather ? `${weather.humidity}%` : "--",
                  icon: <Droplets size={12} />,
                },
                {
                  label: "Wind",
                  value: weather
                    ? `${weather.windSpeedKph.toFixed(0)} kph`
                    : "--",
                  icon: <Wind size={12} />,
                },
                {
                  label: "Feels",
                  value: weather
                    ? `${(weather.temperatureC + 1.5).toFixed(0)}C`
                    : "--",
                  icon: <Thermometer size={12} />,
                },
              ].map((item) => (
                <div
                  key={item.label}
                  className="da-weather-stat min-w-0 rounded border px-2 py-1"
                >
                  <div className="flex items-center gap-1.5 text-[9px] uppercase text-slate-300">
                    {item.icon} <span className="truncate">{item.label}</span>
                  </div>
                  <div className="truncate text-xs font-semibold text-white">
                    {item.value}
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* Summary bar */}
        <div className="mb-5 grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-5">
          {[
            { label: "Registered", val: instances.length, color: "#3b82f6" },
            { label: "Connected", val: connectedCount, color: "#22c55e" },
            {
              label: "Offline",
              val: instances.length - connectedCount,
              color: "#6b7280",
            },
            { label: "Vessels", val: vessels.length, color: "#06b6d4" },
            { label: "Alerts", val: 0, color: "#f59e0b" },
          ].map((s) => (
            <div
              key={s.label}
              className="da-card da-stat-tile min-w-0 px-4 py-3 flex flex-col gap-1"
              style={{ "--da-stat-color": s.color } as CSSProperties}
            >
              <span className="da-stat-value" style={{ color: s.color }}>
                {s.val}
              </span>
              <span className="da-stat-label" style={{ color: "#6b7280" }}>
                {s.label}
              </span>
            </div>
          ))}
        </div>

        {/* Naval vessels strip */}
        {vessels.length > 0 && (
          <div className="mb-5">
            <h3 className="da-section-label mb-3">Naval Vessels</h3>
            <div className="flex gap-3 flex-wrap">
              {vessels.map((v) => (
                <div
                  key={v.id}
                  className="da-card px-4 py-2 flex items-center gap-3 min-w-[220px]"
                >
                  <Anchor
                    size={16}
                    style={{ color: "#06b6d4", flexShrink: 0 }}
                  />
                  <div className="flex-1 min-w-0">
                    <div className="text-sm font-semibold truncate">
                      {v.vessel_id}
                    </div>
                    <div
                      className="text-xs truncate"
                      style={{ color: "#6b7280" }}
                    >
                      {v.name}
                    </div>
                  </div>
                  <div className="flex flex-col items-end gap-0.5">
                    <span
                      className="text-xs font-medium px-1.5 py-0.5 rounded"
                      style={{
                        background:
                          v.deck_status === "clear"
                            ? "#14532d"
                            : v.deck_status === "occupied"
                              ? "#7c2d12"
                              : "#3b2d06",
                        color:
                          v.deck_status === "clear"
                            ? "#86efac"
                            : v.deck_status === "occupied"
                              ? "#fca5a5"
                              : "#fde68a",
                      }}
                    >
                      {v.deck_status}
                    </span>
                    {v.latitude != null && (
                      <span
                        className="text-xs mono"
                        style={{ color: "#6b7280" }}
                      >
                        {v.heading_deg != null
                          ? `${v.heading_deg.toFixed(0)}° `
                          : ""}
                        {v.speed_kts != null
                          ? `${v.speed_kts.toFixed(1)} kts`
                          : ""}
                      </span>
                    )}
                    {v.latitude == null && (
                      <span className="text-xs" style={{ color: "#f59e0b" }}>
                        no position
                      </span>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Payload assignment */}
        <div className="mb-5">
          <div className="flex flex-wrap items-center justify-between gap-2 mb-3">
            <h3 className="da-section-label">Payload Assignment</h3>
            {payloadErr && (
              <span className="text-[11px]" style={{ color: "#d97706" }}>
                {payloadErr}
              </span>
            )}
          </div>
          <div className="da-card overflow-hidden">
            {instances.length === 0 ? (
              <p className="text-xs px-4 py-3" style={{ color: "#64748b" }}>
                Register drones before assigning payloads.
              </p>
            ) : (
              <div
                className="grid"
                style={{
                  gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))",
                }}
              >
                {instances.map((d) => {
                  const assigned = payloadAssignments[d.id];
                  const payload = assigned ? payloadById[assigned] : null;
                  return (
                    <div
                      key={d.id}
                      className="flex min-w-0 items-center gap-3 p-3"
                      style={{
                        borderRight: "1px solid var(--da-border)",
                        borderBottom: "1px solid var(--da-border)",
                      }}
                    >
                      <Package
                        size={15}
                        style={{
                          color: payload ? "#0f766e" : "#64748b",
                          flexShrink: 0,
                        }}
                      />
                      <div className="flex-1 min-w-0">
                        <div className="truncate text-xs font-semibold">
                          {d.call_sign}
                        </div>
                        <select
                          className="da-input mt-1 w-full"
                          value={assigned ?? ""}
                          onChange={(e) =>
                            assignPayload(
                              d.id,
                              e.target.value ? Number(e.target.value) : null,
                            )
                          }
                        >
                          <option value="">No payload mounted</option>
                          {payloads.map((p) => (
                            <option key={p.id ?? p.name} value={p.id}>
                              {p.name} - {p.category} ({p.weight_kg} kg)
                            </option>
                          ))}
                        </select>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </div>

        {/* Drone grid */}
        {instances.length === 0 ? (
          <div
            className="flex min-h-[240px] flex-col items-center justify-center gap-3"
            style={{ color: "#374151" }}
          >
            <Plus size={40} style={{ opacity: 0.3 }} />
            <p className="text-sm">
              No drones registered. Add one in Settings → Master Data.
            </p>
          </div>
        ) : (
          <>
            <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
              <p className="text-xs text-slate-500">
                Showing{" "}
                {showAllDrones
                  ? instances.length
                  : Math.min(INITIAL_DRONE_LIMIT, instances.length)}{" "}
                of {instances.length} drones
              </p>
              {instances.length > INITIAL_DRONE_LIMIT && (
                <button
                  onClick={() => setShowAllDrones((v) => !v)}
                  className="da-btn da-btn-ghost text-xs"
                >
                  {showAllDrones ? "Show less" : "Show all"}
                </button>
              )}
            </div>
            <div
              className="grid gap-4"
              style={{
                gridTemplateColumns: "repeat(auto-fill, minmax(300px, 1fr))",
              }}
            >
              {instances
                .slice(
                  0,
                  showAllDrones ? instances.length : INITIAL_DRONE_LIMIT,
                )
                .map((d) => (
                  <DroneCard
                    key={d.id}
                    drone={d}
                    connected={!!connections[d.id]?.connected}
                    homeVessel={
                      d.home_vessel_id != null
                        ? vesselById[d.home_vessel_id]
                        : undefined
                    }
                    connectionInfo={connections[d.id]}
                    payloadName={
                      payloadAssignments[d.id] &&
                      payloadById[payloadAssignments[d.id]!]
                        ? payloadById[payloadAssignments[d.id]!]!.name
                        : undefined
                    }
                    stale={!connections[d.id]?.connected && isDroneStale(d)}
                    onRemove={
                      canRemoveStaleDrones
                        ? () => {
                            setRemoveError("");
                            setRemoveCandidate(d);
                          }
                        : undefined
                    }
                  />
                ))}
            </div>
          </>
        )}
      </div>

      {showConnect && <ConnectModal onClose={() => setShowConnect(false)} />}
      {removeCandidate && (
        <ConfirmModal
          title={`Remove ${removeCandidate.call_sign}?`}
          message={
            removeError ||
            "This drone has not been used for at least 30 days. It will be removed from the fleet, while historical missions are preserved and unassigned."
          }
          confirmLabel="Remove drone"
          variant="danger"
          isLoading={removingDrone}
          onConfirm={removeStaleDrone}
          onCancel={() => {
            if (!removingDrone) {
              setRemoveCandidate(null);
              setRemoveError("");
            }
          }}
        />
      )}
    </div>
  );
}
