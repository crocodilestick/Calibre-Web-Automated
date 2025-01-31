import sqlite3
import sys
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

        self.schema_path = "/app/calibre-web-automated/scripts/cwa_schema.sql"
        self.stats_tables = ["cwa_enforcement", "cwa_import", "cwa_conversions", "epub_fixes"]
        self.tables, self.schema = self.make_tables()

        self.cwa_default_settings = self.get_cwa_default_settings()
        self.ensure_settings_schema_match()
        self.match_stat_table_columns_with_schema()
        self.set_default_settings()
        self.temp_disable_split_library()
        self.cwa_settings = self.get_cwa_settings()


    def temp_disable_split_library(self): # Temporary measure to disable split library functionality until it can be supported in V2.2.0
        con = sqlite3.connect("/config/app.db")
        cur = con.cursor()

        current_split_setting = bool(cur.execute("SELECT config_calibre_split FROM settings").fetchone()[0])

        if current_split_setting:
            print("[ATTENTION USER]: Split Libraries (having your books in a separate location to your Calibre Library) are currently unsupported by CWA. This is something currently being worked on to be re-added in V2.2.0")
            cur.execute("UPDATE settings SET config_calibre_split=0;")
            con.commit()


    def connect_to_db(self) -> tuple[sqlite3.Connection, sqlite3.Cursor] | None:
        """Establishes connection with the db or makes one if one doesn't already exist"""
        con = None
        cur = None
        try:
            con = sqlite3.connect(self.db_path + self.db_file)
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
            self.cur.execute(f"SELECT * FROM {table}")
            setting_names = [header[0] for header in self.cur.description]
            current_column_names |= {table:setting_names}

        # Produces a dict with all of the column names for each table, from the schema
        column_names_in_schema = {}
        for table in self.tables:
            column_names = []
            table = table.split('\n')
            for line in table:
                if line[:27] == "CREATE TABLE IF NOT EXISTS ":
                    table_name = line[27:].replace('(', '')
                elif line[:4] == "    ":
                    column_names.append(line.strip().split(' ')[0])
            column_names_in_schema |= {table_name:column_names} # type: ignore

        for table in self.stats_tables:
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
                if type(self.cwa_default_settings[setting]) == int:
                    self.cur.execute(f"UPDATE cwa_settings SET {setting}={self.cwa_default_settings[setting]};")
                    self.con.commit()
                else:
                    self.cur.execute(f'UPDATE cwa_settings SET {setting}="{self.cwa_default_settings[setting]}";')
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
                if type(self.cwa_default_settings[setting]) == int:
                    self.cur.execute(f"UPDATE cwa_settings SET {setting}={self.cwa_default_settings[setting]};")
                else:
                    self.cur.execute(f'UPDATE cwa_settings SET {setting}="{self.cwa_default_settings[setting]}";')
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

        for header in headers:
            if type(cwa_settings[header]) == int:
                cwa_settings[header] = bool(cwa_settings[header])
            elif type(cwa_settings[header]) == str and ',' in cwa_settings[header]:
                cwa_settings[header] = cwa_settings[header].split(',')

        return cwa_settings


    def update_cwa_settings(self, result) -> None:
        """Sets settings using POST request from set_cwa_settings()"""
        for setting in result.keys():
            if setting == "auto_convert_ignored_formats" or setting == "auto_ingest_ignored_formats":
                result[setting] = ','.join(result[setting])

            if type(result[setting]) == int:
                self.cur.execute(f"UPDATE cwa_settings SET {setting}={result[setting]};")
            else:
                self.cur.execute(f'UPDATE cwa_settings SET {setting}="{result[setting]}";')
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

def main():
    db = CWA_DB()


if __name__ == "__main__":
    main()