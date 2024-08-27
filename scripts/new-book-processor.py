import atexit
import json
import os
import subprocess
import sys
import tempfile
import time

# Global variable counting the number of books processed
books_processed = 0

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
    lock = open(tempfile.gettempdir() + '/new-book-processor.lock', 'x')
    lock.close()
except FileExistsError:
    print("CANCELING... new-book-processor initiated but is already running")
    sys.exit(2)

# Defineing function to delete the lock on script exit
def removeLock():
    os.remove(tempfile.gettempdir() + '/new-book-processor.lock')

# Will automatically run when the script exits
atexit.register(removeLock)

class NewBookProcessor:
    def __init__(self, filepath: str):
        self.supported_book_formats = ['azw', 'azw3', 'azw4', 'cbz', 'cbr', 'cb7', 'cbc', 'chm', 'djvu', 'docx', 'epub', 'fb2', 'fbz', 'html', 'htmlz', 'lit', 'lrf', 'mobi', 'odt', 'pdf', 'prc', 'pdb', 'pml', 'rb', 'rtf', 'snb', 'tcr', 'txtz']
        self.hierarchy_of_success = ['lit', 'mobi', 'azw', 'epub', 'azw3', 'fb2', 'fbz', 'azw4',  'prc', 'odt', 'lrf', 'pdb',  'cbz', 'pml', 'rb', 'cbr', 'cb7', 'cbc', 'chm', 'djvu', 'snb', 'tcr', 'pdf', 'docx', 'rtf', 'html', 'htmlz', 'txtz']
        self.import_folder, self.ingest_folder = self.get_dirs("/app/calibre-web-automated/dirs.json")

        self.filepath = filepath # path of the book we're targeting
        self.is_epub: bool = bool(self.filepath.endswith('.epub'))

    def get_dirs(self, dirs_json_path: str) -> tuple[str, str]:
        dirs = {}
        with open(dirs_json_path, 'r') as f:
            dirs: dict[str, str] = json.load(f)
        # Both folders are preassigned in dirs.json but can be changed with the 'cwa-change-dirs' command from within the container
        import_folder = f"{dirs['import_folder']}/"
        ingest_folder = f"{dirs['ingest_folder']}/" # Dir where new files are looked for to process and subsequently deleted

        return import_folder, ingest_folder


    def convert_book(self, import_format: str) -> float:
        """Uses the following terminal command to convert the books provided using the calibre converter tool:\n\n--- ebook-convert myfile.input_format myfile.output_format\n\nAnd then saves the resulting epubs to the calibre-web import folder."""
        t_convert_total_start = time.time()
        t_convert_book_start = time.time()
        filename = self.filepath.split('/')[-1]
        print(f"[new-book-processor]: START_CON: Converting {filename}...\n")
        os.system(f'ebook-convert "{self.filepath}" "{self.import_folder}{(filename.split(f".{import_format}"))[0]}.epub"')
        t_convert_book_end = time.time()
        time_book_conversion = t_convert_book_end - t_convert_book_start
        print(f"\n[new-book-processor]: END_CON: Conversion of {filename} complete in {time_book_conversion:.2f} seconds.\n")

        t_convert_total_end = time.time()
        time_total_conversion = t_convert_total_end - t_convert_total_start

        return time_total_conversion


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

    def move_epub(self) -> None:
        """Moves the epubs from the download folder to the calibre-web import folder"""
        print(f"[new-book-processor]: Moving {self.filepath}...")
        filename = self.filepath.split('/')[-1]
        os.system(f'cp "{self.filepath}" "{self.import_folder}{filename}"')

    def empty_to_process_folder(self) -> None:
        """Empties the ingest folder"""
        os.remove(self.filepath)
        subprocess.run(["find", f"{self.ingest_folder}", "-type", "d", "-empty", "-delete"])

    def delete_file(self) -> None:
        """Empties the ingest folder"""
        os.remove(self.filepath)
        subprocess.run(["find", f"{self.ingest_folder}", "-type", "d", "-empty", "-delete"])


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

    # t_start = time.time()
    nbp = NewBookProcessor(filepath)

    if not nbp.is_epub: # Books require conversion
        print("\n[new-book-processor]: No epub files found in the current directory. Starting conversion process...")
        can_convert, import_format = nbp.can_convert_check()
        print(f"[new-book-processor]: Converting file from to epub format...\n")

        if can_convert:
            time_total_conversion = nbp.convert_book(import_format)
            print(f"\n[new-book-processor]: Conversion to .epub format completed succsessfully in {time_total_conversion:.2f} seconds.")
            print("[new-book-processor]: Importing new epub to CWA...")
            increment_books_processed()
        else:
            print(f"Cannot convert {nbp.filepath}")

    else: # Books only need copying to the import folder
        print(f"\n[new-book-processor]: Found  epub file in ingest folder.")
        print("[new-book-processor]: Moving epub file to the CWA import folder...\n")
        nbp.move_epub()
        increment_books_processed()

    # t_end = time.time()
    # running_time = t_end - t_start

    # print(f"[new-book-processor]: Processing of new files completed in {running_time:.2f} seconds.\n\n")
    nbp.delete_file()
    del nbp # New in Version 2.0.0, should drastically reduce memory usage with large ingests

if __name__ == "__main__":
    main()
    sys.exit(books_processed)