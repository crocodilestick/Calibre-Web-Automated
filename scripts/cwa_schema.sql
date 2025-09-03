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
    auto_ingest_automerge TEXT DEFAULT "new_record" NOT NULL,
    ingest_timeout_minutes INTEGER DEFAULT 15 NOT NULL,
    auto_metadata_enforcement SMALLINT DEFAULT 1 NOT NULL,
    kindle_epub_fixer SMALLINT DEFAULT 1 NOT NULL,
    auto_backup_epub_fixes SMALLINT DEFAULT 1 NOT NULL,
    enable_mobile_blur SMALLINT DEFAULT 1 NOT NULL
);