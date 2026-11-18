# Render deployment and operating limits

## Supported first release

The tracked render.yaml is a **public mock-only** single-instance deployment.
Visitors can execute the same synthetic comparisons, view the recorded real
Groq benchmark, and download their own artifacts. No provider credentials are
needed. Starlette/Uvicorn is the hosted HTTP layer; the existing CLI and local
demo remain available. Model generation/evaluation logic is shared.

Prepared and locally tested does not mean deployed. An actual Render build,
assigned URL, HTTPS smoke check, and restart check are required before claiming
the hosted service works.

## Deploy the public demo

1. Connect Render to https://github.com/Deep6908/VaaniBench-AI.
2. Create a Blueprint from main, using render.yaml. Review the Free-plan service
   and environment values before creation. No API key or owner password is part
   of the Blueprint. Auto-deployment waits for CI checks.
3. Render supplies PORT and RENDER_EXTERNAL_URL. The application uses the latter
   as its exact public origin. For a custom domain, set VAANIBENCH_ORIGIN to the
   exact `https://your-domain` origin without a trailing path. Do not use a
   wildcard or disable host/origin validation.
4. Check /healthz returns 200, then load the interface over HTTPS. Run both mock
   presets, inspect a response, refresh during a comparison, download a report,
   and open the saved Groq evidence. Live choices must remain disabled.
5. In a different browser/private session, verify the first session's job and
   download URLs return 404. A cross-origin POST must return 403. No .env,
   filesystem directory, credential, or arbitrary config is served.

The build installs locked runtime dependencies, not pytest/httpx. Python 3.13.18
is explicitly pinned for hosting. Keep that patch version maintained; CI covers
Python 3.11/3.13. Uvicorn binds 0.0.0.0:$PORT with one worker. Forwarded headers
are not trusted for identity/origin decisions. HTTPS terminates at Render;
production cookies are Secure/HttpOnly/SameSite=Strict and HSTS is sent.

## Free hosting behavior

Free services can sleep after inactivity and use ephemeral storage. Sessions,
mock job history, and reports in /tmp may disappear on restart/redeploy; the
recorded benchmark is shipped from the repository. Open the service before an
interview and retain the offline demo as a fallback. Do not promise always-on
availability. Mock-only mode makes no live API calls even if a provider key is
accidentally present in the environment.

## Optional owner-only live execution

This is a deliberate second deployment configuration. Keep it disabled for the
first public release. Use a separately configured web service for owner-live mode,
copying the Blueprint's build/start/health settings and production/Python settings.
Do not rely on manual overrides of a Blueprint-managed mock service: a later
Blueprint sync can restore its tracked safe defaults. Live hosting fails startup
without both owner authentication and an explicit persistent-storage confirmation.

1. Use a Render service with an attached persistent disk, mounted at /var/data.
   Confirm pricing in Render before selecting paid compute/storage. Maintain one
   instance and one worker; do not horizontally scale a SQLite deployment.
2. Set VAANIBENCH_STATE_DIR=/var/data/vaanibench. Back up that directory's SQLite
   database and runs using controlled access. Live production rejects state paths
   inside the project or temporary directory. The confirmation flag is an
   operator assertion; the application cannot prove a cloud disk is durable.
3. Generate a strong owner password hash locally:

   ```powershell
   uv run --no-sync python -m vaanibench.hosted_auth
   ```

   Enter a unique password of at least 16 characters in the hidden prompt. Store
   the resulting PBKDF2 hash as VAANIBENCH_OWNER_PASSWORD_HASH in Render secrets.
   Never put the password/hash or provider key into Git, client-side JavaScript,
   a URL, or chat. Only the hash is needed on the server.
4. Store GROQ_API_KEY as a Render secret. Do not upload the local .env. Set
   VAANIBENCH_PERSISTENT_STORAGE=true and VAANIBENCH_LIVE_ENABLED=true only after
   the persistent mount is verified. Set VAANIBENCH_DAILY_USD and
   VAANIBENCH_DAILY_CALLS if changing defaults ($0.50 and 50 attempts per UTC day).
5. Redeploy, sign in through Owner sign-in, and perform one explicit single-case
   smoke test. Verify usage and daily reservations survive a service restart.
   Sign out; live execution must again be forbidden. Check the provider's account
   plan/quotas separately. No automatic model/provider fallback is implemented.

