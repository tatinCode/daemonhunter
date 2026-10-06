# DaemonHunter

DaemonHunter is a self-hosted homelab and server monitoring dashboard. One
device acts as the central monitoring server while Raspberry Pis, Linux
servers, and other network devices are added as monitored nodes.

The project is in early development. The current implementation provides the
FastAPI backend foundation, a health endpoint, and SQLite persistence managed
with SQLAlchemy and Alembic.

## Planned Features

- Add, list, and remove monitored devices
- Check device availability using ping
- Collect CPU, memory, disk, temperature, uptime, and hostname data through a
  lightweight Python agent
- Display the latest device status and metrics in a web dashboard
- Run the central server with Docker Compose

Future work may include service checks, LAN discovery, metric history, alerts,
authentication, and Docker container monitoring.

## Development Setup

DaemonHunter uses [uv](https://docs.astral.sh/uv/) for Python dependency and
environment management.

Clone the repository and install the dependencies:

```bash
git clone git@github.com:tatinCode/daemonhunter.git
cd daemonhunter
uv sync
```

Apply the database migrations:

```bash
uv run alembic upgrade head
```

Start the development server:

```bash
uv run uvicorn daemonhunter.main:app --reload
```

The API is then available at `http://127.0.0.1:8000`.

## Database

DaemonHunter uses SQLite by default. When `XDG_DATA_HOME` contains an absolute
path, the database is stored at:

```text
$XDG_DATA_HOME/daemonhunter/daemonhunter.db
```

If `XDG_DATA_HOME` is unset, empty, or relative, DaemonHunter falls back to:

```text
~/.local/share/daemonhunter/daemonhunter.db
```

DaemonHunter sets the application data directory to mode `0700` and the
database file to mode `0600`.

The database URL can be overridden through the
`DAEMONHUNTER_DATABASE_URL` environment variable:

```bash
DAEMONHUNTER_DATABASE_URL=sqlite:///./custom.db uv run alembic upgrade head
```

Explicit database URLs are used unchanged. DaemonHunter does not create their
parent directories or adjust their permissions.

### Moving an Existing Database

Earlier versions stored `daemonhunter.db` in the project directory. Stop
DaemonHunter before moving that database. If SQLite `-wal` or `-shm` sidecar
files exist, move them with the main database:

```bash
case "${XDG_DATA_HOME:-}" in
    /*) data_directory="$XDG_DATA_HOME/daemonhunter" ;;
    *) data_directory="$HOME/.local/share/daemonhunter" ;;
esac

mkdir -p "$data_directory"
chmod 700 "$data_directory"

for suffix in "" "-wal" "-shm"; do
    if [ -e "./daemonhunter.db${suffix}" ]; then
        mv "./daemonhunter.db${suffix}" \
            "$data_directory/daemonhunter.db${suffix}"
        chmod 600 "$data_directory/daemonhunter.db${suffix}"
    fi
done
```

Alternatively, set `DAEMONHUNTER_DATABASE_URL` to an absolute URL pointing to
the existing database.

After changing a SQLAlchemy model, generate a migration:

```bash
uv run alembic revision --autogenerate -m "describe the schema change"
```

Review the generated migration before applying it. Then upgrade the database:

```bash
uv run alembic upgrade head
```

Inspect the current and available migration revisions:

```bash
uv run alembic current
uv run alembic history
```

Check whether the models contain schema changes that have not been migrated:

```bash
uv run alembic check
```

## API

Current endpoints:

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/` | Basic application response |
| `GET` | `/api/v1/health` | Backend health check |

Interactive API documentation is available at:

- Swagger UI: `http://127.0.0.1:8000/docs`
- ReDoc: `http://127.0.0.1:8000/redoc`

## Testing

Run the test suite with:

```bash
uv run pytest
```

## Architecture

DaemonHunter will consist of two main components:

- **Central server:** FastAPI API, monitoring services, database, and web
  dashboard
- **Agent:** Lightweight Python process that collects local system metrics and
  reports them to the central server

The agent will communicate only with the API and will not access the database
directly.

Additional design notes are available in [`documentation/`](documentation/).

## MVP Development Order

1. FastAPI backend foundation
2. SQLite database foundation
3. Device management API
4. Ping monitoring
5. Basic dashboard
6. Monitoring agent
7. Metrics ingestion
8. Docker deployment
