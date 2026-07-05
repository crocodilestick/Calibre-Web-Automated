# Feldinventar: CWA Alexandria Einstellungen

Dieses Dokument enthält das vollständige, maschinenlesbare Feldinventar aller Einstellungen von Calibre-Web Automated (Roadmap-Punkt 2). Es dient als Quelle für die Spiegel-Makros und den Drift-Test.

---

## 1. Übersicht der Speicherorte

*   **app.db (`_Settings`):** Globale Konfiguration von Calibre-Web (Verzeichnisse, Mail, Server, Sicherheit, LDAP/OAuth, etc.).
*   **cwa.db (`cwa_settings`):** Automatisierung, Ingest, EPUB-Fixer, Backups, Duplikaterkennung, Hardcover-Auto-Fetch.
*   **User-Tabelle (`cps/ub.py`):** Benutzerbezogene Einstellungen (Profil, eigene eReader-Mails, Kobo-Dashboard-Flags).

---

## 2. Feld-Details nach POST-Endpoints

### Endpoint `/admin/ajaxconfig` (Speichert in `app.db`)

Diese Einstellungen werden vom Handler `_configuration_update_helper()` in `cps/admin.py` verarbeitet.
*Checkboxen und Integer-Checkboxen (Checkboxen, die als 0/1 in der DB liegen) werden bei Fehlen im POST auf `False` bzw. `0` zurückgesetzt.*

| Feldname | Typ | Standardwert | Pflichtfeld | Reboot nötig | Reset bei Abwesenheit |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `config_trustedhosts` | String | `""` | Nein | Ja | Nein |
| `config_keyfile` | String | `""` | Nein | Ja | Nein |
| `config_certfile` | String | `""` | Nein | Ja | Nein |
| `config_uploading` | Checkbox (Int) | `1` | Nein | Nein | Ja |
| `config_unicode_filename` | Checkbox (Int) | `0` | Nein | Nein | Ja |
| `config_embed_metadata` | Checkbox (Int) | `1` | Nein | Nein | Ja |
| `config_anonbrowse` | Checkbox (Int) | `0` | Nein | Bei LDAP | Ja |
| `config_public_reg` | Checkbox (Int) | `0` | Nein | Nein | Ja |
| `config_register_email` | Checkbox (Int) | `0` | Nein | Nein | Ja |
| `config_kobo_sync` | Checkbox (Int) | `0` | Nein | Ja | Ja |
| `config_external_port` | Integer | `8083` | Ja | Nein | Nein |
| `config_kobo_proxy` | Checkbox (Int) | `0` | Nein | Nein | Ja |
| `config_hardcover_sync` | Checkbox (Int) | `0` | Nein | Nein | Ja |
| `config_upload_formats` | String | `"txt,epub,pdf"` | Nein | Nein | Nein |
| `config_calibre` | String | `""` | Nein | Nein | Nein |
| `config_binariesdir` | String | `""` | Nein | Nein | Nein |
| `config_kepubifypath` | String | `""` | Nein | Nein | Nein |
| `config_converterpath` | String | `""` | Nein | Nein | Nein |
| `config_log_level` | Integer | `20` | Ja | Ja | Nein |
| `config_logfile` | String | `""` | Nein | Ja | Nein |
| `config_access_log` | Checkbox (Int) | `0` | Nein | Ja | Ja |
| `config_access_logfile` | String | `""` | Nein | Ja | Nein |
| `config_login_type` | Integer | `0` | Ja | Ja | Nein |
| `config_remote_login` | Checkbox | `False` | Nein | Nein | Ja |
| `config_use_goodreads` | Checkbox | `False` | Nein | Nein | Ja |
| `config_goodreads_api_key` | String | `""` | Nein | Nein | Nein |
| `config_hardcover_annotations_sync` | Checkbox | `False` | Nein | Nein | Ja |
| `config_hardcover_token` | String | `""` | Nein | Nein | Nein |
| `config_updatechannel` | Integer | `constants.UPDATE_STABLE` | Ja | Nein | Nein |
| `config_allow_reverse_proxy_header_login` | Checkbox | `False` | Nein | Nein | Ja |
| `config_reverse_proxy_login_header_name` | String | `""` | Nein | Nein | Nein |
| `config_reverse_proxy_auto_create_users` | Checkbox | `False` | Nein | Nein | Ja |
| `config_oauth_redirect_host` | String | `""` | Nein | Ja | Nein |
| `config_disable_standard_login` | Checkbox | `False` | Nein | Nein | Ja |
| `config_enable_oauth_group_admin_management` | Checkbox | `True` | Nein | Nein | Ja |
| `config_check_extensions` | Checkbox | `True` | Nein | Nein | Ja |
| `config_password_policy` | Checkbox | `True` | Nein | Nein | Ja |
| `config_password_number` | Checkbox | `True` | Nein | Nein | Ja |
| `config_password_lower` | Checkbox | `True` | Nein | Nein | Ja |
| `config_password_upper` | Checkbox | `True` | Nein | Nein | Ja |
| `config_password_character` | Checkbox | `True` | Nein | Nein | Ja |
| `config_password_special` | Checkbox | `True` | Nein | Nein | Ja |
| `config_password_min_length` | Integer | `8` | **Ja** (1-40) | Nein | Nein |
| `config_session` | Integer | `1` | Ja | Ja | Nein |
| `config_ratelimiter` | Checkbox | `True` | Nein | Ja | Ja |
| `config_limiter_uri` | String | `""` | Nein | Ja | Nein |
| `config_limiter_options` | String | `""` | Nein | Ja | Nein |
| `config_rarfile_location` | String | `""` | Nein | Nein | Nein |

