# ADR 001: USE SQLite for MVP

##Context

Daemon hunter requires persistent storage for monitored devices 
and their last metrics

##Decision

Use SQLite for the initial implementation. Might change or not change

##Reasoning

- Simple development
- No separate database server
- Suitable for a single-instance homelab application
- Easy to backup
- SQLAlchemy allows migration to PostgreSQL later

##Alternatives Considered

###PostgreSQL

More scalable and better for concurrent workloads, but adds deployment
and configuration complexity that isn't necessary for the MVP

###Consequences

SQLite may start to become a problem once metric history and concurrent writes
increases significantly. But that's where SQLAlchemy comes in to migrate
everything into PostgreSQL later.




