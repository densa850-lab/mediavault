# MediaVault

MediaVault is a free, ad-supported media manager for **your own** photos, videos and audio, on
Android and the web, backed by one shared server.

> **Status: Phase 1 (foundation).** Phase 1 contains the shared FastAPI backend with a health check
> and PostgreSQL connection, a website home screen and an Android home screen. Both apps call the
> backend and show whether it's reachable. Media import, the library, tools, accounts and ads
> come in later phases.

MediaVault works only with media you own or are authorized to use. It uses official APIs and OAuth
only, never asks for social-media passwords, and does **not** support downloading Instagram Reels,
Stories or other private or protected content.

## What's in this repo

| Folder | What it is |
| --- | --- |
| `backend/` | FastAPI API (Python 3.13), SQLAlchemy 2.1 + psycopg 3, Alembic migrations |
| `web/` | Next.js 16 + React 19 + TypeScript + Tailwind CSS 4 website |
| `android/` | Kotlin + Jetpack Compose + Material 3 app (`app.densa.mediavault`) |
| `infrastructure/docker/` | Local PostgreSQL 18, Redis 8 and SeaweedFS (S3) via Docker Compose |
| `.github/workflows/` | CI (`ci.yml`): backend, web and android jobs on every PR, plus the `ci-required` gate |

See [ARCHITECTURE.md](ARCHITECTURE.md) for the design and [TESTING.md](TESTING.md) for test results.

---

## 1. One-time setup (beginner guide)

Install these free tools. After each one, run its check command in a new terminal.

| Tool | Get it | Check |
| --- | --- | --- |
| Git | https://git-scm.com | `git --version` |
| Docker Desktop (on Windows, turn on WSL 2 when asked) | https://www.docker.com/products/docker-desktop | `docker compose version` |
| uv (installs Python for you) | https://docs.astral.sh/uv/getting-started/installation/ | `uv --version` |
| Node.js 24 LTS | https://nodejs.org | `node -v` (shows v24.x) |
| Android Studio (latest stable) | https://developer.android.com/studio | opens without errors |

In Android Studio, open **Settings → Languages & Frameworks → Android SDK** and install:

* **SDK Platforms:** Android 16 (API 36) and Android API 37 (the app compiles against 37)
* **SDK Tools:** Android SDK Build-Tools, Android Emulator, Android SDK Platform-Tools

Then open **Device Manager**, create a Pixel device with an API 36 image and start it.

Get the code and create your local settings file:

```bash
git clone https://github.com/densa850-lab/mediavault.git
cd mediavault
cp .env.example .env          # Windows PowerShell: Copy-Item .env.example .env
```

Open `.env` and change `change-me-local-only` to any password you like. Change it in all three
places: `POSTGRES_PASSWORD`, `DATABASE_URL` and `TEST_DATABASE_URL`. This file stays on your computer.
Git ignores it, so it never gets committed.

## 2. Run everything locally

Use three terminals, all starting in the `mediavault` folder.

### Terminal 1: database and backend

```bash
docker compose -f infrastructure/docker/compose.dev.yml --env-file .env up -d
docker compose -f infrastructure/docker/compose.dev.yml --env-file .env ps   # wait until "healthy"

cd backend
uv python install 3.13
uv sync
uv run alembic upgrade head
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Check it in a browser or a second terminal:

```bash
curl http://localhost:8000/api/v1/health
```

Expected (HTTP 200):

```json
{"status":"ok","service":"mediavault-api","version":"0.1.0","environment":"development","checks":{"database":"ok"},"time":"..."}
```

If the database is down, you get HTTP 503 with `"status":"degraded"` and `"database":"error"`.
The interactive API docs are at http://localhost:8000/docs.

### Terminal 2: website

```bash
cd web
npm install -g corepack@latest   # only needed once, if `pnpm` is not found
corepack enable
pnpm install
cp .env.example .env.local       # Windows PowerShell: Copy-Item .env.example .env.local
pnpm dev
```

Open http://localhost:3000. The card should say **Backend connected**.

### Terminal 3: Android app (emulator running)

```bash
cd android
./gradlew :app:installDebug      # Windows: gradlew.bat :app:installDebug
```

Open **MediaVault** on the emulator. It calls `http://10.0.2.2:8000/`, the emulator's address for
your computer, and should show **Backend connected**. You can also just open the `android` folder in
Android Studio and press **Run**.

**Using a real phone over USB?** Turn on USB debugging, plug the phone in, then run:

```bash
adb reverse tcp:8000 tcp:8000
./gradlew :app:installDebug -Pmediavault.apiBaseUrl=http://localhost:8000/
```

### Stop everything

Press `Ctrl+C` in terminals 1 and 2, then:

```bash
docker compose -f infrastructure/docker/compose.dev.yml --env-file .env down      # keeps data
docker compose -f infrastructure/docker/compose.dev.yml --env-file .env down -v   # deletes data
```

## 3. Run the tests

```bash
# Backend (the database tests use TEST_DATABASE_URL from .env)
cd backend && uv run ruff check . && uv run pytest -v

# Website. `pnpm typecheck` (= `next typegen && tsc --noEmit`) is the supported type check;
# a bare `pnpm exec tsc --noEmit` also works on a fresh clone.
cd web && pnpm lint && pnpm typecheck && pnpm test && pnpm build

# Android (JVM unit tests + lint; the UI tests need a running emulator)
cd android && ./gradlew assembleDebug testDebugUnitTest lintDebug
cd android && ./gradlew connectedDebugAndroidTest
# Optional: unit-test the app's network stack against your running backend
cd android && MEDIAVAULT_LIVE_API_URL=http://localhost:8000/ ./gradlew testDebugUnitTest
# Release builds REQUIRE a real https:// API URL and fail without one (no placeholder fallback)
cd android && ./gradlew assembleRelease -Pmediavault.releaseApiBaseUrl=https://api.your-domain.com/
```

## Troubleshooting

* **Website says "Backend unreachable":** make sure terminal 1 is running and
  `curl http://localhost:8000/api/v1/health` works. If the website is on a different address than
  `http://localhost:3000`, add that address to `CORS_ALLOW_ORIGINS` in `.env`.
* **Android says "Backend unreachable":** the backend must listen on `0.0.0.0` (as above). On a real
  phone, use the `adb reverse` steps.
* **Port 5432 already in use:** set `POSTGRES_PORT=5433` in `.env`, update the port in
  `DATABASE_URL` and `TEST_DATABASE_URL`, then run `docker compose ... up -d` again.

## Deployed environments (staging / production)

The backend refuses to start (`ConfigurationError`, no values echoed) when `ENVIRONMENT` is
`staging` or `production` and:

* `DATABASE_URL` is missing or empty. There is no built-in database default outside development/test.
* `CORS_ALLOW_ORIGINS` contains `*`, a wildcard, an `http://` origin, a path, a query or credentials.
  Only explicit `https://host[:port]` origins are accepted.

In production `/docs`, `/redoc` and `/openapi.json` are not served.

## Security rules for contributors

* Never commit `.env`, keystores, API keys or real passwords. Only `.env.example` files belong in git.
* Debug Android builds allow plain HTTP **only** to `10.0.2.2`, `localhost` and `127.0.0.1`.
  Release builds are HTTPS-only and need `-Pmediavault.releaseApiBaseUrl=https://...`.
* All changes to `main` go through a pull request; the `ci-required` check must pass.
* Don't add scraping, login-bypass or DRM-bypass code, or anything that downloads content the
  user isn't authorized to use.
