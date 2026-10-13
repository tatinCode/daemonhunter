# Development Approach

## MVP

The initial goal is to create a central monitoring server capable of
registering devices and determining whether they are online.

## Development Order

1. Backend foundation - complete
2. Database foundation - complete
3. Device management API - complete
4. Admin Authentication and guest visibility - complete
5. Ping monitoring and status transition logging - complete
6. Basic dashboard
7. Monitoring agent
8. Metrics ingestion
9. Configured service and port checks
10. Docker deployment

## Completed Milestones

### Backend Foundation

- Set up FastAPI
- Add a versioned health endpoint
- Add pytest
- Establish the 'src/' package structure

### Database Foundation

- Add SQLAlchemy and Alembic
- Configure SQLite through an environment variable
- Add the database engine and session factory
- Define the 'device' model
- Add admin-only and guest-visibleb device config
- Create and apply the initial Alembic migration
- Test device persistence with a temporary database

### Admin Authentication

- Require a first-run setup token before the owner account can be created
- Hash owner and admin passwords with Argon2
- Issue a signed, per-user session cookie on setup and login
- Revoke sessions on logout by rotating the per-user session secret
- Reject reused passwords and stale writes with per-row version checks
- Support owner password reset, admin password reset, and ownership transfer
- Add a factory-reset command that clears application data while preserving
  the database schema

### Device Management API

- Add Pydantic schemas for creating, updating, and returning devices
- Add FastAPI database-session dependency injection
- Create, list, retrieve, update, and delete devices
- Return not-found and duplicate-device errors
- Test device persistence with an isolated SQLite database

### Ping Monitoring

- Add per-device consecutive-failure counters with a three-failure
  offline threshold
- Record every status transition in a `device_status_events` table that
  is deleted with its device
- Enable SQLite foreign-key enforcement
- Probe hosts with `ping` through an injectable function
- Add a `daemonhunter monitor --interval` worker with its own Alembic
  migration for existing databases
- Add an admin-only status-history endpoint, newest first


## Current Milestone

### Basic Dashboard

#### Goals

- Render a guest-visible device status page
- Show each device's name, host, and current status
- Refresh statuses automatically while the page is open
- Serve the page from the existing FastAPI process
- Keep the dashboard read-only

#### Out of Scope

- Monitoring agents
- Metrics ingestion
- Configured service and port checks
- Docker deployment
