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
