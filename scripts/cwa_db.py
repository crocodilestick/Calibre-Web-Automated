import sqlite3
import sys
from sqlite3 import Error as sqlError
import os

from tabulate import tabulate


class CWA_DB:
    def __init__(self, verbose=False):
        self.verbose = verbose

        self.db_file = "cwa.db"
        self.db_path = "/config/"
        self.con, self.cur = self.connect_to_db()

        self.headers = {"no_path":["Timestamp", "Book ID", "Book Title", "Book Author", "Trigger Type"],
                       "with_path":["Timestamp","Book ID", "EPUB Path"]}

        self.make_tables()
        self.set_default_settings()

        self.cwa_settings = self.get_cwa_settings()

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
        with open("cwa_schema.sql", 'r') as f:
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

    def set_default_settings(self):
        """Sets default settings for new tables and keeps track if the user is using the default settings or not"""
        current_settings = self.cur.execute("SELECT * FROM cwa_settings").fetchall()
        if current_settings == []:
            self.cur.execute("INSERT INTO cwa_settings (default_settings) VALUES (1);")
            print("[cwa-db]: New DB detected, applying default CWA settings...")
            self.con.commit()
        else:
            if current_settings == [(0 ,1, 1, 1, 1, 0)]:
                self.cur.execute("UPDATE cwa_settings SET default_settings=1 WHERE default_settings=0;")
                self.con.commit()
            elif current_settings != [(1, 1, 1, 1, 1, 0)]:
                self.cur.execute("UPDATE cwa_settings SET default_settings=0 WHERE default_settings=1;")
                self.con.commit()

            if self.verbose:
                print("[cwa-db] CWA Settings loaded successfully")

    def get_cwa_settings(self) -> dict[str:bool]:
        """Gets the cwa_settings from the table of the same name in cwa.db"""
        settings_dump = self.cur.execute("PRAGMA table_info(cwa_settings)").fetchall()
        cwa_setting_names = [i[1] for i in settings_dump]
        cwa_setting_values = self.cur.execute("SELECT * FROM cwa_settings").fetchall()

        cwa_settings = {}
        for x in range(len(cwa_setting_names)):
            cwa_settings |= {cwa_setting_names[x]:bool(cwa_setting_values[0][x])}

        return cwa_settings

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

    def enforce_show(self, paths: bool, verbose: bool):
        results_no_path = self.cur.execute("SELECT timestamp, book_id, book_title, author, trigger_type FROM cwa_enforcement ORDER BY timestamp DESC;").fetchall()
        results_with_path = self.cur.execute("SELECT timestamp, book_id, epub_path FROM cwa_enforcement ORDER BY timestamp DESC;").fetchall()
        if paths:
            if verbose:
                results_with_path.reverse()
                print(f"\n{tabulate(results_with_path, headers=self.headers['with_path'], tablefmt='rounded_grid')}\n")
            else:
                newest_ten = []
                x = 0
                for result in results_with_path:
                    newest_ten.insert(0, result)
                    x += 1
                    if x == 10:
                        break
                print(f"\n{tabulate(newest_ten, headers=self.headers['with_path'], tablefmt='rounded_grid')}\n")
        else:
            if verbose:
                results_no_path.reverse()
                print(f"\n{tabulate(results_no_path, headers=self.headers['no_path'], tablefmt='rounded_grid')}\n")
            else:
                newest_ten = []
                x = 0
                for result in results_no_path:
                    newest_ten.insert(0, result)
                    x += 1
                    if x == 10:
                        break
                print(f"\n{tabulate(newest_ten, headers=self.headers['no_path'], tablefmt='rounded_grid')}\n")

    # def manual_add_entry(self, timestamp: str, book_id: int, book_title: str, author: str, epub_path: str, trigger_type: str):
    #     """Allows manual addition of an entry to the db, timestamp format is YYYY-MM-DD HH:MM:SS"""
    #     self.cur.execute("INSERT INTO cwa_enforcement(timestamp, book_id, book_title, author, epub_path, trigger_type) VALUES (?, ?, ?, ?, ?, ?);", (timestamp, book_id, book_title, author, epub_path, trigger_type))
    #     self.con.commit()

    def import_add_entry(self, timestamp, filename, original_backed_up):
        self.cur.execute("INSERT INTO cwa_conversions(timestamp, filename, original_backed_up) VALUES (?, ?, ?);", (timestamp, filename, original_backed_up))
        self.con.commit()
    
    def conversion_add_entry(self, timestamp, filename, original_format, original_backed_up):
        self.cur.execute("INSERT INTO cwa_conversions(timestamp, filename, original_format, original_backed_up) VALUES (?, ?, ?, ?);", (timestamp, filename, original_format, original_backed_up))
        self.con.commit()


def main():
    cwa_db = CWA_DB()


if __name__ == "__main__":
    main()