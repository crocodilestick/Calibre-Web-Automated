import atexit
import json
import os
import subprocess
import sys
import tempfile
import time
import shutil

from pathlib import Path

# Global variable counting the number of books processed
books_processed = 0

# Used to generate a count of the number of books processed during each run
# 1 book is 101 as there are functions that use the scripts exit code to tell the number of processed books
# In that case, the code being over 100 indicates at least one book was processed and the actual number is the value - 100
def increment_books_processed():
    global books_processed
    if books_processed == 0:
        books_processed = 101
    else:
        books_processed += 1

# Creates a lock file unless one already exists meaning an instance of the script is
# already running, then the script is closed, the user is notified and the program
# exits with code 2
try:
    lock = open(tempfile.gettempdir() + '/ingest-processor.lock', 'x')
    lock.close()
except FileExistsError:
    print("CANCELLING... ingest-processor initiated but is already running")
    sys.exit(2)

# Make sure required directories are there
required_directories = [
    "/config/.cwa_conversion_tmp",
    "/config/processed_books",
    "/config/processed_books/imported",
    "/config/processed_books/failed",
    "/config/processed_books/converted"
]
for directory in required_directories:
    Path(directory).mkdir(exist_ok=True)
    os.system(f"chown -R abc:abc {directory}")

# Defining function to delete the lock on script exit
def removeLock():
    os.remove(tempfile.gettempdir() + '/ingest-processor.lock')

def numProcessed():
    if books_processed > 100:
        print(f"[ingest-processor] All {books_processed - 100} books found in ingest folder processed! Exiting now...")
    elif books_processed == 0:
        print("[ingest-processor] No books found to process ingest folder. Exiting now...")
    sys.exit(books_processed)

# Will automatically run when the script exits
atexit.register(removeLock)
atexit.register(numProcessed)

