# Presenting VaaniBench

## Start

After `uv sync --locked --cache-dir .uv-cache`, run from the repository root:

```powershell
uv run --no-sync vaanibench demo
```

Open http://127.0.0.1:8765. Keep the terminal running; Ctrl+C stops it. Use
`--port 8766` if the port is occupied. No account is needed for the mock demo.

For deliberately enabled live mode, save GROQ_API_KEY locally in .env, confirm
your provider plan/limits, then start:

```powershell
uv run --no-sync vaanibench demo --allow-live --env-file .env
```

Keys stay in the server process. Select Groq and confirm before live execution.
Live mode defaults to one case; the optional judge is uncalibrated. Each of the
two configuration runs is capped at $0.10 estimated spend and 20 attempts. One
server session permits one live comparison (two runs); restarting deliberately
creates a new session/budget. The selector indicates configured credentials, not
guaranteed quota/access. A terminal quota/authentication error stops the pair.

## Five-minute walkthrough

1. **0:00–0:45 — Explain the contract.** Show the versioned synthetic scenarios.
   Inputs end in user; references/rubrics never reach generation. A successful
   request is distinct from an answer passing its checks.
2. **0:45–2:00 — Run the six-case mock comparison.** Baseline vs deliberately
   degraded candidate. Watch per-case progress. Expand a response to inspect its
   rubric, metric reason, and trace ID. Mock presentation pacing is outside
   measured request latency.
3. **2:00–3:00 — Inspect the gate.** The default selection yields baseline 3/3 and
   degraded 1/3 applicable checks. Three semantic cases stay unscored. The paired
   regression is blocked. Choose baseline on both sides to show a passing gate.
   Mock scores validate the harness, not model intelligence.
4. **3:00–4:00 — Show real evidence or one live case.** Use the saved Groq
   smoke/A/B reports, or run Groq on one case when quota permits. Explain the
   judge's extra request and calibration limits. Real A/B may show no improvement.
5. **4:00–5:00 — Inspect reproducibility.** Download JSON, reports, comparison,
   and traces. Show hashes, model/configuration, versions, safe failures, token
   usage and USD estimates. Show the passing GitHub Actions run linked in README.

## Fallback and limits

Use mock mode or docs/benchmarks/groq-live-v1 when connectivity/quota is unavailable.
Unknown usage retains its reservation; it is not assumed free. Paid-equivalent
estimates do not prove actual Free-plan billing or lack of a charge.

The standard-library server is intentionally local, with Host/Origin checks,
a session request token, allowlisted configs/downloads, and one active comparison.
It is not a public service: no hosted-user authentication, durable queue, or
multiuser billing controls. Do not expose it publicly. History lives in memory;
artifacts remain under artifacts/demo/. Refreshing does not resume the old page's
job, though work continues and files are saved.

## Browser verification

Desktop/mobile layout, case details, mock gate, artifact download, and absence of
JavaScript errors were verified in headless Chrome. To reproduce against an
already running mock-only server:

```powershell
uv run --with playwright python scripts/check_demo_browser.py --browser "C:\Program Files\Google\Chrome\Application\chrome.exe"
```

Playwright is an optional QA tool, not an app dependency. Screenshots go under
artifacts/demo-preview/. Unit tests block network and inject provider transports;
authorized live smoke tests are separate from the suite.
