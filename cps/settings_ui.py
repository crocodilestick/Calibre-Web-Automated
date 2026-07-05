# -*- coding: utf-8 -*-
# Calibre-Web Automated
# Blueprint for consolidated Settings UI (Roadmap-Punkt 2)

import os
import sys
from urllib.parse import urlparse
from flask import Blueprint, redirect, url_for, request, g, abort, flash
from flask_babel import gettext as _
from sqlalchemy import and_

# Make sure scripts directory is in sys.path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
scripts_path = os.path.join(project_root, "scripts")
if scripts_path not in sys.path:
    sys.path.insert(1, scripts_path)

from cwa_db import CWA_DB

from .cw_login import current_user
from .usermanagement import user_login_required
from .admin import admin_required, feature_support
from .render_template import render_title_template
from .cw_babel import get_available_locale
from . import config, calibre_db, db, constants, logger

# Import oauth_bb or mock it if missing
try:
    from . import oauth_bb
    oauth_blueprints = getattr(oauth_bb, "oauthblueprints", [])
except ImportError:
    oauth_blueprints = []

log = logger.create()

settings = Blueprint('settings', __name__, template_folder='templates')

# Static fields
AJAXCONFIG_FIELDS = [
    "config_trustedhosts", "config_keyfile", "config_certfile", "config_uploading",
    "config_unicode_filename", "config_embed_metadata", "config_anonbrowse",
    "config_public_reg", "config_register_email", "config_kobo_sync",
    "config_external_port", "config_kobo_proxy", "config_hardcover_sync",
    "config_upload_formats", "config_calibre", "config_binariesdir",
    "config_kepubifypath", "config_login_type", "config_remote_login",
    "config_use_goodreads", "config_goodreads_api_key",
    "config_hardcover_annotations_sync", "config_hardcover_token",
    "config_updatechannel", "config_allow_reverse_proxy_header_login",
    "config_reverse_proxy_login_header_name", "config_reverse_proxy_auto_create_users",
    "config_oauth_redirect_host", "config_disable_standard_login",
    "config_enable_oauth_group_admin_management", "config_check_extensions",
    "config_password_policy", "config_password_number", "config_password_lower",
    "config_password_upper", "config_password_character", "config_password_special",
    "config_password_min_length", "config_session", "config_ratelimiter",
    "config_limiter_uri", "config_limiter_options", "config_rarfile_location",
    "config_converterpath", "config_log_level", "config_logfile",
    "config_access_log", "config_access_logfile",
    # LDAP Fields
    "config_ldap_provider_url", "config_ldap_port", "config_ldap_authentication",
    "config_ldap_serv_username", "config_ldap_serv_password_e", "config_ldap_dn", "config_ldap_user_object",
    "config_ldap_member_user_object", "config_ldap_openldap", "config_ldap_auto_create_users",
    "config_ldap_encryption", "config_ldap_cacert_path", "config_ldap_cert_path",
    "config_ldap_key_path", "config_ldap_group_name", "config_ldap_group_object_filter",
    "config_ldap_group_members_field"
]

VIEWCONFIG_FIELDS = [
    "config_calibre_web_title", "config_books_per_page", "config_random_books",
    "config_authors_max", "config_title_regex", "config_read_column",
    "config_restricted_column", "config_default_language", "config_default_locale",
    "config_columns_to_ignore", "config_theme",
    # Roles Checkboxes
    "admin_role", "download_role", "upload_role", "edit_role", "delete_role",
    "passwd_role", "edit_shelf_role", "viewer_role",
    # Show Checkboxes (dynamic values based on bitmasks)
    "show_2", "show_4", "show_8", "show_16", "show_32", "show_64", "show_128",
    "show_256", "show_512", "show_1024", "show_4096", "show_8192", "show_16384",
    "show_32768", "show_65536", "show_131072", "show_262144",
    "Show_detail_random"
]

MAILSETTINGS_FIELDS = [
    "mail_server", "mail_port", "mail_use_ssl", "mail_login",
    "mail_password", "mail_password_e", "mail_from", "mail_size", "mail_server_type"
]

SCHEDULEDTASKS_FIELDS = [
    "schedule_start_time", "schedule_duration", "schedule_generate_book_covers",
    "schedule_generate_series_covers", "schedule_reconnect", "schedule_metadata_backup"
]

