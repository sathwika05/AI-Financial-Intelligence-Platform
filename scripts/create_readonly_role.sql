-- A SELECT-only role for the generated-SQL path.
--
-- validate_sql_query blocks INSERT, UPDATE, DELETE, ALTER, DROP, CREATE and
-- TRUNCATE by regex, which enumerates badness: it does not cover COPY,
-- GRANT, pg_sleep, pg_read_file, or reads of pg_catalog. That layer stays,
-- because a clear error beats a permission failure, but it should not be
-- the only thing between a model-written query and the database.
--
-- With this role a bypass of the regex still cannot write. The model can be
-- argued with; a privilege cannot.
--
--   psql -U finuser -d findb -f scripts/create_readonly_role.sql
--
-- Then set in .env:
--   READONLY_DATABASE_URL=postgresql+asyncpg://finreader:<password>@localhost:5433/findb

DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'finreader') THEN
        CREATE ROLE finreader LOGIN PASSWORD 'finreader';
    END IF;
END
$$;

-- Connect and read the application schema, nothing else.
GRANT CONNECT ON DATABASE findb TO finreader;
GRANT USAGE ON SCHEMA public TO finreader;

GRANT SELECT ON ALL TABLES IN SCHEMA public TO finreader;

-- Tables created by a later migration are covered without revisiting this.
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT SELECT ON TABLES TO finreader;

-- Explicit, so a future GRANT ALL on the schema cannot quietly restore them.
REVOKE INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER
    ON ALL TABLES IN SCHEMA public FROM finreader;

REVOKE CREATE ON SCHEMA public FROM finreader;
