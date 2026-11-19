# Durable owner-live setup, verification and recovery

The public https://vaanibench-ai.onrender.com deployment remains the verified
mock-only MVP. This release includes the durability extensions below. The user's
Supabase Oregon session pooler passed an encrypted read-only driver check; no
tables were changed during verification. Owner-live hosting is not yet configured.
No paid service, new real benchmark or collector account was created by this work.

## External PostgreSQL with ephemeral web hosting

The application supports external PostgreSQL without a persistent web disk.
SQLite remains the local/default backend and can alternatively use a paid disk.
Use a dedicated database or schema-owner role, never an existing unrelated app's
database credentials. All application tables live in the `vaanibench` schema.

One possible setup is a Supabase project. Review its current free-plan limits,
pausing policy, backup availability and region before creating the resource.
In the project's Connect dialog, use a **direct connection** or **session pooler**
URL compatible with the host's IP support. **Do not use transaction pooling**:
the application holds a session-scoped singleton lease. Add `sslmode=require`
(prefer `verify-full` with the provider CA when configured). Percent-encode
passwords in a URI. Never paste the URL into chat or commit it.

Official connection guidance:
https://supabase.com/docs/guides/database/connecting-to-postgres

For hosting, create a separately configured Render web service from the same
repository using the existing build/start/health commands. Select free compute
if appropriate; no web disk is needed with PostgreSQL. Do not manually override
the public Blueprint's fixed live=false settings: a later sync can revert them.
Keep one instance and one worker. Render cold starts and database availability
still affect this portfolio service; this is not an always-on production SLA.

Set these server environment variables (values below are not real secrets):

| Variable | Value/purpose |
| --- | --- |
| PYTHON_VERSION | 3.13.18, matching current public Blueprint |
| VAANIBENCH_ENV | production |
| VAANIBENCH_DATABASE_URL | Secret direct/session PostgreSQL URI with TLS |
| VAANIBENCH_STATE_DIR | /tmp/vaanibench-owner (scratch only) |
| VAANIBENCH_OWNER_PASSWORD_HASH | Secret hash generated below |
| GROQ_API_KEY | Provider secret, only for explicitly approved live calls |
| VAANIBENCH_LIVE_ENABLED | false initially; true only after durability smoke checks |
| VAANIBENCH_PERSISTENT_STORAGE | false; a disk attestation is unnecessary with PostgreSQL |
| VAANIBENCH_DAILY_USD | 0.50 (estimated; not an invoice guarantee) |
| VAANIBENCH_DAILY_CALLS | 20 for a conservative initial deployment (application default 50) |

Generate the hash locally using `uv run --no-sync python -m vaanibench.hosted_auth`.
Use a unique password of at least 16 characters; only the hash goes into Render.
The app obtains its exact HTTPS origin from RENDER_EXTERNAL_URL. Set
VAANIBENCH_ORIGIN only for a custom exact origin, without a path or wildcard.
Keep `/healthz` and existing `--workers 1 --no-proxy-headers` start options.

## Acceptance and demo procedure

1. Install the locked environment and run the offline tests.
2. Start `uv run --no-sync python scripts/serve_browser_fixture.py`. This is a
   loopback-only mock fixture with a documented THROWAWAY password, not a real
   owner service. Open http://127.0.0.1:8771 and show regression/repeatability.
3. Sign in with `temporary browser-only test password`. Run a comparison, expand
   Saved evaluations, refresh history, open a result and download a report.
   Compare two compatible saved candidates; different cases/datasets/judge
   settings are rejected. Cancel a running comparison and inspect its status.
4. Verify the local PostgreSQL contract with the disposable database test below.
5. After external configuration, keep live=false, sign in and repeat the mock
   workflow on HTTPS. Restart with a new scratch directory: sessions, history,
   downloads and daily accounting must remain. Another browser cannot read jobs.
6. Enable owner-live only after that check. Prepare a benchmark dry plan and
   obtain approval for the selected cases/calls/cost before any real API request.
7. For one approved hosted smoke, select one known case, confirm live execution,
   inspect usage, restart, and verify counters. Sign out; live options disappear.
   Do not execute this step automatically or as part of unit/CI tests.

## Storage, migrations and bounded execution

Schema version 1 records the original session/job/rate/attempt/metadata tables.
Version 2 adds job controls and artifact tables. Startup applies pending additive
migrations inside a write transaction. Existing SQLite files are adopted without
erasing reservations. A newer schema version fails closed. Do not edit migration
history or reset a production ledger to work around a failure.

PostgreSQL write transactions take one advisory lock; SQLite uses BEGIN IMMEDIATE.
Capacity admission, idempotency lookup/insertion, and budget reservations are
atomic. A dedicated PostgreSQL connection holds the process lease; direct/session
pooling is required. Losing the lease prevents further model attempts. During a
rolling deployment the replacement starts in standby if the predecessor still
owns the lease. /healthz returns 200 with execution_ready=false and
deployment_state=standby so Render can switch traffic and retire the predecessor.
All /api routes return 503 with Retry-After while in standby. The browser retries
its bootstrap automatically. Only after acquiring the lease does the replacement
rotate owner sessions if needed, recover interrupted jobs, and enable the API.
Shutdown retains leadership until evaluation threads drain. Late completions
cannot overwrite already-recovered jobs. This preserves one evaluation owner
without requiring the old process to stop before the new HTTP server starts.

