import os
import sys
import csv
import time
import shutil
import sqlite3
import datetime
import socket
import platform
import plistlib
import glob
import subprocess
import logging
from collections import deque, defaultdict, Counter
from pathlib import Path
try:
    import exifread
    logging.getLogger('exifread').setLevel(logging.ERROR)
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

# C-level Extended Attributes for macOS Finder Tagging
if platform.system() == "Darwin":
    try:
        import ctypes
        _libc = ctypes.cdll.LoadLibrary('libc.dylib')
        _setxattr = _libc.setxattr
        _setxattr.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_uint32, ctypes.c_int]
        _setxattr.restype = ctypes.c_int

        _getxattr = _libc.getxattr
        _getxattr.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_uint32, ctypes.c_int]
        _getxattr.restype = ctypes.c_ssize_t

        _removexattr = _libc.removexattr
        _removexattr.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_int]
        _removexattr.restype = ctypes.c_int
    except Exception:
        _libc = None
else:
    _libc = None

FINDER_COLOR_MAP = {
    0: "None",
    1: "Gray",
    2: "Green",
    3: "Purple",
    4: "Blue",
    5: "Yellow",
    6: "Red",
    7: "Orange",
}

FINDER_COLOR_EMOJI = {
    0: "⚪",
    1: "🩶",
    2: "🟢",
    3: "🟣",
    4: "🔵",
    5: "🟡",
    6: "🔴",
    7: "🟠",
}

PRIORITY_TIER_CONFIG = {
    "priority 1": {"tag": "Priority 1", "color": 6, "color_name": "Red"},
    "priority 2": {"tag": "Priority 2", "color": 4, "color_name": "Blue"},
    "priority 3": {"tag": "Priority 3", "color": 3, "color_name": "Purple"},
    "priority 4": {"tag": "Priority 4", "color": 5, "color_name": "Yellow"},
}

def set_finder_tags(file_or_dir_path: Path, tag_entries: list) -> bool:
    """Writes macOS Finder tags to extended attributes with optional color codes."""
    if platform.system() != "Darwin":
        return False
    try:
        raw_entries = []
        for entry in tag_entries:
            if isinstance(entry, tuple):
                name, color_idx = entry
                raw_entries.append(f"{name}\n{color_idx}")
            else:
                raw_entries.append(entry if "\n" in entry else f"{entry}\n0")

        raw_plist = plistlib.dumps(raw_entries, fmt=plistlib.FMT_BINARY)
        resolved_bytes = str(file_or_dir_path.resolve()).encode('utf-8')
        if _libc:
            ret = _setxattr(resolved_bytes, b'com.apple.metadata:_kMDItemUserTags', raw_plist, len(raw_plist), 0, 0)
            return ret == 0
        else:
            cmd = ["xattr", "-w", "-x", "com.apple.metadata:_kMDItemUserTags", raw_plist.hex(), str(file_or_dir_path.resolve())]
            res = subprocess.run(cmd, capture_output=True)
            return res.returncode == 0
    except Exception:
        return False

def remove_finder_tags(file_or_dir_path: Path) -> bool:
    """Removes macOS Finder tags from extended attributes."""
    if platform.system() != "Darwin":
        return False
    try:
        resolved_bytes = str(file_or_dir_path.resolve()).encode('utf-8')
        if _libc:
            ret = _removexattr(resolved_bytes, b'com.apple.metadata:_kMDItemUserTags', 0)
            return ret == 0
        else:
            cmd = ["xattr", "-d", "com.apple.metadata:_kMDItemUserTags", str(file_or_dir_path.resolve())]
            res = subprocess.run(cmd, capture_output=True)
            return res.returncode == 0
    except Exception:
        return False

def get_finder_tags(file_or_dir_path: Path) -> list:
    """Extracts macOS Finder tags from extended attributes (com.apple.metadata:_kMDItemUserTags)."""
    tags = []
    if platform.system() != "Darwin":
        return tags

    try:
        resolved_bytes = str(file_or_dir_path.resolve()).encode('utf-8')
        if _libc:
            buf_size = _getxattr(resolved_bytes, b'com.apple.metadata:_kMDItemUserTags', None, 0, 0, 0)
            if buf_size > 0:
                buf = ctypes.create_string_buffer(buf_size)
                _getxattr(resolved_bytes, b'com.apple.metadata:_kMDItemUserTags', buf, buf_size, 0, 0)
                plist_data = plistlib.loads(buf.raw)
                for tag_entry in plist_data:
                    tag_name = tag_entry.split('\n')[0].strip().lower()
                    if tag_name:
                        tags.append(tag_name)
                return tags

        cmd = ["xattr", "-p", "com.apple.metadata:_kMDItemUserTags", str(file_or_dir_path.resolve())]
        result = subprocess.run(cmd, capture_output=True)
        if result.returncode == 0 and result.stdout:
            hex_str = result.stdout.decode('utf-8').replace(" ", "").replace("\n", "")
            raw_data = bytes.fromhex(hex_str)
            plist_data = plistlib.loads(raw_data)
            for tag_entry in plist_data:
                tag_name = tag_entry.split('\n')[0].strip().lower()
                if tag_name:
                    tags.append(tag_name)
    except Exception:
        pass

    return tags

def get_finder_tags_with_details(file_or_dir_path: Path) -> list:
    """Extracts macOS Finder tags with raw color codes, color names, and emojis."""
    results = []
    if platform.system() != "Darwin":
        return results

    try:
        resolved_bytes = str(file_or_dir_path.resolve()).encode('utf-8')
        raw_plist = None
        if _libc:
            buf_size = _getxattr(resolved_bytes, b'com.apple.metadata:_kMDItemUserTags', None, 0, 0, 0)
            if buf_size > 0:
                buf = ctypes.create_string_buffer(buf_size)
                _getxattr(resolved_bytes, b'com.apple.metadata:_kMDItemUserTags', buf, buf_size, 0, 0)
                raw_plist = buf.raw

        if raw_plist is None:
            cmd = ["xattr", "-p", "com.apple.metadata:_kMDItemUserTags", str(file_or_dir_path.resolve())]
            res = subprocess.run(cmd, capture_output=True)
            if res.returncode == 0 and res.stdout:
                try:
                    raw_plist = res.stdout
                except Exception:
                    pass

        if raw_plist:
            plist_data = plistlib.loads(raw_plist) if isinstance(raw_plist, bytes) else raw_plist
            for entry in plist_data:
                parts = entry.split('\n')
                t_name = parts[0].strip()
                c_code = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
                results.append({
                    "name": t_name,
                    "color": c_code,
                    "color_name": FINDER_COLOR_MAP.get(c_code, "None"),
                    "emoji": FINDER_COLOR_EMOJI.get(c_code, "⚪")
                })
    except Exception:
        pass

    return results

def derive_folder_tags(folder_path: Path) -> list:
    """Derives Priority Tier tag (with Finder color) and Category tag based on directory path."""
    tags = []
    path_parts = folder_path.resolve().parts

    tier_found = None
    for part in path_parts:
        part_clean = part.strip().lower()
        if part_clean in PRIORITY_TIER_CONFIG:
            tier_info = PRIORITY_TIER_CONFIG[part_clean]
            tags.append((tier_info["tag"], tier_info["color"]))
            tier_found = part
            break

    if tier_found and tier_found in path_parts:
        tier_idx = path_parts.index(tier_found)
        if len(path_parts) > tier_idx + 1:
            category_name = path_parts[tier_idx + 1]
            tags.append((category_name, 0))

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
            description TEXT,
            FOREIGN KEY (host_id) REFERENCES hosts (id) ON DELETE CASCADE,
            UNIQUE(host_id, path)
        )
    """)
    cursor.execute("PRAGMA table_info(directories)")
    col_names = [col[1] for col in cursor.fetchall()]
    if "description" not in col_names:
        cursor.execute("ALTER TABLE directories ADD COLUMN description TEXT")
    if "is_verified" not in col_names:
        cursor.execute("ALTER TABLE directories ADD COLUMN is_verified INTEGER DEFAULT 0")
    if "verified_at" not in col_names:
        cursor.execute("ALTER TABLE directories ADD COLUMN verified_at TEXT")

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

    # 7. App Settings Table (Key-Value Store)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS app_settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    """)

    # 8. Priority Locations Table (Intermediary level mapping multiple folders per Priority tier)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS priority_locations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            priority_tier TEXT NOT NULL,
            path TEXT NOT NULL UNIQUE,
            label TEXT,
            description TEXT,
            is_active INTEGER DEFAULT 1,
            created_at TEXT NOT NULL
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_priority_locations_tier ON priority_locations(priority_tier);")

    # 9. Performance Indexes
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_files_name_size ON files(name, size_bytes);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_files_size ON files(size_bytes);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_directories_path ON directories(path);")

    conn.commit()
    return conn

