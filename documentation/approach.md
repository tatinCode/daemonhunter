# Development Approach

## MVP

The initial goal is to create a central monitoring server capable of
registering devices and determining whether they are online.

## Development Order

1. Backend foundation - complete
2. Database foundation- complete
3. Device management API
4. Admin Authentication and guest visibility 
5. Ping monitoring and status transition loggin
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


## Current Milestone



#### Goals

- Add Pydantic schemas for creating, updating, and returning devices
- Add FastAPI database-session dependency injection
- Create devices
- List devices
- Retrieve individual devices
- Update device names, hosts, and guest visibility
- Delete devices
- Return appropriate not-found and duplicate-device errors
- Add API tests using an isolated SQLite database

#### Out of Scope

- Authentication and authorization
- Ping and port monitoring
- Monitoring agents
- Metrics ingestion
- Dashboard
- Docker deployment
