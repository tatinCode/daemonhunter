# DaemonHunter

DaemonHunter is a self-hosted homelab and server monitoring dashboard. One
device acts as the central monitoring server while Raspberry Pis, Linux
servers, and other network devices are added as monitored nodes.

The project is in early development. The current implementation provides the
FastAPI backend foundation, a health endpoint, SQLite persistence managed
with SQLAlchemy and Alembic, device management, and owner and admin
authentication with signed session cookies.

## Planned Features

- Add, list, and remove monitored devices
- Check device availability using ping
- Collect CPU, memory, disk, temperature, uptime, and hostname data through a
  lightweight Python agent
- Display the latest device status and metrics in a web dashboard
- Run the central server with Docker Compose

Future work may include service checks, LAN discovery, metric history, alerts,
and Docker container monitoring.

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

## Configuration

| Variable | Default | Description |
| --- | --- | --- |
| `DAEMONHUNTER_DATABASE_URL` | XDG path | SQLAlchemy database URL. Path and permission behavior is documented under [Database](#database). |
| `DAEMONHUNTER_SETUP_TOKEN` | generated at first run | Token required to create the owner account. Must be at least 32 characters. |
| `DAEMONHUNTER_COOKIE_SECURE` | `false` | Set to `1`, `true`, `yes`, or `on` to send the session cookie with the `Secure` attribute. Enable this when serving over HTTPS. |

When `DAEMONHUNTER_SETUP_TOKEN` is not set, DaemonHunter generates a token
and logs it at startup as `First-run setup token was: <token>`.

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

## Authentication

DaemonHunter ships with owner and admin accounts, guest visibility, and
session-based authentication.

### First-Run Setup

Create the owner account by posting to `POST /api/v1/auth/setup` with a
username, a password of at least 12 characters, and the setup token. The
owner account can be created only once; later attempts return `409`.

```bash
curl -X POST http://127.0.0.1:8000/api/v1/auth/setup \
    -H 'Content-Type: application/json' \
    -d '{"username":"owner","password":"correct horse battery staple","setup_token":"<token>"}'
```

### Sessions

Successful setup and login set the `daemonhunter_session` cookie with:

- `HttpOnly`
- `SameSite=lax`
- `Path=/`
- `Max-Age=1209600` (14 days)
- `Secure`, only when `DAEMONHUNTER_COOKIE_SECURE` is enabled

The cookie value is signed with a per-user session secret, so rotating that
secret invalidates every copy of it. `POST /api/v1/auth/logout` clears the
cookie and rotates the secret, logging out any other holder of the token.
`POST /api/v1/auth/change-password` rotates it as well.

### Owner Recovery

If the owner password is lost, stop DaemonHunter and run:

```bash
uv run daemonhunter reset-owner-password
```

The command prompts for a new password twice, requires 12 to 128
characters, rotates the owner's session secret so every existing session is
logged out, and reactivates the owner account.

## Factory Reset

`factory-reset` deletes every user and device so DaemonHunter returns to
its first-run state.

```bash
uv run daemonhunter factory-reset
```

Stop DaemonHunter before running the command, then type the confirmation
phrase exactly:

| Mode | Confirmation |
| --- | --- |
| default | `RESET DAEMONHUNTER` |
| `--no-backup` | `RESET DAEMONHUNTER WITHOUT BACKUP` |

By default a consistent copy of the database is written first to
`<database directory>/backups/` with directory mode `0700` and file mode
`0600`, and its path is printed when the reset finishes. `--no-backup`
skips that copy and therefore requires the longer confirmation phrase.

**The reset preserves the database schema.** It clears application rows in
place inside a single transaction. It does not delete the database file,
delete `-wal` or `-shm` sidecar files, run migrations, or move the file,
so an existing database stays on its current migration revision.

The reset aborts and leaves the database untouched if it is unreadable, if
SQLite journaling is disabled, if it is locked by another process, or if
anything is written to it while the backup is being taken.

## API

Current endpoints:

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/` | Basic application response |
| `GET` | `/api/v1/health` | Backend health check |
| `GET` | `/api/v1/auth/setup-status` | Whether the owner account still needs to be created |
| `POST` | `/api/v1/auth/setup` | Create the owner account and start a session |
| `POST` | `/api/v1/auth/login` | Start a session |
| `POST` | `/api/v1/auth/logout` | Clear the session cookie and revoke the token |
| `GET` | `/api/v1/auth/me` | Current user |
| `POST` | `/api/v1/auth/change-password` | Change the current user's password |
| `GET` | `/api/v1/devices` | Guest-visible devices |
| `GET` | `/api/v1/devices/{device_id}` | One guest-visible device |
| `GET` | `/api/v1/admin/devices` | All devices |
| `POST` | `/api/v1/admin/devices` | Create a device |
| `GET` | `/api/v1/admin/devices/{device_id}` | One device |
| `PATCH` | `/api/v1/admin/devices/{device_id}` | Update a device |
| `DELETE` | `/api/v1/admin/devices/{device_id}` | Delete a device |
| `GET` | `/api/v1/admin/users` | All users |
| `POST` | `/api/v1/admin/users` | Create an admin with a temporary password |
| `GET` | `/api/v1/admin/users/{user_id}` | One user |
| `PATCH` | `/api/v1/admin/users/{user_id}` | Rename or deactivate a user |
| `DELETE` | `/api/v1/admin/users/{user_id}` | Delete a user |
| `POST` | `/api/v1/admin/users/{user_id}/reset-password` | Reset a user's password |
| `POST` | `/api/v1/admin/users/{user_id}/transfer-ownership` | Transfer ownership |

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
4. Admin authentication and guest visibility
5. Ping monitoring
6. Basic dashboard
7. Monitoring agent
8. Metrics ingestion
9. Docker deployment
