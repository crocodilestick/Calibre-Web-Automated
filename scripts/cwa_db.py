import sqlite3
import sys
from sqlite3 import Error as sqlError
import os
import re
from datetime import datetime

from tabulate import tabulate


class CWA_DB:
    def __init__(self, verbose=False):
        self.verbose = verbose

        self.db_file = "cwa.db"
        self.db_path = "/config/"
        self.con, self.cur = self.connect_to_db()

        self.stats_tables_headers = {"no_path":["Timestamp", "Book ID", "Book Title", "Book Author", "Trigger Type"],
                                    "with_path":["Timestamp","Book ID", "EPUB Path"]}

        self.cwa_default_settings = {"default_settings":1,
                                    "auto_backup_imports": 1,
                                    "auto_backup_conversions": 1,
                                    "auto_zip_backups": 1,
                                    "cwa_update_notifications": 1,
                                    "auto_convert": 1,
                                    "auto_convert_target_format": "epub",
                                    "auto_convert_ignored_formats":"",
                                    "auto_import_ignored_formats":""}

        self.tables, self.schema = self.make_tables()
        self.ensure_schema_match()
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


    def make_tables(self) -> None:
        """Creates the tables for the CWA DB if they don't already exist"""
        schema = []
        with open("/app/calibre-web-automated/scripts/cwa_schema.sql", 'r') as f:
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


    def ensure_schema_match(self) -> None:
        self.cur.execute("SELECT * FROM cwa_settings")
        cwa_setting_names = [header[0] for header in self.cur.description]

        # Add any settings present in the schema file but not in the db
        for setting in self.cwa_default_settings.keys():
            if setting not in cwa_setting_names:
                for line in self.schema:
                    matches = re.findall(setting, line)
                    if matches:
                        command = line.replace('\n', '').strip()
                        command = command.replace(',', ';')
                        with open('/config/debug', 'w') as f:
                            f.write(command)
                        self.cur.execute(f"ALTER TABLE cwa_settings ADD {command}")  
                        self.con.commit()
                    else:
                        print("[cwa_db] Error adding new setting to cwa.db: Matching setting could not be found in schema file")
        
        # Delete any settings in the db but not in the schema file
        for setting in cwa_setting_names:
            if setting not in self.cwa_default_settings.keys():
                self.cur.execute(f"ALTER TABLE cwa_settings DROP COLUMN {setting}")  
                self.con.commit()
                print(f"[cwa_db] Deprecated setting found from previous version of CWA, deleting setting '{setting}' from cwa.db...")


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


    def get_cwa_settings(self) -> dict[str:bool|str]:
        """Gets the current cwa_settings values from the table of the same name in cwa.db and returns them as a dict"""
        self.cur.execute("SELECT * FROM cwa_settings")
        headers = [header[0] for header in self.cur.description]
        cwa_settings = [dict(zip(headers,row)) for row in self.cur.fetchall()][0]

        for header in headers:
            if type(cwa_settings[header]) == int:
                cwa_settings[header] = bool(cwa_settings[header])
        cwa_settings['auto_convert_ignored_formats'] = cwa_settings['auto_convert_ignored_formats'].split(',')
        cwa_settings['auto_import_ignored_formats'] = cwa_settings['auto_import_ignored_formats'].split(',')

        return cwa_settings


    def update_cwa_settings(self, result) -> None:
        """Sets settings using POST request from set_cwa_settings()"""
        for setting in result.keys():
            if setting == "auto_convert_ignored_formats" or setting == "auto_import_ignored_formats":
                result[setting] = ','.join(result[setting])

            if type(result[setting]) == int:
                self.cur.execute(f"UPDATE cwa_settings SET {setting}={result[setting]};")
            else:
                self.cur.execute(f'UPDATE cwa_settings SET {setting}="{result[setting]}";')
            self.con.commit()
        self.set_default_settings()


    def enforce_add_entry_from_log(self, log_info: dict):
        """Adds an entry to the db from a change log file"""
        self.cur.execute("INSERT INTO cwa_enforcement(timestamp, book_id, book_title, author, epub_path, trigger_type) VALUES (?, ?, ?, ?, ?, ?);", (log_info['timestamp'], log_info['book_id'], log_info['book_title'], log_info['author_name'], log_info['epub_path'], 'auto -log'))
        self.con.commit()


    def enforce_add_entry_from_dir(self, book_info: dict):
        """Adds an entry to the db when cover-enforcer is ran with a directory"""
        self.cur.execute("INSERT INTO cwa_enforcement(timestamp, book_id, book_title, author, epub_path, trigger_type) VALUES (?, ?, ?, ?, ?, ?);", (book_info['timestamp'], book_info['book_id'], book_info['book_title'], book_info['author_name'], book_info['epub_path'], 'manual -dir'))
        self.con.commit()


    def enforce_add_entry_from_all(self, book_info: dict):
        """Adds an entry to the db when cover-enforcer is ran with the -all flag"""
        self.cur.execute("INSERT INTO cwa_enforcement(timestamp, book_id, book_title, author, epub_path, trigger_type) VALUES (?, ?, ?, ?, ?, ?);", (book_info['timestamp'], book_info['book_id'], book_info['book_title'], book_info['author_name'], book_info['epub_path'], 'manual -all'))
        self.con.commit()


    def enforce_show(self, paths: bool, verbose: bool, web_ui=False):
        results_no_path = self.cur.execute("SELECT timestamp, book_id, book_title, author, trigger_type FROM cwa_enforcement ORDER BY timestamp DESC;").fetchall()
        results_with_path = self.cur.execute("SELECT timestamp, book_id, epub_path FROM cwa_enforcement ORDER BY timestamp DESC;").fetchall()
        if paths:
            if verbose:
                results_with_path.reverse()
                if web_ui:
                    return results_with_path, self.stats_tables_headers['with_path']
                else:
                    print(f"\n{tabulate(results_with_path, headers=self.stats_tables_headers['with_path'], tablefmt='rounded_grid')}\n")
            else:
                newest_ten = []
                x = 0
                for result in results_with_path:
                    newest_ten.insert(0, result)
                    x += 1
                    if x == 10:
                        break
                if web_ui:
                    return newest_ten, self.stats_tables_headers['with_path']
                else:
                    print(f"\n{tabulate(newest_ten, headers=self.stats_tables_headers['with_path'], tablefmt='rounded_grid')}\n")
        else:
            if verbose:
                results_no_path.reverse()
                if web_ui:
                    return results_no_path, self.stats_tables_headers['no_path']
                else:
                    print(f"\n{tabulate(results_no_path, headers=self.stats_tables_headers['no_path'], tablefmt='rounded_grid')}\n")
            else:
                newest_ten = []
                x = 0
                for result in results_no_path:
                    newest_ten.insert(0, result)
                    x += 1
                    if x == 10:
                        break
                if web_ui:
                    return newest_ten, self.stats_tables_headers['no_path']
                else:
                    print(f"\n{tabulate(newest_ten, headers=self.stats_tables_headers['no_path'], tablefmt='rounded_grid')}\n")

    def get_import_history(self, verbose: bool):
        headers = ["Timestamp", "Filename", "Original Backed Up?"]
        results = self.cur.execute("SELECT timestamp, filename, original_backed_up FROM cwa_import ORDER BY timestamp DESC;").fetchall()
        if verbose:
            results.reverse()
            return results, headers
        else:
            newest_ten = []
            x = 0
            for result in results:
                newest_ten.insert(0, result)
                x += 1
                if x == 10:
                    break
            return newest_ten, headers
    

    def get_conversion_history(self, verbose: bool):
        headers = ["Timestamp", "Filename", "Original Format", "Original Backed Up?"]
        results = self.cur.execute("SELECT timestamp, filename, original_format, original_backed_up FROM cwa_conversions ORDER BY timestamp DESC;").fetchall()
        if verbose:
            results.reverse()
            return results, headers
        else:
            newest_ten = []
            x = 0
            for result in results:
                newest_ten.insert(0, result)
                x += 1
                if x == 10:
                    break
            return newest_ten, headers


    def import_add_entry(self, filename, original_backed_up):
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        self.cur.execute("INSERT INTO cwa_import(timestamp, filename, original_backed_up) VALUES (?, ?, ?);", (timestamp, filename, original_backed_up))
        self.con.commit()


    def conversion_add_entry(self, filename, original_format, original_backed_up):
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        self.cur.execute("INSERT INTO cwa_conversions(timestamp, filename, original_format, original_backed_up) VALUES (?, ?, ?, ?);", (timestamp, filename, original_format, original_backed_up))
        self.con.commit()


def main():
    cwa_db = CWA_DB()


if __name__ == "__main__":
    main()