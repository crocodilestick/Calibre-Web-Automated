# Calibre-Web Automated _(formerly Calibre-Web Automator)_

![Calibre-Web Automated](README_images/CWA-banner.png "Calibre-Web Automated")

## Making Calibre-Web your _dream_, all-in-one self-hosted digital library solution.

![Docker Pulls](https://img.shields.io/docker/pulls/crocodilestick/calibre-web-automated)

## _Quick Access_

- [Features](https://github.com/crocodilestick/Calibre-Web-Automated?tab=readme-ov-file#what-does-it-do-) 🪄
- [Releases](https://github.com/crocodilestick/Calibre-Web-Automated/releases) 🆕
- [Roadmap](https://github.com/crocodilestick/Calibre-Web-Automated?tab=readme-ov-file#under-active-development-%EF%B8%8F) 🛣️
- [How to Install](https://github.com/crocodilestick/Calibre-Web-Automated?tab=readme-ov-file#how-to-install-): 📖
  - [Docker-Compose](https://github.com/crocodilestick/Calibre-Web-Automated?tab=readme-ov-file#method-1-using-docker-compose--recommended) 🐋⭐(Recommended)
  - [Quick Install](https://github.com/crocodilestick/Calibre-Web-Automated/tree/main?tab=readme-ov-file#quick-install-) 🚀
- [Usage](https://github.com/crocodilestick/Calibre-Web-Automated?tab=readme-ov-file#method-2-using-the-script-install-method-with-clean-calibre-web-base-image--not-recommended) 🔧
- [Further Development](https://github.com/crocodilestick/Calibre-Web-Automated?tab=readme-ov-file#method-2-using-the-script-install-method-with-clean-calibre-web-base-image--not-recommended) 🏗️
- [Support / Buy me a Coffee](https://ko-fi.com/crocodilestick) ☕

## Why does it exist? 🔓

Calibre, while a fantastic tool for its age, has several problems when containerised, including its reliance on a KasmVNC server instance for the UI, which is near impossible to use on mobile and is relatively resource-heavy if you're running a small, lower power server like I am.

For many, Calibre-Web has really swooped in to save the day, offering an alternative to a containerised Calibre instance that's quick, easy to set up, resource-light and with a much more modern UI to boot.

However, when compared to full-fat Calibre, it unfortunately lacks a few core features leading many to run both services in parallel, each serving to fill in where the other lacks, resulting in an often clunky, imperfect solution.

# 🚨 **HUGE NEW UPDATE** 🚨 - Version 2.0.0 - 28.08.2024

![GitHub Release](https://img.shields.io/github/v/release/crocodilestick/calibre-web-automated)
![GitHub commits since latest release](https://img.shields.io/github/commits-since/crocodilestick/calibre-web-automated/latest)

### 🚨 Please **Update to the latest DockerHub image ASAP** to avoid stability & import/ ingest issues that have been corrected from previous versions

View [The changelog for more info](https://github.com/crocodilestick/Calibre-Web-Automated/releases/tag/V2.0.0). New features have been released

## What Does it do? 🎯

After discovering that using the DOCKER_MODS universal-calibre environment variable, you could gain access to Calibre's fantastic eBook conversion tools, both in the Web UI and in the container's CLI, I set about designing a similar solution that could really make the most of all of the tools available to try and fill in the gaps in functionality I was facing with Calibre-Web so that I could finally get rid of my bulky Calibre instance for good.

### **_Features:_**

- **Automatic Imports** - of `.epub` files into your Calibre-Web library ✨

- **Automatic Conversion** 🔃 - of newly downloaded books in 28 other formats into `.epub` **for optimal compatibility** with the widest number of eReaders, library homogeneity, and seamless functionality with Calibre-Web's excellent **Send-to-Kindle** Function.

- A **Weighted Conversion Algorithm:** ⚖️
  - Using the information provided in the Calibre eBook-converter documentation on which formats convert best into epubs, CWA is able to determine from downloads containing multiple eBook formats, which format will convert most optimally, ignoring the other formats to ensure the **best possible quality** and no **duplicate imports**
- **28 Supported file types for conversion:** 🤯
  - _.azw, .azw3, .azw4, .mobi, .cbz, .cbr, .cb7, .cbc, .chm, .djvu, .docx, .epub, .fb2, .fbz, .html, .htmlz, .lit, .lrf, .odt, .pdf, .prc, .pdb, .pml, .rb, .rtf, .snb, .tcr, .txtz_

![Cover Enforcement CWA](README_images/cwa-enforcer-diagram.png "CWA 1.2.0 Cover Enforcement Diagram")

- **Automatic Enforcement of Changes made to Covers & Metadata through the Calibre-Web UI!** 👀📔
  - In stock Calibre-Web, any changes made to a book's **Cover and/or Metadata** are only applied to how the book appears in the Calibre-Web UI, changing nothing in the ebook's files like you would expect
  - This results in a frustrating situation for many CW users who utilise CW's Send-To-Kindle function, and are disappointed to find that the High-Quality Covers they picked out and carefully chosen Metadata they sourced are completely absent on all their other devices! UGH!
  - CWA's **Automatic Cover & Metadata Enforcement Feature** makes it so that **WHATEVER** you changes you make to **YOUR** books, **_are made to the books themselves_**, as well as in the Web UI, **making what you see, what you get.**
- **One Step Full Library Conversion** 🔂 - Any format -> `.epub`

  - Calibre-Web Automated has always been designed with `.epub` libraries in mind due to many factors, chief among which being the fact they are **Compatible with the Widest Range of Devices**, **Ubiquitous** as well as being **Easy to Manage and Work with**
  - Previously this meant that anyone with `non-epub` ebooks in their existing Calibre Libraries was unable to take advantage of all of `Calibre-Web Automated`'s features reliably
  - So new to Version 1.2.0 is the ability for those users to quickly and easily convert their existing eBook Libraries, no matter the size, to `.epub Version 3` format using a one-step CLI Command from within the CWA Container
  - This utility gives the user the option to either keep a copy of the original of all converted files in `/config/original-library` or to trust the process and have CWA simply convert and replace those files (not recommended)
  - Full usage details can be found [here](#the-convert-library-tool)

- **Simple CLI Tools** for manual fixes, conversions, enforcements, history viewing ect. 👨‍💻

  - Built-in command-line tools now also exist for:
    - Viewing the Edit History of your Library files _(detailed above)_
    - Listing all of the books currently in your Library with their current Book IDs
    - **Manually enforcing the covers & metadata for ALL BOOKS** in your library using the `cover-enforcer -all` command from within the container **(RECOMMENDED WITH FIRST TIME USE)**
    - Manually Enforcing the Covers & Metadata for any individual books by using the following command
    - `cover-enforcer --dir <path-to-folder-containing-the-books-epub-here>`
  - Full usage and documentation for all new CLI Commands can be found [here](#the-cover-enforcer-cli-tool)
    ![CWA Database](README_images/cwa-db-diagram.png "CWA 1.2.0 Cover Database Diagram")

- **Change Tracking Database** 📊 - In combination with the **New Cover & Metadata Enforcement Features**, a database now exists to keep track of any and all enforcements, both for peace of mind and to make the checking of any bugs or weird behaviour easier, but also to make the data available for statistical analysis or whatever else someone might want to use the data for
  - Full documentation can be found below [here](#checking-the-cover-enforcement-logs)

- ### NEW FEATURE - Library Auto-Detect 📚🕵️
  - Made to MASSIVELY simplify the setup process for both new and existing users alike
  - **New Users without existing Libraries:** 🆕
    - New users without existing Calibre Libraries no longer need to copy and paste `metadata.db` files and point to their location in the Web UI, CWA will now automatically detect the lack of Library in your given bind and automatically create a new one for you! It will even automatically register it with the Web UI so you can really hit the ground running
  - **New or Existing Users with Existing Libraries:**
    - Simply bind a directory containing your Calibre Library (search is done recursively so it doesn't matter how deep in the directory it is) and CWA will now automatically find it and mount it to the Web UI
    - Should you bind a directory with more than 1 Calibre Library in it, CWA will intelligently compare the disk sizes of all discovered libraries and mount the largest one
      - _CWA supports only one library per instance though support for multiple libraries is being investigated for future releases_
      - _In the meantime, users with multiple libraries who don't want to consolidate them are advised to run multiple, parallel instances_
- ### NEW FEATURE - Easy Dark/ Light Mode Switching ☀️🌙
- **Switch between Light & Dark Modes in just one click from anywhere in the Web UI!**
  - Simply click/tap the 🕶️ icon on the  Web UI's navbar and switch between themes at your leisure
- ### NEW FEATURE - Internal Update Notification System 🛎️
  - Users will now be automatically notified of the availability of new updates from within the Web UI
    - Automatically triggered by a difference between the version number of the most recent GitHub release and the version installed
    - Set to only show once per calendar day until updated as to not be annoying
      - _Visible to Admin users only_
- ### NEW FEATURE - Manual Library Refresh ♻️
  - Ever had books get stuck in the ingest folder after an unexpected power-cut ect.? Well say goodbye to having to manually copy the books to be ingested back in and out of the ingest folder, simply press the `Refresh Library` button on the navbar of the Web UI and anything still sitting in the ingest folder will be automatically ingested!
- ### NEW FEATURE - Batch Editing & Deletion! 🗂️🗄️
  - Say goodbye to clicking that edit button again, and again, and again just to remove or edit a single series!
  - To use, simply navigate to the `Books List`page on the left hand side of the Web UI, select the books you wish to edit/ delete and use the buttons either above the table or within the headers to do whatever you need!
  - _Courtesy of [@jmarmstrong1207](https://github.com/jmarmstrong1207)_

![Calibre-Web Automated](README_images/cwa-bulk-editting-diagram.png "Calibre-Web Automated Bulk Editing & Bulk Deletion")


# UNDER ACTIVE DEVELOPMENT ⚠️

- Please be aware that while CWA currently works for most people, it is still under active development and that bugs and unexpected behaviours can occur while we work and the code base matures
- I want to say a big thanks 🙏 to the members of this community that have taken the time to participate in the testing and development of this project, especially to [@jmarmstrong1207](https://github.com/jmarmstrong1207) who has been working tirelessly on improving the project since the release of Version 1.2.0
  - In recognition of this, [@jmarmstrong1207](https://github.com/jmarmstrong1207) has now been promoted to a co-contributor here on the project, so feel free to also contact him with any issues, suggestions, ideas ect.
  - For any others that wish to contribute to this project in some way, please reach out on our Discord Server and see how you can best get involved:\
    \
    [![](https://dcbadge.limes.pink/api/server/https://discord.gg/EjgSeek94R)](https://discord.gg/EjgSeek94R)

### Coming in Version 2.0.1 - Currently in Testing Phase 🧪

- Integrating some of the new **Command-Line Features into the Web UI**
  - Including Library Conversion, the Display of Conversion History and checking of the CWA Monitoring Services

### Coming Soon - Currently Under Active Development 🏗️

- **Robo**tic **Read**ing 🤖📖
  - **Bio**nic **read**ing **wa**s **initi**ally **rele**ased **i**n **20**22 **a**s **a** **met**hod **o**f **forma**tting **te**xt **t**o **ma**ke **i**t **eas**ier **fo**r **peo**ple **wi**th **AD**HD **an**d **oth**er **concent**ration **&** **read**ing **iss**ues **t**o **re**ad **fast**er, **eas**ier **an**d **t**o **ret**ain **mo**re **o**f **wh**at **they**'ve **rea**d.
  - **W**e **we**re **insp**ired **b**y **th**e **conc**ept **an**d **ha**ve **crea**ted **a** **eP**ub **conve**rsion **algor**ithm **insp**ired **b**y **th**e **orig**inal **Bio**nic **Read**ing **fo**r **tho**se **wh**o **li**ke **i**t **o**r **wh**o **ma**y **wa**nt **t**o **gi**ve **i**t **a** **g**o

### Additional Features on our Roadmap 🛣️🌱

- Release CWA also as a Docker Mod
- Support for `arm64` architectures
- Adding tracking of ebook imports & deletions to the `cwa.db`
- Improved metadata handling and conversion for comics & manga
- Please suggest any ideas or wishes you might have! we're open to anything!

### IMPORTANT NOTE: ⚡ Current users of Calibre-Web Automated version 1.2.2 or below should update using the latest DockerHub image to ensure stability and compatibility with future updates

# How To Install 📖

## Quick Install 🚀

1. Download the Docker Compose template file using the command below:

```
curl -OL https://raw.githubusercontent.com/crocodilestick/calibre-web-automated/main/docker-compose.yml
```

2. Navigate to where you downloaded the Compose file using `cd` and run:

```
docker compose up -d
```

And that's you off to the races! 🥳 HOWEVER to avoid potential problems and ensure maximum functionality, we recommend carrying out these [Post-Install Tasks Here](#3-recommended-post-install-tasks).

---
## Using Docker Compose 🐋⭐(Recommended)

### 1. Setup the container using the Docker Compose template below: 🐋📜

```
---
services:
  calibre-web-automated:
    image: crocodilestick/calibre-web-automated:latest
    container_name: calibre-web-automated
    environment:
      - PUID=1000
      - PGID=100
      - TZ=UTC
      - DOCKER_MODS=lscr.io/linuxserver/mods:universal-calibre-v7.16.0
    volumes:
      - /path/to/config/folder:/config
      - /path/to/the/folder/you/want/to/use/for/book/ingest:/cwa-book-ingest
      - /path/to/your/calibre/library:/calibre-library
      #- /path/to/where/you/keep/your/books:/books #Optional
      #- /path/to/your/gmail/credentials.json:/app/calibre-web/gmail.json #Optional
    ports:
      - 8084:8083 # Change the first number to change the port you want to access the Web UI, not the second
    restart: unless-stopped
    
```

- **Explanation of the Container Bindings:**
  - Make sure all 3 of the main bindings are separate directories, errors can occur when binds are made within other binds
  - `/config` - Can be any empty folder, used to store logs and other miscellaneous files that keep CWA running
  - `/cwa-book-ingest` - **ATTENTION** ⚠️ - All files within this folder will be **DELETED** after being processed. This folder should only be used to dump new books into for import and automatic conversion
  - `/calibre-library` - This should be bound to your Calibre library folder where the `metadata.db` file resides within and will be mounted automatically. If there are multiple libraries, it will find and mount the largest one.
    - If you don't have an **existing** Calibre Database, you can use the Docker Template folder for a quick install mentioned above.
  - `/books` _(Optional)_ - This is purely optional, I personally bind /books to where I store my downloaded books so that they accessible from within the container but CWA doesn't require this
  - `/gmail.json` _(Optional)_ - This is used to setup Calibre-Web and/or CWA with your gmail account for sending books via email. Follow the guide [here](https://github.com/janeczku/calibre-web/wiki/Setup-Mailserver#gmail) if this is something you're interested in but be warned it can be a very fiddly process, I would personally recommend a simple SMTP Server

### And just like that, Calibre-Web Automated should be up and running!

<!-- - By default, `/cwa-book-ingest` is the ingest folder bound to the ingest folder you entered in the Docker Compose template however should you want to change any of the default directories, use the `cwa-change-dirs` command from within the container to edit the default paths -->

### 2. **_Recommended Post-Install Tasks:_**

#### _Calibre-Web Quick Start Guide_

1. Open your browser and navigate to http://localhost:8084 or http://localhost:8084/opds for the OPDS catalog
2. Log in with the default admin credentials (_below_)
<!-- 3. If you don't have an existing Calibre database, you can use the `metadata.db` file above
   - This is a blank Calibre-Database you can use to perform the Initial Setup with
   - Place the `metadata.db` file in the the folder you bound to `/calibre-main` in your Docker Compose -->
<!-- 4. During the Web UI's Initial Setup screen, Set Location of Calibre database to the path of the folder to `/calibre-main` and click "Save"
5. Optionally, use Google Drive to host your Calibre library by following the Google Drive integration guide -->
3. Configure your Calibre-Web instance via the admin page, referring to the Basic Configuration and UI Configuration guides
4. Add books by having them placed in the folder you bound to `cwa-book-ingest` in your Docker Compose

**⚠️ ATTENTION ⚠️**

- _Downloading files directly into `/cwa-book-ingest` is not supported. It can cause duplicate imports and potentially a corrupt database. It is recommended to first download the books completely, then transfer them to `/cwa-book-ingest` to avoid any issues_

#### Default Admin Login:

> **Username:** admin\
> **Password:** admin123

#### Configuring CWA ⚙️

- If your Calibre Library contains any ebooks not in the `.epub` format, from within the container run the `convert-library` command.
  - Calibre-Web Automated's extra features only work with epubs and so **failure to complete this step could result in unforeseen errors and general unreliability**
  - Full usage can be found below in the Usage Section however the following command will automatically convert any non-epubs to epubs and store the original files in `/config/original-library`:

```
convert-library --keep
```

- Drop a book into your ingest folder and check everything is working correctly!

# Usage 🔧

## Adding Books to Your Library

- Simply move your newly downloaded or existing eBook files to the ingest folder which is `/cwa-book-ingest` by default or whatever you designated during setup if using the Script Install method. Anything you place in that folder will be automatically analysed, converted if necessary and then imported into your Calibre-Web library.
  - **⚠️ ATTENTION ⚠️**
    - _Downloading files directly into `/cwa-book-ingest` is not supported. It can cause duplicate imports and potentially a corrupt database. It is recommended to first download the books completely, then transfer them to `/cwa-book-ingest` to avoid any issues_

## The Cover-Enforcer CLI Tool

```
usage: cover-enforcer [-h] [--log LOG] [--dir DIR] [-all] [-list] [-history] [-paths] [-v]

Upon receiving a log, valid directory or an "-all" flag, this script will enforce the covers and metadata of the corresponding books, making sure that each are correctly stored in
both the epubs themselves and the user's Calibre Library. Additionally, if an epub happens to be in EPUB 2 format, it will also be automatically upgraded to EPUB 3.

options:
  -h, --help     show this help message and exit
  --log LOG      Will enforce the covers and metadata of the books in the given log file.
  --dir DIR      Will enforce the covers and metadata of the books in the given directory.
  -all           Will enforce covers & metadata for ALL books currently in your calibre-library-dir
  -list, -l      List all books in your calibre-library-dir
  -history       Display a history of all enforcements ever carried out on your machine (not yet implemented)
  -paths, -p     Use with '-history' flag to display stored paths of all epubs in enforcement database
  -v, --verbose  Use with history to display entire enforcement history instead of only the most recent 10 entries
```

![CWA Cover-Enforcer History Usage](README_images/cwa-db-diagram.png)

## The Convert-Library Tool

```
usage: convert-library [-h] [--replace] [--keep] [-setup]

Made for the purpose of converting ebooks in a calibre library not in epub format, to epub format

options:
  -h, --help     show this help message and exit
  --replace, -r  Replaces the old library with the new one
  --keep, -k     Creates a new epub library with the old one but stores the old files in /config/original-library
  -setup         Indicates to the function whether or not it's being ran from the setup script or manually (DO NOT USE MANUALLY)
```

<!-- ## Changing the Default Directories

- If you ever need to change the locations of your **ingest**, **import** and/ or **calibre-library** folders, use the `cwa-change-dirs` command from anywhere within the container's terminal to open the json file where the paths are saved and change them as required. -->

## Checking the Monitoring Services are working correctly

- Simply run the following command from within the container: `cwa-check`
- If all 3 services come back as green and running they are working properly, otherwise there may be problems with your configuration/install

# Further Development 🏗️

- Calibre-Web Automated (_formerly Calibre-Web Automator_) was made to be everything I need for my reading workflow, I personally love the new features and hope you do to!
- While it already does everything I need, building it has been really fun and it's great to see so many other people get so much use out of it!
- And so on top of continuing to perform maintenance and bugfixes, we are always open to suggestions and ideas from the community so if there's something you'd like to see, don't be afraid to ask!
- To do so you can either open an Issue here on the project page or get in touch with us on our Discord Server [here](https://discord.gg/EjgSeek94R)!
- We're always looking for new people to help out too so if that sounds like you, let us know!
