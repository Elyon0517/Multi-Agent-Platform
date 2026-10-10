from alembic import op

revision = "root_session"
down_revision = "project_threads"


def upgrade() -> None:
    # All identifiers resolve in the current migration scope; never qualify base tables.
    op.execute("""CREATE TABLE thread (
        id text PRIMARY KEY, project_id text, payload jsonb NOT NULL)""")
    op.execute("""CREATE TABLE message (
        id text PRIMARY KEY, thread_id text NOT NULL REFERENCES thread(id), project_id text,
        seq integer NOT NULL, author text NOT NULL CHECK(author IN ('user','assistant','system')),
        payload jsonb NOT NULL, UNIQUE(thread_id,seq))""")
    op.execute("""CREATE TABLE root_turn (
        id text PRIMARY KEY, thread_id text NOT NULL REFERENCES thread(id), project_id text,
        payload jsonb NOT NULL)""")
    op.execute("""INSERT INTO thread SELECT key, data->>'project_id', data-'messages'
        FROM state_record WHERE kind='thread'""")
    op.execute("""INSERT INTO message
        SELECT m.value->>'id', s.key, s.data->>'project_id', m.ordinality::integer,
               m.value->>'author', m.value || jsonb_build_object('seq', m.ordinality)
        FROM state_record s CROSS JOIN LATERAL
        jsonb_array_elements(COALESCE(s.data->'messages','[]'::jsonb)) WITH ORDINALITY m(value,ordinality)
        WHERE s.kind='thread'""")
    # The old JSON remains available as a data-preserving backup.


def downgrade() -> None:
    raise RuntimeError("Data-preserving migration")
