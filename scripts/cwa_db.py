# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2026 Calibre-Web contributors
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

import sqlite3
import sys
import os
from sqlite3 import Error as sqlError
import re
from datetime import datetime

from tabulate import tabulate


class CWA_DB:
    def __init__(self, verbose=False):
        self.verbose = verbose

        self.db_file = "cwa.db"
        self.db_path = "/config/"
        self.con, self.cur = self.connect_to_db() # type: ignore

        # Support both Docker and CI environments for schema path
        script_dir = os.path.dirname(os.path.abspath(__file__))
        self.schema_path = os.path.join(script_dir, "cwa_schema.sql")
        self.stats_tables = ["cwa_enforcement", "cwa_import", "cwa_conversions", "epub_fixes", "cwa_user_activity", "cwa_duplicate_cache", "cwa_duplicate_resolutions"]
        self.tables, self.schema = self.make_tables()

        self.cwa_default_settings = self.get_cwa_default_settings()
        self.ensure_settings_schema_match()
        self.match_stat_table_columns_with_schema()
        self.ensure_scheduled_jobs_schema()
        self.set_default_settings()
        self.cwa_settings = self.get_cwa_settings()


    def connect_to_db(self) -> tuple[sqlite3.Connection, sqlite3.Cursor] | None:
        """Establishes connection with the db or makes one if one doesn't already exist"""
        con = None
        cur = None
        try:
            con = sqlite3.connect(self.db_path + self.db_file, timeout=30)
        except sqlError as e:
            print(f"[cwa-db]: The following error occurred while trying to connect to the CWA Enforcement DB: {e}")
            sys.exit(0)
        if con:
            cur = con.cursor()
            if self.verbose:
                print("[cwa-db]: Connection with the CWA Enforcement DB Successful!")
            return con, cur


    def make_tables(self) -> tuple[list[str], list[str]]:
        """Creates the tables for the CWA DB if they don't already exist"""
        schema = []
        with open(self.schema_path, 'r') as f:
            for line in f:
                if line != "\n":
                    schema.append(line)
        tables = "".join(schema)
        tables = tables.split(';')
        tables.pop(-1)
        for x in range(len(tables)):
            tables[x] = tables[x] + ";"
        for table in tables:
            self.cur.execute(table)
            self.con.commit()

        return tables, schema


    def get_cwa_default_settings(self):
        for table in self.tables:
            if "cwa_settings" in table:
                settings_table = table.strip()
                break

        settings_lines = []
        for line in settings_table.split('\n'):
            stripped = line.strip()
            # Skip comment lines and empty lines
            if line[:4] == "    " and not stripped.startswith('--') and stripped:
                settings_lines.append(stripped)

        default_settings = {}
        for line in settings_lines:
            # Extract setting name and DEFAULT value more carefully
            # Format: setting_name TYPE DEFAULT value [NOT NULL]
            if ' DEFAULT ' not in line:
                continue
                
            setting_name = line.split()[0]
            
            # Extract everything after DEFAULT
            default_start = line.index(' DEFAULT ') + len(' DEFAULT ')
            remainder = line[default_start:].strip()
            
            # Handle different value types
            if remainder.startswith("'"):
                # String value with single quotes - could be '', or 'value', or JSON
                # Find the matching closing quote
                end_quote = remainder.index("'", 1)
                setting_value = remainder[1:end_quote]  # Extract content between quotes
            elif ' ' in remainder:
                # Value followed by other keywords (like NOT NULL)
                setting_value = remainder.split()[0]
                try:
                    setting_value = int(setting_value)
                except ValueError:
                    pass
            else:
                # Simple value at end of line
                setting_value = remainder
                try:
                    setting_value = int(setting_value)
                except ValueError:
                    pass

            default_settings |= {setting_name:setting_value}

        return default_settings


    def ensure_settings_schema_match(self) -> None:
        self.cur.execute("SELECT * FROM cwa_settings")
        cwa_setting_names = [header[0] for header in self.cur.description]
        # print(f"[cwa-db] DEBUG: Current available cwa_settings: {cwa_setting_names}")

        # Add any settings present in the schema file but not in the db
        newly_added_settings = []
        for setting in self.cwa_default_settings.keys():
            if setting not in cwa_setting_names:
                success = self.add_missing_setting(setting)
                if success:
                    print(f"[cwa-db] Setting '{setting}' successfully added to cwa.db!")
                    newly_added_settings.append(setting)
        
        # Sync newly added settings with schema defaults
        # This handles cases where schema default was updated after column was added
        if newly_added_settings:
            self.sync_new_settings_with_defaults(newly_added_settings)
        
        # Fix for issue #903: Repair incorrectly parsed default values from older versions
        self.fix_malformed_setting_values()
        
        # Delete any settings in the db but not in the schema file
        for setting in cwa_setting_names:
            if setting not in self.cwa_default_settings.keys():
                try:
                    print(f"[cwa-db] Deprecated setting found from previous version of CWA, removing setting '{setting}' from cwa.db...")
                    self.cur.execute(f"ALTER TABLE cwa_settings DROP COLUMN {setting}")  
                    self.con.commit()
                    print(f"[cwa-db] Deprecated setting '{setting}' successfully removed from cwa.db!")
                except Exception as e:
                    print(f"[cwa-db] The following error occurred when trying to remove {setting} from cwa.db:\n{e}")
    
    
    def sync_new_settings_with_defaults(self, newly_added_settings) -> None:
        """Sync newly added settings to match schema defaults
        
        This ensures that if a column was added with one default value, then the schema 
        was updated with a different default, existing databases get the new default.
        """
        try:
            # Get current values
            self.cur.execute("SELECT * FROM cwa_settings")
            headers = [header[0] for header in self.cur.description]
            current_values = dict(zip(headers, self.cur.fetchone()))
            
            # Update any newly added settings that don't match schema defaults
            updates_made = []
            for setting in newly_added_settings:
                current_val = current_values.get(setting)
                expected_val = self.cwa_default_settings.get(setting)
                
                # Compare with type handling (int vs string)
                if str(current_val) != str(expected_val):
                    self.cur.execute(f"UPDATE cwa_settings SET {setting}=?", (expected_val,))
                    updates_made.append(f"{setting}: {current_val} -> {expected_val}")
            
            if updates_made:
                self.con.commit()
                print(f"[cwa-db] Synced {len(updates_made)} new setting(s) with schema defaults:")
                for update in updates_made:
                    print(f"[cwa-db]   - {update}")
        except Exception as e:
            print(f"[cwa-db] Warning: Failed to sync new settings with defaults: {e}")


    def fix_malformed_setting_values(self) -> None:
        """Fix settings that may have been incorrectly parsed in older versions.
        
        Issue #903: Old parser would save '' as literal two-quote string and truncate JSON.
        This migration fixes existing databases with malformed values.
        """
        try:
            self.cur.execute("SELECT duplicate_scan_cron, duplicate_format_priority FROM cwa_settings")
            row = self.cur.fetchone()
            if not row:
                return
            
            cron_value, format_priority = row
            fixes_made = []
            
            # Fix duplicate_scan_cron if it's the literal string "''"
            if cron_value == "''":
                self.cur.execute("UPDATE cwa_settings SET duplicate_scan_cron = ''")
                fixes_made.append("duplicate_scan_cron: removed literal quotes")
            
            # Fix duplicate_format_priority if it's malformed (not valid JSON or missing formats)
            if format_priority:
                try:
                    import json
                    parsed = json.loads(format_priority)
                    # Check if it has at least the basic formats
                    if not isinstance(parsed, dict) or 'EPUB' not in parsed:
                        raise ValueError("Missing expected format data")
                except (json.JSONDecodeError, ValueError):
                    # Reset to default if malformed
                    default_json = self.cwa_default_settings.get('duplicate_format_priority', '{}')
                    self.cur.execute("UPDATE cwa_settings SET duplicate_format_priority = ?", (default_json,))
                    fixes_made.append("duplicate_format_priority: reset to default due to malformed JSON")
            
            if fixes_made:
                self.con.commit()
                print(f"[cwa-db] Fixed {len(fixes_made)} malformed setting value(s) from previous version:")
                for fix in fixes_made:
                    print(f"[cwa-db]   - {fix}")
        except Exception as e:
            print(f"[cwa-db] Warning: Failed to fix malformed setting values: {e}")


    def add_missing_setting(self, setting) -> bool:
        for line in self.schema:
            match = re.findall(setting, line)
            if match:
                try:
                    command = line.replace('\n', '').strip()
                    # Skip SQL comments
                    if command.startswith('--') or not command:
                        continue
                    command = command.replace(',', ';')
                    with open('/config/.cwa_db_debug', 'a') as f:
                        f.write(command)
                    self.cur.execute(f"ALTER TABLE cwa_settings ADD {command}")  
                    self.con.commit()
                    return True
                except Exception as e:
                    print(f"[cwa-db] The following error occurred when trying to add {setting} to cwa.db:\n{e}")
                    return False
        print(f"[cwa-db] Error adding new setting to cwa.db: {setting}: Matching setting could not be found in schema file")
        return False

    def match_stat_table_columns_with_schema(self) -> None:
        """ Used to rename columns whose names have been changed in later versions and add columns added in later versions """
        # Produces a dict with all of the column names for each table, from the existing DB
        current_column_names = {}
        for table in self.stats_tables:
            try:
                self.cur.execute(f"SELECT * FROM {table}")
                setting_names = [header[0] for header in self.cur.description]
                current_column_names |= {table:setting_names}
            except sqlite3.OperationalError:
                # Table might not exist yet if it's new, skip it for now
                # It will be created by make_tables() if it doesn't exist
                current_column_names |= {table: []}

        # Produces a dict with all of the column names for each table, from the schema
        column_names_in_schema = {}
        for table in self.tables:
            column_names = []
            table_name = None  # Reset for each table
            table = table.split('\n')
            for line in table:
                if line[:27] == "CREATE TABLE IF NOT EXISTS ":
                    table_name = line[27:].replace('(', '').strip()
                elif line[:4] == "    ":
                    column_names.append(line.strip().split(' ')[0])
            if table_name is not None:  # Only add if table_name was actually found
                column_names_in_schema[table_name] = column_names

        for table in self.stats_tables:
            # Skip if table wasn't found in current DB (it was just created empty)
            if not current_column_names[table]:
                continue
            
            # Skip if table not found in schema (shouldn't happen but safety check)
            if table not in column_names_in_schema:
                print(f"[cwa-db] Warning: Table '{table}' in stats_tables but not found in schema")
                continue
            
            columns_added = False  # Track if we added any columns this iteration
                
            if len(current_column_names[table]) < len(column_names_in_schema[table]): # Adds new columns not yet in existing db
                num_new_columns = len(column_names_in_schema[table]) - len(current_column_names[table])
                for x in range(1, num_new_columns + 1):
                    if column_names_in_schema[table][-x] not in current_column_names[table]:
                        for line in self.schema:
                            matches = re.findall(column_names_in_schema[table][-x], line)
                            if matches:
                                # Extract column definition, remove trailing comma and SQL comments
                                new_column = line.strip()
                                if '--' in new_column:
                                    new_column = new_column[:new_column.index('--')].strip()
                                new_column = new_column.rstrip(',')
                                self.cur.execute(f"ALTER TABLE {table} ADD COLUMN {new_column}")
                                self.con.commit()
                                print(f'[cwa-db] Missing Column detected in cwa.db. Added new column "{column_names_in_schema[table][-x]}" to table "{table}" in cwa.db')
                                columns_added = True
                                break  # Found and added the column, move to next missing column
            
            # Only check for column renames if we didn't just add columns
            # (newly added columns are correct, don't try to rename them)
            if not columns_added and len(current_column_names[table]) == len(column_names_in_schema[table]):
                # Check if all columns exist but just in different order (SQLite ADD COLUMN always appends)
                current_set = set(current_column_names[table])
                schema_set = set(column_names_in_schema[table])
                
                if current_set == schema_set:
                    # All columns exist, just in different order - this is fine, SQLite can't reorder
                    continue
                
                # Columns differ, check for actual renames needed
                for x in range(len(column_names_in_schema[table])):
                    if current_column_names[table][x] != column_names_in_schema[table][x]:
                        self.cur.execute(f"ALTER TABLE {table} RENAME COLUMN {current_column_names[table][x]} TO {column_names_in_schema[table][x]}")
                        self.con.commit()
                        print(f'[cwa-db] Fixed column mismatch between versions. Column "{current_column_names[table][x]}" in table "{table}" renamed to "{column_names_in_schema[table][x]}"', flush=True)


    def set_default_settings(self, force=False) -> None:
        """Sets default settings for new tables and keeps track if the user is using the default settings or not.\n\n
        If the argument 'force' is set to True, the function instead sets all settings to their default values"""
        if force:
            for setting in self.cwa_default_settings:
                self.cur.execute(f"UPDATE cwa_settings SET {setting}=?;", (self.cwa_default_settings[setting],))
                self.con.commit()
            print("[cwa-db] CWA Default Settings successfully applied!")
            return
        try:
            self.cur.execute("SELECT * FROM cwa_settings")
            setting_names = [header[0] for header in self.cur.description]
            current_settings = [dict(zip(setting_names,row)) for row in self.cur.fetchall()][0]
    
        except IndexError:
            print("[cwa-db]: No existing CWA settings detected, applying default CWA settings...")
            for setting in self.cwa_default_settings:
                self.cur.execute(f"UPDATE cwa_settings SET {setting}=?;", (self.cwa_default_settings[setting],))
                self.con.commit()
            print("[cwa-db] CWA Default Settings successfully applied!")
            return

        default_check = True
        for setting in setting_names:
            if setting == "default_settings":
                continue
            elif current_settings[setting] != self.cwa_default_settings[setting]:
                default_check = False
                self.cur.execute("UPDATE cwa_settings SET default_settings=0 WHERE default_settings=1;")
                self.con.commit()
                break
        if default_check:
            self.cur.execute("UPDATE cwa_settings SET default_settings=1 WHERE default_settings=0;")
            self.con.commit()

        if self.verbose:
            print("[cwa-db] CWA Settings loaded successfully")


    def get_cwa_settings(self) -> dict:
        """Gets the current cwa_settings values from the table of the same name in cwa.db and returns them as a dict"""
        self.cur.execute("SELECT * FROM cwa_settings")
        if self.cur.fetchall() == []: # If settings table is empty, populates it with default values
            self.cur.execute("INSERT INTO cwa_settings DEFAULT VALUES;")
            self.con.commit()
            
        self.cur.execute("SELECT * FROM cwa_settings")
        headers = [header[0] for header in self.cur.description]
        cwa_settings = [dict(zip(headers,row)) for row in self.cur.fetchall()][0]

        # Define default values for new columns (in case db doesn't have them yet)
        schema_defaults = {
            'hardcover_auto_fetch_enabled': 0,
            'hardcover_auto_fetch_schedule': 'weekly',
            'hardcover_auto_fetch_schedule_day': 'sunday',
            'hardcover_auto_fetch_schedule_hour': 2,
            'hardcover_auto_fetch_min_confidence': 0.85,
            'hardcover_auto_fetch_batch_size': 50,
            'hardcover_auto_fetch_rate_limit': 5.0
        }
        
        # Apply defaults for missing keys
        for key, default_value in schema_defaults.items():
            if key not in cwa_settings:
                cwa_settings[key] = default_value

        # Define which settings should remain as integers (not converted to boolean)
        integer_settings = ['ingest_timeout_minutes', 'auto_send_delay_minutes', 'hardcover_auto_fetch_batch_size', 'hardcover_auto_fetch_schedule_hour', 'duplicate_scan_hour', 'duplicate_scan_chunk_size', 'duplicate_scan_debounce_seconds']
        
        # Define which settings should remain as floats (not converted to boolean)
        float_settings = ['hardcover_auto_fetch_min_confidence', 'hardcover_auto_fetch_rate_limit']
        
        # Define which settings should remain as JSON strings (not split by comma)
        json_settings = ['metadata_provider_hierarchy', 'metadata_providers_enabled', 'duplicate_format_priority']

        for header in headers:
            if isinstance(cwa_settings[header], int) and header not in integer_settings and header not in float_settings:
                cwa_settings[header] = bool(cwa_settings[header])
            elif isinstance(cwa_settings[header], str) and ',' in cwa_settings[header] and header not in json_settings:
                cwa_settings[header] = cwa_settings[header].split(',')

        return cwa_settings


    def update_cwa_settings(self, result) -> None:
        """Sets settings using POST request from set_cwa_settings()"""
        for setting in result.keys():
            if setting == "auto_convert_ignored_formats" or setting == "auto_ingest_ignored_formats" or setting == "auto_convert_retained_formats":
                result[setting] = ','.join(result[setting])

            # Skip updates for unset values to avoid NOT NULL constraint failures
            if result[setting] is None:
                continue

            try:
                # Use parameterized queries to safely handle non-English characters and quotes
                self.cur.execute(f"UPDATE cwa_settings SET {setting}=?;", (result[setting],))
                self.con.commit()
            except Exception as e:
                print(f"[CWA_DB] Error updating setting '{setting}' with value '{result[setting]}': {e}")
                # Continue to next setting instead of failing completely
                continue
        self.set_default_settings()


    def enforce_add_entry_from_log(self, log_info: dict):
        """Adds an entry to the db from a change log file"""
        self.cur.execute("INSERT INTO cwa_enforcement(timestamp, book_id, book_title, author, file_path, trigger_type) VALUES (?, ?, ?, ?, ?, ?);", (log_info['timestamp'], log_info['book_id'], log_info['title'], log_info['authors'], log_info['file_path'], 'auto -log'))
        self.con.commit()


    def enforce_add_entry_from_dir(self, book_dicts: list[dict[str,str]]):
        """Adds an entry to the db when cover_enforcer is ran with a directory"""
        for book in book_dicts:
            self.cur.execute("INSERT INTO cwa_enforcement(timestamp, book_id, book_title, author, file_path, trigger_type) VALUES (?, ?, ?, ?, ?, ?);", (book['timestamp'], book['book_id'], book['book_title'], book['author_name'], book['file_path'], 'manual -dir'))
            self.con.commit()


    def enforce_add_entry_from_all(self, book_dicts: list[dict[str,str]]):
        """Adds an entry to the db when cover_enforcer is ran with the -all flag"""
        for book in book_dicts:
            self.cur.execute("INSERT INTO cwa_enforcement(timestamp, book_id, book_title, author, file_path, trigger_type) VALUES (?, ?, ?, ?, ?, ?);", (book['timestamp'], book['book_id'], book['book_title'], book['author_name'], book['file_path'], 'manual -all'))
            self.con.commit()


    def enforce_show(self, paths: bool, verbose: bool, web_ui=False):
        results_no_path = self.cur.execute("SELECT timestamp, book_id, book_title, author, trigger_type FROM cwa_enforcement ORDER BY timestamp DESC;").fetchall()
        results_with_path = self.cur.execute("SELECT timestamp, book_id, file_path FROM cwa_enforcement ORDER BY timestamp DESC;").fetchall()
        if paths:
            results = results_with_path
            headers = ["Timestamp", "Book ID", "Book Title", "Book Author", "Trigger Type"]
        else:
            results = results_no_path
            headers = ["Timestamp","Book ID", "Filepath"]

        if verbose:
            results.reverse()
            if web_ui:
                return results
            else:
                print(f"\n{tabulate(results, headers=headers, tablefmt='rounded_grid')}\n")
        else:
            newest_ten = []
            x = 0
            for result in results:
                newest_ten.insert(0, result)
                x += 1
                if x == 10:
                    break
            if web_ui:
                return newest_ten
            else:
                print(f"\n{tabulate(newest_ten, headers=headers, tablefmt='rounded_grid')}\n")


    def get_import_history(self, verbose: bool):
        results = self.cur.execute("SELECT timestamp, filename, original_backed_up FROM cwa_import ORDER BY timestamp DESC;").fetchall()
        if verbose:
            results.reverse()
            return results
        else:
            newest_ten = []
            x = 0
            for result in results:
                newest_ten.insert(0, result)
                x += 1
                if x == 10:
                    break
            return newest_ten


    def get_conversion_history(self, verbose: bool):
        results = self.cur.execute("SELECT timestamp, filename, original_format, end_format, original_backed_up FROM cwa_conversions ORDER BY timestamp DESC;").fetchall()
        if verbose:
            results.reverse()
            return results
        else:
            newest_ten = []
            x = 0
            for result in results:
                newest_ten.insert(0, result)
                x += 1
                if x == 10:
                    break
            return newest_ten


    def get_epub_fixer_history(self, fixes:bool, verbose: bool):
        results_no_fixes = self.cur.execute("SELECT timestamp, filename, manually_triggered, num_of_fixes_applied, original_backed_up FROM epub_fixes ORDER BY timestamp DESC;").fetchall()
        results_with_fixes = self.cur.execute("SELECT timestamp, filename, file_path, fixes_applied FROM epub_fixes ORDER BY timestamp DESC;").fetchall()
        if fixes:
            results = results_with_fixes
        else:
            results = results_no_fixes

        if verbose:
            results.reverse()
            return results
        else:
            newest_ten = []
            x = 0
            for result in results:
                newest_ten.insert(0, result)
                x += 1
                if x == 10:
                    break
            return newest_ten


    def import_add_entry(self, filename, original_backed_up):
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        self.cur.execute("INSERT INTO cwa_import(timestamp, filename, original_backed_up) VALUES (?, ?, ?);", (timestamp, filename, original_backed_up))
        self.con.commit()


    def conversion_add_entry(self, filename, original_format, end_format, original_backed_up): # TODO Add end_format - 22.11.2024 - Done?
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        self.cur.execute("INSERT INTO cwa_conversions(timestamp, filename, original_format, end_format, original_backed_up) VALUES (?, ?, ?, ?, ?);", (timestamp, filename, original_format, end_format, original_backed_up))
        self.con.commit()

    def epub_fixer_add_entry(self, filename, manually_triggered, num_of_fixes_applied, original_backed_up, file_path, fixes_applied=""):
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        self.cur.execute("INSERT INTO epub_fixes(timestamp, filename, manually_triggered, num_of_fixes_applied, original_backed_up, file_path, fixes_applied) VALUES (?, ?, ?, ?, ?, ?, ?);", (timestamp, filename, manually_triggered, num_of_fixes_applied, original_backed_up, file_path, fixes_applied))
        self.con.commit()

    def get_stat_totals(self) -> dict[str,int]:
        totals = {"cwa_enforcement":0,
                "cwa_conversions":0,
                "epub_fixes":0}
        
        for table in totals:
            try:
                totals[table] = self.cur.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            except Exception as e:
                print(f"[cwa-db] ERROR - The following error occurred when fetching stat totals:\n{e}")

        return totals

    # ==============================
    # Scheduled Jobs (Auto-Send)
    # ==============================

    def ensure_scheduled_jobs_schema(self) -> None:
        """Add missing columns to cwa_scheduled_jobs if older table exists."""
        try:
            cols = [r[1] for r in self.cur.execute("PRAGMA table_info('cwa_scheduled_jobs')").fetchall()]
            if cols:
                if 'scheduler_job_id' not in cols:
                    self.cur.execute("ALTER TABLE cwa_scheduled_jobs ADD COLUMN scheduler_job_id TEXT DEFAULT ''")
                    self.con.commit()
        except Exception:
            # If table doesn't exist yet, it will be created from schema
            pass

    def scheduled_add_autosend(self, book_id: int, user_id: int, run_at_utc_iso: str, username: str, title: str) -> int | None:
        """Insert a scheduled auto-send job and return its row id."""
        try:
            created_at = datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')
            self.cur.execute(
                """
                INSERT INTO cwa_scheduled_jobs(job_type, book_id, user_id, username, title, run_at_utc, created_at_utc, state)
                VALUES(?,?,?,?,?,?,?, 'scheduled')
                """,
                ('auto_send', int(book_id), int(user_id), username, title, run_at_utc_iso, created_at)
            )
            self.con.commit()
            return self.cur.lastrowid
        except Exception as e:
            print(f"[cwa-db] ERROR adding scheduled auto-send: {e}")
            return None

    def scheduled_add_job(self, job_type: str, run_at_utc_iso: str, username: str = 'System', title: str = '') -> int | None:
        """Insert a scheduled generic job (e.g., convert_library, epub_fixer) and return row id."""
        try:
            created_at = datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')
            self.cur.execute(
                """
                INSERT INTO cwa_scheduled_jobs(job_type, book_id, user_id, username, title, run_at_utc, created_at_utc, state)
                VALUES(?,?,?,?,?,?,?, 'scheduled')
                """,
                (str(job_type), None, None, username, title, run_at_utc_iso, created_at)
            )
            self.con.commit()
            return self.cur.lastrowid
        except Exception as e:
            print(f"[cwa-db] ERROR adding scheduled job '{job_type}': {e}")
            return None

    def scheduled_mark_dispatched(self, row_id: int) -> bool:
        try:
            # Only transition scheduled -> dispatched; ignore if already cancelled/dispatched
            self.cur.execute("UPDATE cwa_scheduled_jobs SET state='dispatched' WHERE id=? AND state='scheduled'", (int(row_id),))
            self.con.commit()
            return self.cur.rowcount > 0
        except Exception as e:
            print(f"[cwa-db] ERROR marking scheduled job dispatched: {e}")
            return False

    def scheduled_mark_cancelled(self, row_id: int) -> None:
        try:
            self.cur.execute("UPDATE cwa_scheduled_jobs SET state='cancelled' WHERE id=?", (int(row_id),))
            self.con.commit()
        except Exception as e:
            print(f"[cwa-db] ERROR marking scheduled job cancelled: {e}")

    def scheduled_cancel_for_book(self, book_id: int) -> int:
        """Cancel all scheduled jobs (auto-send, etc.) for a specific book
        
        Args:
            book_id: The book ID whose scheduled jobs should be cancelled
            
        Returns:
            int: Number of jobs cancelled
        """
        try:
            self.cur.execute(
                "UPDATE cwa_scheduled_jobs SET state='cancelled' WHERE book_id=? AND state='scheduled'",
                (int(book_id),)
            )
            self.con.commit()
            cancelled_count = self.cur.rowcount
            if cancelled_count > 0:
                print(f"[cwa-db] Cancelled {cancelled_count} scheduled job(s) for book {book_id}", flush=True)
            return cancelled_count
        except Exception as e:
            print(f"[cwa-db] ERROR cancelling scheduled jobs for book {book_id}: {e}", flush=True)
            return 0

    def scheduled_update_job_id(self, row_id: int, scheduler_job_id: str) -> None:
        try:
            self.cur.execute("UPDATE cwa_scheduled_jobs SET scheduler_job_id=? WHERE id=?", (scheduler_job_id, int(row_id)))
            self.con.commit()
        except Exception as e:
            print(f"[cwa-db] ERROR updating scheduler_job_id: {e}")

    def scheduled_get_by_id(self, row_id: int):
        try:
            row = self.cur.execute("SELECT * FROM cwa_scheduled_jobs WHERE id=?", (int(row_id),)).fetchone()
            if not row:
                return None
            cols = [d[0] for d in self.cur.description]
            return dict(zip(cols, row))
        except Exception as e:
            print(f"[cwa-db] ERROR fetching scheduled job by id: {e}")
            return None

    def scheduled_get_upcoming_autosend(self, limit: int = 50):
        try:
            now_utc = datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')
            rows = self.cur.execute(
                """
                SELECT id, book_id, user_id, username, title, run_at_utc, state
                FROM cwa_scheduled_jobs
                WHERE job_type='auto_send' AND state='scheduled' AND run_at_utc >= ?
                ORDER BY run_at_utc ASC
                LIMIT ?
                """,
                (now_utc, int(limit))
            ).fetchall()
            cols = [d[0] for d in self.cur.description]
            return [dict(zip(cols, r)) for r in rows]
        except Exception as e:
            print(f"[cwa-db] ERROR fetching upcoming scheduled auto-sends: {e}")
            return []

    def scheduled_get_upcoming_by_type(self, job_type: str, limit: int = 50):
        try:
            now_utc = datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')
            rows = self.cur.execute(
                """
                SELECT id, job_type, book_id, user_id, username, title, run_at_utc, state
                FROM cwa_scheduled_jobs
                WHERE job_type=? AND state='scheduled' AND run_at_utc >= ?
                ORDER BY run_at_utc ASC
                LIMIT ?
                """,
                (str(job_type), now_utc, int(limit))
            ).fetchall()
            cols = [d[0] for d in self.cur.description]
            return [dict(zip(cols, r)) for r in rows]
        except Exception as e:
            print(f"[cwa-db] ERROR fetching upcoming scheduled jobs for {job_type}: {e}")
            return []

    def scheduled_get_pending_autosend(self):
        """Return all not-yet-dispatched auto-sends due in the future (for rehydration)."""
        try:
            now_utc = datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')
            rows = self.cur.execute(
                """
                SELECT id, book_id, user_id, username, title, run_at_utc
                FROM cwa_scheduled_jobs
                WHERE job_type='auto_send' AND state='scheduled' AND run_at_utc >= ?
                ORDER BY run_at_utc ASC
                """,
                (now_utc,)
            ).fetchall()
            cols = [d[0] for d in self.cur.description]
            return [dict(zip(cols, r)) for r in rows]
        except Exception as e:
            print(f"[cwa-db] ERROR fetching pending scheduled auto-sends: {e}")
            return []

    def scheduled_get_pending_by_type(self, job_type: str):
        """Return all not-yet-dispatched jobs of given type due in the future (for rehydration)."""
        try:
            now_utc = datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')
            rows = self.cur.execute(
                """
                SELECT id, job_type, book_id, user_id, username, title, run_at_utc
                FROM cwa_scheduled_jobs
                WHERE job_type=? AND state='scheduled' AND run_at_utc >= ?
                ORDER BY run_at_utc ASC
                """,
                (str(job_type), now_utc)
            ).fetchall()
            cols = [d[0] for d in self.cur.description]
            return [dict(zip(cols, r)) for r in rows]
        except Exception as e:
            print(f"[cwa-db] ERROR fetching pending scheduled jobs for {job_type}: {e}")
            return []

    def log_activity(self, user_id, user_name, event_type, item_id=None, item_title=None, extra_data=None):
        """Logs a user activity event to the database with device detection."""
        try:
            import json
            
            # Parse extra_data if it's a string
            if isinstance(extra_data, str):
                try:
                    extra_data_dict = json.loads(extra_data)
                except:
                    # If not JSON, treat as simple string (legacy format compatibility)
                    extra_data_dict = {'format': extra_data}
            elif isinstance(extra_data, dict):
                extra_data_dict = extra_data
            else:
                extra_data_dict = {}
            
            # Add device type detection using User-Agent
            try:
                from flask import request
                user_agent = request.headers.get('User-Agent', '').lower()
                
                # Simple device type detection
                if 'mobile' in user_agent or 'android' in user_agent or 'iphone' in user_agent:
                    device_type = 'mobile'
                elif 'tablet' in user_agent or 'ipad' in user_agent:
                    device_type = 'tablet'
                else:
                    device_type = 'desktop'
                
                extra_data_dict['device_type'] = device_type
            except:
                # If flask context not available, skip device detection
                pass
            
            # Convert back to JSON string
            extra_data_json = json.dumps(extra_data_dict) if extra_data_dict else None
            
            self.cur.execute("""
                INSERT INTO cwa_user_activity (user_id, user_name, event_type, item_id, item_title, extra_data)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (user_id, user_name, event_type, item_id, item_title, extra_data_json))
            self.con.commit()
        except Exception as e:
            print(f"[cwa-db] Error logging activity: {e}")

    def get_active_users(self):
        """Returns list of distinct users who have activity logged."""
        try:
            self.cur.execute("""
                SELECT DISTINCT user_id, COALESCE(user_name, 'Unknown User') as user_name
                FROM cwa_user_activity
                WHERE user_id IS NOT NULL
                ORDER BY user_name ASC
            """)
            return self.cur.fetchall()
        except Exception as e:
            print(f"[cwa-db] Error fetching active users: {e}")
            return []
    def get_hourly_activity_heatmap(self, days=None, start_date=None, end_date=None, user_id=None):
        """Returns activity count by hour of day and day of week for heatmap visualization.
        
        Returns list of tuples: (day_of_week, hour, count)
        day_of_week: 0=Sunday, 1=Monday, ..., 6=Saturday
        hour: 0-23
        """
        try:
            # Build date filter
            if start_date and end_date:
                date_filter = f"timestamp BETWEEN date('{start_date}') AND date('{end_date}', '+1 day')"
            else:
                days = days or 30
                date_filter = f"timestamp >= date('now', '-{days} days')"
            
            # Add user filter if provided
            user_filter = f" AND user_id = {user_id}" if user_id else ""
            combined_filter = date_filter + user_filter
            
            self.cur.execute(f"""
                SELECT 
                    CAST(strftime('%w', timestamp) AS INTEGER) as day_of_week,
                    CAST(strftime('%H', timestamp) AS INTEGER) as hour,
                    COUNT(*) as activity_count
                FROM cwa_user_activity
                WHERE {combined_filter}
                GROUP BY day_of_week, hour
                ORDER BY day_of_week, hour
            """)
            return self.cur.fetchall()
        except Exception as e:
            print(f"[cwa-db] Error getting hourly activity heatmap: {e}")
            return []

    def get_reading_velocity(self, days=None, start_date=None, end_date=None, user_id=None):
        """Returns books read per week for velocity trend chart.
        
        Returns list of tuples: (week_start_date, books_read_count)
        """
        try:
            # Build date filter
            if start_date and end_date:
                date_filter = f"timestamp BETWEEN date('{start_date}') AND date('{end_date}', '+1 day')"
            else:
                days = days or 90  # Default to 90 days for velocity trends
                date_filter = f"timestamp >= date('now', '-{days} days')"
            
            # Add user filter if provided
            user_filter = f" AND user_id = {user_id}" if user_id else ""
            combined_filter = date_filter + user_filter
            
            self.cur.execute(f"""
                SELECT 
                    date(timestamp, 'weekday 0', '-6 days') as week_start,
                    COUNT(DISTINCT item_id) as books_read
                FROM cwa_user_activity
                WHERE event_type = 'READ'
                    AND {combined_filter}
                GROUP BY week_start
                ORDER BY week_start
            """)
            return self.cur.fetchall()
        except Exception as e:
            print(f"[cwa-db] Error getting reading velocity: {e}")
            return []

    def get_format_preferences(self, days=None, start_date=None, end_date=None, user_id=None):
        """Returns format preferences by user for stacked bar chart.
        
        Returns list of tuples: (user_name, format, count)
        """
        try:
            # Build date filter
            if start_date and end_date:
                date_filter = f"timestamp BETWEEN date('{start_date}') AND date('{end_date}', '+1 day')"
            else:
                days = days or 30
                date_filter = f"timestamp >= date('now', '-{days} days')"
            
            # Add user filter if provided
            user_filter = f" AND user_id = {user_id}" if user_id else ""
            combined_filter = date_filter + user_filter
            
            self.cur.execute(f"""
                SELECT 
                    COALESCE(user_name, 'Unknown User') as user_name,
                    UPPER(COALESCE(
                        CASE WHEN json_valid(extra_data) 
                            THEN json_extract(extra_data, '$.format')
                            ELSE extra_data
                        END,
                        'UNKNOWN'
                    )) as format,
                    COUNT(*) as count
                FROM cwa_user_activity
                WHERE event_type IN ('DOWNLOAD', 'READ', 'EMAIL')
                    AND {combined_filter}
                GROUP BY user_name, format
                ORDER BY user_name, count DESC
            """)
            return self.cur.fetchall()
        except Exception as e:
            print(f"[cwa-db] Error getting format preferences: {e}")
            return []

    def get_discovery_sources(self, days=None, start_date=None, end_date=None, user_id=None):
        """Returns count of book discoveries grouped by source.
        
        Returns list of tuples: (source, count)
        """
        try:
            # Build date filter
            if start_date and end_date:
                date_filter = f"timestamp BETWEEN date('{start_date}') AND date('{end_date}', '+1 day')"
            else:
                days = days or 30
                date_filter = f"timestamp >= date('now', '-{days} days')"
            
            # Add user filter if provided
            user_filter = f" AND user_id = {user_id}" if user_id else ""
            combined_filter = date_filter + user_filter
            
            self.cur.execute(f"""
                SELECT 
                    COALESCE(
                        CASE WHEN json_valid(extra_data) 
                            THEN json_extract(extra_data, '$.source')
                            ELSE NULL
                        END,
                        'direct'
                    ) as source,
                    COUNT(*) as count
                FROM cwa_user_activity
                WHERE event_type IN ('READ', 'DOWNLOAD')
                    AND {combined_filter}
                GROUP BY source
                ORDER BY count DESC
            """)
            return self.cur.fetchall()
        except Exception as e:
            print(f"[cwa-db] Error getting discovery sources: {e}")
            return []

    def get_device_breakdown(self, days=None, start_date=None, end_date=None, user_id=None):
        """Returns activity count grouped by device type.
        
        Returns list of tuples: (device_type, count)
        """
        try:
            # Build date filter
            if start_date and end_date:
                date_filter = f"timestamp BETWEEN date('{start_date}') AND date('{end_date}', '+1 day')"
            else:
                days = days or 30
                date_filter = f"timestamp >= date('now', '-{days} days')"
            
            # Add user filter if provided
            user_filter = f" AND user_id = {user_id}" if user_id else ""
            combined_filter = date_filter + user_filter
            
            self.cur.execute(f"""
                SELECT 
                    COALESCE(
                        CASE WHEN json_valid(extra_data) 
                            THEN json_extract(extra_data, '$.device_type')
                            ELSE NULL
                        END,
                        'unknown'
                    ) as device_type,
                    COUNT(*) as count
                FROM cwa_user_activity
                WHERE {combined_filter}
                GROUP BY device_type
                ORDER BY count DESC
            """)
            return self.cur.fetchall()
        except Exception as e:
            print(f"[cwa-db] Error getting device breakdown: {e}")
            return []

    def get_failed_logins(self, days=None, start_date=None, end_date=None):
        """Returns failed login attempts with details.
        
        Returns list of tuples: (ip, username_attempted, timestamp, count)
        """
        try:
            # Build date filter
            if start_date and end_date:
                date_filter = f"timestamp BETWEEN date('{start_date}') AND date('{end_date}', '+1 day')"
            else:
                days = days or 30
                date_filter = f"timestamp >= date('now', '-{days} days')"
            
            self.cur.execute(f"""
                SELECT 
                    json_extract(extra_data, '$.ip') as ip_address,
                    json_extract(extra_data, '$.username_attempted') as username,
                    MAX(timestamp) as last_attempt,
                    COUNT(*) as attempt_count
                FROM cwa_user_activity
                WHERE event_type = 'LOGIN_FAILED'
                    AND {date_filter}
                GROUP BY ip_address, username
                ORDER BY attempt_count DESC, last_attempt DESC
                LIMIT 20
            """)
            return self.cur.fetchall()
        except Exception as e:
            print(f"[cwa-db] Error getting failed logins: {e}")
            return []

    def get_library_growth(self, days=None, start_date=None, end_date=None):
        """Returns books added per day from Calibre metadata.db for library growth timeline.
        
        Returns list of tuples: (date, books_added_count)
        """
        try:
            import sqlite3
            
            # Connect to Calibre's metadata.db
            metadata_db_path = "/calibre-library/metadata.db"
            metadata_con = sqlite3.connect(metadata_db_path, timeout=10)
            metadata_cur = metadata_con.cursor()
            
            # Build date filter
            if start_date and end_date:
                date_filter = f"timestamp BETWEEN date('{start_date}') AND date('{end_date}', '+1 day')"
            else:
                days = days or 365  # Default to 1 year for growth chart
                date_filter = f"timestamp >= date('now', '-{days} days')"
            
            metadata_cur.execute(f"""
                SELECT 
                    date(timestamp) as add_date,
                    COUNT(*) as books_added
                FROM books
                WHERE timestamp IS NOT NULL
                    AND {date_filter}
                GROUP BY add_date
                ORDER BY add_date ASC
            """)
            result = metadata_cur.fetchall()
            metadata_con.close()
            return result
        except Exception as e:
            print(f"[cwa-db] Error getting library growth: {e}")
            return []

    def get_books_added_count(self, days=None, start_date=None, end_date=None):
        """Returns total books added in time period with trend comparison.
        
        Returns dict with: total, trend
        """
        try:
            import sqlite3
            
            # Connect to Calibre's metadata.db
            metadata_db_path = "/calibre-library/metadata.db"
            metadata_con = sqlite3.connect(metadata_db_path, timeout=10)
            metadata_cur = metadata_con.cursor()
            
            # Build date filter for current period
            if start_date and end_date:
                date_filter = f"timestamp BETWEEN date('{start_date}') AND date('{end_date}', '+1 day')"
            elif days:
                date_filter = f"timestamp >= date('now', '-{days} days')"
            else:
                date_filter = "1=1"  # All time - no filter
            
            # Get current period count
            metadata_cur.execute(f"""
                SELECT COUNT(*) as total
                FROM books
                WHERE timestamp IS NOT NULL
                    AND {date_filter}
            """)
            current = metadata_cur.fetchone()
            
            # Get previous period for trend comparison
            if start_date and end_date:
                # Calculate previous period of same duration
                from datetime import datetime, timedelta
                start_dt = datetime.strptime(start_date, '%Y-%m-%d')
                end_dt = datetime.strptime(end_date, '%Y-%m-%d')
                duration = (end_dt - start_dt).days
                prev_start = (start_dt - timedelta(days=duration)).strftime('%Y-%m-%d')
                prev_end = start_date
                prev_filter = f"timestamp BETWEEN date('{prev_start}') AND date('{prev_end}')"
            elif days:
                prev_filter = f"timestamp >= date('now', '-{days * 2} days') AND timestamp < date('now', '-{days} days')"
            else:
                # All time - no previous period comparison
                prev_filter = "1=0"  # Returns 0
            
            metadata_cur.execute(f"""
                SELECT COUNT(*) as total
                FROM books
                WHERE timestamp IS NOT NULL
                    AND {prev_filter}
            """)
            previous = metadata_cur.fetchone()
            
            total = current[0] or 0
            prev_total = previous[0] or 0
            
            # Calculate trend based on volume change
            if prev_total > 0:
                trend = ((total - prev_total) / prev_total * 100)
            else:
                trend = 0
            
            metadata_con.close()
            
            return {
                'total': total,
                'trend': round(trend, 1)
            }
        except Exception as e:
            print(f"[cwa-db] Error getting books added count: {e}")
            import traceback
            traceback.print_exc()
            return {
                'total': 0,
                'trend': 0
            }

    def get_library_formats(self, days=None, start_date=None, end_date=None):
        """Returns format distribution from Calibre metadata.db.
        
        Args:
            days: Number of days back from now (optional)
            start_date: Start date string 'YYYY-MM-DD' (optional)
            end_date: End date string 'YYYY-MM-DD' (optional)
        
        Returns list of tuples: (format, count)
        """
        try:
            import sqlite3
            
            # Connect to Calibre's metadata.db
            metadata_db_path = "/calibre-library/metadata.db"
            metadata_con = sqlite3.connect(metadata_db_path, timeout=10)
            metadata_cur = metadata_con.cursor()
            
            # Build date filter
            if start_date and end_date:
                date_filter = f"WHERE books.timestamp BETWEEN date('{start_date}') AND date('{end_date}', '+1 day')"
            elif days:
                date_filter = f"WHERE books.timestamp >= date('now', '-{days} days')"
            else:
                date_filter = ""  # No filter, show all time
            
            metadata_cur.execute(f"""
                SELECT 
                    UPPER(data.format) as format,
                    COUNT(*) as count
                FROM books
                JOIN data ON books.id = data.book
                {date_filter}
                GROUP BY format
                ORDER BY count DESC
            """)
            result = metadata_cur.fetchall()
            metadata_con.close()
            return result
        except Exception as e:
            print(f"[cwa-db] Error getting library formats: {e}")
            import traceback
            traceback.print_exc()
            return []

    def get_conversion_success_rate(self, days=None, start_date=None, end_date=None):
        """Returns conversion success statistics from cwa_conversions table.
        Note: All entries in cwa_conversions are successful (failed conversions aren't logged)
        
        Returns dict with: total, successful, failed, success_rate, trend
        """
        try:
            # Build date filter
            if start_date and end_date:
                date_filter = f"timestamp BETWEEN date('{start_date}') AND date('{end_date}', '+1 day')"
            elif days:
                date_filter = f"timestamp >= date('now', '-{days} days')"
            else:
                date_filter = "1=1"  # All time - no filter
            
            # Get current period stats - all logged conversions are successful
            self.cur.execute(f"""
                SELECT COUNT(*) as total
                FROM cwa_conversions
                WHERE {date_filter}
            """)
            current = self.cur.fetchone()
            
            # Get previous period for trend comparison
            if start_date and end_date:
                # Calculate previous period of same duration
                from datetime import datetime, timedelta
                start_dt = datetime.strptime(start_date, '%Y-%m-%d')
                end_dt = datetime.strptime(end_date, '%Y-%m-%d')
                duration = (end_dt - start_dt).days
                prev_start = (start_dt - timedelta(days=duration)).strftime('%Y-%m-%d')
                prev_end = start_date
                prev_filter = f"timestamp BETWEEN date('{prev_start}') AND date('{prev_end}')"
            elif days:
                prev_filter = f"timestamp >= date('now', '-{days * 2} days') AND timestamp < date('now', '-{days} days')"
            else:
                # All time - no previous period comparison
                prev_filter = "1=0"  # Returns 0
            
            self.cur.execute(f"""
                SELECT COUNT(*) as total
                FROM cwa_conversions
                WHERE {prev_filter}
            """)
            previous = self.cur.fetchone()
            
            total = current[0] or 0
            successful = total  # All logged conversions are successful
            failed = 0  # Failed conversions are not logged in cwa_conversions
            success_rate = 100.0 if total > 0 else 0  # 100% of logged conversions succeeded
            
            # Calculate trend based on volume change (not rate, since rate is always 100%)
            prev_total = previous[0] or 0
            if prev_total > 0:
                trend = ((total - prev_total) / prev_total * 100)
            else:
                trend = 0
            
            return {
                'total': total,
                'successful': successful,
                'failed': failed,
                'success_rate': round(success_rate, 1),
                'trend': round(trend, 1)  # Trend represents volume change
            }
        except Exception as e:
            print(f"[cwa-db] Error getting conversion success rate: {e}")
            import traceback
            traceback.print_exc()
            return {
                'total': 0,
                'successful': 0,
                'failed': 0,
                'success_rate': 0,
                'trend': 0
            }

    def get_series_completion_stats(self, limit=10):
        """Returns largest series by book count from Calibre metadata.db.
        
        Args:
            limit: Number of series to return (default 10)
        
        Returns: List of tuples: (series_name, book_count, highest_index)
        """
        try:
            import sqlite3
            
            # Connect to Calibre's metadata.db
            metadata_db_path = "/calibre-library/metadata.db"
            metadata_con = sqlite3.connect(metadata_db_path, timeout=10)
            metadata_cur = metadata_con.cursor()
            
            # Query series with book counts and highest index, ordered by count
            metadata_cur.execute(f"""
                SELECT 
                    s.name as series_name,
                    COUNT(DISTINCT bs.book) as book_count,
                    CAST(MAX(b.series_index) AS INTEGER) as highest_index
                FROM series s
                JOIN books_series_link bs ON s.id = bs.series
                JOIN books b ON bs.book = b.id
                GROUP BY s.id, s.name
                ORDER BY book_count DESC, series_name ASC
                LIMIT {limit}
            """)
            
            results = metadata_cur.fetchall()
            metadata_con.close()
            
            return results
        except Exception as e:
            print(f"[cwa-db] Error getting series completion stats: {e}")
            import traceback
            traceback.print_exc()
            return []

    def get_publication_year_distribution(self):
        """Returns distribution of books by publication year from Calibre metadata.db.
        
        Returns: List of tuples: (year, count)
        """
        try:
            import sqlite3
            
            # Connect to Calibre's metadata.db
            metadata_db_path = "/calibre-library/metadata.db"
            metadata_con = sqlite3.connect(metadata_db_path, timeout=10)
            metadata_cur = metadata_con.cursor()
            
            # Extract year from pubdate and count books
            metadata_cur.execute("""
                SELECT 
                    CAST(strftime('%Y', pubdate) as INTEGER) as year,
                    COUNT(*) as count
                FROM books
                WHERE pubdate IS NOT NULL
                    AND pubdate != '0101-01-01 00:00:00+00:00'
                    AND pubdate != ''
                GROUP BY year
                HAVING year >= 1800 AND year <= 2030
                ORDER BY year ASC
            """)
            
            results = metadata_cur.fetchall()
            metadata_con.close()
            
            return results
        except Exception as e:
            print(f"[cwa-db] Error getting publication year distribution: {e}")
            import traceback
            traceback.print_exc()
            return []

    def get_most_fixed_books(self, limit=10):
        """Returns books with most EPUB fixes applied from epub_fixes table.
        
        Args:
            limit: Number of books to return (default 10)
        
        Returns: List of tuples: (filename, fix_count, fixes_applied, last_fixed, file_path)
        """
        try:
            self.cur.execute(f"""
                SELECT 
                    filename,
                    COUNT(*) as fix_count,
                    GROUP_CONCAT(num_of_fixes_applied, ', ') as total_fixes,
                    MAX(timestamp) as last_fixed,
                    file_path
                FROM epub_fixes
                GROUP BY filename
                ORDER BY fix_count DESC, last_fixed DESC
                LIMIT {limit}
            """)
            
            return self.cur.fetchall()
        except Exception as e:
            print(f"[cwa-db] Error getting most fixed books: {e}")
            import traceback
            traceback.print_exc()
            return []

    def get_session_duration_stats(self, days=None, start_date=None, end_date=None, user_id=None):
        """Returns session duration statistics by calculating time between LOGIN events.
        
        Args:
            days: Number of days back (optional)
            start_date/end_date: Custom range 'YYYY-MM-DD' (takes precedence)
            user_id: Filter by user (optional)
        
        Returns: Dict with average_minutes, median_minutes, session_distribution
        """
        try:
            # Build date filter
            if start_date and end_date:
                date_filter = f"timestamp BETWEEN date('{start_date}') AND date('{end_date}', '+1 day')"
            else:
                days = days or 30
                date_filter = f"timestamp >= date('now', '-{days} days')"
            
            # Add user filter if provided
            user_filter = f" AND user_id = {user_id}" if user_id else ""
            combined_filter = date_filter + user_filter
            
            # Get LOGIN events ordered by user and time
            self.cur.execute(f"""
                WITH ordered_logins AS (
                    SELECT 
                        user_id,
                        user_name,
                        timestamp,
                        LEAD(timestamp) OVER (PARTITION BY user_id ORDER BY timestamp) as next_login,
                        julianday(LEAD(timestamp) OVER (PARTITION BY user_id ORDER BY timestamp)) - 
                        julianday(timestamp) as duration_days
                    FROM cwa_user_activity
                    WHERE event_type = 'LOGIN' AND {combined_filter}
                )
                SELECT 
                    ROUND(AVG(duration_days * 24 * 60), 1) as avg_minutes,
                    duration_days * 24 * 60 as session_minutes
                FROM ordered_logins
                WHERE next_login IS NOT NULL
                    AND duration_days < 1  -- Ignore sessions > 24 hours
            """)
            
            results = self.cur.fetchall()
            if not results:
                return {'average_minutes': 0, 'median_minutes': 0, 'distribution': []}
            
            # Calculate average
            avg_result = self.cur.execute(f"""
                WITH ordered_logins AS (
                    SELECT 
                        julianday(LEAD(timestamp) OVER (PARTITION BY user_id ORDER BY timestamp)) - 
                        julianday(timestamp) as duration_days
                    FROM cwa_user_activity
                    WHERE event_type = 'LOGIN' AND {combined_filter}
                )
                SELECT ROUND(AVG(duration_days * 24 * 60), 1) as avg_minutes
                FROM ordered_logins
                WHERE duration_days IS NOT NULL AND duration_days < 1
            """).fetchone()
            
            avg_minutes = avg_result[0] if avg_result and avg_result[0] else 0
            
            # Get distribution for histogram (5-minute buckets)
            self.cur.execute(f"""
                WITH ordered_logins AS (
                    SELECT 
                        julianday(LEAD(timestamp) OVER (PARTITION BY user_id ORDER BY timestamp)) - 
                        julianday(timestamp) as duration_days
                    FROM cwa_user_activity
                    WHERE event_type = 'LOGIN' AND {combined_filter}
                )
                SELECT 
                    CAST((duration_days * 24 * 60) / 5 AS INTEGER) * 5 as bucket_start,
                    COUNT(*) as count
                FROM ordered_logins
                WHERE duration_days IS NOT NULL AND duration_days < 1
                GROUP BY bucket_start
                ORDER BY bucket_start
            """)
            
            distribution = self.cur.fetchall()
            
            return {
                'average_minutes': avg_minutes,
                'distribution': distribution  # List of (bucket_start_minutes, count)
            }
            
        except Exception as e:
            print(f"[cwa-db] Error getting session duration stats: {e}")
            import traceback
            traceback.print_exc()
            return {'average_minutes': 0, 'distribution': []}

    def get_search_success_rate(self, days=None, start_date=None, end_date=None, user_id=None):
        """Returns search success rate (searches followed by DOWNLOAD/READ within 5 minutes).
        
        Args:
            days: Number of days back (optional)
            start_date/end_date: Custom range 'YYYY-MM-DD' (takes precedence)
            user_id: Filter by user (optional)
        
        Returns: Dict with total_searches, successful_searches, success_rate, trend
        """
        try:
            # Build date filter
            if start_date and end_date:
                date_filter = f"timestamp BETWEEN date('{start_date}') AND date('{end_date}', '+1 day')"
                date_filter_prev = None
            else:
                days = days or 30
                date_filter = f"timestamp >= date('now', '-{days} days')"
                date_filter_prev = f"timestamp >= date('now', '-{days * 2} days') AND timestamp < date('now', '-{days} days')"
            
            # Add user filter if provided
            user_filter = f" AND user_id = {user_id}" if user_id else ""
            combined_filter = date_filter + user_filter
            
            # Count total searches in period
            total_searches = self.cur.execute(f"""
                SELECT COUNT(*)
                FROM cwa_user_activity
                WHERE event_type = 'SEARCH' AND {combined_filter}
            """).fetchone()[0]
            
            # Count successful searches (followed by DOWNLOAD or READ within 5 minutes)
            successful_searches = self.cur.execute(f"""
                SELECT COUNT(DISTINCT s.id)
                FROM cwa_user_activity s
                WHERE s.event_type = 'SEARCH' 
                    AND {combined_filter}
                    AND EXISTS (
                        SELECT 1 FROM cwa_user_activity a
                        WHERE a.user_id = s.user_id
                            AND a.event_type IN ('DOWNLOAD', 'READ')
                            AND a.timestamp BETWEEN s.timestamp AND datetime(s.timestamp, '+5 minutes')
                    )
            """).fetchone()[0]
            
            success_rate = (successful_searches / total_searches * 100) if total_searches > 0 else 0
            
            # Calculate trend if we have previous period
            trend = 0
            if date_filter_prev:
                combined_filter_prev = date_filter_prev + user_filter
                total_prev = self.cur.execute(f"""
                    SELECT COUNT(*)
                    FROM cwa_user_activity
                    WHERE event_type = 'SEARCH' AND {combined_filter_prev}
                """).fetchone()[0]
                
                successful_prev = self.cur.execute(f"""
                    SELECT COUNT(DISTINCT s.id)
                    FROM cwa_user_activity s
                    WHERE s.event_type = 'SEARCH' 
                        AND {combined_filter_prev}
                        AND EXISTS (
                            SELECT 1 FROM cwa_user_activity a
                            WHERE a.user_id = s.user_id
                                AND a.event_type IN ('DOWNLOAD', 'READ')
                                AND a.timestamp BETWEEN s.timestamp AND datetime(s.timestamp, '+5 minutes')
                        )
                """).fetchone()[0]
                
                success_rate_prev = (successful_prev / total_prev * 100) if total_prev > 0 else 0
                trend = success_rate - success_rate_prev if success_rate_prev > 0 else 0
            
            return {
                'total_searches': total_searches,
                'successful_searches': successful_searches,
                'success_rate': round(success_rate, 1),
                'trend': round(trend, 1)
            }
            
        except Exception as e:
            print(f"[cwa-db] Error getting search success rate: {e}")
            import traceback
            traceback.print_exc()
            return {
                'total_searches': 0,
                'successful_searches': 0,
                'success_rate': 0,
                'trend': 0
            }

    def get_shelf_activity_stats(self, days=None, start_date=None, end_date=None, user_id=None, limit=10):
        """Returns most active shelves by number of additions.
        
        Args:
            days: Number of days back (optional)
            start_date/end_date: Custom range 'YYYY-MM-DD' (takes precedence)
            user_id: Filter by user (optional)
            limit: Number of shelves to return (default 10)
        
        Returns: List of tuples: (shelf_name, add_count, remove_count, net_change)
        """
        try:
            import json
            
            # Build date filter
            if start_date and end_date:
                date_filter = f"timestamp BETWEEN date('{start_date}') AND date('{end_date}', '+1 day')"
            else:
                days = days or 30
                date_filter = f"timestamp >= date('now', '-{days} days')"
            
            # Add user filter if provided
            user_filter = f" AND user_id = {user_id}" if user_id else ""
            combined_filter = date_filter + user_filter
            
            # Get shelf activity (parse shelf_name from extra_data JSON)
            self.cur.execute(f"""
                SELECT 
                    json_extract(extra_data, '$.shelf_name') as shelf_name,
                    SUM(CASE WHEN event_type = 'SHELF_ADD' THEN 1 ELSE 0 END) as add_count,
                    SUM(CASE WHEN event_type = 'SHELF_REMOVE' THEN 1 ELSE 0 END) as remove_count,
                    SUM(CASE 
                        WHEN event_type = 'SHELF_ADD' THEN 1 
                        WHEN event_type = 'SHELF_REMOVE' THEN -1 
                        ELSE 0 
                    END) as net_change,
                    SUM(CASE WHEN event_type = 'MAGIC_SHELF_VIEW' THEN 1 ELSE 0 END) as view_count,
                    json_extract(extra_data, '$.shelf_type') as shelf_type
                FROM cwa_user_activity
                WHERE event_type IN ('SHELF_ADD', 'SHELF_REMOVE', 'MAGIC_SHELF_VIEW')
                    AND {combined_filter}
                    AND json_extract(extra_data, '$.shelf_name') IS NOT NULL
                GROUP BY shelf_name
                ORDER BY (add_count + view_count) DESC, net_change DESC
                LIMIT {limit}
            """)
            
            return self.cur.fetchall()
            
        except Exception as e:
            print(f"[cwa-db] Error getting shelf activity stats: {e}")
            import traceback
            traceback.print_exc()
            return []

    def get_api_usage_breakdown(self, days=None, start_date=None, end_date=None, user_id=None):
        """Returns API usage breakdown by category (Web, Kobo, OPDS, Email).
        
        Args:
            days: Number of days back (optional)
            start_date/end_date: Custom range 'YYYY-MM-DD' (takes precedence)
            user_id: Filter by user (optional)
        
        Returns: List of tuples: (category, count)
        """
        try:
            # Build date filter
            if start_date and end_date:
                date_filter = f"timestamp BETWEEN date('{start_date}') AND date('{end_date}', '+1 day')"
            else:
                days = days or 30
                date_filter = f"timestamp >= date('now', '-{days} days')"
            
            # Add user filter if provided
            user_filter = f" AND user_id = {user_id}" if user_id else ""
            combined_filter = date_filter + user_filter
            
            # Categorize events
            self.cur.execute(f"""
                SELECT 
                    CASE 
                        WHEN event_type = 'KOBO_SYNC' THEN 'Kobo Sync'
                        WHEN event_type = 'OPDS_ACCESS' THEN 'OPDS Feed'
                        WHEN event_type = 'EMAIL' THEN 'Email Delivery'
                        WHEN event_type IN ('DOWNLOAD', 'READ', 'SEARCH', 'LOGIN') THEN 'Web UI'
                        ELSE 'Other'
                    END as category,
                    COUNT(*) as count
                FROM cwa_user_activity
                WHERE {combined_filter}
                GROUP BY category
                ORDER BY count DESC
            """)
            
            return self.cur.fetchall()
            
        except Exception as e:
            print(f"[cwa-db] Error getting API usage breakdown: {e}")
            import traceback
            traceback.print_exc()
            return []

    def get_endpoint_frequency_grouped(self, days=None, start_date=None, end_date=None, user_id=None, limit=20):
        """Returns endpoint access frequency with grouping by category.
        
        Args:
            days: Number of days back (optional)
            start_date/end_date: Custom range 'YYYY-MM-DD' (takes precedence)
            user_id: Filter by user (optional)
            limit: Number of endpoints to return (default 20)
        
        Returns: List of tuples: (endpoint, category, count, last_accessed)
        """
        try:
            import json
            
            # Build date filter
            if start_date and end_date:
                date_filter = f"timestamp BETWEEN date('{start_date}') AND date('{end_date}', '+1 day')"
            else:
                days = days or 30
                date_filter = f"timestamp >= date('now', '-{days} days')"
            
            # Add user filter if provided
            user_filter = f" AND user_id = {user_id}" if user_id else ""
            combined_filter = date_filter + user_filter
            
            # Debug: Check what event types actually exist
            debug_query = f"SELECT DISTINCT event_type FROM cwa_user_activity WHERE {combined_filter}"
            print(f"[cwa-db] Checking event types with filter: {debug_query}")
            self.cur.execute(debug_query)
            event_types = self.cur.fetchall()
            print(f"[cwa-db] Found event types: {event_types}")
            
            # Debug: Check what events exist
            query = f"""
                SELECT 
                    CASE
                        WHEN extra_data IS NOT NULL AND extra_data != '' 
                            AND json_valid(extra_data) = 1
                            AND json_extract(extra_data, '$.endpoint') IS NOT NULL 
                        THEN json_extract(extra_data, '$.endpoint')
                        ELSE event_type
                    END as endpoint,
                    CASE 
                        WHEN event_type = 'KOBO_SYNC' THEN 'Kobo'
                        WHEN event_type = 'OPDS_ACCESS' THEN 'OPDS'
                        WHEN event_type = 'EMAIL' THEN 'Email'
                        WHEN event_type = 'DOWNLOAD' THEN 'Downloads'
                        WHEN event_type = 'READ' THEN 'Reading'
                        WHEN event_type = 'SEARCH' THEN 'Search'
                        WHEN event_type = 'LOGIN' THEN 'Authentication'
                        ELSE 'Other'
                    END as category,
                    COUNT(*) as access_count,
                    MAX(timestamp) as last_accessed
                FROM cwa_user_activity
                WHERE {combined_filter}
                GROUP BY endpoint, category
                HAVING COUNT(*) > 0
                ORDER BY access_count DESC, last_accessed DESC
                LIMIT {limit}
            """
            
            print(f"[cwa-db] Endpoint frequency query: {query}")
            self.cur.execute(query)
            
            results = self.cur.fetchall()
            print(f"[cwa-db] Endpoint frequency results: {results}")
            return results
            
        except Exception as e:
            print(f"[cwa-db] Error getting endpoint frequency: {e}")
            import traceback
            traceback.print_exc()
            return []

    def get_api_timing_heatmap(self, days=None, start_date=None, end_date=None, user_id=None):
        """Returns API activity timing for heatmap (hour × day of week).
        
        Args:
            days: Number of days back (optional)
            start_date/end_date: Custom range 'YYYY-MM-DD' (takes precedence)
            user_id: Filter by user (optional)
        
        Returns: List of tuples: (day_of_week, hour, count)
        """
        try:
            # Build date filter
            if start_date and end_date:
                date_filter = f"timestamp BETWEEN date('{start_date}') AND date('{end_date}', '+1 day')"
            else:
                days = days or 30
                date_filter = f"timestamp >= date('now', '-{days} days')"
            
            # Add user filter if provided
            user_filter = f" AND user_id = {user_id}" if user_id else ""
            combined_filter = date_filter + user_filter
            
            # Get API activity by time (focus on API events)
            self.cur.execute(f"""
                SELECT 
                    CAST(strftime('%w', timestamp) AS INTEGER) as day_of_week,
                    CAST(strftime('%H', timestamp) AS INTEGER) as hour,
                    COUNT(*) as api_count
                FROM cwa_user_activity
                WHERE event_type IN ('KOBO_SYNC', 'OPDS_ACCESS', 'EMAIL', 'DOWNLOAD')
                    AND {combined_filter}
                GROUP BY day_of_week, hour
                ORDER BY day_of_week, hour
            """)
            
            return self.cur.fetchall()
            
        except Exception as e:
            print(f"[cwa-db] Error getting API timing heatmap: {e}")
            import traceback
            traceback.print_exc()
            return []

    def get_rating_statistics(self, days=None, start_date=None, end_date=None):
        """Returns rating statistics from metadata.db.
        
        Args:
            days: Number of days back (optional) - filters books added in period
            start_date/end_date: Custom range 'YYYY-MM-DD' (takes precedence)
        
        Returns: Dict with:
            - average_rating: float (0-5 scale)
            - rating_distribution: [(stars, count), ...] sorted by stars descending
            - unrated_percentage: float
            - trend: float (percentage change from previous period)
        """
        try:
            import sqlite3
            
            metadata_db_path = "/calibre-library/metadata.db"
            metadata_con = sqlite3.connect(metadata_db_path, timeout=10)
            metadata_cur = metadata_con.cursor()
            
            # Build date filter for books added in time period
            if start_date and end_date:
                date_filter = f"WHERE b.timestamp BETWEEN date('{start_date}') AND date('{end_date}', '+1 day')"
                # Calculate previous period for trend
                from datetime import datetime, timedelta
                start_dt = datetime.strptime(start_date, '%Y-%m-%d')
                end_dt = datetime.strptime(end_date, '%Y-%m-%d')
                period_days = (end_dt - start_dt).days
                prev_start = (start_dt - timedelta(days=period_days)).strftime('%Y-%m-%d')
                prev_end = start_date
                prev_date_filter = f"WHERE b.timestamp BETWEEN date('{prev_start}') AND date('{prev_end}', '+1 day')"
            elif days:
                date_filter = f"WHERE b.timestamp >= date('now', '-{days} days')"
                prev_date_filter = f"WHERE b.timestamp >= date('now', '-{days * 2} days') AND b.timestamp < date('now', '-{days} days')"
            else:
                date_filter = ""
                prev_date_filter = ""
            
            # Get average rating (convert 0-10 scale to 0-5)
            avg_query = f"""
                SELECT AVG(r.rating) / 2.0 as avg_rating
                FROM books b
                JOIN books_ratings_link brl ON b.id = brl.book
                JOIN ratings r ON brl.rating = r.id
                {date_filter.replace('WHERE', 'WHERE' if date_filter else '') if date_filter else ''}
                {'AND' if date_filter else 'WHERE'} r.rating > 0
            """
            metadata_cur.execute(avg_query)
            avg_result = metadata_cur.fetchone()
            average_rating = round(avg_result[0], 2) if avg_result and avg_result[0] else 0.0
            
            # Get previous period average for trend
            if prev_date_filter:
                prev_avg_query = f"""
                    SELECT AVG(r.rating) / 2.0 as avg_rating
                    FROM books b
                    JOIN books_ratings_link brl ON b.id = brl.book
                    JOIN ratings r ON brl.rating = r.id
                    {prev_date_filter}
                    AND r.rating > 0
                """
                metadata_cur.execute(prev_avg_query)
                prev_avg_result = metadata_cur.fetchone()
                prev_average = prev_avg_result[0] if prev_avg_result and prev_avg_result[0] else 0.0
                
                if prev_average > 0:
                    trend = round(((average_rating - prev_average) / prev_average) * 100, 1)
                else:
                    trend = 0.0
            else:
                trend = 0.0
            
            # Get rating distribution (1-5 stars)
            dist_query = f"""
                SELECT 
                    CAST(r.rating / 2 AS INTEGER) as stars,
                    COUNT(*) as count
                FROM books b
                JOIN books_ratings_link brl ON b.id = brl.book
                JOIN ratings r ON brl.rating = r.id
                {date_filter}
                {'AND' if date_filter else 'WHERE'} r.rating > 0
                GROUP BY stars
                ORDER BY stars DESC
            """
            metadata_cur.execute(dist_query)
            rating_distribution = metadata_cur.fetchall()
            
            # Get total books and unrated count
            total_query = f"SELECT COUNT(*) FROM books b {date_filter}"
            metadata_cur.execute(total_query)
            total_books = metadata_cur.fetchone()[0]
            
            unrated_query = f"""
                SELECT COUNT(*) 
                FROM books b
                LEFT JOIN books_ratings_link brl ON b.id = brl.book
                LEFT JOIN ratings r ON brl.rating = r.id
                {date_filter}
                {'AND' if date_filter else 'WHERE'} (brl.rating IS NULL OR r.rating = 0)
            """
            metadata_cur.execute(unrated_query)
            unrated_books = metadata_cur.fetchone()[0]
            
            unrated_percentage = round((unrated_books / total_books * 100), 1) if total_books > 0 else 0.0
            
            metadata_con.close()
            
            return {
                'average_rating': average_rating,
                'rating_distribution': rating_distribution,
                'unrated_percentage': unrated_percentage,
                'trend': trend,
                'total_books': total_books,
                'rated_books': total_books - unrated_books
            }
            
        except Exception as e:
            print(f"[cwa-db] Error getting rating statistics: {e}")
            import traceback
            traceback.print_exc()
            return {
                'average_rating': 0.0,
                'rating_distribution': [],
                'unrated_percentage': 0.0,
                'trend': 0.0,
                'total_books': 0,
                'rated_books': 0
            }

    def get_top_enforced_books(self, limit=10):
        """Returns top books by enforcement count (cross-database query).
        
        Args:
            limit: Number of top books to return (default 10, max 10000)
        
        Returns: List of tuples: (book_id, title, enforcement_count, last_enforced)
        """
        try:
            import sqlite3
            
            # Limit to reasonable size
            limit = min(limit, 10000)
            
            # Pass 1: Get enforcement counts from cwa.db
            self.cur.execute(f"""
                SELECT 
                    book_id,
                    COUNT(DISTINCT file_path) as enforcement_count,
                    MAX(timestamp) as last_enforced
                FROM cwa_enforcement
                GROUP BY book_id
                ORDER BY enforcement_count DESC
                LIMIT {limit}
            """)
            enforcement_data = self.cur.fetchall()
            
            if not enforcement_data:
                return []
            
            # Pass 2: Enrich with book titles from metadata.db
            metadata_db_path = "/calibre-library/metadata.db"
            metadata_con = sqlite3.connect(metadata_db_path, timeout=10)
            metadata_cur = metadata_con.cursor()
            
            results = []
            for book_id, enforcement_count, last_enforced in enforcement_data:
                try:
                    metadata_cur.execute("SELECT title FROM books WHERE id = ?", (book_id,))
                    title_result = metadata_cur.fetchone()
                    if title_result:
                        results.append((book_id, title_result[0], enforcement_count, last_enforced))
                except Exception as e:
                    print(f"[cwa-db] Error getting title for book_id {book_id}: {e}")
                    # Include with placeholder title
                    results.append((book_id, f"Book #{book_id}", enforcement_count, last_enforced))
            
            metadata_con.close()
            return results
            
        except Exception as e:
            print(f"[cwa-db] Error getting top enforced books: {e}")
            import traceback
            traceback.print_exc()
            return []

    def get_import_source_flows(self, limit=15):
        """Returns format conversion flows for Sankey diagram.
        
        Args:
            limit: Number of top flows to return (default 15)
        
        Returns: List of tuples: (source_format, target_format, count)
        """
        try:
            # Get conversion flows from cwa_conversions table
            self.cur.execute(f"""
                SELECT 
                    UPPER(original_format) as source,
                    UPPER(end_format) as target,
                    COUNT(*) as value
                FROM cwa_conversions
                WHERE original_format != '' 
                    AND original_format IS NOT NULL
                    AND end_format != '' 
                    AND end_format IS NOT NULL
                GROUP BY source, target
                ORDER BY value DESC
                LIMIT {limit}
            """)
            
            return self.cur.fetchall()
            
        except Exception as e:
            print(f"[cwa-db] Error getting import source flows: {e}")
            import traceback
            traceback.print_exc()
            return []

    def get_hourly_activity_heatmap(self, days=None, start_date=None, end_date=None, user_id=None):
        """Returns activity count by hour of day and day of week for heatmap visualization.
        
        Returns list of tuples: (day_of_week, hour, count)
        day_of_week: 0=Sunday, 1=Monday, ..., 6=Saturday
        hour: 0-23
        """
        try:
            # Build date filter
            if start_date and end_date:
                date_filter = f"timestamp BETWEEN date('{start_date}') AND date('{end_date}', '+1 day')"
            else:
                days = days or 30
                date_filter = f"timestamp >= date('now', '-{days} days')"
            
            # Add user filter if provided
            user_filter = f" AND user_id = {user_id}" if user_id else ""
            combined_filter = date_filter + user_filter
            
            self.cur.execute(f"""
                SELECT 
                    CAST(strftime('%w', timestamp) AS INTEGER) as day_of_week,
                    CAST(strftime('%H', timestamp) AS INTEGER) as hour,
                    COUNT(*) as activity_count
                FROM cwa_user_activity
                WHERE {combined_filter}
                GROUP BY day_of_week, hour
                ORDER BY day_of_week, hour
            """)
            return self.cur.fetchall()
        except Exception as e:
            print(f"[cwa-db] Error getting hourly activity heatmap: {e}")
            return []

    def get_reading_velocity(self, days=None, start_date=None, end_date=None, user_id=None):
        """Returns books read per week with data for moving average calculation.
        
        Returns list of tuples: (week_label, books_read_count)
        week_label format: 'YYYY-Www' (e.g., '2025-W01')
        """
        try:
            # Build date filter
            if start_date and end_date:
                date_filter = f"timestamp BETWEEN date('{start_date}') AND date('{end_date}', '+1 day')"
            else:
                days = days or 30
                date_filter = f"timestamp >= date('now', '-{days} days')"
            
            # Add user filter if provided
            user_filter = f" AND user_id = {user_id}" if user_id else ""
            combined_filter = date_filter + user_filter
            
            self.cur.execute(f"""
                SELECT 
                    strftime('%Y-W%W', timestamp) as week,
                    COUNT(DISTINCT item_id) as books_read
                FROM cwa_user_activity
                WHERE event_type = 'READ'
                    AND {combined_filter}
                GROUP BY week
                ORDER BY week
            """)
            return self.cur.fetchall()
        except Exception as e:
            print(f"[cwa-db] Error getting reading velocity: {e}")
            return []

    def get_format_preferences(self, days=None, start_date=None, end_date=None, user_id=None):
        """Returns format usage by user for stacked bar chart.
        
        Returns list of tuples: (user_name, format, count)
        """
        try:
            # Build date filter
            if start_date and end_date:
                date_filter = f"timestamp BETWEEN date('{start_date}') AND date('{end_date}', '+1 day')"
            else:
                days = days or 30
                date_filter = f"timestamp >= date('now', '-{days} days')"
            
            # Add user filter if provided
            user_filter = f" AND user_id = {user_id}" if user_id else ""
            combined_filter = date_filter + user_filter
            
            self.cur.execute(f"""
                SELECT 
                    COALESCE(user_name, 'Unknown User') as user_name,
                    UPPER(COALESCE(
                        json_extract(extra_data, '$.format'),
                        'Unknown'
                    )) as format,
                    COUNT(*) as count
                FROM cwa_user_activity
                WHERE event_type IN ('DOWNLOAD', 'READ')
                    AND {combined_filter}
                GROUP BY user_name, format
                ORDER BY user_name, count DESC
            """)
            return self.cur.fetchall()
        except Exception as e:
            print(f"[cwa-db] Error getting format preferences: {e}")
            return []

    def get_dashboard_stats(self, days=None, start_date=None, end_date=None, user_id=None):
        """Returns comprehensive activity stats for the user dashboard.
        
        Args:
            days: Number of days back from now (legacy support)
            start_date: Start date string 'YYYY-MM-DD' (takes precedence over days)
            end_date: End date string 'YYYY-MM-DD' (takes precedence over days)
            user_id: Filter stats for specific user ID (optional)
        """
        try:
            # Use date range if provided, otherwise fall back to days
            if start_date and end_date:
                date_filter = f"timestamp BETWEEN date('{start_date}') AND date('{end_date}', '+1 day')"
            else:
                days = days or 30  # Default to 30 days
                date_filter = f"timestamp >= date('now', '-{days} days')"
            
            # Add user filter if provided
            user_filter = f" AND user_id = {user_id}" if user_id else ""
            combined_filter = date_filter + user_filter
            
            # 1. Activity timeline - Daily counts by event type
            self.cur.execute(f"""
                SELECT date(timestamp) as day, event_type, COUNT(*) as count
                FROM cwa_user_activity 
                WHERE {combined_filter}
                GROUP BY day, event_type
                ORDER BY day ASC
            """)
            timeline_data = self.cur.fetchall()

            # 2. Top active users or most active days (depending on user filter)
            if user_id:
                # Show most active days for specific user
                self.cur.execute(f"""
                    SELECT date(timestamp) as day, COUNT(*) as activity_count
                    FROM cwa_user_activity 
                    WHERE {combined_filter}
                    GROUP BY day
                    ORDER BY activity_count DESC 
                    LIMIT 10
                """)
                top_users = self.cur.fetchall()
            else:
                # Show top active users across all users
                self.cur.execute(f"""
                    SELECT user_id, COALESCE(user_name, 'Unknown User') as user_name, COUNT(*) as activity_count
                    FROM cwa_user_activity 
                    WHERE {combined_filter}
                    GROUP BY user_id, user_name
                    ORDER BY activity_count DESC 
                    LIMIT 10
                """)
                top_users = self.cur.fetchall()

            # 3. Most popular books (reads + downloads + emails combined)
            self.cur.execute(f"""
                SELECT item_title, item_id, COUNT(*) as hits
                FROM cwa_user_activity 
                WHERE item_id IS NOT NULL 
                  AND event_type IN ('DOWNLOAD', 'READ', 'EMAIL')
                  AND {combined_filter}
                GROUP BY item_id, item_title
                ORDER BY hits DESC 
                LIMIT 10
            """)
            top_books = self.cur.fetchall()
            
            # 4. Recent search terms
            self.cur.execute(f"""
                SELECT extra_data as search_term, timestamp, user_name
                FROM cwa_user_activity 
                WHERE event_type = 'SEARCH' 
                  AND extra_data IS NOT NULL
                  AND {combined_filter}
                ORDER BY timestamp DESC 
                LIMIT 15
            """)
            recent_searches = self.cur.fetchall()

            # 5. Download format distribution
            self.cur.execute(f"""
                SELECT 
                    UPPER(COALESCE(
                        CASE WHEN json_valid(extra_data) 
                            THEN json_extract(extra_data, '$.format')
                            ELSE extra_data 
                        END,
                        'UNKNOWN'
                    )) as format,
                    COUNT(*) as count
                FROM cwa_user_activity
                WHERE event_type IN ('DOWNLOAD', 'EMAIL')
                  AND extra_data IS NOT NULL
                  AND {combined_filter}
                GROUP BY format
                ORDER BY count DESC
            """)
            format_distribution = self.cur.fetchall()

            # 6. Event type breakdown (LOGIN, DOWNLOAD, READ, SEARCH, EMAIL)
            self.cur.execute(f"""
                SELECT event_type, COUNT(*) as count
                FROM cwa_user_activity
                WHERE {combined_filter}
                GROUP BY event_type
                ORDER BY count DESC
            """)
            event_breakdown = self.cur.fetchall()

            # 7. Total activity metrics
            if user_id:
                # For single user, show total logins instead of active users
                self.cur.execute(f"""
                    SELECT 
                        COUNT(*) as total_events,
                        COUNT(CASE WHEN event_type = 'LOGIN' THEN 1 END) as total_logins,
                        COUNT(DISTINCT CASE WHEN event_type IN ('DOWNLOAD', 'EMAIL') THEN item_id END) as unique_downloads,
                        COUNT(DISTINCT CASE WHEN event_type = 'READ' THEN item_id END) as unique_reads,
                        0 as active_users,
                        COUNT(CASE WHEN event_type IN ('DOWNLOAD', 'EMAIL') THEN 1 END) as total_downloads,
                        COUNT(CASE WHEN event_type = 'READ' THEN 1 END) as total_reads,
                        COUNT(CASE WHEN event_type = 'SEARCH' THEN 1 END) as total_searches
                    FROM cwa_user_activity
                    WHERE {combined_filter}
                """)
            else:
                # For all users, show active user count
                self.cur.execute(f"""
                    SELECT 
                        COUNT(*) as total_events,
                        COUNT(CASE WHEN event_type = 'LOGIN' THEN 1 END) as total_logins,
                        COUNT(DISTINCT CASE WHEN event_type IN ('DOWNLOAD', 'EMAIL') THEN item_id END) as unique_downloads,
                        COUNT(DISTINCT CASE WHEN event_type = 'READ' THEN item_id END) as unique_reads,
                        COUNT(DISTINCT user_id) as active_users,
                        COUNT(CASE WHEN event_type IN ('DOWNLOAD', 'EMAIL') THEN 1 END) as total_downloads,
                        COUNT(CASE WHEN event_type = 'READ' THEN 1 END) as total_reads,
                        COUNT(CASE WHEN event_type = 'SEARCH' THEN 1 END) as total_searches
                    FROM cwa_user_activity
                    WHERE {combined_filter}
                """)
            totals = self.cur.fetchone()

            return {
                "timeline": timeline_data or [],
                "top_users": top_users or [],
                "top_books": top_books or [],
                "recent_searches": recent_searches or [],
                "format_distribution": format_distribution or [],
                "event_breakdown": event_breakdown or [],
                "totals": {
                    "total_events": totals[0] if totals else 0,
                    "total_logins": totals[1] if totals else 0,
                    "unique_downloads": totals[2] if totals else 0,
                    "unique_reads": totals[3] if totals else 0,
                    "active_users": totals[4] if totals else 0,
                    "total_downloads": totals[5] if totals else 0,
                    "total_reads": totals[6] if totals else 0,
                    "total_searches": totals[7] if totals else 0,
                }
            }
        except Exception as e:
            print(f"[cwa-db] Error getting dashboard stats: {e}")
            import traceback
            traceback.print_exc()
            return {
                "timeline": [],
                "top_users": [],
                "top_books": [],
                "recent_searches": [],
                "format_distribution": [],
                "event_breakdown": [],
                "totals": {
                    "total_events": 0,
                    "active_users": 0,
                    "unique_downloads": 0,
                    "unique_reads": 0,
                    "total_logins": 0,
                    "total_downloads": 0,
                    "total_reads": 0,
                    "total_searches": 0,
                }
            }

    def invalidate_duplicate_cache(self):
        """Mark duplicate cache as needing refresh"""
        try:
            self.cur.execute("""
                UPDATE cwa_duplicate_cache 
                SET scan_pending = 1 
                WHERE id = 1
            """)
            self.con.commit()
            return True
        except Exception as e:
            print(f"[cwa-db] Error invalidating duplicate cache: {e}")
            return False

    def get_duplicate_cache(self):
        """Get cached duplicate scan results"""
        import json
        try:
            self.cur.execute("""
                SELECT scan_timestamp, duplicate_groups_json, total_count, scan_pending, last_scanned_book_id
                FROM cwa_duplicate_cache 
                WHERE id = 1
            """)
            row = self.cur.fetchone()
            if row and row[1]:  # Has cached data
                return {
                    'scan_timestamp': row[0],
                    'duplicate_groups': json.loads(row[1]),
                    'total_count': row[2],
                    'scan_pending': bool(row[3]),
                    'last_scanned_book_id': row[4]
                }
            return None
        except Exception as e:
            print(f"[cwa-db] Error getting duplicate cache: {e}")
            return None

    def update_duplicate_cache(self, duplicate_groups, total_count, max_book_id=None):
        """Update duplicate cache with fresh scan results
        
        Args:
            duplicate_groups: List of duplicate group dictionaries
            total_count: Total number of duplicate groups found
            max_book_id: Maximum book ID in metadata.db (optional, for incremental scanning)
        """
        import json
        from datetime import datetime
        try:
            # Serialize duplicate groups to JSON (extract only serializable data)
            serializable_groups = []
            for group in duplicate_groups:
                serializable_group = {
                    'title': group.get('title', ''),
                    'author': group.get('author', ''),
                    'count': group.get('count', 0),
                    'group_hash': group.get('group_hash', ''),
                    'book_ids': [book.id for book in group.get('books', [])]
                }
                serializable_groups.append(serializable_group)
            
            groups_json = json.dumps(serializable_groups)
            
            # Update cache with optional max_book_id for incremental scanning
            if max_book_id is not None:
                self.cur.execute("""
                    UPDATE cwa_duplicate_cache 
                    SET scan_timestamp = ?, 
                        duplicate_groups_json = ?, 
                        total_count = ?, 
                        scan_pending = 0,
                        last_scanned_book_id = ?
                    WHERE id = 1
                """, (datetime.now().isoformat(), groups_json, total_count, max_book_id))
            else:
                self.cur.execute("""
                    UPDATE cwa_duplicate_cache 
                    SET scan_timestamp = ?, 
                        duplicate_groups_json = ?, 
                        total_count = ?, 
                        scan_pending = 0
                    WHERE id = 1
                """, (datetime.now().isoformat(), groups_json, total_count))
            self.con.commit()
            return True
        except Exception as e:
            print(f"[cwa-db] Error updating duplicate cache: {e}")
            return False

    def log_duplicate_resolution(self, group_hash, group_title, group_author, kept_book_id, 
                                 deleted_book_ids, strategy, trigger_type, user_id=None, notes=None):
        """Log a duplicate resolution to audit table"""
        import json
        try:
            self.cur.execute("""
                INSERT INTO cwa_duplicate_resolutions 
                (group_hash, group_title, group_author, kept_book_id, deleted_book_ids, 
                 strategy, trigger_type, user_id, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (group_hash, group_title, group_author, kept_book_id, 
                  json.dumps(deleted_book_ids), strategy, trigger_type, user_id, notes))
            self.con.commit()
            return True
        except Exception as e:
            print(f"[cwa-db] Error logging duplicate resolution: {e}")
            return False

    def get_resolution_history(self, limit=100):
        """Get recent resolution history"""
        import json
        try:
            self.cur.execute("""
                SELECT id, timestamp, group_hash, group_title, group_author, 
                       kept_book_id, deleted_book_ids, strategy, trigger_type, user_id, notes
                FROM cwa_duplicate_resolutions 
                ORDER BY timestamp DESC 
                LIMIT ?
            """, (limit,))
            
            results = []
            for row in self.cur.fetchall():
                results.append({
                    'id': row[0],
                    'timestamp': row[1],
                    'group_hash': row[2],
                    'group_title': row[3],
                    'group_author': row[4],
                    'kept_book_id': row[5],
                    'deleted_book_ids': json.loads(row[6]),
                    'strategy': row[7],
                    'trigger_type': row[8],
                    'user_id': row[9],
                    'notes': row[10]
                })
            return results
        except Exception as e:
            print(f"[cwa-db] Error getting resolution history: {e}")
            return []


def main():
    db = CWA_DB()


if __name__ == "__main__":
    main()
