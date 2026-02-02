# **Version 4.0.0** - Smart Automatic Duplicate Handling & Resolution 🔍, a Gorgeous & Powerful New Stats Centre 📊, Magic Shelves ✨, Robust OAuth, Auto-Send & Auto-Fetch ✈️ Huge Performance Uplifts and more!

### MAJOR UPDATE! 🚨

### TLDR: CWA now has a new, robust OAuth system, a new smart Duplicate Detection & Auto-Resolution system, a brand-new & very powerful Stats Dashboard, Auto-Send to eReader functionality as well as Automatic Metadata Fetching, a new and Improved Automatic EPUB Fixer service, a new Network Share mode for increased compatibility & reliability with NFS & SMB shares, a major performance overhaul making the whole service more lightweight than ever and so much more! Check out the full changelog on GitHub for more details!

[Link to GitHub Project Page](https://github.com/crocodilestick/Calibre-Web-Automated)

> "I'm honestly so excited to finally share this update with you all. We've tackled the duplicate book problem once and for all, built a sick stats system that actually shows you how your library is being used, added dynamic/Magic Shelves, and a powerful & robust new OAuth system. The amount of new features and fixes in this release is incredible. This is the biggest, most community-driven update CWA has ever had and I'm very grateful to everyone that helped work on it." - **CrocodileStick**

### If you enjoy the project and want to support the coffee fund for v5.0, you can do so here:

[![ko-fi](https://ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/crocodilestick)

## Release V3.1.0 Changelog

### 🚀 Major Features

## Here is the highlight reel:

* **🔍 Smart Duplicate Detection & Resolution:** A completely rebuilt hybrid SQL/Python engine. It detects 95% of duplicates other systems miss (ignoring articles like "The", fuzzy matching, etc.). Includes **Auto-Resolution** to merge books automatically and **Scheduled Scans**.
![](https://github.com/crocodilestick/Calibre-Web-Automated/blob/main/README_images/duplicate-detection-system.gif?raw=true)

* **✨ Magic Shelves:** Dynamic, rules-based collections. Create shelves based on tags, ratings, series, or publication dates (e.g., "Rated 4+ stars", "Published in 2024"). **Bonus:** These sync directly to Kobo devices!
![](https://github.com/crocodilestick/Calibre-Web-Automated/blob/main/README_images/magic-shelf-showcase.gif?raw=true)

* **📊 Deep Stats Centre:** A brand new dashboard. Track **User Activity** (reading velocity, top users), **Library Stats** (format distribution, language), and **Peak Usage Hours**.
![](https://github.com/crocodilestick/Calibre-Web-Automated/blob/main/README_images/cwa-stats-showcse.gif?raw=true)

* **📧 Auto-Send to eReader:** Set it and forget it. New books can be automatically emailed to your Kindle/Kobo/eReader immediately upon ingest, with smart delays to allow for metadata fetching first.
* **🛡️ Robust OAuth Rewrite:** Completely rewritten authentication. Now supports **LDAP, Reverse Proxy (Authelia/Authentik), and OIDC** natively with auto-user creation. No more redirect loops.
* **✅ EPUB Fixer 2.0 (No more E999 Errors):** Specifically targets Amazon's strict rejection criteria. Automatically fixes language tags, XML declarations, and broken CSS so your Send-to-Kindle works reliably.
* **🏷️ Auto-Metadata Fetching:** CWA can now automatically fetch metadata (Google Books, Kobo, Hardcover, etc.) during ingest or before sending to a device.

### ⚡ Performance & Quality of Life

* **Performance Overhaul:** Search is drastically faster, and we’ve moved to WebP thumbnails which reduces page weight by 97%. Large libraries (50k+ books) load instantly now.
* **Network Share Mode:** Running on a NAS/Unraid? We added a specific mode to handle NFS/SMB locking issues to prevent database corruption.
* **Better Kobo Integration:** Improved sync reliability, annotations, and a new "Featured Products" endpoint.
* **Hardcover.app ID Fetch:** Automatically links your library to Hardcover for better tracking.
* **Enhanced Manual Sending:** Want to send a book to a friend? You can now type in any email address on the fly to send a book without creating a user account.

### 🔗 Links
* **Full Change Log:** [Link to your GitHub Release]
* **Docker Hub:** [Link to DockerHub](https://hub.docker.com/r/crocodilestick/calibre-web-automated)
* **Repo:** [Link to GitHub Project Page](https://github.com/crocodilestick/Calibre-Web-Automated)

### Upcoming changes 🔮

Major changes are still coming to CWA including:
- A brand new Svelte based Frontend. The days of the current Bootstrap UI are numbers and migrating to Svelte ensures that the new UI will still be easy to edit and add to for as many contributors as possible due to it's very familiar syntax to traditional sites and can be compiled with Capacitor for native mobile apps which is very exiting
- A new web reader, epub.js is a little dated now and there are now much better alternatives
- A much more robust & powerful progress syncing system that will be able to have CWA act as a single source of truth for reading progress no matter what device you read from
- Full Text Search functionality
- 🐁 is coming very soon, the integration just had to be as sensible & respectful to the 🐁 and it's servers as possible and a good balance has now been reached

## A massive thank you to the 60+ contributors who helped test, translate, and code this release.

### TLDR: CWA now has a new, robust OAuth system, a new smart Duplicate Detection & Auto-Resolution system, a brand-new & very powerful Stats Dashboard, Auto-Send to eReader functionality as well as Automatic Metadata Fetching, a new and Improved Automatic EPUB Fixer service, a new Network Share mode for increased compatibility & reliability with NFS & SMB shares, a major performance overhaul making the whole service more lightweight than ever and so much more! Check out the full changelog on GitHub for more details!

### If you enjoy the project and want to support the coffee fund for v5.0, you can do so here:

[![ko-fi](https://ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/crocodilestick)