One shared daily SQLite ledger covers both configurations, retries, generation,
and judging. Each request reserves estimated maximum input/output USD **before**
transport. Returned usage reconciles it; uncertain failures retain reservations.
Crashes do not refund uncertain spend, and deleting expired reports does not
reset today's ledger. Daily entries are retained for 90 days. Limits are per
deployment, not a cap on other applications sharing a provider account. Estimates
are not a hard guarantee about the provider's invoice or Free-plan eligibility.

## Sessions, jobs, throttling, and recovery

- Anonymous visitors receive an opaque one-hour session. Tokens are hashed in
  SQLite; jobs and downloads require the creating session's owner identity.
- Owner sign-in rotates the session and uses a single configured owner account.
  Sign-out revokes that token. There is no public registration. Treat the owner
  password as a credential; stronger identity-provider authentication is a later
  option for a larger deployment.
  Changing/removing the configured password hash invalidates existing owner
  sessions on restart without clearing the spending ledger.
- State-changing requests require the configured exact Origin and a session CSRF
  token. A bootstrap token alone does not authorize owner-only live execution.
- Maximum two running comparisons globally, one per owner identity, three starts
  per identity per five minutes, and 20 starts globally per minute. Login/session
  creation are also throttled in SQLite. These protect a small demo; they are not
  a guarantee against distributed denial of service. Limits intentionally use
  global/session identities rather than trusting arbitrary proxy IP headers.
  API reads are limited to 600/minute per session identity and 2,400/minute globally;
  normal progress polling is below these limits. The health endpoint is exempt.
- Inputs are bounded JSON with allowlisted configurations and at most six known
  synthetic cases. No visitor prompts/uploads or real child data are accepted.
- Completed results expire after one hour; older completed entries are evicted
  at the 100-job history bound. Running jobs are not deleted. Anonymous sessions
  and expired rate buckets are cleaned. The UI can resume an in-progress job
  after refresh using its session cookie and a nonsecret job ID.
- A process lock rejects a second worker against the same state directory.
  Restart marks unfinished jobs interrupted, preserves events/artifacts and
  daily reservations, and never automatically retries model requests.
- A job deadline stops subsequent calls after 180 seconds; shutdown also asks the
  runner to stop between calls. Socket timeouts cannot forcibly interrupt a
  slowly arriving response. A platform kill can interrupt work; the persisted
  reservation remains conservative. This is bounded background execution, not
  a durable, resumable distributed task queue.

## Verification, rollback, and monitoring

To preview the hosted adapter locally on Windows without any live mode:

```powershell
$env:VAANIBENCH_ENV="development"
$env:VAANIBENCH_LIVE_ENABLED="false"
$env:VAANIBENCH_ORIGIN="http://127.0.0.1:8767"
$env:VAANIBENCH_STATE_DIR="artifacts/hosted-preview"
uv run --no-sync uvicorn vaanibench.hosted:app --host 127.0.0.1 --port 8767 --workers 1 --no-access-log --no-proxy-headers
```

Do not set live/auth secrets for the public mock preview. The browser check can
then use `--url http://127.0.0.1:8767 --check-hosted` with
scripts/check_demo_browser.py. Its optional owner-UI flag uses a fixed throwaway
test password on loopback only and must never configure a public deployment.

Before launch, run the full pytest suite and browser checks. Unit/integration
tests use fake model transports; Windows asyncio's internal socket pair is
permitted, but external/model network connections are blocked. CI exercises the
same locked install, tests, dataset validation, and mock regression gates.

After deployment, monitor Render health/restarts, failed or interrupted jobs,
429 responses, the owner daily ledger, and provider usage. Local OpenTelemetry
artifacts persist with each run; an external trace backend is still optional.
Access logging is disabled by default to avoid logging cookies, credentials, or
visitor request metadata. Keep Render deployment logs and health events available.

For rollback, disable live execution first if accounting/storage is in doubt,
then deploy the previous known-good commit in Render. Preserve the state directory
and current day's reservations. Do not "fix" a failed deployment by deleting
state. Current schema is creation-only; a future schema change needs a tested
migration/backup procedure before rollout. Verify health, a mock comparison, and
private download behavior after rollback.

Sources: [Render services](https://render.com/docs/web-services),
[Blueprint spec](https://render.com/docs/blueprint-spec),
[Free-service limits](https://render.com/docs/free),
[Persistent disks](https://render.com/docs/disks),
[Python version configuration](https://render.com/docs/python-version).
