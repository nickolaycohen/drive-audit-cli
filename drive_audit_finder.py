import os
import sys
import time
import shutil
import sqlite3
import datetime
import socket
import platform
import plistlib
import subprocess
from pathlib import Path
try:
    import exifread
except ImportError:
    exifread = None

# Extension mappings for classification
EXTENSION_MAP = {
    "image": {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tiff", ".webp", ".heic", ".raw", ".cr2", ".nef"},
    "video": {".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".webm", ".m4v", ".3gp"},
    "audio": {".mp3", ".wav", ".flac", ".aac", ".ogg", ".m4a", ".wma"},
    "document": {".pdf", ".docx", ".doc", ".xlsx", ".xls", ".pptx", ".txt", ".csv", ".rtf"},
    "archive": {".zip", ".tar", ".gz", ".7z", ".rar", ".bz2"},
    "code": {".py", ".js", ".html", ".css", ".cpp", ".c", ".java", ".json", ".xml", ".sh", ".sql"}
}

def get_file_category(extension: str) -> str:
    """Categorizes a file based on its extension."""
    ext = extension.lower()
    for category, extensions in EXTENSION_MAP.items():
        if ext in extensions:
            return category
    return "other"

def get_finder_tags(file_or_dir_path: Path) -> list:
    """Extracts macOS Finder tags from extended attributes (com.apple.metadata:_kMDItemUserTags)."""
    tags = []
    if platform.system() != "Darwin":
        return tags  # Finder tags are macOS-specific

    try:
        cmd = ["xattr", "-p", "com.apple.metadata:_kMDItemUserTags", str(file_or_dir_path.resolve())]
        result = subprocess.run(cmd, capture_output=True)

        if result.returncode == 0 and result.stdout:
            hex_str = result.stdout.decode('utf-8').replace(" ", "").replace("\n", "")
            raw_data = bytes.fromhex(hex_str)
            plist_data = plistlib.loads(raw_data)
            
            for tag_entry in plist_data:
                # Finder tags can be "TagName\nColorIndex" or plain "TagName"
                tag_name = tag_entry.split('\n')[0].strip().lower()
                if tag_name:
                    tags.append(tag_name)
    except Exception:
        pass  # Gracefully ignore permission or missing attribute errors

    return tags

def extract_photo_exif(file_path: Path) -> dict:
    """Extracts EXIF metadata from photo files."""
    exif_data = {}
    if exifread is None:
        return exif_data
    try:
        with open(file_path, 'rb') as f:
            tags = exifread.process_file(f, stop_tag="UNDEF", details=False)
            target_tags = {
                "Image Make": "camera_make",
                "Image Model": "camera_model",
                "EXIF DateTimeOriginal": "date_taken",
                "EXIF ExifImageWidth": "width",
                "EXIF ExifImageLength": "height",
                "GPS GPSLatitude": "gps_latitude",
                "GPS GPSLongitude": "gps_longitude",
                "EXIF FNumber": "f_number",
                "EXIF ExposureTime": "exposure_time",
                "EXIF ISOSpeedRatings": "iso"
            }
            for tag_key, output_key in target_tags.items():
                if tag_key in tags:
                    exif_data[output_key] = str(tags[tag_key])
    except Exception as e:
        exif_data["exif_error"] = str(e)
    return exif_data

def get_db_connection(db_path: str) -> sqlite3.Connection:
    """Returns a SQLite connection configured with WAL mode, busy timeout, and foreign keys."""
    conn = sqlite3.connect(db_path, timeout=60.0)
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA busy_timeout = 60000;")
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn

def init_database(db_path: str) -> sqlite3.Connection:
    """Creates schema supporting hosts, directories, directory_tags, files, file_tags, and media_metadata."""
    conn = get_db_connection(db_path)
    cursor = conn.cursor()

    # 1. Hosts Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS hosts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            hostname TEXT NOT NULL UNIQUE,
            os_name TEXT,
            ip_address TEXT,
            first_scanned_at TEXT NOT NULL,
            last_scanned_at TEXT NOT NULL
        )
    """)

    # 2. Directories Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS directories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            host_id INTEGER NOT NULL,
            path TEXT NOT NULL,
            name TEXT NOT NULL,
            created_at TEXT,
            modified_at TEXT,
            scanned_at TEXT NOT NULL,
            FOREIGN KEY (host_id) REFERENCES hosts (id) ON DELETE CASCADE,
            UNIQUE(host_id, path)
        )
    """)

    # 3. Directory Tags Table (Supports both Finder and Manual sources)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS directory_tags (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            directory_id INTEGER NOT NULL,
            tag_name TEXT NOT NULL,
            source TEXT NOT NULL DEFAULT 'finder',
            created_at TEXT NOT NULL,
            FOREIGN KEY (directory_id) REFERENCES directories (id) ON DELETE CASCADE,
            UNIQUE(directory_id, tag_name)
        )
    """)

    # 4. Files Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            directory_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            category TEXT NOT NULL,
            extension TEXT,
            size_bytes INTEGER NOT NULL,
            created_at TEXT,
            modified_at TEXT,
            scanned_at TEXT NOT NULL,
            FOREIGN KEY (directory_id) REFERENCES directories (id) ON DELETE CASCADE,
            UNIQUE(directory_id, name)
        )
    """)

    # 5. File Tags Table (For direct Finder tags on individual files)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS file_tags (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_id INTEGER NOT NULL,
            tag_name TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (file_id) REFERENCES files (id) ON DELETE CASCADE,
            UNIQUE(file_id, tag_name)
        )
    """)

    # 6. Media Metadata Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS media_metadata (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_id INTEGER NOT NULL,
            camera_make TEXT,
            camera_model TEXT,
            date_taken TEXT,
            width TEXT,
            height TEXT,
            gps_latitude TEXT,
            gps_longitude TEXT,
            f_number TEXT,
            exposure_time TEXT,
            iso TEXT,
            FOREIGN KEY (file_id) REFERENCES files (id) ON DELETE CASCADE
        )
    """)

    conn.commit()
    return conn

