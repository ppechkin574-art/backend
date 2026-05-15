"""Admin-editable runtime configuration store.

Values that need to change without a backend redeploy live here:
global SMS cap, per-IP abuse thresholds, feature flags. Reads are
cached in Redis with a 60-second TTL so admin updates propagate
across replicas within at most a minute. Persisted in the
`app_settings` table — Redis is just an in-front cache.
"""
