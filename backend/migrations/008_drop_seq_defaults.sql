-- Remove DEFAULT nextval() from primary key columns.
-- Our INSERT statements call nextval() explicitly; having both a column DEFAULT
-- and an explicit nextval() in the VALUES clause confuses DuckDB 1.5.2's MVCC
-- undo log, corrupting the primary index and causing FatalException on UPDATE.
ALTER TABLE raw_items   ALTER COLUMN id DROP DEFAULT;
ALTER TABLE embeddings  ALTER COLUMN id DROP DEFAULT;
ALTER TABLE clusters    ALTER COLUMN id DROP DEFAULT;
ALTER TABLE read_events ALTER COLUMN id DROP DEFAULT;
