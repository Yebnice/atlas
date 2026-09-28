# Supabase database setup

1. Create a Supabase project.
2. Obtain the PostgreSQL connection string from the Supabase database connection settings.
3. Put the connection string into `DATABASE_URL` using the SQLAlchemy asyncpg scheme, for example:

`postgresql+asyncpg://USER:PASSWORD@HOST:5432/postgres?ssl=require`

4. Prefer a Supabase pooler when connection volume or scaling requires it. Supabase documents server-side pooling for horizontally scaled/serverless workloads.
5. Run `alembic upgrade head` from a trusted deployment environment.
6. Verify Cloud Run `/readyz` after migration.

Never put a Supabase service-role key in the browser. This application talks to PostgreSQL from the backend.
