import json
import os
import shutil
import sqlite3
import sys


def main():
    auto_lib = AutoLibrary()
    auto_lib.check_for_app_db()
    if auto_lib.check_for_existing_library():
        auto_lib.set_library_location()
    else: # No existing library found
        auto_lib.make_new_library()
        auto_lib.set_library_location()

    print(f"[auto-library] Library location successfully set to: {auto_lib.lib_path}")
    sys.exit(0)


class AutoLibrary:
    def __init__(self):
        self.config_dir = "/config"
        self.library_dir = "/calibre-library"
        self.dirs_path = "/app/calibre-web-automated/dirs.json"
        self.app_db = "/config/app.db"
        
        self.empty_appdb = "/app/calibre-web-automated/empty_library/app.db"
        self.empty_metadb = "/app/calibre-web-automated/empty_library/metadata.db"
        
        self.metadb_path = None
        self.lib_path = None

    @property #getter
    def metadb_path(self):
        return self._metadb_path

    @metadb_path.setter
    def metadb_path(self, path):
        if path is None:
            self._metadb_path = None
            self.lib_path = None
        else:
            self._metadb_path = path
            self.lib_path = os.path.dirname(path)

    # Checks config_dir for an exisiting app.db, if one doesn't already exist it copies an empty one from /app/calibre-web-automated/empty_library/app.db and sets the permissiosn
    def check_for_app_db(self):
        files_in_config = [os.path.join(dirpath,f) for (dirpath, dirnames, filenames) in os.walk(self.config_dir) for f in filenames]
        db_files = [f for f in files_in_config if "app.db" in f]
        if len(db_files) == 0:
            print(f"[auto-library] No app.db found in {self.config_dir}, copying from /app/calibre-web-automated/empty_library/app.db")
            shutil.copyfile(self.empty_appdb, f"{self.config_dir}/app.db")
            os.system(f"chown -R abc:abc {self.config_dir}")
            print(f"[auto-library] app.db successfully copied to {self.config_dir}")
        else:
            return

    # Check for a metadata.db file in the given library dir and returns False if one doesn't exist
    # and True if one does exist, while also updating metadb_path to the path of the found metadata.db file
    # In the case of multiple metadata.db files, the user is notified and the one with the largest filesize is chosen
    def check_for_existing_library(self) -> bool: 
        files_in_library = [os.path.join(dirpath,f) for (dirpath, dirnames, filenames) in os.walk(self.library_dir) for f in filenames]
        db_files = [f for f in files_in_library if "metadata.db" in f]
        if len(db_files) == 1:
            self.metadb_path = db_files[0]
            print(f"[auto-library]: Existing library found at {self.lib_path}, mounting now...")
            return True
        elif len(db_files) > 1:
            print("[auto-library]: Multiple metadata.db files found in library directory:\n")
            for db in db_files:
                print(f"    - {db} | Size: {os.path.getsize(db)}")
            db_sizes = [os.path.getsize(f) for f in db_files]
            index_of_biggest_db = max(range(len(db_sizes)), key=db_sizes.__getitem__)
            self.metadb_path = db_files[index_of_biggest_db]
            print(f"\n[auto-library]: Automatically mounting the largest database using the following db file - {db_files[index_of_biggest_db]} ...")
            print("\n[auto-library]: If this is unwanted, please ensure only 1 metadata.db file / only your desired Calibre Database exists in '/calibre-library', then restart the container")
            return True
        else:
            return False

    # Sets the library's location in both dirs.json and the CW db
    def set_library_location(self):
        if self.metadb_path is not None and os.path.exists(self.metadb_path):
            self.update_dirs_json()
            self.update_calibre_web_db()
            return
        else:
            print("[auto-library]: ERROR: metadata.db found but not mounted")
            sys.exit(1)

    # Uses sql to update CW's app.db with the correct library location (config_calibre_dir in the settings table)
    def update_calibre_web_db(self):
        if os.path.exists(self.metadb_path):
            try:
                print("[auto-library]: Updating Settings Database with library location...")
                conn = sqlite3.connect(self.app_db)
                cur = conn.cursor()
                cur.execute("UPDATE settings SET config_calibre_dir = ?;", (self.lib_path,))
                conn.commit()
                return
            except Exception as e:
                print("[auto-library]: ERROR: Could not update Calibre Web Database")
                print(e)
                sys.exit(1)
        else:
            print(f"[auto-library]: ERROR: app.db in {self.app_db} not found")
            sys.exit(1)

    # Update the dirs.json file with the new library location (lib_path))
    def update_dirs_json(self):
        """Updates the location of the calibre library stored in dirs.json with the found library"""
        try:
            print("[auto-library] Updating dirs.json with new library location...")
            with open(self.dirs_path) as f:
                dirs = json.load(f)
            dirs["calibre_library_dir"] = self.lib_path
            with open(self.dirs_path, 'w') as f:
                json.dump(dirs, f)
            return
        except Exception as e:
            print("[auto-library]: ERROR: Could not update dirs.json")
            print(e)
            sys.exit(1)

    # Uses the empty metadata.db in /app/calibre-web-automated to create a new library
    def make_new_library(self):
        print("[auto-library]: No existing library found. Creating new library...")
        shutil.copyfile(self.empty_metadb, f"{self.library_dir}/metadata.db")
        os.system(f"chown -R abc:abc {self.library_dir}")
        self.metadb_path = self.library_dir
        return
        

if __name__ == '__main__':
    main()