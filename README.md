# Lumi Backend

Backend service for the Lumi educational mobile app. Provides API for authentication, payments, quizzes, analytics, notifications, and integration with external services (Keycloak, Firebase, FreedomPay, MinIO, etc.).

## Tech Stack

- **Python 3.13** + **FastAPI** — main web framework
- **PostgreSQL 15** + **SQLAlchemy 2.0** + **Alembic** — database and migrations
- **Redis** — caching and WebSocket support
- **Keycloak** — identity provider (OAuth2 / OpenID Connect)
- **MinIO** — S3-compatible file storage
- **Docker**, **docker-compose** — containerization and local development
- **GitLab CI** — CI/CD pipelines
- **Prometheus**, **Grafana**, **Loki** — monitoring and logging (optional)

## Project Structure

```
├── alembic/      # Database migration scripts
├── src/
│ ├── api/                       # FastAPI routes, middlewares, dependencies
│ ├── auth/                      # Authentication, OAuth, Keycloak integration
│ ├── clients/                   # External clients (Firebase, Apple, FreedomPay...)
│ ├── database/                  # DB connection, UoW
│ ├── payments/                  # Payment services and WebSockets
│ ├── quiz/                      # Test logic, questions, progress
│ ├── analytics/                 # Analytics and reporting
│ ├── student/                   # Student management and ratings
│ └── subscription/              # Subscription handling
├── .env.example                 # Example environment variables
├── .gitlab-ci.yml               # CI/CD pipeline definition
├── docker-compose.yml           # Main compose file for all services
├── docker-compose.override.yml  # Override for local development (hot-reload, volume mounts)
├── Dockerfile                   # Optimised multi-stage Dockerfile
├── requirements.txt             # Python dependencies (pinned via pip-tools)
├── pyproject.toml               # Ruff configuration
└── .pre-commit-config.yaml      # Pre-commit hooks setup
```

## Prerequisites

- **Docker** _20.10+_ and **docker-compose** _2.x_
- **Python _3.13_** (if running locally without Docker)
- **Git** (for pre-commit hooks)

## Quick Start (Local Development)

1. **Clone the repository**
   ```bash
   git clone <repository-url>
   cd backend
   ```
2. **Set up environment variables**

   Copy `.env.example` to `.env` and fill in your values (see Environment Variables section).

3. **Prepare secret files**

- _For Apple OAuth_: place your private key in `secrets/apple_private_key.p8`
- _For Firebase_: place your service account JSON in `secrets/firebase_credentials.json`.

  Example files are provided with `.example` extension.

4.  **Start all services**

    ```bash
    docker-compose up -d
    ```

    The API will be available at http://localhost:8000.

    Swagger docs: http://localhost:8000/docs

5.  **(Optional) Development mode with hot-reload**

    Ensure `docker-compose.override.yml` exists (it mounts your code and enables --reload).

    Code changes will automatically restart the server.

6.  **(Optional) Install pre-commit hooks**
    ```bash
    pip install pre-commit
    pre-commit install
    ```
    Hooks will run before each commit to lint and format code.

## Managing Secrets

**Important**: Secret files **must never be committed** to the repository. They are stored locally in `secrets/` (ignored by `.gitignore`) and on the production server.

- _**Apple OAuth**_: file `apple_private_key.p8` (PEM format)

- _**Firebase**_: file `firebase_credentials.json` (service account JSON)

Inside the container, these files are mounted to `/app/secrets/`.
Corresponding environment variables (already in `.env`):

```bash
APPLE_OAUTH__PRIVATE_KEY_FILE=/app/secrets/apple_private_key.p8
FIREBASE__CREDENTIALS_PATH=/app/secrets/firebase_credentials.json
```

## Environment Variables

Key variables (full list in `.env.example`):

| Variable            | Description                                |
| ------------------- | ------------------------------------------ |
| DATABASE\_\_URI     | _PostgreSQL connection string_             |
| REDIS_URL           | _Redis address_                            |
| keycloak\_\_\*      | _Keycloak admin/openid settings_           |
| minio\_\_\*         | _MinIO access_                             |
| FREEDOM_PAY\_\_\*   | _FreedomPay credentials_                   |
| telegram_bot\_\_\*  | _Telegram bot token for notifications_     |
| APPLE_OAUTH\_\_\*   | _Apple OAuth (client_id, team_id, key_id)_ |
| FIREBASE\_\_ENABLED | _Enable Firebase push notifications_       |

## Linting & Formatting

The project uses **ruff** for linting, import sorting, and formatting.

- Run checks manually:
  ```bash
  ruff check .
  ruff format --check .
  ```
- Auto-fix issues:
  ```bash
  ruff check --fix .
  ruff format .
  ```
  Pre-commit hooks run these automatically on every commit.

## CI/CD (GitLab CI)

The pipeline consists of four stages:

- **lint** — ruff checks

- **safety** — vulnerability audit with pip-audit

- **build** — Docker image build (with BuildKit caching) and push to GitLab Container Registry

- **deploy** — deploy to production server (stops old container, starts new one with mounted secrets)

### Production server requirements:

- Directory `/var/www/lumi/secrets/` containing the actual secret files

- Directory `/var/www/lumi/uploads/` for uploaded files

- Docker installed and accessible by the GitLab runner

## Monitoring

The `docker-compose.yml` includes optional monitoring services:

- **Prometheus** (port 9090) — metrics collection

- **Grafana** (port 3000) — dashboards

- **Loki + Promtail** — log aggregation

- **cAdvisor, node-exporter, postgres-exporter, redis-exporter** — system and database metrics

## Useful Commands

- Rebuild and restart all containers:

  ```bash
  docker-compose down && docker-compose up -d --build
  ```

- Apply database migrations manually (if not auto‑run):

  ```bash
  docker exec -it lumi-backend alembic upgrade head
  ```

- View logs:

  ```bash
  docker-compose logs -f backend
  ```
