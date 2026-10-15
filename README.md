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
| `DAEMONHUNTER_LOGIN_RATE_LIMIT_ATTEMPTS` | `5` | Failed login or setup-token attempts allowed per client IP in each window. |
| `DAEMONHUNTER_LOGIN_RATE_LIMIT_WINDOW_SECONDS` | `300` | Sliding-window duration for login and setup-token failures. |
| `DAEMONHUNTER_TRUST_PROXY_HEADERS` | `false` | Use the last `X-Forwarded-For` address as the client IP. Enable only behind a trusted proxy that sanitizes this header and blocks direct access. |

When `DAEMONHUNTER_SETUP_TOKEN` is not set, DaemonHunter generates a token
and logs it at startup as `First-run setup token was: <token>`.

Login and first-run setup have separate, per-IP limits. By default, once five
failures have occurred within five minutes, further attempts receive `429`
and a `Retry-After` header. Concurrent in-flight attempts also occupy slots.
The limits are held in memory per server process; running multiple workers
does not provide a shared limit, and restarting the server clears the history.

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

## Monitoring

The monitor worker pings every registered device and records status
transitions. Run it alongside the web server:

```bash
uv run daemonhunter monitor
```

`--interval` sets the seconds between cycles and defaults to `60`:

```bash
uv run daemonhunter monitor --interval 30
```

The worker requires the `ping` command. On Raspberry Pi OS and Debian:

```bash
sudo apt install iputils-ping
```

Run only one monitor worker against a database. Multiple workers would
probe the same devices redundantly and record duplicate transitions.

Behavior:

- A successful ping sets the device to `online` and resets its failure
  counter.
- A failed ping increments the counter, but the device only becomes
  `offline` after three consecutive failures.
- Every status change is stored in `device_status_events` and can be read
  through the admin API.
- A device deleted through the admin API has its history deleted with it.

## Dashboard

Open `http://127.0.0.1:8000/` while the web server is running. The dashboard
shows real device reachability in a dark, responsive overview with a compact
six-device inventory, status filters, name sorting, and a selected-device detail panel.
The overview refreshes every five seconds while preserving your search, filter,
and selection. A failed refresh leaves the last loaded results visible with a notice.
Searches, status filters, sort order, and selected devices are kept in the page URL,
so reload, browser Back/Forward, and bookmarked links restore the same view.
Notifications distinguish success, errors, and information and can be dismissed.

Guests see only guest-visible devices and their statuses. Sign in with an owner
or admin account to see all devices, consecutive failures, last status-change times,
the three most recent activity entries, and up to 50 selected-device transitions.
The dashboard honors revoked sessions and required password changes. First-run owner
setup and temporary-password changes are available from the account dialog.

The **Add device** button is always visible in the top-right corner. If signed out,
it opens sign-in (or first-run owner setup), then continues to the device form after
authentication and any required password change. The sidebar also has a **Log in**
button, replaced by the username, role, and sign-out control once authenticated.

Admins can register a name and an IP address or hostname. Devices are private by default;
check **Share this device with guests**
to expose it on the guest dashboard. New devices start as `unknown`; run the
separate monitor worker to establish and update their reachability.

### Devices

The sidebar's **Devices** link opens `/devices`, the full inventory page. Search by
name or host, filter by status, and select a device for its details and history.
Ready admins can edit a device's name, host and visibility, toggle guest sharing
directly in the table, and delete devices after confirmation. Deletion also removes
their transition history. Guests get a read-only inventory of shared devices.
Links from Activity open this page with the relevant device selected.
On narrow screens the full inventory becomes labelled cards with sharing, Edit,
and Delete controls visible without horizontal scrolling.

### Activity

The sidebar's **Activity** link opens `/activity`. Signed-out users see a login prompt;
only ready admins can access status history. Search by device name or host, filter by
device, resulting status and a local date/time range, and browse 25, 50 or 100 events
per page. History is ordered by occurrence time and then event ID, newest first.
Pagination pins a snapshot so new events do not shift rows between pages. Page one
refreshes automatically; **Refresh latest** starts a fresh snapshot at page one.
Applied filters, pagination, and the snapshot ID are reflected in the URL and restored
when returning to the page. Date bounds in URLs use UTC; form controls show local time.
Background refresh uses a reserved header indicator so the history table stays in place.

This is a status-transition log, not an audit log: device creation, edits, deletion,
and user actions do not create entries. Deleting a device removes its status entries.

