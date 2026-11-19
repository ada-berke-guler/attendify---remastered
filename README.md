# Attendify

[![CI](../../actions/workflows/ci.yml/badge.svg)](../../actions/workflows/ci.yml)

Classroom attendance with a rotating QR code, a blink-based liveness check and face
verification. FastAPI + PostgreSQL/pgvector + Redis + React, one `docker compose up`.

> **v2 of a team project.** Attendify started as our graduation project
> ([v1, team repository](https://github.com/ada-berke-guler/attendify), also tagged
> [`v1.0-graduation`](../../tree/v1.0-graduation) here). v2 reworks the backend (pgvector
> matching, Redis-backed QR nonces, liveness tickets, rate limits and live events), merges the
> three frontends into one app and packages everything to run with a single command.

## Screenshots

| Instructor: live session | Instructor: dashboard |
|---|---|
| ![Live session with rotating QR, live feed, pending request and manual attendance](docs/screenshots/04-instructor-live-session.png) | ![Instructor dashboard](docs/screenshots/03-instructor-dashboard.png) |
| **Instructor: at-risk report** | **Admin: students** |
| ![Reports](docs/screenshots/10-instructor-reports.png) | ![Admin panel](docs/screenshots/02-admin-students.png) |

| Sign in | Student home | QR scan | Face check (no face → retry) | Checked in | Face registration |
|---|---|---|---|---|---|
| ![](docs/screenshots/01-login.png) | ![](docs/screenshots/05-student-dashboard.png) | ![](docs/screenshots/06-student-scan.png) | ![](docs/screenshots/07-student-verify-no-face.png) | ![](docs/screenshots/08-student-confirmation.png) | ![](docs/screenshots/09-student-face-setup.png) |

<sub>Camera views show the browser's synthetic test feed instead of a real face.</sub>

## Quick start

```bash
cp .env.example .env
docker compose up --build        # first build ~5 min (prebuilt dlib from conda-forge)
# open http://localhost  →  admin@test.com / admin123
```

Testing on a phone: `docker compose --profile tunnel up --build` (or `make tunnel`) and open
the `https://*.trycloudflare.com` URL from `docker compose logs tunnel` on **both** the laptop
(instructor) and the phone (student). See [Phone testing](#phone-testing).

### Demo accounts

| Role       | Login                                          | Password   |
|------------|------------------------------------------------|------------|
| Admin      | `admin@test.com`                               | `admin123` |
| Instructor | `hoca@test.com`                                | `hoca123`  |
| Students   | `ali@test.com`, `ayse@test.com`, `mehmet@test.com` (or student no. `20210001`…`3`) | `123456` |

Students register their face on first sign-in. Courses CS101 and CS201 are seeded with a
weekly schedule and all three students enrolled.

## Architecture

```
            browser / phone
                  │  http(s)://host
                  ▼
           ┌─────────────┐   /api/*    ┌──────────────┐   /analyze   ┌──────────────┐
           │    caddy    │ ──────────▶ │     api      │ ───────────▶ │     face     │
           │ (SPA + TLS) │             │   FastAPI    │  (internal)  │ dlib, stateless
           └─────────────┘             └──────┬───────┘              └──────────────┘
             serves web/ build                │
                                  ┌───────────┴───────────┐
                                  ▼                       ▼
                          ┌──────────────┐        ┌──────────────┐
                          │  PostgreSQL  │        │    Redis     │
                          │  + pgvector  │        │ nonces, tickets,
                          └──────────────┘        │ rate limits, pub/sub
                                                  └──────────────┘
```

| Directory | What |
|-----------|------|
| `api/`    | FastAPI backend. Routers in `app/api/v1`, logic in `app/services` (`qr`, `liveness`, `face_matching`, `attendance`, `events`, `qr_rotator`). |
| `face/`   | Internal face service. One endpoint: face count, eye aspect ratio, blur score, 128-d embedding. Keeps no state. |
| `web/`    | One React app. `/admin/*`, `/instructor/*`, `/student/*`, each its own lazy chunk behind a role guard. |
| `deploy/` | Caddyfile: `/api/*` → api, everything else → SPA. One origin, so no CORS. |

Only Caddy publishes a port. Postgres, Redis, api and face are reachable only inside the
compose network.

## How a check-in is secured

```
instructor screen                  student phone                       api
─────────────────                  ─────────────                       ───
QR = JWT{session, nonce, exp}  ──▶ scan
  nonce rotates every 15 s                │
  (Redis qr:{id}:current/previous)        │  frames  ──────────────▶  /attendance/liveness-check
                                          │                           EAR < 0.21 then > 0.25 within 60 s
                                          │                           state in Redis liveness:{user}
                                          │  ◀────────────────────── single-use ticket (60 s)
                                          │
                                          │  QR + ticket + frame ───▶  /attendance/submit
                                          │                            1. nonce is current or previous   → 400
                                          │                            2. enrolled, not yet recorded     → 403/409
                                          │                            3. GETDEL ticket, issued to me    → 403
                                          │                            4. face == face that blinked      → 422
                                          │                            5. min(embedding <-> q) ≤ 0.45    → 422
live list updates  ◀── SSE ◀── Redis pub/sub session:{id}:events ◀─── record saved
```

- **Rotating QR (Redis).** Every 15 s the server writes a fresh random nonce. A token is only
  accepted while its nonce is the current or the previous one, so a forwarded screenshot dies
  within ~30 s. Rotation runs in the api lifespan; a `SET NX` lock keeps replicas from
  double-rotating.
- **Liveness ticket (Redis).** The blink state machine lives in the api and its state in Redis,
  so it works across workers and restarts. A completed blink mints a ticket that `submit`
  consumes atomically with `GETDEL`: one use, one user, 60 s. The ticket also stores the
  embedding of the blinking frame, so blinking with your own face and submitting a photo of
  someone else fails.
- **Fail closed.** If the face service is down, liveness and submit return 503. Nothing is
  treated as a pass by default.
- **Matching in SQL (pgvector).** Embeddings are `vector(128)`. 1:1 verification is
  `SELECT min(embedding <-> :q) FROM face_embeddings WHERE student_id = :sid AND is_active`.
  `POST /sessions/{id}/identify` does 1:N search among a course's students
  ("find by photo" on the instructor screen). An HNSW index (`vector_l2_ops`) covers
  unfiltered search. Photos are not stored, only embeddings.
- **Rate limits (Redis).** Fixed windows: login 10/min per IP, submit 30/min per user,
  liveness frames 120/min per user. 429 with `Retry-After`.
- **Accounts.** Only an admin can create students or instructors. `SECRET_KEY` has no default;
  with `ENV=production` the api refuses to start without a 32+ character key.

Regression tests for each of these are named after the issue they close
(`test_s1_…` to `test_s8_…`).

## Configuration

`.env.example` lists everything you normally touch:

| Variable | Default | Notes |
|----------|---------|-------|
| `ENV` | `development` | `production` enforces `SECRET_KEY` |
| `PUBLIC_URL` | empty | Origin used in QR links. Empty: taken from the request, which is what makes the tunnel work without edits |
| `SECRET_KEY` | empty | Random per process in development (tokens die on restart) |
| `FACE_MODE` | `real` | `mock` = hash-based embeddings, for tests/CI only. Logs a warning |
| `FACE_MATCH_MAX_DISTANCE` | `0.45` | L2 distance threshold |
| `QR_ROTATE_SECONDS` | `15` | QR JWTs expire after twice this |
| `SEED_DEMO_DATA` | `true` | Idempotent demo seed on api start |
| `MAIL_*` | empty | Without SMTP the reset code is printed in `docker compose logs api` |

## Phone testing

Phones need HTTPS for the camera. The `tunnel` profile starts a Cloudflare quick tunnel to
Caddy and prints a random `https://….trycloudflare.com` URL:

```bash
make tunnel                 # or: docker compose --profile tunnel up --build -d
docker compose logs tunnel  # look for https://….trycloudflare.com
```

Open that URL on the laptop as the instructor too. The QR encodes the origin the instructor
opened, so a QR shown on `http://localhost` would point the phone at `localhost`. (Alternatively
set `PUBLIC_URL` to the tunnel URL and restart the api.) Scanning with the phone's own camera
app works: the link opens `/student/scan?token=…`, which goes straight to the face check.

### Fixed address on your own domain

With the domain on Cloudflare (free plan):

```bash
CF="docker run --rm --user root -v ./deploy/cloudflared:/root/.cloudflared cloudflare/cloudflared:2024.12.2"
$CF tunnel login                                   # open the link, authorize the domain
$CF tunnel create attendify                        # writes <tunnel-id>.json
$CF tunnel route dns attendify attendify.example.com
```

Then write `deploy/cloudflared/config.yml` (the folder is gitignored):

```yaml
tunnel: <tunnel-id>
credentials-file: /etc/cloudflared/<tunnel-id>.json
ingress:
  - hostname: attendify.example.com
    service: http://caddy:80
  - service: http_status:404
```

and run `docker compose --profile domain up -d`.

## Development

```bash
make up / down / logs / seed / reset-db / tunnel
make test                   # api tests + ruff inside Docker against the compose Postgres/Redis
```

Without Docker:

```bash
# api (needs PostgreSQL with pgvector, and Redis)
cd api && python -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
TEST_DATABASE_URL=postgresql://user:pass@localhost:5432/attendify_test .venv/bin/pytest
FACE_MODE=mock .venv/bin/uvicorn app.main:app --reload       # http://localhost:8000/api/docs

# web (proxies /api to :8000)
cd web && npm install && npm run dev
```

Tests run on real PostgreSQL + pgvector (each test in a rolled-back transaction) and on
fakeredis, or a real Redis when `TEST_REDIS_URL` is set. The face service is replaced by the
deterministic mock client. `face/tests` covers EAR and blur math without dlib.

API docs: `http://localhost/api/docs`.

## Deploying to a VPS

The same compose file works on a single server. Point a DNS record at it and set in `.env`:

```
ENV=production
SECRET_KEY=<openssl rand -base64 48>
POSTGRES_PASSWORD=<strong password>
PUBLIC_URL=https://attendify.example.edu
SITE_ADDRESS=attendify.example.edu
SEED_DEMO_DATA=false
```

Caddy obtains and renews the certificate on its own (ports 80 and 443 must be open).

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| Port 80 in use | `HTTP_PORT=8080 docker compose up`, then open `http://localhost:8080` |
| Phone camera does not start | You are on plain http. Use the tunnel URL (https) |
| "This QR code has expired" right after scanning | The phone took longer than ~30 s between scan and face check, or the laptop shows a QR from a different origin. Scan again |
| Face service unavailable (503) | `docker compose logs face`; the first start loads the dlib models |
| Everyone is logged out after a restart | `SECRET_KEY` is empty, so a new one was generated. Set it in `.env` |
| Need the password reset code | `docker compose logs api | grep "reset code"` |
| Start from a clean database | `make reset-db` |