CWA_FIELDS = [
    "auto_backup_imports", "auto_backup_conversions", "auto_zip_backups",
    "cwa_update_notifications", "contribute_translations_notifications",
    "auto_convert", "auto_convert_target_format", "auto_ingest_automerge",
    "ingest_timeout_minutes", "ingest_stale_temp_minutes", "ingest_stale_temp_interval",
    "auto_metadata_enforcement", "kindle_epub_fixer", "kindle_epub_fixer_aggressive",
    "koreader_sync_enabled", "auto_backup_epub_fixes", "archived_cleanup_enabled",
    "archived_cleanup_schedule", "archived_cleanup_schedule_day",
    "archived_cleanup_schedule_hour", "enable_mobile_blur", "auto_metadata_fetch_enabled",
    "auto_metadata_smart_application", "auto_metadata_update_title",
    "auto_metadata_update_authors", "auto_metadata_update_description",
    "auto_metadata_update_publisher", "auto_metadata_update_tags",
    "auto_metadata_update_series", "auto_metadata_update_rating",
    "auto_metadata_update_published_date", "auto_metadata_update_identifiers",
    "auto_metadata_update_cover", "cover_download_max_mb",
    "metadata_provider_hierarchy", "metadata_providers_enabled", "auto_send_delay_minutes",
    "duplicate_detection_title", "duplicate_detection_author", "duplicate_detection_language",
    "duplicate_detection_series", "duplicate_detection_publisher", "duplicate_detection_format",
    "duplicate_detection_enabled", "duplicate_notifications_enabled", "duplicate_auto_resolve_enabled",
    "duplicate_auto_resolve_strategy", "duplicate_auto_resolve_cooldown_minutes",
    "duplicate_format_priority", "duplicate_detection_use_sql", "duplicate_scan_method",
    "duplicate_scan_enabled", "duplicate_scan_frequency", "duplicate_scan_cron",
    "duplicate_scan_hour", "duplicate_scan_chunk_size", "duplicate_scan_debounce_seconds",
    # app.db Boolean sent through this handler
    "config_kobo_sync_magic_shelves",
    # Hardcover (Non-displayed but mirrored)
    "hardcover_auto_fetch_enabled", "hardcover_auto_fetch_schedule",
    "hardcover_auto_fetch_schedule_day", "hardcover_auto_fetch_schedule_hour",
    "hardcover_auto_fetch_min_confidence", "hardcover_auto_fetch_batch_size",
    "hardcover_auto_fetch_rate_limit",
    # Form control field required by handler
    "submit_button"
]

BOOLEAN_SETTINGS = {
    # ajaxconfig
    "config_uploading", "config_unicode_filename", "config_embed_metadata",
    "config_anonbrowse", "config_public_reg", "config_register_email",
    "config_kobo_sync", "config_kobo_proxy", "config_hardcover_sync",
    "config_remote_login", "config_use_goodreads", "config_hardcover_annotations_sync",
    "config_allow_reverse_proxy_header_login", "config_reverse_proxy_auto_create_users",
    "config_disable_standard_login", "config_enable_oauth_group_admin_management",
    "config_check_extensions", "config_password_policy", "config_password_number",
    "config_password_lower", "config_password_upper", "config_password_character",
    "config_password_special", "config_ratelimiter", "config_ldap_openldap",
    "config_ldap_auto_create_users", "config_access_log",
    # viewconfig (roles and show settings are treated as checkboxes in form)
    "admin_role", "download_role", "upload_role", "edit_role", "delete_role",
    "passwd_role", "edit_shelf_role", "viewer_role",
    "show_2", "show_4", "show_8", "show_16", "show_32", "show_64", "show_128",
    "show_256", "show_512", "show_1024", "show_4096", "show_8192", "show_16384",
    "show_32768", "show_65536", "show_131072", "show_262144",
    "Show_detail_random",
    # scheduledtasks
    "schedule_generate_book_covers", "schedule_generate_series_covers",
    "schedule_reconnect", "schedule_metadata_backup",
    # cwa
    "auto_backup_imports", "auto_backup_conversions", "auto_zip_backups",
    "cwa_update_notifications", "contribute_translations_notifications",
    "auto_convert", "auto_metadata_enforcement", "kindle_epub_fixer",
    "kindle_epub_fixer_aggressive", "koreader_sync_enabled", "auto_backup_epub_fixes",
    "archived_cleanup_enabled", "enable_mobile_blur", "auto_metadata_fetch_enabled",
    "auto_metadata_smart_application", "auto_metadata_update_title",
    "auto_metadata_update_authors", "auto_metadata_update_description",
    "auto_metadata_update_publisher", "auto_metadata_update_tags",
    "auto_metadata_update_series", "auto_metadata_update_rating",
    "auto_metadata_update_published_date", "auto_metadata_update_identifiers",
    "auto_metadata_update_cover", "duplicate_detection_title", "duplicate_detection_author",
    "duplicate_detection_language", "duplicate_detection_series", "duplicate_detection_publisher",
    "duplicate_detection_format", "duplicate_detection_enabled", "duplicate_notifications_enabled",
    "duplicate_auto_resolve_enabled", "duplicate_detection_use_sql", "duplicate_scan_enabled",
    "hardcover_auto_fetch_enabled", "config_kobo_sync_magic_shelves"
}

