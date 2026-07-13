DROP VIEW IF EXISTS telemetry_gauges CASCADE;

CREATE TABLE IF NOT EXISTS telemetry_gauges (
    recorded_at TIMESTAMPTZ NOT NULL,
    drone_id INTEGER NOT NULL,
    battery_pct INTEGER NOT NULL DEFAULT -1,
    altitude_m DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    ground_speed_ms DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    gps_satellites INTEGER NOT NULL DEFAULT 0,
    rssi INTEGER NOT NULL DEFAULT 0,
    cpu_load_pct DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    PRIMARY KEY (recorded_at, drone_id)
);

CREATE INDEX IF NOT EXISTS ix_telemetry_gauges_drone_time
    ON telemetry_gauges (drone_id, recorded_at);

SELECT create_hypertable(
    'telemetry_gauges',
    'recorded_at',
    if_not_exists => TRUE,
    migrate_data => TRUE
);

INSERT INTO telemetry_gauges (
    recorded_at,
    drone_id,
    battery_pct,
    altitude_m,
    ground_speed_ms,
    gps_satellites,
    rssi,
    cpu_load_pct
)
SELECT
    recorded_at,
    drone_id,
    battery_remaining_pct,
    alt_agl,
    groundspeed_ms,
    gps_satellites,
    rssi,
    cpu_load_pct
FROM telemetry
ON CONFLICT (recorded_at, drone_id) DO NOTHING;

SELECT add_retention_policy(
    'telemetry_gauges',
    INTERVAL '30 days',
    if_not_exists => TRUE
);
