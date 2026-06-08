# DroneArjuna (DA) — Claude Code Context

## Project Identity

**DroneArjuna** is a military-grade Ground Control System (GCS) for heterogeneous drone fleets.
The name fuses "Drone" with "Arjuna" from the Mahabharata — evoking precision, battlefield
awareness, and mastery — while intentionally echoing Dronacharya. Built by ACS Technologies
Limited. Classified **RESTRICTED / CONFIDENTIAL**.

**Design philosophy:** Decisively superior UI/UX to QGroundControl. Operational depth with
battlefield ergonomics. Every design decision should reflect that standard.

---

## Architecture

**Pattern:** Microservices-Oriented Modular Monolith  
**V2 Stack:** React/TypeScript frontend + Python/FastAPI backend, fully containerised via Docker Compose.

### Five Spec-Defined Modules
| Module | Purpose |
|--------|---------|
| Drone Control | MAVLink flight control, real-time telemetry, multi-drone management |
| Drone Master | Master data — drone types, payload types, configuration templates |
| Drone Inventory | Knowledge base / encyclopedia of drones, payloads, threat systems |
| Drone Flight | Mission planning, 2D/3D visualisation, geofencing, multi-drone ops |
| Drone Analyst | AI/CV pipeline — YOLOv8 object detection, change detection, reports |

### Component Layers
```
Presentation  →  React 18 + TypeScript + Tailwind CSS + Zustand
Application   →  FastAPI (Python 3.11) + uvloop + AsyncIO
Data          →  PostgreSQL+PostGIS | TimescaleDB | Redis | RabbitMQ | MinIO
Integration   →  pymavlink | RabbitMQ AMQP | WebSockets
Infrastructure → Docker Compose + da_network (named bridge)
```

---

## Current State

| Phase | Status | Description |
|-------|--------|-------------|
| Phase 0 | ✅ COMPLETE | V2 scaffold, Docker Compose stack, all containers healthy, login screen live |
| Phase 1 | 🔄 IN PROGRESS | JWT auth flow debugging complete; moving to MAVLink connection manager |
| Phase 2 | ⏳ PENDING | Drone Master CRUD + mission planning UI |
| Phase 3 | ⏳ PENDING | Drone Flight — Leaflet 2D map, Cesium 3D, geofencing |
| Phase 4 | ⏳ PENDING | Drone Inventory — knowledge base UI, full-text search |
| Phase 5 | ⏳ PENDING | Drone Analyst — CV pipeline, YOLOv8, detection UI |
| Phase 6 | ⏳ PENDING | Hardening, security audit, WCAG, superior UX polish |

**Phase 1 exit criteria (must pass before Phase 2):**
- MAVLink comms working with ArduPilot SITL simulator
- Drone Master CRUD operational (drone types, payload types)
- JWT auth flow fully verified end-to-end

---

## Project Structure

```
DroneArjuna/
├── CLAUDE.md                        ← you are here
├── docker-compose.yml
├── .env                             ← NOT in Git; see .env.example
├── .env.example
│
├── backend/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── alembic.ini
│   ├── alembic/versions/
│   └── app/
│       ├── __init__.py              ← MUST EXIST (DEF-01)
│       ├── main.py                  ← FastAPI entry point
│       ├── config.py                ← pydantic-settings (see DEF-04)
│       ├── database.py              ← DB engine + session (note spelling, see DEF-02)
│       ├── dependencies.py
│       ├── models/
│       │   ├── __init__.py
│       │   ├── user.py
│       │   ├── drone.py
│       │   ├── payload.py
│       │   ├── mission.py
│       │   └── telemetry.py
│       ├── schemas/
│       │   └── (mirrors models/)
│       ├── modules/
│       │   ├── drone_control/
│       │   │   ├── __init__.py
│       │   │   ├── router.py
│       │   │   ├── mavlink_manager.py
│       │   │   ├── telemetry_processor.py
│       │   │   ├── command_controller.py
│       │   │   ├── state_manager.py
│       │   │   ├── health_monitor.py
│       │   │   └── data_recorder.py  ← see DEF-09 (structlog shadow)
│       │   ├── drone_master/
│       │   ├── drone_inventory/
│       │   ├── drone_flight/
│       │   │   ├── mission_planner.py
│       │   │   └── geo_service.py
│       │   └── drone_analyst/
│       └── core/
│           ├── auth.py
│           ├── security.py
│           ├── rbac.py
│           └── events.py
│
└── frontend/
    ├── Dockerfile
    ├── package.json
    ├── vite.config.ts               ← see DEF-07, DEF-08
    ├── tailwind.config.js
    └── src/
        ├── main.tsx
        ├── App.tsx
        ├── stores/                  ← Zustand stores (auth, drone, mission, etc.)
        ├── api/
        │   ├── client.ts            ← axios with relative URLs (DEF-08)
        │   └── auth.ts              ← must import { api } from './client' (past fix)
        └── components/
            ├── layout/
            │   └── LoginScreen.tsx
            └── workspace/
                ├── FleetWorkspace.tsx
                ├── PlanWorkspace.tsx
                ├── FlyWorkspace.tsx
                ├── MonitorWorkspace.tsx
                └── SettingsWorkspace.tsx
```

