# Log Analysis & Chart Display — DroneArjuna

Audience: developers extending the Monitor / Settings workspaces or the telemetry backend.

DroneArjuna has three separate "log" data paths. They do not share a store, so each is documented on its own.

| Path | Data | Where it lives | Displayed by |
|------|------|----------------|--------------|
| 1. System event log | Audit events (auth, command, mission, connection…) | Frontend memory (Zustand), last 5000 | `SystemLogViewer` (Settings → Logs) |
| 2. Monitor live log | Health alerts, mode/arm changes | Frontend memory (module array), last 500 | `SystemLog` (Monitor workspace) |
| 3. Telemetry | 10 Hz MAVLink frames | Browser buffer (300 frames) + TimescaleDB | `TelemetryChart`, replay player |

---

## 1. System event log (audit trail)

**Store:** [eventLogStore.ts](../frontend/src/store/eventLogStore.ts)

```ts
SystemEvent {
  id, timestamp: Date,
  category: 'auth'|'drone'|'mission'|'command'|'system'|'connection'|'telemetry',
  level:    'info'|'success'|'warning'|'error',
  title, description, details?, userId?, droneId?, missionId?
}
```

- `addEvent()` prepends the event and keeps the newest **5000**.
- Do not call `addEvent` directly. Use the `eventLog` helpers: `eventLog.auth / authSuccess / authError / drone / command / mission / connection / telemetry / system`.
- Queries: `getEventsByCategory`, `getEventsByDrone`, `getRecentEvents(n)`.
- `clearOldEvents(days)` drops events older than the cutoff.
- `exportLogs('json' | 'csv')` returns a string.

