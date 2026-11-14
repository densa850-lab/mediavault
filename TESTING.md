# Testing

## CI

`.github/workflows/ci.yml` runs on every pull request and every push to `main`, with no path
filters, so these checks are always reported: `backend`, `web`, `android` and the final
`ci-required` gate (fails unless all three succeed). The android job also proves that
`assembleRelease` fails without / with a non-https API URL and succeeds with a valid one.
The backend job runs every test against a real PostgreSQL 18.6 service container (auth, IDOR,
migrations) and then `alembic upgrade head && alembic check` (migrations must match the models).

**Compose UI tests in CI (plan, not yet enabled):** `app/src/androidTest` (6 tests: connected,
loading, degraded, error-retry, debug error reason, release hides reason) compiles in CI via
`assembleDebugAndroidTest`. Running them needs an emulator: add a job using
`reactivecircus/android-emulator-runner` (KVM is available on GitHub-hosted Linux runners, API 34
`google_apis` x86_64 image, `./gradlew connectedDebugAndroidTest`), first as non-required for a week
to measure flakiness, then make it required. Locally: `./gradlew connectedDebugAndroidTest` with an
emulator running.


## Phase 2 step 1 results (accounts and ownership, 2026-11-14, Linux x86_64 dev box)

Raw logs and exact counts are in the Phase 2 step 1 report attached to the pull request.

| Suite | Command | Result |
| --- | --- | --- |
| Backend, real PostgreSQL 18.6 | `uv run pytest -v -rs` with `TEST_DATABASE_URL` | all passed, 0 skipped |
| Backend without a database | `uv run pytest -rs` | DB tests skip cleanly, the rest pass |
| Migrations | `alembic upgrade head`, `downgrade 0001_baseline`, `downgrade base`, `upgrade head`, `alembic check` | clean, no model drift |
| Live API | uvicorn + curl (register, login, me, IDOR, rotate, reuse, logout, rate limit) | as expected |
| Production config | `ENVIRONMENT=production` without / dev-default / short `JWT_SECRET` | refuses to start; starts with a 64-char secret |
| Web | `pnpm lint`, `typecheck`, `test`, `build`; live `next start` + API via curl cookie jar | clean; cookies HttpOnly + SameSite=Strict + Secure, no tokens in bodies |
| Android | `assembleDebug testDebugUnitTest lintDebug assembleDebugAndroidTest` | JVM tests pass, lint 0 errors (1 intentional `OldTargetApi` warning) |
| Android on emulator | `am instrument` on an API 28 x86_64 emulator (software rendering) | Compose UI tests + the Keystore/Tink token store test passed |

What the auth tests cover:

* **Backend:** argon2id storage, 12-char policy, case-insensitive unique email, identical register
  response for new and existing emails, generic login errors (unknown email, wrong password,
  inactive), access-token expiry / wrong secret / `alg=none` / wrong type / future `iat`, refresh
  expiry, rotation, reuse detection revoking the session (and only that session), two concurrent
  refreshes (exactly one wins), logout revocation of access and refresh tokens, rate limits per
  email and per IP and the window reset, trusted-proxy `X-Forwarded-For` handling (IPs and CIDRs),
  two-user IDOR on get / patch / delete / list (404, other row untouched), `owner_id` spoofing
  ignored, production config negatives (including importing `app.main` without `JWT_SECRET`).
* **Web:** the `/api/auth/*` route handlers (cookie flags, no tokens in bodies, Origin check,
  refresh-on-401 with cookie rotation, cookie clearing, API unreachable) and the auth form.
* **Android:** `NetworkAuthRepository` over real Retrofit/OkHttp against MockWebServer (login,
  register, 401/422/429 mapping, refresh-and-retry, refresh rejection clears tokens, offline keeps
  tokens, logout always clears), Tink AES-256-GCM token cipher (round trip, tamper, wrong key,
  associated data), `AuthViewModel`, Compose `AuthScreen` (masked password, 12-char check, errors,
  sign out) and `EncryptedTokenStore` on a device (no plaintext token in the app's data directory).

Concurrent refresh (fix): truly concurrent refreshes on separate PostgreSQL connections (2 with a held
session lock, and 8) keep the session and return one successor; replay after the grace revokes; other
sessions unaffected; website overlapping `/api/auth/me` share one refresh with identical cookies;
Android overlapping `currentSession()` share one refresh, logout waits and leaves no credentials.

QA fixes (Tester's report on 0d065bb): MV-015 racers with different and unsynchronised clocks
(deterministic earlier-clock loser, mixed offsets under a held lock, 25 two-way + 8 five-way real
races per CI run, bounded skew still revokes); `scripts/stress_refresh_races.py` runs 100+ two-way
and 20+ five-way HTTP races against a live API and fails on any revocation. MV-016 rotating
`X-Forwarded-For` / `X-MediaVault-Client-IP` from untrusted peers (one bucket, also when uvicorn
rewrote the peer), trusted website header per client; website never forwards the browser's XFF.
MV-018 unset `ENVIRONMENT` refuses to start; MV-019 422 bodies never echo the password; MV-020
`no-store` on token responses; MV-021 failed refresh / unmatched logout limits.

Still not verified: the R8-minified release build was built but not run on a device, so Tink under
R8 relies on its bundled keep rules; the in-memory rate limiter is per process.

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
