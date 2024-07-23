import json
import os
import sys


def main():
    while True:
        dirs = {}
        dirs |= {"ingest_folder":get_ingest_dir()}
        dirs |= {"import_folder":get_import_dir()}
        dirs |= {"calibre_library_dir":get_calibre_library_dir()}
        if confirm_dirs(dirs):
            break
        else:
            continue

    # Export the dirs to the dirs.json file
    with open("dirs.json", "w") as f:
        json.dump(dirs, f)
    dir_path = os.path.dirname(os.path.realpath(__file__))
    os.system(f"chown abc:users {dir_path}/dirs.json")
    os.system(f"mv {dir_path}/dirs.json /etc/calibre-web-automator/dirs.json")

    # Check for non epubs in given library
    result, non_epubs = check_library_for_non_epub_files(dirs['calibre_library_dir'])
    if not result:
        os.system("mkdir /config/original-library")
        os.system("chown -R abc:1000 /config/original-library")
        while True:
            os.system('cls' if os.name == 'nt' else 'clear')
            print("============ Welcome to the Calibre-Web Automater setup script! ============")

            print("\nCalibre-Web Automator requires all books in your Calibre Library to be in epub format.\n")
            print("The following files were found in formats that can be automatically converted to epubs:\n")
            for file in non_epubs:
                print(f"    - {file.split('/')[-1]}")
            print("\nPlease choose from the following options:\n")
            print("    1. Convert all non-epub books in the library to epubs, keeping copies of the original files")
            print("    2. Convert all non-epub books in the library to epubs, deleting the original files")
            print("    3. Abandon setup and exit\n")
            choice = input("Please enter your choice: ")
            match choice:
                case "1":
                    os.system("python3 /etc/calibre-web-automator/convert-library.py --keep -setup")
                    break
                case "2":
                    os.system("python3 /etc/calibre-web-automator/convert-library.py --replace -setup")
                    break
                case "3":
                    print("By exiting setup now, your install will still be functional for the epubs in your library, as well as any books you use the auto-import feature with.\n")
                    print("However, errors may occur and to manually convert your non-epub books to epubs, you will need to run the 'convert-library' command in the container's terminal with either the --keep or --replace flag.\n")
                    input("Press enter to exit...")
                    sys.exit(1)
                case _:
                    continue
    
    sys.exit(1)

def check_library_for_non_epub_files(library_dir):
    """Checks given library directory for non-epub files and warns the user"""
    supported_book_formats = ['azw', 'azw3', 'azw4', 'cbz', 'cbr', 'cb7', 'cbc', 'chm', 'djvu', 'docx', 'fb2', 'fbz', 'html', 'htmlz', 'lit', 'lrf', 'mobi', 'odt', 'pdf', 'prc', 'pdb', 'pml', 'rb', 'rtf', 'snb', 'tcr', 'txt', 'txtz']

    library_files = [os.path.join(dirpath,f) for (dirpath, dirnames, filenames) in os.walk(library_dir) for f in filenames]
    non_epubs = []
    for format in supported_book_formats:
        format_files = [f for f in library_files if f.endswith(f'.{format}')]
        if len(format_files) > 0:
            non_epubs = non_epubs + format_files

    if len(non_epubs) > 0:
        return False, non_epubs
    else:
        return True, None
            

def path_check(path: str) -> bool:
    """Returns true if a given path exists and is a directory after making sure it has the correct permissions, and False if not"""
    if os.path.exists(f"{path}/"):
        os.system(f'chown -R abc:1000 {path}/')    
    
    return os.path.exists(f"{path}/")

def path_correct(path: str) -> str:
    """Checks that the path is in the correct format and corrects it if not"""
    if not path:
        return path
    else:
        corrected_path = path
        if path[0] != "/":
            corrected_path = "/" + corrected_path
        if path[-1] == "/":
            corrected_path = corrected_path[:-1]
        return corrected_path

def confirm_dirs(dirs: dict[str, str]) -> bool:
    """Allows the user to confirm that the entrered dirs are correct"""
    while True:
        os.system('cls' if os.name == 'nt' else 'clear')
        print("============ Welcome to the Calibre-Web Automater setup script! ============")
    
        print("\nPlease confirm the following directories are correct:\n")
        print(f"{'Ingest folder:':<30}{dirs['ingest_folder']}")
        print(f"{'Import folder:':<30}{dirs['import_folder']}")
        print(f"{'Calibre Library dir:':<30}{dirs['calibre_library_dir']}")
        confirmation = input("\nAre these directories correct? (Y/n): ").strip().lower()
        match confirmation:
            case "y":
                input("\nDirectories sucsessfully confirmed. Press Enter to continue the Setup.")
                return True
            case "n":
                input("\nEntered paths deleted. Press Enter to try again.")
                return False
            case _:
                continue

def get_ingest_dir() -> str:
    """Gets the ingest folder from the user"""
    while True:
        os.system('cls' if os.name == 'nt' else 'clear')
        print("============ Welcome to the Calibre-Web Automater Setup Wizard! ============")
    
        print("\nCalibre-Web-Automater needs an Ingest Folder for New Files that are to be\nprocessed (converted / imported if they're already epubs).\n")
        print("This folder needs to be accessable from within the Calibre-Web container so\nmake sure you add the appropriate binds to your Docker-Compose file.\n")
        print("BY DEFAULT THE INGEST FOLDER IS /cwa-book-ingest, SIMPLY PRESS ENTER TO USE THE DEFAULT BIND\n")
        print("Please make such a folder exists & enter it's internal container path below\n(e.g. /books/cwa-ingest/):\n")
        ingest_folder = path_correct(input("    - Ingest Directory Path: ").strip())
        if not ingest_folder:
            return "/cwa-book-ingest"
        elif path_check(ingest_folder):
            return ingest_folder
        else:
            input("\nThe path you entered is not valid. Press Enter to try again.")
            continue

def get_import_dir() -> str:
    """Gets the import folder from the user"""
    import_folder = '/etc/calibre-web-automator/cwa-import'
    return import_folder
    # while True:
    #     os.system('cls' if os.name == 'nt' else 'clear')
    #     print("============ Welcome to the Calibre-Web Automater Setup Wizard! ============")

    #     print("\nCalibre-Web-Automater also needs a folder for processed files to be\ntemporarily stored within prior to their auto-import into Calibre-Web.\n")
    #     print("This folder also needs to be accessable from within the Calibre-Web container\nso make sure you add the appropriate binds to yopur docker compose file.\n")
    #     print("Make such a folder & enter it's internal container path below\n(e.g. /books/cwa-import/):\n")
    #     import_folder = path_correct(input("    - Import Directory Path: ").strip())
    #     if path_check(import_folder):
    #         return import_folder
    #     else:
    #         input("\nThe path you entered is not valid. Press Enter to try again.")
    #         continue

def get_calibre_library_dir() -> str:
    """Gets the path to the calibre library dir from the user"""
    while True:
        os.system('cls' if os.name == 'nt' else 'clear')
        print("============ Welcome to the Calibre-Web Automater Setup Wizard! ============")
        
        print("\nLastly, Calibre-Web-Automater needs the location of the Calibre Library\nfolder accessable from inside your container.\n")
        print('It is usually /calibre-main/Calibre Library/.\n')
        print("Please enter it's internal container path below (without quotes):\n")
        calibre_library_dir = path_correct(input("    - Calibre Library Path: ").strip())
        if path_check(calibre_library_dir):
            return calibre_library_dir
        else:
            input("\nThe path you entered is not valid. Press Enter to try again.")
            continue

if __name__ == "__main__":
    main()