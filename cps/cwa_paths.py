import os


# Base paths — read from environment each call so tests can override via monkeypatch.setenv
def GET_CONFIG_PATH() -> str:
    return os.environ.get("CWA_CONFIG_PATH", "/config")

def GET_LIBRARY_PATH() -> str:
    return os.environ.get("CWA_LIBRARY_PATH", "/calibre-library")

def GET_INGEST_PATH() -> str:
    return os.environ.get("CWA_INGEST_PATH", "/cwa-book-ingest")

def GET_APP_PATH() -> str:
    return os.environ.get("CWA_APP_PATH", "/app/calibre-web-automated")

def GET_APP_ROOT() -> str:
    return os.path.dirname(GET_APP_PATH())


# Derived paths — config dir
def GET_APP_DB() -> str:
    return os.path.join(GET_CONFIG_PATH(), "app.db")

def GET_CWA_DB_PATH() -> str:
    return os.path.join(GET_CONFIG_PATH(), "cwa.db")

def GET_PROCESSED_BOOKS() -> str:
    return os.path.join(GET_CONFIG_PATH(), "processed_books")

def GET_LOG_ARCHIVE() -> str:
    return os.path.join(GET_CONFIG_PATH(), "log_archive")

def GET_CONVERT_LOG() -> str:
    return os.path.join(GET_CONFIG_PATH(), "convert-library.log")

def GET_EPUB_FIXER_LOG() -> str:
    return os.path.join(GET_CONFIG_PATH(), "epub-fixer.log")

def GET_USER_PROFILES() -> str:
    return os.path.join(GET_CONFIG_PATH(), "user_profiles.json")

def GET_INGEST_STATUS() -> str:
    return os.path.join(GET_CONFIG_PATH(), "cwa_ingest_status")

def GET_INGEST_RETRY_QUEUE() -> str:
    return os.path.join(GET_CONFIG_PATH(), "cwa_ingest_retry_queue")

def GET_CWA_DB_DEBUG() -> str:
    return os.path.join(GET_CONFIG_PATH(), ".cwa_db_debug")


# Derived paths — library dir
def GET_METADATA_DB() -> str:
    return os.path.join(GET_LIBRARY_PATH(), "metadata.db")


# Derived paths — config dir (continued)
def GET_TMP_CONVERSION_DIR() -> str:
    return os.path.join(GET_CONFIG_PATH(), ".cwa_conversion_tmp")


# Derived paths — app dir
def GET_CHANGE_LOGS_DIR() -> str:
    return os.path.join(GET_APP_PATH(), "metadata_change_logs")

def GET_METADATA_TEMP_DIR() -> str:
    return os.path.join(GET_APP_PATH(), "metadata_temp")

def GET_EMPTY_LIBRARY_APP_DB() -> str:
    return os.path.join(GET_APP_PATH(), "empty_library", "app.db")

def GET_EMPTY_LIBRARY_METADATA_DB() -> str:
    return os.path.join(GET_APP_PATH(), "empty_library", "metadata.db")

def GET_INGEST_SCRIPT() -> str:
    return os.path.join(GET_APP_PATH(), "scripts", "ingest_processor.py")

def GET_CONVERT_SCRIPT() -> str:
    return os.path.join(GET_APP_PATH(), "scripts", "convert_library.py")

def GET_EPUB_FIXER_SCRIPT() -> str:
    return os.path.join(GET_APP_PATH(), "scripts", "kindle_epub_fixer.py")

def GET_CHECK_SERVICES_SCRIPT() -> str:
    return os.path.join(GET_APP_PATH(), "scripts", "check-cwa-services.sh")


# Derived paths — app root (/app)
def GET_CWA_RELEASE_FILE() -> str:
    return os.path.join(GET_APP_ROOT(), "CWA_RELEASE")

def GET_CWA_STABLE_RELEASE_FILE() -> str:
    return os.path.join(GET_APP_ROOT(), "CWA_STABLE_RELEASE")

def GET_KEPUBIFY_RELEASE_FILE() -> str:
    return os.path.join(GET_APP_ROOT(), "KEPUBIFY_RELEASE")

def GET_CWA_UPDATE_NOTICE() -> str:
    return os.path.join(GET_APP_ROOT(), "cwa_update_notice")

def GET_THEME_MIGRATION_NOTICE() -> str:
    return os.path.join(GET_APP_ROOT(), "theme_migration_notice")

def GET_CALIBRE_DIR() -> str:
    return os.path.join(GET_APP_ROOT(), "calibre")
