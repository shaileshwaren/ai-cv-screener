-- Migration: Make match_id the primary key of candidates
-- Run this in Supabase SQL Editor (Dashboard → SQL Editor) before using the pipeline with match_id as PK.
--
-- Prerequisites:
--   - candidates table has a match_id column (TEXT).
--   - Existing rows have match_id populated (e.g. "job_id-candidate_id" from Manatal).

-- 1. Drop the existing primary key (if it is on candidate_id)
ALTER TABLE candidates
  DROP CONSTRAINT IF EXISTS candidates_pkey;

-- 2. Ensure match_id is non-null and unique (required for PK)
-- If you have rows with NULL match_id, backfill or delete them first.
UPDATE candidates SET match_id = (job_id::text || '-' || candidate_id::text) WHERE match_id IS NULL OR match_id = '';
ALTER TABLE candidates ALTER COLUMN match_id SET NOT NULL;

-- 3. Set match_id as the new primary key
ALTER TABLE candidates
  ADD PRIMARY KEY (match_id);

-- 4. (Optional) Keep candidate_id unique for reference
-- ALTER TABLE candidates ADD CONSTRAINT candidates_candidate_id_unique UNIQUE (candidate_id);
