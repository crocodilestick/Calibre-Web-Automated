# Development Notes

## Syntax Fixes
- **File:** `hardcover.py` (lines 145 and 147)  
  Changed `is` to `==` when comparing literal values.  
  The original code was using `is` for value comparison, which is meant for identity checks.  
  Using `==` ensures proper value equality checks and avoids `SyntaxWarning` messages in logs.

## Ingest Filter Fixes
- **File:** `ingest_processor.py`  
  Fixed logic for ignoring unwanted files with extensions like `.crdownload`, `.download`, and `.part`.  
  See section: `# Make sure it's a list, if it's a string convert it to a single-item list`.

## Line Ending Normalization
- Added a `.gitattributes` file to enforce LF line endings for shell scripts and related files.  
  This helps prevent inconsistent line endings across environments during versioning, pulls, and merges.

## Directory Handling
- **File:** `metadata-change-detector/run`  
  Added logic to create the `$WATCH_FOLDER` directory if it doesn't exist.  
  This prevents the script from entering a continuous loop due to a missing folder.

## File Name Truncation
- **File:** `ingest_processor.py`  
  Implemented filename truncation to prevent issues with excessively long file names.  
  This resolves errors when processing files that exceed filesystem limits or break internal logic.
  Improve file renaming logic in ingest_processor.py
  Avoids concatenating the original filename with the path and extension in a way that could exceed filesystem limits.
  Resolves edge cases where the filename could still be too long even after truncation.