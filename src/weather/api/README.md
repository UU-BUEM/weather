# Point-query HTTP API

**Status: deployed on `sd26` as of 2026-08-13 (not wired into this repo's
CI). See "Deployment (sd26)" below for the real, currently-running setup.**

## Why this exists

buem's production deployment cannot reach this repo's processed archives
directly: they live on a university server behind VPN, and a
request-serving container can't join a human VPN client the way a developer
does with `ssh sd26`. This exposes exactly one operation over HTTP so a
service running on/near the data host can sit inside that network boundary,
while callers outside it never need filesystem or bulk access.

## Scope

`GET /v1/weather/point?provider=merra-2&lat=52.0&lon=5.0&year=2018`
→ `weather.get_point_weather(latitude, longitude, year, provider=provider)`,
returned as a parquet-encoded body (`application/octet-stream`; the reset
index column is first, then `T`/`GHI`/`DHI`/`DNI`).

`GET /v1/health` → per-provider list of years with a processed archive,
derived from filenames already on disk. Deliberately does not expose a raw
directory listing.

Deliberately **not** exposed: file listing, bulk/archive download, anything
beyond this single point query already at the heart of `weather`'s own
public API. Keeping the network surface this narrow is the point — a
security review of "one typed query operation" is a much smaller ask than
"open network access to the data host".

## Auth (minimum viable, not sufficient on its own)

Static API keys via `WEATHER_API_KEYS` (comma-separated), checked against
the `X-API-Key` header. A per-key in-memory rate limiter
(`WEATHER_API_RATE_LIMIT`, default 60 req/min) guards against the "many
small point queries reconstruct the bulk archive" risk. Every request is
audit-logged (key prefix, path, status, remote address).

This is not a substitute for network-level restrictions — real deployment
should still pair this with a firewall/IP allowlist scoped to buem's known
egress, per the production-access design discussion (see buem's CLAUDE.md,
"weather-archive-access"). The rate limiter is in-memory and per-process —
fine for the single-process dev server below, not for a multi-worker WSGI
deployment (would need a shared store, e.g. redis, at that point).

## Running it locally

```bash
pip install -e ".[api,pointquery,solar,parquet]"
export WEATHER_API_KEYS="dev-key-change-me"
weather serve --host 127.0.0.1 --port 8080
```

`weather serve` runs Flask's dev server — fine for local testing, **not**
for production (no concurrency, no TLS). A real deployment should run this
app under gunicorn/similar, same as buem's own `infrastructure/container/`
does for its API.

## Deployment (`sd26`)

Running via `scripts/launch_weather_serve.sh` (repo root), bound to
`0.0.0.0:8091`, pointed at the real `/data/soma` archives:

```bash
ssh sd26
cd ~/weather

# Check it's running
ps -p "$(cat logs/weather_serve.pid)" 2>/dev/null && echo running

# Stop it
kill "$(cat logs/weather_serve.pid)"

# Start/restart (reads WEATHER_API_KEYS from .env -- see that script's
# header for how to generate one; refuses to start if .env has none, and
# refuses to double-start if the PID file shows an already-running process)
bash scripts/launch_weather_serve.sh
```

PID and log files live under `logs/` (gitignored, not `/tmp` — survives a
`/tmp` cleanup, though not a full server reboot without re-running the
script).

**Firewall**: port 8091 is not reachable directly from outside `sd26`, even
over the university VPN (confirmed: TCP connect times out) — only SSH
(port 22) is open. Every caller, including a developer's own machine,
currently needs an SSH tunnel:

```bash
ssh -N -L 8091:localhost:8091 sd26
```

Each client environment needs its own tunnel (Windows, WSL2, etc. don't
share a loopback interface) — see the main repo README's troubleshooting
history for this if a tunnel silently isn't forwarding. A real production
deployment (e.g. buem's own hosting) would need either a firewall rule
opening 8091 for its specific egress IP, or a reverse proxy on a port
that's already open — an infrastructure decision, not resolved here.

## buem-side integration

`buem`'s `weather_cache.py::get_or_fetch_weather()` has a matching remote
branch, gated by `WEATHER_API_URL`/`WEATHER_API_KEY`. Unset (the default),
buem's behavior is entirely unchanged (local `data_dir`/archive path,
exactly as before this API existed). Verified end-to-end (2026-08-13):
`get_or_fetch_weather()` unmodified, through the SSH tunnel above, against
two independent (location, year) pairs guaranteed not already
locally-cached — both returned correct 8760-hour years with physically
sane values.

## Still open (not decided here)

- Verified so far: `/v1/health` returns correct real data for all three
  providers; `/v1/weather/point` verified for `merra-2` only (two real
  fetches via buem, see above). `cosmo-rea6`/`era5-land` point-query is
  wired identically (same provider-agnostic `get_point_weather` call) but
  not yet exercised against their real archives through this API
  specifically.
- Whether buem's actual production deployment (as opposed to a
  developer's tunneled machine) can reach this at all depends on the
  firewall question above — needs the IT conversation flagged in buem's
  CLAUDE.md, not a code change.