**Needs attention** counts offline and unknown devices. CPU, memory, uptime,
temperature, disk and ping latency are not yet collected and display as unavailable.
The selected-device chart plots actual recorded status transitions. Page refresh time
and last status-change time do not represent the last probe time.

Jinja2 renders the initial page, with locally served CSS, SVG icons and JavaScript.
No CDN, Node build step or external fonts are required. Dashboard pages, the
`/dashboard/state` refresh endpoint and private API responses send `Cache-Control: no-store`.
Without JavaScript, the initial device list remains readable and can be refreshed
manually; interactive forms require JavaScript or the existing API at `/docs`.

### Account

Signed-in owners and admins can open `/account` from the sidebar to view their
username and role and change their password voluntarily. Enter the current password,
a new password of 12–128 characters, and its confirmation. Changing the password
revokes other sessions while keeping the current session signed in. Users with a
temporary password can also complete their required password change here.

### Users

Ready owners can open `/users` to list accounts, create admins with temporary
passwords, rename admins, enable or disable accounts, reset passwords, and delete
admins after confirmation. Disabling an account or resetting its password revokes
its existing sessions; a reset requires a password change at the next login.
The owner row is protected from these admin-management actions. Guests and admins
cannot access the account list or perform owner-only operations. Losing owner access
clears the loaded list and closes account-management dialogs.

### Current Dashboard Limitations

- Named TCP-port checks and clickable service links are deferred; the agreed design
  is in [the development plan](documentation/plan.md).
- Agent metrics are not collected yet; CPU, memory, uptime and related fields remain
  unavailable.
- Ownership transfer is available through the existing API, not through the Users page.
- Global application settings are configured through environment variables rather
  than a dashboard settings editor.

## API

Current endpoints:

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/` | Device dashboard; guest or authenticated admin view |
| `GET` | `/devices` | Full inventory with admin management controls |
| `GET` | `/activity` | Status-history page with admin login gate |
| `GET` | `/account` | Signed-in profile and password-change page |
| `GET` | `/users` | Owner-only administrator-account management |
| `GET` | `/dashboard/state` | Dashboard refresh data with session-aware visibility |
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
| `GET` | `/api/v1/admin/devices/{device_id}/status-events` | Device status history, newest first |
| `GET` | `/api/v1/admin/status-events` | Filtered, paginated status activity across devices |
| `GET` | `/api/v1/admin/users` | All users |
| `POST` | `/api/v1/admin/users` | Create an admin with a temporary password |
| `GET` | `/api/v1/admin/users/{user_id}` | One user |
| `PATCH` | `/api/v1/admin/users/{user_id}` | Rename or deactivate a user |
| `DELETE` | `/api/v1/admin/users/{user_id}` | Delete a user |
| `POST` | `/api/v1/admin/users/{user_id}/reset-password` | Reset a user's password |
| `POST` | `/api/v1/admin/users/{user_id}/transfer-ownership` | Transfer ownership |

The paginated status-activity endpoint accepts `device_id`, `new_status`, `q`,
`start`, `end`, `page`, `limit` and `snapshot_id`. Date bounds are inclusive;
timezone-aware values are normalized to UTC and naive values are interpreted as UTC.
The response includes `items`, `total`, `page`, `limit` and `snapshot_id`. Pass the
returned snapshot ID on later pages to exclude newly inserted events. Pages beyond
the last available page are clamped to the last page, including after deletions.

Interactive API documentation is available at:

- Swagger UI: `http://127.0.0.1:8000/docs`
- ReDoc: `http://127.0.0.1:8000/redoc`

## Testing

Run the test suite with:

```bash
uv run pytest
```

Browser regression checks are optional and use temporary databases and a local test
server. Install the browser group and run them with:

```bash
uv run --group browser pytest tests/browser --run-browser -q
```

The tests use a system `chromium` or `chromium-browser` if available. Otherwise,
install Playwright's Chromium first:

```bash
uv run --group browser playwright install chromium
```

Set `DAEMONHUNTER_TEST_BROWSER` to use another Chromium executable. Browser tests
skip unless `--run-browser` is supplied, or when Playwright or a browser is
unavailable. To run the API and browser suites together:

```bash
uv run --group browser pytest --run-browser
```

GitHub Actions is configured to run the API tests on Python 3.11 and 3.14 and a
separate Chromium browser-test job on Python 3.14. That job installs Chromium and
its system dependencies and runs the browser suite with `--run-browser`.

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
5. Ping monitoring - complete
6. Basic dashboard - complete
7. Monitoring agent
8. Metrics ingestion
9. Docker deployment
