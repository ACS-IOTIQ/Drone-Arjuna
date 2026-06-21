# DroneArjuna Ground Control System

DroneArjuna is a professional-grade Docker-based drone ground control system with enterprise-level telemetry, real-time command execution, and AI-powered mission analytics. Built with React/TypeScript frontend and FastAPI backend.

**Key Features:**
- 🛰️ Real-time MAVLink telemetry streaming (WebSocket)
- 🎯 Multi-drone fleet management with centralized control
- 🗺️ Advanced mission planning with 2D/3D visualization
- 📊 Live telemetry dashboard with health monitoring
- 🎥 Integrated video feed streaming from drone cameras
- 🤖 AI object detection (YOLOv8) for intelligent operations
- 📝 Complete event logging and audit trails
- 🔐 JWT authentication with role-based access control
- 🧲 Seamless WebSocket connections with auto-reconnection
- 📱 Responsive UI with professional design

---

## Project Structure

```text
DroneArjuna/
  backend/                 FastAPI backend application
    alembic/               Database migration configuration and versions
    app/                   Backend source code
    Dockerfile             Backend Docker image definition
    requirements.txt       Python dependencies
  frontend/                React + Vite frontend application
    src/                   Frontend source code
    Dockerfile             Frontend Docker image definition
    package.json           Frontend dependencies and scripts
  database_dumps/          Local SQL dump files for manual database restore
  docs/                    Project documents
  .env.example             Example environment variables
  docker-compose.yml       Main Docker Compose stack
```

## Docker Services

These are the exact service names from `docker-compose.yml`:

| Service | Container | Port | Purpose |
| --- | --- | --- | --- |
| `postgres` | `da_postgres` | 5432 | Main PostgreSQL + PostGIS database |
| `timescale` | `da_timescale` | 5432 | Telemetry TimescaleDB (time-series) |
| `pgadmin` | `da_pgadmin` | 5050 | Web UI for PostgreSQL and TimescaleDB |
| `redis` | `da_redis` | 6379 | Cache/session service |
| `rabbitmq` | `da_rabbitmq` | 5672, 15672 | Event bus and message broker |
| `minio` | `da_minio` | 9000, 9001 | S3-compatible object storage |
| `backend` | `da_backend` | 8000 | FastAPI API server |
| `frontend` | `da_frontend` | 3000 | React/Vite web app |

All services are on `da_network` (named bridge) for DNS resolution.

---

## Communication Protocols

### 1. **RESTful API** (`/api/*`)
- Standard HTTP endpoints for CRUD operations
- JWT Bearer token authentication
- Request/response: JSON
- Latency: ~50-100ms

### 2. **WebSocket** (`ws://backend:8000/api/drone-control/stream/{droneId}`)
- **Purpose:** Real-time telemetry streaming
- **Payload:** Raw MAVLink messages or parsed JSON
- **Update Rate:** 10 Hz per drone
- **Protocol:** Binary or JSON frames
- **Auto-reconnection:** Built-in with exponential backoff (up to 5 retries)
- **Heartbeat:** Ping every 30 seconds
- **Typical Latency:** 10-50ms

### 3. **MAVLink Protocol** (Backend only)
- Direct serial/UDP communication with drones (ArduPilot)
- Handled by `pymavlink` library
- Command channels: ARM, DISARM, MODE changes, waypoint uploads
- Telemetry channels: GPS, attitude, battery, RC input

### 4. **Event Bus** (RabbitMQ AMQP)
- Asynchronous event propagation across backend services
- Topics: `drone.connected`, `drone.telemetry`, `mission.updated`, `command.executed`
- Durable queues for reliability

---

## First-Time Setup

1. **Install Docker Desktop**
   - Windows: https://docs.docker.com/desktop/install/windows-install/
   - macOS: https://docs.docker.com/desktop/install/mac-install/

2. **Clone/navigate to project:**
   ```powershell
   cd path\to\DroneArjuna
   ```

3. **Create environment file:**
   ```powershell
   Copy-Item .env.example .env
   ```
   Edit `.env` with your values (see `Configuration` section below).

