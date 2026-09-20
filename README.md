# Drive Audit & Finder Tag Manager (`drive-audit-cli`)

A fast, lightweight CLI utility for auditing local drives, cataloging files, indexing macOS Finder tags, and extracting photo EXIF metadata into an organized SQLite database.

---

## Features

- **Host & Multi-Drive Tracking**: Automatically identifies machine hostnames, OS info, and IP addresses, enabling multi-machine drive inventorying in a unified database.
- **Native macOS Finder Tag Extraction**: Reads extended file attributes (`com.apple.metadata:_kMDItemUserTags`) via binary property list decoding to capture Finder color/text tags for both folders and files.
- **Manual Directory Tagging**: Search and tag specific directories interactively with custom labels.
- **Photo EXIF Metadata Parsing**: Automatically parses EXIF data from images (camera make/model, date taken, resolution, GPS coordinates, ISO, f-stop, exposure time).
- **File Categorization**: Automatically categorizes files into `image`, `video`, `audio`, `document`, `archive`, `code`, and `other`.
- **Search & Reporting**: Search files across direct tags and inherited folder tags, view storage breakdowns per host, and list all active tags.
- **Relational SQLite Database**: Structured schema with foreign keys and cascade rules for clean data integrity and easy custom querying.

---

## Requirements

- **Python 3.8+**
- **macOS** (for macOS Finder tag extraction; core auditing and EXIF parsing work cross-platform)
- Python packages:
  - `exifread`

---

## Installation

1. **Clone the repository**:
   ```bash
   git clone https://github.com/nickolaycohen/drive-audit-cli.git
   cd drive-audit-cli
   ```

2. **Create a virtual environment (optional, recommended)**:
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   ```

3. **Install dependencies**:
   ```bash
   pip3 install -r requirements.txt
   # or
   python3 -m pip install -r requirements.txt
   ```

---

## Quick Start

Run the interactive CLI application:

```bash
python3 drive_audit_finder.py
```

Upon launch, you will be presented with the main menu:

```text
=============================================
  DRIVE AUDIT & FINDER TAG MANAGER  
=============================================
1. Scan local directory (Sync Finder Tags)
2. View hosts & storage overview
3. List all active tags (Directory & File)
4. Add manual tag to a directory
5. Search files by tag (Finder & Manual)
6. Exit
```

---

## Menu Options & Usage

### 1. Scan Local Directory (Sync Finder Tags)
Scans a target directory path (e.g., `/Users/username/Pictures` or `/Volumes/ExternalDrive`), indexing all files and subdirectories.
- Automatically extracts macOS Finder tags for directories and individual files.
- Automatically extracts EXIF metadata for supported image files (`.jpg`, `.jpeg`, `.png`, `.heic`, `.raw`, `.cr2`, `.nef`, etc.).
- Updates existing records if re-scanned.

### 2. View Hosts & Storage Overview
Displays a summary table showing all indexed hosts, their operating system, IP address, total file count, and aggregate storage size in gigabytes (GB).

### 3. List All Active Tags (Directory & File)
Lists all discovered tags grouped by:
- **Directory Tags**: Displays the tag name, source (`finder` vs `manual`), directory name, path, and host.
- **File Tags**: Displays direct Finder tags attached to specific files.

### 4. Add Manual Tag to a Directory
Allows you to search for directories by keyword and attach custom metadata tags directly to the folder in the database.

### 5. Search Files by Tag (Finder & Manual)
Search for files matching a specific tag query. Matches both:
- Tags placed directly on the file.
- Tags inherited from the parent directory.
- Displays file category, file size in MB, full path, and camera model (if EXIF exists).

---

## Database Schema

All audit data is saved to a SQLite database (`drive_audit.db`). The relational schema includes:

```
  ┌────────────┐
  │   hosts    │
  └─────┬──────┘
        │ 1:N
        ▼
  ┌────────────┐        1:N       ┌────────────────┐
  │directories ├─────────────────►│ directory_tags │
  └─────┬──────┘                  └────────────────┘
        │ 1:N
        ▼
  ┌────────────┐        1:N       ┌────────────────┐
  │   files    ├─────────────────►│   file_tags    │
  └─────┬──────┘                  └────────────────┘
        │ 1:1
        ▼
  ┌────────────────┐
  │ media_metadata │
  └────────────────┘
```

- **`hosts`**: `id`, `hostname`, `os_name`, `ip_address`, `first_scanned_at`, `last_scanned_at`
- **`directories`**: `id`, `host_id`, `path`, `name`, `created_at`, `modified_at`, `scanned_at`
- **`directory_tags`**: `id`, `directory_id`, `tag_name`, `source` (`finder` | `manual`), `created_at`
- **`files`**: `id`, `directory_id`, `name`, `category`, `extension`, `size_bytes`, `created_at`, `modified_at`, `scanned_at`
- **`file_tags`**: `id`, `file_id`, `tag_name`, `created_at`
- **`media_metadata`**: `id`, `file_id`, `camera_make`, `camera_model`, `date_taken`, `width`, `height`, `gps_latitude`, `gps_longitude`, `f_number`, `exposure_time`, `iso`

---

## Custom SQL Queries

Because data is stored in standard SQLite format (`drive_audit.db`), you can run queries with any SQLite client:

```sql
-- Find top 10 largest video files
SELECT f.name, (f.size_bytes / 1024.0 / 1024.0) AS size_mb, d.path
FROM files f
JOIN directories d ON f.directory_id = d.id
WHERE f.category = 'video'
ORDER BY f.size_bytes DESC
LIMIT 10;

-- Find all photos taken with a specific camera model
SELECT f.name, m.camera_model, m.date_taken, d.path
FROM files f
JOIN media_metadata m ON f.id = m.file_id
JOIN directories d ON f.directory_id = d.id
WHERE m.camera_model LIKE '%Sony%' OR m.camera_model LIKE '%Canon%';
```

---

## License

MIT License.