#### LDAP-Untergruppe (nur aktiv bei `config_login_type == LOGIN_LDAP`)
| Feldname | Typ | Standardwert | Pflichtfeld | Reboot nötig | Reset bei Abwesenheit |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `config_ldap_provider_url` | String | `"example.org"` | Ja (bei LDAP) | Ja | Nein |
| `config_ldap_port` | Integer | `389` | Ja (bei LDAP) | Ja | Nein |
| `config_ldap_authentication` | Integer | `constants.LDAP_AUTH_SIMPLE` | Ja | Ja | Nein |
| `config_ldap_serv_username` | String | `"cn=admin,dc=org"` | Nein | Ja | Nein |
| `config_ldap_serv_password` | String | `""` | Nein | Nein (über `_password_e`) | Nein |
| `config_ldap_dn` | String | `"dc=org"` | Ja (bei LDAP) | Ja | Nein |
| `config_ldap_user_object` | String | `"uid=%s"` | Ja (bei LDAP) | Ja | Nein |
| `config_ldap_member_user_object` | String | `""` | Nein | Ja | Nein |
| `config_ldap_openldap` | Checkbox | `True` | Nein | Ja | Ja |
| `config_ldap_auto_create_users` | Checkbox | `True` | Nein | Nein | Ja |
| `config_ldap_encryption` | Integer | `0` | Ja | Ja | Nein |
| `config_ldap_cacert_path` | String | `""` | Nein | Ja | Nein |
| `config_ldap_cert_path` | String | `""` | Nein | Ja | Nein |
| `config_ldap_key_path` | String | `""` | Nein | Ja | Nein |
| `config_ldap_group_name` | String | `"calibreweb"` | Nein | Nein | Nein |
| `config_ldap_group_object_filter` | String | `"(&(objectclass=posixGroup)(cn=%s))"` | Nein | Ja | Nein |
| `config_ldap_group_members_field` | String | `"memberUid"` | Nein | Ja | Nein |

#### OAuth-Untergruppe (nur aktiv bei `config_login_type == LOGIN_OAUTH`)
Die OAuth-Feldnamen werden im Code dynamisch generiert, basierend auf den IDs der in der Datenbank geladenen Provider (z. B. `config_1_oauth_client_id` für GitHub).