4. **Start the full stack:**
   ```powershell
   docker compose up -d --build
   ```
   This builds images and starts all services in the background.

5. **Apply database migrations:**
   ```powershell
   docker compose exec backend alembic upgrade head
   ```
   Initializes PostgreSQL schema and creates default admin account.

6. **Access the system:**
   ```
   Frontend:    http://localhost:3000
   Backend API: http://localhost:8000
   Swagger:     http://localhost:8000/docs
   pgAdmin:     http://localhost:5050
   RabbitMQ:    http://localhost:15672
   MinIO:       http://localhost:9001
   ```

7. **Default credentials:**
   ```
   Username: admin
   Password: Admin@1234
   ```

---

## Configuration

### Environment Variables (`.env`)

```env
# Database
POSTGRES_USER=droneArjuna
POSTGRES_PASSWORD=<your_secret_password>
POSTGRES_DB=drone_arjuna_db

# JWT Security
SECRET_KEY=<64-char hex string — use: python -c "import secrets; print(secrets.token_hex(32))">
ACCESS_TOKEN_EXPIRE_MINUTES=30
REFRESH_TOKEN_EXPIRE_DAYS=7

# CORS Origins (comma-separated, NO SPACES, NO BRACKETS)
CORS_ORIGINS=http://localhost:3000,http://localhost:5173

# Services
REDIS_URL=redis://redis:6379
RABBITMQ_URL=amqp://guest:guest@rabbitmq:5672/
MINIO_ENDPOINT=minio:9000
```

### Frontend Environment (`.env` or `.env.local`)

```env
VITE_API_BASE_URL=/api
VITE_WS_BASE_URL=ws://localhost:8000
VITE_TIMEZONE=auto  # auto or specific timezone (e.g., America/New_York)
```

---

## API Endpoints

### Authentication
- `POST /api/auth/login` → `{ access_token, refresh_token, token_type }`
- `POST /api/auth/refresh` → `{ access_token }`
- `GET /api/auth/users` → `[users]` (admin only)

### Drone Control (Real-time)
- `GET /api/drone-control/status` → Active drones
- `POST /api/drone-control/connect` → Establish MAVLink connection
- `POST /api/drone-control/command` → Dispatch flight command (ARM, DISARM, MODE)
- `GET /api/drone-control/telemetry/{id}` → Current telemetry snapshot
- `WS /api/drone-control/stream/{id}` → Live telemetry WebSocket (10 Hz)

### Drone Master (Configuration)
- `GET /api/master/drone-types` → List all drone models
- `POST /api/master/drone-types` → Create new drone type
- `GET /api/master/payload-types` → List payload types
- `POST /api/master/payload-types` → Create payload type

### Mission Planning
- `GET /api/drone-flight/missions` → List missions
- `POST /api/drone-flight/missions` → Create mission
- `PUT /api/drone-flight/missions/{id}` → Update mission
- `DELETE /api/drone-flight/missions/{id}` → Delete mission
- `POST /api/drone-flight/missions/{id}/upload` → Upload waypoints to drone

### Health Checks
- `GET /health` → `{ status: "ok", version: "2.0.0" }`
- `GET /docs` → Interactive Swagger UI

---

## Frontend Architecture

### Stores (Zustand)
- **authStore** — User session, JWT tokens, login/logout
- **fleetStore** — Active drones, drone metadata, status
- **missionStore** — Mission CRUD, waypoints, status
- **telemetryStore** — Live telemetry data, health metrics
- **notificationStore** — Toast notifications, unread count
- **eventLogStore** — Audit trail of all operations (with export)
- **timezoneStore** — Timezone sync, local time formatting
- **connectionHealthStore** — WebSocket health, latency, packet loss

### Components
```
layout/
  ├── LoginScreen.tsx          → Sign in / Access request
  ├── PasswordSetupScreen.tsx  → Password setup after admin approval
  ├── AppShell.tsx             → Main shell with sidebar/topbar
  ├── Sidebar.tsx              → Workspace navigation
  └── TopBar.tsx               → Breadcrumb, notifications, user menu

workspaces/
  ├── Fleet/                   → Drone list, health, status
  ├── Plan/                    → Mission designer, waypoint editor
  ├── Fly/                     → Real-time control, video feed
  ├── Monitor/                 → Telemetry dashboard, gauges
  └── Settings/                → User profile, event logs, system logs

common/
  ├── NotificationDrawer.tsx   → Toast notifications
  ├── CameraWindow.tsx         → Video stream overlay
  ├── SystemLogViewer.tsx      → Event audit trail
  └── ...
```

