# MAVLink Communication — Drone Control Module

This document describes how DroneArjuna talks to real and simulated vehicles over
MAVLink. It covers the connection lifecycle, transports, data flow, command
dispatch, HF (ship-to-shore) support, and the simulator's MAVLink broadcaster.

All code lives under `backend/app/modules/drone_control/` and
`backend/app/utils/`, built on **pymavlink**.

---

## 1. Component overview

| Component | File | Responsibility |
|---|---|---|
| `MAVLinkManager` | `mavlink_manager.py` | Singleton owning all drone connections; one asyncio read-loop task per drone |
| `mavlink_executor` | `utils/mavlink_executor.py` | Dedicated 64-thread pool for blocking pymavlink I/O |
| `mavlink_utils` | `utils/mavlink_utils.py` | Connection-string builders, mode/GPS/status decoders, coordinate packing |
| `CommandController` | `command_controller.py` | Per-drone: validates, encodes, dispatches commands and tracks ACKs |
| `TelemetryProcessor` | `telemetry_processor.py` | Parses inbound MAVLink messages into `StateManager` state |
| `HFLinkAdapter` | `hf_link_adapter.py` | HF-radio tier: message priority filtering, degraded/lost link state machine |
| `AutoConnector` | `auto_connector.py` | Background task that discovers and auto-connects drones via `com_bridge` |
| `MAVLinkBroadcaster` | `mavlink_broadcaster.py` | Re-encodes simulated drone state as real MAVLink UDP packets for external GCS |

---

## 2. Connection lifecycle (`MAVLinkManager`)

`mavlink_manager` (module-level singleton) holds a `DroneConnection` per drone:

```python
@dataclass
class DroneConnection:
    drone_id, call_sign, transport, connection_string
    mav: Optional[object]              # pymavlink connection
    task, heartbeat_task, home_task     # asyncio tasks
    controller: CommandController
    connected: bool
    hf_adapter: Optional[HFLinkAdapter]
    link_timeout_s: float
```

### `connect(drone_id, call_sign, transport, host, port, serial_port, baud_rate, hf_modem_type, heartbeat_timeout)`

1. Acquires a per-`drone_id` `asyncio.Lock`, pre-checks it isn't already connected.
2. Builds the connection string via `build_connection_string()`.
3. Opens `mavutil.mavlink_connection(conn_str, source_system=255)` in the
   `mavlink_executor` thread pool (blocking call, so it never touches the event loop).
