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

    sys.exit(1)

def path_check(path: str) -> bool:
    """Returns true if a given path exists and is a directory and False if not"""
    return os.path.exists(f"{path}/")

def path_correct(path: str) -> str:
    """Checks that the path is in the correct format and corrects it if not"""
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
        print("\n-- Welcome to the Calibre-Web Automater setup script! --\n")
    
        print("Please confirm the following directories are correct:\n")
        print(f"{'Ingest folder:':<30}{dirs['ingest_folder']}")
        print(f"{'Import folder:':<30}{dirs['import_folder']}")
        print(f"{'Calibre Library dir:':<30}{dirs['calibre_library_dir']}")
        confirmation = input("\nAre these directories correct? (y/n): ").strip().lower()
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
        print("\n-- Welcome to the Calibre-Web Automater setup script! --\n")
    
        print("\nCalibre-Web-Automater needs an ingest folder for new files that are to be processed (converted / imported).")
        print("This folder needs to be accessable from within the Calibre-Web container so make sure you add the appropriate binds to yopur docker compose file.\n")
        ingest_folder = path_correct(input("Please make such a folder and enter it's internal container path here (e.g. /books/to_process/): ").strip())
        if path_check(ingest_folder):
            return ingest_folder
        else:
            input("\nThe path you entered is not valid. Press Enter to try again.")
            continue

def get_import_dir() -> str:
    """Gets the import folder from the user"""
    while True:
        os.system('cls' if os.name == 'nt' else 'clear')
        print("\n--Welcome to the Calibre-Web Automater setup script! --\n")

        print("\nCalibre-Web-Automater also needs a folder for processed files to be temporarily stored within prior to their auto-import into Calibre-Web")
        print("This folder also needs to be accessable from within the Calibre-Web container so make sure you add the appropriate binds to yopur docker compose file.\n")
        import_folder = path_correct(input("Make such a folder & enter it's internal container path here (e.g. /books/to_calibre/): ").strip())
        if path_check(import_folder):
            return import_folder
        else:
            input("\nThe path you entered is not valid. Press Enter to try again.")
            continue

def get_calibre_library_dir() -> str:
    """Gets the path to the calibre library dir from the user"""
    while True:
        os.system('cls' if os.name == 'nt' else 'clear')
        print("\n-- Welcome to the Calibre-Web Automater setup script! --\n")

        print("\nLastly, Calibre-Web-Automater needs the location of the calibre library folder in your container.")
        print('It is usually "/calibre-main/Calibre Library".\n')
        calibre_library_dir = path_correct(input("Please enter it's internal container path here: ").strip())
        if path_check(calibre_library_dir):
            return calibre_library_dir
        else:
            input("\nThe path you entered is not valid. Press Enter to try again.")
            continue

if __name__ == "__main__":
    main()