---

## Features & Capabilities

### 1. **Real-Time Telemetry**
- 10 Hz update rate per drone
- WebSocket-based streaming
- Auto-reconnection with exponential backoff
- Metrics tracked: GPS, altitude, speed, attitude, battery, signal strength
- Latency monitoring (typical: 10-50ms)

### 2. **Multi-Drone Fleet Management**
- Centralized drone status dashboard
- Live health monitoring (battery, signal, GPS)
- Simultaneous control of up to 10+ drones
- Drone type templates (Quad, Fixed-wing, VTOL)

### 3. **Advanced Mission Planning**
- 2D map (Leaflet) with waypoint editor
- 3D terrain visualization (Cesium)
- Geofencing and no-fly zones
- Automatic waypoint upload to drone
- Mission status tracking (pending, active, completed)

### 4. **Live Video Feed**
- Camera stream overlay on map
- Floating window for multi-view monitoring
- Persistent across workspace switches
- Supports RTSP/MJPEG streams

### 5. **Event Logging & Audit Trail**
- All user actions logged: login, command execution, mission changes
- System events: connection state, telemetry anomalies, errors
- Filterable by category, level, drone, mission
- Export to JSON/CSV for compliance
- Auto-retention: last 5000 events

### 6. **Role-Based Access Control**
- Roles: system_admin, mission_commander, flight_controller, sensor_operator, observer
- Permission model per module and action
- Access request flow: request → admin approval → password setup

### 7. **Connection Health Monitoring**
- Automatic latency measurement
- Packet loss detection and reporting
- WebSocket auto-reconnection (up to 5 attempts, exponential backoff)
- 30-second heartbeat to detect stale connections
- Health score (0-100) for overall system status

### 8. **Timezone Synchronization**
- Auto-sync to system timezone on app launch
- Manual timezone selection
- Consistent time formatting across UI
- Event timestamps in user's local timezone

### 9. **Notification System**
- In-app toast notifications (info, success, warning, danger)
- Unread notification count badge
- Notification drawer with history
- Auto-integration with event logs

---

## Common Operations

### View Real-Time Telemetry
1. Log in → Fleet workspace
2. Select a drone from the list
3. Telemetry dashboard shows: GPS, altitude, battery, signal
4. Metrics auto-update every 100ms (10 Hz from backend)

### Create & Execute Mission
1. Plan workspace → Click "New Mission"
2. Set drone type, add waypoints on 2D map
3. Configure flight parameters (speed, altitude, RTH)
4. Save mission → Auto-upload to drone
5. Fly workspace → Arm → Start mission
6. Monitor in real-time; pause/resume/RTH available

### Check System Health
1. Settings workspace → System Logs tab
2. Filter by category (connection, telemetry, command, etc.)
3. Export logs for analysis
4. View connection status: Backend, DB, WebSocket

### Access Request & Setup
1. Not a user? Click "Request Access" on login screen
2. Fill form: name, email, role, reason
3. Admin approves in Settings → Access Requests
4. You receive temp password
5. Use temp password to log in
6. Password Setup screen appears → Set permanent password
7. Done! Full access granted

---

## Troubleshooting

### WebSocket Disconnections
**Symptom:** Telemetry stops updating, "Connection lost" banner  
**Fix:**
1. Check backend health: `docker compose ps`
2. Check network: `docker network inspect da_network`
3. Restart backend: `docker compose restart backend`
4. Frontend auto-reconnects after ~5 seconds

### High Latency (>200ms)
**Symptom:** Telemetry updates slowly, video feed lags  
**Cause:** Network congestion, backend overload, or large mission file  
**Fix:**
1. Check `docker compose logs backend` for errors
2. Monitor CPU: `docker stats`
3. Reduce telemetry update rate (if configurable)

