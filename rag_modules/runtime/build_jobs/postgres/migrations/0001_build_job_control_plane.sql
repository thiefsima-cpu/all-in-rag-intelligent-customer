CREATE SCHEMA IF NOT EXISTS graph_rag_control_plane;

CREATE TABLE graph_rag_control_plane.build_jobs (
    job_id text PRIMARY KEY CHECK (job_id ~ '^[0-9a-f]{32}$'),
    request_id text NOT NULL,
    job_type text NOT NULL CHECK (job_type IN ('build', 'rebuild')),
    status text NOT NULL CHECK (
        status IN (
            'queued', 'claimed', 'running', 'cancel_requested',
            'succeeded', 'failed', 'cancelled', 'interrupted'
        )
    ),
    revision integer NOT NULL CHECK (revision >= 1),
    created_at timestamptz NOT NULL,
    started_at timestamptz,
    finished_at timestamptz,
    message text NOT NULL DEFAULT '',
    error jsonb,
    logs jsonb NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(logs) = 'array'),
    result jsonb,
    retry_of_job_id text CHECK (
        retry_of_job_id IS NULL OR retry_of_job_id ~ '^[0-9a-f]{32}$'
    ),
    idempotency_key_hash text NOT NULL DEFAULT '',
    worker_id text,
    runner_backend text,
    lease_token text NOT NULL DEFAULT '',
    lease_expires_at timestamptz,
    archived_at timestamptz,
    updated_at timestamptz NOT NULL
);

CREATE TABLE graph_rag_control_plane.build_job_events (
    job_id text NOT NULL REFERENCES graph_rag_control_plane.build_jobs(job_id),
    revision integer NOT NULL CHECK (revision >= 1),
    event_id text NOT NULL UNIQUE,
    event_type text NOT NULL CHECK (
        event_type IN (
            'queued', 'claimed', 'started', 'progress_recorded',
            'cancellation_requested', 'cancelled', 'succeeded', 'failed', 'interrupted'
        )
    ),
    schema_version integer NOT NULL,
    occurred_at timestamptz NOT NULL,
    request_id text NOT NULL,
    payload jsonb NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
    PRIMARY KEY (job_id, revision)
);

CREATE UNIQUE INDEX build_jobs_idempotency_uq
    ON graph_rag_control_plane.build_jobs (idempotency_key_hash)
    WHERE idempotency_key_hash <> '';
CREATE UNIQUE INDEX build_jobs_one_active_uq
    ON graph_rag_control_plane.build_jobs ((true))
    WHERE archived_at IS NULL
      AND status IN ('queued', 'claimed', 'running', 'cancel_requested');
CREATE INDEX build_jobs_list_idx
    ON graph_rag_control_plane.build_jobs (created_at DESC, job_id DESC)
    WHERE archived_at IS NULL;
CREATE INDEX build_jobs_status_list_idx
    ON graph_rag_control_plane.build_jobs (status, created_at DESC, job_id DESC)
    WHERE archived_at IS NULL;
CREATE INDEX build_jobs_claim_idx
    ON graph_rag_control_plane.build_jobs (created_at, job_id)
    WHERE archived_at IS NULL AND status = 'queued';
CREATE INDEX build_jobs_lease_expiry_idx
    ON graph_rag_control_plane.build_jobs (lease_expires_at, job_id)
    WHERE archived_at IS NULL
      AND status IN ('claimed', 'running', 'cancel_requested');
CREATE INDEX build_jobs_terminal_retention_idx
    ON graph_rag_control_plane.build_jobs (finished_at DESC, job_id DESC)
    WHERE archived_at IS NULL
      AND status IN ('succeeded', 'failed', 'cancelled', 'interrupted');
CREATE INDEX build_jobs_archive_purge_idx
    ON graph_rag_control_plane.build_jobs (archived_at, job_id)
    WHERE archived_at IS NOT NULL;
CREATE INDEX build_job_events_list_idx
    ON graph_rag_control_plane.build_job_events (occurred_at DESC, event_id DESC);
