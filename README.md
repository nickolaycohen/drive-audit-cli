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
- **Live Progress & Smart Caching**: Real-time terminal progress indicators and automatic skip-caching for folders scanned within a configurable window (default: 24h) if unchanged on disk.
- **Interruption Resilience**: Periodic batch commits and graceful `Ctrl+C` interrupt handling ensure zero data loss during long scans.
- **Relational SQLite Database**: Structured schema with WAL mode, foreign keys, and cascade rules for clean data integrity and easy custom querying.

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
1. Scan local directory (Sync Finder Tags & Clean Deletions)
2. View hosts & storage overview
3. View top-level folder scans report
4. Generate report of largest files
5. Prune deleted files & folders (Sync DB with disk)
6. List all active tags (Directory & File)
7. Add manual tag to a directory
8. Search files by tag (Finder & Manual)
9. Exit
```

---

## Menu Options & Usage

### 1. Scan Local Directory (Sync Finder Tags & Clean Deletions)
Scans a target directory path (e.g., `/Users/username/Pictures` or `/Volumes/ExternalDrive`), indexing all files and subdirectories.
- **Pre-Scan Finder Size Query**: Instantly queries macOS Finder via AppleScript for the target folder's total size before scanning starts.
- **Dynamic Live Progress & ETA**: Displays real-time progress percentage (`%`), estimated time remaining (`ETA: mm:ss`), current I/O speed (`MB/s`), and elapsed time.
- **Automatic Deletion Reconciliation**: Purges deleted files and removed subdirectories from the database.
- **Smart 24-Hour Skip Caching**: Skips scanning files in folders that were already scanned within the last $N$ hours and untouched since.
- **macOS Finder Tags & EXIF Parsing**: Captures native Finder color/name tags and image camera/GPS metadata.
- **Updates & Refreshes**: Automatically updates existing records if modified on disk.

### 2. View Hosts & Storage Overview
Displays a summary table showing all indexed hosts, their operating system, IP address, total file count, and aggregate storage size in gigabytes (GB).

### 3. View Top-Level Folder Scans Report
Provides an overarching summary of each primary root folder scanned:
- Total subdirectories, total files, and cumulative storage per root scan.
- Detailed file category breakdown (image, video, document, archive, code, other).
- Top direct subfolders with individual subtree storage and file counts.
- Optional one-click export to **CSV** (`top_level_scans_report.csv`) or **Markdown** (`top_level_scans_report.md`).

### 4. Generate Report of Largest Files
Displays a formatted ranking of the largest indexed files across all scanned hosts:
- Configurable result limit (e.g. top 25, 50, 100).
- Optional category filter (`video`, `image`, `document`, `archive`, `code`, `other`).
- Displays formatted size, modified date, created date, hostname, and full path.
- Optional one-click export to **CSV** (`largest_files_report.csv`) or **Markdown** (`largest_files_report.md`).

### 5. Prune Deleted Files & Folders (Sync DB with Disk)
Instantly validates all indexed directories and files in the database against the local filesystem, immediately purging records for files and folders that no longer exist on disk.

### 6. List All Active Tags (Directory & File)
Lists all discovered tags grouped by:
- **Directory Tags**: Displays the tag name, source (`finder` vs `manual`), directory name, path, and host.
- **File Tags**: Displays direct Finder tags attached to specific files.

### 7. Add Manual Tag to a Directory
Allows you to search for directories by keyword and attach custom metadata tags directly to the folder in the database.

### 8. Search Files by Tag (Finder & Manual)
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