IGNORABLE_FORMATS = [
    'acsm', 'azw', 'azw3', 'azw4', 'cbz', 'cbr', 'cb7', 'cbc', 'chm',
    'djvu', 'docx', 'epub', 'fb2', 'fbz', 'html', 'htmlz', 'kepub', 'lit',
    'lrf', 'mobi', 'odt', 'pdf', 'prc', 'pdb', 'pml', 'rb', 'rtf', 'snb',
    'tcr', 'txt', 'txtz', 'kfx', 'kfx-zip'
]

def get_dynamic_oauth_fields():
    """Generates OAuth field names dynamically based on loaded blueprints."""
    fields = []
    # Safely query oauth blueprints at call time
    try:
        from . import oauth_bb
        oauth_bps = getattr(oauth_bb, "oauthblueprints", []) or oauth_blueprints
    except ImportError:
        oauth_bps = oauth_blueprints
        
    for bp in oauth_bps:
        pid = bp.get("id")
        pname = bp.get("provider_name")
        if pname == "generic":
            fields.extend([
                "config_generic_oauth_client_id", "config_generic_oauth_client_secret",
                "config_generic_oauth_metadata_url", "config_generic_oauth_server_url",
                "config_generic_oauth_auth_url", "config_generic_oauth_token_url",
                "config_generic_oauth_userinfo_url", "config_generic_oauth_scope",
                "config_generic_oauth_username_mapper", "config_generic_oauth_email_mapper",
                "config_generic_oauth_login_button", "config_generic_oauth_admin_group"
            ])
        else:
            fields.extend([
                f"config_{pid}_oauth_client_id",
                f"config_{pid}_oauth_client_secret"
            ])
    return fields

def get_dynamic_format_fields():
    """Generates CWA format fields dynamically (ignore_ingest_*, ignore_convert_*, etc.)."""
    fields = []
    for fmt in IGNORABLE_FORMATS:
        fields.append(f"ignore_ingest_{fmt}")
        fields.append(f"ignore_convert_{fmt}")
        fields.append(f"convert_retained_{fmt}")
    return fields

def get_all_mapped_fields():
    """Compiles all mapped fields (including dynamic ones) for drift test validation."""
    fields = (
        set(AJAXCONFIG_FIELDS) |
        set(VIEWCONFIG_FIELDS) |
        set(MAILSETTINGS_FIELDS) |
        set(SCHEDULEDTASKS_FIELDS) |
        set(CWA_FIELDS)
    )
    fields.update(get_dynamic_oauth_fields())
    fields.update(get_dynamic_format_fields())
    return fields

def get_next_duplicate_scan_run(settings):
    """Compute next scheduled duplicate scan run time based on settings."""
    try:
        enabled = bool(settings.get('duplicate_scan_enabled', 0))
        cron_expr = (settings.get('duplicate_scan_cron') or '').strip()
        if not enabled:
            return _("Disabled")
        if not cron_expr:
            scan_hour = settings.get('duplicate_scan_hour', 3)
            return _("Daily at %(hour)02d:00", hour=scan_hour)

        from croniter import croniter
        from datetime import datetime, timezone
        iter_cron = croniter(cron_expr, datetime.now(timezone.utc))
        next_run = iter_cron.get_next(datetime)
        return next_run.strftime("%Y-%m-%d %H:%M:%S UTC")
    except Exception:
        return _("Invalid schedule")

