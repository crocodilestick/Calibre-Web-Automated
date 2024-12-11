import os
import sys
from os.path import isfile, join
from datetime import datetime
import pathlib
from zipfile import ZipFile 

from cwa_db import CWA_DB

class AutoZipper:
    def __init__(self):
        self.archive_dirs_stem = "/config/processed_books/"
        self.converted_dir = self.archive_dirs_stem + "converted/"
        self.failed_dir = self.archive_dirs_stem + "failed/"
        self.imported_dir = self.archive_dirs_stem + "imported/"
        self.archive_dirs = [self.converted_dir, self.failed_dir, self.imported_dir]

        self.current_date = datetime.today().strftime('%Y-%m-%d')

        self.db = CWA_DB()
        self.cwa_settings = self.db.cwa_settings

        if self.cwa_settings["auto_zip_backups"]:
            self.to_zip = self.get_books_to_zip()
        else:
            print("[cwa-auto-zipper] Cancelling Auto-Zipper as the service is currently disabled in the cwa-settings panel. Exiting...")
            sys.exit(0)


    def last_mod_date(self, path_to_file) -> str:
        """ Returns the date a given file was last modified as a string """
        
        stat = os.stat(path_to_file)
        return datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d') #%H:%M:%S

    def get_books_to_zip(self) -> dict[str:list[str]]:
        """ Returns a dictionary with the books that are to be zipped together in each dir """
        to_zip = {}
        for dir in self.archive_dirs:
            dir_name = dir.split('/')[-2]
            books = [f for f in os.listdir(dir) if isfile(join(dir, f)) and pathlib.Path(f).suffix != ".zip"]
            to_zip_in_dir = []
            for book in books:
                if self.last_mod_date(dir + book) == self.current_date:
                    to_zip_in_dir.append(dir + book)
            to_zip |= {dir_name:to_zip_in_dir}

        return to_zip

    def zip_todays_books(self) -> bool:
        """ Zips the files in self.to_zip for each respective dir together if new files are found in each. If no files are zipped, the bool returned is false. """
        zip_indicator = False
        for dir in self.archive_dirs:
            dir_name = dir.split('/')[-2]
            if len(self.to_zip[dir_name]) > 0:
                zip_indicator = True
                with ZipFile(f'{self.archive_dirs_stem}{dir_name}/{self.current_date}-{dir_name}.zip', 'w') as zip:
                    for file in self.to_zip[dir_name]:
                        zip.write(file)

        return zip_indicator

    def remove_zipped_files(self) -> None:
        """ Deletes files following their successful compression """
        for dir in self.archive_dirs:
            dir_name = dir.split('/')[-2]
            for file in self.to_zip[dir_name]:
                os.remove(file)     

def main():
    try:
        zipper = AutoZipper()
        print(f"[cwa-auto-zipper] Successfully initiated, processing new files from {zipper.current_date}...\n")
        for dir in zipper.archive_dirs:
            dir_name = dir.split('/')[-2]
            if len(zipper.to_zip[dir_name]) > 0:
                print(f"[cwa-auto-zipper] {dir_name.title()} - {len(zipper.to_zip[dir_name])} file(s) found to zip.")
            else:
                print(f"[cwa-auto-zipper] {dir_name.title()} - no files found to zip.")
    except Exception as e:
        print(f"[cwa-auto-zipper] AutoZipper could not be initiated due to the following error:\n{e}")
        sys.exit(1)
    try:
        zip_indicator = zipper.zip_todays_books()
        if zip_indicator:
            print(f"\n[cwa-auto-zipper] All files from {zipper.current_date} successfully zipped! Removing zipped files...")
        else:
            print(f"\n[cwa-auto-zipper] No files from {zipper.current_date} found to be zipped. Exiting now...")
            sys.exit(0)
    except Exception as e:
        print(f"[cwa-auto-zipper] Files could not be automatically zipped due to the following error:\n{e} ")
        sys.exit(2)
    try:
        zipper.remove_zipped_files()
        print(f"[cwa-auto-zipper] All zipped files successfully removed!")
    except Exception as e:
        print(f"[cwa-auto-zipper] The following error occurred when trying to remove the zipped files:\n{e}")
        sys.exit(3)

    print(f"\n[cwa-auto-zipper] Files from {zipper.current_date} successfully processed! Exiting now...")


if __name__ == "__main__":
    main()