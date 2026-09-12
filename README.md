# DaemonHunter

DaemonHunter is a self-hosted homelab and server monitoring dashboard. One
device acts as the central monitoring server while Raspberry Pis, Linux
servers, and other network devices are added as monitored nodes.

The project is in early development. The current implementation provides the
FastAPI backend foundation and a health endpoint.

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

Start the development server:

```bash
uv run uvicorn daemonhunter.main:app --reload
```

The API is then available at `http://127.0.0.1:8000`.

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