def get_app_setting(db_path: str, key: str) -> str | None:
    """Retrieves a persisted application setting from the database."""
    if not os.path.exists(db_path):
        return None
    try:
        conn = get_db_connection(db_path)
        cursor = conn.cursor()
        cursor.execute("CREATE TABLE IF NOT EXISTS app_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        cursor.execute("SELECT value FROM app_settings WHERE key = ?", (key,))
        row = cursor.fetchone()
        if row and row[0]:
            conn.close()
            return row[0]
        # Fallback for last_scanned_dir to most recent directory scan if not set
        if key == "last_scanned_dir":
            cursor.execute("SELECT path FROM directories ORDER BY scanned_at DESC LIMIT 1")
            dir_row = cursor.fetchone()
            conn.close()
            return dir_row[0] if dir_row else None
        conn.close()
        return None
    except Exception:
        return None

def set_app_setting(db_path: str, key: str, value: str):
    """Saves a persisted application setting into the database."""
    try:
        conn = get_db_connection(db_path)
        cursor = conn.cursor()
        cursor.execute("CREATE TABLE IF NOT EXISTS app_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        cursor.execute("""
            INSERT INTO app_settings (key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value=excluded.value
        """, (key, value))
        conn.commit()
        conn.close()
    except Exception:
        pass

def get_or_create_host(cursor: sqlite3.Cursor) -> int:
    """Detects current desktop host details and returns its database ID."""
    if platform.system() == "Darwin":
        try:
            local_name = subprocess.check_output(["scutil", "--get", "LocalHostName"], timeout=2).decode().strip()
            hostname = f"{local_name}.local" if local_name else socket.gethostname()
        except Exception:
            hostname = socket.gethostname()
    else:
        hostname = socket.gethostname()

    os_name = platform.system()
    scan_time = datetime.datetime.now().isoformat()

    try:
        ip_address = socket.gethostbyname(socket.gethostname())
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

def get_finder_folder_size(folder_path: Path) -> int | None:
    """Queries macOS Finder for the cached folder size in bytes before scanning."""
    if platform.system() != "Darwin":
        return None
    try:
        resolved = str(folder_path.resolve())
        cmd = [
            "osascript", "-e",
            f'tell application "Finder" to get size of (POSIX file "{resolved}" as alias)'
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=3.0)
        if result.returncode == 0 and result.stdout.strip():
            raw_val = result.stdout.strip()
            if raw_val and raw_val != "missing value":
                return int(float(raw_val))
    except Exception:
        pass
    return None

class ScanProgressTracker:
    """Tracks scan throughput, progress percentage, and calculates a stable ETA based on total size and processing speed."""
    def __init__(self, total_target_bytes: int | None = None):
        self.total_target_bytes = total_target_bytes
        self.start_time = time.time()
        self.cached_bytes = 0
        self.fresh_bytes = 0
        self.fresh_files = 0
        self.fresh_start_time = None
        self.history = deque()  # stores (timestamp, fresh_bytes, total_processed_bytes)
        self.smoothed_eta_sec = None
        self.smoothed_speed = None

    def add_cached(self, byte_count: int):
        self.cached_bytes += byte_count

    def add_fresh_file(self, byte_count: int):
        if self.fresh_start_time is None:
            self.fresh_start_time = time.time()
        self.fresh_bytes += byte_count
        self.fresh_files += 1

    def get_progress_info(self):
        now = time.time()
        elapsed = max(0.01, now - self.start_time)
        mins, secs = divmod(int(elapsed), 60)
        hours, mins = divmod(mins, 60)
        elapsed_str = f"{hours:02d}:{mins:02d}:{secs:02d}" if hours > 0 else f"{mins:02d}:{secs:02d}"

        total_processed_bytes = self.cached_bytes + self.fresh_bytes

        # Sliding window history over the last 15 seconds
        self.history.append((now, self.fresh_bytes, total_processed_bytes))
        while len(self.history) > 1 and (now - self.history[0][0]) > 15.0:
            self.history.popleft()

        oldest_time, oldest_fresh, oldest_total = self.history[0]
        dt = now - oldest_time

        # 1. Disk Throughput (measured on fresh files read from disk)
        if dt >= 1.5 and self.fresh_bytes > oldest_fresh:
            window_fresh_speed = (self.fresh_bytes - oldest_fresh) / dt
        else:
            window_fresh_speed = 0.0

        if self.fresh_start_time is not None:
            fresh_elapsed = max(0.1, now - self.fresh_start_time)
            cum_fresh_speed = self.fresh_bytes / fresh_elapsed
        else:
            cum_fresh_speed = 0.0

        # Effective fresh disk speed (blends 15s window with cumulative fresh rate)
        if window_fresh_speed > 0 and cum_fresh_speed > 0:
            eff_fresh_speed = 0.60 * window_fresh_speed + 0.40 * cum_fresh_speed
        elif cum_fresh_speed > 0:
            eff_fresh_speed = cum_fresh_speed
        elif window_fresh_speed > 0:
            eff_fresh_speed = window_fresh_speed
        else:
            eff_fresh_speed = 0.0

        # Overall throughput for display (smooth EMA)
        if eff_fresh_speed > 0:
            if self.smoothed_speed is None:
                self.smoothed_speed = eff_fresh_speed
            else:
                self.smoothed_speed = 0.85 * self.smoothed_speed + 0.15 * eff_fresh_speed
        elif self.cached_bytes > 0 and self.fresh_bytes == 0:
            # Pure cache scan
            self.smoothed_speed = total_processed_bytes / elapsed

        display_speed = max(self.smoothed_speed or 0.0, 0.0)
        speed_str = f"{format_size(int(display_speed))}/s" if display_speed > 0 else "--/s"

        eta_label = ""
        pct_label = ""

        if self.total_target_bytes and self.total_target_bytes > 0:
            eff_total = max(self.total_target_bytes, total_processed_bytes)
            pct = min(99.9, (total_processed_bytes / eff_total) * 100) if total_processed_bytes < eff_total else 100.0
            pct_label = f"{pct:.1f}%"

            remaining_bytes = max(0, eff_total - total_processed_bytes)

            if remaining_bytes == 0:
                eta_label = "finishing..."
            elif elapsed < 2.0 and self.fresh_files < 5:
                eta_label = "calculating ETA..."
            else:
                # Direct mathematical calculation based on disk throughput & cumulative pace
                if eff_fresh_speed > 1024:
                    raw_eta = remaining_bytes / eff_fresh_speed
                elif self.cached_bytes > 0 and self.fresh_bytes == 0:
                    pace = total_processed_bytes / elapsed
                    raw_eta = remaining_bytes / max(pace, 1)
                else:
                    pace = total_processed_bytes / elapsed
                    raw_eta = remaining_bytes / max(pace, 1)

                # Exponential smoothing to prevent clock jitter
                if self.smoothed_eta_sec is None:
                    self.smoothed_eta_sec = raw_eta
                else:
                    self.smoothed_eta_sec = 0.90 * self.smoothed_eta_sec + 0.10 * raw_eta

                finish_dt = datetime.datetime.now() + datetime.timedelta(seconds=self.smoothed_eta_sec)
                now_dt = datetime.datetime.now()

                # Remaining duration string
                rem_s = int(self.smoothed_eta_sec)
                if rem_s < 60:
                    dur_str = f"{rem_s}s"
                elif rem_s < 3600:
                    dur_str = f"{rem_s // 60}m {rem_s % 60:02d}s"
                else:
                    dur_str = f"{rem_s // 3600}h {(rem_s % 3600) // 60}m"

                # Completion clock time formatting
                if finish_dt.date() == now_dt.date():
                    eta_clock = finish_dt.strftime("%I:%M:%S %p").lstrip("0")
                elif finish_dt.date() == (now_dt + datetime.timedelta(days=1)).date():
                    eta_clock = "Tomorrow " + finish_dt.strftime("%I:%M %p").lstrip("0")
                elif (finish_dt - now_dt).days < 7:
                    eta_clock = finish_dt.strftime("%a %I:%M %p").lstrip("0")
                else:
                    eta_clock = finish_dt.strftime("%b %d %I:%M %p").lstrip("0")

                cols = shutil.get_terminal_size((80, 20)).columns
                if cols >= 115:
                    eta_label = f"ETA: {eta_clock} (~{dur_str})"
                else:
                    eta_label = f"ETA: {eta_clock}"

        return elapsed_str, speed_str, pct_label, eta_label, total_processed_bytes

def update_scan_progress(scanned_dirs: int, scanned_files: int, skipped_dirs: int, skipped_files: int, current_path: str, tracker: ScanProgressTracker):
    """Prints a single-line live progress indicator with ETA, percentage, and current speed."""
    elapsed_str, speed_str, pct_label, eta_label, total_bytes = tracker.get_progress_info()
    cols = shutil.get_terminal_size((80, 20)).columns
    skip_str = f" ({skipped_dirs:,} cached)" if skipped_dirs > 0 else ""

    total_files = scanned_files + skipped_files
    size_str = format_size(total_bytes)

    if tracker.total_target_bytes and tracker.total_target_bytes > 0:
        target_str = format_size(tracker.total_target_bytes)
        metric_info = f"{size_str}/{target_str} @ {speed_str}"
        if eta_label:
            status_tag = f"{elapsed_str} | {eta_label} | {pct_label}"
        else:
            status_tag = f"{elapsed_str} | {pct_label}"
    else:
        metric_info = f"{size_str} @ {speed_str}"
        status_tag = f"{elapsed_str} | {speed_str}"

    base_info = f"⏳ [{status_tag}] {scanned_dirs:,} dirs{skip_str} | {total_files:,} files ({metric_info}) -> "
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
    last_dir = get_app_setting(db_path, "last_scanned_dir")

    if last_dir and os.path.exists(last_dir):
        prompt_msg = f"Enter path to scan [Default: {last_dir}]: "
    else:
        prompt_msg = "Enter path to scan (e.g., ./ or /Users/name/Pictures): "

    target_input = input(prompt_msg).strip().strip('"').strip("'")
    if not target_input and last_dir and os.path.exists(last_dir):
        target_path = last_dir
    else:
        target_path = target_input

    root = Path(target_path)

    if not root.exists():
        print(f"\n[Error] Path '{target_path}' does not exist.")
        return

    # Save last scanned path for future suggestion
    set_app_setting(db_path, "last_scanned_dir", str(root.resolve()))

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

    # Query macOS Finder for cached folder size to provide ETA
    total_target_bytes = get_finder_folder_size(root)
    
    # Fallback to previous scan size from database if Finder did not return a cached size
    if not total_target_bytes:
        resolved_root_str = str(root.resolve())
        cursor.execute("""
            SELECT SUM(f.size_bytes)
            FROM files f
            JOIN directories d ON f.directory_id = d.id
            WHERE d.host_id = ? AND (d.path = ? OR d.path LIKE ? || '/%')
        """, (host_id, resolved_root_str, resolved_root_str))
        db_size_row = cursor.fetchone()
        if db_size_row and db_size_row[0] and db_size_row[0] > 0:
            total_target_bytes = db_size_row[0]

    tracker = ScanProgressTracker(total_target_bytes)

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

    size_estimate_msg = f" (Target size: ~{format_size(total_target_bytes)})" if total_target_bytes else ""
    skip_msg = f"(skipping folders scanned < {skip_hours:g}h ago)" if skip_hours > 0 else "(full rescan)"
    print(f"\nScanning: {root.resolve()} on host [{hostname}]{size_estimate_msg} {skip_msg} ... (Press Ctrl+C to stop)")

    scanned_files = 0
    scanned_dirs = 0
    skipped_dirs = 0
    skipped_files = 0
    purged_files = 0
    purged_dirs = 0
    dir_tags_count = 0
    file_tags_count = 0
    visited_dir_paths = set()

    last_progress_time = 0.0
    last_commit_time = time.time()

    try:
        for dirpath, _, filenames in os.walk(root):
            dir_obj = Path(dirpath)
            if not dir_obj.exists():
                continue

            try:
                resolved_path = str(dir_obj.resolve())
                visited_dir_paths.add(resolved_path)
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
                            tracker.add_cached(cached["total_bytes"])
                            
                            now = time.time()
                            if now - last_progress_time >= 0.1:
                                update_scan_progress(scanned_dirs, scanned_files, skipped_dirs, skipped_files, resolved_path, tracker)
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

                # 2. Reconcile deleted files in this directory
                current_filenames = set(filenames)
                cursor.execute("SELECT id, name FROM files WHERE directory_id = ?", (directory_id,))
                db_file_map = {row[1]: row[0] for row in cursor.fetchall()}
                for del_name in (set(db_file_map.keys()) - current_filenames):
                    cursor.execute("DELETE FROM files WHERE id = ?", (db_file_map[del_name],))
                    purged_files += 1

                # 3. Process Files inside Directory
                for filename in filenames:
                    file_path = dir_obj / filename
                    if not file_path.exists():
                        continue

                    try:
                        stat = file_path.stat()
                        ext = file_path.suffix.lower()
                        category = get_file_category(ext)
                        file_size = stat.st_size
                        tracker.add_fresh_file(file_size)

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
                        update_scan_progress(scanned_dirs, scanned_files, skipped_dirs, skipped_files, resolved_path, tracker)
                        last_progress_time = now

                    # Periodic commit every 2 seconds
                    if now - last_commit_time >= 2.0:
                        conn.commit()
                        last_commit_time = now

                # Progress update after directory completion
                now = time.time()
                if now - last_progress_time >= 0.1:
                    update_scan_progress(scanned_dirs, scanned_files, skipped_dirs, skipped_files, resolved_path, tracker)
                    last_progress_time = now

            except PermissionError:
                continue

        # 4. Reconcile deleted subdirectories under the scanned root
        resolved_root = str(root.resolve())
        cursor.execute("""
            SELECT id, path FROM directories
            WHERE host_id = ? AND (path = ? OR path LIKE ? || '/%')
        """, (host_id, resolved_root, resolved_root))
        for d_id, d_path in cursor.fetchall():
            if d_path not in visited_dir_paths:
                cursor.execute("SELECT COUNT(*) FROM files WHERE directory_id = ?", (d_id,))
                purged_files += cursor.fetchone()[0]
                cursor.execute("DELETE FROM directories WHERE id = ?", (d_id,))
                purged_dirs += 1

    except KeyboardInterrupt:
        conn.commit()
        conn.close()
        sys.stdout.write("\r\033[K")
        sys.stdout.flush()
        total_bytes = tracker.cached_bytes + tracker.fresh_bytes
        print(f"\n[Scan Interrupted] Stopped by user.")
        print(f"  • Processed: {scanned_dirs:,} folders ({skipped_dirs:,} cached), {scanned_files + skipped_files:,} files ({format_size(total_bytes)}).")
        return

    conn.commit()
    conn.close()
    sys.stdout.write("\r\033[K")
    sys.stdout.flush()

    elapsed = time.time() - tracker.start_time
    mins, secs = divmod(int(elapsed), 60)
    time_str = f"{mins}m {secs}s" if mins > 0 else f"{elapsed:.1f}s"
    total_bytes = tracker.cached_bytes + tracker.fresh_bytes

    print(f"\n[Success] Audit complete in {time_str}!")
    print(f"  • Host:            {hostname}")
    print(f"  • Root scanned:    {root.resolve()}")
    if skipped_dirs > 0:
        print(f"  • Folders indexed: {scanned_dirs:,} scanned ({skipped_dirs:,} skipped — scanned < {skip_hours:g}h ago)")
        print(f"  • Files indexed:   {scanned_files:,} scanned ({skipped_files:,} verified from cache)")
    else:
        print(f"  • Folders indexed: {scanned_dirs:,} ({dir_tags_count:,} Finder tags)")
        print(f"  • Files indexed:   {scanned_files:,} ({file_tags_count:,} Finder tags)")
    if purged_dirs > 0 or purged_files > 0:
        print(f"  • Purged deleted:  {purged_dirs:,} folders, {purged_files:,} files removed from database")
    print(f"  • Total storage:   {format_size(total_bytes)}")



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
    print("=" * 75)

    bench_prompt = input("\nRun live drive performance & I/O benchmark across mounted volumes? (y/N): ").strip().lower()
    if bench_prompt == 'y':
        try:
            import benchmark_drives
            benchmark_drives.run_benchmark_interactive()
        except ImportError:
            print("\n[Notice] benchmark_drives.py not found in working directory.")

def generate_top_level_scans_report(db_path: str):
    """Generates a detailed breakdown report for each top-level scanned root folder."""
    if not os.path.exists(db_path):
        print("\n[Notice] No database found. Run a scan first.")
        return

    conn = get_db_connection(db_path)
    cursor = conn.cursor()

    # Identify top-level roots (directories with no parent directory recorded for that host)
    query_roots = """
        SELECT d.id, d.path, d.name, d.scanned_at, h.hostname, h.id
        FROM directories d
        JOIN hosts h ON d.host_id = h.id
        WHERE NOT EXISTS (
            SELECT 1 FROM directories parent
            WHERE parent.host_id = d.host_id
              AND parent.id != d.id
              AND d.path LIKE parent.path || '/%'
        )
        ORDER BY d.path;
    """
    cursor.execute(query_roots)
    roots = cursor.fetchall()

    if not roots:
        print("\nNo scanned folders found in database.")
        conn.close()
        return

    print("\n" + "=" * 90)
    print(f"TOP-LEVEL SCANNED FOLDERS REPORT ({len(roots)} root scans found)")
    print("=" * 90)

    report_data = []

    for idx, (rid, rpath, rname, rscanned, rhost, hid) in enumerate(roots, 1):
        # 1. Total statistics for this root tree
        cursor.execute("""
            SELECT 
                COUNT(DISTINCT child.id) as total_dirs,
                COUNT(f.id) as total_files,
                COALESCE(SUM(f.size_bytes), 0) as total_bytes
            FROM directories child
            LEFT JOIN files f ON f.directory_id = child.id
            WHERE child.host_id = ?
              AND (child.path = ? OR child.path LIKE ? || '/%')
        """, (hid, rpath, rpath))
        tree_dirs, tree_files, tree_bytes = cursor.fetchone()

        # 2. Category breakdown
        cursor.execute("""
            SELECT f.category, COUNT(f.id), COALESCE(SUM(f.size_bytes), 0)
            FROM directories child
            JOIN files f ON f.directory_id = child.id
            WHERE child.host_id = ?
              AND (child.path = ? OR child.path LIKE ? || '/%')
            GROUP BY f.category
            ORDER BY SUM(f.size_bytes) DESC
        """, (hid, rpath, rpath))
        categories = cursor.fetchall()
        cat_str_list = [f"{cat}: {cnt:,} ({format_size(sz)})" for cat, cnt, sz in categories]
        cat_summary = " | ".join(cat_str_list) if cat_str_list else "None"

        # 3. Direct immediate subfolders
        cursor.execute("""
            SELECT d.name,
                   (SELECT COUNT(f.id) FROM directories sub JOIN files f ON f.directory_id = sub.id WHERE sub.host_id = d.host_id AND (sub.path = d.path OR sub.path LIKE d.path || '/%')) as sub_files,
                   (SELECT COALESCE(SUM(f.size_bytes), 0) FROM directories sub JOIN files f ON f.directory_id = sub.id WHERE sub.host_id = d.host_id AND (sub.path = d.path OR sub.path LIKE d.path || '/%')) as sub_bytes
            FROM directories d
            WHERE d.host_id = ?
              AND d.path LIKE ? || '/%'
              AND d.path NOT LIKE ? || '/%/%'
            ORDER BY sub_bytes DESC
            LIMIT 5
        """, (hid, rpath, rpath))
        top_subdirs = cursor.fetchall()

        scan_time_str = rscanned.replace("T", " ")[:19] if rscanned else "N/A"
        size_str = format_size(tree_bytes)

        print(f"[{idx}] {rpath}")
        print(f"    • Host:            {rhost}")
        print(f"    • Last Scanned:    {scan_time_str}")
        print(f"    • Subdirectories:  {tree_dirs:,} folders")
        print(f"    • Total Files:     {tree_files:,} files")
        print(f"    • Total Storage:   {size_str}")
        print(f"    • Category Types:  {cat_summary}")

        if top_subdirs:
            print("    • Top Direct Subfolders:")
            for sname, sfiles, sbytes in top_subdirs:
                print(f"        - {sname}: {format_size(sbytes)} ({sfiles:,} files)")
        print()

        report_data.append({
            "rank": idx,
            "path": rpath,
            "name": rname,
            "host": rhost,
            "scanned_at": scan_time_str,
            "total_dirs": tree_dirs,
            "total_files": tree_files,
            "total_bytes": tree_bytes,
            "total_size_str": size_str,
            "categories": cat_summary,
            "top_subdirs": "; ".join([f"{sn} ({format_size(sb)}, {sf} files)" for sn, sf, sb in top_subdirs])
        })

    print("=" * 90)
    conn.close()

    # Optional export to CSV or Markdown
    export_choice = input("Export report to file? (c = CSV, m = Markdown, n = No) [Default: n]: ").strip().lower()
    if export_choice == "c":
        filename = "top_level_scans_report.csv"
        try:
            with open(filename, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(["Rank", "Root Path", "Folder Name", "Host", "Last Scanned At", "Total Folders", "Total Files", "Total Bytes", "Formatted Size", "Category Breakdown", "Top Subfolders"])
                for item in report_data:
                    writer.writerow([item["rank"], item["path"], item["name"], item["host"], item["scanned_at"], item["total_dirs"], item["total_files"], item["total_bytes"], item["total_size_str"], item["categories"], item["top_subdirs"]])
            print(f"[Success] Report exported to: {os.path.abspath(filename)}")
        except Exception as e:
            print(f"[Error] Failed to export CSV: {e}")

    elif export_choice == "m":
        filename = "top_level_scans_report.md"
        try:
            with open(filename, "w", encoding="utf-8") as f:
                f.write(f"# Top-Level Scanned Folders Report\n\n")
                f.write(f"**Generated**: `{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`\n\n")
                f.write("| # | Root Path | Host | Total Size | Files | Folders | Last Scanned | Categories |\n")
                f.write("|---|---|---|---|---|---|---|---|\n")
                for item in report_data:
                    f.write(f"| {item['rank']} | `{item['path']}` | {item['host']} | **{item['total_size_str']}** | {item['total_files']:,} | {item['total_dirs']:,} | {item['scanned_at']} | {item['categories']} |\n")
            print(f"[Success] Report exported to: {os.path.abspath(filename)}")
        except Exception as e:
            print(f"[Error] Failed to export Markdown: {e}")


def generate_largest_files_report(db_path: str):
    """Generates a detailed report of the largest indexed files, with optional category filter and file export."""
    if not os.path.exists(db_path):
        print("\n[Notice] No database found. Run a scan first.")
        return

    print("\n--- LARGEST FILES REPORT ---")
    limit_input = input("How many files to show? [Default: 25]: ").strip()
    try:
        limit = int(limit_input) if limit_input else 25
    except ValueError:
        limit = 25

    cat_input = input("Filter by category (image/video/audio/document/archive/code/other, or Enter for all): ").strip().lower()

    conn = get_db_connection(db_path)
    cursor = conn.cursor()

    if cat_input and (cat_input in EXTENSION_MAP or cat_input == "other"):
        query = """
            SELECT 
                f.name, f.category, f.size_bytes, f.created_at, f.modified_at,
                d.path, h.hostname
            FROM files f
            JOIN directories d ON f.directory_id = d.id
            JOIN hosts h ON d.host_id = h.id
            WHERE f.category = ?
            ORDER BY f.size_bytes DESC
            LIMIT ?
        """
        cursor.execute(query, (cat_input, limit))
    else:
        query = """
            SELECT 
                f.name, f.category, f.size_bytes, f.created_at, f.modified_at,
                d.path, h.hostname
            FROM files f
            JOIN directories d ON f.directory_id = d.id
            JOIN hosts h ON d.host_id = h.id
            ORDER BY f.size_bytes DESC
            LIMIT ?
        """
        cursor.execute(query, (limit,))

    rows = cursor.fetchall()
    conn.close()

    if not rows:
        print("\nNo files found matching criteria.")
        return

    print("\n" + "=" * 90)
    filter_label = f" (Category: {cat_input.upper()})" if cat_input else ""
    print(f"TOP {len(rows)} LARGEST FILES{filter_label}")
    print("=" * 90)

    for idx, (name, category, size_bytes, created_at, modified_at, dir_path, host) in enumerate(rows, 1):
        size_str = format_size(size_bytes)
        mod_date = modified_at.replace("T", " ")[:19] if modified_at else "N/A"
        cre_date = created_at.replace("T", " ")[:19] if created_at else "N/A"
        print(f"{idx:>3}. [{size_str:>9}] [{category.upper():<8}] {name}")
        print(f"     Modified: {mod_date} | Created: {cre_date} | Host: {host}")
        print(f"     Path: {dir_path}/{name}\n")

    print("=" * 90)

    # Optional export to CSV or Markdown
    export_choice = input("Export report to file? (c = CSV, m = Markdown, n = No) [Default: n]: ").strip().lower()
    if export_choice == "c":
        filename = "largest_files_report.csv"
        try:
            with open(filename, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(["Rank", "Hostname", "File Name", "Category", "Size Bytes", "Size Formatted", "Modified At", "Created At", "Directory Path", "Full Path"])
                for idx, (name, category, size_bytes, created_at, modified_at, dir_path, host) in enumerate(rows, 1):
                    writer.writerow([idx, host, name, category, size_bytes, format_size(size_bytes), modified_at or "", created_at or "", dir_path, f"{dir_path}/{name}"])
            print(f"[Success] Report exported to: {os.path.abspath(filename)}")
        except Exception as e:
            print(f"[Error] Failed to export CSV: {e}")

    elif export_choice == "m":
        filename = "largest_files_report.md"
        try:
            with open(filename, "w", encoding="utf-8") as f:
                f.write(f"# Top {len(rows)} Largest Files Report\n\n")
                if cat_input:
                    f.write(f"**Category Filter**: `{cat_input}`\n\n")
                f.write(f"**Generated**: `{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`\n\n")
                f.write("| # | File Name | Category | Size | Modified Date | Created Date | Path |\n")
                f.write("|---|---|---|---|---|---|---|\n")
                for idx, (name, category, size_bytes, created_at, modified_at, dir_path, host) in enumerate(rows, 1):
                    mod_str = modified_at.replace('T', ' ')[:19] if modified_at else 'N/A'
                    cre_str = created_at.replace('T', ' ')[:19] if created_at else 'N/A'
                    f.write(f"| {idx} | `{name}` | `{category}` | **{format_size(size_bytes)}** | {mod_str} | {cre_str} | `{dir_path}/{name}` |\n")
            print(f"[Success] Report exported to: {os.path.abspath(filename)}")
        except Exception as e:
            print(f"[Error] Failed to export Markdown: {e}")


def generate_curation_verification_report(db_path: str):
    """
    Generates a comprehensive verification status report separating Approved/Verified
    folders and files from Unapproved/Pending folders and files across storage locations.
    """
    if not os.path.exists(db_path):
        print("\n[Notice] No database found. Run a scan first.")
        return

    conn = get_db_connection(db_path)
    cursor = conn.cursor()

    while True:
        # 1. Fetch Global Summary across all indexed data
        cursor.execute("SELECT COUNT(id), COALESCE(SUM(size_bytes), 0) FROM files")
        tot_files_row = cursor.fetchone()
        total_files = tot_files_row[0] or 0
        total_bytes = tot_files_row[1] or 0

        cursor.execute("SELECT COUNT(id) FROM directories")
        total_folders = cursor.fetchone()[0] or 0

        cursor.execute("SELECT COUNT(id) FROM directories WHERE is_verified = 1")
        verified_folders = cursor.fetchone()[0] or 0
        unverified_folders = total_folders - verified_folders

        cursor.execute("""
            SELECT COUNT(f.id), COALESCE(SUM(f.size_bytes), 0)
            FROM files f
            JOIN directories d ON f.directory_id = d.id
            WHERE d.is_verified = 1
               OR EXISTS (SELECT 1 FROM directories p WHERE p.is_verified = 1 AND d.path LIKE p.path || '/%')
        """)
        ver_stats = cursor.fetchone()
        verified_files = ver_stats[0] or 0
        verified_bytes = ver_stats[1] or 0
        unverified_files = max(0, total_files - verified_files)
        unverified_bytes = max(0, total_bytes - verified_bytes)

        pct_folders = (verified_folders / total_folders * 100) if total_folders > 0 else 0
        pct_files = (verified_files / total_files * 100) if total_files > 0 else 0
        pct_bytes = (verified_bytes / total_bytes * 100) if total_bytes > 0 else 0

        bar_len = 30
        filled_len = int(round(bar_len * pct_folders / 100))
        prog_bar = "█" * filled_len + "░" * (bar_len - filled_len)

        # 2. Fetch Priority Locations Breakdown
        cursor.execute("""
            SELECT 
                pl.id,
                pl.priority_tier,
                pl.label,
                pl.path,
                COUNT(DISTINCT d.id) as tot_f,
                COUNT(DISTINCT CASE WHEN d.is_verified = 1 THEN d.id END) as v_f,
                COUNT(f.id) as tot_files,
                COALESCE(SUM(f.size_bytes), 0) as tot_b,
                COUNT(CASE WHEN d.is_verified = 1 OR EXISTS (SELECT 1 FROM directories p WHERE p.is_verified = 1 AND d.path LIKE p.path || '/%') THEN f.id END) as v_files,
                COALESCE(SUM(CASE WHEN d.is_verified = 1 OR EXISTS (SELECT 1 FROM directories p WHERE p.is_verified = 1 AND d.path LIKE p.path || '/%') THEN f.size_bytes ELSE 0 END), 0) as v_b
            FROM priority_locations pl
            JOIN directories d ON (d.path = pl.path OR d.path LIKE pl.path || '/%')
            LEFT JOIN files f ON f.directory_id = d.id
            WHERE pl.is_active = 1
            GROUP BY pl.id
            ORDER BY pl.priority_tier, pl.id
        """)
        loc_rows = cursor.fetchall()

        print("\n" + "=" * 96)
        print("             STORAGE CURATION & VERIFICATION STATUS REPORT             ")
        print("               (Separated Approved vs. Unapproved Inventory)           ")
        print("=" * 96)
        print(f"  Overall Progress : [{prog_bar}] {pct_folders:.1f}% Folders Approved")
        print(f"  • Approved       : {verified_folders:,} Folders | {verified_files:,} Files | {format_size(verified_bytes)}")
        print(f"  • Unapproved     : {unverified_folders:,} Folders | {unverified_files:,} Files | {format_size(unverified_bytes)}")
        print(f"  • Total Database : {total_folders:,} Folders | {total_files:,} Files | {format_size(total_bytes)}")
        print("-" * 96)
        print(f"{'Priority Tier / Location':<36} | {'Approved Folders':<18} | {'Approved Size':<15} | {'Pending Unapproved'}")
        print("-" * 96)

        for pl_id, p_tier, p_lbl, p_path, tot_f, v_f, tot_files_loc, tot_b_loc, v_files_loc, v_b_loc in loc_rows:
            loc_pct = (v_f / tot_f * 100) if tot_f > 0 else 0
            tier_badge = f"{p_tier.title()} ({p_lbl})"
            app_str = f"{v_f:,} / {tot_f:,} ({loc_pct:.1f}%)"
            app_sz = format_size(v_b_loc)
            u_f = tot_f - v_f
            u_b = tot_b_loc - v_b_loc
            unapp_str = f"{u_f:,} folders ({format_size(u_b)})"
            print(f"{tier_badge:<36} | {app_str:<18} | {app_sz:<15} | {unapp_str}")

        print("=" * 96)
        print("\nOptions:")
        print("  1. List Approved Folders (is_verified = 1) — [Enter # to inspect folder details & files]")
        print("  2. List All Approved Files (Detailed file-by-file inventory)")
        print("  3. List Unapproved Category Folders (is_verified = 0) — [Enter # to inspect pending files]")
        print("  4. Filter Approved / Unapproved by Priority Tier (P1, P2, P3, P4)")
        print("  5. Export Full Report (Markdown / CSV with file inventory)")
        print("  6. Return to previous menu")

        rep_choice = input("\nSelect report option (1-6): ").strip()

        if rep_choice == "6":
            break

        elif rep_choice == "1":
            # List Approved Folders with Subtree Totals & drilldown
            cursor.execute("""
                SELECT 
                    d.id,
                    d.name,
                    d.path,
                    d.verified_at,
                    d.description,
                    (SELECT COUNT(f.id) FROM directories sub JOIN files f ON f.directory_id = sub.id WHERE sub.id = d.id OR sub.path LIKE d.path || '/%') AS subtree_files,
                    (SELECT COALESCE(SUM(f.size_bytes), 0) FROM directories sub JOIN files f ON f.directory_id = sub.id WHERE sub.id = d.id OR sub.path LIKE d.path || '/%') AS subtree_bytes,
                    (SELECT COUNT(f.id) FROM files f WHERE f.directory_id = d.id) AS direct_files,
                    (SELECT COALESCE(SUM(f.size_bytes), 0) FROM files f WHERE f.directory_id = d.id) AS direct_bytes,
                    COALESCE(GROUP_CONCAT(DISTINCT dt.tag_name), '-') as tags
                FROM directories d
                LEFT JOIN directory_tags dt ON d.id = dt.directory_id
                WHERE d.is_verified = 1
                GROUP BY d.id
                ORDER BY d.path
            """)
            v_rows = cursor.fetchall()
            print("\n" + "=" * 98)
            print(f"APPROVED / VERIFIED FOLDERS ({len(v_rows)} folders)")
            print("=" * 98)
            print(f"{'#':<4} {'Folder Name':<28} {'Subtree Files / Size':<26} {'Verified Date':<20} {'Tags'}")
            print("-" * 98)
            for idx, (did, dname, dpath, v_at, ddesc, sub_cnt, sub_b, dir_cnt, dir_b, dtags) in enumerate(v_rows, 1):
                v_date_str = v_at.replace("T", " ")[:19] if v_at else "N/A"
                if sub_cnt > 0:
                    stat_str = f"{sub_cnt:,} files ({format_size(sub_b)})"
                elif os.path.exists(dpath):
                    try:
                        disk_files = sum(len(fls) for _, _, fls in os.walk(dpath))
                        stat_str = f"⚠️ Unindexed ({disk_files:,} on disk)" if disk_files > 0 else "0 files (0 B)"
                    except Exception:
                        stat_str = "0 files (0 B)"
                else:
                    stat_str = "0 files (0 B)"
                print(f"{idx:<4} {dname:<28} {stat_str:<26} {v_date_str:<20} {dtags}")
                print(f"     📍 Path: {dpath}")
                if ddesc:
                    print(f"     ↳ 📝 \"{ddesc}\"")
            print("=" * 98)

            while True:
                f_drill = input("\nEnter folder # (1-N) to view contained files & details, or Enter to return: ").strip().lower()
                if not f_drill:
                    break
                if f_drill.isdigit():
                    f_idx = int(f_drill) - 1
                    if 0 <= f_idx < len(v_rows):
                        did, dname, dpath, v_at, ddesc, sub_cnt, sub_b, dir_cnt, dir_b, dtags = v_rows[f_idx]
                        
                        # Category breakdown across folder subtree
                        cursor.execute("""
                            SELECT f.category, COUNT(f.id), SUM(f.size_bytes)
                            FROM directories sub
                            JOIN files f ON f.directory_id = sub.id
                            WHERE sub.id = ? OR sub.path LIKE ? || '/%'
                            GROUP BY f.category
                            ORDER BY SUM(f.size_bytes) DESC
                        """, (did, dpath))
                        cat_breakdown = cursor.fetchall()
                        cat_str = " | ".join([f"{c}: {cnt:,} ({format_size(sb)})" for c, cnt, sb in cat_breakdown]) if cat_breakdown else "No indexed files"

                        # Fetch files in subtree (up to 100)
                        cursor.execute("""
                            SELECT f.name, f.category, f.extension, f.size_bytes, f.modified_at, sub.name as sub_folder
                            FROM directories sub
                            JOIN files f ON f.directory_id = sub.id
                            WHERE sub.id = ? OR sub.path LIKE ? || '/%'
                            ORDER BY f.size_bytes DESC
                            LIMIT 100
                        """, (did, dpath))
                        dir_files = cursor.fetchall()

                        v_date_str = v_at.replace("T", " ")[:19] if v_at else "N/A"
                        print("\n" + "#" * 90)
                        print(f"  APPROVED FOLDER DETAILS: '{dname}'")
                        print("#" * 90)
                        print(f"  • Full Path:       {dpath}")
                        print(f"  • Status:          ✓ Approved & Verified ({v_date_str})")
                        print(f"  • Subtree Storage: {format_size(sub_b)} across {sub_cnt:,} files ({dir_cnt:,} direct root files)")
                        print(f"  • Folder Tags:     {dtags}")
                        print(f"  • Categories:      {cat_str}")
                        if ddesc:
                            print(f"  • Description:     \"{ddesc}\"")
                        print("-" * 90)
                        if dir_files:
                            print(f"  Contained Files in Subtree ({len(dir_files)} displayed):")
                            print(f"  {'#':<4} {'Subfolder':<22} {'File Name':<34} {'Category':<10} {'Size':<10} {'Modified Date'}")
                            print("  " + "-" * 86)
                            for d_fi, (df_name, df_cat, df_ext, df_sz, df_mod, df_sub) in enumerate(dir_files, 1):
                                m_str = df_mod.replace("T", " ")[:19] if df_mod else "N/A"
                                s_str = format_size(df_sz)
                                disp_name = df_name if len(df_name) <= 32 else df_name[:29] + "..."
                                disp_sub = df_sub if len(df_sub) <= 20 else df_sub[:17] + "..."
                                print(f"  {d_fi:<4} {disp_sub:<22} {disp_name:<34} {df_cat:<10} {s_str:<10} {m_str}")
                        elif sub_cnt == 0 and os.path.exists(dpath):
                            try:
                                disk_files = sum(len(fls) for _, _, fls in os.walk(dpath))
                                if disk_files > 0:
                                    print(f"  ⚠️ Notice: This folder contains {disk_files:,} files on disk that have NOT been scanned into SQLite.")
                                    print(f"     Run Option 2 ('Scan & index directory') on '{dpath}' to index its contents.")
                                else:
                                    print("  (Folder is empty on disk)")
                            except Exception:
                                print("  (Folder contains 0 files)")
                        else:
                            print("  (Folder contains 0 files)")
                        print("#" * 90)
                    else:
                        print(f"[Error] Invalid selection. Choose 1-{len(v_rows)}.")

        elif rep_choice == "2":
            # List All Approved Files (including files inside subdirectories of approved folders)
            cursor.execute("""
                SELECT 
                    d.name as folder_name,
                    d.path as folder_path,
                    f.name as file_name,
                    f.category,
                    f.extension,
                    f.size_bytes,
                    f.modified_at,
                    COALESCE(GROUP_CONCAT(DISTINCT ft.tag_name), '-') as file_tags
                FROM files f
                JOIN directories d ON f.directory_id = d.id
                LEFT JOIN file_tags ft ON ft.file_id = f.id
                WHERE d.is_verified = 1
                   OR EXISTS (SELECT 1 FROM directories p WHERE p.is_verified = 1 AND d.path LIKE p.path || '/%')
                GROUP BY f.id
                ORDER BY d.path, f.name
            """)
            all_v_files = cursor.fetchall()
            print("\n" + "=" * 98)
            print(f"ALL APPROVED FILES ({len(all_v_files):,} files across approved folders and subtrees)")
            print("=" * 98)
            print(f"{'#':<4} {'Folder':<22} {'File Name':<34} {'Category':<10} {'Size':<10} {'Modified Date'}")
            print("-" * 98)
            for f_i, (f_dname, f_dpath, f_name, f_cat, f_ext, f_sz, f_mod, f_tags) in enumerate(all_v_files[:100], 1):
                m_str = f_mod.replace("T", " ")[:19] if f_mod else "N/A"
                s_str = format_size(f_sz)
                disp_fname = f_name if len(f_name) <= 32 else f_name[:29] + "..."
                disp_dname = f_dname if len(f_dname) <= 20 else f_dname[:17] + "..."
                print(f"{f_i:<4} {disp_dname:<22} {disp_fname:<34} {f_cat:<10} {s_str:<10} {m_str}")
            if len(all_v_files) > 100:
                print(f"  ... and {len(all_v_files) - 100:,} more approved files (use Option 5 to export complete list).")
            print("=" * 98)
            input("\nPress Enter to continue...")

        elif rep_choice == "3":
            # List Unapproved Level-1 / Level-2 Folders Pending Curation
            cursor.execute("""
                SELECT 
                    pl.priority_tier,
                    pl.label,
                    d.id,
                    d.name,
                    d.path,
                    (SELECT COUNT(f.id) FROM directories sub JOIN files f ON f.directory_id = sub.id WHERE sub.id = d.id OR sub.path LIKE d.path || '/%') as sub_cnt,
                    (SELECT COALESCE(SUM(f.size_bytes), 0) FROM directories sub JOIN files f ON f.directory_id = sub.id WHERE sub.id = d.id OR sub.path LIKE d.path || '/%') as sub_b,
                    (SELECT COUNT(f.id) FROM files f WHERE f.directory_id = d.id) as dir_cnt,
                    COALESCE(GROUP_CONCAT(DISTINCT dt.tag_name), '-') as tags
                FROM priority_locations pl
                JOIN directories d ON (d.path LIKE pl.path || '/%' AND d.path NOT LIKE pl.path || '/%/%/%')
                LEFT JOIN directory_tags dt ON d.id = dt.directory_id
                WHERE pl.is_active = 1 AND d.is_verified = 0
                GROUP BY d.id
                ORDER BY pl.priority_tier, d.path
            """)
            u_rows = cursor.fetchall()
            print("\n" + "=" * 98)
            print(f"PENDING / UNAPPROVED CATEGORY FOLDERS ({len(u_rows)} Level-1/2 folders)")
            print("=" * 98)
            print(f"{'#':<4} {'Tier':<14} {'Folder Name':<28} {'Subtree Files / Size':<26} {'Tags'}")
            print("-" * 98)
            for idx, (ptier, plbl, did, dname, dpath, sub_cnt, sub_b, dir_cnt, dtags) in enumerate(u_rows, 1):
                stat_str = f"{sub_cnt:,} files ({format_size(sub_b)})"
                print(f"{idx:<4} {ptier.title():<14} {dname:<28} {stat_str:<26} {dtags}")
                print(f"     📍 Path: {dpath}")
            print("=" * 98)

            while True:
                u_drill = input("\nEnter folder # (1-N) to inspect pending files & details, or Enter to return: ").strip().lower()
                if not u_drill:
                    break
                if u_drill.isdigit():
                    u_idx = int(u_drill) - 1
                    if 0 <= u_idx < len(u_rows):
                        ptier, plbl, did, dname, dpath, sub_cnt, sub_b, dir_cnt, dtags = u_rows[u_idx]
                        cursor.execute("""
                            SELECT f.name, f.category, f.extension, f.size_bytes, f.modified_at, sub.name as sub_folder
                            FROM directories sub
                            JOIN files f ON f.directory_id = sub.id
                            WHERE sub.id = ? OR sub.path LIKE ? || '/%'
                            ORDER BY f.size_bytes DESC
                            LIMIT 100
                        """, (did, dpath))
                        u_dir_files = cursor.fetchall()
                        print("\n" + "#" * 90)
                        print(f"  PENDING FOLDER DETAILS: '{dname}' ({ptier.title()})")
                        print("#" * 90)
                        print(f"  • Full Path:       {dpath}")
                        print(f"  • Status:          ⚪ Pending Curation / Unapproved")
                        print(f"  • Subtree Storage: {format_size(sub_b)} across {sub_cnt:,} files ({dir_cnt:,} direct root files)")
                        print("-" * 90)
                        if u_dir_files:
                            print(f"  Contained Files in Subtree ({len(u_dir_files)} displayed):")
                            print(f"  {'#':<4} {'Subfolder':<22} {'File Name':<34} {'Category':<10} {'Size':<10} {'Modified Date'}")
                            print("  " + "-" * 86)
                            for u_fi, (uf_name, uf_cat, uf_ext, uf_sz, uf_mod, uf_sub) in enumerate(u_dir_files, 1):
                                m_str = uf_mod.replace("T", " ")[:19] if uf_mod else "N/A"
                                s_str = format_size(uf_sz)
                                disp_name = uf_name if len(uf_name) <= 32 else uf_name[:29] + "..."
                                disp_sub = uf_sub if len(uf_sub) <= 20 else uf_sub[:17] + "..."
                                print(f"  {u_fi:<4} {disp_sub:<22} {disp_name:<34} {uf_cat:<10} {s_str:<10} {m_str}")
                        else:
                            print("  (Folder contains 0 files)")
                        print("#" * 90)
                    else:
                        print(f"[Error] Invalid selection. Choose 1-{len(u_rows)}.")

        elif rep_choice == "4":
            tier_in = input("\nEnter Priority Tier to filter (1, 2, 3, or 4): ").strip()
            if tier_in in ["1", "2", "3", "4"]:
                t_filter = f"priority {tier_in}"
                cursor.execute("""
                    SELECT 
                        d.is_verified,
                        d.name,
                        d.path,
                        d.verified_at,
                        d.description,
                        (SELECT COUNT(f.id) FROM directories sub JOIN files f ON f.directory_id = sub.id WHERE sub.id = d.id OR sub.path LIKE d.path || '/%') as sub_cnt,
                        (SELECT COALESCE(SUM(f.size_bytes), 0) FROM directories sub JOIN files f ON f.directory_id = sub.id WHERE sub.id = d.id OR sub.path LIKE d.path || '/%') as sub_b
                    FROM priority_locations pl
                    JOIN directories d ON (d.path = pl.path OR d.path LIKE pl.path || '/%')
                    WHERE pl.priority_tier = ? AND pl.is_active = 1
                    GROUP BY d.id
                    ORDER BY d.is_verified DESC, d.path
                """, (t_filter,))
                tier_rows = cursor.fetchall()
                t_ver = [r for r in tier_rows if r[0] == 1]
                t_unver = [r for r in tier_rows if r[0] == 0]
                print("\n" + "=" * 90)
                print(f"PRIORITY {tier_in} STATUS: {len(t_ver):,} Approved | {len(t_unver):,} Pending Unapproved")
                print("=" * 90)
                print(f"\n--- APPROVED FOLDERS ({len(t_ver)}) ---")
                for idx, (_, dname, dpath, v_at, ddesc, sub_cnt, sub_b) in enumerate(t_ver, 1):
                    v_date = v_at.replace("T", " ")[:19] if v_at else ""
                    print(f"  [{idx}] {dname} ({sub_cnt:,} files, {format_size(sub_b)}) - {v_date}")
                    if ddesc:
                        print(f"      ↳ 📝 \"{ddesc}\"")
                print(f"\n--- PENDING UNAPPROVED FOLDERS ({min(len(t_unver), 30)} of {len(t_unver):,}) ---")
                for idx, (_, dname, dpath, _, _, sub_cnt, sub_b) in enumerate(t_unver[:30], 1):
                    print(f"  [{idx}] {dname} ({sub_cnt:,} files, {format_size(sub_b)}) 📍 {dpath}")
                if len(t_unver) > 30:
                    print(f"  ... and {len(t_unver) - 30:,} more subfolders pending curation.")
                print("=" * 90)
                input("\nPress Enter to continue...")

        elif rep_choice == "5":
            exp_fmt = input("\nExport format [m = Markdown, c = CSV, or enter to cancel]: ").strip().lower()
            if exp_fmt == "m":
                fname = "curation_status_report.md"
                cursor.execute("""
                    SELECT d.id, d.name, d.path, d.is_verified, d.verified_at, d.description,
                           (SELECT COUNT(f.id) FROM directories sub JOIN files f ON f.directory_id = sub.id WHERE sub.id = d.id OR sub.path LIKE d.path || '/%') as sub_cnt,
                           (SELECT COALESCE(SUM(f.size_bytes), 0) FROM directories sub JOIN files f ON f.directory_id = sub.id WHERE sub.id = d.id OR sub.path LIKE d.path || '/%') as sub_b
                    FROM directories d
                    WHERE d.is_verified = 1
                    ORDER BY d.path
                """)
                ver_list = cursor.fetchall()

                cursor.execute("""
                    SELECT d.name as folder_name, f.name, f.category, f.size_bytes, f.modified_at, d.path
                    FROM files f
                    JOIN directories d ON f.directory_id = d.id
                    WHERE d.is_verified = 1
                       OR EXISTS (SELECT 1 FROM directories p WHERE p.is_verified = 1 AND d.path LIKE p.path || '/%')
                    ORDER BY d.path, f.name
                """)
                v_files_all = cursor.fetchall()

                cursor.execute("""
                    SELECT d.id, d.name, d.path,
                           (SELECT COUNT(f.id) FROM directories sub JOIN files f ON f.directory_id = sub.id WHERE sub.id = d.id OR sub.path LIKE d.path || '/%') as sub_cnt,
                           (SELECT COALESCE(SUM(f.size_bytes), 0) FROM directories sub JOIN files f ON f.directory_id = sub.id WHERE sub.id = d.id OR sub.path LIKE d.path || '/%') as sub_b
                    FROM directories d
                    WHERE d.is_verified = 0
                    ORDER BY d.path
                    LIMIT 200
                """)
                unver_list = cursor.fetchall()

                with open(fname, "w", encoding="utf-8") as f:
                    f.write("# Storage Curation & Verification Status Report\n\n")
                    f.write(f"**Generated**: `{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`  \n")
                    f.write(f"**Overall Progress**: {pct_folders:.1f}% Approved ({verified_folders:,} / {total_folders:,} folders)\n\n")
                    f.write(f"- **Approved Storage**: {format_size(verified_bytes)} across {verified_files:,} files\n")
                    f.write(f"- **Pending Storage**: {format_size(unverified_bytes)} across {unverified_files:,} files\n\n")
                    f.write("## 1. Approved / Verified Folders (`is_verified = 1`)\n\n")
                    f.write("| # | Folder Name | Subtree Files | Subtree Size | Verified Date | Description | Path |\n")
                    f.write("|---|---|---|---|---|---|---|\n")
                    for i, (_, dn, dp, _, va, dd, fc, bc) in enumerate(ver_list, 1):
                        v_str = va.replace("T", " ")[:19] if va else "N/A"
                        desc_str = dd.replace("|", "/") if dd else "-"
                        f.write(f"| {i} | `{dn}` | {fc:,} | {format_size(bc)} | {v_str} | {desc_str} | `{dp}` |\n")

                    f.write(f"\n## 2. Approved Files Inventory ({len(v_files_all):,} files)\n\n")
                    f.write("| # | Folder | File Name | Category | Size | Modified Date | Path |\n")
                    f.write("|---|---|---|---|---|---|---|\n")
                    for fi, (fdn, fn, fcat, fsz, fmod, fdp) in enumerate(v_files_all, 1):
                        fm_str = fmod.replace("T", " ")[:19] if fmod else "N/A"
                        f.write(f"| {fi} | `{fdn}` | `{fn}` | `{fcat}` | **{format_size(fsz)}** | {fm_str} | `{fdp}/{fn}` |\n")

                    f.write("\n## 3. Unapproved / Pending Folders (`is_verified = 0`)\n\n")
                    f.write(f"Total unapproved subfolders in database: **{unverified_folders:,}**\n\n")
                    f.write("| # | Folder Name | Subtree Files | Subtree Size | Path |\n")
                    f.write("|---|---|---|---|---|\n")
                    for i, (_, dn, dp, fc, bc) in enumerate(unver_list, 1):
                        f.write(f"| {i} | `{dn}` | {fc:,} | {format_size(bc)} | `{dp}` |\n")
                    if unverified_folders > 200:
                        f.write(f"\n*(Showing top 200 of {unverified_folders:,} unapproved folders in Markdown summary)*\n")
                print(f"\n[Success] Full Markdown report exported to: {os.path.abspath(fname)}")
                input("\nPress Enter to continue...")
            elif exp_fmt == "c":
                fname = "curation_status_report.csv"
                cursor.execute("""
                    SELECT d.id, d.name, d.path, d.is_verified, d.verified_at, d.description,
                           (SELECT COUNT(f.id) FROM directories sub JOIN files f ON f.directory_id = sub.id WHERE sub.id = d.id OR sub.path LIKE d.path || '/%') as sub_cnt,
                           (SELECT COALESCE(SUM(f.size_bytes), 0) FROM directories sub JOIN files f ON f.directory_id = sub.id WHERE sub.id = d.id OR sub.path LIKE d.path || '/%') as sub_b
                    FROM directories d
                    ORDER BY d.is_verified DESC, d.path
                """)
                all_d = cursor.fetchall()
                with open(fname, "w", newline="", encoding="utf-8") as f:
                    writer = csv.writer(f)
                    writer.writerow(["ID", "Status", "Folder Name", "Path", "Subtree Files Count", "Subtree Size Bytes", "Subtree Size Formatted", "Verified At", "Description"])
                    for did, dname, dpath, is_v, vat, ddesc, fc, bc in all_d:
                        status_str = "Approved" if is_v == 1 else "Unapproved"
                        writer.writerow([did, status_str, dname, dpath, fc, bc, format_size(bc), vat or "", ddesc or ""])
                print(f"\n[Success] Full CSV report exported to: {os.path.abspath(fname)}")
                input("\nPress Enter to continue...")

    conn.close()


def auto_tag_priority_tree_interactive(db_path: str):
    """Recursively derives and applies Priority Tier (with colors) and Category tags across a folder tree."""
    print("\n--- AUTO-TAG STORAGE TREE (PRIORITY & CATEGORY) ---")
    last_dir = get_app_setting(db_path, "last_scanned_dir")
    default_root = last_dir if (last_dir and os.path.exists(last_dir)) else "/Volumes/LaCie/Storage"

    target_input = input(f"Enter target root folder [Default: {default_root}]: ").strip().strip('"').strip("'")
    target_path = target_input if target_input else default_root
    root = Path(target_path)

    if not root.exists() or not root.is_dir():
        print(f"\n[Error] Directory '{target_path}' does not exist.")
        return

    print("\nSelect Tagging Scope:")
    print("  1. Recursive (All subfolders inherit Priority Tier & Category tags) [Recommended]")
    print("  2. Top 2 levels only (Priority tier folder & direct category folders)")
    scope_choice = input("Choice [1/2, default: 1]: ").strip()
    recursive = scope_choice != "2"

    print(f"\nAnalyzing '{root}'...")
    folders_to_tag = []

    if recursive:
        for dirpath, dirs, files in os.walk(root):
            dp = Path(dirpath)
            tags = derive_folder_tags(dp)
            if tags:
                folders_to_tag.append((dp, tags))
    else:
        tags_root = derive_folder_tags(root)
        if tags_root:
            folders_to_tag.append((root, tags_root))
        for item in root.iterdir():
            if item.is_dir() and not item.name.startswith('.'):
                tags = derive_folder_tags(item)
                if tags:
                    folders_to_tag.append((item, tags))
                for sub in item.iterdir():
                    if sub.is_dir() and not sub.name.startswith('.'):
                        sub_tags = derive_folder_tags(sub)
                        if sub_tags:
                            folders_to_tag.append((sub, sub_tags))

    if not folders_to_tag:
        print("\n[Notice] No priority tiers or categories detected in the specified path.")
        return

    print("\n" + "=" * 75)
    print(f"TAGGING PREVIEW ({len(folders_to_tag):,} folders to be tagged)")
    print("=" * 75)
    for folder, tags in folders_to_tag[:12]:
        tag_str = ", ".join([f"[{name} ({FINDER_COLOR_MAP.get(c, 'None')})]" if c > 0 else f"[{name}]" for name, c in tags])
        print(f"  • {folder} -> {tag_str}")
    if len(folders_to_tag) > 12:
        print(f"  ... and {len(folders_to_tag) - 12:,} more folders")
    print("=" * 75)

    confirm = input("\nApply tags to macOS Finder and SQLite database? [y/N]: ").strip().lower()
    if confirm != 'y':
        print("\n[Cancelled] Auto-tagging aborted.")
        return

    print("\nApplying tags to filesystem and syncing database...")
    conn = get_db_connection(db_path) if os.path.exists(db_path) else None
    cursor = conn.cursor() if conn else None
    scan_time = datetime.datetime.now().isoformat()
    host_id = get_or_create_host(cursor) if cursor else None

    tagged_count = 0
    errors = 0

    for folder, tags in folders_to_tag:
        success = set_finder_tags(folder, tags)
        if success:
            tagged_count += 1
        else:
            errors += 1

        if cursor and host_id:
            resolved_p = str(folder.resolve())
            cursor.execute("SELECT id FROM directories WHERE host_id = ? AND path = ?", (host_id, resolved_p))
            row = cursor.fetchone()
            if row:
                d_id = row[0]
                for tag_name, _ in tags:
                    cursor.execute("""
                        INSERT INTO directory_tags (directory_id, tag_name, source, created_at)
                        VALUES (?, ?, 'finder', ?)
                        ON CONFLICT(directory_id, tag_name) DO NOTHING
                    """, (d_id, tag_name.lower(), scan_time))

    if conn:
        conn.commit()
        conn.close()

    print("\n" + "=" * 65)
    print(f"[Success] Tagged {tagged_count:,} folders in macOS Finder and SQLite!")
    if errors > 0:
        print(f"  • Non-fatal permission/filesystem skips: {errors}")
    print("=" * 65)

def manual_tag_directory_interactive(db_path: str):
    """Tags a specific directory on disk with custom text and Finder color, syncing to DB."""
    print("\n--- MANUAL FOLDER TAGGING ---")
    folder_input = input("Enter directory path to tag (or enter keyword to search DB): ").strip().strip('"').strip("'")
    if not folder_input:
        print("Cancelled.")
        return

    target_dir = Path(folder_input)
    if not target_dir.exists() or not target_dir.is_dir():
        # Search DB
        if not os.path.exists(db_path):
            print(f"\n[Error] Path '{folder_input}' not found.")
            return
        conn = get_db_connection(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT id, name, path FROM directories WHERE name LIKE ? OR path LIKE ? LIMIT 10", (f"%{folder_input}%", f"%{folder_input}%"))
        matches = cursor.fetchall()
        conn.close()
        if not matches:
            print(f"\n[Error] Directory '{folder_input}' not found on disk or in database.")
            return
        print("\nMatching Directories:")
        for idx, (did, name, path) in enumerate(matches, 1):
            print(f"  {idx}. {name} -> {path}")
        sel = input("Select number (or 'c' to cancel): ").strip()
        if not sel.isdigit() or int(sel) < 1 or int(sel) > len(matches):
            print("Cancelled.")
            return
        target_dir = Path(matches[int(sel)-1][2])

    tag_name = input(f"\nEnter tag name for '{target_dir.name}': ").strip()
    if not tag_name:
        print("Tag name cannot be empty.")
        return

    print("\nSelect Finder Color:")
    for code, color_name in FINDER_COLOR_MAP.items():
        print(f"  {code}: {color_name}")
    color_input = input("Enter color number (0-7, default: 0): ").strip()
    color_code = int(color_input) if color_input.isdigit() and 0 <= int(color_input) <= 7 else 0

    # Write Finder tag
    existing_tags = get_finder_tags(target_dir)
    updated_tags = [(tag_name, color_code)] + [(t, 0) for t in existing_tags if t != tag_name.lower()]
    set_finder_tags(target_dir, updated_tags)

    # Sync to DB
    if os.path.exists(db_path):
        conn = get_db_connection(db_path)
        cursor = conn.cursor()
        host_id = get_or_create_host(cursor)
        scan_time = datetime.datetime.now().isoformat()
        resolved_p = str(target_dir.resolve())
        cursor.execute("SELECT id FROM directories WHERE host_id = ? AND path = ?", (host_id, resolved_p))
        row = cursor.fetchone()
        if row:
            cursor.execute("""
                INSERT INTO directory_tags (directory_id, tag_name, source, created_at)
                VALUES (?, ?, 'manual', ?)
                ON CONFLICT(directory_id, tag_name) DO NOTHING
            """, (row[0], tag_name.lower(), scan_time))
            conn.commit()
        conn.close()

    print(f"\n[Success] Tag '[{tag_name} ({FINDER_COLOR_MAP[color_code]})]' applied to '{target_dir}' in Finder and DB.")

def clear_tags_directory_interactive(db_path: str):
    """Removes Finder tags from a directory on disk and cleans DB records."""
    print("\n--- REMOVE / CLEAR FOLDER TAGS ---")
    folder_input = input("Enter directory path to clear tags from: ").strip().strip('"').strip("'")
    target_dir = Path(folder_input)
    if not target_dir.exists() or not target_dir.is_dir():
        print(f"\n[Error] Directory '{folder_input}' does not exist.")
        return

    recursive = input("Clear tags recursively for all subfolders too? [y/N]: ").strip().lower() == 'y'
    confirm = input(f"Are you sure you want to remove tags from '{target_dir}'? [y/N]: ").strip().lower()
    if confirm != 'y':
        print("Cancelled.")
        return

    cleared = 0
    dirs_to_clear = [target_dir]
    if recursive:
        for root, dirs, files in os.walk(target_dir):
            dirs_to_clear.append(Path(root))

    conn = get_db_connection(db_path) if os.path.exists(db_path) else None
    cursor = conn.cursor() if conn else None
    host_id = get_or_create_host(cursor) if cursor else None

    for d in set(dirs_to_clear):
        if remove_finder_tags(d):
            cleared += 1
        if cursor and host_id:
            resolved_p = str(d.resolve())
            cursor.execute("SELECT id FROM directories WHERE host_id = ? AND path = ?", (host_id, resolved_p))
            row = cursor.fetchone()
            if row:
                cursor.execute("DELETE FROM directory_tags WHERE directory_id = ?", (row[0],))

    if conn:
        conn.commit()
        conn.close()

    print(f"\n[Success] Tags cleared from {cleared:,} directories on disk and in database.")

def resync_finder_tags_interactive(db_path: str):
    """Re-reads Finder tags from extended attributes on disk and synchronizes SQLite database."""
    print("\n--- RE-SYNC FINDER TAGS FROM DISK TO DB ---")
    last_dir = get_app_setting(db_path, "last_scanned_dir")
    default_root = last_dir if (last_dir and os.path.exists(last_dir)) else "/Volumes/LaCie/Storage"
    target_input = input(f"Enter root folder to scan for Finder tags [Default: {default_root}]: ").strip().strip('"').strip("'")
    target_path = target_input if target_input else default_root
    root = Path(target_path)

    if not root.exists() or not root.is_dir():
        print(f"\n[Error] Directory '{target_path}' does not exist.")
        return

    conn = get_db_connection(db_path)
    cursor = conn.cursor()
    host_id = get_or_create_host(cursor)
    scan_time = datetime.datetime.now().isoformat()

    synced_dirs = 0
    synced_tags = 0

    print(f"\nReading Finder tags across '{root}'...")
    for dirpath, dirs, files in os.walk(root):
        dp = Path(dirpath)
        tags = get_finder_tags(dp)
        if tags:
            resolved_p = str(dp.resolve())
            cursor.execute("SELECT id FROM directories WHERE host_id = ? AND path = ?", (host_id, resolved_p))
            row = cursor.fetchone()
            if row:
                d_id = row[0]
                synced_dirs += 1
                for tag in tags:
                    cursor.execute("""
                        INSERT INTO directory_tags (directory_id, tag_name, source, created_at)
                        VALUES (?, ?, 'finder', ?)
                        ON CONFLICT(directory_id, tag_name) DO NOTHING
                    """, (d_id, tag, scan_time))
                    synced_tags += 1

    conn.commit()
    conn.close()
    print(f"\n[Success] Re-synced {synced_tags:,} tags across {synced_dirs:,} directories into SQLite database.")

def _sync_directory_tags_to_db(dir_path: Path, tag_entries: list, db_path: str):
    """Syncs a directory and its tags to SQLite database."""
    if not os.path.exists(db_path):
        return
    try:
        conn = get_db_connection(db_path)
        cursor = conn.cursor()
        host_id = get_or_create_host(cursor)
        scan_time = datetime.datetime.now().isoformat()
        res_p = str(dir_path.resolve())

        cursor.execute("SELECT id FROM directories WHERE host_id = ? AND path = ?", (host_id, res_p))
        row = cursor.fetchone()
        if not row:
            d_stat = dir_path.stat()
            cursor.execute("""
                INSERT INTO directories (host_id, path, name, created_at, modified_at, scanned_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (host_id, res_p, dir_path.name,
                  datetime.datetime.fromtimestamp(d_stat.st_ctime).isoformat(),
                  datetime.datetime.fromtimestamp(d_stat.st_mtime).isoformat(),
                  scan_time))
            cursor.execute("SELECT id FROM directories WHERE host_id = ? AND path = ?", (host_id, res_p))
            row = cursor.fetchone()

        if row:
            did = row[0]
            cursor.execute("DELETE FROM directory_tags WHERE directory_id = ? AND source = 'finder'", (did,))
            for entry in tag_entries:
                t_name = entry[0] if isinstance(entry, (tuple, list)) else entry.split('\n')[0].strip()
                if t_name:
                    cursor.execute("""
                        INSERT INTO directory_tags (directory_id, tag_name, source, created_at)
                        VALUES (?, ?, 'finder', ?)
                        ON CONFLICT(directory_id, tag_name) DO NOTHING
                    """, (did, t_name.lower(), scan_time))
            conn.commit()
        conn.close()
    except Exception:
        pass

DEFAULT_PRIORITY_DESCRIPTIONS = {
    "priority 1": "Active & critical personal data (Quicken financial DBs, essential identity & legal documents)",
    "priority 2": "Systems, developer projects, Ruby/DevKits, user profiles, and PC software binaries",
    "priority 3": "Archival references, foreign media, downloaded materials, and historical records",
    "priority 4": "Central media staging depot (photos and home videos awaiting Media Organizer intake)",
}

DEFAULT_LEVEL1_DESCRIPTIONS = {
    # Priority 1 (Active & Critical Personal Data)
    ("priority 1", "data"): "Critical financial & account databases (Quicken .qdf, active tax/financial records)",
    ("priority 1", "documents"): "Vital personal identity, legal, medical, and essential personal documentation",

    # Priority 2 (Systems, Developer Projects, Profiles & Software)
    ("priority 2", "adobe font folio"): "Design typography font archives & digital design typefaces",
    ("priority 2", "bak"): "Legacy machine backup archives undergoing triage & deduplication",
    ("priority 2", "camera movies"): "Personal video clips & camera recordings prior to media pipeline intake",
    ("priority 2", "dev"): "Developer source code, repositories, toolchains, scripts, and Ruby/DevKits",
    ("priority 2", "documents"): "Secondary technical documentation, reference papers, and user guides",
    ("priority 2", "edu"): "Educational courses, tutorials, textbooks, and professional certifications",
    ("priority 2", "pc bin"): "Software utilities, system installers, tools, and Windows executables",
    ("priority 2", "projects"): "Active & historical engineering/consulting project workspaces",
    ("priority 2", "references"): "Technical reference documentation, vendor manuals, and datasheets",
    ("priority 2", "saved user profiles"): "Saved Windows/OS user application settings and profile snapshots",
    ("priority 2", "dmg"): "macOS disk image installers and application packages",

    # Priority 3 (Archival References, Foreign Media & Historic Drops)
    ("priority 3", "downloaded media"): "Collected external podcasts, internet videos, and web media",
    ("priority 3", "downloads"): "General staging downloads and historical transfer drops",
    ("priority 3", "foreign data and media"): "External data dumps, guest files, and non-personal media collections",
    ("priority 3", "pc bin"): "Legacy PC software archives, system drivers, and redundant installers",
    ("priority 3", "references"): "General reference material, public domain archives, and e-books",

    # Priority 4 (Media Organizer Intake & Staging Depot)
    ("priority 4", "03a-movies"): "Digitized home movies and family video footage",
    ("priority 4", "nonmediafiles"): "Non-media files filtered out from photo/video import archives",
    ("priority 4", "pictures"): "Central intake depot for family photos awaiting Media Organizer intake",
    ("priority 4", "tobeimportedtombp personal photolibrary"): "Staged photo batches pending import into macOS Photos library",
}

def _set_directory_description_in_db(dir_path: Path, description: str | None, db_path: str, is_verified: bool = False):
    """Sets or updates description and verification columns for a directory in SQLite database."""
    if not os.path.exists(db_path):
        return
    try:
        conn = get_db_connection(db_path)
        cursor = conn.cursor()
        host_id = get_or_create_host(cursor)
        scan_time = datetime.datetime.now().isoformat()
        res_p = str(dir_path.resolve())
        verified_val = 1 if is_verified else 0
        verified_at_val = scan_time if is_verified else None

        cursor.execute("SELECT id FROM directories WHERE host_id = ? AND path = ?", (host_id, res_p))
        row = cursor.fetchone()
        if not row:
            d_stat = dir_path.stat()
            cursor.execute("""
                INSERT INTO directories (host_id, path, name, created_at, modified_at, scanned_at, description, is_verified, verified_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (host_id, res_p, dir_path.name,
                  datetime.datetime.fromtimestamp(d_stat.st_ctime).isoformat(),
                  datetime.datetime.fromtimestamp(d_stat.st_mtime).isoformat(),
                  scan_time, description, verified_val, verified_at_val))
        else:
            if is_verified:
                cursor.execute("""
                    UPDATE directories 
                    SET description = ?, is_verified = ?, verified_at = ?
                    WHERE id = ?
                """, (description, verified_val, verified_at_val, row[0]))
            else:
                cursor.execute("UPDATE directories SET description = ? WHERE id = ?", (description, row[0]))
        conn.commit()
        conn.close()
    except Exception:
        pass

def analyze_folder_content(folder_path: Path, max_depth: int = 3) -> dict:
    """Fast content profiler for a subfolder to assist the curation wizard."""
    total_files = 0
    total_bytes = 0
    ext_counts = Counter()
    sample_files = []
    mtimes = []
    subfolders = []

    try:
        for root_dir, dirnames, filenames in os.walk(folder_path):
            rel_depth = len(Path(root_dir).relative_to(folder_path).parts)
            if rel_depth >= max_depth:
                dirnames.clear()
            else:
                for d in dirnames:
                    if not d.startswith('.'):
                        subfolders.append(d)
            for f in filenames:
                if f.startswith('.'):
                    continue
                total_files += 1
                f_path = Path(root_dir) / f
                try:
                    stat = f_path.stat()
                    total_bytes += stat.st_size
                    mtimes.append(stat.st_mtime)
                    ext = f_path.suffix.lower()
                    if ext:
                        ext_counts[ext] += 1
                    else:
                        ext_counts['(no ext)'] += 1
                    if len(sample_files) < 4:
                        sample_files.append(f)
                except Exception:
                    pass
    except Exception:
        pass

    earliest_date = datetime.date.fromtimestamp(min(mtimes)).isoformat() if mtimes else None
    latest_date = datetime.date.fromtimestamp(max(mtimes)).isoformat() if mtimes else None

    return {
        "total_files": total_files,
        "total_bytes": total_bytes,
        "ext_counts": ext_counts,
        "sample_files": sample_files,
        "earliest_date": earliest_date,
        "latest_date": latest_date,
        "subfolder_count": len(subfolders)
    }

def suggest_folder_description(folder_name: str, parent_l1_name: str, tier_name: str, stats: dict) -> str:
    """Intelligently suggests a concise human-readable description for a folder based on its name and contents."""
    name_lower = folder_name.lower()
    total_files = stats.get("total_files", 0)
    ext_counts = stats.get("ext_counts", Counter())
    earliest = stats.get("earliest_date")
    latest = stats.get("latest_date")

    year_str = ""
    if earliest and latest:
        y1 = earliest.split("-")[0]
        y2 = latest.split("-")[0]
        year_str = f" ({y1}-{y2})" if y1 != y2 else f" ({y1})"

    top_exts = [e for e, _ in ext_counts.most_common(3) if e != '(no ext)']
    ext_label = f"[{', '.join(top_exts)}]" if top_exts else ""

    # Specific name & signature heuristics
    if "money" in name_lower or ".mny" in ext_counts or ".mbf" in ext_counts:
        return f"Microsoft Money financial database & backup archives (.mny, .mbf{year_str})"
    if "quicken" in name_lower or ".qdf" in ext_counts:
        return f"Quicken personal financial accounts & tax records (.qdf{year_str})"
    if "db backup" in name_lower or ".sql" in ext_counts:
        return f"Database SQL dumps & backup snapshots (.sql{year_str})"
    if "resume" in name_lower or "cv" in name_lower:
        return f"Professional resumes, CVs & career application documentation{year_str}"
    if "kindle" in name_lower or ".azw" in ext_counts or ".mobi" in ext_counts:
        return f"Amazon Kindle e-books and reading library content{year_str}"
    if "credit" in name_lower or "report" in name_lower:
        return f"Credit reports, financial documentation & personal records{year_str}"
    if "font" in name_lower or ".otf" in ext_counts or ".ttf" in ext_counts:
        return f"Typography font assets & design typeface archives{year_str}"
    if "vertexte" in name_lower:
        return f"Vertex historical workstation setup logs & system archives{year_str}"
    if "asus" in name_lower:
        return f"ASUS PC backup archive & migrated system assets{year_str}"
    if "presario" in name_lower:
        return f"Compaq Presario historic system backup & personal files{year_str}"
    if "families" in name_lower or "family" in name_lower:
        return f"Family vital documentation, certificates & personal records{year_str}"

    # Dominant type heuristics
    img_count = sum(ext_counts[e] for e in ['.jpg', '.jpeg', '.png', '.heic', '.tif', '.tiff', '.bmp', '.gif', '.nef', '.cr2'] if e in ext_counts)
    vid_count = sum(ext_counts[e] for e in ['.mov', '.mp4', '.avi', '.m4v', '.wmv', '.mpg', '.mpeg', '.mkv'] if e in ext_counts)
    code_count = sum(ext_counts[e] for e in ['.py', '.rb', '.js', '.ts', '.html', '.css', '.c', '.h', '.cpp', '.php', '.sh', '.json', '.yml'] if e in ext_counts)
    doc_count = sum(ext_counts[e] for e in ['.pdf', '.doc', '.docx', '.xls', '.xlsx', '.txt', '.rtf', '.ppt', '.pptx'] if e in ext_counts)

    if total_files > 0:
        if img_count / total_files >= 0.5:
            return f"Photo collection & digital image albums ({img_count:,} photos{year_str})"
        if vid_count / total_files >= 0.5:
            return f"Video recordings & digital home movie footage ({vid_count:,} clips{year_str})"
        if code_count / total_files >= 0.5:
            return f"Developer project source code & repositories {ext_label}{year_str}"
        if doc_count / total_files >= 0.5:
            return f"Personal documentation & archived records ({doc_count:,} documents{year_str})"

    if total_files == 0:
        return f"{folder_name} (Empty folder)"

    return f"{folder_name} archives ({total_files:,} files {ext_label}{year_str})"


def get_priority_locations(db_path: str, active_only: bool = True, priority_tier: str | None = None) -> list[dict]:
    """Retrieves mapped priority locations from SQLite."""
    if not os.path.exists(db_path):
        return []
    try:
        conn = get_db_connection(db_path)
        cursor = conn.cursor()

        # Check if empty, auto-seed defaults if /Volumes/LaCie/Storage exists
        cursor.execute("SELECT COUNT(*) FROM priority_locations")
        if cursor.fetchone()[0] == 0:
            now = datetime.datetime.now().isoformat()
            storage_root = Path("/Volumes/LaCie/Storage")
            for p_num in range(1, 5):
                p_name = f"priority {p_num}"
                p_path = storage_root / f"Priority {p_num}"
                desc = DEFAULT_PRIORITY_DESCRIPTIONS.get(p_name, "")
                cursor.execute("""
                    INSERT OR IGNORE INTO priority_locations (priority_tier, path, label, description, is_active, created_at)
                    VALUES (?, ?, ?, ?, 1, ?)
                """, (p_name, str(p_path.resolve()) if p_path.exists() else str(p_path), "LaCie Primary Storage", desc, now))
            conn.commit()

        query = "SELECT id, priority_tier, path, label, description, is_active, created_at FROM priority_locations WHERE 1=1"
        params = []
        if active_only:
            query += " AND is_active = 1"
        if priority_tier:
            query += " AND LOWER(priority_tier) = LOWER(?)"
            params.append(priority_tier)
        query += " ORDER BY priority_tier, id"

        cursor.execute(query, params)
        rows = cursor.fetchall()
        conn.close()

        results = []
        for r in rows:
            results.append({
                "id": r[0],
                "priority_tier": r[1],
                "path": Path(r[2]),
                "path_str": r[2],
                "label": r[3] or "",
                "description": r[4] or "",
                "is_active": bool(r[5]),
                "created_at": r[6]
            })
        return results
    except Exception:
        return []

def add_priority_location(db_path: str, priority_tier: str, path_str: str, label: str = "", description: str = "") -> bool:
    """Adds a new folder mapping to a Priority tier in SQLite."""
    try:
        p = Path(path_str).resolve()
        if not p.exists():
            create_choice = input(f"Directory '{p}' does not exist on disk. Create it? [Y/n]: ").strip().lower()
            if create_choice != 'n':
                p.mkdir(parents=True, exist_ok=True)
            else:
                return False

        tier_clean = priority_tier.lower()
        tier_info = PRIORITY_TIER_CONFIG.get(tier_clean, {"tag": priority_tier.title(), "color": 0})
        # Tag the location root with parent Priority color
        set_finder_tags(p, [(tier_info["tag"], tier_info["color"])])
        _sync_directory_tags_to_db(p, [(tier_info["tag"], tier_info["color"])], db_path)

        now = datetime.datetime.now().isoformat()
        conn = get_db_connection(db_path)
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO priority_locations (priority_tier, path, label, description, is_active, created_at)
            VALUES (?, ?, ?, ?, 1, ?)
        """, (tier_clean, str(p), label if label else p.name, description, now))
        conn.commit()
        conn.close()

        if description:
            _set_directory_description_in_db(p, description, db_path, is_verified=True)
        return True
    except Exception as e:
        print(f"[Error] Failed to add priority location: {e}")
        return False

def manage_priority_locations_interactive(db_path: str):
    """Sub-menu to list, add, edit, or remove mapped locations across Priority 1-4."""
    while True:
        locations = get_priority_locations(db_path, active_only=False)
        print("\n" + "=" * 80)
        print("  PRIORITY LEVEL LOCATIONS & STORAGE MAPPINGS  ")
        print("=" * 80)
        print(f"{'#':<4} {'Priority Tier':<14} {'Label / Name':<24} {'Active':<8} {'Path'}")
        print("-" * 80)
        for idx, loc in enumerate(locations, 1):
            tier_info = PRIORITY_TIER_CONFIG.get(loc["priority_tier"].lower(), {"color": 0, "color_name": "None"})
            emoji = FINDER_COLOR_EMOJI.get(tier_info["color"], "⚪")
            status = "✓ Yes" if loc["is_active"] else "⚪ Disabled"
            exists_mark = "" if loc["path"].exists() else " ⚠️ (Not Mounted)"
            print(f"{idx:<4} {emoji} {loc['priority_tier'].title():<12} {loc['label']:<24} {status:<8} {loc['path_str']}{exists_mark}")
            if loc["description"]:
                print(f"     ↳ 📝 {loc['description']}")
        print("-" * 80)

        print("\nActions:")
        print("  1. Add a new folder location mapping to a Priority level")
        print("  2. Toggle Active / Inactive status of a location")
        print("  3. Edit location Label or Description")
        print("  4. Remove / Unmap a location")
        print("  5. Return to previous menu")

        choice = input("\nSelect action (1-5): ").strip()
        if choice == "1":
            print("\nSelect Priority Tier to map:")
            for p_num in range(1, 5):
                p_name = f"priority {p_num}"
                p_info = PRIORITY_TIER_CONFIG[p_name]
                p_em = FINDER_COLOR_EMOJI[p_info["color"]]
                print(f"  {p_num}: {p_em} Priority {p_num} ({p_info['color_name']})")
            p_in = input("Enter priority number (1-4): ").strip()
            if p_in not in ['1', '2', '3', '4']:
                print("Invalid priority.")
                continue
            tier_selected = f"priority {p_in}"
            path_in = input("Enter directory path to map for this Priority level: ").strip().strip('"').strip("'")
            if not path_in:
                print("Path cannot be empty.")
                continue
            label_in = input("Enter a descriptive label / nickname (e.g. 'Workstation SSD', 'Backup NAS'): ").strip()
            desc_in = input("Enter optional description / notes for this location: ").strip()
            if add_priority_location(db_path, tier_selected, path_in, label_in, desc_in):
                print(f"\n[Success] Mapped '{path_in}' to {tier_selected.title()} ({label_in}).")
        elif choice == "2":
            sel = input(f"Enter location number (1-{len(locations)}) to toggle active status: ").strip()
            if sel.isdigit() and 1 <= int(sel) <= len(locations):
                loc = locations[int(sel) - 1]
                new_status = 0 if loc["is_active"] else 1
                conn = get_db_connection(db_path)
                conn.execute("UPDATE priority_locations SET is_active = ? WHERE id = ?", (new_status, loc["id"]))
                conn.commit()
                conn.close()
                print(f"\n[Success] Toggled '{loc['label']}' to {'Active' if new_status else 'Inactive'}.")
        elif choice == "3":
            sel = input(f"Enter location number (1-{len(locations)}) to edit: ").strip()
            if sel.isdigit() and 1 <= int(sel) <= len(locations):
                loc = locations[int(sel) - 1]
                print(f"\nCurrent Label: {loc['label']}")
                new_lbl = input("Enter new label (or press Enter to keep): ").strip()
                print(f"Current Description: {loc['description']}")
                new_desc = input("Enter new description (or press Enter to keep): ").strip()
                conn = get_db_connection(db_path)
                if new_lbl:
                    conn.execute("UPDATE priority_locations SET label = ? WHERE id = ?", (new_lbl, loc["id"]))
                if new_desc:
                    conn.execute("UPDATE priority_locations SET description = ? WHERE id = ?", (new_desc, loc["id"]))
                conn.commit()
                conn.close()
                print("\n[Success] Location updated.")
        elif choice == "4":
            sel = input(f"Enter location number (1-{len(locations)}) to unmap / remove: ").strip()
            if sel.isdigit() and 1 <= int(sel) <= len(locations):
                loc = locations[int(sel) - 1]
                confirm_del = input(f"Remove mapping for '{loc['label']}' ({loc['path_str']})? (Folder files will not be deleted) [y/N]: ").strip().lower()
                if confirm_del == 'y':
                    conn = get_db_connection(db_path)
                    conn.execute("DELETE FROM priority_locations WHERE id = ?", (loc["id"],))
                    conn.commit()
                    conn.close()
                    print("\n[Success] Location unmapped.")
        elif choice == "5":
            break

def reset_subfolder_tags_and_verification(db_path: str, storage_root: Path | None = None):
    """
    Preserves tags, descriptions, and verified status for all registered Priority locations and their level-1 folders.
    Strips Finder tags and DB tags from all subfolders beneath level 1 (level 2+).
    Resets verification status (is_verified = 0) on level 2+ subfolders so they can be curated.
    """
    print("\n" + "=" * 80)
    print("  RESET SUBFOLDER TAGS & VERIFICATION STATUS  ")
    print("=" * 80)
    print("This action will:")
    print("  1. PRESERVE tags, colors, and descriptions on all Priority Locations & their Level-1 folders.")
    print("  2. STRIP all Finder tags on disk from subfolders beneath Level-1 (Level 2+).")
    print("  3. REMOVE all database tags for subfolders beneath Level-1 in SQLite.")
    print("  4. RESET verification status (is_verified = 0) so all subfolders are ready for curation.")
    print("=" * 80)

    confirm = input("\nProceed with resetting subfolder tags across all Priority locations? [y/N]: ").strip().lower()
    if confirm != 'y':
        print("\n[Cancelled] Reset aborted.")
        return

    print("\nProcessing reset across all Priority Locations...")
    now_iso = datetime.datetime.now().isoformat()
    if os.path.exists(db_path):
        conn = get_db_connection(db_path)
        cursor = conn.cursor()

        locations = get_priority_locations(db_path, active_only=True)
        if not locations:
            print("[Notice] No active priority locations mapped.")
            conn.close()
            return

        total_cleared_disk = 0
        total_deleted_dt = 0
        total_deleted_ft = 0
        total_reset_dirs = 0

        for loc in locations:
            loc_path_str = loc["path_str"]

            # Step 1: Ensure Location root and direct Level-1 folders are marked verified = 1
            cursor.execute("""
                UPDATE directories 
                SET is_verified = 1, verified_at = ?
                WHERE path = ? OR (
                    path LIKE ? || '/%' AND path NOT LIKE ? || '/%/%'
                )
            """, (now_iso, loc_path_str, loc_path_str, loc_path_str))

            # Step 2: Query all level-2+ directories recorded with tags under this location
            cursor.execute("""
                SELECT DISTINCT d.path 
                FROM directories d 
                JOIN directory_tags dt ON d.id = dt.directory_id
                WHERE d.path LIKE ? || '/%/%'
            """, (loc_path_str,))
            tagged_paths = [r[0] for r in cursor.fetchall()]

            # Step 3: Remove Finder tags on disk
            for p_str in tagged_paths:
                p = Path(p_str)
                if p.exists() and remove_finder_tags(p):
                    total_cleared_disk += 1

            # Step 4: Clear DB tags
            cursor.execute("""
                DELETE FROM directory_tags 
                WHERE directory_id IN (
                    SELECT id FROM directories WHERE path LIKE ? || '/%/%'
                )
            """, (loc_path_str,))
            total_deleted_dt += cursor.rowcount

            cursor.execute("""
                DELETE FROM file_tags 
                WHERE file_id IN (
                    SELECT f.id FROM files f 
                    JOIN directories d ON f.directory_id = d.id 
                    WHERE d.path LIKE ? || '/%/%'
                )
            """, (loc_path_str,))
            total_deleted_ft += cursor.rowcount

            # Step 5: Reset verification
            cursor.execute("""
                UPDATE directories 
                SET is_verified = 0, verified_at = NULL 
                WHERE path LIKE ? || '/%/%'
            """, (loc_path_str,))
            total_reset_dirs += cursor.rowcount

        conn.commit()
        conn.close()

        print("\n[Success] Tag & Verification Reset Complete:")
        print(f"  • Scoped across {len(locations)} active Priority Locations")
        print(f"  • Cleared Finder tags from {total_cleared_disk:,} folders on disk")
        print(f"  • Removed {total_deleted_dt:,} directory tags and {total_deleted_ft:,} file tags from SQLite")
        print(f"  • Reset {total_reset_dirs:,} subfolders to Unverified (ready for Curation Wizard)")

def curation_wizard_interactive(db_path: str, storage_root: Path | None = None, target_l1_dir: Path | None = None):
    """
    Sequential Curation Wizard:
    Steps through Level-1 folders under Priority 1-4 mapped locations, inspects Level-2 subfolders,
    generates smart suggested descriptions, and prompts for human review & approval.
    """
    print("\n" + "=" * 80)
    print("  SEQUENTIAL STORAGE CURATION WIZARD  ")
    print("=" * 80)
    print("This wizard inspects subfolders under each Priority Location & Level-1 category,")
    print("analyzes their contents, suggests descriptions, and prompts for your approval.")
    print("Approved folders receive Priority Finder color tags and are marked as verified DB entries.")
    print("=" * 80)

    # 1. Determine Scope
    target_l1_folders = []
    if target_l1_dir:
        tier_name = target_l1_dir.parent.name
        loc_label = target_l1_dir.parent.name
        target_l1_folders = [(tier_name, loc_label, target_l1_dir.parent, target_l1_dir)]
    else:
        all_locations = get_priority_locations(db_path, active_only=True)
        if not all_locations:
            print("\n[Notice] No active Priority locations mapped. Use 'loc' to map folder locations.")
            return

        print("\nSelect Curation Scope:")
        print("  1. All Priority Tiers & Locations sequentially (Priority 1 -> 4) [Default]")
        print("  2. Priority 1 (Active & Critical Data)")
        print("  3. Priority 2 (Systems, DEV & Profiles)")
        print("  4. Priority 3 (Archival References & Foreign Media)")
        print("  5. Priority 4 (Media Staging & Photos)")
        print("  6. Return to menu")
        scope_choice = input("\nSelect option (1-6) [Default: 1]: ").strip()

        if scope_choice == "6":
            return
        elif scope_choice == "2":
            selected_locs = [l for l in all_locations if l["priority_tier"] == "priority 1"]
        elif scope_choice == "3":
            selected_locs = [l for l in all_locations if l["priority_tier"] == "priority 2"]
        elif scope_choice == "4":
            selected_locs = [l for l in all_locations if l["priority_tier"] == "priority 3"]
        elif scope_choice == "5":
            selected_locs = [l for l in all_locations if l["priority_tier"] == "priority 4"]
        else:
            selected_locs = all_locations

        for loc in selected_locs:
            p_dir = loc["path"]
            if p_dir.exists() and p_dir.is_dir():
                for sub in sorted(p_dir.iterdir()):
                    if sub.is_dir() and not sub.name.startswith('.'):
                        target_l1_folders.append((loc["priority_tier"].title(), loc["label"], p_dir, sub))

    if not target_l1_folders:
        print("\n[Notice] No Level-1 folders found to curate.")
        return

    unverified_only = input("\nReview only UNVERIFIED subfolders? [Y/n]: ").strip().lower() != 'n'

    total_curated = 0
    total_skipped = 0

    conn = get_db_connection(db_path) if os.path.exists(db_path) else None

    for tier_name, loc_label, loc_path, l1_dir in target_l1_folders:
        tier_clean = tier_name.lower()
        tier_info = PRIORITY_TIER_CONFIG.get(tier_clean, {"tag": tier_name, "color": 0, "color_name": "None"})
        tier_emoji = FINDER_COLOR_EMOJI.get(tier_info["color"], "⚪")

        # Get immediate subfolders (Level-2)
        l2_subdirs = [s for s in sorted(l1_dir.iterdir()) if s.is_dir() and not s.name.startswith('.')]
        if not l2_subdirs:
            continue

        print(f"\n" + "#" * 80)
        print(f"  {tier_emoji} [{tier_name}] ▸ 📍 {loc_label} ▸ {l1_dir.name}  ({len(l2_subdirs)} subfolders to inspect)")
        print("#" * 80)

        for s_idx, sub_dir in enumerate(l2_subdirs, 1):
            res_p = str(sub_dir.resolve())
            is_verified = 0
            existing_desc = None

            if conn:
                cursor = conn.cursor()
                cursor.execute("SELECT is_verified, description FROM directories WHERE path = ?", (res_p,))
                row = cursor.fetchone()
                if row:
                    is_verified = row[0] or 0
                    existing_desc = row[1]

            if unverified_only and is_verified == 1:
                desc_label = f" — \"{existing_desc}\"" if existing_desc else ""
                print(f"  [{s_idx}/{len(l2_subdirs)}] ✓ Verified: {sub_dir.name}{desc_label} (Skipping)")
                continue

            # Analyze content
            stats = analyze_folder_content(sub_dir)
            suggested_desc = existing_desc if existing_desc else suggest_folder_description(sub_dir.name, l1_dir.name, tier_name, stats)

            # Format stats
            size_str = format_size(stats["total_bytes"])
            files_count = stats["total_files"]
            date_range = f"{stats['earliest_date']} → {stats['latest_date']}" if stats["earliest_date"] else "Unknown dates"
            top_exts = ", ".join([f"{count} {ext}" for ext, count in stats["ext_counts"].most_common(4)]) if stats["ext_counts"] else "None"
            samples = ", ".join(stats["sample_files"][:3]) if stats["sample_files"] else "None"

            verified_badge = "✓ Verified" if is_verified == 1 else "⚪ Unverified (Untagged)"

            while True:
                print("\n" + "-" * 80)
                print(f"  {tier_emoji} [{tier_name}] ▸ 📍 {loc_label} ▸ {l1_dir.name}  |  Folder {s_idx}/{len(l2_subdirs)}: '{sub_dir.name}'")
                print("-" * 80)
                print(f"  • Location:     {loc_label} ({loc_path})")
                print(f"  • Full Path:    {sub_dir}")
                print(f"  • Status:       {verified_badge}")
                print(f"  • Storage:      {size_str} across {files_count:,} files ({stats['subfolder_count']} subfolders)")
                print(f"  • Date Range:   {date_range}")
                print(f"  • File Types:   {top_exts}")
                print(f"  • Sample Files: {samples}")
                print(f"\n  💡 Suggested Description:")
                print(f"     \"{suggested_desc}\"")
                print("\n  Actions:")
                print("    [a] Approve suggested description & apply tags (Mark Verified ✓)")
                print("    [e] Edit description, apply tags & verify")
                print("    [m] Move / Reassign to another Priority tier or parent folder")
                print("    [s] Skip for now (remain unverified)")
                print("    [q] Quit wizard and return to menu")

                action = input("\nSelect action [a/e/m/s/q] (Default: a): ").strip().lower()
                if not action:
                    action = 'a'

                if action == 'a':
                    tags = [(tier_info["tag"], tier_info["color"]), (l1_dir.name, 0), (sub_dir.name, 0)]
                    set_finder_tags(sub_dir, tags)
                    _sync_directory_tags_to_db(sub_dir, tags, db_path)
                    _set_directory_description_in_db(sub_dir, suggested_desc, db_path, is_verified=True)
                    print(f"\n[Success] ✓ Approved & verified '{sub_dir.name}'. Tags & description saved.")
                    total_curated += 1
                    break
                elif action == 'e':
                    print(f"\nCurrent suggestion: {suggested_desc}")
                    custom_desc = input("Enter custom description (or press Enter to keep suggestion): ").strip()
                    final_desc = custom_desc if custom_desc else suggested_desc
                    tags = [(tier_info["tag"], tier_info["color"]), (l1_dir.name, 0), (sub_dir.name, 0)]
                    set_finder_tags(sub_dir, tags)
                    _sync_directory_tags_to_db(sub_dir, tags, db_path)
                    _set_directory_description_in_db(sub_dir, final_desc, db_path, is_verified=True)
                    print(f"\n[Success] ✓ Custom description approved & verified for '{sub_dir.name}'.")
                    total_curated += 1
                    break
                elif action == 'm':
                    active_locs = get_priority_locations(db_path, active_only=True)
                    print("\nSelect Target Location for move:")
                    for l_idx, al in enumerate(active_locs, 1):
                        p_info = PRIORITY_TIER_CONFIG.get(al["priority_tier"].lower(), {"color": 0})
                        p_em = FINDER_COLOR_EMOJI.get(p_info["color"], "⚪")
                        print(f"  {l_idx}: {p_em} {al['priority_tier'].title()} - {al['label']} ({al['path_str']})")
                    l_sel = input(f"Select location (1-{len(active_locs)}) or 'c' to cancel: ").strip()
                    if not l_sel.isdigit() or int(l_sel) < 1 or int(l_sel) > len(active_locs):
                        print("Move cancelled.")
                        continue
                    
                    target_loc = active_locs[int(l_sel) - 1]
                    target_tier_dir = target_loc["path"]
                    target_l1_subdirs = [s for s in sorted(target_tier_dir.iterdir()) if s.is_dir() and not s.name.startswith('.')]
                    print(f"\nSelect target category in {target_loc['label']}:")
                    for t_idx, tl1 in enumerate(target_l1_subdirs, 1):
                        print(f"  {t_idx}: {tl1.name}")
                    tl1_sel = input(f"Select category (1-{len(target_l1_subdirs)}) or 'c' to cancel: ").strip()
                    if not tl1_sel.isdigit() or int(tl1_sel) < 1 or int(tl1_sel) > len(target_l1_subdirs):
                        print("Move cancelled.")
                        continue
                    
                    target_l1_dest = target_l1_subdirs[int(tl1_sel) - 1]
                    target_dest_path = target_l1_dest / sub_dir.name
                    if target_dest_path.exists():
                        print(f"\n[Error] Destination '{target_dest_path}' already exists!")
                        continue

                    confirm_m = input(f"Move '{sub_dir.name}' to '{target_dest_path}'? [y/N]: ").strip().lower()
                    if confirm_m == 'y':
                        shutil.move(str(sub_dir), str(target_dest_path))
                        if os.path.exists(db_path):
                            c_conn = get_db_connection(db_path)
                            c_cur = c_conn.cursor()
                            old_p = str(sub_dir.resolve())
                            new_p = str(target_dest_path.resolve())
                            c_cur.execute("""
                                UPDATE directories
                                SET path = ? || SUBSTR(path, LENGTH(?) + 1)
                                WHERE path = ? OR path LIKE ? || '/%'
                            """, (new_p, old_p, old_p, old_p))
                            c_conn.commit()
                            c_conn.close()

                        new_tier_info = PRIORITY_TIER_CONFIG[target_loc["priority_tier"].lower()]
                        new_tags = [(new_tier_info["tag"], new_tier_info["color"]), (target_l1_dest.name, 0), (sub_dir.name, 0)]
                        set_finder_tags(target_dest_path, new_tags)
                        _sync_directory_tags_to_db(target_dest_path, new_tags, db_path)
                        _set_directory_description_in_db(target_dest_path, suggested_desc, db_path, is_verified=True)
                        print(f"\n[Success] ✓ Moved and verified '{sub_dir.name}' under {target_loc['label']} / {target_l1_dest.name}.")
                        total_curated += 1
                        break
                elif action == 's':
                    print(f"\n[Skipped] '{sub_dir.name}' left unverified.")
                    total_skipped += 1
                    break
                elif action == 'q':
                    if conn:
                        conn.close()
                    print("\n" + "=" * 80)
                    print("CURATION WIZARD SUMMARY")
                    print("=" * 80)
                    print(f"  • Verified in this session: {total_curated}")
                    print(f"  • Skipped unverified:       {total_skipped}")
                    print("Progress saved in SQLite. You can resume any time!")
                    print("=" * 80)
                    return
                else:
                    print("\n[Error] Invalid choice.")

    if conn:
        conn.close()

    print("\n" + "=" * 80)
    print("CURATION WIZARD COMPLETED")
    print("=" * 80)
    print(f"  • Newly Verified Folders:   {total_curated}")
    print(f"  • Skipped Unverified:       {total_skipped}")
    print("=" * 80)


def _inspect_and_edit_single_folder(item: dict, storage_root: Path, db_path: str):

    """Sub-menu to edit a single level-1 folder's tags, color, description, or reassign its Priority tier."""
    folder_path = item["path"]
    while True:
        finder_details = get_finder_tags_with_details(folder_path)
        print("\n" + "=" * 65)
        print(f"FOLDER INSPECTION & TAGGING: {item['name']}")
        print("=" * 65)
        print(f"  • Path:         {folder_path}")
        print(f"  • Parent Tier:  {item['parent_tier']} ({item['tier_color_name']})")
        desc_val = item.get("description")
        print(f"  • Description:  {desc_val if desc_val else 'None (stored in SQLite DB)'}")
        
        if item["size_bytes"] is not None and item["file_count"] is not None:
            print(f"  • DB Storage:   {format_size(item['size_bytes'])} across {item['file_count']:,} indexed files")

        if finder_details:
            tag_desc = ", ".join([f"{t['emoji']} {t['name']} ({t['color_name']})" for t in finder_details])
            print(f"  • Finder Tags:  {tag_desc}")
        else:
            print(f"  • Finder Tags:  ⚪ None (Untagged)")

        if item.get("db_tags"):
            print(f"  • SQLite Tags:  {', '.join(item['db_tags'])}")

        # Check iDrive status for this folder
        b_info = get_idrive_backup_sets()
        is_cov, cov_reason = check_idrive_backup_coverage(folder_path, b_info.get("all", set()))
        cov_icon = "✅ Included" if is_cov else "❌ Missing"
        print(f"  • iDrive Backup: {cov_icon} ({cov_reason})")

        print("\nActions:")
        print("  1. Apply standard Priority tags (Priority tier with color + folder name tag)")
        print("  2. Add / Edit folder description (Stored in SQLite database)")
        print("  3. Custom tag & Finder color (Add/edit custom tag and pick color)")
        print("  4. Move / Reassign to a different Priority Tier (e.g., Priority 2 -> Priority 3)")
        print("  5. Propagate current tags to all subfolders in this subtree")
        print("  6. Remove / Clear all tags from this folder")
        print("  7. Launch Curation Wizard on this folder's subdirectories (Scan & Triage)")
        print("  8. Add / Sync this folder to iDrive backup set (.plist)")
        print("  9. Return to folder list")

        sub_choice = input("\nSelect action (1-9): ").strip()

        if sub_choice == "1":
            tier_info = PRIORITY_TIER_CONFIG.get(item["parent_tier"].lower(), {"tag": item["parent_tier"], "color": item["tier_color"]})
            tags_to_apply = [(tier_info["tag"], tier_info["color"]), (item["name"], 0)]
            set_finder_tags(folder_path, tags_to_apply)
            _sync_directory_tags_to_db(folder_path, tags_to_apply, db_path)
            item["finder_details"] = get_finder_tags_with_details(folder_path)
            item["db_tags"] = [t[0].lower() for t in tags_to_apply]
            print(f"\n[Success] Standard tags applied: {tags_to_apply}")
        elif sub_choice == "2":
            cur_desc = item.get("description") or ""
            print(f"\nCurrent description: {cur_desc if cur_desc else '(empty)'}")
            new_desc = input("Enter new folder description (or press Enter to keep current): ").strip()
            if new_desc:
                _set_directory_description_in_db(folder_path, new_desc, db_path)
                item["description"] = new_desc
                print(f"\n[Success] Folder description saved to SQLite.")
            elif new_desc == "" and cur_desc:
                clear_desc = input("Clear existing description? [y/N]: ").strip().lower()
                if clear_desc == 'y':
                    _set_directory_description_in_db(folder_path, None, db_path)
                    item["description"] = None
                    print(f"\n[Success] Folder description cleared.")
        elif sub_choice == "3":
            tag_name = input(f"Enter custom tag name [Default: {item['name']}]: ").strip()
            tag_name = tag_name if tag_name else item["name"]

            print("\nSelect Finder Color:")
            for code, color_name in FINDER_COLOR_MAP.items():
                emoji = FINDER_COLOR_EMOJI.get(code, "⚪")
                print(f"  {code}: {emoji} {color_name}")
            c_input = input(f"Enter color number (0-7) [Default: {item['tier_color']}]: ").strip()
            color_code = int(c_input) if c_input.isdigit() and 0 <= int(c_input) <= 7 else item["tier_color"]

            new_tags = [(tag_name, color_code)]
            add_parent = input(f"Also keep parent Priority tag '{item['parent_tier']}'? [Y/n]: ").strip().lower()
            if add_parent != 'n':
                new_tags.append((item["parent_tier"], item["tier_color"]))

            set_finder_tags(folder_path, new_tags)
            _sync_directory_tags_to_db(folder_path, new_tags, db_path)
            item["finder_details"] = get_finder_tags_with_details(folder_path)
            item["db_tags"] = [t[0].lower() for t in new_tags]
            print(f"\n[Success] Custom tags applied: {new_tags}")
        elif sub_choice == "4":
            print("\nSelect Target Priority Tier:")
            for p_num in range(1, 5):
                p_name = f"Priority {p_num}"
                p_info = PRIORITY_TIER_CONFIG[p_name.lower()]
                p_emoji = FINDER_COLOR_EMOJI[p_info["color"]]
                marker = " (Current)" if p_name == item["parent_tier"] else ""
                print(f"  {p_num}: {p_emoji} {p_name} ({p_info['color_name']}){marker}")

            p_sel = input("Enter target priority number (1-4) or 'c' to cancel: ").strip()
            if not p_sel.isdigit() or int(p_sel) not in [1, 2, 3, 4]:
                print("Cancelled.")
                continue

            target_p_name = f"Priority {p_sel}"
            if target_p_name == item["parent_tier"]:
                print("\n[Notice] Folder is already in this Priority tier.")
                continue

            target_parent_dir = storage_root / target_p_name
            target_dest_path = target_parent_dir / item["name"]

            if target_dest_path.exists():
                print(f"\n[Warning] Destination '{target_dest_path}' already exists! Cannot move.")
                continue

            confirm_move = input(f"\nAre you sure you want to MOVE '{folder_path}' to '{target_dest_path}'? [y/N]: ").strip().lower()
            if confirm_move == 'y':
                target_parent_dir.mkdir(exist_ok=True)
                shutil.move(str(folder_path), str(target_dest_path))
                print(f"\n[Success] Moved directory to '{target_dest_path}'.")

                new_tier_info = PRIORITY_TIER_CONFIG[target_p_name.lower()]
                new_tags = [(new_tier_info["tag"], new_tier_info["color"]), (item["name"], 0)]
                set_finder_tags(target_dest_path, new_tags)

                if os.path.exists(db_path):
                    conn = get_db_connection(db_path)
                    cursor = conn.cursor()
                    old_path_str = str(folder_path.resolve())
                    new_path_str = str(target_dest_path.resolve())
                    cursor.execute("""
                        UPDATE directories
                        SET path = ? || SUBSTR(path, LENGTH(?) + 1)
                        WHERE path = ? OR path LIKE ? || '/%'
                    """, (new_path_str, old_path_str, old_path_str, old_path_str))
                    conn.commit()
                    conn.close()
                    print("[Success] Synchronized updated paths in SQLite database.")

                item["path"] = target_dest_path
                item["parent_tier"] = target_p_name
                item["tier_color"] = new_tier_info["color"]
                item["tier_color_name"] = new_tier_info["color_name"]
                item["tier_emoji"] = FINDER_COLOR_EMOJI[new_tier_info["color"]]
                item["finder_details"] = get_finder_tags_with_details(target_dest_path)
                folder_path = target_dest_path
        elif sub_choice == "5":
            confirm_prop = input(f"\nPropagate tags recursively to all subfolders of '{item['name']}'? [y/N]: ").strip().lower()
            if confirm_prop == 'y':
                tier_info = PRIORITY_TIER_CONFIG.get(item["parent_tier"].lower(), {"tag": item["parent_tier"], "color": item["tier_color"]})
                tags_to_prop = [(tier_info["tag"], tier_info["color"]), (item["name"], 0)]
                count_prop = 0
                for root_dir, dirnames, _ in os.walk(folder_path):
                    for d in dirnames:
                        sub_p = Path(root_dir) / d
                        set_finder_tags(sub_p, tags_to_prop)
                        _sync_directory_tags_to_db(sub_p, tags_to_prop, db_path)
                        count_prop += 1
                print(f"\n[Success] Propagated tags across {count_prop:,} subdirectories.")
        elif sub_choice == "6":
            confirm_clear = input(f"\nClear all Finder & DB tags from '{item['name']}'? [y/N]: ").strip().lower()
            if confirm_clear == 'y':
                remove_finder_tags(folder_path)
                if os.path.exists(db_path):
                    conn = get_db_connection(db_path)
                    cursor = conn.cursor()
                    res_p = str(folder_path.resolve())
                    cursor.execute("SELECT id FROM directories WHERE path = ?", (res_p,))
                    row = cursor.fetchone()
                    if row:
                        cursor.execute("DELETE FROM directory_tags WHERE directory_id = ?", (row[0],))
                        conn.commit()
                    conn.close()
                item["finder_details"] = []
                item["db_tags"] = []
                print("\n[Success] All tags removed.")
        elif sub_choice == "7":
            curation_wizard_interactive(db_path, storage_root, target_l1_dir=folder_path)
        elif sub_choice == "8":
            confirm_idrive = input(f"\nAdd '{folder_path}' to iDrive Backup Set? [y/N]: ").strip().lower()
            if confirm_idrive == 'y':
                ok, msg = add_folder_to_idrive_backup_set(folder_path)
                print(f"\n{'[Success]' if ok else '[Error]'} {msg}")
                if ok:
                    print("[Important] If IDrive is currently running, quit and reopen IDrive to reload the backup set.")
        elif sub_choice == "9":
            break
        else:
            print("\n[Error] Invalid choice.")

def get_idrive_backup_sets() -> dict:
    """Discovers and parses iDrive backup sets from IDriveforMac application support plist files.
    Returns dict with keys:
      'main': list of paths from backupReferenceFile.plist
      'network': list of paths from NetworkDriveBackupSet.plist
      'local': list of paths from localBackupReferenceFile.plist
      'all': set of all normalized backed-up paths
      'account_dir': str path to user's IDrive account directory
    """
    base_dir = os.path.expanduser('~/Library/Application Support/IDriveforMac')
    results = {'main': [], 'network': [], 'local': [], 'all': set(), 'account_dir': None}
    if not os.path.isdir(base_dir):
        return results

    # Locate account directories
    account_dirs = [os.path.join(base_dir, d) for d in os.listdir(base_dir) if os.path.isdir(os.path.join(base_dir, d)) and "@" in d]
    if account_dirs:
        results['account_dir'] = account_dirs[0]

    # Main online backup set
    for p in glob.glob(f'{base_dir}/**/backupReferenceFile.plist', recursive=True):
        try:
            with open(p, 'rb') as f:
                items = plistlib.load(f)
                if isinstance(items, list):
                    results['main'].extend(items)
                    results['all'].update([os.path.normpath(i) for i in items])
        except Exception:
            pass

    # Network / External drive backup set
    for p in glob.glob(f'{base_dir}/**/NetworkDriveBackupSet.plist', recursive=True):
        try:
            with open(p, 'rb') as f:
                items = plistlib.load(f)
                if isinstance(items, list):
                    results['network'].extend(items)
                    results['all'].update([os.path.normpath(i) for i in items])
        except Exception:
            pass

    # Local backup set
    for p in glob.glob(f'{base_dir}/**/localBackupReferenceFile.plist', recursive=True):
        try:
            with open(p, 'rb') as f:
                items = plistlib.load(f)
                if isinstance(items, list):
                    results['local'].extend(items)
                    results['all'].update([os.path.normpath(i) for i in items])
        except Exception:
            pass

    results['main'] = sorted(list(set(results['main'])))
    results['network'] = sorted(list(set(results['network'])))
    results['local'] = sorted(list(set(results['local'])))
    return results

def check_idrive_backup_coverage(folder_path: str | Path, backup_items: set) -> tuple[bool, str]:
    """Checks whether folder_path or any of its parent folders are covered in backup_items."""
    p_norm = os.path.normpath(str(folder_path))
    for b in backup_items:
        b_norm = os.path.normpath(b)
        if p_norm == b_norm:
            return True, f"Direct Match ({b})"
        if p_norm.startswith(b_norm + os.sep):
            return True, f"Covered by Parent ({b})"
    # Check if children are in backup items (partial coverage)
    child_matches = [b for b in backup_items if b.startswith(p_norm + os.sep)]
    if child_matches:
        return False, f"Partial Match ({len(child_matches)} sub-items backed up)"
    return False, "Not in iDrive backup set"

def add_folder_to_idrive_backup_set(folder_path: str | Path) -> tuple[bool, str]:
    """Safely adds a folder path to the appropriate iDrive backup set plist file."""
    norm_p = os.path.normpath(str(folder_path))
    if not os.path.exists(norm_p):
        return False, f"Path does not exist on disk: {norm_p}"

    base_dir = os.path.expanduser('~/Library/Application Support/IDriveforMac')
    account_dirs = [os.path.join(base_dir, d) for d in os.listdir(base_dir) if os.path.isdir(os.path.join(base_dir, d)) and "@" in d] if os.path.isdir(base_dir) else []
    if not account_dirs:
        return False, "Could not locate iDrive account folder in Application Support."

    acc_dir = account_dirs[0]
    # External volumes (/Volumes/...) belong to NetworkDriveBackupSet.plist in IDrive for Mac
    if norm_p.startswith("/Volumes/"):
        target_plist = os.path.join(acc_dir, "NetworkDriveBackupSet.plist")
        set_name = "Network / External Drive Backup Set"
    else:
        target_plist = os.path.join(acc_dir, "backupReferenceFile.plist")
        set_name = "Main Backup Set"

    try:
        current_items = []
        if os.path.exists(target_plist):
            bak_path = f"{target_plist}.bak.{int(time.time())}"
            shutil.copy2(target_plist, bak_path)
            with open(target_plist, 'rb') as f:
                data = plistlib.load(f)
                if isinstance(data, list):
                    current_items = list(data)

        if norm_p in current_items:
            return True, f"Already present in {set_name}."

        current_items.append(norm_p)
        with open(target_plist, 'wb') as f:
            plistlib.dump(current_items, f, fmt=plistlib.FMT_XML)

        return True, f"Successfully added to {set_name} ({target_plist})."
    except Exception as e:
        return False, f"Failed to update iDrive plist: {e}"

def audit_idrive_backup_interactive(db_path: str, target_tiers: list | str | None = None):
    """Interactively audits Priority 1 and/or Priority 2 folders against active iDrive backup sets."""
    print("\n" + "=" * 85)
    print("  iDRIVE BACKUP INCLUSION AUDIT & VERIFICATION")
    print("=" * 85)

    backup_info = get_idrive_backup_sets()
    all_backup_items = backup_info["all"]
    account_dir = backup_info.get("account_dir")

    print(f"  • iDrive Account Directory:  {account_dir if account_dir else 'Not found'}")
    print(f"  • Main Backup Set:           {len(backup_info['main'])} folders configured")
    print(f"  • External/Network Drives:   {len(backup_info['network'])} folders configured")
    print(f"  • Total Backed Up Items:     {len(all_backup_items)} items")

    # Check if IDrive app is running
    idrive_running = False
    try:
        proc = subprocess.run(["pgrep", "-f", "/Applications/IDrive.app"], capture_output=True, text=True)
        idrive_running = (proc.returncode == 0)
    except Exception:
        pass
    status_icon = "🟢 Running" if idrive_running else "⚪ Not Running"
    print(f"  • IDrive Client Process:     {status_icon}")

    selected_tiers = ["priority 1", "priority 2"]
    if target_tiers is None:
        print("\nSelect Priority Tiers to Audit:")
        print("  1. Priority 1 & Priority 2 (Active Personal & Systems/Dev Targets) [Default]")
        print("  2. Priority 1 only (Critical active personal data)")
        print("  3. Priority 2 only (Systems, Dev, User Profiles, References)")
        print("  4. All Mapped Locations (Priority 1-4)")
        sc = input("Choice [1-4, default: 1]: ").strip()
        if sc == "2":
            selected_tiers = ["priority 1"]
        elif sc == "3":
            selected_tiers = ["priority 2"]
        elif sc == "4":
            selected_tiers = None
        else:
            selected_tiers = ["priority 1", "priority 2"]
    elif isinstance(target_tiers, str):
        selected_tiers = [target_tiers.lower()]
    elif isinstance(target_tiers, list):
        selected_tiers = [t.lower() for t in target_tiers]

    locations = get_priority_locations(db_path, active_only=True)
    if selected_tiers is not None:
        locations = [l for l in locations if l["priority_tier"].lower() in selected_tiers]

    if not locations:
        print(f"\n[Notice] No active locations found matching selected scope.")
        input("\nPress Enter to return...")
        return

    conn = get_db_connection(db_path) if os.path.exists(db_path) else None
    cursor = conn.cursor() if conn else None

    audit_rows = []

    for loc in locations:
        loc_path = loc["path"]
        loc_label = loc["label"]
        tier = loc["priority_tier"].title()

        # Check the location root itself
        loc_covered, loc_reason = check_idrive_backup_coverage(loc_path, all_backup_items)
        audit_rows.append({
            "is_root": True,
            "tier": tier,
            "label": loc_label,
            "path": loc_path,
            "name": f"📍 [ROOT] {loc_label}",
            "covered": loc_covered,
            "reason": loc_reason,
            "size_bytes": None,
            "file_count": None
        })

        # Check level-1 categories under this location
        if loc_path.exists():
            for sub in sorted(loc_path.iterdir()):
                if sub.is_dir() and not sub.name.startswith('.'):
                    sub_covered, sub_reason = check_idrive_backup_coverage(sub, all_backup_items)
                    fc, sb = None, None
                    if cursor:
                        res_p = str(sub.resolve())
                        cursor.execute("""
                            SELECT COUNT(f.id), COALESCE(SUM(f.size_bytes), 0)
                            FROM directories d
                            LEFT JOIN files f ON d.id = f.directory_id
                            WHERE d.path = ? OR d.path LIKE ? || '/%'
                        """, (res_p, res_p))
                        row = cursor.fetchone()
                        if row and row[0] is not None and row[0] > 0:
                            fc, sb = row[0], row[1]
                    audit_rows.append({
                        "is_root": False,
                        "tier": tier,
                        "label": loc_label,
                        "path": sub,
                        "name": sub.name,
                        "covered": sub_covered,
                        "reason": sub_reason,
                        "size_bytes": sb,
                        "file_count": fc
                    })

    if conn:
        conn.close()

    title_scope = " & ".join([t.upper() for t in selected_tiers]) if selected_tiers else "ALL PRIORITY TIERS"
    print("\n" + "=" * 98)
    print(f"  BACKUP VERIFICATION RESULTS: {title_scope}")
    print("=" * 98)
    print(f"{'#':<4} {'Priority Tier':<14} {'Target Folder':<32} {'Size / Files':<18} {'iDrive Status'}")
    print("-" * 98)

    missing_count = 0
    covered_count = 0

    curr_t = None
    for idx, row in enumerate(audit_rows, 1):
        if row["tier"] != curr_t:
            curr_t = row["tier"]
            t_clean = curr_t.lower()
            t_conf = PRIORITY_TIER_CONFIG.get(t_clean, {"color": 0})
            t_em = FINDER_COLOR_EMOJI.get(t_conf["color"], "⚪")
            print(f"\n{t_em} [{curr_t}]")

        if row["size_bytes"] is not None and row["file_count"] is not None:
            sz_str = f"{format_size(row['size_bytes'])} ({row['file_count']:,})"
        else:
            sz_str = "--"

        if row["covered"]:
            covered_count += 1
            status_str = f"✅ INCLUDED ({row['reason']})"
        else:
            missing_count += 1
            status_str = f"❌ MISSING ({row['reason']})"

        name_display = row["name"]
        if row["is_root"]:
            name_display = f"📍 {name_display[:28]}"

        print(f"{idx:<4} {row['tier']:<14} {name_display:<32} {sz_str:<18} {status_str}")
        print(f"     ↳ Path: {row['path']}")

    print("-" * 98)
    print(f"Summary: {covered_count} covered in iDrive, {missing_count} MISSING from backup list.")

    if missing_count > 0:
        print(f"\n⚠️  ACTION REQUIRED: {missing_count} folder(s) in {title_scope} are NOT currently backed up to iDrive!")
    else:
        print(f"\n✅ All folders in {title_scope} are confirmed in the active iDrive backup set!")

    while True:
        print("\nOptions:")
        print("  1. Add missing Location Root(s) to iDrive backup set (.plist)")
        print("  2. Select individual Category Folders to add to iDrive backup set (.plist)")
        print("  3. View current active items in iDrive backup sets (Main online & External sets)")
        print("  4. View step-by-step instructions for adding folders in iDrive Desktop GUI")
        print("  5. Return to Tagging Review menu")

        act = input("\nSelect option (1-5): ").strip()
        if act == "1":
            root_targets = [r for r in audit_rows if r["is_root"] and not r["covered"]]
            if not root_targets:
                print("\n[Notice] All location roots in this scope are already covered in iDrive.")
                continue
            for r_item in root_targets:
                r_p = r_item["path"]
                confirm = input(f"Add [{r_item['tier']}] '{r_p}' to iDrive Backup Set? [y/N]: ").strip().lower()
                if confirm == 'y':
                    ok, msg = add_folder_to_idrive_backup_set(r_p)
                    print(f"  • [{r_item['tier']}] {r_p}: {'[Success]' if ok else '[Error]'} {msg}")
            print("\n[Important] If IDrive is currently running, quit and reopen IDrive to reload the backup set.")
        elif act == "2":
            sub_targets = [r for r in audit_rows if not r["is_root"] and not r["covered"]]
            if not sub_targets:
                print("\n[Notice] All category folders in this scope are already covered in iDrive.")
                continue
            print("\nMissing Category Folders:")
            for s_idx, st in enumerate(sub_targets, 1):
                print(f"  {s_idx}. [{st['tier']}] {st['name']} ({st['path']})")
            sel_s = input(f"\nEnter folder numbers to add (e.g. '1, 2', 'all', or 'c' to cancel): ").strip().lower()
            if sel_s == 'c' or not sel_s:
                continue
            chosen = []
            if sel_s == 'all':
                chosen = sub_targets
            else:
                for part in sel_s.replace(' ', ',').split(','):
                    if part.isdigit() and 1 <= int(part) <= len(sub_targets):
                        chosen.append(sub_targets[int(part) - 1])
            if not chosen:
                print("No valid folders selected.")
                continue
            for ch in chosen:
                ok, msg = add_folder_to_idrive_backup_set(ch["path"])
                print(f"  • [{ch['tier']}] {ch['name']}: {'[Success]' if ok else '[Error]'} {msg}")
            print("\n[Important] If IDrive is currently running, quit and reopen IDrive to reload the backup set.")
        elif act == "3":
            print("\n--- CURRENT iDRIVE BACKUP SET ---")
            print("Main Online Backup Set (Local):")
            for m in backup_info["main"]:
                print(f"  • {m}")
            print("\nExternal / Network Drives Backup Set:")
            for n in backup_info["network"]:
                print(f"  • {n}")
        elif act == "4":
            print("\n" + "=" * 65)
            print("  HOW TO ADD PRIORITY 1 & 2 FOLDERS IN iDRIVE DESKTOP GUI")
            print("=" * 65)
            print("1. Open the IDrive application on your Mac.")
            print("2. Navigate to the 'Backup' tab on the left sidebar.")
            print("3. Click 'Change...' or browse down the folder tree.")
            print("4. Expand 'Volumes' -> 'LaCie' -> 'Storage'.")
            print("5. Check the box for 'Priority 1' and 'Priority 2' (or individual subfolders).")
            print("6. Click 'Save' / 'Apply'.")
            print("7. Run 'audit_idrive_backup_interactive' here to confirm coverage!")
            print("=" * 65)
        elif act == "5":
            break
        else:
            print("[Error] Invalid choice.")

def tag_review_priority_folders_interactive(db_path: str):
    """Interactive review and editing of level-1 folders across all mapped Priority locations."""
    print("\n" + "=" * 70)
    print("  TAGGING REVIEW & MANAGEMENT (Priority Locations & Level-1 Folders)")
    print("=" * 70)

    while True:
        locations = get_priority_locations(db_path, active_only=True)
        if not locations:
            # Seed defaults
            get_priority_locations(db_path, active_only=True)
            locations = get_priority_locations(db_path, active_only=True)

        tier_map = defaultdict(list)
        for loc in locations:
            t_num = 99
            for part in loc["priority_tier"].split():
                if part.isdigit():
                    t_num = int(part)
            tier_map[t_num].append(loc)

        priority_tier_desc = {}
        level1_items = []
        conn = get_db_connection(db_path) if os.path.exists(db_path) else None
        cursor = conn.cursor() if conn else None

        for p_num in sorted(tier_map.keys()):
            tier_name = f"Priority {p_num}"
            tier_clean = f"priority {p_num}"
            tier_info = PRIORITY_TIER_CONFIG.get(tier_clean, {"tag": tier_name, "color": 0, "color_name": "None"})
            tier_color_emoji = FINDER_COLOR_EMOJI.get(tier_info["color"], "⚪")

            loc_list = tier_map[p_num]
            # Get tier description from primary location or defaults
            for loc in loc_list:
                if cursor and loc["path"].exists():
                    res_p = str(loc["path"].resolve())
                    cursor.execute("SELECT description FROM directories WHERE path = ?", (res_p,))
                    desc_row = cursor.fetchone()
                    if desc_row and desc_row[0]:
                        priority_tier_desc[tier_name] = desc_row[0]
                        break
            if tier_name not in priority_tier_desc:
                def_desc = DEFAULT_PRIORITY_DESCRIPTIONS.get(tier_clean, "")
                priority_tier_desc[tier_name] = def_desc

            for loc in loc_list:
                loc_path = loc["path"]
                loc_label = loc["label"]
                if not loc_path.exists():
                    continue

                sub_dirs = [s for s in sorted(loc_path.iterdir()) if s.is_dir() and not s.name.startswith('.')]
                for s_dir in sub_dirs:
                    finder_details = get_finder_tags_with_details(s_dir)
                    file_count = None
                    size_bytes = None
                    db_tags = []
                    folder_desc = None
                    if cursor:
                        res_p = str(s_dir.resolve())
                        cursor.execute("""
                            SELECT COUNT(f.id), COALESCE(SUM(f.size_bytes), 0)
                            FROM directories d
                            LEFT JOIN files f ON d.id = f.directory_id
                            WHERE d.path = ? OR d.path LIKE ? || '/%'
                        """, (res_p, res_p))
                        row = cursor.fetchone()
                        if row and row[0] is not None and row[0] > 0:
                            file_count, size_bytes = row[0], row[1]
                        
                        cursor.execute("""
                            SELECT dt.tag_name
                            FROM directory_tags dt
                            JOIN directories d ON dt.directory_id = d.id
                            WHERE d.path = ?
                        """, (res_p,))
                        db_tags = [r[0] for r in cursor.fetchall()]

                        cursor.execute("SELECT description FROM directories WHERE path = ?", (res_p,))
                        d_row = cursor.fetchone()
                        if d_row and d_row[0]:
                            folder_desc = d_row[0]
                        else:
                            def_l1_desc = DEFAULT_LEVEL1_DESCRIPTIONS.get((tier_clean, s_dir.name.lower()))
                            if def_l1_desc:
                                _set_directory_description_in_db(s_dir, def_l1_desc, db_path)
                                folder_desc = def_l1_desc

                    level1_items.append({
                        "path": s_dir,
                        "name": s_dir.name,
                        "parent_tier": tier_name,
                        "loc_label": loc_label,
                        "loc_path": loc_path,
                        "tier_color": tier_info["color"],
                        "tier_color_name": tier_info["color_name"],
                        "tier_emoji": tier_color_emoji,
                        "finder_details": finder_details,
                        "file_count": file_count,
                        "size_bytes": size_bytes,
                        "db_tags": db_tags,
                        "description": folder_desc
                    })

        if conn:
            conn.close()

        # Check iDrive backup sets
        idrive_info = get_idrive_backup_sets()
        all_backup_items = idrive_info["all"]

        print("\n" + "=" * 98)
        print("  STORAGE LEVEL-1 FOLDERS & PRIORITY LOCATIONS REVIEW")
        print("=" * 98)
        print(f"{'#':<4} {'Parent Tier':<14} {'Folder Name':<32} {'Size / Files':<18} {'Finder Color & Tags'}")
        print("-" * 98)

        curr_tier = None
        curr_loc = None
        for idx, item in enumerate(level1_items, 1):
            if item["parent_tier"] != curr_tier:
                curr_tier = item["parent_tier"]
                curr_loc = None
                t_desc = priority_tier_desc.get(curr_tier, "")
                desc_label = f" — \"{t_desc}\"" if t_desc else ""
                print(f"\n{item['tier_emoji']} [{curr_tier}] ({item['tier_color_name']}){desc_label}")

                # If Priority 1 or Priority 2, check if all mapped locations & items are in iDrive
                if curr_tier.lower() in ["priority 1", "priority 2"]:
                    tier_missing = [it for it in level1_items if it["parent_tier"].lower() == curr_tier.lower() and not check_idrive_backup_coverage(it["path"], all_backup_items)[0]]
                    if tier_missing:
                        print(f"  ⚠️  Notice: {curr_tier} folders are NOT confirmed in iDrive backup set! Type 'idrive' to review & fix.")
                    else:
                        print(f"  ☁️  iDrive Status: All {curr_tier} folders are confirmed in the active backup set.")

            loc_key = (item["loc_label"], str(item["loc_path"]))
            if loc_key != curr_loc:
                curr_loc = loc_key
                print(f"  📍 Location: {item['loc_label']} ({item['loc_path']})")

            if item["size_bytes"] is not None and item["file_count"] is not None:
                size_str = f"{format_size(item['size_bytes'])} ({item['file_count']:,})"
            else:
                size_str = "--"

            if not item["finder_details"]:
                tag_display = "⚪ Untagged ⚠️"
            else:
                tag_parts = []
                for td in item["finder_details"]:
                    c_emoji = td["emoji"]
                    t_name = td["name"]
                    if td["color"] > 0:
                        tag_parts.append(f"{c_emoji} {td['color_name']}: {t_name}")
                    else:
                        tag_parts.append(f"{t_name}")
                tag_display = " | ".join(tag_parts)

            # For Priority 1 & Priority 2, append iDrive coverage badge
            if item["parent_tier"].lower() in ["priority 1", "priority 2"]:
                is_cov, _ = check_idrive_backup_coverage(item["path"], all_backup_items)
                idrive_badge = " [☁️ iDrive: ✅]" if is_cov else " [☁️ iDrive: ❌ Missing]"
                tag_display += idrive_badge

            print(f"{idx:<4} {item['parent_tier']:<14} {item['name']:<32} {size_str:<18} {tag_display}")
            if item.get("description"):
                print(f"     ↳ 📝 {item['description']}")

        print("-" * 98)
        print(f"Total Folders: {len(level1_items)}")
        print("\nOptions:")
        print(f"  • Enter folder number (1-{len(level1_items)}) to inspect & edit tags / color / description / tier")
        print("  • 'v' / 'status' - Curation & Verification Report (Separated Approved vs Unapproved folders)")
        print("  • 'loc' - Manage Priority Locations (Add / Edit / Remove mapped folders for Priority 1-4)")
        print("  • 'idrive' - Audit iDrive backup inclusion (Check Priority 1 & 2 folders in iDrive)")
        print("  • 'w' - Launch Sequential Curation Wizard (Triage subfolders across locations)")
        print("  • 'p1'-'p4' - Edit description of a top-level Priority tier (Priority 1-4)")
        print("  • 'a' - Auto-tag untagged folders with parent Priority & category")
        print("  • 'reset-tags' - Reset subfolder tags & verification (Preserve level-1, clear level-2+ tags)")
        print("  • 'r' - Refresh view from filesystem")
        print("  • 'b' - Return to main menu")

        action_choice = input("\nSelect option or folder number: ").strip().lower()

        if action_choice == 'b':
            break
        elif action_choice == 'r':
            continue
        elif action_choice in ['v', 'status']:
            generate_curation_verification_report(db_path)
            continue
        elif action_choice == 'idrive':
            audit_idrive_backup_interactive(db_path, ["priority 1", "priority 2"])
            continue
        elif action_choice == 'loc':
            manage_priority_locations_interactive(db_path)
            continue
        elif action_choice == 'w':
            curation_wizard_interactive(db_path)
            continue
        elif action_choice == 'reset-tags':
            reset_subfolder_tags_and_verification(db_path)
            continue
        elif action_choice in ['p1', 'p2', 'p3', 'p4']:
            p_num = action_choice[1]
            p_target_name = f"Priority {p_num}"
            cur_p_desc = priority_tier_desc.get(p_target_name, "")
            print(f"\n--- EDIT DESCRIPTION FOR TOP-LEVEL {p_target_name} ---")
            print(f"Current description: {cur_p_desc if cur_p_desc else '(empty)'}")
            new_p_desc = input(f"Enter new description for {p_target_name} (or Enter to keep): ").strip()
            if new_p_desc:
                # Update across mapped locations for this tier
                for loc in tier_map.get(int(p_num), []):
                    if loc["path"].exists():
                        _set_directory_description_in_db(loc["path"], new_p_desc, db_path)
                priority_tier_desc[p_target_name] = new_p_desc
                print(f"\n[Success] Updated description for {p_target_name} in SQLite database.")
            continue
        elif action_choice == 'a':
            untagged = [it for it in level1_items if not it["finder_details"] or not any(it["parent_tier"].lower() in td["name"].lower() for td in it["finder_details"])]
            if not untagged:
                print("\n[Notice] All level-1 folders already possess their parent Priority tags!")
                continue

            print(f"\nFound {len(untagged)} folders needing standard Priority tags:")
            for u in untagged:
                print(f"  • [{u['parent_tier']}] {u['name']} -> {u['tier_emoji']} {u['parent_tier']} ({u['tier_color_name']}) + '{u['name']}'")

            confirm_a = input("\nApply tags to these folders in Finder and SQLite? [y/N]: ").strip().lower()
            if confirm_a == 'y':
                for u in untagged:
                    tags_to_apply = [(u["parent_tier"], u["tier_color"]), (u["name"], 0)]
                    set_finder_tags(u["path"], tags_to_apply)
                    _sync_directory_tags_to_db(u["path"], tags_to_apply, db_path)
                print(f"\n[Success] Standard Priority tags applied to {len(untagged)} folders.")
            continue
        elif action_choice.isdigit():
            idx_sel = int(action_choice)
            if idx_sel < 1 or idx_sel > len(level1_items):
                print(f"\n[Error] Invalid folder number. Choose between 1 and {len(level1_items)}.")
                continue

            sel_item = level1_items[idx_sel - 1]
            _inspect_and_edit_single_folder(sel_item, sel_item["loc_path"], db_path)
        else:
            print("\n[Error] Invalid choice.")


def tag_manager_interactive(db_path: str):
    """Submenu for auto-tagging, manual tagging, tag clearing, and Finder-to-DB sync."""
    while True:
        print("\n" + "=" * 55)
        print("  FOLDER TAGGING & FINDER SYNC MANAGER  ")
        print("=" * 55)
        print("1. Review & manage Priority level-1 folders (Finder colors, tags & tier reassign)")
        print("2. Auto-tag Storage tree by Priority & Category (Finder Colors + DB Sync)")
        print("3. Manually tag a directory (Custom text & Finder color)")
        print("4. Remove / clear tags from a directory")
        print("5. Re-sync Finder tags from disk into SQLite Database")
        print("6. Return to main menu")

        choice = input("\nSelect option (1-6): ").strip()

        if choice == "1":
            tag_review_priority_folders_interactive(db_path)
        elif choice == "2":
            auto_tag_priority_tree_interactive(db_path)
        elif choice == "3":
            manual_tag_directory_interactive(db_path)
        elif choice == "4":
            clear_tags_directory_interactive(db_path)
        elif choice == "5":
            resync_finder_tags_interactive(db_path)
        elif choice == "6":
            break
        else:
            print("\n[Error] Invalid option.")


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

def prune_missing_records(db_path: str):
    """Verifies all indexed directories and files against the filesystem, removing deleted items."""
    if not os.path.exists(db_path):
        print("\n[Notice] No database found. Run a scan first.")
        return

    print("\n--- PRUNE & SYNC DELETED RECORDS ---")
    conn = get_db_connection(db_path)
    cursor = conn.cursor()

    cursor.execute("SELECT id, path FROM directories")
    all_dirs = cursor.fetchall()

    print(f"Checking {len(all_dirs):,} directories against filesystem...")
    del_dirs = 0
    del_files = 0

    for did, dpath in all_dirs:
        if not os.path.exists(dpath):
            cursor.execute("SELECT COUNT(*) FROM files WHERE directory_id = ?", (did,))
            del_files += cursor.fetchone()[0]
            cursor.execute("DELETE FROM directories WHERE id = ?", (did,))
            del_dirs += 1

    # Check remaining files in existing directories
    cursor.execute("SELECT f.id, f.name, d.path FROM files f JOIN directories d ON f.directory_id = d.id")
    all_files = cursor.fetchall()
    print(f"Checking {len(all_files):,} files against filesystem...")

    for fid, fname, dpath in all_files:
        full_path = os.path.join(dpath, fname)
        if not os.path.exists(full_path):
            cursor.execute("DELETE FROM files WHERE id = ?", (fid,))
            del_files += 1

    conn.commit()
    conn.close()

    print("\n" + "=" * 65)
    print(f"[Success] Pruning complete!")
    print(f"  • Removed missing folders: {del_dirs:,}")
    print(f"  • Removed deleted files:   {del_files:,}")
    print("=" * 65)

def migrate_non_media_interactive(db_path: str):
    """Interactively segregates non-media files from a media directory to a NonMediaFiles destination while preserving folder structure."""
    print("\n--- SEGREGATE NON-MEDIA FILES ---")
    last_dir = get_app_setting(db_path, "last_scanned_dir")
    if last_dir and os.path.exists(last_dir):
        prompt_msg = f"Enter source media folder [Default: {last_dir}]: "
    else:
        prompt_msg = "Enter source media folder (e.g., /Volumes/LaCie/Storage/Priority 4/Pictures): "

    source_input = input(prompt_msg).strip().strip('"').strip("'")
    if not source_input and last_dir and os.path.exists(last_dir):
        source_path = last_dir
    else:
        source_path = source_input

    source_root = Path(source_path)
    if not source_root.exists() or not source_root.is_dir():
        print(f"\n[Error] Directory '{source_path}' does not exist.")
        return

    default_dest = source_root.parent / "NonMediaFiles"
    dest_input = input(f"Enter target destination folder [Default: {default_dest}]: ").strip().strip('"').strip("'")
    dest_root = Path(dest_input) if dest_input else default_dest

    purge_junk = input("Purge legacy thumbnail/metadata caches (Thumbs.db, .picasa.ini, .pal, .pmp, etc.)? [Y/n]: ").strip().lower()
    do_purge = purge_junk != 'n'

    MEDIA_EXTS = {
        '.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff', '.tif', '.webp', '.heic', '.raw', '.cr2', '.nef',
        '.mp4', '.mkv', '.avi', '.mov', '.wmv', '.flv', '.webm', '.m4v', '.3gp', '.mpg', '.mpeg', '.vob', '.mts', '.m2ts'
    }

    DELETE_EXTS = {'.pal', '.pmp', '.tmp', '.bak'}

    def is_junk_cache(f_name, ext_lower):
        fn_lower = f_name.lower()
        if fn_lower in ('thumbs.db', '.picasa.ini', 'picasa.ini', '.ds_store', '._.ds_store', 'desktop.ini') or fn_lower.startswith('desktop (') or f_name.startswith('._'):
            return True
        if ext_lower in DELETE_EXTS:
            return True
        if ext_lower == '.db' and any(k in fn_lower for k in ('thumb', 'picasa', 'preview', 'album', 'facetemplate')):
            return True
        return False

    print(f"\nScanning '{source_root}' to analyze file distribution...")
    to_keep_media = []
    to_delete = []
    to_move = []

    for root, dirs, files in os.walk(source_root):
        for f in files:
            fp = Path(root) / f
            try:
                sz = fp.stat().st_size
                ext_lower = fp.suffix.lower()
                rel = fp.relative_to(source_root)
                if ext_lower in MEDIA_EXTS:
                    to_keep_media.append((fp, sz))
                elif do_purge and is_junk_cache(f, ext_lower):
                    to_delete.append((fp, sz, f))
                else:
                    to_move.append((fp, sz, rel, dest_root / rel))
            except Exception:
                pass

    print("\n" + "=" * 65)
    print("MIGRATION PREVIEW")
    print("=" * 65)
    print(f"  • Media files to KEEP in source:       {len(to_keep_media):,} files ({format_size(sum(x[1] for x in to_keep_media))})")
    if do_purge:
        print(f"  • Junk/Cache files to DELETE:          {len(to_delete):,} files ({format_size(sum(x[1] for x in to_delete))})")
    print(f"  • Non-media files to MOVE:             {len(to_move):,} files ({format_size(sum(x[1] for x in to_move))})")
    print(f"  • Destination:                         {dest_root}")
    print("=" * 65)

    if not to_move and not to_delete:
        print("\n[Notice] No non-media files or junk caches found to process.")
        return

    confirm = input("\nProceed with migration? [y/N]: ").strip().lower()
    if confirm != 'y':
        print("\n[Cancelled] Migration aborted by user.")
        return

    dest_root.mkdir(parents=True, exist_ok=True)
    deleted_count = 0
    deleted_bytes = 0
    moved_count = 0
    moved_bytes = 0
    errors = []

    print("\nExecuting migration...")

    # 1. Delete caches
    for fp, sz, f in to_delete:
        try:
            fp.unlink()
            deleted_count += 1
            deleted_bytes += sz
        except Exception as e:
            errors.append(f"Delete failed: {fp} ({e})")

    # 2. Move non-media
    for fp, sz, rel, dest_fp in to_move:
        try:
            dest_fp.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(fp), str(dest_fp))
            moved_count += 1
            moved_bytes += sz
        except Exception as e:
            errors.append(f"Move failed: {fp} -> {dest_fp} ({e})")

    # 3. Prune empty folders in source
    pruned_dirs = 0
    for root, dirs, files in os.walk(source_root, topdown=False):
        rp = Path(root)
        if rp != source_root:
            try:
                if not any(rp.iterdir()):
                    rp.rmdir()
                    pruned_dirs += 1
            except Exception:
                pass

    print("\n" + "=" * 65)
    print("[Success] Non-Media Migration Complete!")
    print(f"  • Media files preserved:               {len(to_keep_media):,} ({format_size(sum(x[1] for x in to_keep_media))})")
    if do_purge:
        print(f"  • Junk/Cache files deleted:            {deleted_count:,} ({format_size(deleted_bytes)})")
    print(f"  • Non-media files moved:               {moved_count:,} ({format_size(moved_bytes)})")
    print(f"  • Empty folders pruned from source:    {pruned_dirs:,}")
    if errors:
        print(f"  • Errors encountered:                  {len(errors)}")
        for err in errors[:5]:
            print(f"    - {err}")
    print("=" * 65)

    # Option to auto-sync DB
    if os.path.exists(db_path):
        sync_db = input("\nReconcile database (prune deleted records & update DB)? [Y/n]: ").strip().lower()
        if sync_db != 'n':
            prune_missing_records(db_path)

def detect_and_resolve_duplicates_interactive(db_path: str):
    """Interactively detects duplicate files, identifies keeper copies inside the Storage repository, and allows safe cleanup of redundant copies."""
    if not os.path.exists(db_path):
        print("\n[Notice] No database found. Run a scan first.")
        return

    print("\n" + "=" * 70)
    print("  INTERACTIVE DUPLICATE DETECTION & RESOLVER  ")
    print("=" * 70)

    # 1. Storage repository root (to preserve)
    last_dir = get_app_setting(db_path, "last_scanned_dir")
    default_storage = "/Volumes/LaCie/Storage"
    if not os.path.exists(default_storage) and last_dir:
        default_storage = last_dir

    storage_input = input(f"Enter primary Storage repository path to PRESERVE [Default: {default_storage}]: ").strip().strip('"').strip("'")
    storage_root = storage_input if storage_input else default_storage
    storage_root = str(Path(storage_root).resolve())

    # 2. Number of duplicate groups to inspect
    limit_input = input("How many top duplicate groups to inspect? (e.g., 50, 100, or 'all') [Default: 50]: ").strip().lower()
    if limit_input == "all":
        limit = None
    else:
        try:
            limit = int(limit_input) if limit_input else 50
        except ValueError:
            limit = 50

    # 3. Category filter
    cat_input = input("Filter by category (video/image/audio/document/archive/code/other, or Enter for all): ").strip().lower()

    # 4. Cleanup Scope
    print("\nCleanup Scope:")
    print("  1. Clean OUTSIDE Storage only (Safest: preserves Storage copies, deletes copies in staging/restore paths)")
    print("  2. Full Deduplication (Preserves 1 best copy in Storage, deletes redundant copies both inside & outside)")
    scope_choice = input("Select scope (1 or 2) [Default: 1]: ").strip()
    scope = 2 if scope_choice == "2" else 1

    # 5. Interactive vs Batch Mode
    print("\nExecution Mode:")
    print("  [B]atch review (Preview all candidates, confirm, and execute all at once) [Default]")
    print("  [S]tep-by-step (Review and confirm each duplicate group individually)")
    mode_choice = input("Select mode (b/s) [Default: b]: ").strip().lower()
    step_mode = mode_choice == "s"

    print("\nQuerying duplicate files from database...")

    conn = get_db_connection(db_path)
    cursor = conn.cursor()

    # Build query
    cat_filter = ""
    params = []
    if cat_input and (cat_input in EXTENSION_MAP or cat_input == "other"):
        cat_filter = "AND category = ?"
        params.append(cat_input)

    limit_clause = f"LIMIT {limit}" if limit else ""

    query = f"""
        WITH top_duplicates AS (
            SELECT name, size_bytes
            FROM files
            WHERE size_bytes > 0 {cat_filter}
            GROUP BY name, size_bytes
            HAVING COUNT(*) > 1
            ORDER BY size_bytes DESC
            {limit_clause}
        )
        SELECT 
            f.id AS file_id,
            f.name,
            f.category,
            f.size_bytes,
            f.modified_at,
            d.path,
            h.hostname,
            COALESCE(GROUP_CONCAT(DISTINCT dt.tag_name), '-') AS folder_tags,
            COALESCE(GROUP_CONCAT(DISTINCT ft.tag_name), '-') AS file_tags
        FROM top_duplicates td
        JOIN files f ON f.name = td.name AND f.size_bytes = td.size_bytes
        JOIN directories d ON f.directory_id = d.id
        JOIN hosts h ON d.host_id = h.id
        LEFT JOIN directory_tags dt ON d.id = dt.directory_id
        LEFT JOIN file_tags ft ON f.id = ft.file_id
        GROUP BY f.id
        ORDER BY f.size_bytes DESC, f.name, d.path;
    """

    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()

    if not rows:
        print("\n[Notice] No duplicate files found matching the criteria.")
        return

    # Group by (name, size_bytes)
    groups = defaultdict(list)
    for r in rows:
        fid, name, cat, sz, mtime, dpath, host, dtags, ftags = r
        full_p = f"{dpath}/{name}"
        groups[(name, sz, cat)].append({
            "file_id": fid,
            "name": name,
            "category": cat,
            "size_bytes": sz,
            "modified_at": mtime,
            "dir_path": dpath,
            "full_path": full_p,
            "host": host,
            "folder_tags": dtags,
            "file_tags": ftags
        })

    def get_tier_rank(path_str: str) -> int:
        p_lower = path_str.lower()
        if "priority 1" in p_lower:
            return 1
        elif "priority 2" in p_lower:
            return 2
        elif "priority 3" in p_lower:
            return 3
        elif "priority 4" in p_lower:
            return 4
        return 5

    # Process resolution plan for each group
    resolution_plan = []
    total_reclaimable_bytes = 0
    total_deletions_count = 0

    for (name, sz, cat), copies in groups.items():
        storage_copies = [c for c in copies if c["full_path"].startswith(storage_root)]
        outside_copies = [c for c in copies if not c["full_path"].startswith(storage_root)]

        if storage_copies:
            # Sort storage copies by tier rank, then shortest path
            storage_copies.sort(key=lambda c: (get_tier_rank(c["full_path"]), len(c["full_path"])))
            keeper = storage_copies[0]
            
            if scope == 1:
                # Scope 1: Only delete outside copies
                to_delete = outside_copies
            else:
                # Scope 2: Full deduplication
                to_delete = [c for c in copies if c["file_id"] != keeper["file_id"]]
        else:
            # No copies in storage
            if scope == 1:
                # In Scope 1, skip groups with 0 copies in Storage to avoid data loss
                keeper = copies[0]
                to_delete = []
            else:
                copies.sort(key=lambda c: (len(c["full_path"])))
                keeper = copies[0]
                to_delete = copies[1:]

        if to_delete:
            group_reclaimable = sum(c["size_bytes"] for c in to_delete)
            total_reclaimable_bytes += group_reclaimable
            total_deletions_count += len(to_delete)

        resolution_plan.append({
            "name": name,
            "size_bytes": sz,
            "category": cat,
            "copies": copies,
            "keeper": keeper,
            "to_delete": to_delete
        })

    # Summary
    groups_with_deletions = [g for g in resolution_plan if g["to_delete"]]
    print("\n" + "=" * 80)
    print("DUPLICATE RESOLUTION PREVIEW")
    print("=" * 80)
    print(f"  • Total Duplicate Groups Analyzed:    {len(resolution_plan):,}")
    print(f"  • Groups with Actionable Deletions:   {len(groups_with_deletions):,}")
    print(f"  • Redundant Files to Delete:          {total_deletions_count:,}")
    print(f"  • Total Reclaimable Disk Space:       {format_size(total_reclaimable_bytes)}")
    print(f"  • Preserved Storage Root:             {storage_root}")
    print("=" * 80)

    if not groups_with_deletions:
        print("\n[Notice] No redundant copies found outside the Storage root to delete.")
        return

    # Execution logic
    deleted_fids = []
    actual_deleted_bytes = 0
    actual_deleted_files = 0
    errors = []

    def execute_group_deletion(group: dict) -> bool:
        nonlocal actual_deleted_bytes, actual_deleted_files
        keeper = group["keeper"]
        keeper_path = Path(keeper["full_path"])

        # 1. PHYSICAL DISK SAFETY VERIFICATION: Keeper must exist and match size!
        if not keeper_path.exists() or not keeper_path.is_file():
            errors.append(f"SAFETY ABORT: Keeper file missing on disk: {keeper['full_path']}")
            print(f"  [Error] Keeper file missing on disk! Skipping deletion for group '{group['name']}'.")
            return False

        try:
            if keeper_path.stat().st_size != keeper["size_bytes"]:
                errors.append(f"SAFETY ABORT: Keeper size mismatch on disk: {keeper['full_path']}")
                print(f"  [Error] Keeper file size mismatch! Skipping deletion for group '{group['name']}'.")
                return False
        except Exception as e:
            errors.append(f"SAFETY ABORT: Stat failed on keeper: {e}")
            return False

        # 2. Delete redundant copies
        for del_item in group["to_delete"]:
            del_path = Path(del_item["full_path"])
            try:
                if del_path.exists() and del_path.is_file():
                    del_path.unlink()
                    actual_deleted_files += 1
                    actual_deleted_bytes += del_item["size_bytes"]
                    deleted_fids.append(del_item["file_id"])
                    print(f"  ✓ Deleted: {del_item['full_path']}")
                elif not del_path.exists():
                    # Already missing on disk, still record fid to purge DB
                    deleted_fids.append(del_item["file_id"])
                    print(f"  - Record pruned (file already absent on disk): {del_item['full_path']}")
            except Exception as e:
                errors.append(f"Delete failed on {del_item['full_path']}: {e}")
                print(f"  ✗ Failed to delete {del_item['full_path']}: {e}")

        # Real-time database sync for step mode
        if deleted_fids:
            try:
                conn_sync = get_db_connection(db_path)
                cursor_sync = conn_sync.cursor()
                cursor_sync.executemany("DELETE FROM files WHERE id = ?", [(fid,) for fid in deleted_fids])
                conn_sync.commit()
                conn_sync.close()
                deleted_fids.clear()
            except Exception:
                pass

        return True

    if step_mode:
        # Step-by-Step Review: stream candidates continuously until 'q'
        print("\nEntering step-by-step duplicate resolution...")
        print("Tip: Press [Enter] or 'a' to accept & delete, 's' to skip, 'q' to quit & prune.\n")

        processed_idx = 0
        current_groups = groups_with_deletions
        stop_requested = False

        while current_groups and not stop_requested:
            for group in current_groups:
                processed_idx += 1
                sz_str = format_size(group["size_bytes"])
                reclaim_str = format_size(sum(c["size_bytes"] for c in group["to_delete"]))
                print(f"\n[Candidate #{processed_idx}] Duplicate Group: {group['name']} ({sz_str}, {group['category'].upper()}) -> Reclaimable: {reclaim_str}")
                print(f"  [KEEP]:   {group['keeper']['full_path']} (Tags: {group['keeper']['folder_tags']})")
                for d in group["to_delete"]:
                    loc_type = "OUTSIDE Storage" if not d["full_path"].startswith(storage_root) else "Internal Duplicate"
                    print(f"  [DELETE] ({loc_type}): {d['full_path']} (Tags: {d['folder_tags']})")

                prompt = input("Action: [A]ccept & delete / [S]kip / [Q]uit & prune [Default: a]: ").strip().lower()
                if prompt == 'q':
                    stop_requested = True
                    print("\n[Stopped] Step-by-step review terminated by user.")
                    break
                elif prompt == 's':
                    print("  Skipped.")
                    continue
                else:
                    execute_group_deletion(group)

            if not stop_requested:
                # Check if more duplicate candidates exist in the database
                conn_check = get_db_connection(db_path)
                cursor_check = conn_check.cursor()
                check_query = f"""
                    WITH next_duplicates AS (
                        SELECT name, size_bytes
                        FROM files
                        WHERE size_bytes > 0 {cat_filter}
                        GROUP BY name, size_bytes
                        HAVING COUNT(*) > 1
                        ORDER BY size_bytes DESC
                        LIMIT 50
                    )
                    SELECT 
                        f.id AS file_id,
                        f.name,
                        f.category,
                        f.size_bytes,
                        f.modified_at,
                        d.path,
                        h.hostname,
                        COALESCE(GROUP_CONCAT(DISTINCT dt.tag_name), '-') AS folder_tags,
                        COALESCE(GROUP_CONCAT(DISTINCT ft.tag_name), '-') AS file_tags
                    FROM next_duplicates td
                    JOIN files f ON f.name = td.name AND f.size_bytes = td.size_bytes
                    JOIN directories d ON f.directory_id = d.id
                    JOIN hosts h ON d.host_id = h.id
                    LEFT JOIN directory_tags dt ON d.id = dt.directory_id
                    LEFT JOIN file_tags ft ON f.id = ft.file_id
                    GROUP BY f.id
                    ORDER BY f.size_bytes DESC, f.name, d.path;
                """
                cursor_check.execute(check_query, params)
                next_rows = cursor_check.fetchall()
                conn_check.close()

                next_groups_dict = defaultdict(list)
                for r in next_rows:
                    fid, name, cat, sz, mtime, dpath, host, dtags, ftags = r
                    next_groups_dict[(name, sz, cat)].append({
                        "file_id": fid,
                        "name": name,
                        "category": cat,
                        "size_bytes": sz,
                        "modified_at": mtime,
                        "dir_path": dpath,
                        "full_path": f"{dpath}/{name}",
                        "host": host,
                        "folder_tags": dtags,
                        "file_tags": ftags
                    })

                next_actionable = []
                for (name, sz, cat), copies in next_groups_dict.items():
                    s_copies = [c for c in copies if c["full_path"].startswith(storage_root)]
                    o_copies = [c for c in copies if not c["full_path"].startswith(storage_root)]
                    if s_copies:
                        s_copies.sort(key=lambda c: (get_tier_rank(c["full_path"]), len(c["full_path"])))
                        k = s_copies[0]
                        td = o_copies if scope == 1 else [c for c in copies if c["file_id"] != k["file_id"]]
                    else:
                        if scope == 1:
                            continue
                        copies.sort(key=lambda c: (len(c["full_path"])))
                        k = copies[0]
                        td = copies[1:]
                    if td:
                        next_actionable.append({"name": name, "size_bytes": sz, "category": cat, "copies": copies, "keeper": k, "to_delete": td})

                if next_actionable:
                    cont = input(f"\nReviewed {processed_idx} candidates. Load next batch of {len(next_actionable)} duplicate groups? [Y/n/q] [Default: y]: ").strip().lower()
                    if cont in ('n', 'q'):
                        stop_requested = True
                        break
                    current_groups = next_actionable
                else:
                    print("\n[Complete] All duplicate candidate groups have been reviewed.")
                    break

    else:
        # Batch Review: show top candidate groups
        print("\nTop Actionable Duplicate Groups:")
        for idx, group in enumerate(groups_with_deletions[:15], 1):
            sz_str = format_size(group["size_bytes"])
            reclaim_str = format_size(sum(c["size_bytes"] for c in group["to_delete"]))
            print(f"  {idx:>2}. {group['name']:<35} ({sz_str}) -> Reclaim: {reclaim_str} ({len(group['to_delete'])} copies)")
            print(f"      [KEEP]:   {group['keeper']['full_path']}")
            for d in group["to_delete"][:2]:
                print(f"      [DELETE]: {d['full_path']}")
            if len(group["to_delete"]) > 2:
                print(f"      [DELETE]: ... (+{len(group['to_delete']) - 2} more copies)")

        if len(groups_with_deletions) > 15:
            print(f"  ... and {len(groups_with_deletions) - 15} more duplicate groups.")

        confirm = input(f"\nProceed with deleting {total_deletions_count:,} duplicate files ({format_size(total_reclaimable_bytes)})? [y/N]: ").strip().lower()
        if confirm != 'y':
            print("\n[Cancelled] Duplicate cleanup aborted by user.")
            return

        print("\nExecuting batch duplicate deletion...")
        for group in groups_with_deletions:
            execute_group_deletion(group)

    # 3. Synchronize any remaining database records
    if deleted_fids:
        print(f"\nUpdating database (purging {len(deleted_fids):,} deleted records)...")
        try:
            conn = get_db_connection(db_path)
            cursor = conn.cursor()
            chunk_size = 500
            for i in range(0, len(deleted_fids), chunk_size):
                chunk = deleted_fids[i:i + chunk_size]
                placeholders = ",".join("?" for _ in chunk)
                cursor.execute(f"DELETE FROM files WHERE id IN ({placeholders})", chunk)
            conn.commit()
            conn.close()
            print("[Success] Database records synchronized.")
        except Exception as e:
            print(f"[Warning] Failed to update database: {e}")

    print("\n" + "=" * 80)
    print("DUPLICATE CLEANUP SUMMARY")
    print("=" * 80)
    print(f"  • Files Deleted:                      {actual_deleted_files:,}")
    print(f"  • Storage Space Reclaimed:            {format_size(actual_deleted_bytes)}")
    if errors:
        print(f"  • Errors / Aborts:                    {len(errors)}")
        for err in errors[:5]:
            print(f"    - {err}")
    print("=" * 80)

    # Automatically prompt to prune empty folders
    prune_dirs = input("\nPrune empty folders left behind? [Y/n]: ").strip().lower()
    if prune_dirs != 'n':
        prune_missing_records(db_path)

def get_orchestrator_db_path() -> str:
    """Discovers and resolves the active database location across external and local storage."""
    # 1. Environment variable override
    env_p = os.environ.get("DRIVE_AUDIT_DB")
    if env_p and os.path.exists(env_p):
        return env_p
    # 2. Canonical external persistent storage on Extreme Pro
    ext_pro_p = "/Volumes/Extreme Pro/Data/sqlite/drive-audit/drive_audit.db"
    if os.path.exists(ext_pro_p):
        return ext_pro_p
    # 3. Local symlink or relative file in workspace
    return "drive_audit.db"

def main():
    db_file = get_orchestrator_db_path()

    while True:
        print("\n" + "=" * 55)
        print("        DRIVE AUDIT & STORAGE ORCHESTRATOR        ")
        print("=" * 55)
        print(f"  📍 Database: {db_file}")
        print("=" * 55)
        print("1. Tagging Review, Curation Wizard & Subfolder Triage")
        print("2. Scan & index directory (Read-only catalog & tag sync)")
        print("3. View hosts & storage overview")
        print("4. View top-level folder scans report")
        print("5. Generate report of largest files")
        print("6. Prune deleted records from DB (Sync with disk)")
        print("7. List all active tags (Directory & File)")
        print("8. Tag & sync folders (Priority Tiers, Finder Colors & DB)")
        print("9. Search files by tag (Finder & Manual)")
        print("10. Segregate non-media files from folder (On-demand migration)")
        print("11. Detect & clean duplicate files (Interactive duplicate resolver)")
        print("12. View Curation & Verification Report (Approved vs Unapproved folders)")
        print("13. Exit")

        choice = input("\nSelect option (1-13): ").strip()

        if choice == "1":
            tag_review_priority_folders_interactive(db_file)
        elif choice == "2":
            audit_directory_interactive(db_file)
        elif choice == "3":
            show_hosts_summary(db_file)
        elif choice == "4":
            generate_top_level_scans_report(db_file)
        elif choice == "5":
            generate_largest_files_report(db_file)
        elif choice == "6":
            prune_missing_records(db_file)
        elif choice == "7":
            list_all_tags(db_file)
        elif choice == "8":
            tag_manager_interactive(db_file)
        elif choice == "9":
            search_files_by_tag(db_file)
        elif choice == "10":
            migrate_non_media_interactive(db_file)
        elif choice == "11":
            detect_and_resolve_duplicates_interactive(db_file)
        elif choice == "12":
            generate_curation_verification_report(db_file)
        elif choice == "13":
            print("\nExiting Storage Orchestrator. Goodbye!")
            break
        else:
            print("\n[Error] Invalid option.")

if __name__ == "__main__":
    main()