def get_or_create_host(cursor: sqlite3.Cursor) -> int:
    """Detects current desktop host details and returns its database ID."""
    hostname = socket.gethostname()
    os_name = platform.system()
    scan_time = datetime.datetime.now().isoformat()

    try:
        ip_address = socket.gethostbyname(hostname)
    except Exception:
        ip_address = "127.0.0.1"

    cursor.execute("""
        INSERT INTO hosts (hostname, os_name, ip_address, first_scanned_at, last_scanned_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(hostname) DO UPDATE SET
            os_name=excluded.os_name,
            ip_address=excluded.ip_address,
            last_scanned_at=excluded.last_scanned_at
    """, (hostname, os_name, ip_address, scan_time, scan_time))

    cursor.execute("SELECT id FROM hosts WHERE hostname = ?", (hostname,))
    return cursor.fetchone()[0]

def format_size(bytes_val: int) -> str:
    """Formats bytes into a readable string (KB, MB, GB, TB)."""
    if bytes_val < 1024:
        return f"{bytes_val} B"
    elif bytes_val < 1024**2:
        return f"{bytes_val / 1024:.1f} KB"
    elif bytes_val < 1024**3:
        return f"{bytes_val / (1024**2):.1f} MB"
    elif bytes_val < 1024**4:
        return f"{bytes_val / (1024**3):.2f} GB"
    else:
        return f"{bytes_val / (1024**4):.2f} TB"

def update_scan_progress(scanned_dirs: int, scanned_files: int, scanned_bytes: int, current_path: str, start_time: float, skipped_dirs: int = 0):
    """Prints a single-line live progress indicator."""
    elapsed = int(time.time() - start_time)
    mins, secs = divmod(elapsed, 60)
    elapsed_str = f"{mins:02d}:{secs:02d}"
    size_str = format_size(scanned_bytes)
    cols = shutil.get_terminal_size((80, 20)).columns

    skip_str = f" ({skipped_dirs:,} cached)" if skipped_dirs > 0 else ""
    base_info = f"⏳ [{elapsed_str}] {scanned_dirs:,} dirs{skip_str} | {scanned_files:,} files ({size_str}) -> "
    avail_cols = cols - len(base_info) - 2
    if avail_cols > 10:
        if len(current_path) > avail_cols:
            display_path = "..." + current_path[-(avail_cols - 3):]
        else:
            display_path = current_path
    else:
        display_path = ""

    status = f"{base_info}{display_path}"
    sys.stdout.write(f"\r\033[K{status}")
    sys.stdout.flush()

