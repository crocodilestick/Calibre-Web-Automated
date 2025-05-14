### Summary of Changes:

1. **Script Integration in `layout.html`**
   Added a script to `layout.html` (located at `root/app/calibre-web/cps/`) that:
   - Retrieves the user's profile name from the existing HTML.
   - Replaces the default image in the dark theme with a custom user profile image.
   
   **Current Behavior:**
   The script requires images to be converted to base64 to fit the current HTML structure. However, I am working on implementing a user-friendly process for this in the UX.Ideally, users will have a separate field to upload an image, which will then be automatically converted to base64.
   
   For now, both usernames and base64 images are stored in a JSON file located beside the script at `root/app/calibre-web/cps/static/`. This feature is currently supported only in the "Caliblur! Dark Theme."

2. **Admin Profile Picture Management Page**
   A new page has been added for admins to manage profile pictures. The page is accessible via a button in the admin panel (`admin.html`), and the corresponding HTML page is `profile_pictures.html` located at `root/app/calibre-web/cps/`.
   
   **Key Features:**
   - The page checks for admin status before allowing access.
   - Two text fields are provided to input the username and base64 image string, which will be stored in the JSON file.
   - For now, only admins have access to this feature to reduce the chances of simultaneous writes to the JSON file.
   - In the future, I might consider moving to a database for better scalability.

3. **Permissions for JSON File**
   Permissions for the JSON file were set in the Dockerfile, which is located at the very bottom.

4. **New Admin Button**
   I added a button to the admin panel to access the profile picture management page. Look for the following line in `admin.html`:
   <a class="btn btn-default" id="admin_profile_pictures" href="{{ url_for('web.profile_pictures') }}">{{ _('Manage Profile Pictures') }}</a>

5. **Using the Tool**
   Admins can click the button in the admin panel to access the new interface. From there:
   - They can add a username and base64 image string.
   - If an image for a user already exists, adding the same username and new base64 string will overwrite the old data.
   - After applying the image, users may need to click the refresh button to see the updated profile picture.

