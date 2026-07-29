ALTER TABLE graph_rag_control_plane.build_jobs
    ADD COLUMN import_source_schema_version integer;

ALTER TABLE graph_rag_control_plane.build_jobs
    DROP CONSTRAINT build_jobs_revision_check;

ALTER TABLE graph_rag_control_plane.build_jobs
    ADD CONSTRAINT build_jobs_revision_check CHECK (
        revision >= 1
        OR (revision = 0 AND import_source_schema_version = 2)
    ),
    ADD CONSTRAINT build_jobs_import_source_schema_version_check CHECK (
        import_source_schema_version IS NULL OR import_source_schema_version = 2
    );

ALTER TABLE graph_rag_control_plane.build_job_events
    DROP CONSTRAINT build_job_events_revision_check,
    DROP CONSTRAINT build_job_events_event_type_check;

ALTER TABLE graph_rag_control_plane.build_job_events
    ADD CONSTRAINT build_job_events_revision_check CHECK (
        revision >= 1
        OR (revision = 0 AND event_type = 'baseline_imported')
    ),
    ADD CONSTRAINT build_job_events_event_type_check CHECK (
        event_type IN (
            'baseline_imported', 'queued', 'claimed', 'started', 'progress_recorded',
            'cancellation_requested', 'cancelled', 'succeeded', 'failed', 'interrupted'
        )
    );
