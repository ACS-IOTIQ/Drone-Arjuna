# pgAdmin Web Database UI

pgAdmin is included in Docker Compose as a browser-based interface for viewing and managing the project databases.

## Start pgAdmin

From the project root, run:

```powershell
docker compose up -d pgadmin
```

Explanation: Starts the `pgadmin` service and its required database dependencies.

Use when: You want to inspect tables, run SQL queries, or browse database data from a web UI.

## Open pgAdmin

Open this URL in your browser:

```text
http://localhost:5050
```

## Log In

Use the values from your `.env` file:

```text
Email: PGADMIN_DEFAULT_EMAIL
Password: PGADMIN_DEFAULT_PASSWORD
```

The default example values from `.env.example` are:

```text
Email: admin@dronearjuna.com
Password: changeme
```

For real work, change `PGADMIN_DEFAULT_PASSWORD` in `.env` before sharing or deploying this setup.

## Register the Main PostgreSQL Database

1. Right-click `Servers`.
2. Select `Register` > `Server`.
3. In the `General` tab, set:

```text
Name: DroneArjuna PostgreSQL
```

4. In the `Connection` tab, set:

```text
Host name/address: postgres
Port: 5432
Maintenance database: dronearjuna
Username: da_admin
Password: your POSTGRES_PASSWORD value from .env
```

5. Enable `Save password`.
6. Click `Save`.

Use this connection when you want to inspect the main application database used by the `backend` service.

## Register the TimescaleDB Telemetry Database

1. Right-click `Servers`.
2. Select `Register` > `Server`.
3. In the `General` tab, set:

```text
Name: DroneArjuna TimescaleDB
```

4. In the `Connection` tab, set:

```text
Host name/address: timescale
Port: 5432
Maintenance database: da_telemetry
Username: da_admin
Password: your POSTGRES_PASSWORD value from .env
```

5. Enable `Save password`.
6. Click `Save`.

Use this connection when you want to inspect telemetry/time-series data.

## Important Connection Notes

- Use `postgres` as the host inside pgAdmin for the main PostgreSQL database.
- Use `timescale` as the host inside pgAdmin for the telemetry database.
- Use port `5432` inside pgAdmin for both database connections.
- Do not use `localhost` inside pgAdmin for these database connections, because pgAdmin is running inside Docker.
- From your host machine, PostgreSQL is exposed on `localhost:5432` and TimescaleDB is exposed on `localhost:5433`.

## Useful pgAdmin Commands

```powershell
docker compose up -d pgadmin
```

Explanation: Starts pgAdmin.

Use when: You only need the database web UI and its dependent database containers.

```powershell
docker compose restart pgadmin
```

Explanation: Restarts the pgAdmin container.

Use when: pgAdmin is not loading, login settings changed, or the UI needs a clean restart.

```powershell
docker compose logs -f pgadmin
```

Explanation: Streams pgAdmin logs.

Use when: Debugging login, startup, or connection issues.