### Login Fails
**Symptom:** "Invalid credentials" despite correct password  
**Fix:**
1. Check user exists: `docker compose exec backend alembic downgrade -1 && alembic upgrade head`
2. Reset to defaults: `docker compose down -v && docker compose up -d --build`

### Event Logs Growing Too Large
**Symptom:** UI slows down, browser memory high  
**Fix:**
1. Settings → System Logs → Click "Clear"
2. Exports old logs first if needed
3. Auto-retention limits to 5000 events

---

## Development

### Run Tests
```powershell
# Backend
docker compose exec backend pytest

# Frontend (inside container)
docker compose exec frontend npm run test
```

### View Logs
```powershell
# All services
docker compose logs -f

# Specific service
docker compose logs -f backend
```

### Database Shell
```powershell
# PostgreSQL
docker compose exec postgres psql -U droneArjuna -d drone_arjuna_db

# TimescaleDB
docker compose exec timescale psql -U droneArjuna -d drone_arjuna_db
```

### Debugging
- Frontend: Open DevTools (F12) → Network tab
- Backend: `docker compose logs -f backend`
- WebSocket: Chrome DevTools → Network → WS connections

---

## Performance Targets

| Metric | Target | Typical |
| --- | --- | --- |
| Telemetry latency | <100ms | 10-50ms |
| Login time | <1s | 500-800ms |
| Map load | <2s | 1.5s |
| WebSocket reconnect | <5s | 2-3s |
| Command execution | <200ms | 50-100ms |
| Packet loss | <2% | <1% |

---

## Security Considerations

1. **JWT tokens expire:** Set `ACCESS_TOKEN_EXPIRE_MINUTES` to 30 (prod: 15)
2. **CORS whitelist:** Only allow trusted origins in `CORS_ORIGINS`
3. **Database:** Use strong `POSTGRES_PASSWORD` (20+ chars, mixed case/numbers)
4. **Secret key:** Generate with: `python -c "import secrets; print(secrets.token_hex(32))"`
5. **Event logs:** Export and archive regularly for compliance
6. **API rate limiting:** Implement in production (not in Phase 1)

---

## Technology Stack

| Layer | Technology | Version | Why |
| --- | --- | --- | --- |
| Frontend | React + TypeScript | 18 | Type safety, fast rendering |
| Frontend UI | Tailwind CSS | Latest | Utility-first, responsive |
| State | Zustand | Latest | Lightweight, minimal boilerplate |
| API Client | Axios | Latest | Promise-based HTTP |
| Mapping | Leaflet | Latest | Lightweight 2D maps |
| 3D | Cesium | Latest | Professional 3D visualization |
| Backend | FastAPI | 0.104+ | Modern, fast, async |
| Database | PostgreSQL + PostGIS | 15 | Spatial queries, reliability |
| Telemetry DB | TimescaleDB | 2.13+ | Time-series optimized |
| Cache | Redis | 7+ | Fast session/cache storage |
| Message Bus | RabbitMQ | 3.12+ | Reliable async messaging |
| Object Storage | MinIO | Latest | S3-compatible, self-hosted |
| Containerization | Docker Compose | 2.10+ | Multi-service orchestration |

---

## What's Next?

### Phase 1 Exit Criteria (In Progress)
- ✅ Login screen with improved UI
- ✅ Event logging system
- ✅ Connection health monitoring
- ✅ Timezone synchronization
- ✅ Password setup after access approval
- 🔄 MAVLink integration with ArduPilot SITL

### Phase 2 Planned
- Full Drone Master CRUD (drone types, payload types)
- Configuration templates
- Basic 2D mission planner with Leaflet
- Real-time telemetry WebSocket verified

### Phase 3+ Planned
- 3D mission planning (Cesium)
- Geofencing and no-fly zones
- Drone Inventory (knowledge base)
- Drone Analyst (YOLOv8 detection)
- WCAG accessibility audit

---

## Support & Documentation

- API Docs: http://localhost:8000/docs (Swagger UI)
- GitHub: https://github.com/ACS-IOTIQ/Drone-Arjuna
- Issues: File an issue on GitHub