| Feldname | Typ | Standardwert | Pflichtfeld | Reboot nötig | Reset bei Abwesenheit |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `config_generic_oauth_client_id` | String | `""` | Ja (bei OIDC) | Ja | Nein |
| `config_generic_oauth_client_secret` | String | `""` | Ja (bei OIDC) | Ja | Nein |
| `config_generic_oauth_metadata_url` | String | `""` | Nein | Ja | Nein |
| `config_generic_oauth_server_url` | String | `""` | Nein | Ja | Nein |
| `config_generic_oauth_auth_url` | String | `""` | Nein | Ja | Nein |
| `config_generic_oauth_token_url` | String | `""` | Nein | Ja | Nein |
| `config_generic_oauth_userinfo_url` | String | `""` | Nein | Ja | Nein |
| `config_generic_oauth_scope` | String | `"openid profile email"` | Nein | Ja | Nein |
| `config_generic_oauth_username_mapper` | String | `"preferred_username"` | Nein | Ja | Nein |
| `config_generic_oauth_email_mapper` | String | `"email"` | Nein | Ja | Nein |
| `config_generic_oauth_login_button` | String | `"OpenID Connect"` | Nein | Ja | Nein |
| `config_generic_oauth_admin_group` | String | `"admin"` | Nein | Ja | Nein |
| `config_<id>_oauth_client_id` | String | `""` | Ja (bei OAuth) | Ja | Nein |
| `config_<id>_oauth_client_secret` | String | `""` | Ja (bei OAuth) | Ja | Nein |

---

### Endpoint `/admin/viewconfig` (Speichert in `app.db`)

Verarbeitet durch `admi.route("/admin/viewconfig", methods=["POST"])` in `cps/admin.py`.
*Achtung: `config_default_role` und `config_default_show` werden dynamisch aus den gesendeten Checkboxen summiert. Wenn Rollen- oder Show-Checkboxen fehlen, werden sie auf 0 zurückgesetzt.*

| Feldname | Typ | Standardwert | Pflichtfeld | Reboot nötig | Reset bei Abwesenheit |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `config_calibre_web_title` | String | `"Calibre-Web Automated"` | Nein | Nein | Nein |
| `config_books_per_page` | Integer | `60` | Ja | Nein | Nein |
| `config_random_books` | Integer | `4` | Ja | Nein | Nein |
| `config_authors_max` | Integer | `0` | Ja | Nein | Nein |
| `config_title_regex` | String | `r'...'` | Nein | Nein | Nein |
| `config_read_column` | Integer | `0` | Nein | Nein | Nein |
| `config_restricted_column` | Integer | `0` | Nein | Nein | Nein |
| `config_default_language` | String | `"all"` | Ja | Nein | Nein |
| `config_default_locale` | String | `"de"` | Ja | Nein | Nein |
| `config_columns_to_ignore` | String | `""` | Nein | Nein | Nein |
| `config_theme` | Integer (Ausgeblendet!) | `1` | Nein | Nein | Nein |

#### Dynamische Checkboxen für Default-Rollen (`config_default_role`)
*Wenn abwesend, verliert die Default-Rolle dieses Recht.*
*   `admin_role`
*   `download_role`
*   `upload_role`
*   `edit_role`
*   `delete_role`
*   `passwd_role`
*   `edit_shelf_role`
*   `viewer_role`

#### Dynamische Checkboxen für Default-Seiten (`config_default_show` / Sidebar)
*Wenn abwesend, wird diese Seite in der Seitenleiste standardmäßig ausgeblendet.*
*   `show_<bitmask_integer>` (z. B. `show_2`, `show_4`, `show_8`, `show_16`, etc.)
*   `Show_detail_random` (Show random books in detail view)

---

### Endpoint `/admin/mailsettings` (Speichert in `app.db`)

Verarbeitet durch `admi.route("/admin/mailsettings", methods=["POST"])` in `cps/admin.py`.
*Die neuen E-Mail-Einstellungen enthalten das vollständige Set dieses Endpoints.*

| Feldname | Typ | Standardwert | Pflichtfeld | Reboot nötig | Reset bei Abwesenheit |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `mail_server` | String | `"localhost"` | Ja | Nein | Nein |
| `mail_port` | Integer | `25` | Ja | Nein | Nein |
| `mail_use_ssl` | Integer | `0` | Ja | Nein | Nein |
| `mail_login` | String | `""` | Nein | Nein | Nein |
| `mail_password` | String | `""` | Nein | Nein | Nein |
| `mail_password_e` | String | `""` | Nein | Nein | Nein |
| `mail_from` | String | `""` | Ja | Nein | Nein |
| `mail_size` | Integer | `26214400` | Ja | Nein | Nein |
| `mail_server_type` | Integer | `0` | Ja | Nein | Nein |

