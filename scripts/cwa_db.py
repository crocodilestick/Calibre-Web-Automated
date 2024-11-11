import sqlite3
import sys
from sqlite3 import Error as sqlError
import os
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

        self.cwa_default_settings = {"auto_backup_imports": 1,
                                     "auto_backup_conversions": 1,
                                     "auto_zip_backups": 1,
                                     "cwa_update_notifications": 1,
                                     "auto_convert": 1,
                                     "auto_convert_target_format": "epub",
                                     "cwa_ignored_formats":[]}

        self.make_tables()
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

    def set_default_settings(self, force=False) -> None:
        """Sets default settings for new tables and keeps track if the user is using the default settings or not"""
        if force:
            for setting in self.cwa_default_settings:
                self.cur.execute(f"UPDATE cwa_settings SET {setting}={self.cwa_default_settings[setting]};")
                self.con.commit()
            print("[cwa-db] CWA Default Settings successfully applied.")
        
        current_settings = self.cur.execute("SELECT * FROM cwa_settings").fetchall()
        if current_settings == []:
            print("[cwa-db]: New DB detected, applying default CWA settings...")
            for setting in self.cwa_default_settings:
                self.cur.execute(f"UPDATE cwa_settings SET {setting}={self.cwa_default_settings[setting]};")
                self.con.commit()
        else:
            if current_settings == [(0, 1, 1, 1, 1, 0, 1, "epub", "")]:
                self.cur.execute("UPDATE cwa_settings SET default_settings=1 WHERE default_settings=0;")
                self.con.commit()
            elif current_settings != [(1, 1, 1, 1, 1, 0, "epub", "")]:
                self.cur.execute("UPDATE cwa_settings SET default_settings=0 WHERE default_settings=1;")
                self.con.commit()

            if self.verbose:
                print("[cwa-db] CWA Settings loaded successfully")

    def get_cwa_settings(self) -> dict[str:bool|str]:
        """Gets the cwa_settings from the table of the same name in cwa.db"""
        settings_dump = self.cur.execute("PRAGMA table_info(cwa_settings)").fetchall()
        cwa_setting_names = [i[1] for i in settings_dump]
        cwa_setting_values = self.cur.execute("SELECT * FROM cwa_settings").fetchall()

        cwa_settings = {}
        for x in range(len(cwa_setting_names)):
            if type(cwa_setting_values[0][x]) == int:
                cwa_settings |= {cwa_setting_names[x]:bool(cwa_setting_values[0][x])}
            else:
                cwa_settings |= {cwa_setting_names[x]:cwa_setting_values[0][x]}

        cwa_settings['cwa_ignored_formats'] = cwa_settings['cwa_ignored_formats'].split(',')

        return cwa_settings

    def update_cwa_settings(self, result) -> None:
        """Sets settings using POST request from set_cwa_settings()"""
        settings = result.keys()
        for setting in settings:
            self.cur.execute(f"UPDATE cwa_settings SET {setting}={result[setting]};")
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