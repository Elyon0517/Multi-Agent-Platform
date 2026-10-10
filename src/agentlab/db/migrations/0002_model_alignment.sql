BEGIN;
ALTER TABLE project ADD COLUMN IF NOT EXISTS goal text NOT NULL DEFAULT '';
ALTER TABLE project ADD COLUMN IF NOT EXISTS phases jsonb NOT NULL DEFAULT '[]';
ALTER TABLE memory ALTER COLUMN project_id DROP NOT NULL;
ALTER TABLE memory ADD COLUMN IF NOT EXISTS source text NOT NULL DEFAULT '';
ALTER TABLE memory DROP CONSTRAINT IF EXISTS memory_kind_check;
ALTER TABLE memory ADD CONSTRAINT memory_kind_check
    CHECK (kind IN ('episodic', 'semantic', 'procedural', 'document', 'note'));
COMMIT;
