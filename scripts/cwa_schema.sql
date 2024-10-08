CREATE TABLE IF NOT EXISTS cwa_enforcement(
    id INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL, 
    timestamp TEXT NOT NULL,
    book_id INTEGER NOT NULL, 
    book_title TEXT NOT NULL,
    author TEXT NOT NULL, 
    epub_path TEXT NOT NULL, 
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
    original_backed_up TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS cwa_settings(
    default_settings SMALLINT NOT NULL,
    auto_backup_imports SMALLINT DEFAULT 1 NOT NULL,
    auto_backup_conversions SMALLINT DEFAULT 1 NOT NULL,
    auto_zip_backups SMALLINT DEFAULT 1 NOT NULL,
    cwa_update_notifications SMALLINT DEFAULT 1 NOT NULL,
    robotic_reading SMALLINT DEFAULT 0 NOT NULL
);