# Deploying MediaVault (auth and rate-limit settings)

Nothing is deployed yet; this is the checklist for the first staging/production setup.

## API (backend)

| Setting | Production value |
| --- | --- |
| `ENVIRONMENT` | `production` (required; the API refuses to start without it) |
| `DATABASE_URL` | from the secret store |
| `JWT_SECRET` | random, 32+ characters, from the secret store |
| `CORS_ALLOW_ORIGINS` | the website's `https://` origin(s) |
| `AUTH_TRUSTED_PROXIES` | the website server's address (IP or CIDR) and nothing else |
| uvicorn flags | `--no-proxy-headers` |

## Website (Next.js)

| Setting | Production value |
| --- | --- |
| `API_INTERNAL_BASE_URL` | the API's internal address |
| `WEB_TRUSTED_PROXY_HOPS` | number of reverse proxies in front of the website that **append** the client address to `X-Forwarded-For`; normally `1` |

Example reverse proxy (nginx) in front of the website:

```nginx
proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
```

## Why it matters (MV-025)

The browser controls `X-Forwarded-For`, so the website only trusts the entry appended by its own
proxy (`WEB_TRUSTED_PROXY_HOPS`-th from the right) and passes it to the API as
`X-MediaVault-Client-IP`. The API believes that header only from `AUTH_TRUSTED_PROXIES`.

* With `WEB_TRUSTED_PROXY_HOPS=0` (the default) the website sends no client IP, so **every website
  user shares one login/register bucket** (20 attempts/minute for the whole site per API process).
  The website prints a warning at startup in production when this is the case, and the API logs
  `auth.no_trusted_proxies` when `AUTH_TRUSTED_PROXIES` is empty.
* Callers that send forwarding headers from an untrusted address are keyed on their own address;
  rotating fake headers gains nothing.
* Anything that can connect from an address in `AUTH_TRUSTED_PROXIES` can name any client IP, so
  keep that list to the website server only.

## Known limits

* Rate-limit counters are in memory per API process (multiply by worker count); moving them to
  Redis is planned before scaling out.
* Refresh and logout are limited only on failures; valid refresh tokens and real logouts are never
  rate limited.
