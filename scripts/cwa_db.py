# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2025 Calibre-Web contributors
# Copyright (C) 2024-2025 Calibre-Web Automated contributors
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
        self.stats_tables = ["cwa_enforcement", "cwa_import", "cwa_conversions", "epub_fixes", "cwa_user_activity"]
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
            if line[:4] == "    ":
                settings_lines.append(line.strip())

        default_settings = {}
        for line in settings_lines:
            components = line.split(' ')
            setting_name = components[0]
            setting_value = components[3]

            try:
                setting_value = int(setting_value)
            except ValueError:
                setting_value = setting_value.replace('"', '')

            default_settings |= {setting_name:setting_value}

        return default_settings


    def ensure_settings_schema_match(self) -> None:
        self.cur.execute("SELECT * FROM cwa_settings")
        cwa_setting_names = [header[0] for header in self.cur.description]
        # print(f"[cwa-db] DEBUG: Current available cwa_settings: {cwa_setting_names}")

        # Add any settings present in the schema file but not in the db
        for setting in self.cwa_default_settings.keys():
            if setting not in cwa_setting_names:
                success = self.add_missing_setting(setting)
                if success:
                    print(f"[cwa-db] Setting '{setting}' successfully added to cwa.db!")
        
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


    def add_missing_setting(self, setting) -> bool:
        for line in self.schema:
            match = re.findall(setting, line)
            if match:
                try:
                    command = line.replace('\n', '').strip()
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
            table = table.split('\n')
            for line in table:
                if line[:27] == "CREATE TABLE IF NOT EXISTS ":
                    table_name = line[27:].replace('(', '').strip()
                elif line[:4] == "    ":
                    column_names.append(line.strip().split(' ')[0])
            if 'table_name' in locals():
                column_names_in_schema |= {table_name:column_names} # type: ignore

        for table in self.stats_tables:
            # Skip if table wasn't found in current DB (it was just created empty)
            if not current_column_names[table]:
                continue
                
            if len(current_column_names[table]) < len(column_names_in_schema[table]): # Adds new columns not yet in existing db
                num_new_columns = len(column_names_in_schema[table]) - len(current_column_names[table])
                for x in range(1, num_new_columns + 1):
                    if column_names_in_schema[table][-x] not in current_column_names[table]:
                        for line in self.schema:
                            matches = re.findall(column_names_in_schema[table][-x], line)
                            if matches:
                                new_column = line.strip().replace(',', '')
                                self.cur.execute(f"ALTER TABLE {table} ADD {new_column};")
                                self.con.commit()
                                print(f'[cwa-db] Missing Column detected in cwa.db. Added new column "{column_names_in_schema[table][-x]}" to table "{table}" in cwa.db')
            else: # Number of columns in table matches the schema, now checks whether the names are the same
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

        # Define which settings should remain as integers (not converted to boolean)
        integer_settings = ['ingest_timeout_minutes', 'auto_send_delay_minutes']
        
        # Define which settings should remain as JSON strings (not split by comma)
        json_settings = ['metadata_provider_hierarchy', 'metadata_providers_enabled']

        for header in headers:
            if isinstance(cwa_settings[header], int) and header not in integer_settings:
                cwa_settings[header] = bool(cwa_settings[header])
            elif isinstance(cwa_settings[header], str) and ',' in cwa_settings[header] and header not in json_settings:
                cwa_settings[header] = cwa_settings[header].split(',')

        return cwa_settings


    def update_cwa_settings(self, result) -> None:
        """Sets settings using POST request from set_cwa_settings()"""
        for setting in result.keys():
            if setting == "auto_convert_ignored_formats" or setting == "auto_ingest_ignored_formats" or setting == "auto_convert_retained_formats":
                result[setting] = ','.join(result[setting])

            # Use parameterized queries to safely handle non-English characters and quotes
            self.cur.execute(f"UPDATE cwa_settings SET {setting}=?;", (result[setting],))
            self.con.commit()
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
        """Logs a user activity event to the database."""
        try:
            self.cur.execute("""
                INSERT INTO cwa_user_activity (user_id, user_name, event_type, item_id, item_title, extra_data)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (user_id, user_name, event_type, item_id, item_title, extra_data))
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
                        json_extract(extra_data, '$.format'),
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
                SELECT UPPER(extra_data) as format, COUNT(*) as count
                FROM cwa_user_activity
                WHERE event_type IN ('DOWNLOAD', 'EMAIL')
                  AND extra_data IS NOT NULL
                  AND {combined_filter}
                GROUP BY UPPER(extra_data)
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

def main():
    db = CWA_DB()


if __name__ == "__main__":
    main()
