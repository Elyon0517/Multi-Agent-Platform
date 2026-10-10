CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS project (
    id text PRIMARY KEY,
    name text NOT NULL,
    goal text NOT NULL DEFAULT '',
    phases jsonb NOT NULL DEFAULT '[]',
    workspace_path text NOT NULL,
    config_ref text,
    budget_cents numeric NOT NULL DEFAULT 5000,
    default_language text,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS agent_def (
    id text PRIMARY KEY,
    project_id text REFERENCES project(id),
    role text NOT NULL,
    system_prompt_ref text NOT NULL,
    model_policy jsonb NOT NULL,
    tool_grants text[] NOT NULL DEFAULT '{}',
    version int NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS run (
    id text PRIMARY KEY,
    project_id text NOT NULL,
    goal text NOT NULL,
    workspace text NOT NULL,
    language text,
    policy text NOT NULL DEFAULT 'auto',
    status text NOT NULL,
    max_iter int NOT NULL,
    iteration_base int NOT NULL DEFAULT 0,
    budget_cents numeric NOT NULL,
    cost_cents numeric NOT NULL DEFAULT 0,
    tokens_in bigint NOT NULL DEFAULT 0,
    tokens_out bigint NOT NULL DEFAULT 0,
    paused_reason text,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS iteration (
    id text PRIMARY KEY,
    run_id text NOT NULL REFERENCES run(id),
    n int NOT NULL,
    phase text NOT NULL,
    gate_result jsonb,
    verdicts jsonb NOT NULL DEFAULT '[]',
    diff_hash text NOT NULL,
    finding_set jsonb NOT NULL DEFAULT '[]',
    UNIQUE (run_id, n)
);

CREATE TABLE IF NOT EXISTS step (
    id text PRIMARY KEY,
    run_id text NOT NULL REFERENCES run(id),
    iteration_n int NOT NULL,
    role text NOT NULL,
    model_alias text NOT NULL,
    model text NOT NULL,
    prompt_ref text,
    response_ref text,
    tool_calls jsonb NOT NULL DEFAULT '[]',
    tokens_in int NOT NULL DEFAULT 0,
    tokens_out int NOT NULL DEFAULT 0,
    cost_cents numeric NOT NULL DEFAULT 0,
    latency_ms int NOT NULL DEFAULT 0,
    parent_step_id text REFERENCES step(id),
    attempt_count int NOT NULL DEFAULT 1,
    retry_reasons jsonb NOT NULL DEFAULT '[]',
    routing_reason text NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS artifact (
    id text PRIMARY KEY,
    run_id text NOT NULL REFERENCES run(id),
    kind text NOT NULL,
    content_ref text NOT NULL,
    sha256 text NOT NULL,
    created_by_step text REFERENCES step(id),
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS blackboard (
    id bigserial PRIMARY KEY,
    project_id text NOT NULL,
    run_id text,
    key text NOT NULL,
    value jsonb NOT NULL,
    version int NOT NULL DEFAULT 1,
    updated_by text NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (project_id, key)
);

CREATE TABLE IF NOT EXISTS memory (
    id text PRIMARY KEY,
    project_id text,
    namespace text NOT NULL,
    kind text NOT NULL CHECK (kind IN ('episodic', 'semantic', 'procedural', 'document', 'note')),
    text text NOT NULL,
    embedding vector(3072),
    embedding_model text,
    embedding_version int,
    source text NOT NULL DEFAULT '',
    source_run_id text,
    valid_from timestamptz NOT NULL DEFAULT now(),
    valid_to timestamptz,
    superseded_by text REFERENCES memory(id),
    pinned boolean NOT NULL DEFAULT false,
    tsv tsvector GENERATED ALWAYS AS (to_tsvector('simple', text)) STORED
);
CREATE INDEX IF NOT EXISTS memory_tsv_idx ON memory USING gin (tsv);
CREATE INDEX IF NOT EXISTS memory_scope_idx ON memory (project_id, namespace, kind) WHERE valid_to IS NULL;

CREATE TABLE IF NOT EXISTS approval (
    id text PRIMARY KEY,
    run_id text NOT NULL REFERENCES run(id),
    reason text NOT NULL,
    on_approve text NOT NULL,
    payload jsonb NOT NULL DEFAULT '{}',
    status text NOT NULL DEFAULT 'pending',
    decided_by text,
    feedback text,
    decided_at timestamptz
);

CREATE TABLE IF NOT EXISTS event (
    run_id text NOT NULL REFERENCES run(id),
    seq int NOT NULL,
    ts timestamptz NOT NULL DEFAULT now(),
    type text NOT NULL,
    actor text NOT NULL,
    payload jsonb NOT NULL DEFAULT '{}',
    PRIMARY KEY (run_id, seq)
);