---

### Endpoint `/admin/scheduledtasks` (Speichert in `app.db`)

Verarbeitet durch `admi.route("/admin/scheduledtasks", methods=["POST"])` in `cps/admin.py`.
*Validiert `schedule_start_time` und `schedule_duration` streng als Integers.*

| Feldname | Typ | Standardwert | Pflichtfeld | Reboot nötig | Reset bei Abwesenheit |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `schedule_start_time` | Integer | `4` | **Ja** | Nein | Nein |
| `schedule_duration` | Integer | `10` | **Ja** | Nein | Nein |
| `schedule_generate_book_covers` | Checkbox | `True` | Nein | Nein | Ja |
| `schedule_generate_series_covers` | Checkbox | `False` | Nein | Nein | Ja |
| `schedule_reconnect` | Checkbox | `False` | Nein | Nein | Ja |
| `schedule_metadata_backup` | Checkbox | `False` | Nein | Nein | Ja |

---

### Endpoint `/cwa-settings` (Speichert in `cwa.db`)

Verarbeitet durch `set_cwa_settings()` in `cps/cwa_functions.py`.
*Kritisch: `submit_button="Submit"` muss mitgesendet werden, sonst liefert der Handler 400. Booleans und Checkbox-Formate werden bei Abwesenheit auf False bzw. leer zurückgesetzt. `config_kobo_sync_magic_shelves` wird in `app.db` gespeichert, aber über diesen Endpoint geschickt.*