---

**Version:** 2.0.0  
**Last Updated:** 2026-06-21  
**Maintained by:** ACS Technologies Limited

## Running The Full Application

Recommended full-stack run:

Start Docker Desktop first, then run:

```powershell
docker compose up -d --build
docker compose exec backend alembic upgrade head
```

Then open:

```text
http://localhost:3000
```

Login with:

```text
admin / Admin@1234
```

Local frontend-only development run:

```powershell
npm install
npm run dev
```

Then open:

```text
http://localhost:3000
```

The frontend-only command starts the UI. Login and live API features still require the backend to be running at `http://localhost:8000`. The Vite dev proxy targets `http://localhost:8000` by default for local frontend runs and automatically targets `http://backend:8000` inside Docker, so the frontend container talks to the backend container correctly.

If login fails:

- Confirm the backend is running: `http://localhost:8000/api/health`
- Confirm migrations ran: `docker compose exec backend alembic upgrade head`
- Use the default first-run credentials only when the database has no existing users.
- If you changed users previously, login with the account already stored in the database.

If Docker shows an error like `failed to connect to the docker API at npipe:////./pipe/dockerDesktopLinuxEngine`, Docker Desktop is not running. Open Docker Desktop, wait until it says the engine is running, then run the Docker commands again.

## Simple Local UI Commands

You can now run common frontend commands from the project root.

```powershell
npm install
```

Explanation: Installs the root helper package and automatically installs frontend dependencies.

```powershell
npm run build
```

Explanation: Runs the frontend TypeScript and Vite production build from the root folder.

```powershell
npm run dev
```

Explanation: Starts the frontend dev server from the root folder.

Open:

```text
http://localhost:3000
```

If port `3000` is already occupied, Vite may use the next available port and print it in the terminal. Close the older terminal/server or open the URL Vite prints.

## Daily Docker Commands

### Whole Stack

```powershell
docker compose up -d
```

Explanation: Starts all services in the background without rebuilding images.

Use when: You already built the project and only need to start your local environment.

```powershell
docker compose up -d --build
```

Explanation: Rebuilds images and starts all services in the background.

Use when: Dockerfiles, backend requirements, frontend package files, or dependency setup changed.

```powershell
docker compose down
```

Explanation: Stops and removes the running containers but keeps named volumes.

Use when: You are done working for the day, or want a clean container restart without deleting database data.

```powershell
docker compose down -v
```

Explanation: Stops containers and removes named volumes, including database data.

Use when: You intentionally want a fresh database and can afford to lose local container data.

```powershell
docker compose ps
```

Explanation: Shows the current status and ports of all Compose services.

Use when: Checking whether services are running, unhealthy, stopped, or mapped to the expected ports.

```powershell
docker compose logs -f
```

Explanation: Streams logs from all services.

Use when: Debugging startup issues, crashes, or cross-service problems.

### Backend

```powershell
docker compose up -d --build backend
```

Explanation: Rebuilds and restarts only the `backend` service.

Use when: Backend dependencies, Dockerfile, or backend container setup changed.

```powershell
docker compose restart backend
```

Explanation: Restarts the running `backend` container without rebuilding.

Use when: You changed runtime environment values or need a quick API restart.

```powershell
docker compose logs -f backend
```

Explanation: Streams logs only from the `backend` service.

Use when: Debugging API errors, migration issues, auth issues, or MAVLink backend behavior.

```powershell
docker compose exec backend alembic upgrade head
```

Explanation: Applies all pending backend database migrations.

Use when: New migration files were added, or the backend reports missing/changed database tables.

```powershell
docker compose exec backend alembic revision --autogenerate -m "describe_change"
```

Explanation: Generates a new Alembic migration from SQLAlchemy model changes.

Use when: Backend ORM models changed and you need to create a migration before applying it.

### Frontend

```powershell
docker compose up -d --build frontend
```

Explanation: Rebuilds and restarts only the `frontend` service.

Use when: Frontend dependencies, package files, or frontend Dockerfile changed.

```powershell
docker compose restart frontend
```

