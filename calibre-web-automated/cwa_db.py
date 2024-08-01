import sqlite3
import sys
from sqlite3 import Error as sqlError

from tabulate import tabulate


class CWA_DB:
    def __init__(self):
        self.db_file = "cwa.db"
        self.db_path = "/config/"
        self.con, self.cur = self.connect_to_db()

        self.headers = {"no_path":["Timestamp", "Book ID", "Book Title", "Book Author", "Trigger Type"],
                       "with_path":["Timestamp","Book ID", "EPUB Path"]}

        self.make_table()

    def connect_to_db(self) -> tuple[sqlite3.Connection, sqlite3.Cursor] | None:
        """Establishes connection with the db or makes one if one doesn't already exist"""
        con = None
        cur = None
        try:
            con = sqlite3.connect(self.db_path + self.db_file)
        except sqlError as e:
            print(f"[cover-enforcer]: The following error occuured while trying to connect to the CWA Enforcement DB: {e}")
            sys.exit(0)
        if con:
            cur = con.cursor()
            print("[cover-enforcer]: Connection with the CWA Enforcement DB Successful!")
            return con, cur

    def make_table(self) -> None:
        """Creates the table for the CWA Enforcement DB if one doesn't already exist"""
        table = "CREATE TABLE IF NOT EXISTS cwa_enforcement(id INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL, timestamp TEXT NOT NULL, book_id INTEGER NOT NULL, book_title TEXT NOT NULL, author TEXT NOT NULL, epub_path TEXT NOT NULL, trigger_type TEXT NOT NULL);"
        self.cur.execute(table) 

    def add_entry_from_log(self, log_info: dict):
        """Adds an entry to the db from a change log file"""
        self.cur.execute("INSERT INTO cwa_enforcement(timestamp, book_id, book_title, author, epub_path, trigger_type) VALUES (?, ?, ?, ?, ?, ?);", (log_info['timestamp'], log_info['book_id'], log_info['book_title'], log_info['author_name'], log_info['epub_path'], 'auto -log'))
        self.con.commit()

    def add_entry_from_dir(self, book_info: dict):
        """Adds an entry to the db when cover-enforcer is ran with a directory"""
        self.cur.execute("INSERT INTO cwa_enforcement(timestamp, book_id, book_title, author, epub_path, trigger_type) VALUES (?, ?, ?, ?, ?, ?);", (book_info['timestamp'], book_info['book_id'], book_info['book_title'], book_info['author_name'], book_info['epub_path'], 'manual -dir'))
        self.con.commit()

    def add_entry_from_all(self, book_info: dict):
        """Adds an entry to the db when cover-enforcer is ran with the -all flag"""
        self.cur.execute("INSERT INTO cwa_enforcement(timestamp, book_id, book_title, author, epub_path, trigger_type) VALUES (?, ?, ?, ?, ?, ?);", (book_info['timestamp'], book_info['book_id'], book_info['book_title'], book_info['author_name'], book_info['epub_path'], 'manual -all'))
        self.con.commit()

    def show(self, paths: bool, verbose: bool):
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

    def manual_add_entry(self, timestamp: str, book_id: int, book_title: str, author: str, epub_path: str, trigger_type: str):
        """Allows manual additon of an entry to the db, timestamp format is YYYY-MM-DD HH:MM:SS"""
        self.cur.execute("INSERT INTO cwa_enforcement(timestamp, book_id, book_title, author, epub_path, trigger_type) VALUES (?, ?, ?, ?, ?, ?);", (timestamp, book_id, book_title, author, epub_path, trigger_type))
        self.con.commit()