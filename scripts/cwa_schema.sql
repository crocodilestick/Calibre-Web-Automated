CREATE TABLE IF NOT EXISTS cwa_enforcement(
    id INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL, 
    timestamp TEXT NOT NULL,
    book_id INTEGER NOT NULL, 
    book_title TEXT NOT NULL,
    author TEXT NOT NULL, 
    file_path TEXT NOT NULL, 
    trigger_type TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS cwa_import(
    id INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL,
    timestamp TEXT NOT NULL,
    filename TEXT NOT NULL,
    original_backed_up TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS cwa_conversions(
    id INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL,
    timestamp TEXT NOT NULL,
    filename TEXT NOT NULL,
    original_format TEXT NOT NULL,
    original_backed_up TEXT NOT NULL,
    end_format TEXT DEFAULT "" NOT NULL
);
CREATE TABLE IF NOT EXISTS epub_fixes(
    id INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL,
    timestamp TEXT NOT NULL,
    filename TEXT NOT NULL,
    manually_triggered TEXT NOT NULL,
    num_of_fixes_applied TEXT NOT NULL,
    original_backed_up TEXT NOT NULL,
    file_path TEXT NOT NULL,
    fixes_applied TEXT DEFAULT ""
);
CREATE TABLE IF NOT EXISTS cwa_settings(
    default_settings SMALLINT DEFAULT 1 NOT NULL,
    auto_backup_imports SMALLINT DEFAULT 1 NOT NULL,
    auto_backup_conversions SMALLINT DEFAULT 1 NOT NULL,
    auto_zip_backups SMALLINT DEFAULT 1 NOT NULL,
    cwa_update_notifications SMALLINT DEFAULT 1 NOT NULL,
    contribute_translations_notifications SMALLINT DEFAULT 1 NOT NULL,
    auto_convert SMALLINT DEFAULT 1 NOT NULL,
    auto_convert_target_format TEXT DEFAULT "epub" NOT NULL,
    auto_convert_ignored_formats TEXT DEFAULT "" NOT NULL,
    auto_ingest_ignored_formats TEXT DEFAULT "" NOT NULL,
    auto_convert_retained_formats TEXT DEFAULT "" NOT NULL,
    auto_ingest_automerge TEXT DEFAULT "new_record" NOT NULL,
    ingest_timeout_minutes INTEGER DEFAULT 15 NOT NULL,
    ingest_stale_temp_minutes INTEGER DEFAULT 120 NOT NULL,
    ingest_stale_temp_interval INTEGER DEFAULT 600 NOT NULL,
    auto_metadata_enforcement SMALLINT DEFAULT 1 NOT NULL,
    kindle_epub_fixer SMALLINT DEFAULT 1 NOT NULL,
    auto_backup_epub_fixes SMALLINT DEFAULT 1 NOT NULL,
    enable_mobile_blur SMALLINT DEFAULT 1 NOT NULL,
    auto_metadata_fetch_enabled SMALLINT DEFAULT 0 NOT NULL,
    auto_metadata_smart_application SMALLINT DEFAULT 0 NOT NULL,
    auto_metadata_update_title SMALLINT DEFAULT 1 NOT NULL,
    auto_metadata_update_authors SMALLINT DEFAULT 1 NOT NULL,
    auto_metadata_update_description SMALLINT DEFAULT 1 NOT NULL,
    auto_metadata_update_publisher SMALLINT DEFAULT 1 NOT NULL,
    auto_metadata_update_tags SMALLINT DEFAULT 1 NOT NULL,
    auto_metadata_update_series SMALLINT DEFAULT 1 NOT NULL,
    auto_metadata_update_rating SMALLINT DEFAULT 1 NOT NULL,
    auto_metadata_update_published_date SMALLINT DEFAULT 1 NOT NULL,
    auto_metadata_update_identifiers SMALLINT DEFAULT 1 NOT NULL,
    auto_metadata_update_cover SMALLINT DEFAULT 1 NOT NULL,
    metadata_provider_hierarchy TEXT DEFAULT '["ibdb","google","dnb"]' NOT NULL,
    metadata_providers_enabled TEXT DEFAULT '{}' NOT NULL,
    auto_send_delay_minutes INTEGER DEFAULT 5 NOT NULL,
    duplicate_detection_title SMALLINT DEFAULT 1 NOT NULL,
    duplicate_detection_author SMALLINT DEFAULT 1 NOT NULL,
    duplicate_detection_language SMALLINT DEFAULT 1 NOT NULL,
    duplicate_detection_series SMALLINT DEFAULT 0 NOT NULL,
    duplicate_detection_publisher SMALLINT DEFAULT 0 NOT NULL,
    duplicate_detection_format SMALLINT DEFAULT 0 NOT NULL,
    hardcover_auto_fetch_enabled SMALLINT DEFAULT 0 NOT NULL,
    hardcover_auto_fetch_schedule TEXT DEFAULT 'weekly' NOT NULL,
    hardcover_auto_fetch_schedule_day TEXT DEFAULT 'sunday' NOT NULL,
    hardcover_auto_fetch_schedule_hour INTEGER DEFAULT 2 NOT NULL,
    hardcover_auto_fetch_min_confidence REAL DEFAULT 0.85 NOT NULL,
    hardcover_auto_fetch_batch_size INTEGER DEFAULT 50 NOT NULL,
    hardcover_auto_fetch_rate_limit REAL DEFAULT 5.0 NOT NULL,
    -- Duplicate notification and auto-resolution settings
    duplicate_detection_enabled SMALLINT DEFAULT 1 NOT NULL,
    duplicate_notifications_enabled SMALLINT DEFAULT 1 NOT NULL,
    duplicate_auto_resolve_enabled SMALLINT DEFAULT 0 NOT NULL,
    duplicate_auto_resolve_strategy TEXT DEFAULT 'newest' NOT NULL,
    duplicate_auto_resolve_cooldown_minutes INTEGER DEFAULT 0 NOT NULL,  -- 0 = disabled, >0 = minutes between auto-resolutions
    duplicate_format_priority TEXT DEFAULT '{"EPUB":100,"KEPUB":95,"AZW3":90,"MOBI":80,"AZW":75,"PDF":60,"TXT":40,"CBZ":35,"CBR":35,"FB2":30,"DJVU":25,"HTML":20,"RTF":15,"DOC":10,"DOCX":10}' NOT NULL,
    -- Duplicate scanning performance settings
    duplicate_detection_use_sql SMALLINT DEFAULT 1 NOT NULL, -- Enable SQL prefilter for hybrid by default
    duplicate_scan_method TEXT DEFAULT 'hybrid' NOT NULL, -- Use hybrid prefilter by default
    duplicate_scan_enabled SMALLINT DEFAULT 1 NOT NULL,
    duplicate_scan_frequency TEXT DEFAULT 'after_import' NOT NULL,
    duplicate_scan_cron TEXT DEFAULT '' NOT NULL,
    duplicate_scan_hour INTEGER DEFAULT 3 NOT NULL,
    duplicate_scan_chunk_size INTEGER DEFAULT 5000 NOT NULL,
    duplicate_scan_debounce_seconds INTEGER DEFAULT 5 NOT NULL
);

-- Persisted scheduled jobs (initial focus: auto-send). Rows remain until dispatched or manually cleared.
CREATE TABLE IF NOT EXISTS cwa_scheduled_jobs(
    id INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL,
    job_type TEXT NOT NULL,                     -- e.g., 'auto_send'
    book_id INTEGER,
    user_id INTEGER,
    username TEXT,
    title TEXT,
    scheduler_job_id TEXT DEFAULT '',           -- APScheduler job id for cancellation
    run_at_utc TEXT NOT NULL,                  -- ISO8601 UTC timestamp
    created_at_utc TEXT NOT NULL,              -- ISO8601 UTC timestamp
    state TEXT NOT NULL DEFAULT 'scheduled',   -- 'scheduled' | 'dispatched' | 'cancelled'
    last_error TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS cwa_user_activity (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    user_name TEXT,
    event_type TEXT,
    item_id INTEGER,
    item_title TEXT,
    extra_data TEXT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_activity_user ON cwa_user_activity(user_id);
CREATE INDEX IF NOT EXISTS idx_activity_event ON cwa_user_activity(event_type);
CREATE INDEX IF NOT EXISTS idx_activity_time ON cwa_user_activity(timestamp);

-- Hardcover auto-fetch match queue for manual review of ambiguous matches
CREATE TABLE IF NOT EXISTS hardcover_match_queue(
    id INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL,
    book_id INTEGER NOT NULL,
    book_title TEXT NOT NULL,
    book_authors TEXT NOT NULL,
    search_query TEXT NOT NULL,
    hardcover_results TEXT NOT NULL,              -- JSON array of MetaRecord candidates
    confidence_scores TEXT NOT NULL,              -- JSON array of [score, reason] tuples
    created_at TEXT NOT NULL,
    reviewed INTEGER DEFAULT 0 NOT NULL,          -- 0=pending, 1=reviewed
    selected_result_id TEXT DEFAULT NULL,         -- Hardcover ID if manually selected
    review_action TEXT DEFAULT NULL,              -- 'accept', 'reject', 'skip'
    reviewed_at TEXT DEFAULT NULL,
    reviewed_by TEXT DEFAULT NULL
);
CREATE INDEX IF NOT EXISTS idx_hardcover_queue_book ON hardcover_match_queue(book_id);
CREATE INDEX IF NOT EXISTS idx_hardcover_queue_reviewed ON hardcover_match_queue(reviewed);

-- Stats for hardcover auto-fetch operations
CREATE TABLE IF NOT EXISTS hardcover_auto_fetch_stats(
    id INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL,
    timestamp TEXT NOT NULL,
    books_processed INTEGER DEFAULT 0 NOT NULL,
    auto_matched INTEGER DEFAULT 0 NOT NULL,
    queued_for_review INTEGER DEFAULT 0 NOT NULL,
    skipped_no_results INTEGER DEFAULT 0 NOT NULL,
    errors INTEGER DEFAULT 0 NOT NULL,
    avg_confidence REAL DEFAULT 0.0 NOT NULL
);

-- Duplicate detection cache table
CREATE TABLE IF NOT EXISTS cwa_duplicate_cache (
    id INTEGER PRIMARY KEY CHECK (id = 1),  -- Singleton table, only one row
    scan_timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    duplicate_groups_json TEXT,  -- JSON serialized duplicate groups
    total_count INTEGER DEFAULT 0,
    scan_pending INTEGER DEFAULT 1,  -- 1=needs scan, 0=cache valid
    last_scanned_book_id INTEGER DEFAULT 0,  -- Track last scanned book for incremental updates
    scan_duration_seconds REAL DEFAULT 0,  -- Performance tracking
    scan_method_used TEXT DEFAULT 'python'  -- Track which method was used: 'sql', 'python', 'hybrid'
);

-- Insert default row for cache table
INSERT OR IGNORE INTO cwa_duplicate_cache (id, scan_pending) VALUES (1, 1);

-- Auto-resolution audit log
CREATE TABLE IF NOT EXISTS cwa_duplicate_resolutions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    group_hash TEXT NOT NULL,
    group_title TEXT,
    group_author TEXT,
    kept_book_id INTEGER NOT NULL,
    deleted_book_ids TEXT NOT NULL,  -- JSON array of deleted IDs
    strategy TEXT NOT NULL,  -- 'newest', 'highest_quality_format', 'most_metadata', 'largest_file_size'
    trigger_type TEXT NOT NULL,  -- 'manual', 'scheduled', 'automatic'
    backed_up INTEGER DEFAULT 1,  -- 1=yes, 0=no
    user_id INTEGER,  -- NULL for automatic, admin user ID for manual
    notes TEXT
);

CREATE INDEX IF NOT EXISTS idx_duplicate_resolutions_timestamp ON cwa_duplicate_resolutions(timestamp);
CREATE INDEX IF NOT EXISTS idx_duplicate_resolutions_group_hash ON cwa_duplicate_resolutions(group_hash);
