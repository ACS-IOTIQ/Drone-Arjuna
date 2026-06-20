# DroneArjuna

DroneArjuna is a Docker-based drone ground control system project. It includes a FastAPI backend, a React/Vite frontend, PostgreSQL with PostGIS for the main relational database, TimescaleDB for telemetry time-series data, Redis for cache/session storage, RabbitMQ for event messaging, and MinIO for object storage.

This README is a setup and day-to-day operations guide for running the project with Docker Desktop.

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

| Service | Container | Purpose |
| --- | --- | --- |
| `postgres` | `da_postgres` | Main PostgreSQL + PostGIS database |
| `timescale` | `da_timescale` | Telemetry TimescaleDB database |
| `pgadmin` | `da_pgadmin` | Web UI for PostgreSQL and TimescaleDB |
| `redis` | `da_redis` | Cache/session service |
| `rabbitmq` | `da_rabbitmq` | Event bus and message broker |
| `minio` | `da_minio` | S3-compatible object storage |
| `backend` | `da_backend` | FastAPI API server |
| `frontend` | `da_frontend` | React/Vite web app |

## First-Time Setup

1. Install and start Docker Desktop.

2. Open a terminal in the project root:

```powershell
cd path\to\DroneArjuna
```

3. Create your local environment file:

```powershell
Copy-Item .env.example .env
```

Explanation: Creates the `.env` file used by Docker Compose.

Use when: Setting up the project for the first time, or recreating a missing local `.env`.

4. Start the full stack:

```powershell
docker compose up -d --build
```

Explanation: Builds images and starts every service in the background.

Use when: Running the project for the first time, or after Dockerfiles/dependencies changed.

5. Apply backend database migrations:

```powershell
docker compose exec backend alembic upgrade head
```

Explanation: Runs all pending Alembic migrations against the main PostgreSQL database.

Use when: First setup is complete, or after pulling/applying backend model or migration changes.

6. Open the apps:

```text
Frontend: http://localhost:3000
Backend API: http://localhost:8000
pgAdmin UI: http://localhost:5050
RabbitMQ UI: http://localhost:15672
MinIO UI: http://localhost:9001
```

7. Sign in to the frontend:

```text
Username: admin
Password: Admin@1234
```

Explanation: On first backend startup, the API creates this default admin account if the users table is empty.

Use when: Logging in to a fresh local database for the first time.

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
