# Changelog

## Unreleased: Phase 2 step 1 (accounts, login, ownership)

* Backend: `users` (case-insensitive unique email, argon2id hash), `auth_sessions`, `refresh_tokens`
  (sha256 only) and a `media_items` **stub** (no files), migration `0002_auth`.
* `/api/v1/auth` register / login / refresh / logout / me: 15-minute access JWT bound to a
  server-side session, rotating single-use refresh tokens with reuse detection, generic errors,
  12-character minimum, in-memory rate limits on login/register.
* `JWT_SECRET` required (32+ characters, not the dev default) in staging/production.
* Ownership: every `/api/v1/media-items` query is scoped to the signed-in user; others' rows are 404.
* Web: login / register / account pages; tokens only in HttpOnly SameSite=Strict cookies via the
  website's `/api/auth/*` routes, with an Origin check.
* Android: sign-in / register / sign-out screen; tokens encrypted with Tink (Android Keystore
  master key) in DataStore.
* CI: backend job also runs `alembic upgrade head && alembic check`.
* Concurrent refresh fix (PR #2 review): bounded, session-bound concurrency grace (`0003_refresh_grace`,
  `REFRESH_REUSE_GRACE_S`, default 10 s) returning the same derived successor; website single-flight
  refresh; Android `Mutex`-coordinated refresh/logout.

## Unreleased: Phase 1 remediation (no new features)

* MV-001: staging/production refuse to start without `DATABASE_URL`; no default credentials there.
* MV-002: staging/production reject `*` and non-https CORS origins; disallowed origins get no
  `Access-Control-Allow-Origin` or `Access-Control-Allow-Credentials`.
* MV-003: Android release builds fail unless `-Pmediavault.releaseApiBaseUrl` is a real https URL.
* MV-004: `/openapi.json` is not served in production.
* MV-005: website security headers (CSP, nosniff, X-Frame-Options, Referrer-Policy, ...).
* MV-007: minimatch override (GHSA-g3hv-75wg-m249). MV-008: python-dotenv declared, ruff pinned.
* MV-009: bare `tsc --noEmit` works on a fresh clone. MV-010: debug builds show the error reason;
  deprecated top-app-bar colors replaced. MV-014: loading/degraded/error-reason UI tests, v2 compose rule.
* MV-013: one `ci` workflow without path filters plus a `ci-required` gate job.

## 0.1.0 (Phase 1 foundation), 2026-11-12

* Backend: FastAPI app factory, `GET /api/v1/health` with a PostgreSQL check, Alembic baseline,
  CORS allow-list, security headers, JSON logging, pytest suite.
* Web: Next.js 16 home screen with live backend status, Vitest tests.
* Android: Compose + Material 3 home screen with live backend status, unit tests, Compose UI tests.
* Infra: Docker Compose for PostgreSQL 18, Redis 8 and SeaweedFS. GitHub Actions CI for all three apps.