def audit_directory_interactive(db_path: str):
    """Scans local directory, extracts Finder tags for folders/files, and stores EXIF."""
    print("\n--- NEW DRIVE / FOLDER AUDIT ---")
    target_path = input("Enter path to scan (e.g., ./ or /Users/name/Pictures): ").strip().strip('"').strip("'")
    root = Path(target_path)

    if not root.exists():
        print(f"\n[Error] Path '{target_path}' does not exist.")
        return

    skip_input = input("Skip folders scanned within last N hours? [Default: 24, enter 0 to force rescan]: ").strip()
    if not skip_input:
        skip_hours = 24.0
    else:
        try:
            skip_hours = float(skip_input)
        except ValueError:
            skip_hours = 24.0

    conn = init_database(db_path)
    cursor = conn.cursor()
    scan_time = datetime.datetime.now().isoformat()

    host_id = get_or_create_host(cursor)
    hostname = socket.gethostname()

    # Preload existing directories for host to enable fast O(1) cache lookups
    cursor.execute("""
        SELECT d.id, d.path, d.scanned_at, d.modified_at, COUNT(f.id), COALESCE(SUM(f.size_bytes), 0)
        FROM directories d
        LEFT JOIN files f ON d.id = f.directory_id
        WHERE d.host_id = ?
        GROUP BY d.id
    """, (host_id,))

    existing_dirs = {}
    for row in cursor.fetchall():
        dir_id, d_path, scanned_at_str, mod_at_str, f_count, f_bytes = row
        scanned_dt = None
        if scanned_at_str:
            try:
                scanned_dt = datetime.datetime.fromisoformat(scanned_at_str)
            except Exception:
                pass
        existing_dirs[d_path] = {
            "id": dir_id,
            "scanned_at": scanned_dt,
            "file_count": f_count,
            "total_bytes": f_bytes
        }

    skip_msg = f"(skipping folders scanned < {skip_hours:g}h ago)" if skip_hours > 0 else "(full rescan)"
    print(f"\nScanning: {root.resolve()} on host [{hostname}] {skip_msg} ... (Press Ctrl+C to stop)")

    scanned_files = 0
    scanned_dirs = 0
    skipped_dirs = 0
    skipped_files = 0
    scanned_bytes = 0
    dir_tags_count = 0
    file_tags_count = 0

    start_time = time.time()
    last_progress_time = 0.0
    last_commit_time = time.time()

    try:
        for dirpath, _, filenames in os.walk(root):
            dir_obj = Path(dirpath)
            if not dir_obj.exists():
                continue

            try:
                resolved_path = str(dir_obj.resolve())
                dir_stat = dir_obj.stat()
                dir_mtime_dt = datetime.datetime.fromtimestamp(dir_stat.st_mtime)

                # Smart Cache Check: skip folder if scanned < skip_hours ago and untouched since
                if skip_hours > 0 and resolved_path in existing_dirs:
                    cached = existing_dirs[resolved_path]
                    last_scanned = cached["scanned_at"]
                    if last_scanned:
                        hours_since_scan = (datetime.datetime.now() - last_scanned).total_seconds() / 3600.0
                        if hours_since_scan < skip_hours and dir_mtime_dt <= last_scanned:
                            skipped_dirs += 1
                            skipped_files += cached["file_count"]
                            scanned_bytes += cached["total_bytes"]
                            
                            now = time.time()
                            if now - last_progress_time >= 0.1:
                                update_scan_progress(scanned_dirs, scanned_files + skipped_files, scanned_bytes, resolved_path, start_time, skipped_dirs)
                                last_progress_time = now
                            continue

                # 1. Upsert Directory record
                cursor.execute("""
                    INSERT INTO directories (host_id, path, name, created_at, modified_at, scanned_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(host_id, path) DO UPDATE SET
                        modified_at=excluded.modified_at,
                        scanned_at=excluded.scanned_at
                """, (
                    host_id,
                    resolved_path,
                    dir_obj.name or resolved_path,
                    datetime.datetime.fromtimestamp(dir_stat.st_ctime).isoformat(),
                    datetime.datetime.fromtimestamp(dir_stat.st_mtime).isoformat(),
                    scan_time
                ))

                cursor.execute("SELECT id FROM directories WHERE host_id = ? AND path = ?", (host_id, resolved_path))
                directory_id = cursor.fetchone()[0]
                scanned_dirs += 1

                # Extract Directory Finder Tags
                finder_dir_tags = get_finder_tags(dir_obj)
                for tag in finder_dir_tags:
                    cursor.execute("""
                        INSERT INTO directory_tags (directory_id, tag_name, source, created_at)
                        VALUES (?, ?, 'finder', ?)
                        ON CONFLICT(directory_id, tag_name) DO NOTHING
                    """, (directory_id, tag, scan_time))
                    dir_tags_count += 1

                # 2. Process Files inside Directory
                for filename in filenames:
                    file_path = dir_obj / filename
                    if not file_path.exists():
                        continue

                    try:
                        stat = file_path.stat()
                        ext = file_path.suffix.lower()
                        category = get_file_category(ext)
                        file_size = stat.st_size
                        scanned_bytes += file_size

                        cursor.execute("""
                            INSERT INTO files (directory_id, name, category, extension, size_bytes, created_at, modified_at, scanned_at)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                            ON CONFLICT(directory_id, name) DO UPDATE SET
                                size_bytes=excluded.size_bytes,
                                modified_at=excluded.modified_at,
                                scanned_at=excluded.scanned_at
                        """, (
                            directory_id,
                            filename,
                            category,
                            ext,
                            file_size,
                            datetime.datetime.fromtimestamp(stat.st_ctime).isoformat(),
                            datetime.datetime.fromtimestamp(stat.st_mtime).isoformat(),
                            scan_time
                        ))

                        cursor.execute("SELECT id FROM files WHERE directory_id = ? AND name = ?", (directory_id, filename))
                        file_id = cursor.fetchone()[0]
                        scanned_files += 1

                        # Extract File Finder Tags
                        finder_file_tags = get_finder_tags(file_path)
                        for tag in finder_file_tags:
                            cursor.execute("""
                                INSERT INTO file_tags (file_id, tag_name, created_at)
                                VALUES (?, ?, ?)
                                ON CONFLICT(file_id, tag_name) DO NOTHING
                            """, (file_id, tag, scan_time))
                            file_tags_count += 1

                        # Extract Photo EXIF Metadata
                        if category == "image":
                            exif = extract_photo_exif(file_path)
                            if exif:
                                cursor.execute("""
                                    INSERT INTO media_metadata (
                                        file_id, camera_make, camera_model, date_taken, width, height,
                                        gps_latitude, gps_longitude, f_number, exposure_time, iso
                                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                                """, (
                                    file_id,
                                    exif.get("camera_make"),
                                    exif.get("camera_model"),
                                    exif.get("date_taken"),
                                    exif.get("width"),
                                    exif.get("height"),
                                    exif.get("gps_latitude"),
                                    exif.get("gps_longitude"),
                                    exif.get("f_number"),
                                    exif.get("exposure_time"),
                                    exif.get("iso")
                                ))
                    except PermissionError:
                        continue

                    # Periodic UI update during large directories
                    now = time.time()
                    if now - last_progress_time >= 0.1:
                        update_scan_progress(scanned_dirs, scanned_files + skipped_files, scanned_bytes, resolved_path, start_time, skipped_dirs)
                        last_progress_time = now

                    # Periodic commit every 2 seconds
                    if now - last_commit_time >= 2.0:
                        conn.commit()
                        last_commit_time = now

                # Progress update after directory completion
                now = time.time()
                if now - last_progress_time >= 0.1:
                    update_scan_progress(scanned_dirs, scanned_files + skipped_files, scanned_bytes, resolved_path, start_time, skipped_dirs)
                    last_progress_time = now

            except PermissionError:
                continue

    except KeyboardInterrupt:
        conn.commit()
        conn.close()
        sys.stdout.write("\r\033[K")
        sys.stdout.flush()
        print(f"\n[Scan Interrupted] Stopped by user.")
        print(f"  • Processed: {scanned_dirs:,} folders ({skipped_dirs:,} cached), {scanned_files + skipped_files:,} files ({format_size(scanned_bytes)}).")
        return

    conn.commit()
    conn.close()
    sys.stdout.write("\r\033[K")
    sys.stdout.flush()

    elapsed = time.time() - start_time
    mins, secs = divmod(int(elapsed), 60)
    time_str = f"{mins}m {secs}s" if mins > 0 else f"{elapsed:.1f}s"

    print(f"\n[Success] Audit complete in {time_str}!")
    print(f"  • Host:            {hostname}")
    print(f"  • Root scanned:    {root.resolve()}")
    if skipped_dirs > 0:
        print(f"  • Folders indexed: {scanned_dirs:,} scanned ({skipped_dirs:,} skipped — scanned < {skip_hours:g}h ago)")
        print(f"  • Files indexed:   {scanned_files:,} scanned ({skipped_files:,} verified from cache)")
    else:
        print(f"  • Folders indexed: {scanned_dirs:,} ({dir_tags_count:,} Finder tags)")
        print(f"  • Files indexed:   {scanned_files:,} ({file_tags_count:,} Finder tags)")
    print(f"  • Total storage:   {format_size(scanned_bytes)}")


