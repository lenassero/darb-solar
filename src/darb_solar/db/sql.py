"""DML statements for upserting FusionSolar rows."""

UPSERT_PLANT_SQL = """
INSERT INTO plants (plant_code, plant_name, timezone)
VALUES (:plant_code, :plant_name, :timezone)
ON CONFLICT(plant_code) DO UPDATE SET
    plant_name = excluded.plant_name,
    timezone = excluded.timezone;
"""

UPSERT_DEVICE_SQL = """
INSERT INTO devices (dev_id, plant_code, dev_dn, dev_type_id, role)
VALUES (:dev_id, :plant_code, :dev_dn, :dev_type_id, :role)
ON CONFLICT(dev_id) DO UPDATE SET
    plant_code = excluded.plant_code,
    dev_dn = excluded.dev_dn,
    dev_type_id = excluded.dev_type_id,
    role = excluded.role;
"""

UPSERT_DEVICE_POWER_READING_SQL = """
INSERT INTO device_power_readings (
    dev_id,
    collected_at,
    active_power_kw,
    synced_at
)
VALUES (:dev_id, :collected_at, :active_power_kw, :synced_at)
ON CONFLICT(dev_id, collected_at) DO UPDATE SET
    active_power_kw = excluded.active_power_kw,
    synced_at = excluded.synced_at;
"""

UPSERT_PLANT_POWER_READING_SQL = """
INSERT INTO plant_power_readings (
    plant_code,
    collected_at,
    pv_production_kw,
    grid_export_kw,
    consumption_kw,
    synced_at
)
VALUES (
    :plant_code,
    :collected_at,
    :pv_production_kw,
    :grid_export_kw,
    :consumption_kw,
    :synced_at
)
ON CONFLICT(plant_code, collected_at) DO UPDATE SET
    pv_production_kw = excluded.pv_production_kw,
    grid_export_kw = excluded.grid_export_kw,
    consumption_kw = excluded.consumption_kw,
    synced_at = excluded.synced_at;
"""

UPSERT_SYNC_WINDOW_SQL = """
INSERT INTO sync_windows (
    dev_id,
    window_start,
    window_end,
    status,
    error_message,
    updated_at
)
VALUES (
    :dev_id,
    :window_start,
    :window_end,
    :status,
    :error_message,
    :updated_at
)
ON CONFLICT(dev_id, window_start) DO UPDATE SET
    window_end = excluded.window_end,
    status = excluded.status,
    error_message = excluded.error_message,
    updated_at = excluded.updated_at;
"""
