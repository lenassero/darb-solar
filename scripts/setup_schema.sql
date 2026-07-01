-- Application tables for darb-solar.
-- Run against the darb_solar database after setup_native_postgres.sql.

CREATE TABLE plants (
    plant_code TEXT PRIMARY KEY,
    plant_name TEXT NOT NULL,
    timezone TEXT NOT NULL DEFAULT 'Africa/Casablanca'
);

CREATE TABLE devices (
    dev_id TEXT PRIMARY KEY,
    plant_code TEXT NOT NULL REFERENCES plants(plant_code),
    dev_dn TEXT NOT NULL,
    dev_type_id INTEGER NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('inverter', 'meter'))
);

CREATE INDEX idx_devices_plant_code ON devices(plant_code);

CREATE TABLE device_power_readings (
    dev_id TEXT NOT NULL REFERENCES devices(dev_id),
    collected_at TIMESTAMPTZ NOT NULL,
    active_power_kw DOUBLE PRECISION NOT NULL,
    synced_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (dev_id, collected_at)
);

CREATE INDEX idx_device_power_readings_collected_at
    ON device_power_readings(collected_at);

CREATE TABLE plant_power_readings (
    plant_code TEXT NOT NULL REFERENCES plants(plant_code),
    collected_at TIMESTAMPTZ NOT NULL,
    pv_production_kw DOUBLE PRECISION NOT NULL,
    grid_export_kw DOUBLE PRECISION NOT NULL,
    consumption_kw DOUBLE PRECISION NOT NULL,
    synced_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (plant_code, collected_at)
);

CREATE INDEX idx_plant_power_readings_collected_at
    ON plant_power_readings(collected_at);

CREATE TABLE sync_windows (
    dev_id TEXT NOT NULL REFERENCES devices(dev_id),
    window_start TIMESTAMPTZ NOT NULL,
    window_end TIMESTAMPTZ NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('pending', 'done', 'failed')),
    error_message TEXT,
    updated_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (dev_id, window_start)
);

CREATE INDEX idx_sync_windows_status ON sync_windows(status);