def show_hosts_summary(db_path: str):
    """Displays all indexed hosts and their total storage metrics."""
    if not os.path.exists(db_path):
        print("\n[Notice] No database found. Run a scan first.")
        return

    conn = get_db_connection(db_path)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT h.hostname, h.os_name, h.ip_address, COUNT(f.id) AS file_count, SUM(f.size_bytes) AS total_bytes
        FROM hosts h
        LEFT JOIN directories d ON h.id = d.host_id
        LEFT JOIN files f ON d.id = f.directory_id
        GROUP BY h.id
    """)

    rows = cursor.fetchall()
    conn.close()

    print("\n" + "=" * 75)
    print("INDEXED HOSTS OVERVIEW")
    print("=" * 75)
    print(f"{'Hostname':<20} | {'OS':<10} | {'IP Address':<15} | {'Files':<8} | {'Total Size (GB)'}")
    print("-" * 75)
    for host, os_name, ip, count, size in rows:
        gb = (size or 0) / (1024**3)
        print(f"{host:<20} | {os_name or 'N/A':<10} | {ip or 'N/A':<15} | {count or 0:<8} | {gb:.2f} GB")
    print("=" * 75)

def add_manual_directory_tag(db_path: str):
    """Manually tag a directory via CLI interface."""
    if not os.path.exists(db_path):
        print("\n[Notice] No database found. Run a scan first.")
        return

    search_term = input("\nEnter folder name or path keyword: ").strip()
    conn = get_db_connection(db_path)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT d.id, d.name, d.path, h.hostname 
        FROM directories d
        JOIN hosts h ON d.host_id = h.id
        WHERE d.name LIKE ? OR d.path LIKE ?
        LIMIT 10
    """, (f"%{search_term}%", f"%{search_term}%"))

    dirs = cursor.fetchall()

    if not dirs:
        print("\nNo matching directories found.")
        conn.close()
        return

    print("\nMatching Directories:")
    for idx, (dir_id, name, path, host) in enumerate(dirs, 1):
        print(f"{idx}. [{host}] {name} -> {path} (ID: {dir_id})")

    choice = input("\nSelect directory number to tag (or 'c' to cancel): ").strip()
    if not choice.isdigit() or int(choice) < 1 or int(choice) > len(dirs):
        print("Cancelled.")
        conn.close()
        return

    selected_dir_id = dirs[int(choice) - 1][0]
    selected_dir_name = dirs[int(choice) - 1][1]

    tag_name = input(f"Enter manual tag for '{selected_dir_name}': ").strip().lower()
    if not tag_name:
        print("Tag name cannot be empty.")
        conn.close()
        return

    try:
        cursor.execute("""
            INSERT INTO directory_tags (directory_id, tag_name, source, created_at)
            VALUES (?, ?, 'manual', ?)
        """, (selected_dir_id, tag_name, datetime.datetime.now().isoformat()))
        conn.commit()
        print(f"\n[Success] Manual tag '{tag_name}' attached to '{selected_dir_name}'.")
    except sqlite3.IntegrityError:
        print(f"\n[Notice] Tag '{tag_name}' is already attached to this folder.")

    conn.close()