class NewBookProcessor:
    def __init__(self, filepath: str):
        self.supported_book_formats = ['azw', 'azw3', 'azw4', 'cbz', 'cbr', 'cb7', 'cbc', 'chm', 'djvu', 'docx', 'epub', 'fb2', 'fbz', 'html', 'htmlz', 'lit', 'lrf', 'mobi', 'odt', 'pdf', 'prc', 'pdb', 'pml', 'rb', 'rtf', 'snb', 'tcr', 'txtz']
        self.hierarchy_of_success = ['lit', 'mobi', 'azw', 'epub', 'azw3', 'fb2', 'fbz', 'azw4',  'prc', 'odt', 'lrf', 'pdb',  'cbz', 'pml', 'rb', 'cbr', 'cb7', 'cbc', 'chm', 'djvu', 'snb', 'tcr', 'pdf', 'docx', 'rtf', 'html', 'htmlz', 'txtz']
        self.ingest_folder, self.library_dir = self.get_dirs("/app/calibre-web-automated/dirs.json")
        self.tmp_conversion_dir = "/config/.cwa_conversion_tmp/"

        self.filepath = filepath # path of the book we're targeting
        self.filename = os.path.basename(filepath)
        self.is_epub: bool = bool(self.filepath.endswith('.epub'))

    def get_dirs(self, dirs_json_path: str) -> tuple[str, str, str]:
        dirs = {}
        with open(dirs_json_path, 'r') as f:
            dirs: dict[str, str] = json.load(f)

        ingest_folder = f"{dirs['ingest_folder']}/" # Dir where new files are looked for to process and subsequently deleted
        library_dir = f"{dirs['calibre_library_dir']}/"

        return ingest_folder, library_dir


    def convert_book(self, import_format: str) -> tuple[bool, str]:
        """Uses the following terminal command to convert the books provided using the calibre converter tool:\n\n--- ebook-convert myfile.input_format myfile.output_format\n\nAnd then saves the resulting epubs to the calibre-web import folder."""
        print(f"[ingest-processor]: START_CON: Converting {self.filename}...\n")
        original_filepath = Path(self.filepath)
        target_filepath = f"{self.tmp_conversion_dir}{original_filepath.stem}.epub"
        try:
            t_convert_book_start = time.time()
            subprocess.run(['ebook-convert', self.filepath, target_filepath], check=True)
            t_convert_book_end = time.time()
            time_book_conversion = t_convert_book_end - t_convert_book_start
            print(f"\n[ingest-processor]: END_CON: Conversion of {self.filename} complete in {time_book_conversion:.2f} seconds.\n")
            shutil.copyfile(self.filepath, f"/config/processed_books/converted/{os.path.basename(original_filepath)}")
            return True, target_filepath
        except subprocess.CalledProcessError as e:
            print(f"[ingest-processor]: CON_ERROR: {self.filename} could not be converted to epub due to the following error:\nEXIT/ERROR CODE: {e.returncode}\n{e.stderr}")
            shutil.copyfile(self.filepath, f"/config/processed_books/failed/{os.path.basename(original_filepath)}")
            return False, ""


    def can_convert_check(self):
        """When no epubs are detected in the download, this function will go through the list of new files 
        and check for the format the are in that has the highest chance of successful conversion according to the input format hierarchy list 
        provided by calibre"""
        can_convert = False
        import_format = ''
        for format in self.hierarchy_of_success:
            can_be_converted = bool(self.filepath.endswith(f'.{format}'))
            if can_be_converted:
                can_convert = True
                import_format = format
                break

        return can_convert, import_format


    def delete_current_file(self) -> None:
        """Deletes file just processed from ingest folder"""
        os.remove(self.filepath) # Removes processed file
        subprocess.run(["find", f"{self.ingest_folder}", "-type", "d", "-empty", "-delete"]) # Removes any now empty folders


    def add_book_to_library(self, book_path) -> None:
        print("[ingest-processor]: Importing new epub to CWA...")
        import_path = Path(book_path)
        import_filename = os.path.basename(book_path)
        try:
            subprocess.run(["calibredb", "add", book_path, f"--library-path={self.library_dir}"], check=True)
            print(f"[ingest-processor] Added {import_path.stem} to Calibre database")
            shutil.copyfile(book_path, f"/config/processed_books/imported/{import_filename}")
        except subprocess.CalledProcessError as e:
            print(f"[ingest-processor] {import_path.stem} was not able to be added to the Calibre Library due to the following error:\nCALIBREDB EXIT/ERROR CODE: {e.returncode}\n{e.stderr}")
            shutil.copyfile(book_path, f"/config/processed_books/failed/{import_filename}")


    def empty_tmp_con_dir(self):
        try:
            files = os.listdir(self.tmp_conversion_dir)
            for file in files:
                file_path = os.path.join(self.tmp_conversion_dir, file)
                if os.path.isfile(file_path):
                    os.remove(file_path)
        except OSError:
            print(f"Error occurred while emptying {self.tmp_conversion_dir}.")


def main(filepath=sys.argv[1]):
    # Check if filepath is a directory
    # If it is, main will be ran on every file in the given directory
    # Inotifywait won't detect files inside folders if the folder was moved rather than copied
    if os.path.isdir(filepath):
        print(os.listdir(filepath))
        for filename in os.listdir(filepath):
            f = os.path.join(filepath, filename)
            main(f)
        return

    nbp = NewBookProcessor(filepath)

    if not nbp.is_epub: # Books require conversion
        print(f"\n[ingest-processor]: Starting conversion process for {nbp.filename}...")
        can_convert, import_format = nbp.can_convert_check()
        print(f"[ingest-processor]: Converting file from {import_format} to epub format...\n")

        if can_convert:
            result, epub_filepath = nbp.convert_book(import_format)
            if result:
                nbp.add_book_to_library(epub_filepath)
                increment_books_processed()
                nbp.empty_tmp_con_dir()
        else:
            print(f"[ingest-processor]: Cannot convert {nbp.filepath}. {import_format} is currently unsupported.")

    else: # Books need imported
        print(f"\n[ingest-processor]: No conversion needed for {nbp.filename}, importing now...")
        npb.add_book_to_library(filepath)
        increment_books_processed()

    nbp.delete_current_file()
    del nbp # New in Version 2.0.0, should drastically reduce memory usage with large ingests

if __name__ == "__main__":
    main()