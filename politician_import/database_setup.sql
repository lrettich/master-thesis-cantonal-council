-- Commandline connection to the database with the following command:
-- psql -h kantonsrat-database.postgres.database.azure.com -p 5432 -U kantonsratadmin -d kantonsrat

CREATE TABLE "POLITICIAN" (
    id integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    person_id integer NOT NULL,
    ts_id text UNIQUE,
    first_name text,
    last_name text,
    council text,
    party text,
    valid_from date,
    valid_to date,
    insert_ts timestamp without time zone,
    update_ts timestamp without time zone
);