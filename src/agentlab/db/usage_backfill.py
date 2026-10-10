"""Backfill only after every registered project has reached the new schema."""

from sqlalchemy import text
from sqlalchemy.engine import Connection


def backfill_usage(connection: Connection, base: str) -> None:
    quote = connection.dialect.identifier_preparer.quote
    ledger = f"{quote(base)}.usage_ledger"
    marker = f"{quote(base)}.state_record"
    if connection.execute(
        text(f"SELECT 1 FROM {marker} WHERE kind='migration' AND key='usage_monitor_backfill'")
    ).first():
        return
    # Read registered project schemas without changing search_path or their data.
    bind = connection
    quote = bind.dialect.identifier_preparer.quote
    registry = f"{quote(base)}.project_schema"
    exists = bind.execute(text("SELECT to_regclass(:name)"), {"name": registry}).scalar_one()
    schemas = list(bind.execute(text(f"SELECT schema_name FROM {registry}")).scalars()) if exists else []
    schemas.append(base)
    for schema in schemas:
        q = quote(schema)
        connection.execute(
            text(f"""INSERT INTO {ledger}
            (id,ts,role,model_alias,model,tokens_in,tokens_out,cost_cents,source,ref_id,project_id,metered)
            SELECT 'legacy-attempt-'||a.key,a.updated_at,a.data->>'role',
                   coalesce(a.data->>'alias','unknown'),coalesce(a.data->>'model','unknown'),
                   coalesce((a.data->'usage'->>'tokens_in')::bigint,0),
                   coalesce((a.data->'usage'->>'tokens_out')::bigint,0),
                   coalesce((a.data->'usage'->>'cost_cents')::numeric,0),
                   'run',a.data->>'run_id',r.project_id,a.data ? 'usage'
            FROM {q}.state_record a JOIN {q}.run r ON r.id=a.data->>'run_id'
            WHERE a.kind='attempt' AND a.data->>'role' IS NOT NULL
              AND NOT EXISTS (SELECT 1 FROM {ledger} l WHERE l.source='run'
                  AND l.ref_id=r.id AND l.id NOT LIKE 'legacy-%')
            ON CONFLICT (id) DO NOTHING""")
        )
        connection.execute(
            text(f"""INSERT INTO {ledger}
            (id,role,model_alias,model,tokens_in,tokens_out,cost_cents,source,ref_id,project_id,metered,calls)
            SELECT 'legacy-step-'||s.id,s.role,s.model_alias,s.model,
                   s.tokens_in,s.tokens_out,s.cost_cents,'run',s.run_id,r.project_id,true,
                   greatest(s.attempt_count,1)
            FROM {q}.step s JOIN {q}.run r ON r.id=s.run_id
            WHERE NOT EXISTS (SELECT 1 FROM {ledger} l WHERE l.source='run'
                AND l.ref_id=r.id AND l.id NOT LIKE 'legacy-%')
              AND NOT EXISTS (SELECT 1 FROM {q}.state_record a
                WHERE a.kind='attempt' AND a.data->>'run_id'=s.run_id
                  AND a.data->>'role'=s.role
                  AND (a.data->'batch_key'->>2)::integer=s.iteration_n)
            ON CONFLICT (id) DO NOTHING""")
        )
        connection.execute(
            text(f"""INSERT INTO {ledger}
            (id,ts,role,model_alias,model,tokens_in,tokens_out,cost_cents,source,ref_id,project_id,metered,calls)
            SELECT 'legacy-turn-'||id,coalesce((payload->>'created_at')::timestamptz,now()),
                   'root',coalesce(payload->>'model_alias','unknown'),coalesce(payload->>'model','unknown'),
                   coalesce((payload->>'tokens_in')::bigint,0),coalesce((payload->>'tokens_out')::bigint,0),
                   coalesce((payload->>'cost_cents')::numeric,0),'turn',id,project_id,
                   (coalesce((payload->>'tokens_in')::bigint,0)+coalesce((payload->>'tokens_out')::bigint,0)>0),
                   greatest(jsonb_array_length(coalesce(payload->'attempts','[]'::jsonb)),1)
            FROM {q}.root_turn t WHERE NOT EXISTS (SELECT 1 FROM {ledger} l
                WHERE l.source='turn' AND l.ref_id=t.id AND l.id NOT LIKE 'legacy-%') ON CONFLICT (id) DO NOTHING""")
        )

        connection.execute(
            text(f"""INSERT INTO {ledger}
            (id,ts,role,model_alias,model,tokens_in,tokens_out,cost_cents,source,ref_id,project_id,metered,calls)
            SELECT 'legacy-planning-'||key,updated_at,'project-planner','unknown','unknown',
                   coalesce((data->>'tokens_in')::bigint,0),coalesce((data->>'tokens_out')::bigint,0),
                   coalesce((data->>'cost_cents')::numeric,0),'planning',key,data->>'project_id',
                   (coalesce((data->>'tokens_in')::bigint,0)+coalesce((data->>'tokens_out')::bigint,0)>0),
                   greatest((SELECT count(*)::integer FROM {q}.state_record c
                             WHERE c.kind='planning_call' AND c.data->>'planning_id'=p.key),1)
            FROM {q}.state_record p WHERE kind='planning'
              AND NOT EXISTS (SELECT 1 FROM {ledger} l WHERE l.source='planning'
                AND l.ref_id=p.key AND l.id NOT LIKE 'legacy-%') ON CONFLICT (id) DO NOTHING""")
        )

    connection.execute(
        text(f"INSERT INTO {marker} (kind,key,data) VALUES ('migration','usage_monitor_backfill','{{}}')")
    )