def get_settings_context():
    """Compiles and returns the unified settings context for rendering tabs."""
    cwa_db = CWA_DB()
    cwa_settings = cwa_db.cwa_settings

    target_formats = ['epub', 'azw3', 'kepub', 'mobi', 'pdf']
    automerge_options = ['ignore', 'overwrite', 'new_record']
    autoingest_options = ['ignore', 'overwrite', 'new_record']

    hardcover_token_available = bool(
        getattr(config, "config_hardcover_token", None) or
        os.getenv("HARDCOVER_TOKEN")
    )

    next_scan_run = get_next_duplicate_scan_run(cwa_settings)

    read_column = calibre_db.session.query(db.CustomColumns) \
        .filter(and_(db.CustomColumns.datatype == 'bool', db.CustomColumns.mark_for_delete == 0)).all()
    restrict_columns = calibre_db.session.query(db.CustomColumns) \
        .filter(and_(db.CustomColumns.datatype == 'text', db.CustomColumns.mark_for_delete == 0)).all()
    languages = calibre_db.speaking_language()
    translations = get_available_locale()

    mail_content = config.get_mail_settings()

    # Generate starttime and duration lists for scheduled tasks
    from flask_babel import format_time, format_timedelta
    from datetime import time as datetime_time, timedelta
    time_field = list()
    duration_field = list()
    for n in range(24):
        time_field.append((n, format_time(datetime_time(hour=n), format="short")))
    for n in range(5, 65, 5):
        t = timedelta(hours=n // 60, minutes=n % 60)
        duration_field.append((n, format_timedelta(t, threshold=.97)))

    cleanup_schedules = [
        ('disabled', _('Disabled')),
        ('daily', _('Daily')),
        ('weekly', _('Weekly')),
        ('monthly', _('Monthly'))
    ]
    cleanup_days = [
        ('monday', _('Monday')),
        ('tuesday', _('Tuesday')),
        ('wednesday', _('Wednesday')),
        ('thursday', _('Thursday')),
        ('friday', _('Friday')),
        ('saturday', _('Saturday')),
        ('sunday', _('Sunday'))
    ]

    # Build dynamic fields
    dyn_ajax_fields = list(AJAXCONFIG_FIELDS) + get_dynamic_oauth_fields()
    dyn_cwa_fields = list(CWA_FIELDS) + get_dynamic_format_fields()

    dyn_boolean_settings = set(BOOLEAN_SETTINGS)
    for fmt_field in get_dynamic_format_fields():
        dyn_boolean_settings.add(fmt_field)

    return {
        "config": config,
        "conf": config,
        "cwa_settings": cwa_settings,
        "ignorable_formats": IGNORABLE_FORMATS,
        "target_formats": target_formats,
        "automerge_options": automerge_options,
        "autoingest_options": autoingest_options,
        "hardcover_token_available": hardcover_token_available,
        "next_duplicate_scan_run": next_scan_run,
        "readColumns": read_column,
        "restrictColumns": restrict_columns,
        "languages": languages,
        "translations": translations,
        "content": mail_content,
        "starttime": time_field,
        "duration": duration_field,
        "cleanup_schedules": cleanup_schedules,
        "cleanup_days": cleanup_days,
        "feature_support": feature_support,
        "provider": oauth_blueprints,
        "AJAXCONFIG_FIELDS": dyn_ajax_fields,
        "VIEWCONFIG_FIELDS": VIEWCONFIG_FIELDS,
        "MAILSETTINGS_FIELDS": MAILSETTINGS_FIELDS,
        "SCHEDULEDTASKS_FIELDS": SCHEDULEDTASKS_FIELDS,
        "CWA_FIELDS": dyn_cwa_fields,
        "BOOLEAN_SETTINGS": dyn_boolean_settings
    }

@settings.route("/settings")
@user_login_required
def index():
    if current_user.role_admin():
        return redirect(url_for('settings.tab', active_tab='bibliothek'))
    else:
        return redirect(url_for('web.profile'))

@settings.route("/settings/<active_tab>")
@user_login_required
@admin_required
def tab(active_tab):
    valid_tabs = ['bibliothek', 'kobo', 'automatisierung', 'email', 'wartung', 'experten']
    if active_tab not in valid_tabs:
        abort(404)

    ctx = get_settings_context()
    ctx["active_tab"] = active_tab

    template_map = {
        'bibliothek': 'settings/bibliothek.html',
        'kobo': 'settings/kobo.html',
        'automatisierung': 'settings/automatisierung.html',
        'email': 'settings/email.html',
        'wartung': 'settings/wartung.html',
        'experten': 'settings/experten.html'
    }

    title_map = {
        'bibliothek': _("Library Settings"),
        'kobo': _("Kobo Synchronisation"),
        'automatisierung': _("Import Automation"),
        'email': _("Email Server Settings"),
        'wartung': _("Maintenance and Tasks"),
        'experten': _("Expert Settings")
    }

    return render_title_template(template_map[active_tab], title=title_map[active_tab], page=f"settings_{active_tab}", **ctx)