def list_all_tags(db_path: str):
    """Lists all detected Finder tags and manual tags across folders and files."""
    if not os.path.exists(db_path):
        print("\n[Notice] No database found. Run a scan first.")
        return

    conn = get_db_connection(db_path)
    cursor = conn.cursor()

    print("\n" + "=" * 65)
    print("DIRECTORY TAGS (Finder & Manual)")
    print("=" * 65)
    cursor.execute("""
        SELECT dt.tag_name, dt.source, d.name, d.path, h.hostname
        FROM directory_tags dt
        JOIN directories d ON dt.directory_id = d.id
        JOIN hosts h ON d.host_id = h.id
        ORDER BY dt.tag_name, d.name
    """)
    dir_rows = cursor.fetchall()
    if not dir_rows:
        print("No directory tags found.")
    else:
        for tag, source, folder, path, host in dir_rows:
            print(f"[{tag.upper()}] ({source}) -> [{host}] {folder} ({path})")

    print("\n" + "=" * 65)
    print("FILE TAGS (Finder Direct)")
    print("=" * 65)
    cursor.execute("""
        SELECT ft.tag_name, f.name, d.path, h.hostname
        FROM file_tags ft
        JOIN files f ON ft.file_id = f.id
        JOIN directories d ON f.directory_id = d.id
        JOIN hosts h ON d.host_id = h.id
        ORDER BY ft.tag_name, f.name
        LIMIT 30
    """)
    file_rows = cursor.fetchall()
    if not file_rows:
        print("No file tags found.")
    else:
        for tag, fname, path, host in file_rows:
            print(f"[{tag.upper()}] -> [{host}] {fname} ({path})")

    print("=" * 65)
    conn.close()

