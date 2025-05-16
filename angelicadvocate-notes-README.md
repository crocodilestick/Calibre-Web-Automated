## Update Summary

- Removed previous changes to the Dockerfile.
- Added a check in `/cwa-init/run` to verify if the JSON file exists, and create it if it doesn't.
- Moved the JSON file into the `config` directory to avoid extra volume binds.
- Began integrating the **Caliblur** theme into the profile pictures page for a more cohesive UI across the application.
- Fixed several bugs introduced in the initial draft of `profile_pictures.html`, including issues with page scrolling.
