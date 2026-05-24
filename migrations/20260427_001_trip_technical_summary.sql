BEGIN;

ALTER TABLE IF EXISTS car.trip
    ADD COLUMN IF NOT EXISTS logical_trip_id text,
    ADD COLUMN IF NOT EXISTS speed_max numeric,
    ADD COLUMN IF NOT EXISTS speed_avg numeric,
    ADD COLUMN IF NOT EXISTS rpm_max numeric,
    ADD COLUMN IF NOT EXISTS rpm_avg numeric,
    ADD COLUMN IF NOT EXISTS coolant_temp_max numeric,
    ADD COLUMN IF NOT EXISTS coolant_temp_avg numeric,
    ADD COLUMN IF NOT EXISTS intake_temp_max numeric,
    ADD COLUMN IF NOT EXISTS intake_temp_avg numeric,
    ADD COLUMN IF NOT EXISTS stft_b1_avg numeric,
    ADD COLUMN IF NOT EXISTS stft_b1_min numeric,
    ADD COLUMN IF NOT EXISTS stft_b1_max numeric,
    ADD COLUMN IF NOT EXISTS ltft_b1_avg numeric,
    ADD COLUMN IF NOT EXISTS ltft_b1_min numeric,
    ADD COLUMN IF NOT EXISTS ltft_b1_max numeric,
    ADD COLUMN IF NOT EXISTS fuel_trim_total_avg numeric,
    ADD COLUMN IF NOT EXISTS rich_event_count integer,
    ADD COLUMN IF NOT EXISTS lean_event_count integer,
    ADD COLUMN IF NOT EXISTS sample_count integer;

CREATE INDEX IF NOT EXISTS trip_logical_trip_id_idx
    ON car.trip (logical_trip_id);

COMMIT;