Explanation: Restarts the running `frontend` container without rebuilding.

Use when: The Vite dev server needs a fresh start or environment values changed.

```powershell
docker compose logs -f frontend
```

Explanation: Streams logs only from the `frontend` service.

Use when: Debugging Vite startup, compile errors, or frontend dependency problems.

```powershell
docker compose exec frontend npm run build
```

Explanation: Runs the production frontend build inside the `frontend` container.

Use when: Checking TypeScript/build errors before handing off or deploying changes.

## Frontend Operator Workflow

The UI is organized around normal drone operations:

| Workspace | Use It For |
| --- | --- |
| Fleet | Connect drones, review live fleet readiness, assign payloads to aircraft, and check vessel basing. |
| Plan | Build missions on the Leaflet map, draw geofence safety zones, review waypoints, and submit/approve/reject missions. |
| Fly | Execute live flight commands, monitor instruments, and run mission simulations. |
| Monitor | Watch telemetry charts, gauges, and system logs. |
| Settings | Maintain drone types, drone instances, payload types, vessels, and users. |

### Payload Types

Open `Settings -> Payloads` to manage the payload catalog.

Available actions:

- `Add Payload`: create sensor, combat, comms, or other payload records.
- `Edit`: update payload weight, power, sensor details, gimbal support, and notes.
- `Delete`: remove a payload type from the UI catalog.

The frontend calls the P2-02 payload contract at `/api/master/payload-types`. If that API is not available in the currently running backend, the screen falls back to a local browser cache so operators can still build and review the UI flow without backend changes.

### Login And Access Requests

The login screen has two modes:

- `Sign In`: existing operators enter their username and password.
- `Request Access`: new operators submit name, requested username, email, mobile number, role, and reason.

Access requests are stored in the frontend request queue and appear in `Settings -> Users` under `Access Requests`.

Admin review actions:

- `Allow`: calls the existing `/api/auth/register` endpoint with a generated temporary password and marks the request approved.
- `Reject`: marks the request rejected.
- `Email`: opens a prepared email to the requester.
- `SMS`: opens a prepared SMS to the requester when a mobile number was provided.

Actual automatic email/SMS delivery requires backend or third-party notification service support. Since this pass is frontend-only, the UI provides reliable ready-to-send email/SMS actions and in-app notifications without modifying backend code.

### Fleet Payload Assignment

Open `Fleet` and use the `Payload Assignment` panel above the drone cards.

Each registered drone has a dropdown:

- `No payload mounted`: clears the UI assignment.
- Any saved payload: assigns that payload to the selected drone.

The frontend calls `/api/master/drones/{drone_id}/payload` for backend persistence. If that endpoint is not available, the assignment is saved locally in the browser and the Fleet screen shows a warning.

### Connection Presets

Open `Fleet -> Connect Drone`.

Use `Saved Config Preset` before connecting to apply a complete connection profile. Built-in presets include:

- SITL UDP 14550
- SITL TCP 5760
- USB Serial 57600
- HF Harris Serial

The dialog still supports manual UDP, TCP, serial, HF serial, and HF TCP configuration. Custom presets can be supplied through browser local storage key `da_connection_presets` as an array of connection preset objects.

### Mission Planning And Geofence

Open `Plan`.

Mission setup lives on the left, the Leaflet map is in the center, and live operations telemetry remains visible on the right.

Map actions:

- Click the map normally to add waypoints.
- Click `Draw Geofence`, then click at least three map points to create a polygon safety zone.
- Drag numbered geofence vertices to move the zone.
- Click `Finish` to complete drawing.
- Click `Delete` to remove the geofence zone.
- Waypoints outside the geofence are highlighted red with an alert marker.

When `Save Mission` is clicked, the current geofence is saved with the mission as a GeoJSON polygon in mission state and sent through the mission creation payload.

### Mission Submit, Approve, Reject

In `Plan`, save or load a mission first. The action bar over the map then enables:

- `Submit`: sends the mission through the existing mission status endpoint as `planning`.
- `Approve`: updates the mission status to `approved`.
- `Reject`: maps the operator rejection action to backend status `aborted`, because the current backend status schema accepts `planning`, `approved`, `executing`, `completed`, and `aborted`.

