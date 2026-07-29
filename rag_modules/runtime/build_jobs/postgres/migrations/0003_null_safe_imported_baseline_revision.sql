ALTER TABLE graph_rag_control_plane.build_jobs
    DROP CONSTRAINT build_jobs_revision_check;

ALTER TABLE graph_rag_control_plane.build_jobs
    ADD CONSTRAINT build_jobs_revision_check CHECK (
        (
            revision >= 1
            OR (revision = 0 AND import_source_schema_version = 2)
        ) IS TRUE
    );