def search_files_by_tag(db_path: str):
    """Searches files by tag, matching both direct file tags and inherited directory tags."""
    if not os.path.exists(db_path):
        print("\n[Notice] No database found. Run a scan first.")
        return

    tag_query = input("\nEnter tag name to search (Finder or Manual): ").strip().lower()

    conn = get_db_connection(db_path)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT DISTINCT h.hostname, f.name, f.category, 
               (f.size_bytes / 1024.0 / 1024.0) AS size_mb,
               d.path, COALESCE(ft.tag_name, dt.tag_name) AS matched_tag,
               m.camera_model
        FROM files f
        JOIN directories d ON f.directory_id = d.id
        JOIN hosts h ON d.host_id = h.id
        LEFT JOIN file_tags ft ON f.id = ft.file_id
        LEFT JOIN directory_tags dt ON d.id = dt.directory_id
        LEFT JOIN media_metadata m ON f.id = m.file_id
        WHERE ft.tag_name LIKE ? OR dt.tag_name LIKE ?
        ORDER BY matched_tag, f.name
        LIMIT 30
    """, (f"%{tag_query}%", f"%{tag_query}%"))

    rows = cursor.fetchall()
    conn.close()

    print("\n" + "=" * 75)
    print(f"TAG MATCH RESULTS FOR '{tag_query}' (Showing up to 30)")
    print("=" * 75)

    if not rows:
        print("No matching files found.")
        return

    for host, name, category, size_mb, dir_path, tag, camera in rows:
        cam_info = f" | Camera: {camera}" if camera else ""
        print(f"[{host}] [{tag.upper()}] [{category.upper()}] {name} ({size_mb:.2f} MB){cam_info}")
        print(f"  Path: {dir_path}/{name}\n")

def main():
    db_file = "drive_audit.db"

    while True:
        print("\n" + "=" * 45)
        print("  DRIVE AUDIT & FINDER TAG MANAGER  ")
        print("=" * 45)
        print("1. Scan local directory (Sync Finder Tags)")
        print("2. View hosts & storage overview")
        print("3. List all active tags (Directory & File)")
        print("4. Add manual tag to a directory")
        print("5. Search files by tag (Finder & Manual)")
        print("6. Exit")

        choice = input("\nSelect option (1-6): ").strip()

        if choice == "1":
            audit_directory_interactive(db_file)
        elif choice == "2":
            show_hosts_summary(db_file)
        elif choice == "3":
            list_all_tags(db_file)
        elif choice == "4":
            add_manual_directory_tag(db_file)
        elif choice == "5":
            search_files_by_tag(db_file)
        elif choice == "6":
            print("\nExiting Drive Audit Manager. Goodbye!")
            break
        else:
            print("\n[Error] Invalid option.")

if __name__ == "__main__":
    main()