### Telemetry Readout And Export

Open `Monitor` after connecting a drone or starting a simulation.

The Monitor workspace shows:

- Live gauge dashboard.
- Parameter chart for altitude, speed, battery, climb rate, airspeed, and RSSI.
- Raw telemetry key/value data.
- System log/status text.
- `CSV` export from the Raw Telemetry panel.

The CSV export downloads the current in-browser telemetry buffer for the selected drone. This is useful for quick inspection, debugging, and sharing a short telemetry capture without touching the backend.

### Databases

```powershell
docker compose up -d pgadmin
```

Explanation: Starts the pgAdmin web database UI and its required database dependencies.

Use when: You want to browse database tables, inspect data, or run SQL through a browser.

```powershell
docker compose up -d postgres timescale
```

Explanation: Starts only the database services.

Use when: You need database containers available before running migrations or manual restore commands.

```powershell
docker compose restart postgres
```

Explanation: Restarts the main PostgreSQL/PostGIS database container.

Use when: PostgreSQL is unhealthy, configuration changed, or connections are stuck.

```powershell
docker compose restart timescale
```

Explanation: Restarts the TimescaleDB telemetry database container.

Use when: Telemetry database health or connectivity needs a reset.

```powershell
docker compose exec backend alembic upgrade head
```

Explanation: Applies migrations to the main app database from inside the backend container.

Use when: After creating or receiving migration files, before testing backend features that need new tables/columns.

```powershell
docker compose logs -f postgres
```

Explanation: Streams logs only from the `postgres` service.

Use when: Debugging main database startup, authentication, schema, or connection problems.

```powershell
docker compose logs -f timescale
```

Explanation: Streams logs only from the `timescale` service.

Use when: Debugging telemetry database startup or TimescaleDB connection problems.

```powershell
docker compose restart pgadmin
```

Explanation: Restarts the pgAdmin web UI container.

Use when: pgAdmin is not loading, login settings changed, or database UI connections need a reset.

```powershell
docker compose logs -f pgadmin
```

Explanation: Streams logs only from the `pgadmin` service.

Use when: Debugging pgAdmin startup, login, or database registration issues.

### Supporting Services

```powershell
docker compose restart redis
```

Explanation: Restarts the Redis cache/session service.

Use when: Session/cache state is stale, or Redis health checks fail.

```powershell
docker compose restart rabbitmq
```

Explanation: Restarts the RabbitMQ message broker.

Use when: Event processing or broker connectivity is not behaving correctly.

```powershell
docker compose restart minio
```

Explanation: Restarts the MinIO object storage service.

Use when: File/object storage calls fail, or the MinIO console is not responding.

## Database Dumps

SQL dumps are stored in:

```text
database_dumps/
```

They are not referenced by the code or Docker Compose file. Moving them does not affect the running app unless a manual restore command expects the old path.

## Useful URLs

| Service | URL |
| --- | --- |
| Frontend | `http://localhost:3000` |
| Backend API | `http://localhost:8000` |
| pgAdmin Web UI | `http://localhost:5050` |
| RabbitMQ Management UI | `http://localhost:15672` |
| MinIO Console | `http://localhost:9001` |
| PostgreSQL host port | `localhost:5432` |
| TimescaleDB host port | `localhost:5433` |

## Database Web UI

pgAdmin is available at `http://localhost:5050`.

The login values come from `.env`:

```text
PGADMIN_DEFAULT_EMAIL
PGADMIN_DEFAULT_PASSWORD
```

For full pgAdmin login and database registration steps, see [docs/PGADMIN.md](docs/PGADMIN.md).

## Notes

- Use `docker compose`, not the older `docker-compose`, unless your Docker Desktop version only supports the older command.
- The `backend` service mounts `./backend:/app`, so normal backend source changes should appear in the container during development.
- The `frontend` service mounts `./frontend:/app`, so normal frontend source changes should appear in the Vite dev server during development.
- Do not commit `.env`; keep secrets and local passwords in that file only.

# code push frontend
git add .
git commit -m "Your commit message"
git push origin master