---

## ⚠️ Phase 0 Build Lessons — NEVER Repeat These

These were hard-won during the V2 bring-up. Treat as inviolable rules.

### DEF-01 — Missing `__init__.py`
Every directory under `app/` **must** have an `__init__.py` file.  
Missing one causes silent import failures that are painful to diagnose.  
**Rule:** When creating any new Python package directory, add `__init__.py` immediately.

### DEF-02 — Filename spelling
The database module is `database.py` — NOT `databse.py`.  
**Rule:** Double-check filenames before saving; Python won't warn you until runtime.

### DEF-03 — PostgreSQL healthcheck DB name
The `docker-compose.yml` healthcheck must reference `$POSTGRES_DB`, not the default `postgres`.
```yaml
healthcheck:
  test: ["CMD-SHELL", "pg_isready -U $POSTGRES_USER -d $POSTGRES_DB"]
```
Using `postgres` causes the `db` container to show `(unhealthy)` and blocks dependent services.

### DEF-04 — pydantic-settings cannot parse `list[str]` from `.env` on Windows
**Wrong:** `CORS_ORIGINS=["http://localhost:5173"]`  
**Correct:** `CORS_ORIGINS=http://localhost:5173,http://localhost:3000`

In `config.py`, use a `@property` converter:
```python
cors_origins_str: str = "http://localhost:5173"

@property
def cors_origins(self) -> list[str]:
    return [s.strip() for s in self.cors_origins_str.split(",")]
```

### DEF-05 — Pin bcrypt for passlib compatibility
```
bcrypt==4.0.1
```
Later bcrypt versions remove `__about__` which passlib depends on.  
This causes `AttributeError: module 'bcrypt' has no attribute '__about__'` on every login attempt.  
**Rule:** Do not upgrade bcrypt without testing auth end-to-end first.

### DEF-06 — Docker containers require explicit named bridge network
All services must be attached to `da_network`. Without it, inter-container DNS (`db`, `redis`, `rabbitmq`) fails inconsistently on Docker Desktop for Windows.
```yaml
networks:
  da_network:
    driver: bridge

services:
  backend:
    networks:
      - da_network
  # ... every service needs this
```

### DEF-07 — Vite must bind to 0.0.0.0 inside Docker on Windows
Default Vite binds to `127.0.0.1` (container loopback). Host can't reach it.  
`vite.config.ts` must have:
```typescript
server: {
  host: '0.0.0.0',
  allowedHosts: 'all',
  usePolling: true,   // required for Windows volume mount hot reload
  port: 3000,
}
```

### DEF-08 — Use relative URLs through Vite proxy — never direct backend URLs
**Wrong:** `axios.get('http://localhost:8000/api/drone-control/status')`  
**Correct:** `axios.get('/api/drone-control/status')`