**Viewer:** [SystemLogViewer.tsx](../frontend/src/components/common/SystemLogViewer.tsx), mounted in [SettingsWorkspace.tsx:141](../frontend/src/workspaces/Settings/SettingsWorkspace.tsx#L141) on the `logs` tab.

Analysis features:
- Filter by category and by level (combined with AND).
- Counter: "Showing X of Y total events".
- Level-coded rows (icon, background tint, badge); `details` is shown as pretty-printed JSON.
- Export JSON/CSV to `system-logs.{json,csv}` through a Blob download.
- "Clear" removes events older than **7 days**. It is not a full wipe.

Limitations:
- Events are in-memory only. They are lost on page reload and are not shared between operators.
- The CSV export has no `missionId` or `details` columns, and cells are wrapped in `"` without escaping embedded quotes. Descriptions containing `"` will break the CSV.
- There is no charting here yet (see "Suggested log charts" below).

---

## 2. Monitor live log

**Component:** [SystemLog.tsx](../frontend/src/workspaces/Monitor/SystemLog.tsx), rendered in [MonitorWorkspace.tsx](../frontend/src/workspaces/Monitor/MonitorWorkspace.tsx).

- Module-level ring buffer `_log` (max **500**), with `appendLog({level, source, message, droneId})` and a listener set for re-render.
- Sources bridged in:
  - `notificationStore` → `source: 'health'`
  - `telemetryStore` frames → `source: 'drone_control'` for flight-mode changes (`info`) and ARMED/DISARMED (`warning` / `success`)
- Filters: level (`all`, `danger`, `warning`, `info`, `debug`) and the active drone. Auto-scroll toggle.
- Export: CSV (`timestamp,level,source,message`, with quotes escaped).

---

## 3. Telemetry: storage, API, charts

### 3.1 Backend pipeline

```
MAVLink → mavlink_manager → StateManager ──► WebSocket /api/drone-control/stream/{id}  (live UI)
                                  │
                                  └─► DataRecorder.record()  (data_recorder.py)
                                        ├─ change detection (skips identical frames)
                                        └─ buffers, flushed every 1 s (FLUSH_INTERVAL_S)
                                              ├─ telemetry          (1 row / drone, upsert)
                                              ├─ telemetry_gauges   (1 row / drone, upsert)
                                              └─ telemetry_history  (append-only hypertable)
battery_snapshots (hypertable) ← record_battery_snapshot(), every 2 min during a mission
```

Source: [data_recorder.py](../backend/app/modules/drone_control/data_recorder.py).

| Table | Shape | Retention | Columns |
|-------|-------|-----------|---------|
| `telemetry` | 1 row per `drone_id` | latest only | full frame (position, attitude, speeds, battery, GPS, mode, rssi, cpu, mission_id…) |
| `telemetry_gauges` | 1 row per `drone_id` | latest only | battery_pct, altitude_m, ground_speed_ms, gps_satellites, rssi, cpu_load_pct |
| `telemetry_history` | time series | **1 day** (`RETENTION_DAYS`) | lat, lon, alt_agl, yaw, pitch, roll |
| `battery_snapshots` | time series | 1 day | battery_pct, mission_id |

Safeguards: history buffer is capped at `MAX_PENDING_HISTORY = 20_000` rows. Beyond that, rows are dropped with a warning so a TimescaleDB outage cannot exhaust memory.

### 3.2 Query endpoints

All require a Bearer token (min role VIEWER).

| Endpoint | Returns | Defaults |
|----------|---------|----------|
| `GET /api/drone-control/telemetry/{id}` | live snapshot | — |
| `GET /api/drone-control/telemetry/{id}/gauges` | battery, alt, speed, sats, rssi, cpu | 404 if none |
| `GET /api/drone-control/telemetry/{id}/history?start&end` | `[{timestamp, lat, lng, alt, yaw, pitch, roll}]` oldest first | last 1 h |
| `GET /api/drone-control/telemetry/{id}/battery-log?start&end` | `[{timestamp, battery_remaining_pct, mission_id}]` | last 24 h |
| `GET /api/analyst/missions/{id}/stats` | frame count, duration, avg/max alt & speed, min battery, avg CPU, distance | zeros if no data |
| `GET /api/analyst/missions/{id}/series?param&bucket_seconds` | `{series: [{t, value}]}` using `time_bucket` + `AVG` | `alt_agl`, 5 s (1–300) |

The analyst series endpoint whitelists `param` against: `alt_agl, alt_msl, groundspeed_ms, airspeed_ms, climb_rate_ms, battery_remaining_pct, battery_voltage_v, heading, roll_deg, pitch_deg, rssi, cpu_load_pct`. Other values return HTTP 400.

Frontend calls must use relative URLs through the Vite proxy (DEF-08).

### 3.3 Live chart

**Component:** [TelemetryChart.tsx](../frontend/src/workspaces/Monitor/TelemetryChart.tsx) (Recharts), used as `<TelemetryChart droneId={activeDroneId} />`.

Data flow:
1. `telemetryStore` receives WebSocket frames and keeps the **last 300 frames per drone** in `history[droneId]`. A frame with the same lat/lon/alt as the previous one is not appended.
2. The chart reads `history`, downsamples with `step = floor(len / maxHistory)` (default `maxHistory = 120`), and maps to `{t: index, value: frame[activeParam]}`.
3. The Y domain is `[min - 15%, max + 15%]` (fallback pad of 10), rounded to integers.
4. Rendered as a `LineChart` with no animation or dots, a hidden X axis, and a tooltip formatted as `value + unit`.

Selectable parameters (edit the `PARAMS` array to add more):

| Key | Label | Unit | Warn | Danger |
|-----|-------|------|------|--------|
| `alt_agl` | Altitude AGL | m | — | — |
| `groundspeed_ms` | Ground Speed | m/s | — | — |
| `battery_remaining_pct` | Battery | % | 25 | 15 |
| `climb_rate_ms` | Climb Rate | m/s | — | — |
| `airspeed_ms` | Airspeed | m/s | — | — |
| `rssi` | RSSI | — | — | 40 |

Threshold lines are dashed `ReferenceLine`s (amber for warn, red for danger). Shows "Waiting for telemetry data…" until there are at least 2 points. A pulsing badge shows the latest value.

**To add a parameter:** add an entry to `PARAMS` (key must exist on `TelemetryFrame`), and optionally `warnThreshold` / `dangerThreshold`.

### 3.4 Other displays

- Monitor workspace also shows a buffered-frame count and an export of the in-memory history, via `MonitorWorkspace.tsx`.
- The Telemetry Replay Player reads `/telemetry/{id}/history` (flight path, last hour by default).

---

## 4. Suggested log charts (not yet implemented)

Everything needed is already in the data model. Using the same Recharts setup:

| Chart | Source | Type |
|-------|--------|------|
| Events per level over time | `eventLogStore.events`, bucketed by `timestamp` | Stacked bar |
| Events by category | `events` grouped by `category` | Horizontal bar / donut |
| Errors per drone | `events` where `level === 'error'`, grouped by `droneId` | Bar |
| Battery over a mission | `/battery-log` | Line + warn/danger reference lines |
| Altitude/speed profile for replay | `/telemetry/{id}/history` | Line, X = real `timestamp` |
| Post-mission parameter chart | `/analyst/missions/{id}/series` | Line, X = `t` |

Sketch of the aggregation for the first chart:

```ts
const bucketMs = 5 * 60_000
const byBucket = new Map<number, Record<EventLevel, number>>()
for (const e of events) {
  const k = Math.floor(e.timestamp.getTime() / bucketMs) * bucketMs
  const row = byBucket.get(k) ?? { info: 0, success: 0, warning: 0, error: 0 }
  row[e.level]++
  byBucket.set(k, row)
}
const data = [...byBucket].sort((a, b) => a[0] - b[0]).map(([t, r]) => ({ t, ...r }))
```

---

## 5. Known issues to be aware of

1. **Analyst stats/series read the wrong table.** `mission_telemetry_stats` and `mission_telemetry_series` in [service.py](../backend/app/modules/drone_analyst/service.py) query `telemetry`, which `DataRecorder` now keeps as one row per drone. They therefore return at most a single frame, not a mission time series. Fixing this means giving `telemetry_history` a `mission_id` and the required columns (or recording a per-mission table), then pointing the queries at it. Nothing in the frontend currently consumes these endpoints.
2. **`telemetry_history` holds only position and attitude.** It cannot back speed, battery, RSSI or CPU charts. Only the live 300-frame browser buffer and `battery_snapshots` can.
3. **Retention is 1 day**, so "log analysis" over longer periods needs a policy change (`RETENTION_DAYS`) or an aggregate.
4. **Live chart X axis is a sample index**, not time. Tooltips show no timestamp, and downsampling changes the apparent time scale.
5. **Event logs are volatile** (see section 1); there is no backend audit-log table yet.
6. CSV export in `eventLogStore.exportLogs` does not escape quotes (see section 1).
