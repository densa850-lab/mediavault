# Testing

## Phase 1 results (run on 2026-11-12, Linux x86_64 dev box)

| Suite | Command | Result |
| --- | --- | --- |
| Backend unit + integration (real PostgreSQL 18.6) | `uv run pytest -v` with `TEST_DATABASE_URL` set | **8 passed, 0 failed** |
| Backend without a database | `uv run pytest` | 6 passed, 2 skipped (DB tests skip cleanly) |
| Backend lint | `uv run ruff check .` / `ruff format --check .` | clean |
| Web unit tests (Vitest) | `pnpm test` | **10 passed, 0 failed** (2 files) |
| Web lint / typecheck / build | `pnpm lint`, `pnpm typecheck`, `pnpm build` | clean / clean / success |
| Android build | `./gradlew assembleDebug assembleDebugAndroidTest` | success (`app-debug.apk`, test APK) |
| Android JVM unit tests | `./gradlew testDebugUnitTest` with `MEDIAVAULT_LIVE_API_URL` set | **9 passed, 0 failed, 0 skipped** |
| Android lint | `./gradlew lintDebug` | 0 errors, 1 warning (`OldTargetApi`: targetSdk 36 is intentional) |
| Manual end-to-end | uvicorn + `next start` + headless Chrome | Home page rendered **Backend connected** through real CORS |
| Manual outage | Stop Postgres → `/health` | HTTP 503 `degraded`. Web showed "database unavailable". Restart → 200 |

### What each suite covers

* **Backend:** health 200 against real Postgres, 503 on an unreachable DB with no credential or host
  leak, OpenAPI path, Alembic upgrade → downgrade → upgrade round trip, CORS allow and deny,
  security headers, env parsing.
* **Web:** base-URL handling, `fetchHealth` for 200, 503, network failure, bad payload and HTTP 500,
  and the `HealthStatus` loading, connected, degraded and error states, including the retry button.
* **Android:** `NetworkHealthRepository` over **real Retrofit 3.0.0 + OkHttp 5.5.1** against
  MockWebServer (200, 503 body, 500, malformed JSON, connection refused). `HomeViewModel`
  state transitions, including retry. An optional live test runs the same network stack against a
  running backend.

### Not run yet

* `./gradlew connectedDebugAndroidTest` (Compose UI tests in `app/src/androidTest`) needs an
  emulator or device. The dev box has no KVM access, so these tests compiled but did not run.
  Run them in Android Studio with an API 36 emulator.
* The app running on an actual emulator against `10.0.2.2` hasn't been checked yet, for the same
  reason. The network stack itself was verified against the live backend from JVM tests.
* `docker compose up` wasn't run because Docker isn't available on the dev box. The compose file passes
  `docker compose config` validation, and the tests used a local PostgreSQL 18.6 instead.
