-- Commandline connection to the database with the following command: 
-- psql -h kantonsrat-database.postgres.database.azure.com -p 5432 -U kantonsratadmin -d kantonsrat

-- Table Definition ----------------------------------------------
CREATE TABLE "SESSION" (
    id integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    date date NOT NULL,
    title text,
    filename text UNIQUE,
    insert_ts timestamp without time zone,
    update_ts timestamp without time zone
);

-- Table Definition ----------------------------------------------
CREATE TABLE "PARAGRAPH" (
    id integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    item_of_business text,
    speaker_text text,
    speaker_entry_id integer REFERENCES "POLITICIAN"(id),
    in_admin_role boolean NOT NULL,
    text text,
    session_id integer NOT NULL REFERENCES "SESSION"(id),
    insert_ts timestamp without time zone
);