Startup recovery marks unfinished jobs interrupted and never replays uncertain
calls. Database connection failures remain distinct from a busy deployment lease.
If standby persists well beyond a normal deployment, check for a second service
using the same database. Keep one configured owner service per database.

The browser sends an idempotency key and retains it if submission delivery is
uncertain. Repeating that selection returns the same job; a different payload
under the key is rejected. Keys live as long as the retained job. Refresh after
acceptance resumes polling, not model execution. No automatic full-dataset run.

Cancellation is cooperative: an active HTTP request may finish, but checks before
subsequent cases/retries/judging prevent further calls. Shutdown/deadline uses the
same guard. Completed work and uncertain reservations remain accounted. Work is
not resumable across a crash; this is not a distributed durable queue.

Completed downloads are stored in the database in the same transaction as job
completion. Per artifact limit: 1 MB; combined limit: 5 MB/job. Seven-day result
retention with PostgreSQL, one hour with default SQLite, at most 100 jobs. Daily
reservation rows are retained 90 days, independently of report cleanup. Free
database quotas still need monitoring. Original pre-migration SQLite reports
can use local files as a compatibility fallback and require those files on backup.

## Disposable PostgreSQL verification

Use a database named `vaanibench_test` on localhost only, with throwaway credentials.
Set VAANIBENCH_TEST_POSTGRES_URL in the local process, then run:

```powershell
uv run --no-sync pytest tests/test_postgres_integration.py -q
```

These tests explicitly DROP the application's schema in that **test database**;
never point them at a service database. They use fake provider transports. CI
provides an isolated PostgreSQL 17 service; ordinary tests skip these two checks
unless opted in. They exercise concurrent budget admission, migration, singleton
leases, fake live execution, duplicate submissions and fresh-scratch recovery.

## Backup, restore and rollback

Backups contain private sessions, synthetic responses and spending records.
Restrict access, encrypt retained archives, and keep them outside Git. Use the
provider's backup capabilities where available; free accounts may require manual
exports. https://supabase.com/docs/guides/platform/backups

For PostgreSQL use a matching/newer `pg_dump` client with the provider's direct
connection and securely configured libpq environment or a protected password file.
Do not embed credentials in command arguments, URLs in scripts, or shell history.
With PGHOST/PGPORT/PGUSER/PGDATABASE/PGSSLMODE and credentials already configured:

```text
pg_dump --format=custom --schema=vaanibench --no-owner --no-acl --file=state.dump
```

Restore **into a separate empty database first**, with the service stopped and
the destination configured through libpq. Verify archive/source/destination before
running the explicit restore; never restore over an active deployment:

```text
pg_restore --no-owner --no-acl --exit-on-error --dbname=RESTORE_DATABASE state.dump
```

Check schema version, daily reservations, session revocation behavior, result
ownership, report downloads and interrupted-job status. A backup predates later
spending: do not resume live execution until subsequent provider usage has been
reconciled conservatively. Restoring an older ledger is not a budget reset.

For SQLite use Python's sqlite3.Connection.backup API to get a consistent copy;
include legacy file-only artifacts if present. Stop the service before restoring.
Retain the original copy; validate the restored service with live disabled.

For application rollback stop the current service, back up first, then deploy a
known compatible revision. Version 2 is additive; the pre-PostgreSQL MVP cannot
serve a PostgreSQL deployment and is not a valid rollback target for that backend.
If compatibility is uncertain, keep live disabled and recover from a reviewed
snapshot. Keep provider credentials and operator settings unchanged.

## Remote tracing and alerts

Remote tracing is off by default. One supported destination is an HTTPS OTLP/HTTP
collector configured to receive traces. Set VAANIBENCH_OTLP_ENABLED=true,
OTEL_EXPORTER_OTLP_TRACES_ENDPOINT to the complete `/v1/traces` URL, and secret
OTEL_EXPORTER_OTLP_TRACES_HEADERS if the collector requires authentication.
No collector has been configured or verified by this change.

Generation/judge/retry spans share the evaluation/case trace. Content and secrets
are excluded from application span fields, exception capture is disabled, local
JSONL export remains enabled, and remote errors use sanitized diagnostics. Export
is bounded/batched; losing remote delivery does not erase local evaluation results.
Delivery outages can lose remote spans; this is not a durable telemetry queue.

Owner Saved evaluations shows operational counts, daily accounting and warnings.
GET /api/operations is owner-only. Thresholds are versioned in
configs/operations-thresholds.json: at least 20 attempted live cases before quality
of service warnings, generation error rate >=5%, p95 generation latency >=10s,
and daily usage >=80%. Mock cases are counted separately and do not trigger live
latency/error warnings. Interrupted/failed/cancelled history prompts inspection.
These are initial demo thresholds, not established SLOs. The snapshot covers
retained owner jobs; missing unfinished results cannot establish full traffic rates.
Warnings are visible on refresh; external notifications and uptime monitoring
still require operator configuration. No messages are sent automatically.
