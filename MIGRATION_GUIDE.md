# SellMate Database Migration Guide

We use **Alembic** for versioned database migrations. This ensures that all schema changes are tracked, reversible, and consistent across environments.

## 1. Setup
Alembic is initialized in the `sellmate_backend/` directory. The configuration is stored in `alembic.ini`.

## 2. Creating a Migration
To create a new migration after changing the database models:
```bash
alembic revision --autogenerate -m "description of changes"
```

## 3. Applying Migrations
To upgrade the database to the latest version:
```bash
alembic upgrade head
```

## 4. Rolling Back
To rollback the last migration:
```bash
alembic downgrade -1
```

## 5. Production Rules
- Never modify the database schema manually.
- Always include a `downgrade` path in your migrations.
- Verify migrations in a staging environment before applying to production.
- Migrations are automatically validated on application startup.