Direct backend URLs from the browser trigger CORS errors. All API calls must go through the Vite proxy. The proxy config in `vite.config.ts`:
```typescript
proxy: {
  '/api': {
    target: 'http://backend:8000',
    changeOrigin: true,
  }
}
```

### DEF-09 — Shadowed imports cause UnboundLocalError at runtime
In `data_recorder.py` (and any file), never name a local variable the same as a module-level import.
```python
# WRONG — local 'structlog' shadows the import
import structlog
def record():
    structlog = get_logger()   # ← shadows the import; UnboundLocalError

# CORRECT
import structlog
def record():
    logger = structlog.get_logger()
```
**Rule:** If you see `UnboundLocalError: local variable 'X' referenced before assignment`, check for import shadowing first.

### DEF-10 — Docker port mapping: check docker-compose.yml
Always verify the host port in `docker-compose.yml` — never assume internal == external.  
**Current mapping:** frontend internal `3000` → host `3000`. Use http://localhost:3000.  
The CORS_ORIGINS env var must match the actual host port used in the browser.

---

## Environment Variables (`.env`)

Key variables — see `.env.example` for full list:
```env
# Database
POSTGRES_USER=droneArjuna
POSTGRES_PASSWORD=<secret>
POSTGRES_DB=drone_arjuna_db      ← must match healthcheck

# JWT
SECRET_KEY=<64-char hex string>
ACCESS_TOKEN_EXPIRE_MINUTES=30
REFRESH_TOKEN_EXPIRE_DAYS=7

# CORS — comma-separated, no spaces, no brackets (DEF-04)
CORS_ORIGINS=http://localhost:5173,http://localhost:3000

# Services
REDIS_URL=redis://redis:6379
RABBITMQ_URL=amqp://guest:guest@rabbitmq:5672/
MINIO_ENDPOINT=minio:9000
```

---

## Docker Compose — Key Facts

| Service | Internal Port | Host Port | Health |
|---------|--------------|-----------|--------|
| backend (FastAPI) | 8000 | 8000 | GET /health → 200 |
| frontend (Vite) | 3000 | 3000 | browser opens 3000 |
| db (PostgreSQL+PostGIS+TimescaleDB) | 5432 | 5432 | pg_isready |
| redis | 6379 | 6379 | redis-cli ping |
| rabbitmq | 5672 / 15672 | 5672 / 15672 | management UI on 15672 |
| minio | 9000 / 9001 | 9000 / 9001 | |

**Network:** All services on `da_network` bridge.  
**Volumes:** postgres-data, redis-data, rabbitmq-data, minio-data (all named volumes).

---

## PowerShell Command Equivalents

This project runs on **Windows with PowerShell**. Standard Unix commands are unavailable.

| Unix | PowerShell equivalent |
|------|-----------------------|
| `tail -n 50 file` | `Get-Content file -Tail 50` |
| `docker logs x \| tail -50` | `docker compose logs backend \| Select-Object -Last 50` |
| `grep "ERROR" file` | `Select-String "ERROR" file` or `findstr "ERROR" file` |
| `docker logs x \| grep Y` | `docker compose logs backend \| findstr "Y"` |
| `head -n 10` | `Select-Object -First 10` |
| `cat file` | `Get-Content file` |
| `ls -la` | `Get-ChildItem -Force` |
| `rm -rf dir` | `Remove-Item -Recurse -Force dir` |
| `touch file` | `New-Item file -ItemType File` |
| `export VAR=val` | `$env:VAR = "val"` |

---

## Common Dev Commands

```powershell
# Start everything
docker compose up -d

# Start with fresh build
docker compose up -d --build

# View backend logs (last 50 lines)
docker compose logs backend | Select-Object -Last 50

# Follow backend logs live
docker compose logs -f backend

# Restart one service
docker compose restart backend

# Run Alembic migrations
docker compose exec backend alembic upgrade head

# Open backend Python shell
docker compose exec backend python

# Check all container health
docker compose ps

# Nuke everything and start clean (WARNING: destroys volumes)
docker compose down -v

# Run pytest inside backend container
docker compose exec backend pytest

# Check network
docker network inspect da_network
```