4. Awaits the first heartbeat with a transport-specific timeout (10 s for
   udp/tcp/serial, 45 s for HF — see [§5](#5-hf-ship-to-shore-datalink)).
5. Requests telemetry streams — **both** legacy `REQUEST_DATA_STREAM` and
   `MAV_CMD_SET_MESSAGE_INTERVAL` per message, because modern ArduPilot/PX4
   silently ignore `REQUEST_DATA_STREAM` for some message types (notably
   `GPS_RAW_INT`, `RC_CHANNELS`).
6. Re-checks the connect lock (another concurrently-probed candidate for the
   same `drone_id` may have already won — see `auto_connector` below) and
   commits: creates the `CommandController`, starts the read loop task, and
   starts a home-point updater task (`MAV_CMD_DO_SET_HOME` every 5 s from
   vessel position in Redis, for ship-launched RTL).

Failure paths (`TimeoutError`, `CancelledError`, generic `Exception`) always
close the socket via `_close_mav()` to avoid leaking bound UDP ports.

### `_read_loop(drone_id)`

Runs continuously while `conn.connected`:
- Offloads `recv_match(blocking=True, timeout=1.0)` + heartbeat send to the
  **same executor thread** (the pymavlink connection object must never be
  touched from two threads concurrently).
- Sends a GCS heartbeat (`MAV_TYPE_GCS`) at ~1 Hz from inside that call.
- On a live HF link, applies `hf_adapter.should_forward()` bandwidth filtering
  before handing the message to `TelemetryProcessor.process()`.
- Auto-disconnects on:
  - **Link timeout** — no message at all for `conn.link_timeout_s` (max of
    heartbeat timeout and steady-state liveness timeout).
  - **10 consecutive read errors.**
- On an unclean exit, inline cleanup removes the connection, HF adapter, and
  broadcaster entry so state never stays stale.

### `disconnect(drone_id)` / simulation entries

`disconnect()` cancels the read/home tasks, closes the socket, and clears
state, HF adapter, and broadcaster. `attach_simulation()` /
`detach_simulation()` register a virtual `DroneConnection` (`transport="simulation"`)
so simulated drones show up identically to real ones in `get_all_connections()`.

### Command dispatch

`send_command(drone_id, command, params)` routes to:
- `mission_simulator` if `transport == "simulation"`;
- otherwise `conn.controller.send(command, params)` (see [§4](#4-command-dispatch-commandcontroller)).

---

## 3. Transports and connection strings

`build_connection_string()` (`utils/mavlink_utils.py`) maps a transport name to
a pymavlink connection string:

| Transport | String | Notes |
|---|---|---|
| `udp` | `udpin:0.0.0.0:{port}` | GCS listens; `host` is ignored — always binds all interfaces so SITL/hardware on any host can reach it |
| `udp_out` | `udpout:{host}:{port}` | GCS sends, drone listens |
| `tcp` | `tcp:{host}:{port}` | Used for `com_bridge` (serial-over-TCP) and ArduPilot SITL |
| `serial` | `{serial_port},{baud_rate}` | Direct USB/serial |
| `sitl` | `tcp:{host}:{port}` | Alias resolving to TCP (`host.docker.internal` reaches the Windows host from inside Docker) |
| `hf_serial` / `hf_tcp` | resolves as `serial`/`tcp` | Same wire connection; the `HFLinkAdapter` layer above changes timeouts and message filtering, not the transport itself |

Default SITL/dev port is `14550` (UDP) or `5760`/`5762` (TCP, ArduPilot SITL).

---

## 4. Command dispatch (`CommandController`)

One `CommandController` per connected drone (spec refs FR-DC-002, FR-DC-006).

**Flow (`send()`):**
1. **Validate** (`_validate`) against current `StateManager` state — e.g.
   `arm` is denied below 20% battery or without a 3D GPS fix (≥6 satellites);
   `takeoff` requires armed + altitude in 1–500 m; `set_mode` checks the
   target mode exists in `mav.mode_mapping()`.
2. **ACK-collision guard** — a second `arm`/`disarm` is denied while one is
   still awaiting `COMMAND_ACK`, since both share the same MAVLink command id
   (`MAV_CMD_COMPONENT_ARM_DISARM`) and can't be told apart once the ACK arrives.
3. **Dispatch** (`_dispatch`, run in executor) encodes to the correct MAVLink
   message:

   | Command | MAVLink encoding |
   |---|---|
   | `arm` / `disarm` | `COMMAND_LONG` → `MAV_CMD_COMPONENT_ARM_DISARM` |
   | `emergency_stop` | `COMMAND_LONG` → `MAV_CMD_DO_FLIGHTTERMINATION` |
   | `takeoff` | `COMMAND_LONG` → `MAV_CMD_NAV_TAKEOFF` |
   | `set_mode` | `SET_MODE` |
   | `rtl` | `SET_MODE` → `RTL` (shortest path) or `SMART_RTL` (follow waypoints back) |
   | `land` | `SET_MODE` → `LAND` |
   | `goto` | `MISSION_ITEM_INT` (`current=2` = guided-mode goto) |
   | `velocity` | `SET_POSITION_TARGET_LOCAL_NED` (velocity mask, NED frame) |

4. **Await ACK** (`_await_ack`, up to `ACK_TIMEOUT_S=5.0`, `MAX_RETRIES=2`):
   commands without a `COMMAND_ACK` (`set_mode`, `rtl`, `land`, `goto`,
   `velocity`) resolve as `ACCEPTED` after a 0.2 s grace period instead
   (mode changes are confirmed via `HEARTBEAT`, not `COMMAND_ACK`).
   `handle_ack()` is invoked by `TelemetryProcessor` when a real
   `COMMAND_ACK` message arrives and resolves the pending `Future`.

Results are one of `CommandResult`: `ACCEPTED`, `DENIED`, `FAILED`,
`TIMEOUT`, `UNSUPPORTED`. Last `HISTORY_LIMIT=200` commands are kept per drone
for the audit log (`get_command_history`).

---

## 5. HF (ship-to-shore) datalink

`hf_link_adapter.py` wraps the same MAVLink connection with HF-appropriate
behavior when `transport` is `hf_serial` or `hf_tcp`. Military HF radio
delivers ~1.2–9.6 kbps in practice, so:

- **Message priority filtering** (`should_forward`) — messages are tiered
  (`CRITICAL`/`HIGH`/`MEDIUM`/`LOW`) and rate-limited per tier:
  - `CRITICAL` (`COMMAND_ACK`): never rate-limited.
  - `HIGH` (position, battery, attitude, `HEARTBEAT`): max 2 Hz.
  - `MEDIUM` (`VFR_HUD`, mission progress): max 0.5 Hz.
  - `LOW` (`STATUSTEXT`, `PARAM_VALUE`, raw IMU, RC channels): blocked entirely on HF.
- **Longer timeouts** — `HF_HEARTBEAT_TIMEOUT_S=45s` and
  `HF_COMMAND_ACK_TIMEOUT_S=8s` vs. 5–10 s for short-range RF, since HF ALE
  (Automatic Link Establishment) re-linking can take 10–30 s.
- **Link state machine** (`tick()`, called every 5 s by `run_tick_loop`):
  `CONNECTED` → `DEGRADED` after `HF_DEGRADED_THRESHOLD_S=20s` of silence
  (drone continues autonomously through an ionospheric blackout) →
  `LOST` after `HF_LOST_THRESHOLD_S=120s` (failsafe applies).
- **SNR/BER reporting** from the modem ALE interface (`update_link_quality`),
  logged when SNR < 5 dB.

`MAVLinkManager` attaches an `HFLinkAdapter` per drone in `connect()` when the
transport is HF, and both the heartbeat-wait timeout and steady-state link
timeout use the HF constants instead of the default 10 s.

---

## 6. Auto-connect (`auto_connector.py`)

A background asyncio task (`run_auto_connector`, started from FastAPI
lifespan) that connects drones automatically as their hardware link appears:

- **Bridge watcher** — polls `com_bridge`'s discovery endpoint
  (`http://host.docker.internal:5761/ports`) every `BRIDGE_POLL_INTERVAL=3s`.
  The moment it transitions "not connected → connected" (cable plugged in),
  triggers an **immediate** connection attempt.
- **Retry loop** — every `RETRY_INTERVAL=15s`, retries any drone that's still
  unconnected (covers a cold-start heartbeat timeout on the first attempt).
- **Candidate probing** — builds an ordered candidate list per cycle: the
  `com_bridge` TCP candidate first (most reliable), then any serial ports
  visible in the container, then a fixed fallback list (`tcp:5762`,
  `tcp:5760`, `udp:14550/14551/14560`). All candidates for a drone are probed
  **concurrently** (`_connect_drone`) and the first to get a real heartbeat
  wins; `MAVLinkManager.connect()`'s own per-`drone_id` lock resolves the race
  so only one candidate actually commits.
- **Failure cooldown** — a fallback candidate (not bridge/serial, which are
  only present when something real was detected) that fails twice
  (`COOLDOWN_AFTER_FAILURES=2`) is skipped for `FAILURE_COOLDOWN_S=120s`,
  since a TCP candidate with nothing listening otherwise floods logs with
  `EOF on TCP socket` every retry cycle.
- End-to-end worst case after plugging in a cable: ~7 s (2 s `com_bridge`
  detection + 3 s bridge-poll + 2 s heartbeat wait).

Removed/maintenance drone instances are never treated as connection
candidates.

---

## 7. MAVLink broadcaster (simulator → external GCS)

Simulated drones exist only as Python state — no real MAVLink packets are
generated for them. `MAVLinkBroadcaster` (`mavlink_broadcaster.py`) fixes
this so external GCS software (Mission Planner, QGroundControl) can connect
to a simulated flight exactly like real hardware:

- One outbound `udpout:{sitl_host}:{mavlink_broadcast_port}` link per
  simulated `drone_id`, tagged with that drone's own MAVLink system id, so a
  single GCS UDP listener shows every simulated drone as a separate vehicle.
- On every `send(drone_id, sys_id, state)` call it encodes and sends
  `HEARTBEAT` (1 Hz), `GLOBAL_POSITION_INT`, `ATTITUDE`, `VFR_HUD`,
  `SYS_STATUS`, `GPS_RAW_INT` from the simulator's state dict. `HOME_POSITION`
  is broadcast alongside each heartbeat so a GCS connecting mid-flight learns
  the current home point.
- Sending is fire-and-forget (UDP) — if nothing is listening, the send costs
  nothing and no "enable" step is required.
- **Bidirectional**: the same `udpout` socket receives whatever the GCS sends
  back. `poll_commands` → `_drain_commands` → `_handle_incoming` decodes
  `COMMAND_LONG`/`COMMAND_INT` (both wire formats for lat/lon — floats in
  param5/param6 vs. 1e7-scaled ints in x/y — are handled), applies
  `MAV_CMD_DO_SET_HOME` and `MAV_CMD_COMPONENT_ARM_DISARM` through a
  per-drone callback registered via `set_command_handler`, and **acks every
  command** with `COMMAND_ACK`/`MAV_RESULT_ACCEPTED` — without this, a GCS
  operator command against a simulated vehicle (e.g. "Set Home Here")
  hangs until the GCS times out.

---

## 8. Threading model (`mavlink_executor.py`)

All blocking pymavlink calls (`mavlink_connection`, `recv_match`,
`heartbeat_send`, broadcast sends) run in a **dedicated**
`ThreadPoolExecutor(max_workers=64, thread_name_prefix="mavlink-io")`,
separate from Python's shared default executor (also used by MinIO/boto3 and
backup/dump paths). At fleet scale, every connected drone's read loop submits
a blocking `recv_match` roughly once per second — sharing the default pool
would add latency/jitter to telemetry unrelated to actual MAVLink I/O being
slow. Sizing (64) covers one thread per connected drone plus headroom for
connect-time and broadcast bursts, well beyond a single GCS instance's
expected fleet size.

---

## 9. Protocol helpers (`utils/mavlink_utils.py`)

Shared, protocol-only helpers used across `drone_control` and `drone_flight`:

- **Flight mode decoding** — `decode_flight_mode(custom_mode, autopilot, vehicle_type)`
  dispatches to `ARDUCOPTER_MODES`, `ARDUPLANE_MODES`, or `PX4_NAV_STATES`
  lookup tables; falls back to `MODE_<n>` for unknown values.
- **GPS** — `decode_gps_fix`, `gps_quality_score(fix_type, satellites, hdop)`
  → 0–100 score for the HUD signal-bar indicator.
- **System status** — `decode_system_status`, `is_armed(base_mode)`,
  `is_custom_mode(base_mode)` (MAVLink `base_mode` bitmask helpers).
- **Link quality** — `rssi_to_percent(rssi)` (0–255 MAVLink scale → 0–100%,
  255 = unknown), `link_quality_label`.
- **Commands** — `decode_mav_result(result)`,
  `build_param_set_message(mav, param_id, value, param_type)` (enforces the
  16-character MAVLink `param_id` limit).
- **Coordinate packing** — `pack_latlon`/`unpack_latlon` (×1e7 int ↔ degrees),
  `pack_altitude`/`unpack_altitude` (mm int ↔ metres).

---

## 10. Data flow summary

```
                     ┌────────────────────┐
   Real drone   ───► │  UDP/TCP/Serial     │
   or SITL          │  (mavutil connection)│
                     └─────────┬───────────┘
                               │ mavlink_executor thread
                               ▼
                     ┌────────────────────┐        ┌──────────────────┐
                     │  _read_loop()       │──────► │ HFLinkAdapter     │ (HF only:
                     │  (MAVLinkManager)    │        │ filter + state    │  filter/timeouts)
                     └─────────┬───────────┘        └──────────────────┘
                               ▼
                     ┌────────────────────┐
                     │ TelemetryProcessor  │──► StateManager ──► WebSocket /api/.../stream/{id}
                     │  (also feeds         │──► HealthMonitor, DataRecorder
                     │   CommandController  │──► CommandController.handle_ack()
                     │   COMMAND_ACK)       │
                     └────────────────────┘

   Operator command (REST) ──► MAVLinkManager.send_command()
                                        │
                                        ▼
                              CommandController.send()
                                (validate → encode → dispatch → await ACK)
                                        │
                                        ▼
                                pymavlink .mav.*_send() (mavlink_executor thread)

   Simulated drone state ──► MissionSimulator ──► MAVLinkBroadcaster.send()
                                                        │ UDP (udpout)
                                                        ▼
                                          External GCS (Mission Planner / QGC)
                                                        │ COMMAND_LONG/INT (set_home, arm)
                                                        ▼
                                          MAVLinkBroadcaster._handle_incoming()
                                                → simulator command_handler + COMMAND_ACK
```

---

## 11. Related tests

- [`test_mavlink_broadcaster.py`](../backend/app/tests/test_mavlink_broadcaster.py)
- [`test_command_controller.py`](../backend/app/tests/test_command_controller.py)
- [`test_health_monitor.py`](../backend/app/tests/test_health_monitor.py)
- [`test_telemetry_endpoints.py`](../backend/app/tests/test_telemetry_endpoints.py)
- [`test_auto_connector.py`](../backend/app/tests/test_auto_connector.py)
- [`test_drone_control_api.py`](../backend/app/tests/test_drone_control_api.py)
