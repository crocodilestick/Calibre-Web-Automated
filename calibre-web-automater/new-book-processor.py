import json
import os
import sys
import time

supported_book_formats = ['azw', 'azw3', 'azw4', 'cbz', 'cbr', 'cb7', 'cbc', 'chm', 'djvu', 'docx', 'epub', 'fb2', 'fbz', 'html', 'htmlz', 'lit', 'lrf', 'mobi', 'odt', 'pdf', 'prc', 'pdb', 'pml', 'rb', 'rtf', 'snb', 'tcr', 'txt', 'txtz']
hierarchy_of_succsess = ['lit', 'mobi', 'azw', 'epub', 'azw3', 'fb2', 'fbz', 'azw4',  'prc', 'odt', 'lrf', 'pdb',  'cbz', 'pml', 'rb', 'cbr', 'cb7', 'cbc', 'chm', 'djvu', 'snb', 'tcr', 'pdf', 'docx', 'rtf', 'html', 'htmlz', 'txtz', 'txt']

dirs = {}
with open('dirs.json', 'r') as f: # '/etc/calibre-web-automater/dirs.json'
    dirs: dict[str, str] = json.load(f)

# Both folders are assigned by user during setup
import_folder = f"{dirs['import_folder']}/" # Make sure this folder exists, the permissions are correct and the path is in the following format: "/book/to_calibre/"
ingest_folder = f"{dirs['ingest_folder']}/" # Dir where new files are looked for to process and subsequently deleted

def main():
    t_start = time.time()

    new_files = [os.path.join(dirpath,f) for (dirpath, dirnames, filenames) in os.walk(ingest_folder) for f in filenames] 
    epub_files = [f for f in new_files if f.endswith('.epub')]

    if len(epub_files) == 0: # Books require conversion
        print("\nNo epub files found in the current directory. Starting conversion process...")
        files_to_convert, import_format = select_books_for_conversion(new_files)
        print(f"Converting {len(files_to_convert)} file(s) from to epub format...\n")
        time_total_conversion = convert_books(files_to_convert, import_format)
        print(f"\n{len(files_to_convert)} conversion(s) to .epub format completed succsessfully in {time_total_conversion:.2f} seconds.")
        print("All new epub files have now been moved to the calibre-web import folder.")
    else: # Books only need copying to the import folder
        print(f"\nFound {len(epub_files)} epub file(s) from the most recent download.")
        print("Moving resulting files to calibre-web import folder...\n")
        copy_epubs_for_import(epub_files)
        print(f"Copied {len(epub_files)} epub file(s) to calibre-web import folder.")

    t_end = time.time()
    running_time = t_end - t_start

    print(f"Processing of new files completed in {running_time:.2f} seconds.\n\n")
    empty_to_process_folder()
    sys.exit(1)

def convert_books(files_to_convert, import_format: str) -> float:
    """Uses the following terminal command to convert the books provided using the calibre converter tool:\n\n--- ebook-convert myfile.input_format myfile.output_format\n\nAnd then saves the resulting epubs to the calibre-web import folder."""
    t_convert_total_start = time.time()
    for file_to_convert in files_to_convert:
        t_convert_book_start = time.time()
        book_title = file_to_convert.split('/')[-1]
        print(f"START_CON: Converting {book_title}...\n")
        filename = file_to_convert.split('/')[-1]
        os.system(f'ebook-convert "{file_to_convert}" "{import_folder}{(filename.split(f".{import_format}"))[0]}.epub"')
        t_convert_book_end = time.time()
        time_book_conversion = t_convert_book_end - t_convert_book_start
        print(f"\nEND_CON: Conversion of {book_title} complete in {time_book_conversion:.2f} seconds.\n")

    t_convert_total_end = time.time()
    time_total_conversion = t_convert_total_end - t_convert_total_start

    return time_total_conversion


def select_books_for_conversion(new_files: list[str]) -> tuple[list[str], str]:
    """When no epubs are detected in the download, this function will go through the list of new files and check for the format the are in that has the highest chance of sucsessful conversion according to the input format hierarchy list provided by calibre"""
    files_to_convert = []
    import_format = ''
    for format in hierarchy_of_succsess:
        file_search = [f for f in new_files if f.endswith(f'.{format}')]
        if len(file_search) > 0:
            files_to_convert += file_search
            import_format = format
            break

    return files_to_convert, import_format


def copy_epubs_for_import(epub_files) -> None:
    """Moves the epubs from the download folder to the calibre-web import folder"""
    for file in epub_files:
        print(f"Moving {file}...")
        filename = file.split('/')[-1]
        os.system(f'cp "{file}" "{import_folder}{filename}"')

def empty_to_process_folder() -> None:
    """Empties the ingest folder"""
    os.system(f"rm -r {ingest_folder}*")


if __name__ == "__main__":
    main()