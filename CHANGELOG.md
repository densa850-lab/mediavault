# Changelog

## 0.1.0 (Phase 1 foundation), 2026-11-12

* Backend: FastAPI app factory, `GET /api/v1/health` with a PostgreSQL check, Alembic baseline,
  CORS allow-list, security headers, JSON logging, pytest suite.
* Web: Next.js 16 home screen with live backend status, Vitest tests.
* Android: Compose + Material 3 home screen with live backend status, unit tests, Compose UI tests.
* Infra: Docker Compose for PostgreSQL 18, Redis 8 and SeaweedFS. GitHub Actions CI for all three apps.