---

## API Endpoints — Phase 1 Implemented

```
GET  /health                              → {status: ok, version: 2.0.0}
GET  /docs                                → Swagger UI (all 5 modules registered)

POST /api/auth/login                      → {access_token, refresh_token, token_type}
POST /api/auth/refresh                    → {access_token}
GET  /api/auth/users                      → [users] (admin only)

GET  /api/drone-control/status            → active drones (requires Bearer token)
POST /api/drone-control/connect           → establish MAVLink connection
POST /api/drone-control/command           → dispatch flight command
GET  /api/drone-control/telemetry/{id}    → current telemetry snapshot
WS   /api/drone-control/stream/{id}       → live telemetry WebSocket

GET  /api/master/drone-types              → list drone types (requires Bearer token)
POST /api/master/drone-types              → create drone type
```

---

## RBAC Roles

| Role | Modules | Capabilities |
|------|---------|-------------|
| system_admin | All | Full CRUD, user management, system config |
| mission_commander | Control, Flight, Analyst | Mission create/execute, read Inventory/Master |
| flight_controller | Control, Flight | Real-time control, command dispatch, telemetry |
| sensor_operator | Flight, Analyst | Payload control, video feeds, target designation |
| intelligence_analyst | Analyst, Inventory | Analysis review, reports, knowledge base |
| maintenance | Master, Inventory | Read-only status, maintenance log write |
| observer | Flight (view only) | Situational awareness, no control |

---

## Technology Choices — Rationale Summary

- **uvloop** over default asyncio — critical for telemetry throughput at 10 Hz per drone
- **pymavlink** over mavsdk-python — lower level, more control for multi-drone async patterns
- **TimescaleDB** over InfluxDB — same PostgreSQL connection, SQL interface, hypertables
- **RabbitMQ** over Kafka — right-sized for current scale; Redis Streams as failover
- **Zustand** over Redux — minimal boilerplate; per-module stores map cleanly to 5 modules
- **Vite** over CRA — fast HMR; required polling config for Windows Docker volumes
- **bcrypt==4.0.1** pinned — passlib compatibility (never upgrade without auth regression test)

---

## Working Style Preferences

- **One file per task** — do not combine multiple file edits into a single response
- **Show exact commands** — always use PowerShell-compatible syntax
- **Errors first** — when debugging, read logs before proposing fixes
- **Confirm before destructive ops** — always ask before `docker compose down -v` or file deletion
- **Iterative fixes** — one fix at a time; verify it works before moving to the next
- **Exact error messages matter** — always read the full stack trace, not just the last line

---

## Key Reference Documents

The following documents exist in the project SharePoint and define the authoritative spec.
Ask the developer to paste relevant sections if you need specification details:

| Document | ID | Purpose |
|----------|----|---------|
| System Requirements Specification | DA-SRS-001 | Authoritative requirements for all 5 modules |
| Detailed Design Document | DA-DDD-001 | Architecture, API specs, data models, security design |
| Project Management Plan | DA-PMP-001 | Phase definitions, timeline, team structure |
| Configuration Management Plan | DA-CMP-001 | Git branching strategy, CI/CD, versioning scheme |
| Risk Register | DA-RR-001 | 12 active risks including R-DA-05 (MAVLink integration) |
| Software Test Description | DA-STD-001 | 46 test cases across 6 test groups for Phase 0/1 |
| Software Test Report v1 | DA-STR-001 | Phase 0/1 test results — all 46 TCs passed |

---

## What's Next (Phase 1 → Phase 2 Transition)

Before Phase 2 begins, complete:
1. Automated pytest suite for auth module committed to Git
2. ArduPilot SITL environment configured and verified
3. Phase 1 Build Baseline tagged as `v1.0.0` in Git
4. DA-STD-001 and DA-STR-001 baselined

Phase 2 target deliverables:
- Full CRUD for drone types and payload types (Drone Master)
- Configuration templates
- Basic 2D mission planner with Leaflet.js
- Real-time telemetry WebSocket verified with SITL
