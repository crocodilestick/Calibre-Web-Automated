# Calibre-Web Automated _(formerly Calibre-Web Automator)_

![Calibre-Web Automated](README_images/CWA-banner.png "Calibre-Web Automated")

## Making Calibre-Web your _dream_, all-in-one self-hosted digital library solution.

![Docker Pulls](https://img.shields.io/docker/pulls/crocodilestick/calibre-web-automated)

## _Quick Access_

- [Features](https://github.com/crocodilestick/Calibre-Web-Automator?tab=readme-ov-file#what-does-it-do-) 🪄
- [Releases](https://github.com/crocodilestick/Calibre-Web-Automator/releases) 🆕
- [Roadmap](https://github.com/crocodilestick/Calibre-Web-Automator?tab=readme-ov-file#under-active-development-%EF%B8%8F) 🛣️
- [How to Install](https://github.com/crocodilestick/Calibre-Web-Automator?tab=readme-ov-file#how-to-install-): 📖
  - [Docker-Compose](https://github.com/crocodilestick/Calibre-Web-Automator?tab=readme-ov-file#method-1-using-docker-compose--recommended) 🐋⭐(Recommended)
  - [Quick Install](https://github.com/crocodilestick/Calibre-Web-Automator/tree/main?tab=readme-ov-file#quick-install-) 🚀
- [Usage](https://github.com/crocodilestick/Calibre-Web-Automator?tab=readme-ov-file#method-2-using-the-script-install-method-with-clean-calibre-web-base-image--not-recommended) 🔧
- [Further Development](https://github.com/crocodilestick/Calibre-Web-Automator?tab=readme-ov-file#method-2-using-the-script-install-method-with-clean-calibre-web-base-image--not-recommended) 🏗️

## Why does it exist? 🔓

Calibre, while a fantastic tool for its age, has several problems when containerised, including its reliance on a KasmVNC server instance for the UI, which is near impossible to use on mobile and is relatively resource-heavy if you're running a small, lower power server like I am.

For many, Calibre-Web has really swooped in to save the day, offering an alternative to a containerised Calibre instance that's quick, easy to set up, resource-light and with a much more modern UI to boot.

However, when compared to full-fat Calibre, it unfortunately lacks a few core features leading many to run both services in parallel, each serving to fill in where the other lacks, resulting in an often clunky, imperfect solution.

# 🚨 **NEW UPDATE WITH FIXES** 🚨 - Version 1.2.2 - 29.07.2024

![GitHub Release](https://img.shields.io/github/v/release/crocodilestick/calibre-web-automator)
![GitHub commits since latest release](https://img.shields.io/github/commits-since/crocodilestick/calibre-web-automator/latest)

### 🚨 Please **Update to the latest DockerHub image ASAP** to avoid major issues with the old Import/Ingest System and for **General Stability Improvements**

This update should now render the Auto-Import system **FULLY STABLE**, with all the major bugs now being fixed! 🎊

If you find any bugs however, please be sure to create an issue in the [Issues Section](https://github.com/crocodilestick/Calibre-Web-Automator/issues)! 🪲

#### Fixed Bugs:
- Fixed moving (not copying) a folder into cwa-book-ingest not detecting the folder and its contents
- Fixed import duplication issues that sometimes happens from slower drive speeds or mass importing

#### New Features:
- Calibre-Web-Automated's Version Number now shows up alongside the version of the stock CW running as a base on the Settings page

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
  - Previously this meant that anyone with `non-epub` ebooks in their existing Calibre Libraries was unable to take advantage of all of `Calibre-Web Automator`'s features reliably
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

# UNDER ACTIVE DEVELOPMENT ⚠️

- Please be aware that while CWA currently works for most people, it is still under active development and that bugs and unexpected behaviours can occur while we work and the code base matures
- I want to say a big thanks 🙏 to the members of this community that have taken the time to participate in the testing and development of this project, especially to @jmarmstrong1207 who has been working tirelessly on improving the project since the release of Version 1.2.0
  - In recognition of this, [@jmarmstrong1207](https://github.com/jmarmstrong1207) has now been promoted to a co-contributor here on the project, so feel free to also contact him with any issues, suggestions, ideas ect.
  - For any others that wish to contribute to this project in some way, please reach out on our Discord Server and see how you can best get involved:\
    \
    [![](https://dcbadge.limes.pink/api/server/https://discord.gg/EjgSeek94R)](https://discord.gg/EjgSeek94R)

### Coming in Version 1.3.0 - Currently in Testing Phase 🧪

- Simplification of CWA's install, specifically for users having issues binding the right folder of their existing Calibre libraries in the Docker Compose
- **Rebranded the Web UI** throughout to make it clear you are using Calibre-Web Automated
- Added a button on the Web UI's navbar that allows users to **switch between Light & Dark Modes in one click**
- Fixed a bug with cover_enforcer.py where books with '/' characters in the title or author's name(s) would break the process
- Added Version numbers to Settings page for the installed Linuxserver.io, Calibre and Kepubify distributions
- Added an **Update Notification system** to notify users of the availability of new updates from within the Web UI
  - Automatically triggered by a difference between the version number of the most recent GitHub release and the version installed
  - Set to only show once per calendar day until updated as to not be annoying
  - Persistent until closed with button to ensure it is seen
- Building future images via Dockerfile 🐋

### Coming Soon - Currently Under Active Development 🏗️

- A form of **Library Auto-Detect** is currently in development to mitigate these issues, as well as to automatically establish a fresh Calibre Library for new users without an existing one, to simplify the install for them and make it so they don't have to manually copy `metadata.db` files from the repo into specific folders ect.
- A `dockerfile` to help attract other developers, standardise our Image build procedure and to help us also release CWA as a Docker Mod
- Support for `arm64` architectures
- Adding tracking of ebook conversions to the `cwa.db`
- Integrating some of the new **Command-Line Features into the Web UI**

### Additional Features on our Roadmap 🛣️🌱

- A Batch Editing Feature to allow the editing of Metadata for multiple books at once, i.e. for a series ect.
- Please suggest any ideas or wishes you might have! we're open to anything!

### IMPORTANT NOTE: ⚡ Current users of Calibre-Web Automated versions before 1.2.2 should update using the latest DockerHub image to ensure stability and conpatability with future updates

# How To Install 📖

## Quick Install 🚀

1. Download the Docker Compose template file using the command below:

```
curl -OL https://raw.githubusercontent.com/crocodilestick/calibre-web-automator/main/docker-compose.yml
```

2. Navigate to where you downloaded the Compose file using `cd` and run:

```
docker compose up -d
```

And that's you off to the races! 🥳 HOWEVER to avoid potential problems and ensure maximum functionality, we reccommend carrying out these [Post-Install Tasks Here](#3-recommended-post-install-tasks).

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
    volumes:
      - /path/to/config/folder:/config
      - /path/to/the/folder/you/want/to/use/for/book/ingest:/cwa-book-ingest
      - "/path/to/your/calibre/library:/calibre-main/Calibre Library"
      #- /path/to/where/you/keep/your/books:/books #Optional
      #- /path/to/your/gmail/credentials.json:/app/calibre-web/gmail.json #Optional
    ports:
      - 8084:8083 # Change the first number to change the port you want to access the Web UI, not the second
    restart: unless-stopped
```

- **Explanation of the Container Bindings:**
  - `/config` - Can be any empty folder, used to store logs and other miscellaneous files that keep CWA running
  - `/cwa-book-ingest` - **ATTENTION** ⚠️ - All files within this folder will be **DELETED** after being processed. This folder should only be used to dump new books into for import and automatic conversion
  - `/calibre-main/Calibre Library` - This should be bound to your Calibre library folder where the `metadata.db` file resides within.
    - If you don't have an **existing** Calibre Database, you can use the Docker Template folder for a quick install mentioned above.
  - `/books` _(Optional)_ - This is purely optional, I personally bind /books to where I store my downloaded books so that they accessible from within the container but CWA doesn't require this
  - `/gmail.json` _(Optional)_ - This is used to setup Calibre-Web and/or CWA with your gmail account for sending books via email. Follow the guide [here](https://github.com/janeczku/calibre-web/wiki/Setup-Mailserver#gmail) if this is something you're interested in but be warned it can be a very fiddly process, I would personally recommend a simple SMTP Server

### 2. And just like that, Calibre-Web Automated should be up and running!

- By default, `/cwa-book-ingest` is the ingest folder bound to the ingest folder you entered in the Docker Compose template however should you want to change any of the default directories, use the `cwa-change-dirs` command from within the container to edit the default paths

### 3. **_Recommended Post-Install Tasks:_**

#### _Calibre-Web Quick Start Guide_

1. Open your browser and navigate to http://localhost:8084 or http://localhost:8084/opds for the OPDS catalog
2. Log in with the default admin credentials (_below_)
3. If you don't have an existing Calibre database, you can use the `metadata.db` file above
   - This is a blank Calibre-Database you can use to perform the Initial Setup with
   - Place the `metadata.db` file in the the folder you bound to `/calibre-main` in your Docker Compose
4. During the Web UI's Initial Setup screen, Set Location of Calibre database to the path of the folder to `/calibre-main` and click "Save"
5. Optionally, use Google Drive to host your Calibre library by following the Google Drive integration guide
6. Configure your Calibre-Web instance via the admin page, referring to the Basic Configuration and UI Configuration guides
7. Add books by having them placed in the folder you bound to `cwa-book-ingest` in your Docker Compose

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

<!-- ## Method 2: Using the **Script Install Method** with stock Calibre-Web Base Image 📜 🔻(Not Recommended)

- This method is only recommended for **developers** or those who would like to set their own directories using the provided **Setup Wizard**
- To begin this installation method, you'll need to use the Docker Compose below to set up a base container for you to perform the installation within

### Step 1: docker-compose for stock Calibre-Web with the Calibre eBook-converter

```docker-compose
---
services:
  calibre-web:
    image: lscr.io/linuxserver/calibre-web:latest
    container_name: calibre-web-automated
    environment:
      - PUID=1000
      - PGID=100
      - PATH=/lsiopy/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
      - HOME=/root
      - LANGUAGE=en_US.UTF-8
      - LANG=en_US.UTF-8
      - TERM=xterm
      - S6_CMD_WAIT_FOR_SERVICES_MAXTIME=0
      - S6_VERBOSITY=1
      - S6_STAGE2_HOOK=/docker-mods
      - VIRTUAL_ENV=/isiopy
      - LSIO_FIRST_PARTY=true
      - TZ=Europe/Berlin
      - DOCKER_MODS=linuxserver/mods:universal-calibre
      - OAUTHLIB_RELAX_TOKEN_SCOPE=1 #Optional
    volumes:
      - /path/to/config/folder:/config
      - /path/to/the/folder/you/want/to/use/for/book/ingest:/cwa-book-ingest
      - "/path/to/your/calibre/library:/calibre-main/Calibre Library"
     # - /path/to/where/you/keep/your/books:/books #Optional
     # - /path/to/your/gmail/credentials.json:/app/calibre-web/gmail.json #Optional
    ports:
      - 8083:8083 # Change the first number to change the port you want to access the Web UI, not the second

    restart: unless-stopped

```

### Step 2: CWA Installation ⚙️

1. Download the `calibre-web-automator` folder from this repo, unzip it, and then place the `calibre-web-automator` folder inside into the folder bound to your `/config` volume
2. Next, use the following command to gain access to the container's CLI, replacing **_calibre-web_** with the name of your Calibre-Web container if it differs:

```
docker exec -it calibre-web bash
```

3. Navigate inside the **calibre-web-automator** that you previously placed within your `/config` directory with the following command:

```
cd /config/calibre-web-automator
```

4. Make sure the `setup-cwa.sh`is executable with the following command:

```
chmod +x setup-cwa.sh
```

5. Now initiate the install with the following command:

```
./setup-cwa.sh
```

6. When prompted, follow the on-screen instructions to create and enter the paths of the directories the program needs to function.
   - The folders can be wherever you like but **they must be in a persistent volume** like in your `/books` bind, **otherwise they and their contents won't be persistent between rebuilds of the container**
7. When the setup is complete, we need to restart the container for the changes to take effect. You can do so by using `exit` to return to your main shell and then running the following command:

```
docker restart calibre-web` or `docker restart <replace-this-with-the-name-of-your-calibre-web-container>
```

1. Once the container is back up and running, you should be good to go! To check however, do the following:
   - Then run the included testing script with `cwa-check` anywhere in the terminal to verify your install.
   - All three prompts should return green, indicating that the new `calibre-scan` and `books-to-process-scan` services are working properly.
   - If one or both of the services return red indicating that they are not running, rebuild your Calibre-Web container using the `docker-compose` above and retry the installation process.

### Step 3: Making The Changes Persistent 🔗

As you may know, every time you rebuild a docker container, anything that isn't include in the source image or saved to a persistent volume, is gone and the container returns to it's stock state.

### To make sure CWA remains installed between rebuilds, you can do the following:

### Option 1: Creating a new, modified Docker Image (Recommended)

#### This option sounds much harder than it really is if you've never done it before but it's actually shockingly easy and currently the best option now the developer of Calibre-Web is sunsetting further development of the project.

1. Successfully install CWA using the steps above and confirm it's working by running the included `check-cwa-install.sh' binary from the CLI of your Calibre-Web container as described above in Step 7
2. While the container is running, from your main shell (use `exit` to return to your main shell if your still in the container's CLI) run the following command to generate an image of your newly modified Calibre-Web container, exactly as it's currently configured:

```
docker commit calibre-web calibre-web-automated
```

- Replace `calibre-web` with the name of your Calibre-Web container if it differs and you can also replace `calibre-web-automated` with whatever name you like

3. Once the process is finished, you can check the image was successfully created using the following command to list all current available docker images on your system:

```
docker images
```

4. Once you've confirmed the image was created successfully, edit your docker compose file so that the variable `image` is now as follows:

```docker-compose
---
services:
  calibre-web:
    image: calibre-web-automated:latest
    container_name: calibre-web
    environment:
 ...
```

- Now the image variable should read `image: calibre-web-automated:latest` or `image: <your-chosen-image-name-here>:latest`

5. Finished! 🎉 Now every time you rebuild your container, CWA as well as any other changes you may have made will remain 👍

### Option 2: Re-Running 'setup-cwa.sh' Whenever You Rebuild the Container

This wouldn't be my preferred method but if you never really touch your containers the above may be overkill for you.
 -->
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

## Changing the Default Directories

- If you ever need to change the locations of your **ingest**, **import** and/ or **calibre-library** folders, use the `cwa-change-dirs` command from anywhere within the container's terminal to open the json file where the paths are saved and change them as required.

## Checking the Monitoring Services are working correctly

- Simply run the following command from within the container: `cwa-check`
- If all 3 services come back as green and running they are working properly, otherwise there may be problems with your configuration/install

# Further Development 🏗️

- Calibre-Web Automated (_formerly Calibre-Web Automator_) was made to be everything I need for my reading workflow, I personally love the new features and hope you do to!
- While it already does everything I need, building it has been really fun and it's great to see so many other people get so much use out of it!
- And so on top of continuing to perform maintainace and bugfixes, we are always open to suggestions and ideas from the community so if there's something you'd like to see, don't be afraid to ask!
- To do so you can either open an Issue here on the project page or get in touch with us on our Discord Server [here](https://discord.gg/EjgSeek94R)!
- We're always looking for new people to help out too so if that sounds like you, let us know!