| Feldname | Typ | Standardwert | Pflichtfeld | Reboot nötig | Reset bei Abwesenheit |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `submit_button` | String | `"Submit"` | **Ja** | Nein | Nein |
| `auto_backup_imports` | Checkbox | `True` | Nein | Nein | Ja |
| `auto_backup_conversions` | Checkbox | `True` | Nein | Nein | Ja |
| `auto_zip_backups` | Checkbox | `True` | Nein | Nein | Ja |
| `cwa_update_notifications` | Checkbox | `True` | Nein | Nein | Ja |
| `contribute_translations_notifications` | Checkbox | `True` | Nein | Nein | Ja |
| `auto_convert` | Checkbox | `True` | Nein | Nein | Ja |
| `auto_convert_target_format` | String | `"epub"` | Ja | Nein | Nein |
| `auto_ingest_automerge` | String | `"new_record"` | Ja | Nein | Nein |
| `ingest_timeout_minutes` | Integer | `15` | Ja | Nein | Nein |
| `ingest_stale_temp_minutes` | Integer | `120` | Ja | Nein | Nein |
| `ingest_stale_temp_interval` | Integer | `600` | Ja | Nein | Nein |
| `auto_metadata_enforcement` | Checkbox | `True` | Nein | Nein | Ja |
| `kindle_epub_fixer` | Checkbox | `True` | Nein | Nein | Ja |
| `kindle_epub_fixer_aggressive` | Checkbox | `False` | Nein | Nein | Ja |
| `koreader_sync_enabled` | Checkbox | `False` | Nein | Nein | Ja |
| `auto_backup_epub_fixes` | Checkbox | `True` | Nein | Nein | Ja |
| `archived_cleanup_enabled` | Checkbox | `True` | Nein | Nein | Ja |
| `archived_cleanup_schedule` | String | `"daily"` | Ja | Nein | Nein |
| `archived_cleanup_schedule_day` | String | `"sunday"` | Ja | Nein | Nein |
| `archived_cleanup_schedule_hour` | Integer | `3` | Ja | Nein | Nein |
| `enable_mobile_blur` | Checkbox | `True` | Nein | Nein | Ja |
| `auto_metadata_fetch_enabled` | Checkbox | `False` | Nein | Nein | Ja |
| `auto_metadata_smart_application` | Checkbox | `False` | Nein | Nein | Ja |
| `auto_metadata_update_title` | Checkbox | `True` | Nein | Nein | Ja |
| `auto_metadata_update_authors` | Checkbox | `True` | Nein | Nein | Ja |
| `auto_metadata_update_description` | Checkbox | `True` | Nein | Nein | Ja |
| `auto_metadata_update_publisher` | Checkbox | `True` | Nein | Nein | Ja |
| `auto_metadata_update_tags` | Checkbox | `True` | Nein | Nein | Ja |
| `auto_metadata_update_series` | Checkbox | `True` | Nein | Nein | Ja |
| `auto_metadata_update_rating` | Checkbox | `True` | Nein | Nein | Ja |
| `auto_metadata_update_published_date` | Checkbox | `True` | Nein | Nein | Ja |
| `auto_metadata_update_identifiers` | Checkbox | `True` | Nein | Nein | Ja |
| `auto_metadata_update_cover` | Checkbox | `True` | Nein | Nein | Ja |
| `cover_download_max_mb` | Integer | `15` | Ja | Nein | Nein |
| `metadata_provider_hierarchy` | JSON-String | `'["ibdb","google","dnb"]'` | Ja | Nein | Nein |
| `metadata_providers_enabled` | JSON-String | `'{}'` | Ja | Nein | Nein |
| `auto_send_delay_minutes` | Integer | `5` | Ja | Nein | Nein |
| `duplicate_detection_title` | Checkbox | `True` | Nein | Nein | Ja |
| `duplicate_detection_author` | Checkbox | `True` | Nein | Nein | Ja |
| `duplicate_detection_language` | Checkbox | `True` | Nein | Nein | Ja |
| `duplicate_detection_series` | Checkbox | `False` | Nein | Nein | Ja |
| `duplicate_detection_publisher` | Checkbox | `False` | Nein | Nein | Ja |
| `duplicate_detection_format` | Checkbox | `False` | Nein | Nein | Ja |
| `duplicate_detection_enabled` | Checkbox | `True` | Nein | Nein | Ja |
| `duplicate_notifications_enabled` | Checkbox | `True` | Nein | Nein | Ja |
| `duplicate_auto_resolve_enabled` | Checkbox | `False` | Nein | Nein | Ja |
| `duplicate_auto_resolve_strategy` | String | `"newest"` | Ja | Nein | Nein |
| `duplicate_auto_resolve_cooldown_minutes` | Integer | `0` | **Ja** (Nebenfund!) | Nein | Nein |
| `duplicate_format_priority` | JSON-String | `'{"EPUB":100,...}'` | Ja | Nein | Nein |
| `duplicate_detection_use_sql` | Checkbox | `True` | Nein | Nein | Ja |
| `duplicate_scan_method` | String | `"hybrid"` | Ja | Nein | Nein |
| `duplicate_scan_enabled` | Checkbox | `True` | Nein | Nein | Ja |
| `duplicate_scan_frequency` | String | `"after_import"` | Ja | Nein | Nein |
| `duplicate_scan_cron` | String | `""` | Nein | Nein | Nein |
| `duplicate_scan_hour` | Integer | `3` | Ja | Nein | Nein |
| `duplicate_scan_chunk_size` | Integer | `5000` | Ja | Nein | Nein |
| `duplicate_scan_debounce_seconds` | Integer | `5` | Ja | Nein | Nein |
| `ignore_ingest_<format>` | Checkbox (Array) | `""` | Nein | Nein | Ja |
| `ignore_convert_<format>` | Checkbox (Array) | `""` | Nein | Nein | Ja |
| `convert_retained_<format>` | Checkbox (Array) | `""` | Nein | Nein | Ja |

#### Spezifische app.db Variablen in `/cwa-settings`
*   `config_kobo_sync_magic_shelves` (Checkbox, wird hier als `config_kobo_sync_magic_shelves` gesendet und im Handler gespeichert).

#### Google Drive / Goodreads / Hardcover (Nicht angezeigt, aber gespiegelt)
*   `hardcover_auto_fetch_enabled`
*   `hardcover_auto_fetch_schedule`
*   `hardcover_auto_fetch_schedule_day`
*   `hardcover_auto_fetch_schedule_hour`
*   `hardcover_auto_fetch_min_confidence`
*   `hardcover_auto_fetch_batch_size`
*   `hardcover_auto_fetch_rate_limit`
