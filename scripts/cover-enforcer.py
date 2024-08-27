import argparse
import json
import os
import re
import sys
import time
from datetime import datetime

from cwa_db import CWA_DB


class Enforcer:
    def __init__(self, args):
        self.args = args
        self.dirs_json = "/app/calibre-web-automated/dirs.json"
        self.change_logs_dir = "/app/calibre-web-automated/metadata_change_logs"
        self.metadata_temp_dir = "/app/calibre-web-automated/metadata_temp"
        self.calibre_library = self.get_calibre_library()
        self.db = CWA_DB()

    def get_calibre_library(self) -> str:
        """Gets Calibre-Library location from dirs_json path"""
        with open(self.dirs_json, 'r') as f:
            dirs = json.load(f)
        return dirs['calibre_library_dir'] # Returns without / on the end

    def read_log(self, auto=True, log_path: str = "None") -> dict:
        """Reads pertinant infomation from the given log file, adds the book_id from the log name and returns the info as a dict"""
        if auto:
            book_id = (self.args.log.split('-')[1]).split('.')[0]
            timestamp_raw = self.args.log.split('-')[0]
            timestamp = datetime.strptime(timestamp_raw, '%Y%m%d%H%M%S')

            log_info = {}
            with open(f'{self.change_logs_dir}/{self.args.log}', 'r') as f:
                log_info = json.load(f)
            log_info['book_id'] = book_id
            log_info['timestamp'] = timestamp.strftime('%Y-%m-%d %H:%M:%S')
        else:
            log_name = os.path.basename(log_path)
            book_id = (log_name.split('-')[1]).split('.')[0]
            timestamp_raw = log_name.split('-')[0]
            timestamp = datetime.strptime(timestamp_raw, '%Y%m%d%H%M%S')

            log_info = {}
            with open(log_path, 'r') as f:
                log_info = json.load(f)
            log_info['book_id'] = book_id
            log_info['timestamp'] = timestamp.strftime('%Y-%m-%d %H:%M:%S')

        return log_info

    def get_book_dir_from_log(self, log_info: dict) -> str:
        book_title = log_info['book_title'].replace(':', '_')
        author_name = (log_info['author_name'].split(', ')[0]).split(' & ')[0]
        book_id = log_info['book_id']

        if '/' in book_title:
            book_title = book_title.replace('/', '_')
        if '/' in author_name:
            author_name = author_name.replace('/', '_')

        book_dir = f"{self.calibre_library}/{author_name}/{book_title} ({book_id})/"
        log_info['epub_path'] = book_dir

        return book_dir

    def enforce_cover(self, book_dir: str) -> dict:
        """Will force the Cover & Metadata to update for the book in the given directory"""
        library_files = [os.path.join(dirpath,f) for (dirpath, dirnames, filenames) in os.walk(book_dir) for f in filenames]
        epub = [f for f in library_files if f.endswith('.epub')][0]
        title_author = epub.split('/')[-1].split('.epub')[0]
        cover = book_dir + '/cover.jpg'
        old_metadata = book_dir + '/metadata.opf'

        book_id: str = (list(re.findall(r'\(\d*\)', book_dir))[-1])[1:-1]
        new_metadata = self.get_new_metadata(book_id)
        self.replace_old_metadata(old_metadata, new_metadata)

        os.system(f'ebook-polish -c "{cover}" -o "{new_metadata}" -U "{epub}" "{epub}"')
        self.empty_metadata_temp()
        print(f"[cover-enforcer]: DONE: '{title_author}': Cover & metadata updated")

        timestamp = self.get_time()
        book_title = title_author.split(f" - {title_author.split(' - ')[-1]}")[0]
        author_name = title_author.split(' - ')[-1]

        book_info = {'timestamp':timestamp, 'book_id':book_id, 'book_title':book_title, 'author_name':author_name, 'epub_path':epub}
        return book_info

    def enforce_all_covers(self) -> tuple[int, float]:
        """Will force the covers and metadata to be re-generated for all books in the library"""
        t_start = time.time()
        library_files = [os.path.join(dirpath,f) for (dirpath, dirnames, filenames) in os.walk(self.calibre_library) for f in filenames]
        epubs_in_library = [f for f in library_files if f.endswith('.epub')]
        book_dirs = []
        for epub in epubs_in_library:
            book_dirs.append(os.path.dirname(epub))

        print(f"[cover-enforcer]: {len(book_dirs)} books detected in Library")
        print(f"[cover-enforcer]: Enforcing covers for {len(epubs_in_library)} epub file(s) in {self.calibre_library} ...")

        for book_dir in book_dirs:
            book_info = self.enforce_cover(book_dir)
            self.db.add_entry_from_all(book_info)

        t_end = time.time()

        return len(epubs_in_library), (t_end - t_start)

    def get_new_metadata(self, book_id) -> str:
        """Uses the export function of the calibredb utility to export any new metadata for the given book to metadata_temp, and returns the path to the new metadata.opf"""
        os.system(f"calibredb export --with-library '{self.calibre_library}' --to-dir '{self.metadata_temp_dir}' {book_id}")
        temp_files = [os.path.join(dirpath,f) for (dirpath, dirnames, filenames) in os.walk(self.metadata_temp_dir) for f in filenames]
        return [f for f in temp_files if f.endswith('.opf')][0]

    def replace_old_metadata(self, old_metadata: str, new_metadata: str) -> None:
        """Switches the metadata in metadata_temp with the metadata in the Calibre-Library"""
        os.system(f'cp "{new_metadata}" "{old_metadata}"')

    def print_library_list(self) -> None:
        """Uses the calibredb command line utility to list the books in the library"""
        os.system(f'calibredb list --with-library "{self.calibre_library}"')

    def delete_log(self, auto=True, log_path="None"):
        """Deletes the log file"""
        if auto:
            log = os.path.join(self.change_logs_dir, self.args.log)
            os.remove(log)
        else:
            os.remove(log_path)

    def empty_metadata_temp(self):
        """Empties the metadata_temp folder"""
        os.system(f"rm -r {self.metadata_temp_dir}/*")

    def get_time(self) -> str:
        now = datetime.now()
        return now.strftime('%Y-%m-%d %H:%M:%S')

    def check_for_other_logs(self):
        log_files = [os.path.join(dirpath,f) for (dirpath, dirnames, filenames) in os.walk(self.change_logs_dir) for f in filenames]
        if len(log_files) > 0:
            for log in log_files:
                if log.endswith('.json'):
                    log_info = self.read_log(auto=False, log_path=log)
                    book_dir = self.get_book_dir_from_log(log_info)
                    book_info = self.enforce_cover(book_dir)
                    log_info['epub_path'] = book_info['epub_path']
                    self.db.add_entry_from_log(log_info)
                    self.delete_log(auto=False, log_path=log)


