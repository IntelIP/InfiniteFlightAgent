-- Run as schema owner in the dedicated Jumpseat database after migration.
-- Pass existing non-owner, non-inheriting login names with psql -v runtime=... -v stopper=...
\set ON_ERROR_STOP on
BEGIN;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO :"runtime", :"stopper";
GRANT SELECT, INSERT, UPDATE ON requests, snapshots, leg_meta, settings, siwc_credentials TO :"runtime";
GRANT SELECT, INSERT, UPDATE, DELETE ON checkpoints, checkpoint_blobs, checkpoint_writes TO :"runtime";
GRANT SELECT ON paid_policy TO :"runtime";
GRANT EXECUTE ON FUNCTION public.reserve_aeroapi_pages(integer) TO :"runtime";
GRANT EXECUTE ON FUNCTION public.stop_jumpseat() TO :"stopper";
COMMIT;
