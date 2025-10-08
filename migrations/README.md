This project includes a minimal Alembic scaffold and a migration to add a UNIQUE constraint on the `vote.user_id` column.

How to run migrations (dev):

1. Install alembic in your environment:

   pip install alembic

2. Set the SQLALCHEMY URL in `migrations/alembic.ini` or export as an env var:

   export DATABASE_URL=sqlite:///instance/app.db

3. Run the migration:

   alembic -c migrations/alembic.ini upgrade head

Notes:
- SQLite does not support altering table constraints in-place easily. If you use SQLite for development, the simplest path is to recreate the DB (delete `instance/app.db` and rerun the app's init script) which will pick up the new model constraint when the DB is re-created. For production databases (Postgres/MySQL) the Alembic migration above will add the constraint.