def main():
    parser = argparse.ArgumentParser(
        prog='cover-enforcer',
        description='Upon recieving a log, valid directory or an "-all" flag, this \
        script will enforce the covers and metadata of the corrisponding books, making \
        sure that each are correctly stored in both the epubs themselves and the \
        user\'s Calibre Library. Additionally, if an epub happens to be in EPUB 2 \
        format, it will also be automatically upgraded to EPUB 3.'
    )

    parser.add_argument('--log', action='store', dest='log', required=False, help='Will enforce the covers and metadata of the books in the given log file.', default=None)
    parser.add_argument('--dir', action='store', dest='dir', required=False, help='Will enforce the covers and metadata of the books in the given directory.', default=None)
    parser.add_argument('-all', action='store_true', dest='all', help='Will enforce covers & metadata for ALL books currently in your calibre-library-dir', default=False)
    parser.add_argument('-list', '-l', action='store_true', dest='list', help='List all books in your calibre-library-dir', default=False)
    parser.add_argument('-history', action='store_true', dest='history', help='Display a history of all enforcments ever carried out on your machine (not yet implemented)', default=False)
    parser.add_argument('-paths', '-p', action='store_true', dest='paths', help="Use with '-history' flag to display stored paths of all epubs in enforcement database", default=False)
    parser.add_argument('-v', '--verbose', action='store_true', dest='verbose', help="Use with history to display entire enforcement history instead of only the most recent 10 entries", default=False)
    args = parser.parse_args()

    enforcer = Enforcer(args)

    if len(sys.argv) == 1:
        parser.print_help()
    elif args.log is not None and args.dir is not None:
        # log and dir provided together
        parser.print_usage()
    elif args.all and args.log is None and args.dir is None and args.list is False and args.history is False:
        # only all flag passed
        print('[cover-enforcer]: Enforcing metadata and covers for all books in library...')
        n_enforced, completion_time = enforcer.enforce_all_covers()
        print(f"\n[cover-enforcer]: SUCCESS: All covers & metadata succsessfully updated for all {n_enforced} books in the library in {completion_time:.2f} seconds!")
    elif args.log is not None and args.dir is None and args.all is False and args.list is False and args.history is False:
        # log passed: (args.log), no dir
        log_info = enforcer.read_log()
        book_dir = enforcer.get_book_dir_from_log(log_info)
        book_info = enforcer.enforce_cover(book_dir)
        log_info['epub_path'] = book_info['epub_path']
        enforcer.db.add_entry_from_log(log_info)
        enforcer.delete_log()
        enforcer.check_for_other_logs()
    elif args.log is None and args.dir is not None and args.all is False and args.list is False and args.history is False:
        if args.dir[-1] == '/':
            args.dir = args.dir[:-1]
        if os.path.isdir(args.dir):
            book_info = enforcer.enforce_cover(args.dir)
            enforcer.db.add_entry_from_dir(book_info)
        else:
            print(f"[cover-enforcer]: ERROR: '{args.dir}' is not a valid directory")
    elif args.list and args.log is None and args.dir is None and args.all is False and args.history is False:
        # only list flag passed
        enforcer.print_library_list()
    elif args.history and args.log is None and args.dir is None and args.all is False and args.list is False:
        enforcer.db.show(args.paths, args.verbose)
    else:
        parser.print_usage()

    sys.exit(1)

if __name__ == "__main__":
    main()