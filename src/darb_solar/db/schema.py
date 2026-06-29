"""DDL for the FusionSolar SQLite schema."""

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS plants (
    plant_code TEXT PRIMARY KEY,
    plant_name TEXT NOT NULL,
    timezone TEXT NOT NULL DEFAULT 'Africa/Casablanca'
);

CREATE TABLE IF NOT EXISTS devices (
    dev_id TEXT PRIMARY KEY,
    plant_code TEXT NOT NULL REFERENCES plants(plant_code),
    dev_dn TEXT NOT NULL,
    dev_type_id INTEGER NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('inverter', 'meter'))
);

CREATE INDEX IF NOT EXISTS idx_devices_plant_code ON devices(plant_code);

CREATE TABLE IF NOT EXISTS device_power_readings (
    dev_id TEXT NOT NULL REFERENCES devices(dev_id),
    collected_at TEXT NOT NULL,
    active_power_kw REAL NOT NULL,
    synced_at TEXT NOT NULL,
    PRIMARY KEY (dev_id, collected_at)
);

CREATE INDEX IF NOT EXISTS idx_device_power_readings_collected_at
    ON device_power_readings(collected_at);

CREATE TABLE IF NOT EXISTS plant_power_readings (
    plant_code TEXT NOT NULL REFERENCES plants(plant_code),
    collected_at TEXT NOT NULL,
    pv_production_kw REAL NOT NULL,
    grid_export_kw REAL NOT NULL,
    consumption_kw REAL NOT NULL,
    synced_at TEXT NOT NULL,
    PRIMARY KEY (plant_code, collected_at)
);

CREATE INDEX IF NOT EXISTS idx_plant_power_readings_collected_at
    ON plant_power_readings(collected_at);

CREATE TABLE IF NOT EXISTS sync_windows (
    dev_id TEXT NOT NULL REFERENCES devices(dev_id),
    window_start TEXT NOT NULL,
    window_end TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('pending', 'done', 'failed')),
    error_message TEXT,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (dev_id, window_start)
);

CREATE INDEX IF NOT EXISTS idx_sync_windows_status ON sync_windows(status);
"""
