import os
import re
import sys
import csv
import json
import uuid
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
import hashlib
from collections import deque, defaultdict, Counter
from pathlib import Path

# Ensure python/ package folder and project root are in sys.path
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(1, str(PROJECT_ROOT))

try:
    import exifread
    logging.getLogger('exifread').setLevel(logging.ERROR)
except ImportError:
    exifread = None

# Extension mappings for classification
EXTENSION_MAP = {
    "image": {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tiff", ".tif", ".webp", ".heic", ".raw", ".cr2", ".cr3", ".nef", ".arw", ".dng", ".psd", ".svg"},
    "video": {".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".webm", ".m4v", ".3gp"},
    "audio": {".mp3", ".wav", ".flac", ".aac", ".ogg", ".m4a", ".wma"},
    "document": {".pdf", ".docx", ".doc", ".xlsx", ".xls", ".pptx", ".ppt", ".txt", ".csv", ".tsv", ".rtf", ".pages", ".numbers", ".key", ".epub", ".mobi"},
    "archive": {".zip", ".tar", ".gz", ".7z", ".rar", ".bz2", ".bak"},
    "code": {".py", ".js", ".ts", ".jsx", ".tsx", ".html", ".css", ".cpp", ".c", ".h", ".hpp", ".java", ".json", ".xml", ".sh", ".sql", ".yaml", ".yml"},
    "financial": {".mny", ".mbf", ".lrd", ".ofx", ".qfx", ".qdf", ".qel", ".qsd", ".qph", ".qbw", ".qbb", ".tax", ".tax2018", ".tax2019", ".tax2020", ".tax2021", ".tax2022", ".tax2023", ".tax2024", ".tax2025", ".ptx"}
}

# Comprehensive File Extension Catalog with Category, Description and Default/macOS Applications
DEFAULT_FILE_EXTENSIONS = [
    # Financial & Accounting (Critical proprietary formats)
    (".mny", "Financial Data", "MS Money Active Database", "Windows Microsoft Money (Discontinued)", "Archival Backup Only (Unusable on Mac/PC without legacy Windows VM)", 1),
    (".mbf", "Financial Data", "MS Money Backup Archive", "Windows Microsoft Money (Discontinued)", "Archival Backup Only (Unusable on Mac/PC without legacy Windows VM)", 1),
    (".lrd", "Financial Data", "MS Money Lock/Report Definition", "Windows Microsoft Money (Discontinued)", "Archival Backup Only (Unusable on Mac/PC without legacy Windows VM)", 1),
    (".ofx", "Financial Data", "Open Financial Exchange Transaction Data", "Financial / Banking Software", "Banktivity / MoneyDance / Excel", 1),
    (".qfx", "Financial Data", "Quicken Financial Exchange Data", "Quicken", "Quicken for Mac / Banktivity", 1),
    (".qdf", "Financial Data", "Quicken Financial Database", "Quicken", "Quicken for Mac / Parallels Windows", 1),
    (".qel", "Financial Data", "Quicken Electronic Payee List", "Quicken", "Quicken for Mac", 1),
    (".qsd", "Financial Data", "Quicken Security Data", "Quicken", "Quicken for Mac", 1),
    (".qph", "Financial Data", "Quicken Price History", "Quicken", "Quicken for Mac", 1),
    (".qbw", "Financial Data", "QuickBooks Working Company File", "QuickBooks", "QuickBooks for Mac", 1),
    (".qbb", "Financial Data", "QuickBooks Company Backup", "QuickBooks", "QuickBooks for Mac", 1),
    (".tax", "Tax Records", "TurboTax Return Archive", "TurboTax", "TurboTax for Mac", 1),
    (".tax2018", "Tax Records", "TurboTax 2018 Return", "TurboTax", "TurboTax for Mac", 1),
    (".tax2019", "Tax Records", "TurboTax 2019 Return", "TurboTax", "TurboTax for Mac", 1),
    (".tax2020", "Tax Records", "TurboTax 2020 Return", "TurboTax", "TurboTax for Mac", 1),
    (".tax2021", "Tax Records", "TurboTax 2021 Return", "TurboTax", "TurboTax for Mac", 1),
    (".tax2022", "Tax Records", "TurboTax 2022 Return", "TurboTax", "TurboTax for Mac", 1),
    (".tax2023", "Tax Records", "TurboTax 2023 Return", "TurboTax", "TurboTax for Mac", 1),
    (".tax2024", "Tax Records", "TurboTax 2024 Return", "TurboTax", "TurboTax for Mac", 1),
    (".tax2025", "Tax Records", "TurboTax 2025 Return", "TurboTax", "TurboTax for Mac", 1),
    (".ptx", "Tax Records", "Tax Preparation Data", "TaxSlayer / Tax Software", "Tax Software", 1),

    # Databases & Systems
    (".sql", "Database", "SQL Database Script / Dump", "MySQL / PostgreSQL / SQLite", "TablePlus / DBeaver / Terminal", 1),
    (".sqlite", "Database", "SQLite Database", "SQLite", "DB Browser for SQLite / TablePlus", 1),
    (".sqlite3", "Database", "SQLite 3 Database", "SQLite", "DB Browser for SQLite / TablePlus", 1),
    (".db", "Database", "Database File", "Database Engine", "DB Browser / TablePlus", 1),
    (".mdb", "Database", "Microsoft Access Database", "Microsoft Access", "MDB Viewer / Parallels Windows", 1),
    (".accdb", "Database", "Microsoft Access 2007+ Database", "Microsoft Access", "MDB Viewer / Parallels Windows", 1),
    (".bak", "Backup Archive", "Database / System Backup Archive", "Backup Utility", "Terminal / Archive Utility", 1),

    # Documents & Spreadsheets
    (".pdf", "Document", "Portable Document Format", "PDF Reader", "Preview / Adobe Acrobat", 0),
    (".docx", "Document", "Microsoft Word Document", "Microsoft Word", "Microsoft Word / Pages", 0),
    (".doc", "Document", "Legacy Microsoft Word Document", "Microsoft Word", "Microsoft Word / Pages", 0),
    (".xlsx", "Spreadsheet", "Microsoft Excel Spreadsheet", "Microsoft Excel", "Microsoft Excel / Numbers", 0),
    (".xls", "Spreadsheet", "Legacy Microsoft Excel Spreadsheet", "Microsoft Excel", "Microsoft Excel / Numbers", 0),
    (".csv", "Spreadsheet / Data", "Comma-Separated Values Data", "Spreadsheet / Editor", "Numbers / Excel / VS Code", 0),
    (".tsv", "Spreadsheet / Data", "Tab-Separated Values Data", "Spreadsheet / Editor", "Numbers / Excel / VS Code", 0),
    (".pptx", "Presentation", "Microsoft PowerPoint Presentation", "Microsoft PowerPoint", "Microsoft PowerPoint / Keynote", 0),
    (".ppt", "Presentation", "Legacy Microsoft PowerPoint Presentation", "Microsoft PowerPoint", "Microsoft PowerPoint / Keynote", 0),
    (".txt", "Document", "Plain Text Document", "Text Editor", "TextEdit / VS Code", 0),
    (".rtf", "Document", "Rich Text Format Document", "Rich Text Editor", "TextEdit / Pages", 0),
    (".pages", "Document", "Apple Pages Document", "Apple Pages", "Pages", 0),
    (".numbers", "Spreadsheet", "Apple Numbers Spreadsheet", "Apple Numbers", "Numbers", 0),
    (".key", "Presentation", "Apple Keynote Presentation", "Apple Keynote", "Keynote", 0),

    # Photography & Creative
    (".psd", "Creative / Design", "Adobe Photoshop Document", "Adobe Photoshop", "Adobe Photoshop / Pixelmator Pro", 0),
    (".psb", "Creative / Design", "Adobe Photoshop Large Document", "Adobe Photoshop", "Adobe Photoshop", 0),
    (".ai", "Creative / Design", "Adobe Illustrator Vector Artwork", "Adobe Illustrator", "Adobe Illustrator / Affinity Designer", 0),
    (".indd", "Creative / Design", "Adobe InDesign Layout Document", "Adobe InDesign", "Adobe InDesign", 0),
    (".cr2", "RAW Photography", "Canon RAW Digital Image", "Canon DPP / Adobe RAW", "Lightroom / Apple Photos", 0),
    (".cr3", "RAW Photography", "Canon RAW 3 Digital Image", "Canon DPP / Adobe RAW", "Lightroom / Apple Photos", 0),
    (".nef", "RAW Photography", "Nikon RAW Digital Image", "Nikon NX Studio / Adobe RAW", "Lightroom / Apple Photos", 0),
    (".arw", "RAW Photography", "Sony Alpha RAW Image", "Sony Imaging Edge / Adobe RAW", "Lightroom / Apple Photos", 0),
    (".dng", "RAW Photography", "Adobe Digital Negative RAW", "Adobe Lightroom / Camera RAW", "Lightroom / Apple Photos / Preview", 0),
    (".heic", "Photography", "High Efficiency Image Container", "Apple Photos / Preview", "Apple Photos / Preview", 0),
    (".jpg", "Photography", "JPEG Raster Image", "Image Viewer", "Preview / Apple Photos", 0),
    (".jpeg", "Photography", "JPEG Raster Image", "Image Viewer", "Preview / Apple Photos", 0),
    (".png", "Photography / Graphic", "Portable Network Graphic", "Image Viewer", "Preview / Apple Photos", 0),
    (".tiff", "Photography", "Tagged Image File Format", "Image Viewer", "Preview / Apple Photos", 0),
    (".tif", "Photography", "Tagged Image File Format", "Image Viewer", "Preview / Apple Photos", 0),
    (".bmp", "Photography", "Bitmap Image", "Image Viewer", "Preview", 0),
    (".gif", "Photography / Animation", "Graphics Interchange Format", "Web Browser / Preview", "Preview / Safari", 0),
    (".svg", "Vector Graphic", "Scalable Vector Graphics", "Web Browser / Vector Editor", "Safari / Illustrator", 0),

    # Video & Audio
    (".mov", "Video", "Apple QuickTime Digital Movie", "QuickTime Player", "QuickTime Player / Final Cut Pro / IINA", 0),
    (".mp4", "Video", "MPEG-4 Digital Video", "Video Player", "QuickTime Player / IINA / VLC", 0),
    (".m4v", "Video", "Apple iTunes Video", "Video Player", "Apple TV / QuickTime Player", 0),
    (".mkv", "Video", "Matroska Multimedia Container", "VLC / IINA", "IINA / VLC", 0),
    (".avi", "Video", "Audio Video Interleave", "Video Player", "IINA / VLC", 0),
    (".wmv", "Video", "Windows Media Video", "Windows Media Player", "IINA / VLC", 0),
    (".mp3", "Audio", "MPEG Audio Layer III", "Audio Player", "Apple Music / QuickTime", 0),
    (".wav", "Audio", "Waveform Audio File", "Audio Player", "QuickTime / Audacity", 0),
    (".flac", "Audio", "Free Lossless Audio Codec", "Audio Player", "IINA / VLC / Audacity", 0),
    (".m4a", "Audio", "Apple Lossless / AAC Audio", "Audio Player", "Apple Music / QuickTime", 0),
    (".aac", "Audio", "Advanced Audio Coding", "Audio Player", "Apple Music", 0),

    # Developer & Code
    (".py", "Source Code", "Python Source Code", "Python Interpreter / IDE", "VS Code / PyCharm / Terminal", 0),
    (".js", "Source Code", "JavaScript Source Code", "Node.js / Web Browser", "VS Code", 0),
    (".ts", "Source Code", "TypeScript Source Code", "TypeScript / Node.js", "VS Code", 0),
    (".jsx", "Source Code", "React JSX Component", "Node.js / React", "VS Code", 0),
    (".tsx", "Source Code", "React TypeScript Component", "Node.js / React", "VS Code", 0),
    (".html", "Web Assets", "HyperText Markup Language", "Web Browser", "Safari / Chrome / VS Code", 0),
    (".css", "Web Assets", "Cascading Style Sheets", "Web Browser", "VS Code / Safari", 0),
    (".c", "Source Code", "C Source Code", "C Compiler", "Xcode / VS Code / clang", 0),
    (".cpp", "Source Code", "C++ Source Code", "C++ Compiler", "Xcode / VS Code / clang++", 0),
    (".h", "Source Code", "C/C++ Header File", "C/C++ Compiler", "Xcode / VS Code", 0),
    (".hpp", "Source Code", "C++ Header File", "C++ Compiler", "Xcode / VS Code", 0),
    (".sh", "Shell Script", "Unix Shell Script", "Unix Shell", "Terminal / zsh / bash", 0),
    (".zsh", "Shell Script", "Z Shell Script", "Zsh Shell", "Terminal / zsh", 0),
    (".json", "Config / Data", "JavaScript Object Notation Data", "Code / Data Editor", "VS Code", 0),
    (".yaml", "Config / Data", "YAML Configuration File", "Code Editor", "VS Code", 0),
    (".yml", "Config / Data", "YAML Configuration File", "Code Editor", "VS Code", 0),
    (".xml", "Config / Data", "Extensible Markup Language", "Code Editor", "VS Code", 0),

    # E-Books, Typography & Archives
    (".epub", "E-Book", "Electronic Publication E-Book", "E-Book Reader", "Apple Books / Calibre", 0),
    (".mobi", "E-Book", "Mobipocket / Kindle E-Book", "Kindle App / Calibre", "Calibre / Kindle for Mac", 0),
    (".azw", "E-Book", "Amazon Kindle E-Book", "Kindle App / Calibre", "Calibre / Kindle for Mac", 0),
    (".azw3", "E-Book", "Amazon Kindle Format 8", "Kindle App / Calibre", "Calibre / Kindle for Mac", 0),
    (".otf", "Typography", "OpenType Font File", "Font Book", "Font Book", 0),
    (".ttf", "Typography", "TrueType Font File", "Font Book", "Font Book", 0),
    (".zip", "Archive", "ZIP Compressed Archive", "Archive Utility", "Archive Utility / Keka", 0),
    (".tar", "Archive", "Tape Archive File", "Archive Utility", "Terminal tar / Keka", 0),
    (".gz", "Archive", "Gzip Compressed Archive", "Archive Utility", "Terminal gzip / Keka", 0),
    (".rar", "Archive", "RAR Compressed Archive", "Unrar Utility", "The Unarchiver / Keka", 0),
    (".7z", "Archive", "7-Zip Compressed Archive", "7-Zip Utility", "Keka / The Unarchiver", 0),
]

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
    if "app_needed" not in col_names:
        cursor.execute("ALTER TABLE directories ADD COLUMN app_needed TEXT")

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

    # 9. File Extensions Catalog Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS file_extensions (
            extension TEXT PRIMARY KEY,
            category TEXT NOT NULL,
            description TEXT NOT NULL,
            primary_app TEXT NOT NULL,
            mac_app TEXT,
            is_critical_format INTEGER DEFAULT 0
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_file_extensions_cat ON file_extensions(category);")
    _seed_file_extensions(cursor)

    # 10. Menu Option Usage Table (Tracks frequency and auto-bubbles options)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS menu_option_usage (
            menu_key TEXT NOT NULL,
            option_key TEXT NOT NULL,
            option_label TEXT,
            use_count INTEGER DEFAULT 1,
            last_used_at TEXT NOT NULL,
            PRIMARY KEY (menu_key, option_key)
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_menu_usage_count ON menu_option_usage(menu_key, use_count DESC);")

    # 11. Curation Events & Provenance Tracking Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS curation_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            batch_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            created_at TEXT NOT NULL,
            source_path TEXT,
            destination_path TEXT,
            origin_folder TEXT,
            resource_type TEXT NOT NULL,
            resource_path TEXT NOT NULL,
            file_id INTEGER,
            directory_id INTEGER,
            file_size_bytes INTEGER,
            finder_tags TEXT,
            details TEXT
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_curation_events_batch ON curation_events(batch_id);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_curation_events_res_path ON curation_events(resource_path);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_curation_events_dest ON curation_events(destination_path);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_curation_events_origin ON curation_events(origin_folder);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_curation_events_file_id ON curation_events(file_id);")

    # 12. Performance Indexes
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_files_name_size ON files(name, size_bytes);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_files_size ON files(size_bytes);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_directories_path ON directories(path);")

    conn.commit()
    return conn

def ensure_curation_events_table(cursor_or_conn):
    """Ensures curation_events table and indexes exist in SQLite."""
    cursor = cursor_or_conn.cursor() if hasattr(cursor_or_conn, 'cursor') else cursor_or_conn
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS curation_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            batch_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            created_at TEXT NOT NULL,
            source_path TEXT,
            destination_path TEXT,
            origin_folder TEXT,
            resource_type TEXT NOT NULL,
            resource_path TEXT NOT NULL,
            file_id INTEGER,
            directory_id INTEGER,
            file_size_bytes INTEGER,
            finder_tags TEXT,
            details TEXT
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_curation_events_batch ON curation_events(batch_id);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_curation_events_res_path ON curation_events(resource_path);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_curation_events_dest ON curation_events(destination_path);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_curation_events_origin ON curation_events(origin_folder);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_curation_events_file_id ON curation_events(file_id);")

def log_curation_event(
    db_path: str,
    batch_id: str,
    event_type: str,
    source_path: str | Path | None,
    destination_path: str | Path | None,
    origin_folder: str | None,
    resource_type: str,
    resource_path: str | Path,
    file_id: int | None = None,
    directory_id: int | None = None,
    file_size_bytes: int | None = None,
    finder_tags: list | str | None = None,
    details: str | dict | None = None
) -> int | None:
    """Inserts a curation event record into SQLite and returns the inserted row ID."""
    if not os.path.exists(db_path):
        return None
    try:
        conn = get_db_connection(db_path)
        cur = conn.cursor()
        ensure_curation_events_table(cur)

        now_iso = datetime.datetime.now().isoformat()
        tags_str = finder_tags if isinstance(finder_tags, str) else (", ".join(t[0] if isinstance(t, tuple) else str(t) for t in finder_tags) if finder_tags else "")
        details_str = json.dumps(details) if isinstance(details, (dict, list)) else (details or "")

        cur.execute("""
            INSERT INTO curation_events (
                batch_id, event_type, created_at, source_path, destination_path,
                origin_folder, resource_type, resource_path, file_id, directory_id,
                file_size_bytes, finder_tags, details
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            batch_id, event_type, now_iso,
            str(source_path) if source_path else None,
            str(destination_path) if destination_path else None,
            origin_folder, resource_type, str(resource_path),
            file_id, directory_id, file_size_bytes, tags_str, details_str
        ))
        row_id = cur.lastrowid
        conn.commit()
        conn.close()
        return row_id
    except Exception as e:
        print(f"[Warning] Failed to log curation event: {e}")
        return None

def _seed_file_extensions(cursor):
    """Populates default file extension dictionary into SQLite if not already present."""
    cursor.executemany("""
        INSERT OR IGNORE INTO file_extensions (extension, category, description, primary_app, mac_app, is_critical_format)
        VALUES (?, ?, ?, ?, ?, ?)
    """, DEFAULT_FILE_EXTENSIONS)

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

def record_menu_usage(db_path: str, menu_key: str, option_key: str, option_label: str = ""):
    """Records selection of a menu option to track usage frequency and auto-bubble popular items."""
    if not db_path or not os.path.exists(db_path):
        return
    opt_k = str(option_key).strip().lower()
    if not opt_k:
        return
    try:
        conn = get_db_connection(db_path)
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS menu_option_usage (
                menu_key TEXT NOT NULL,
                option_key TEXT NOT NULL,
                option_label TEXT,
                use_count INTEGER DEFAULT 1,
                last_used_at TEXT NOT NULL,
                PRIMARY KEY (menu_key, option_key)
            )
        """)
        now = datetime.datetime.now().isoformat()
        cur.execute("""
            INSERT INTO menu_option_usage (menu_key, option_key, option_label, use_count, last_used_at)
            VALUES (?, ?, ?, 1, ?)
            ON CONFLICT(menu_key, option_key) DO UPDATE SET
                use_count = use_count + 1,
                option_label = CASE WHEN ? != '' THEN ? ELSE option_label END,
                last_used_at = ?
        """, (menu_key, opt_k, option_label, now, option_label, option_label, now))
        conn.commit()
        conn.close()
    except Exception:
        pass

def get_menu_option_usage(db_path: str, menu_key: str) -> dict[str, int]:
    """Retrieves usage counts for a given menu: {option_key: use_count}."""
    if not db_path or not os.path.exists(db_path):
        return {}
    try:
        conn = get_db_connection(db_path)
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS menu_option_usage (
                menu_key TEXT NOT NULL,
                option_key TEXT NOT NULL,
                option_label TEXT,
                use_count INTEGER DEFAULT 1,
                last_used_at TEXT NOT NULL,
                PRIMARY KEY (menu_key, option_key)
            )
        """)
        cur.execute("SELECT option_key, use_count FROM menu_option_usage WHERE menu_key = ? ORDER BY use_count DESC", (menu_key,))
        rows = cur.fetchall()
        conn.close()
        return {r[0]: r[1] for r in rows}
    except Exception:
        return {}

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

def is_volume_mounted(path_input: str | Path) -> bool:
    """
    Checks if the storage volume containing path_input is currently mounted.
    Prevents false deletions when an external drive is simply detached.
    """
    try:
        p = Path(path_input)
        parts = p.parts
        # On macOS, external drives are mounted under /Volumes/<VolumeName>
        if len(parts) >= 3 and parts[1] == 'Volumes':
            vol_root = Path('/', parts[1], parts[2])
            return vol_root.exists() and vol_root.is_dir()
        # Internal drives or root
        return Path('/').exists()
    except Exception:
        return False

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

def perform_directory_scan(root_input: Path | str, db_path: str, skip_hours: float = 0.0) -> dict:
    """Scans local directory, extracts Finder tags for folders/files, stores EXIF, and reconciles deleted files/dirs."""
    root = Path(root_input)
    if not root.exists():
        print(f"\n[Error] Path '{root}' does not exist.")
        return {
            "interrupted": False,
            "scanned_dirs": 0,
            "scanned_files": 0,
            "skipped_dirs": 0,
            "skipped_files": 0,
            "purged_dirs": 0,
            "purged_files": 0,
            "total_bytes": 0
        }

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

                # 2. Reconcile deleted files in this directory (globally ignore .DS_Store)
                filenames = [f for f in filenames if f not in (".DS_Store", "._.DS_Store")]
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
        return {
            "interrupted": True,
            "scanned_dirs": scanned_dirs,
            "scanned_files": scanned_files,
            "skipped_dirs": skipped_dirs,
            "skipped_files": skipped_files,
            "purged_dirs": purged_dirs,
            "purged_files": purged_files,
            "total_bytes": total_bytes
        }

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

    return {
        "interrupted": False,
        "scanned_dirs": scanned_dirs,
        "scanned_files": scanned_files,
        "skipped_dirs": skipped_dirs,
        "skipped_files": skipped_files,
        "purged_dirs": purged_dirs,
        "purged_files": purged_files,
        "total_bytes": total_bytes
    }

def get_minimal_scan_roots(paths: list[str]) -> list[Path]:
    """Given a list of directory paths, filters to existing paths and returns the minimal set of top-level roots."""
    valid_paths = []
    for p in paths:
        try:
            p_obj = Path(p).resolve()
            if p_obj.exists() and p_obj.is_dir():
                valid_paths.append(p_obj)
        except Exception:
            continue
    unique_paths = list(dict.fromkeys(valid_paths))
    sorted_paths = sorted(unique_paths, key=lambda p: (len(p.parts), len(str(p))))
    minimal_roots = []
    for p in sorted_paths:
        if not any(p == r or r in p.parents for r in minimal_roots):
            minimal_roots.append(p)
    return minimal_roots

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

    perform_directory_scan(root, db_path, skip_hours=skip_hours)



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

    print("\n" + "=" * 78)
    print("                           INDEXED HOSTS OVERVIEW                             ")
    print("=" * 78)
    print(f"{'Hostname':<26} | {'OS':<10} | {'IP Address':<15} | {'Files':<8} | {'Total Size (GB)'}")
    print("-" * 78)
    for host, os_name, ip, count, size in rows:
        gb = (size or 0) / (1024**3)
        h_str = host or "Unknown"
        os_str = os_name or "N/A"
        ip_str = ip or "N/A"
        cnt_str = f"{count:,}" if count else "0"
        print(f"{h_str:<26} | {os_str:<10} | {ip_str:<15} | {cnt_str:<8} | {gb:.2f} GB")
    print("=" * 78)

    # Check Drive Benchmarks in Database vs Mounted Drives
    try:
        import benchmark_drives
        import importlib
        importlib.reload(benchmark_drives)
        mounted_vols = set(benchmark_drives.discover_candidate_volumes())
        saved_benchmarks = benchmark_drives.get_saved_benchmarks(db_path)
        saved_vol_map = {b["mount_point"]: b for b in saved_benchmarks}
        saved_vols = set(saved_vol_map.keys())

        # Determine differences between currently mounted drives and DB
        new_untested_drives = mounted_vols - saved_vols
        missing_drives = saved_vols - mounted_vols

        if saved_benchmarks:
            print("\n" + "=" * 96)
            print("                 SAVED STORAGE DRIVES PERFORMANCE BENCHMARK                    ")
            print("                       (Stored Results from Database)                          ")
            print("=" * 96)
            print(f"{'Volume / Mount Point':<26} | {'Media':<6} | {'Interface':<12} | {'Write Speed':<14} | {'Read Speed':<14} | {'Last Tested'}")
            print("-" * 96)
            for b in saved_benchmarks:
                vol_label = b.get("volume_name") or os.path.basename(b["mount_point"]) or "Root"
                if len(vol_label) > 24:
                    vol_label = vol_label[:21] + "..."
                media = b.get("media_type") or "N/A"
                protocol = b.get("protocol") or "Internal"
                if b.get("write_mb_s") is not None:
                    w_str = f"{b['write_mb_s']} MB/s"
                elif "Time Machine" in (b.get("status") or "") or "Protected" in (b.get("status") or ""):
                    w_str = "Write-Protected"
                else:
                    w_str = b.get("status") or "N/A"

                if b.get("read_mb_s") is not None:
                    r_str = f"{b['read_mb_s']} MB/s"
                elif "FDA Required" in (b.get("status") or "") or "FDA" in (b.get("status") or ""):
                    r_str = "FDA Required"
                else:
                    r_str = "-"
                b_date = b.get("benchmark_at", "")[:19].replace("T", " ") if b.get("benchmark_at") else "N/A"
                unmounted_flag = " (Unmounted)" if b["mount_point"] not in mounted_vols else ""
                print(f"{vol_label:<26} | {media:<6} | {protocol:<12} | {w_str:<14} | {r_str:<14} | {b_date}{unmounted_flag}")
            print("=" * 96)

            if new_untested_drives:
                new_str = ", ".join(sorted(new_untested_drives))
                print(f"\n⚠️ Notice: Current mounted drives differ from saved database!")
                print(f"   New untested volume(s) detected: {new_str}")
                run_new = input("\nRun benchmark to test new drives and update DB? (y/N): ").strip().lower()
                if run_new == 'y':
                    benchmark_drives.run_benchmark_interactive(db_path=db_path)
            else:
                on_demand = input("\nPress Enter to return, or enter 'r' to re-run live benchmark on demand: ").strip().lower()
                if on_demand == 'r':
                    benchmark_drives.run_benchmark_interactive(db_path=db_path)

        else:
            print("\n[Notice] No drive performance benchmark saved in database.")
            run_init = input("Run initial drive performance & I/O benchmark now? (y/N): ").strip().lower()
            if run_init == 'y':
                benchmark_drives.run_benchmark_interactive(db_path=db_path)

    except ImportError:
        pass

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
        os.makedirs("docs", exist_ok=True)
        filename = "docs/top_level_scans_report.md"
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
        os.makedirs("docs", exist_ok=True)
        filename = "docs/largest_files_report.md"
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

def deduplicate_verified_rows_with_breadcrumbs(
    v_rows: list,
    path_idx: int = 2,
    name_idx: int = 1,
    df_cnt_idx: int = 6,
    df_b_idx: int = 7,
    vs_cnt_idx: int = 8,
    vs_b_idx: int = 9,
    pend_cnt_idx: int = 10,
    pend_f_idx: int = 11
) -> list:
    """
    Deduplicates verified directory rows where ancestor and descendant contain the exact same set
    of approved files, keeping the deepest folder and annotating it with the full breadcrumb path
    (e.g., 'Data ▸ Legacy ▸ Windows ▸ MS-Money').
    
    Returns a list of tuples: (row, breadcrumb_str)
    """
    if not v_rows:
        return []

    row_by_path = {r[path_idx]: r for r in v_rows}
    # Sort paths by length (parts) descending so deepest folders are processed first
    sorted_paths = sorted(row_by_path.keys(), key=lambda p: (len(Path(p).parts), len(p)), reverse=True)
    
    subsumed_ancestors = set()
    breadcrumbs = {}

    for deep_path in sorted_paths:
        if deep_path in subsumed_ancestors:
            continue
        deep_row = row_by_path[deep_path]
        deep_app_f = deep_row[df_cnt_idx] + deep_row[vs_cnt_idx]
        deep_app_b = deep_row[df_b_idx] + deep_row[vs_b_idx]
        
        chain = [deep_row]
        for anc_path in sorted(row_by_path.keys(), key=lambda p: (len(Path(p).parts), len(p))):
            if anc_path != deep_path and deep_path.startswith(anc_path + "/"):
                anc_row = row_by_path[anc_path]
                anc_app_f = anc_row[df_cnt_idx] + anc_row[vs_cnt_idx]
                anc_app_b = anc_row[df_b_idx] + anc_row[vs_b_idx]
                # Condition for exact same set of approved files:
                # 1. anc_row has 0 direct files (df_cnt == 0 and df_b == 0)
                # 2. anc_row total approved files and bytes match deep_row
                # 3. anc_row pending subfolder counts match deep_row
                if (anc_row[df_cnt_idx] == 0 and anc_app_f == deep_app_f and anc_app_b == deep_app_b and
                    anc_row[pend_cnt_idx] == deep_row[pend_cnt_idx] and anc_row[pend_f_idx] == deep_row[pend_f_idx]):
                    subsumed_ancestors.add(anc_path)
                    chain.append(anc_row)

        chain_sorted = sorted(chain, key=lambda r: len(Path(r[path_idx]).parts))
        breadcrumbs[deep_path] = " ▸ ".join([r[name_idx] for r in chain_sorted])

    deduped = []
    for r in v_rows:
        if r[path_idx] not in subsumed_ancestors:
            deduped.append((r, breadcrumbs.get(r[path_idx], r[name_idx])))

    return deduped

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
        # 0. Reconcile deleted directories on mounted volumes so report strictly reflects actual filesystem state
        cursor.execute("""
            SELECT d.id, d.path 
            FROM priority_locations pl
            JOIN directories d ON (d.path = pl.path OR d.path LIKE pl.path || '/%')
            WHERE pl.is_active = 1
        """)
        missing_dir_ids = []
        for did, dpath in cursor.fetchall():
            if is_volume_mounted(dpath) and not os.path.exists(dpath):
                missing_dir_ids.append(did)

        if missing_dir_ids:
            placeholders = ",".join("?" for _ in missing_dir_ids)
            cursor.execute(f"DELETE FROM files WHERE directory_id IN ({placeholders})", missing_dir_ids)
            cursor.execute(f"DELETE FROM directory_tags WHERE directory_id IN ({placeholders})", missing_dir_ids)
            cursor.execute(f"DELETE FROM directories WHERE id IN ({placeholders})", missing_dir_ids)
            conn.commit()

        # 1. Fetch Global Summary across all indexed data (Option B: strictly verified files, excluding .DS_Store)
        cursor.execute("SELECT COUNT(id), COALESCE(SUM(size_bytes), 0) FROM files WHERE name != '.DS_Store'")
        tot_files_row = cursor.fetchone()
        total_files = tot_files_row[0] or 0
        total_bytes = tot_files_row[1] or 0

        cursor.execute("SELECT COUNT(id) FROM directories")
        total_folders = cursor.fetchone()[0] or 0

        cursor.execute("SELECT COUNT(id) FROM directories WHERE is_verified = 1")
        verified_folders = cursor.fetchone()[0] or 0
        unverified_folders = total_folders - verified_folders

        # Option B: Strictly verified files (only files in directories where is_verified = 1)
        cursor.execute("""
            SELECT COUNT(f.id), COALESCE(SUM(f.size_bytes), 0)
            FROM files f
            JOIN directories d ON f.directory_id = d.id
            WHERE d.is_verified = 1 AND f.name != '.DS_Store'
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

        # 2. Fetch Priority Locations Breakdown (Option B: strict verified files vs pending subfolders)
        cursor.execute("""
            SELECT 
                pl.id,
                pl.priority_tier,
                pl.label,
                pl.path,
                COUNT(DISTINCT d.id) as tot_f,
                COUNT(DISTINCT CASE WHEN d.is_verified = 1 THEN d.id END) as v_f,
                COUNT(CASE WHEN f.name != '.DS_Store' THEN f.id END) as tot_files,
                COALESCE(SUM(CASE WHEN f.name != '.DS_Store' THEN f.size_bytes ELSE 0 END), 0) as tot_b,
                COUNT(CASE WHEN d.is_verified = 1 AND f.name != '.DS_Store' THEN f.id END) as v_files,
                COALESCE(SUM(CASE WHEN d.is_verified = 1 AND f.name != '.DS_Store' THEN f.size_bytes ELSE 0 END), 0) as v_b
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
        report_options = [
            {"key": "1", "label": "List Approved Folders (is_verified = 1) — [Enter # to inspect folder details & files]"},
            {"key": "2", "label": "List All Approved Files (Detailed file-by-file inventory)"},
            {"key": "3", "label": "List Unapproved Category Folders (is_verified = 0) — [Enter # to inspect pending files]"},
            {"key": "4", "label": "Filter Approved / Unapproved by Priority Tier (P1, P2, P3, P4)"},
            {"key": "5", "label": "Export Full Report (Markdown / CSV with file inventory)"},
            {"key": "6", "label": "Return to previous menu"}
        ]
        rep_usage = get_menu_option_usage(db_path, "curation_reports_menu")
        sorted_rep = sorted(report_options, key=lambda x: rep_usage.get(x["key"], 0), reverse=True)
        top_rep = sorted_rep[0]["key"] if (rep_usage and rep_usage.get(sorted_rep[0]["key"], 0) > 0) else "1"

        print("\nOptions:")
        for ro in sorted_rep:
            cnt = rep_usage.get(ro["key"], 0)
            badge = f" (Used {cnt}x) 🔥" if cnt > 0 and cnt == max(rep_usage.values()) else (f" (Used {cnt}x)" if cnt > 0 else "")
            def_badge = " [Default]" if ro["key"] == top_rep and rep_usage.get(top_rep, 0) > 0 else ""
            print(f"  {ro['key']}. {ro['label']}{badge}{def_badge}")

        def_prompt = f" [Default: {top_rep}]" if (rep_usage and rep_usage.get(top_rep, 0) > 0) else ""
        raw_rep = input(f"\nSelect report option (1-6){def_prompt}: ").strip()
        rep_choice = raw_rep if raw_rep else (top_rep if (rep_usage and rep_usage.get(top_rep, 0) > 0) else "")
        record_menu_usage(db_path, "curation_reports_menu", rep_choice, next((r["label"] for r in report_options if r["key"] == rep_choice), ""))

        if rep_choice == "6":
            break

        elif rep_choice == "1":
            # List Approved Folders with Option B (Separated Direct vs Subtree Curated Status)
            auto_prompted_rescan = False
            while True:
                conn.commit()
                cursor = conn.cursor()
                print("\n⏳ Fetching approved / verified folders... Please wait...")
                cursor.execute("""
                    WITH approved_dirs AS (
                        SELECT id, path, name, verified_at, description, app_needed
                        FROM directories
                        WHERE is_verified = 1
                    )
                    SELECT 
                        ad.id,
                        ad.name,
                        ad.path,
                        ad.verified_at,
                        ad.description,
                        ad.app_needed,
                        -- Direct files in this approved folder
                        (SELECT COUNT(f.id) FROM files f WHERE f.directory_id = ad.id AND f.name != '.DS_Store') as dir_files,
                        (SELECT COALESCE(SUM(f.size_bytes), 0) FROM files f WHERE f.directory_id = ad.id AND f.name != '.DS_Store') as dir_bytes,
                        -- Files in verified subfolders under this folder
                        (SELECT COUNT(f.id) 
                         FROM directories sub 
                         JOIN files f ON f.directory_id = sub.id 
                         WHERE sub.path LIKE ad.path || '/%' AND sub.is_verified = 1 AND f.name != '.DS_Store') as ver_sub_files,
                        (SELECT COALESCE(SUM(f.size_bytes), 0) 
                         FROM directories sub 
                         JOIN files f ON f.directory_id = sub.id 
                         WHERE sub.path LIKE ad.path || '/%' AND sub.is_verified = 1 AND f.name != '.DS_Store') as ver_sub_bytes,
                        -- Unverified subfolders count under this folder
                        (SELECT COUNT(sub.id) 
                         FROM directories sub 
                         WHERE sub.path LIKE ad.path || '/%' AND sub.is_verified = 0) as pending_sub_count,
                        -- Unverified files & bytes in subfolders
                        (SELECT COUNT(f.id) 
                         FROM directories sub 
                         JOIN files f ON f.directory_id = sub.id 
                         WHERE sub.path LIKE ad.path || '/%' AND sub.is_verified = 0 AND f.name != '.DS_Store') as pending_sub_files,
                        (SELECT COALESCE(SUM(f.size_bytes), 0) 
                         FROM directories sub 
                         JOIN files f ON f.directory_id = sub.id 
                         WHERE sub.path LIKE ad.path || '/%' AND sub.is_verified = 0 AND f.name != '.DS_Store') as pending_sub_bytes,
                        COALESCE(GROUP_CONCAT(DISTINCT dt.tag_name), '-') as tags
                    FROM approved_dirs ad
                    LEFT JOIN directory_tags dt ON ad.id = dt.directory_id
                    GROUP BY ad.id
                    ORDER BY ad.path
                """)
                v_rows_raw = cursor.fetchall()
                v_rows_raw = [r for r in v_rows_raw if not (is_volume_mounted(r[2]) and not os.path.exists(r[2]))]
                v_rows = deduplicate_verified_rows_with_breadcrumbs(v_rows_raw)
                # Map location paths to identify level-1 category containers
                loc_paths = {str(loc["path"].resolve()) for loc in get_priority_locations(db_path, active_only=True)}
                all_v_paths = {r_data[2] for r_data, _ in v_rows}

                def is_parent_container_path(p_str: str) -> bool:
                    p_res = str(Path(p_str).resolve())
                    # 1. Has other verified descendants in the report:
                    if any(other_p != p_str and other_p.startswith(p_str + "/") for other_p in all_v_paths):
                        return True
                    # 2. Is directly under a Priority location (Level-1 category container like 'Data'):
                    if any(str(Path(p_res).parent) == lp for lp in loc_paths):
                        return True
                    return False

                print("\n" + "=" * 116)
                print(f"APPROVED / VERIFIED FOLDERS ({len(v_rows)} folders)")
                print("=" * 116)
                print(f"{'#':<4} {'Folder / Breadcrumb':<36} {'Status':<22} {'Approved Size':<16} {'Verified Date':<20} {'Tags'}")
                print("-" * 116)
                for idx, (r_data, breadcrumb) in enumerate(v_rows, 1):
                    did, dname, dpath, v_at, ddesc, dapp, df_cnt, df_b, vs_cnt, vs_b, pend_cnt, pend_f, pend_b, dtags = r_data
                    v_date_str = v_at.replace("T", " ")[:19] if v_at else "N/A"
                    is_parent = is_parent_container_path(dpath)

                    if not is_parent:
                        # Leaf curated folder (e.g. 'DB Backup', 'MS-Money', 'My Kindle Content', 'drive-audit')
                        # The folder itself was explicitly curated and approved — mark as Fully Verified!
                        status_badge = "✓ Fully Verified"
                        app_f = df_cnt + vs_cnt + pend_f
                        app_b = df_b + vs_b + pend_b
                        display_pend_cnt = 0
                    else:
                        # Parent category container (e.g. 'Data')
                        app_f = df_cnt + vs_cnt
                        app_b = df_b + vs_b
                        display_pend_cnt = pend_cnt
                        if display_pend_cnt == 0:
                            status_badge = "✓ Fully Verified"
                        else:
                            status_badge = "⚠️ Partially Curated"

                    stat_str = f"{app_f:,} files ({format_size(app_b)})"
                    disp_name = breadcrumb if len(breadcrumb) <= 36 else ("..." + breadcrumb[-33:])
                    print(f"{idx:<4} {disp_name:<36} {status_badge:<22} {stat_str:<16} {v_date_str:<20} {dtags}")
                    print(f"     📍 Path: {dpath}")
                    if breadcrumb != dname and len(breadcrumb) > 36:
                        print(f"     ↳ 📂 Hierarchy: {breadcrumb}")
                    if dapp:
                        print(f"     ↳ 💻 App Needed: {dapp}")
                    if display_pend_cnt > 0:
                        print(f"     ↳ ⏳ Pending Subfolders: {display_pend_cnt} folders ({pend_f:,} files, {format_size(pend_b)})")
                    if ddesc:
                        print(f"     ↳ 📝 \"{ddesc}\"")
                print("=" * 116)

                partially_curated = [r_data for r_data, _ in v_rows if is_parent_container_path(r_data[2]) and r_data[10] > 0]
                if partially_curated:
                    pend_count = len(partially_curated)
                    tot_pend_subs = sum(r[10] for r in partially_curated)
                    print(f"\n💡 Note: {pend_count} parent category container(s) have {tot_pend_subs:,} pending subfolder(s) awaiting triage.")

                exit_report = False
                while True:
                    prompt_label = "\nEnter folder # (1-N) to view contained files & details, 'r' to rescan & refresh, or Enter to return: "
                    f_drill = input(prompt_label).strip().lower()
                    if not f_drill:
                        exit_report = True
                        break
                    if f_drill in ("r", "rescan"):
                        targets = [r[2] for r in partially_curated] if partially_curated else [r_data[2] for r_data, _ in v_rows]
                        roots_to_rescan = get_minimal_scan_roots(targets)
                        if roots_to_rescan:
                            print(f"\n🔄 Rescanning {len(roots_to_rescan)} root folder(s) from disk...")
                            for r_p in roots_to_rescan:
                                print(f"  ↳ Scanning: {r_p}")
                                perform_directory_scan(r_p, db_path, skip_hours=0.0)
                            print("\n✓ Rescan complete. Refreshing report view...\n")
                            break
                        else:
                            print("\n[Notice] No target folders exist on disk to rescan.")
                            continue

                    if f_drill.isdigit():
                        f_idx = int(f_drill) - 1
                        if 0 <= f_idx < len(v_rows):
                            r_data, breadcrumb = v_rows[f_idx]
                            did, dname, dpath, v_at, ddesc, dapp, df_cnt, df_b, vs_cnt, vs_b, pend_cnt, pend_f, pend_b, dtags = r_data
                            v_date_str = v_at.replace("T", " ")[:19] if v_at else "N/A"
                            is_parent = is_parent_container_path(dpath)

                            if not is_parent:
                                app_f = df_cnt + vs_cnt + pend_f
                                app_b = df_b + vs_b + pend_b
                                display_pend_cnt = 0
                                status_str = f"✓ Fully Verified ({v_date_str})"
                            else:
                                app_f = df_cnt + vs_cnt
                                app_b = df_b + vs_b
                                display_pend_cnt = pend_cnt
                                status_str = f"✓ Fully Verified ({v_date_str})" if pend_cnt == 0 else f"⚠️ Partially Curated ({pend_cnt} unverified subfolders pending triage)"

                            # Category breakdown across approved files
                            if not is_parent:
                                cursor.execute("""
                                    SELECT f.category, COUNT(f.id), SUM(f.size_bytes)
                                    FROM directories sub
                                    JOIN files f ON f.directory_id = sub.id
                                    WHERE (sub.id = ? OR sub.path LIKE ? || '/%')
                                      AND f.name != '.DS_Store'
                                    GROUP BY f.category
                                    ORDER BY SUM(f.size_bytes) DESC
                                """, (did, dpath))
                            else:
                                cursor.execute("""
                                    SELECT f.category, COUNT(f.id), SUM(f.size_bytes)
                                    FROM directories sub
                                    JOIN files f ON f.directory_id = sub.id
                                    WHERE (sub.id = ? OR (sub.path LIKE ? || '/%' AND sub.is_verified = 1))
                                      AND f.name != '.DS_Store'
                                    GROUP BY f.category
                                    ORDER BY SUM(f.size_bytes) DESC
                                """, (did, dpath))
                            cat_breakdown = cursor.fetchall()
                            cat_str = " | ".join([f"{c}: {cnt:,} ({format_size(sb)})" for c, cnt, sb in cat_breakdown]) if cat_breakdown else "0 approved files"

                            # Fetch files in folder (up to 100)
                            if not is_parent:
                                cursor.execute("""
                                    SELECT f.name, f.category, f.extension, f.size_bytes, f.modified_at, sub.name as sub_folder
                                    FROM directories sub
                                    JOIN files f ON f.directory_id = sub.id
                                    WHERE (sub.id = ? OR sub.path LIKE ? || '/%')
                                      AND f.name != '.DS_Store'
                                    ORDER BY f.size_bytes DESC
                                    LIMIT 100
                                """, (did, dpath))
                            else:
                                cursor.execute("""
                                    SELECT f.name, f.category, f.extension, f.size_bytes, f.modified_at, sub.name as sub_folder
                                    FROM directories sub
                                    JOIN files f ON f.directory_id = sub.id
                                    WHERE (sub.id = ? OR (sub.path LIKE ? || '/%' AND sub.is_verified = 1))
                                      AND f.name != '.DS_Store'
                                    ORDER BY f.size_bytes DESC
                                    LIMIT 100
                                """, (did, dpath))
                            dir_files = cursor.fetchall()

                            print("\n" + "#" * 90)
                            print(f"  APPROVED FOLDER DETAILS: '{breadcrumb}'")
                            print("#" * 90)
                            print(f"  • Full Path:         {dpath}")
                            if breadcrumb != dname:
                                print(f"  • Hierarchy:         {breadcrumb}")
                            print(f"  • Status:            {status_str}")
                            print(f"  • Approved Storage:  {format_size(app_b)} across {app_f:,} files")
                            if dapp:
                                print(f"  • Required App:      {dapp}")
                            if display_pend_cnt > 0:
                                print(f"  • Pending Subtree:   {format_size(pend_b)} across {pend_f:,} files in {display_pend_cnt} unverified subfolders")
                            print(f"  • Folder Tags:       {dtags}")
                            print(f"  • Categories:        {cat_str}")
                            if ddesc:
                                print(f"  • Description:       \"{ddesc}\"")
                            print("-" * 90)

                            if dir_files:
                                print(f"  Contained Approved Files ({len(dir_files)} displayed):")
                                print(f"  {'#':<4} {'Subfolder':<22} {'File Name':<34} {'Category':<10} {'Size':<10} {'Modified Date'}")
                                print("  " + "-" * 86)
                                for d_fi, (df_name, df_cat, df_ext, df_sz, df_mod, df_sub) in enumerate(dir_files, 1):
                                    m_str = df_mod.replace("T", " ")[:19] if df_mod else "N/A"
                                    s_str = format_size(df_sz)
                                    disp_name = df_name if len(df_name) <= 32 else df_name[:29] + "..."
                                    disp_sub = df_sub if len(df_sub) <= 20 else df_sub[:17] + "..."
                                    print(f"  {d_fi:<4} {disp_sub:<22} {disp_name:<34} {df_cat:<10} {s_str:<10} {m_str}")
                            else:
                                print("  (Folder contains 0 directly approved files)")

                            if pend_cnt > 0:
                                cursor.execute("""
                                    SELECT sub.name, sub.path, COUNT(f.id) as cnt, COALESCE(SUM(f.size_bytes), 0) as b
                                    FROM directories sub
                                    LEFT JOIN files f ON f.directory_id = sub.id AND f.name != '.DS_Store'
                                    WHERE sub.path LIKE ? || '/%' AND sub.is_verified = 0
                                    GROUP BY sub.id
                                    ORDER BY b DESC
                                    LIMIT 15
                                """, (dpath,))
                                pending_subs = cursor.fetchall()
                                if pending_subs:
                                    print("-" * 90)
                                    print(f"  Pending Subfolders Awaiting Triage ({len(pending_subs)} displayed of {pend_cnt}):")
                                    for ps_name, ps_path, ps_f, ps_b in pending_subs:
                                        disp_pname = ps_name if len(ps_name) <= 24 else ps_name[:21] + "..."
                                        print(f"    ⏳ {disp_pname:<24} {ps_f:,} files ({format_size(ps_b)}) 📍 {ps_path}")

                            print("#" * 90)
                            drill_act = input("\n[e] Edit description or app, [u] Un-verify (remove from approved folders), or Enter to return: ").strip().lower()
                            if drill_act == 'e':
                                print(f"\nCurrent description: \"{ddesc or '(none)'}\"")
                                new_desc = input("Enter new description (or Enter to keep): ").strip()
                                print(f"Current attached app: \"{dapp or '(none)'}\"")
                                new_app = input("Enter new attached app (or Enter to keep): ").strip()
                                final_desc = new_desc if new_desc else ddesc
                                final_app = new_app if new_app else dapp
                                _set_directory_description_in_db(Path(dpath), final_desc, db_path, is_verified=True, app_needed=final_app)
                                print(f"\n[Success] ✓ Updated description & app for '{dname}' in SQLite!")
                                break
                            elif drill_act == 'u':
                                cursor.execute("UPDATE directories SET is_verified = 0, verified_at = NULL WHERE id = ?", (did,))
                                conn.commit()
                                print(f"\n[Success] ✓ Un-verified '{dname}'. Removed from Approved / Verified folders.")
                                break
                        else:
                            print(f"[Error] Invalid selection. Choose 1-{len(v_rows)}.")
                    else:
                        print(f"[Error] Invalid selection. Choose 1-{len(v_rows)}, 'r' to rescan, or Enter to return.")

                if exit_report:
                    break

        elif rep_choice == "2":
            # List All Approved Files (strictly files inside verified directories, excluding .DS_Store)
            print("\n⏳ Fetching approved files across verified directories... Please wait...")
            t_start = time.time()
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
                  AND f.name != '.DS_Store'
                GROUP BY f.id
                ORDER BY d.path, f.name
            """)
            all_v_files = cursor.fetchall()
            t_elapsed = time.time() - t_start
            print(f"✓ Retrieved {len(all_v_files):,} approved files in {t_elapsed:.2f}s.")
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
            print("\n⏳ Fetching pending / unapproved category folders... Please wait...")
            t_start = time.time()
            cursor.execute("""
                WITH unapproved_dirs AS (
                    SELECT 
                        pl.priority_tier,
                        pl.label,
                        d.id,
                        d.name,
                        d.path
                    FROM priority_locations pl
                    JOIN directories d ON (d.path LIKE pl.path || '/%' AND d.path NOT LIKE pl.path || '/%/%/%')
                    WHERE pl.is_active = 1 AND d.is_verified = 0
                )
                SELECT 
                    ud.priority_tier,
                    ud.label,
                    ud.id,
                    ud.name,
                    ud.path,
                    COUNT(CASE WHEN f.name != '.DS_Store' THEN f.id END) as sub_cnt,
                    COALESCE(SUM(CASE WHEN f.name != '.DS_Store' THEN f.size_bytes ELSE 0 END), 0) as sub_b,
                    (SELECT COUNT(f2.id) FROM files f2 WHERE f2.directory_id = ud.id AND f2.name != '.DS_Store') as dir_cnt,
                    COALESCE(GROUP_CONCAT(DISTINCT dt.tag_name), '-') as tags
                FROM unapproved_dirs ud
                LEFT JOIN directories sub ON (sub.id = ud.id OR sub.path LIKE ud.path || '/%')
                LEFT JOIN files f ON f.directory_id = sub.id
                LEFT JOIN directory_tags dt ON ud.id = dt.directory_id
                GROUP BY ud.id
                ORDER BY ud.priority_tier, ud.path
            """)
            u_rows = cursor.fetchall()
            t_elapsed = time.time() - t_start
            print(f"✓ Retrieved {len(u_rows):,} pending folders in {t_elapsed:.2f}s.")
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
                            WHERE (sub.id = ? OR sub.path LIKE ? || '/%') AND f.name != '.DS_Store'
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
                print(f"\n⏳ Loading Priority {tier_in} folders... Please wait...")
                t_filter = f"priority {tier_in}"
                cursor.execute("""
                    WITH tier_dirs AS (
                        SELECT d.id, d.name, d.path, d.is_verified, d.verified_at, d.description
                        FROM priority_locations pl
                        JOIN directories d ON (d.path = pl.path OR d.path LIKE pl.path || '/%')
                        WHERE pl.priority_tier = ? AND pl.is_active = 1
                    )
                    SELECT 
                        td.is_verified,
                        td.name,
                        td.path,
                        td.verified_at,
                        td.description,
                        (SELECT COUNT(f.id) FROM files f WHERE f.directory_id = td.id AND f.name != '.DS_Store') as dir_files,
                        (SELECT COALESCE(SUM(f.size_bytes), 0) FROM files f WHERE f.directory_id = td.id AND f.name != '.DS_Store') as dir_bytes,
                        (SELECT COUNT(f.id) FROM directories sub JOIN files f ON f.directory_id = sub.id WHERE sub.path LIKE td.path || '/%' AND sub.is_verified = 1 AND f.name != '.DS_Store') as ver_sub_files,
                        (SELECT COALESCE(SUM(f.size_bytes), 0) FROM directories sub JOIN files f ON f.directory_id = sub.id WHERE sub.path LIKE td.path || '/%' AND sub.is_verified = 1 AND f.name != '.DS_Store') as ver_sub_bytes,
                        (SELECT COUNT(sub.id) FROM directories sub WHERE sub.path LIKE td.path || '/%' AND sub.is_verified = 0) as pend_sub_cnt,
                        (SELECT COUNT(f.id) FROM directories sub JOIN files f ON f.directory_id = sub.id WHERE sub.path LIKE td.path || '/%' AND sub.is_verified = 0 AND f.name != '.DS_Store') as pend_sub_files,
                        (SELECT COALESCE(SUM(f.size_bytes), 0) FROM directories sub JOIN files f ON f.directory_id = sub.id WHERE sub.path LIKE td.path || '/%' AND sub.is_verified = 0 AND f.name != '.DS_Store') as pend_sub_bytes
                    FROM tier_dirs td
                    ORDER BY td.is_verified DESC, td.path
                """, (t_filter,))
                tier_rows = cursor.fetchall()
                t_ver_raw = [r for r in tier_rows if r[0] == 1]
                t_ver = deduplicate_verified_rows_with_breadcrumbs(
                    t_ver_raw,
                    path_idx=2, name_idx=1,
                    df_cnt_idx=5, df_b_idx=6,
                    vs_cnt_idx=7, vs_b_idx=8,
                    pend_cnt_idx=9, pend_f_idx=10
                )
                t_unver = [r for r in tier_rows if r[0] == 0]
                print("\n" + "=" * 98)
                print(f"PRIORITY {tier_in} STATUS: {len(t_ver):,} Approved | {len(t_unver):,} Pending Unapproved")
                print("=" * 98)
                print(f"\n--- APPROVED FOLDERS ({len(t_ver)}) ---")
                for idx, (row, breadcrumb) in enumerate(t_ver, 1):
                    _, dname, dpath, v_at, ddesc, df_c, df_b, vs_c, vs_b, p_cnt, p_f, p_b = row
                    app_f = df_c + vs_c
                    app_b = df_b + vs_b
                    v_date = v_at.replace("T", " ")[:19] if v_at else ""
                    if p_cnt == 0:
                        status_str = "✓ Fully Verified"
                    else:
                        status_str = f"⚠️ Partially Curated"
                    stat_str = f"{app_f:,} files ({format_size(app_b)})"
                    disp_name = breadcrumb if len(breadcrumb) <= 32 else ("..." + breadcrumb[-29:])
                    print(f"  [{idx}] {disp_name:<32} {status_str:<22} {stat_str:<16} - {v_date}")
                    print(f"      📍 Path: {dpath}")
                    if breadcrumb != dname and len(breadcrumb) > 32:
                        print(f"      ↳ 📂 Hierarchy: {breadcrumb}")
                    if p_cnt > 0:
                        print(f"      ↳ ⏳ Pending Subfolders: {p_cnt} folders ({p_f:,} files, {format_size(p_b)})")
                    if ddesc:
                        print(f"      ↳ 📝 \"{ddesc}\"")
                print(f"\n--- PENDING UNAPPROVED FOLDERS ({min(len(t_unver), 30)} of {len(t_unver):,}) ---")
                for idx, (_, dname, dpath, _, _, df_c, df_b, vs_c, vs_b, p_cnt, p_f, p_b) in enumerate(t_unver[:30], 1):
                    tot_f = df_c + vs_c + p_f
                    tot_b = df_b + vs_b + p_b
                    print(f"  [{idx}] {dname} ({tot_f:,} files, {format_size(tot_b)}) 📍 {dpath}")
                if len(t_unver) > 30:
                    print(f"  ... and {len(t_unver) - 30:,} more subfolders pending curation.")
                print("=" * 98)
                input("\nPress Enter to continue...")

        elif rep_choice == "5":
            exp_fmt = input("\nExport format [m = Markdown, c = CSV, or enter to cancel]: ").strip().lower()
            if exp_fmt == "m":
                os.makedirs("docs", exist_ok=True)
                fname = "docs/curation_status_report.md"
                cursor.execute("""
                    WITH approved_dirs AS (
                        SELECT id, name, path, is_verified, verified_at, description, app_needed
                        FROM directories
                        WHERE is_verified = 1
                    )
                    SELECT 
                        ad.id,
                        ad.name,
                        ad.path,
                        ad.verified_at,
                        ad.description,
                        ad.app_needed,
                        (SELECT COUNT(f.id) FROM files f WHERE f.directory_id = ad.id AND f.name != '.DS_Store') as dir_files,
                        (SELECT COALESCE(SUM(f.size_bytes), 0) FROM files f WHERE f.directory_id = ad.id AND f.name != '.DS_Store') as dir_bytes,
                        (SELECT COUNT(f.id) FROM directories sub JOIN files f ON f.directory_id = sub.id 
                         WHERE sub.path LIKE ad.path || '/%' AND sub.is_verified = 1 AND f.name != '.DS_Store') as ver_sub_files,
                        (SELECT COALESCE(SUM(f.size_bytes), 0) FROM directories sub JOIN files f ON f.directory_id = sub.id 
                         WHERE sub.path LIKE ad.path || '/%' AND sub.is_verified = 1 AND f.name != '.DS_Store') as ver_sub_bytes,
                        (SELECT COUNT(sub.id) FROM directories sub WHERE sub.path LIKE ad.path || '/%' AND sub.is_verified = 0) as pending_sub_folders,
                        (SELECT COUNT(f.id) FROM directories sub JOIN files f ON f.directory_id = sub.id 
                         WHERE sub.path LIKE ad.path || '/%' AND sub.is_verified = 0 AND f.name != '.DS_Store') as pending_sub_files,
                        (SELECT COALESCE(SUM(f.size_bytes), 0) FROM directories sub JOIN files f ON f.directory_id = sub.id 
                         WHERE sub.path LIKE ad.path || '/%' AND sub.is_verified = 0 AND f.name != '.DS_Store') as pending_sub_bytes
                    FROM approved_dirs ad
                    ORDER BY ad.path
                """)
                ver_list_raw = cursor.fetchall()
                ver_list = deduplicate_verified_rows_with_breadcrumbs(ver_list_raw)

                cursor.execute("""
                    SELECT d.name as folder_name, f.name, f.category, f.size_bytes, f.modified_at, d.path
                    FROM directories d
                    JOIN files f ON f.directory_id = d.id
                    WHERE d.is_verified = 1 AND f.name != '.DS_Store'
                    ORDER BY d.path, f.name
                """)
                v_files_all = cursor.fetchall()

                cursor.execute("""
                    SELECT d.id, d.name, d.path,
                           (SELECT COUNT(f.id) FROM directories sub JOIN files f ON f.directory_id = sub.id WHERE (sub.id = d.id OR sub.path LIKE d.path || '/%') AND f.name != '.DS_Store') as sub_cnt,
                           (SELECT COALESCE(SUM(f.size_bytes), 0) FROM directories sub JOIN files f ON f.directory_id = sub.id WHERE (sub.id = d.id OR sub.path LIKE d.path || '/%') AND f.name != '.DS_Store') as sub_b
                    FROM directories d
                    WHERE d.is_verified = 0
                    ORDER BY d.path
                    LIMIT 200
                """)
                unver_list = cursor.fetchall()

                with open(fname, "w", encoding="utf-8") as f:
                    f.write("# Storage Curation & Verification Status Report (Option B)\n\n")
                    f.write(f"**Generated**: `{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`  \n")
                    f.write(f"**Overall Progress**: {pct_folders:.1f}% Approved ({verified_folders:,} / {total_folders:,} folders)\n\n")
                    f.write(f"- **Approved Storage**: {format_size(verified_bytes)} across {verified_files:,} files\n")
                    f.write(f"- **Pending Storage**: {format_size(unverified_bytes)} across {unverified_files:,} files\n\n")
                    f.write("## 1. Approved / Verified Folders (`is_verified = 1`)\n\n")
                    f.write("| # | Folder / Breadcrumb | Status | Approved Files | Approved Size | Required App | Pending Subfolders | Verified Date | Description | Path |\n")
                    f.write("|---|---|---|---|---|---|---|---|---|---|\n")
                    for i, (row, breadcrumb) in enumerate(ver_list, 1):
                        _, dn, dp, va, dd, dapp, df_c, df_b, vs_c, vs_b, pend_cnt, pend_f, pend_b = row
                        v_str = va.replace("T", " ")[:19] if va else "N/A"
                        desc_str = dd.replace("|", "/") if dd else "-"
                        app_str = dapp if dapp else "-"
                        app_f = df_c + vs_c
                        app_b = df_b + vs_b
                        if pend_cnt == 0:
                            status_str = "✓ Fully Verified"
                            pend_str = "-"
                        else:
                            status_str = "⚠️ Partially Curated"
                            pend_str = f"{pend_cnt} folders ({pend_f:,} files, {format_size(pend_b)})"
                        f.write(f"| {i} | `{breadcrumb}` | {status_str} | {app_f:,} | {format_size(app_b)} | {app_str} | {pend_str} | {v_str} | {desc_str} | `{dp}` |\n")

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
                    WITH approved_dirs AS (
                        SELECT id, name, path, is_verified, verified_at, description, app_needed
                        FROM directories
                        WHERE is_verified = 1
                    )
                    SELECT 
                        ad.id,
                        ad.name,
                        ad.path,
                        ad.verified_at,
                        ad.description,
                        ad.app_needed,
                        (SELECT COUNT(f.id) FROM files f WHERE f.directory_id = ad.id AND f.name != '.DS_Store') as dir_files,
                        (SELECT COALESCE(SUM(f.size_bytes), 0) FROM files f WHERE f.directory_id = ad.id AND f.name != '.DS_Store') as dir_bytes,
                        (SELECT COUNT(f.id) FROM directories sub JOIN files f ON f.directory_id = sub.id 
                         WHERE sub.path LIKE ad.path || '/%' AND sub.is_verified = 1 AND f.name != '.DS_Store') as ver_sub_files,
                        (SELECT COALESCE(SUM(f.size_bytes), 0) FROM directories sub JOIN files f ON f.directory_id = sub.id 
                         WHERE sub.path LIKE ad.path || '/%' AND sub.is_verified = 1 AND f.name != '.DS_Store') as ver_sub_bytes,
                        (SELECT COUNT(sub.id) FROM directories sub WHERE sub.path LIKE ad.path || '/%' AND sub.is_verified = 0) as pending_sub_folders,
                        (SELECT COUNT(f.id) FROM directories sub JOIN files f ON f.directory_id = sub.id 
                         WHERE sub.path LIKE ad.path || '/%' AND sub.is_verified = 0 AND f.name != '.DS_Store') as pending_sub_files,
                        (SELECT COALESCE(SUM(f.size_bytes), 0) FROM directories sub JOIN files f ON f.directory_id = sub.id 
                         WHERE sub.path LIKE ad.path || '/%' AND sub.is_verified = 0 AND f.name != '.DS_Store') as pending_sub_bytes
                    FROM approved_dirs ad
                    ORDER BY ad.path
                """)
                ver_rows_raw = cursor.fetchall()
                ver_rows = deduplicate_verified_rows_with_breadcrumbs(ver_rows_raw)

                cursor.execute("""
                    SELECT d.id, d.name, d.path,
                           (SELECT COUNT(f.id) FROM directories sub JOIN files f ON f.directory_id = sub.id WHERE (sub.id = d.id OR sub.path LIKE d.path || '/%') AND f.name != '.DS_Store') as sub_cnt,
                           (SELECT COALESCE(SUM(f.size_bytes), 0) FROM directories sub JOIN files f ON f.directory_id = sub.id WHERE (sub.id = d.id OR sub.path LIKE d.path || '/%') AND f.name != '.DS_Store') as sub_b
                    FROM directories d
                    WHERE d.is_verified = 0
                    ORDER BY d.path
                """)
                unver_rows = cursor.fetchall()

                with open(fname, "w", newline="", encoding="utf-8") as f:
                    writer = csv.writer(f)
                    writer.writerow(["ID", "Status", "Folder / Breadcrumb", "Path", "Approved Files", "Approved Size Bytes", "Approved Size Formatted", "Required App", "Pending Subfolders Count", "Pending Subfolder Files", "Pending Subfolder Size Formatted", "Verified At", "Description"])
                    for (did, dname, dpath, vat, ddesc, dapp, df_c, df_b, vs_c, vs_b, p_cnt, p_f, p_b), breadcrumb in ver_rows:
                        status_str = "Fully Verified" if p_cnt == 0 else "Partially Curated"
                        app_f = df_c + vs_c
                        app_b = df_b + vs_b
                        writer.writerow([did, status_str, breadcrumb, dpath, app_f, app_b, format_size(app_b), dapp or "", p_cnt, p_f, format_size(p_b), vat or "", ddesc or ""])
                    for did, dname, dpath, sub_cnt, sub_b in unver_rows:
                        writer.writerow([did, "Pending / Unapproved", dname, dpath, 0, 0, "0 B", "", 0, sub_cnt, format_size(sub_b), "", ""])
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
    "priority 1": "Active & critical personal data (Quicken financial DBs, essential identity & legal documents) — Stored ONLY on high-availability storage (Internal HD for iMini) with applicable apps, backed up to iDrive",
    "priority 2": "Systems, developer projects, profiles, and legacy application archives (e.g. MS Money) — Stored primarily on external storage (LaCie / secondary drives), backed up to iDrive for reference",
    "priority 3": "Archival references, foreign media, downloaded materials, and historical records — Stored on low-availability external drive, not backed up to iDrive",
    "priority 4": "Central media staging depot (photos and home videos awaiting Media Organizer intake) — Temporary external storage, no backup",
}

DEFAULT_LEVEL1_DESCRIPTIONS = {
    # Priority 1 (Active & Critical Personal Data)
    ("priority 1", "data"): "Critical financial & account databases (Quicken .qdf, active tax/financial records)",
    ("priority 1", "documents"): "Vital personal identity, legal, medical, and essential personal documentation",

    # Priority 2 (Systems, Developer Projects, Profiles & Software)
    ("priority 2", "data"): "Secondary financial data & application archives (backed up to iDrive for reference)",
    ("priority 2", "legacy / windows data"): "Legacy Windows application data archives (e.g. MS Money .mny/.mbf, backed up to iDrive for reference)",
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

def _set_directory_description_in_db(dir_path: Path, description: str | None, db_path: str, is_verified: bool = False, app_needed: str | None = None):
    """Sets or updates description, verification and app_needed columns for a directory in SQLite database."""
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

        cursor.execute("SELECT id, app_needed FROM directories WHERE host_id = ? AND path = ?", (host_id, res_p))
        row = cursor.fetchone()
        if not row:
            d_stat = dir_path.stat()
            cursor.execute("""
                INSERT INTO directories (host_id, path, name, created_at, modified_at, scanned_at, description, is_verified, verified_at, app_needed)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (host_id, res_p, dir_path.name,
                  datetime.datetime.fromtimestamp(d_stat.st_ctime).isoformat(),
                  datetime.datetime.fromtimestamp(d_stat.st_mtime).isoformat(),
                  scan_time, description, verified_val, verified_at_val, app_needed))
        else:
            final_app = app_needed if app_needed is not None else row[1]
            if is_verified:
                cursor.execute("""
                    UPDATE directories 
                    SET description = ?, is_verified = ?, verified_at = ?, app_needed = ?
                    WHERE id = ?
                """, (description, verified_val, verified_at_val, final_app, row[0]))
            else:
                cursor.execute("""
                    UPDATE directories 
                    SET description = ?, app_needed = COALESCE(?, app_needed)
                    WHERE id = ?
                """, (description, app_needed, row[0]))
        conn.commit()
        conn.close()
    except Exception:
        pass

def _rename_directory_on_disk_and_db(old_dir: Path, new_name: str, db_path: str) -> tuple[bool, Path, str]:
    """
    Safely renames a directory on disk, updates all SQLite directory and tag records,
    and synchronizes macOS Finder tags. Returns (success, new_path, error_message).
    """
    if not old_dir.exists():
        return False, old_dir, f"Source directory '{old_dir}' does not exist on disk."

    new_dir = old_dir.parent / new_name
    if new_dir.resolve() == old_dir.resolve():
        return True, old_dir, "Name unchanged."

    if new_dir.exists():
        return False, old_dir, f"Destination directory '{new_dir}' already exists on disk."

    try:
        old_p = str(old_dir.resolve())
        old_name = old_dir.name

        # Read current Finder tags before moving
        cur_ftags = get_finder_tags_with_details(old_dir)

        # Rename on disk
        shutil.move(str(old_dir), str(new_dir))
        new_p = str(new_dir.resolve())

        # Update SQLite
        if os.path.exists(db_path):
            conn = get_db_connection(db_path)
            cur = conn.cursor()
            # Update directory path and all child paths
            cur.execute("""
                UPDATE directories
                SET path = ? || SUBSTR(path, LENGTH(?) + 1)
                WHERE path = ? OR path LIKE ? || '/%'
            """, (new_p, old_p, old_p, old_p))
            # Update directory name itself
            cur.execute("UPDATE directories SET name = ? WHERE path = ?", (new_name, new_p))
            # Update directory tags matching the old folder name
            cur.execute("""
                UPDATE directory_tags
                SET tag_name = ?
                WHERE tag_name = ? AND directory_id IN (SELECT id FROM directories WHERE path = ?)
            """, (new_name, old_name, new_p))
            conn.commit()
            conn.close()

        # Update Finder tags on disk: replace old folder name tag with new name
        if cur_ftags:
            updated_tags = []
            for t in cur_ftags:
                t_name = new_name if t["name"] == old_name else t["name"]
                updated_tags.append((t_name, t["color"]))
            set_finder_tags(new_dir, updated_tags)
            _sync_directory_tags_to_db(new_dir, updated_tags, db_path)

        return True, new_dir, ""
    except Exception as e:
        return False, old_dir, str(e)

def analyze_folder_content(folder_path: Path, max_depth: int = 3) -> dict:
    """Fast content profiler for a subfolder to assist the curation wizard."""
    total_files = 0
    total_bytes = 0
    ext_counts = Counter()
    sample_files = []
    mtimes = []
    subfolders = []
    no_ext_files = []

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
                        no_ext_files.append(f_path)
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
        "subfolder_count": len(subfolders),
        "no_ext_files": no_ext_files
    }

def inspect_file_magic(file_path: Path, base_folder: Path = None) -> dict:
    """Inspects file magic bytes and suggests extension and file category."""
    rel_path = str(file_path.relative_to(base_folder)) if base_folder else str(file_path)
    try:
        stat = file_path.stat()
        size_bytes = stat.st_size
        size_str = format_size(size_bytes)
    except Exception:
        size_bytes = 0
        size_str = "0 B"

    buf = b""
    try:
        with open(file_path, "rb") as f:
            buf = f.read(512)
    except Exception:
        pass

    raw_hex = " ".join(f"{b:02x}" for b in buf[:16])
    raw_asc = "".join(chr(b) if 32 <= b < 127 else "." for b in buf[:16])

    suggested_ext = None
    short_type = "Unknown"
    full_type = "Unknown binary data"
    extra_notes = ""

    # Check for known signatures
    if len(buf) >= 19 and buf[4:19] == b"MSISAM Database":
        suggested_ext = ".mny"
        short_type = "MS Money DB (.mny)"
        full_type = "Microsoft Money Active Database (.mny) [Windows Jet/ISAM]"
        extra_notes = "Proprietary accounting database used by discontinued Microsoft Money"
    elif len(buf) >= 19 and buf[4:19] == b"Standard Jet DB":
        suggested_ext = ".mdb"
        short_type = "MS Access DB (.mdb)"
        full_type = "Microsoft Access Jet Database (.mdb)"
    elif len(buf) >= 19 and buf[4:19] == b"Standard ACE DB":
        suggested_ext = ".accdb"
        short_type = "MS Access DB (.accdb)"
        full_type = "Microsoft Access 2007+ Database (.accdb)"
    elif len(buf) >= 4 and buf[:4] == b"MSCF":
        # Cabinet file - check if internal filename has mbf or tmp
        buf_low = buf.lower()
        if b"mbf" in buf_low or b".tmp" in buf_low:
            suggested_ext = ".mbf"
            short_type = "MS Money Backup (.mbf)"
            full_type = "Microsoft Money Backup Archive (.mbf) [CAB format]"
            extra_notes = "Compressed backup archive created by discontinued Microsoft Money"
        else:
            suggested_ext = ".cab"
            short_type = "Cabinet Archive (.cab)"
            full_type = "Microsoft Cabinet Archive (.cab)"
    elif len(buf) >= 16 and buf[:16] == b"SQLite format 3\x00":
        suggested_ext = ".sqlite"
        short_type = "SQLite DB (.sqlite)"
        full_type = "SQLite 3 Database (.sqlite/.db)"
    elif len(buf) >= 5 and buf[:5] == b"%PDF-":
        suggested_ext = ".pdf"
        short_type = "PDF (.pdf)"
        full_type = "Adobe PDF Document (.pdf)"
    elif len(buf) >= 3 and buf[:3] == b"\xff\xd8\xff":
        suggested_ext = ".jpg"
        short_type = "JPEG (.jpg)"
        full_type = "JPEG Image (.jpg)"
    elif len(buf) >= 8 and buf[:8] == b"\x89PNG\r\n\x1a\n":
        suggested_ext = ".png"
        short_type = "PNG (.png)"
        full_type = "PNG Image (.png)"
    elif len(buf) >= 6 and buf[:6] in (b"GIF87a", b"GIF89a"):
        suggested_ext = ".gif"
        short_type = "GIF (.gif)"
        full_type = "GIF Image (.gif)"
    elif len(buf) >= 2 and buf[:2] == b"BM":
        suggested_ext = ".bmp"
        short_type = "Bitmap (.bmp)"
        full_type = "BMP Image (.bmp)"
    elif len(buf) >= 12 and buf[:4] == b"RIFF" and buf[8:12] == b"WEBP":
        suggested_ext = ".webp"
        short_type = "WebP (.webp)"
        full_type = "Google WebP Image (.webp)"
    elif len(buf) >= 4 and buf[:4] == b"PK\x03\x04":
        if b"word/" in buf:
            suggested_ext = ".docx"
            short_type = "Word Doc (.docx)"
            full_type = "Microsoft Word Document (.docx)"
        elif b"xl/" in buf:
            suggested_ext = ".xlsx"
            short_type = "Excel Sheet (.xlsx)"
            full_type = "Microsoft Excel Spreadsheet (.xlsx)"
        elif b"ppt/" in buf:
            suggested_ext = ".pptx"
            short_type = "PowerPoint (.pptx)"
            full_type = "Microsoft PowerPoint Presentation (.pptx)"
        else:
            suggested_ext = ".zip"
            short_type = "ZIP (.zip)"
            full_type = "ZIP Archive (.zip)"
    elif len(buf) >= 2 and buf[:2] == b"\x1f\x8b":
        suggested_ext = ".gz"
        short_type = "GZIP (.gz)"
        full_type = "GZIP Compressed Archive (.gz)"
    elif len(buf) >= 3 and buf[:3] == b"BZh":
        suggested_ext = ".bz2"
        short_type = "BZip2 (.bz2)"
        full_type = "BZip2 Compressed Archive (.bz2)"
    elif len(buf) >= 6 and buf[:6] == b"7z\xbc\xaf\x27\x1c":
        suggested_ext = ".7z"
        short_type = "7-Zip (.7z)"
        full_type = "7-Zip Archive (.7z)"
    elif len(buf) >= 4 and buf[:4] == b"Rar!":
        suggested_ext = ".rar"
        short_type = "RAR (.rar)"
        full_type = "RAR Archive (.rar)"
    elif len(buf) >= 2 and buf[:2] == b"MZ":
        suggested_ext = ".exe"
        short_type = "Windows EXE (.exe)"
        full_type = "Windows PE Executable / DLL (.exe)"
    elif len(buf) >= 4 and buf[:4] in (b"\xfe\xed\xfa\xce", b"\xfe\xed\xfa\xcf", b"\xce\xfa\xed\xfe", b"\xcf\xfa\xed\xfe", b"\xca\xfe\xba\xbe"):
        short_type = "Mach-O Binary"
        full_type = "macOS Mach-O Binary Executable"
    elif len(buf) >= 2 and buf[:2] == b"#!":
        suggested_ext = ".sh"
        short_type = "Script (.sh)"
        full_type = "Shell Script Executable (.sh)"
    else:
        # Check text
        try:
            text_snippet = buf.decode("utf-8")
            if text_snippet.strip().startswith(("{", "[")):
                suggested_ext = ".json"
                short_type = "JSON (.json)"
                full_type = "JSON Data Document (.json)"
            elif text_snippet.strip().lower().startswith(("<?xml", "<html", "<!doctype")):
                suggested_ext = ".xml" if "<?xml" in text_snippet.lower() else ".html"
                short_type = f"{suggested_ext.upper()[1:]} Document"
                full_type = f"{short_type} ({suggested_ext})"
            elif all(c in '\r\n\t' or 32 <= ord(c) < 127 for c in text_snippet[:100]):
                suggested_ext = ".txt"
                short_type = "Text (.txt)"
                full_type = "Plain Text Document (.txt)"
        except Exception:
            pass

    # If still unknown, fallback to system file command if available
    if short_type == "Unknown" and shutil.which("file"):
        try:
            res = subprocess.run(["file", "-b", str(file_path)], capture_output=True, text=True, timeout=2)
            out = res.stdout.strip()
            if out and out.lower() != "data":
                short_type = out.split(",")[0][:30]
                full_type = out
        except Exception:
            pass

    # If filename indicates spideroak temp
    if "spideroak_temp" in file_path.name.lower():
        extra_notes = (extra_notes + " | " if extra_notes else "") + "SpiderOak cloud backup chunk cache file"

    return {
        "file_path": file_path,
        "name": file_path.name,
        "rel_path": rel_path,
        "size_bytes": size_bytes,
        "size_str": size_str,
        "hex_dump": raw_hex,
        "ascii_dump": raw_asc,
        "short_type": short_type,
        "full_type": full_type,
        "suggested_ext": suggested_ext,
        "extra_notes": extra_notes
    }

def format_hexdump(data: bytes, bytes_per_line: int = 16) -> str:
    """Formats binary bytes into classic hex + ASCII dump representation."""
    lines = []
    for offset in range(0, len(data), bytes_per_line):
        chunk = data[offset:offset + bytes_per_line]
        part1 = " ".join(f"{b:02x}" for b in chunk[:8])
        part2 = " ".join(f"{b:02x}" for b in chunk[8:])
        hex_str = f"{part1:<23}  {part2:<23}"
        asc_str = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
        lines.append(f"{offset:08x}  {hex_str} |{asc_str}|")
    return "\n".join(lines)

def _handle_inspect_mystery_files(sub_dir: Path, analyses: list[dict], db_path: str) -> bool:
    """
    Interactive sub-screen to inspect mystery/extensionless files, view raw hex dumps,
    and optionally restore suggested extensions on disk & SQLite.
    Returns True if any file was renamed on disk.
    """
    has_renamed_any = False
    while True:
        print("\n" + "=" * 80)
        print(f"  🔍 MYSTERY & EXTENSIONLESS FILE INSPECTOR")
        print(f"  Folder: '{sub_dir.name}'  |  Total Files Without Extension: {len(analyses)}")
        print("=" * 80)

        for idx, item in enumerate(analyses, 1):
            print(f"\n  [{idx}] {item['name']}")
            print(f"      • Relative Path:  {item['rel_path']}")
            print(f"      • File Size:      {item['size_str']}")
            print(f"      • Magic Header:   {item['hex_dump']} ({item['ascii_dump']})")
            print(f"      • Identified:     {item['full_type']}")
            if item.get("suggested_ext"):
                print(f"      • Suggested Ext:  {item['suggested_ext']}")
            if item.get("extra_notes"):
                print(f"      • Notes:          {item['extra_notes']}")

        print("\n" + "-" * 80)
        print("  Actions:")
        print("    [v] View raw hex dump (first 128 bytes) of a file")
        print("    [r] Restore suggested extensions (Safe rename on disk & SQLite)")
        print("    [b] Return to Curation Wizard")
        print("-" * 80)

        m_act = input("\nSelect mystery action [v/r/b] (Default: b): ").strip().lower()
        if not m_act or m_act == 'b':
            break

        if m_act == 'v':
            v_sel = input(f"Select file number to view (1-{len(analyses)}) or 'b' to back: ").strip()
            if not v_sel.isdigit() or int(v_sel) < 1 or int(v_sel) > len(analyses):
                continue
            selected_file = analyses[int(v_sel) - 1]
            try:
                with open(selected_file["file_path"], "rb") as f:
                    chunk = f.read(128)
                print("\n" + "=" * 80)
                print(f"  RAW HEX DUMP (First 128 bytes): {selected_file['name']}")
                print(f"  Path: {selected_file['rel_path']}")
                print("=" * 80)
                print(format_hexdump(chunk))
                print("=" * 80)
                input("\nPress Enter to return to mystery inspector...")
            except Exception as e:
                print(f"[Error] Could not read file: {e}")
                input("Press Enter to continue...")

        elif m_act == 'r':
            renamable = [m for m in analyses if m.get("suggested_ext") and m["file_path"].exists()]
            if not renamable:
                print("\n[Notice] No files with suggested extensions found to restore.")
                input("Press Enter to continue...")
                continue

            print("\n" + "=" * 80)
            print("  PROPOSED FILE EXTENSION RESTORATIONS")
            print("=" * 80)
            for idx, r_item in enumerate(renamable, 1):
                new_name = f"{r_item['file_path'].name}{r_item['suggested_ext']}"
                print(f"  {idx}. {r_item['name']}  →  {new_name}")

            confirm_r = input(f"\nRestore suggested extensions to {len(renamable)} file(s) on disk & SQLite? [y/N]: ").strip().lower()
            if confirm_r != 'y':
                print("Operation cancelled.")
                continue

            success_count = 0
            conn = None
            try:
                if os.path.exists(db_path):
                    conn = get_db_connection(db_path)
            except Exception:
                conn = None

            for r_item in renamable:
                old_p = r_item["file_path"]
                new_ext = r_item["suggested_ext"]
                new_p = old_p.parent / f"{old_p.name}{new_ext}"
                if new_p.exists():
                    print(f"  [Skipped] Destination already exists: {new_p.name}")
                    continue
                try:
                    old_p.rename(new_p)
                    if conn:
                        try:
                            parent_dir_str = str(old_p.parent.resolve())
                            new_cat = get_file_category(new_ext).title()
                            conn.execute("""
                                UPDATE files
                                SET name = ?, extension = ?, category = ?
                                WHERE directory_id = (SELECT id FROM directories WHERE path = ?)
                                  AND name = ?
                            """, (new_p.name, new_ext, new_cat, parent_dir_str, old_p.name))
                            conn.commit()
                        except Exception:
                            pass
                    r_item["file_path"] = new_p
                    r_item["name"] = new_p.name
                    success_count += 1
                    print(f"  ✓ Renamed: {old_p.name} → {new_p.name}")
                except Exception as e:
                    print(f"  [Error] Failed to rename {old_p.name}: {e}")

            if conn:
                try:
                    conn.close()
                except Exception:
                    pass

            if success_count > 0:
                has_renamed_any = True
                print(f"\n[Success] Restored extensions for {success_count} file(s)!")
                analyses = [m for m in analyses if not m["name"].endswith(m.get("suggested_ext", "___"))]
                if not analyses:
                    print("All mystery files have been restored with their proper extensions.")
                    input("Press Enter to return to Curation Wizard...")
                    break
                input("Press Enter to return to mystery inspector...")

    return has_renamed_any

def identify_folder_filetypes_and_apps(db_path: str, ext_counts: Counter, l1_name: str, tier_name: str) -> dict:
    """
    Performs file type identification, maps found extensions to their categories and required applications,
    and checks if the files belong to the expected category/priority tier.
    """
    if not ext_counts:
        return {
            "file_types_formatted": "None",
            "app_needed": "None",
            "primary_category": "Empty",
            "category_percent": 0.0,
            "is_match": True,
            "category_match_msg": "⚪ Empty folder (0 files)",
            "suggested_move_tier": None
        }

    db_ext_map = {}
    try:
        conn = get_db_connection(db_path)
        cursor = conn.cursor()
        ext_list = [e for e in ext_counts.keys() if e != '(no ext)']
        if ext_list:
            placeholders = ",".join("?" for _ in ext_list)
            cursor.execute(f"""
                SELECT extension, category, description, primary_app, mac_app, is_critical_format
                FROM file_extensions
                WHERE extension IN ({placeholders})
            """, ext_list)
            for row in cursor.fetchall():
                db_ext_map[row[0].lower()] = {
                    "category": row[1],
                    "description": row[2],
                    "primary_app": row[3],
                    "mac_app": row[4],
                    "critical": bool(row[5])
                }
        conn.close()
    except Exception:
        pass

    for ext in ext_counts.keys():
        if ext == '(no ext)':
            continue
        ext_lower = ext.lower()
        if ext_lower not in db_ext_map:
            if ext_lower.startswith('.mny'):
                db_ext_map[ext_lower] = {
                    "category": "Financial Data",
                    "description": f"MS Money DB Snapshot ({ext_lower.lstrip('.')})",
                    "primary_app": "Windows Microsoft Money (Discontinued)",
                    "mac_app": "Archival Backup Only (Unusable on Mac/PC without legacy Windows VM)",
                    "critical": True
                }
            elif ext_lower.startswith('.mbf'):
                db_ext_map[ext_lower] = {
                    "category": "Financial Data",
                    "description": f"MS Money Backup Archive ({ext_lower.lstrip('.')})",
                    "primary_app": "Windows Microsoft Money (Discontinued)",
                    "mac_app": "Archival Backup Only (Unusable on Mac/PC without legacy Windows VM)",
                    "critical": True
                }
            elif ext_lower.startswith('.lrd'):
                db_ext_map[ext_lower] = {
                    "category": "Financial Data",
                    "description": f"MS Money Lock/Report Def ({ext_lower.lstrip('.')})",
                    "primary_app": "Windows Microsoft Money (Discontinued)",
                    "mac_app": "Archival Backup Only (Unusable on Mac/PC without legacy Windows VM)",
                    "critical": True
                }
            else:
                cat = get_file_category(ext_lower).title()
                db_ext_map[ext_lower] = {
                    "category": cat,
                    "description": f"{ext_lower.upper().lstrip('.')} File",
                    "primary_app": f"{ext_lower.upper().lstrip('.')} Viewer",
                    "mac_app": None,
                    "critical": False
                }

    # Format top extensions with descriptions
    ext_summary_parts = []
    top_exts = ext_counts.most_common(5) if hasattr(ext_counts, 'most_common') else sorted(ext_counts.items(), key=lambda x: x[1], reverse=True)[:5]
    for ext, cnt in top_exts:
        if ext == '(no ext)':
            ext_summary_parts.append(f"{cnt} (no ext)")
        else:
            info = db_ext_map.get(ext.lower(), {})
            desc = info.get("description", ext)
            desc = desc.replace("Microsoft Money", "MS Money").replace("Account Database", "DB").replace("Transaction Data", "Data")
            ext_summary_parts.append(f"{cnt} {ext} ({desc})")
    file_types_formatted = ", ".join(ext_summary_parts) if ext_summary_parts else "None"

    # Identify primary app needed
    app_weights = Counter()
    app_mac_map = {}
    for ext, cnt in ext_counts.items():
        if ext != '(no ext)':
            info = db_ext_map.get(ext.lower())
            if info:
                p_app = info["primary_app"]
                m_app = info["mac_app"]
                app_weights[p_app] += cnt
                if m_app:
                    app_mac_map[p_app] = m_app

    detected_app = "General Viewer"
    if app_weights:
        top_app, _ = app_weights.most_common(1)[0]
        mac_alt = app_mac_map.get(top_app)
        if mac_alt and mac_alt.strip().lower() != top_app.strip().lower():
            detected_app = f"{top_app} (Mac: {mac_alt})"
        else:
            detected_app = top_app

    # Category analysis and verification
    cat_weights = Counter()
    total_non_empty = sum(cnt for ext, cnt in ext_counts.items() if ext != '(no ext)')
    for ext, cnt in ext_counts.items():
        if ext != '(no ext)':
            info = db_ext_map.get(ext.lower())
            cat_name = info["category"] if info else "Other"
            cat_weights[cat_name] += cnt

    # Build structured application groups
    grouped_map = defaultdict(lambda: {"count": 0, "app_name": "", "mac_note": None, "ext_items": []})
    for ext, cnt in ext_counts.items():
        if ext == '(no ext)':
            continue
        info = db_ext_map.get(ext.lower(), {})
        p_app = info.get("primary_app", "General Viewer")
        m_app = info.get("mac_app")
        desc = info.get("description", ext)
        clean_desc = (desc.replace(" (Discontinued format)", "")
                          .replace("(Discontinued format)", "")
                          .replace("Microsoft Money", "MS Money")
                          .replace("Account Database", "DB")
                          .replace("Transaction Data", "Data")
                          .strip())

        mac_note = None
        if m_app and ("unusable" in m_app.lower() or "archival" in m_app.lower()):
            mac_note = m_app
            p_app_display = p_app
        elif m_app and m_app.strip().lower() != p_app.strip().lower():
            p_app_display = f"{p_app} (Mac: {m_app})"
        else:
            p_app_display = p_app

        grouped_map[p_app_display]["count"] += cnt
        grouped_map[p_app_display]["app_name"] = p_app_display
        if mac_note:
            grouped_map[p_app_display]["mac_note"] = mac_note
        grouped_map[p_app_display]["ext_items"].append({"ext": ext, "cnt": cnt, "label": f"{cnt} {ext} ({clean_desc})"})

    app_groups = []
    for app_name, g_data in sorted(grouped_map.items(), key=lambda x: x[1]["count"], reverse=True):
        sorted_exts = sorted(g_data["ext_items"], key=lambda x: x["cnt"], reverse=True)
        app_groups.append({
            "name": app_name,
            "count": g_data["count"],
            "mac_note": g_data["mac_note"],
            "exts": [e["label"] for e in sorted_exts]
        })

    top_cat = "Other"
    top_pct = 0.0
    if cat_weights and total_non_empty > 0:
        top_cat, top_cnt = cat_weights.most_common(1)[0]
        top_pct = (top_cnt / total_non_empty) * 100.0

    t_lower = tier_name.lower()
    l1_lower = l1_name.lower()

    is_match = True
    match_msg = f"✓ {top_pct:.0f}% {top_cat} (Consistent with {tier_name} / {l1_name})"
    suggested_move = None
    # Check for unusable / discontinued applications
    has_unusable_app = False
    unusable_file_count = 0
    for ext, cnt in ext_counts.items():
        if ext != '(no ext)':
            info = db_ext_map.get(ext.lower(), {})
            p_app = (info.get("primary_app") or "").lower()
            m_app = (info.get("mac_app") or "").lower()
            desc = (info.get("description") or "").lower()
            is_unusable = (
                "discontinued" in p_app
                or "discontinued" in desc
                or "unusable" in m_app
                or "archival backup only" in m_app
                or "legacy windows vm" in m_app
                or "no modern app" in m_app
            )
            if is_unusable:
                unusable_file_count += cnt

    # Enforce Rule: All files in Priority 1 must have an applicable app to open them directly,
    # and Priority 1 is reserved strictly for high-availability internal storage (Internal HD for iMini).
    # Discontinued formats (like MS Money) belong on external storage (LaCie Priority 2) with iDrive backup.
    if "priority 1" in t_lower and (unusable_file_count > 0 or "discontinued" in detected_app.lower() or "unusable" in detected_app.lower()):
        has_unusable_app = True
        is_match = False
        suggested_move = "Priority 2 / Data or Priority 2 / Legacy / Windows Data (LaCie)"
        match_msg = (
            f"⚠️ Storage Policy Violation: Files cannot be opened directly ({unusable_file_count}/{total_non_empty} files in discontinued/unusable format)! "
            f"Priority 1 is reserved ONLY for high-availability internal storage (Internal HD for iMini) with active applications. "
            f"Recommended: Move to external storage on LaCie ('Priority 2 / Data' or 'Priority 2 / Legacy / Windows Data', backed up to iDrive for reference)"
        )
    # Check Tier 1 Category Mismatches:
    elif "priority 1" in t_lower:
        if top_cat in ["Video", "RAW Photography"] and top_pct >= 50:
            is_match = False
            suggested_move = "Priority 4 (Media Staging & Photos)"
            match_msg = f"⚠️ Category Mismatch: {top_pct:.0f}% {top_cat} in '{tier_name} / {l1_name}'! Recommended: {suggested_move}"
        elif top_cat in ["Source Code"] and top_pct >= 50:
            is_match = False
            suggested_move = "Priority 2 (DEV & Systems)"
            match_msg = f"⚠️ Category Mismatch: {top_pct:.0f}% Source Code in '{tier_name} / {l1_name}'! Recommended: {suggested_move}"

    # Check Tier 4 Mismatches:
    elif "priority 4" in t_lower:
        if top_cat in ["Financial Data", "Database", "Tax Records"] and top_pct >= 50:
            is_match = False
            suggested_move = "Priority 1 (Active & Critical Data)"
            match_msg = f"⚠️ Category Mismatch: {top_pct:.0f}% {top_cat} in Media tier! Recommended: {suggested_move}"
        elif top_cat in ["Source Code"] and top_pct >= 50:
            is_match = False
            suggested_move = "Priority 2 (DEV & Systems)"
            match_msg = f"⚠️ Category Mismatch: {top_pct:.0f}% Source Code in Media tier! Recommended: {suggested_move}"

    # Check Tier 2 Mismatches:
    elif "priority 2" in t_lower:
        if top_cat in ["Video", "RAW Photography"] and top_pct >= 50:
            is_match = False
            suggested_move = "Priority 4 (Media Staging & Photos)"
            match_msg = f"⚠️ Category Mismatch: {top_pct:.0f}% {top_cat} in DEV tier! Recommended: {suggested_move}"

    return {
        "file_types_formatted": file_types_formatted,
        "app_needed": detected_app,
        "primary_category": top_cat,
        "category_percent": top_pct,
        "is_match": is_match,
        "category_match_msg": match_msg,
        "suggested_move_tier": suggested_move,
        "has_unusable_app": has_unusable_app,
        "unusable_file_count": unusable_file_count,
        "app_groups": app_groups
    }

def suggest_clean_folder_name(folder_name: str, detected_app: str | None = None, ext_counts: dict | None = None) -> str:
    """Suggests a modernized, clean folder name by stripping legacy numbered prefixes and standardizing app naming."""
    lower_name = folder_name.lower()
    app_lower = (detected_app or "").lower()
    exts = ext_counts or {}

    # Check for MS Money
    if any(ext in exts for ext in [".mny", ".mbf", ".lrd"]) or "microsoft money" in app_lower or "ms money" in app_lower:
        return "MS-Money"

    # Check for Quicken
    if any(ext in exts for ext in [".qdf", ".qel", ".qsd", ".qph"]) or "quicken" in app_lower:
        return "Quicken"

    # Check for TurboTax
    if any(ext.startswith(".tax") for ext in exts) or "turbotax" in app_lower:
        return "Tax-Returns"

    # Remove leading numeric prefixes like "01-", "13.", "02_Data.", "13-Data."
    cleaned = re.sub(r'^\d+[\s._-]+(?:(?:data|DATA)[\s._-]+)?', '', folder_name)
    # Replace dots or underscores with dashes if appropriate
    cleaned = re.sub(r'[._]+', '-', cleaned).strip('- ')

    return cleaned if cleaned else folder_name

def suggest_folder_description(folder_name: str, parent_l1_name: str, tier_name: str, stats: dict, ft_info: dict | None = None) -> str:
    """Intelligently suggests a concise human-readable description for a folder based on its name, contents, and detected applications."""
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

    if ft_info:
        top_cat = ft_info.get("primary_category")
        app = ft_info.get("app_needed", "")
        if "Microsoft Money" in app or top_cat == "Financial Data":
            if "money" in name_lower or ".mny" in ext_counts or ".mbf" in ext_counts:
                return f"Discontinued Microsoft Money financial archives & backups (.mny, .mbf{year_str}) — Archival backup only (unusable without legacy Windows VM)"
            return f"Financial account databases & transaction records{year_str}"
        if "Quicken" in app:
            return f"Quicken personal financial accounts & tax records (.qdf{year_str})"
        if "TurboTax" in app or top_cat == "Tax Records":
            return f"Historical tax returns & IRS filing records{year_str}"
        if top_cat == "Database":
            return f"Database SQL dumps & backup snapshots (.sql{year_str})"
        if "Photoshop" in app:
            return f"Adobe Photoshop design project files & creative assets (.psd{year_str})"
        if "Lightroom" in app or top_cat == "RAW Photography":
            return f"RAW digital photo archives & camera master shoots{year_str}"

    # Specific name & signature heuristics
    if "money" in name_lower or ".mny" in ext_counts or ".mbf" in ext_counts:
        return f"Discontinued Microsoft Money financial archives & backups (.mny, .mbf{year_str}) — Archival backup only (unusable without legacy Windows VM)"
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

        loc_actions = [
            {"key": "1", "label": "Add a new folder location mapping to a Priority level"},
            {"key": "2", "label": "Toggle Active / Inactive status of a location"},
            {"key": "3", "label": "Edit location Label or Description"},
            {"key": "4", "label": "Remove / Unmap a location"},
            {"key": "5", "label": "Return to previous menu"}
        ]
        loc_usage = get_menu_option_usage(db_path, "locations_manager_menu")
        sorted_loc = sorted(loc_actions, key=lambda x: loc_usage.get(x["key"], 0), reverse=True)
        top_loc = sorted_loc[0]["key"] if (loc_usage and loc_usage.get(sorted_loc[0]["key"], 0) > 0) else "1"

        print("\nActions:")
        for la in sorted_loc:
            cnt = loc_usage.get(la["key"], 0)
            badge = f" (Used {cnt}x) 🔥" if cnt > 0 and cnt == max(loc_usage.values()) else (f" (Used {cnt}x)" if cnt > 0 else "")
            def_badge = " [Default]" if la["key"] == top_loc and loc_usage.get(top_loc, 0) > 0 else ""
            print(f"  {la['key']}. {la['label']}{badge}{def_badge}")

        def_prompt = f" [Default: {top_loc}]" if (loc_usage and loc_usage.get(top_loc, 0) > 0) else ""
        raw_loc = input(f"\nSelect action (1-5){def_prompt}: ").strip()
        choice = raw_loc if raw_loc else (top_loc if (loc_usage and loc_usage.get(top_loc, 0) > 0) else "")
        record_menu_usage(db_path, "locations_manager_menu", choice, next((a["label"] for a in loc_actions if a["key"] == choice), ""))
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

            # Step 1: Retain location root configuration without auto-approving uncurated subfolders
            # (Subfolders remain is_verified = 0 until explicitly approved by the user in the curation wizard)

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

def apply_hierarchical_tags_for_path(
    target_path: Path,
    target_loc: dict,
    db_path: str,
    leaf_desc: str | None = None,
    leaf_app: str | None = None
) -> None:
    """
    Applies macOS Finder color & category tags and SQLite metadata for EACH level in the
    hierarchy from the target location root down to the target folder path.
    """
    loc_path = target_loc["path"]
    p_tier_name = target_loc.get("priority_tier", "priority 2").lower()
    p_info = PRIORITY_TIER_CONFIG.get(p_tier_name, {"tag": "Priority 2", "color": 4})
    p_em = FINDER_COLOR_EMOJI.get(p_info.get("color", 4), "⚪")
    tier_tag = p_info["tag"]
    tier_color = p_info["color"]

    try:
        rel = target_path.resolve().relative_to(loc_path.resolve())
        parts = rel.parts
        base_dir = loc_path
    except Exception:
        parts = target_path.parts[1:]
        base_dir = Path(target_path.anchor)

    print("\n  Applying hierarchical Finder tags & SQLite metadata:")
    curr = base_dir
    for i, part in enumerate(parts):
        curr = curr / part
        if not curr.exists():
            continue
        is_leaf = (i == len(parts) - 1)
        
        # Build tags for this specific level: Tier Tag (with color) + all category ancestors down to this level
        level_tags = [(tier_tag, tier_color)]
        seen = {tier_tag}
        for p in parts[:i+1]:
            clean_p = p.strip()
            if clean_p and clean_p not in seen:
                seen.add(clean_p)
                level_tags.append((clean_p, 0))

        # Apply native macOS Finder tags & SQLite sync
        set_finder_tags(curr, level_tags)
        _sync_directory_tags_to_db(curr, level_tags, db_path)

        # Update description & verification status in SQLite
        if is_leaf:
            desc = leaf_desc or f"Curated {curr.name} directory"
            app = leaf_app
            lvl_name = f"Leaf folder '{curr.name}'"
        else:
            p_lower = str(curr).lower()
            if any(w in p_lower for w in ["legacy", "archive", "windows"]):
                desc = f"Archived {curr.name} assets and legacy application containers"
            else:
                desc = f"{curr.name} category container"
            app = None
            lvl_name = f"Level {i+1} parent '{curr.name}'"

        _set_directory_description_in_db(curr, desc, db_path, is_verified=is_leaf, app_needed=app)
        tag_labels = [t[0] for t in level_tags]
        print(f"    ✓ {p_em} {lvl_name} tagged with: {tag_labels}")

def _handle_custom_relocation_target(
    raw_path_input: str | None,
    sub_dir: Path,
    active_locs: list[dict],
    db_path: str,
    suggested_desc: str,
    detected_app: str | None
) -> bool:
    """
    Handles custom target relocation path input:
    - Prompts for path if not already provided.
    - Strips quotes and expands ~ / paths.
    - Determines if target is container or rename target.
    - Dynamically detects and creates all intermediate destination folders (mkdir parents=True).
    - Sets Finder tags and registers newly created directories in SQLite.
    - Relocates folder via shutil.move, updates SQLite directories records, and tags destination.
    Returns True if successfully relocated, False if cancelled or failed.
    """
    if not raw_path_input or raw_path_input.lower() == 'p':
        raw_path_input = input(f"\nEnter custom target folder path for '{sub_dir.name}': ").strip()

    if not raw_path_input:
        print("Move cancelled.")
        return False

    clean_str = raw_path_input.strip().strip("'\"")
    if clean_str.lower() == 'c':
        print("Move cancelled.")
        return False

    is_explicit_container = clean_str.endswith('/') or clean_str.endswith('\\')
    entered_path = Path(clean_str).expanduser()

    if entered_path.exists() and entered_path.resolve() == sub_dir.resolve():
        print(f"\n[Error] Destination cannot be the same as the source directory '{sub_dir}'.")
        return False

    # Determine resolved destination path and parent to ensure
    if entered_path.exists():
        if entered_path.is_dir():
            clean_sug = suggest_clean_folder_name(sub_dir.name, detected_app)
            if clean_sug != sub_dir.name:
                print(f"\nDestination folder name:")
                print(f"  • Current name:     '{sub_dir.name}'")
                print(f"  • Suggested clean:  '{clean_sug}' (Default)")
                c_name = input(f"Enter folder name in destination [Press Enter for '{clean_sug}', '1' for '{sub_dir.name}', or type new name]: ").strip()
                dest_fn = clean_sug if not c_name else (sub_dir.name if c_name == '1' else c_name)
            else:
                dest_fn = sub_dir.name
            target_dest_path = entered_path / dest_fn
            parent_to_ensure = entered_path
        else:
            print(f"\n[Error] Destination '{entered_path}' exists and is a regular file, not a directory.")
            return False
    else:
        if is_explicit_container:
            clean_sug = suggest_clean_folder_name(sub_dir.name, detected_app)
            if clean_sug != sub_dir.name:
                print(f"\nDestination folder name:")
                print(f"  • Current name:     '{sub_dir.name}'")
                print(f"  • Suggested clean:  '{clean_sug}' (Default)")
                c_name = input(f"Enter folder name in destination [Press Enter for '{clean_sug}', '1' for '{sub_dir.name}', or type new name]: ").strip()
                dest_fn = clean_sug if not c_name else (sub_dir.name if c_name == '1' else c_name)
            else:
                dest_fn = sub_dir.name
            target_dest_path = entered_path / dest_fn
            parent_to_ensure = entered_path
        elif entered_path.name == sub_dir.name:
            target_dest_path = entered_path
            parent_to_ensure = entered_path.parent
        else:
            print(f"\nDestination folder does not currently exist on disk:")
            print(f"  • Specified path: {entered_path}")
            print(f"\nHow should '{sub_dir.name}' be relocated?")
            print(f"  [1] Relocate and rename to '{entered_path.name}' (Recommended)")
            print(f"      → {entered_path}")
            print(f"  [2] Create directory and relocate inside as '{sub_dir.name}'")
            print(f"      → {entered_path / sub_dir.name}")
            print(f"  [c] Cancel move")
            c_sel = input("\nSelect placement [1/2/c] (Default: 1): ").strip().lower()
            if not c_sel:
                c_sel = "1"
            if c_sel == 'c':
                print("Move cancelled.")
                return False
            elif c_sel == '2':
                target_dest_path = entered_path / sub_dir.name
                parent_to_ensure = entered_path
            else:
                target_dest_path = entered_path
                parent_to_ensure = entered_path.parent

    if target_dest_path.exists():
        print(f"\n[Error] Destination '{target_dest_path}' already exists!")
        return False

    # Discover any non-existent directories in parent_to_ensure hierarchy
    dirs_to_create = []
    curr = parent_to_ensure
    while curr and not curr.exists() and curr != curr.parent:
        dirs_to_create.append(curr)
        curr = curr.parent
    dirs_to_create.reverse()

    # Match target Priority Location
    target_loc = None
    for al in active_locs:
        try:
            al_res = al["path"].resolve()
            if al_res in target_dest_path.parents or al_res == target_dest_path.parent:
                target_loc = al
                break
        except Exception:
            if str(target_dest_path).startswith(al["path_str"]):
                target_loc = al
                break

    if not target_loc:
        t_lower = str(target_dest_path).lower()
        for p_tier in ["priority 1", "priority 2", "priority 3", "priority 4"]:
            if p_tier in t_lower:
                target_loc = next((al for al in active_locs if al["priority_tier"].lower() == p_tier), None)
                if not target_loc:
                    target_loc = {
                        "priority_tier": p_tier,
                        "label": f"{p_tier.title()} Storage",
                        "path": parent_to_ensure,
                        "path_str": str(parent_to_ensure),
                    }
                break

    if not target_loc:
        target_loc = next((al for al in active_locs if al["priority_tier"].lower() == "priority 2"), None)
        if not target_loc:
            target_loc = {
                "priority_tier": "priority 2",
                "label": "Custom Storage Target",
                "path": parent_to_ensure,
                "path_str": str(parent_to_ensure),
            }

    p_tier_name = target_loc["priority_tier"].lower()
    p_info = PRIORITY_TIER_CONFIG.get(p_tier_name, {"tag": "Priority 2", "color": 4})
    p_em = FINDER_COLOR_EMOJI.get(p_info.get("color", 4), "⚪")

    try:
        rel_parts = list(target_dest_path.relative_to(target_loc["path"]).parts[:-1])
    except Exception:
        rel_parts = list(target_dest_path.parent.parts[-2:])

    target_cat_name = " ▸ ".join(rel_parts) if rel_parts else target_dest_path.parent.name

    print("\n" + "=" * 80)
    print("  CUSTOM RELOCATION PLAN")
    print("=" * 80)
    print(f"  • Source Folder:    {sub_dir}")
    print(f"  • Destination Path: {target_dest_path}")
    print(f"  • Priority Tier:    {p_em} {target_loc['priority_tier'].title()} ({target_loc['label']})")
    print(f"  • Category Branch:  {target_cat_name}")
    if dirs_to_create:
        print(f"  • Destination Directories to Create ({len(dirs_to_create)}):")
        for d in dirs_to_create:
            print(f"    + {d}")
    else:
        print("  • Destination parent directory already exists on disk.")
    print("=" * 80)

    confirm = input(f"Confirm creating destination hierarchy and moving '{sub_dir.name}'? [Y/n]: ").strip().lower()
    if confirm not in ('', 'y', 'yes'):
        print("Move cancelled.")
        return False

    try:
        # Create non-existent directory hierarchy
        for d in dirs_to_create:
            d.mkdir(parents=True, exist_ok=True)
            print(f"  ✓ Created destination directory: {d}")

        # Ensure parent exists
        parent_to_ensure.mkdir(parents=True, exist_ok=True)

        # Move folder
        shutil.move(str(sub_dir), str(target_dest_path))

        # Update SQLite directories table
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
            c_cur.execute("UPDATE directories SET name = ? WHERE path = ?", (target_dest_path.name, new_p))
            c_conn.commit()
            c_conn.close()

        # Apply hierarchical tags and metadata for each level from root to target
        apply_hierarchical_tags_for_path(target_dest_path, target_loc, db_path, suggested_desc, detected_app)

        print(f"\n[Success] ✓ Moved and verified '{sub_dir.name}' → '{target_dest_path}' under {target_loc['label']} / {target_cat_name}.")
        return True
    except Exception as e:
        print(f"\n[Error] Relocation failed: {e}")
        return False


def detect_verified_folder_overlap(sub_dir: Path, db_path: str) -> dict | None:
    """
    Compares candidate folder files against already verified database folders (is_verified = 1).
    Detects identical duplicate files and diff/unique files.
    Excludes candidate itself and any ancestor or descendant paths.
    Returns overlap summary dict if significant overlap is detected (>= 3 identical files and >= 20%, or >= 5 identical), else None.
    """
    if not sub_dir.exists() or not sub_dir.is_dir():
        return None

    # Collect candidate files (ignoring hidden files / macOS metadata)
    cand_files = []
    try:
        for f in sub_dir.rglob('*'):
            if f.is_file() and not f.name.startswith('.'):
                try:
                    cand_files.append({
                        'file': f,
                        'rel_path': f.relative_to(sub_dir),
                        'name': f.name,
                        'size': f.stat().st_size,
                        'mtime': f.stat().st_mtime
                    })
                except (OSError, PermissionError):
                    continue
    except Exception:
        return None

    if not cand_files:
        return None

    cand_total = len(cand_files)
    sub_dir_resolved = sub_dir.resolve()

    if not os.path.exists(db_path):
        return None

    try:
        conn = get_db_connection(db_path)
        cur = conn.cursor()
        ver_rows = cur.execute("""
            SELECT id, name, path, description, app_needed
            FROM directories
            WHERE is_verified = 1
        """).fetchall()
        conn.close()
    except Exception:
        return None

    valid_candidates = []
    for v_id, v_name, v_path_str, v_desc, v_app in ver_rows:
        try:
            v_path = Path(v_path_str).resolve()
        except Exception:
            continue

        if not v_path.exists() or not v_path.is_dir():
            continue

        # Exclude candidate itself and any ancestor or descendant
        if v_path == sub_dir_resolved or v_path in sub_dir_resolved.parents or sub_dir_resolved in v_path.parents:
            continue

        # Collect target files
        target_files = []
        try:
            for tf in v_path.rglob('*'):
                if tf.is_file() and not tf.name.startswith('.'):
                    try:
                        target_files.append({
                            'file': tf,
                            'rel_path': tf.relative_to(v_path),
                            'name': tf.name,
                            'size': tf.stat().st_size,
                            'mtime': tf.stat().st_mtime
                        })
                    except (OSError, PermissionError):
                        continue
        except Exception:
            continue

        if not target_files:
            continue

        target_by_rel = {tf['rel_path']: tf for tf in target_files}
        target_by_name = {}
        for tf in target_files:
            target_by_name.setdefault(tf['name'], []).append(tf)

        identical_list = []
        diff_list = []
        for c in cand_files:
            if c['rel_path'] in target_by_rel and target_by_rel[c['rel_path']]['size'] == c['size']:
                identical_list.append((c, target_by_rel[c['rel_path']]))
            elif c['name'] in target_by_name and any(m['size'] == c['size'] for m in target_by_name[c['name']]):
                identical_list.append((c, next(m for m in target_by_name[c['name']] if m['size'] == c['size'])))
            elif c['rel_path'] in target_by_rel:
                diff_list.append({
                    'cand_file': c['file'],
                    'rel_path': c['rel_path'],
                    'name': c['name'],
                    'size': c['size'],
                    'mtime': c['mtime'],
                    'reason': 'modified_same_path',
                    'conflict': True,
                    'target_match': target_by_rel[c['rel_path']]
                })
            elif c['name'] in target_by_name:
                diff_list.append({
                    'cand_file': c['file'],
                    'rel_path': c['rel_path'],
                    'name': c['name'],
                    'size': c['size'],
                    'mtime': c['mtime'],
                    'reason': 'modified_diff_path',
                    'conflict': False,
                    'target_match': target_by_name[c['name']][0]
                })
            else:
                diff_list.append({
                    'cand_file': c['file'],
                    'rel_path': c['rel_path'],
                    'name': c['name'],
                    'size': c['size'],
                    'mtime': c['mtime'],
                    'reason': 'new',
                    'conflict': False,
                    'target_match': None
                })

        identical_count = len(identical_list)
        pct = (identical_count / cand_total) * 100.0 if cand_total > 0 else 0.0

        if (identical_count >= 3 and pct >= 20.0) or identical_count >= 5:
            valid_candidates.append({
                'target_id': v_id,
                'target_name': v_name,
                'target_path': v_path,
                'target_desc': v_desc,
                'target_app': v_app,
                'depth': len(v_path.parts),
                'total_cand': cand_total,
                'cand_bytes': sum(c['size'] for c in cand_files),
                'identical_count': identical_count,
                'identical_bytes': sum(item[0]['size'] for item in identical_list),
                'diff_count': len(diff_list),
                'diff_bytes': sum(d['size'] for d in diff_list),
                'pct': pct,
                'identical_files': identical_list,
                'diff_files': diff_list
            })

    if not valid_candidates:
        return None

    # Filter out any candidate that is an ancestor of another candidate match
    filtered_candidates = []
    for c in valid_candidates:
        is_ancestor_of_another = any(
            other['target_path'] != c['target_path'] and c['target_path'] in other['target_path'].parents
            for other in valid_candidates
        )
        if not is_ancestor_of_another:
            filtered_candidates.append(c)

    if not filtered_candidates:
        filtered_candidates = valid_candidates

    # Sort remaining by identical_count desc, then path depth desc
    filtered_candidates.sort(key=lambda m: (m['identical_count'], m['depth']), reverse=True)
    return filtered_candidates[0]


def execute_folder_merge_and_cleanup(sub_dir: Path, overlap: dict, db_path: str) -> bool:
    """
    Merges diff/unique files from candidate sub_dir into verified overlap['target_path'].
    Applies destination and provenance Finder tags to merged files.
    Logs every resource into curation_events and file_tags for auditability and query differentiation.
    Handles file conflicts by preserving older revisions.
    Once diff files are copied safely, removes candidate sub_dir from disk and SQLite.
    Triggers directory scan on destination to update database index.
    """
    dest_dir = overlap['target_path']
    diff_files = overlap.get('diff_files', [])
    batch_id = f"curation_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}"
    now_iso = datetime.datetime.now().isoformat()

    print("\n" + "=" * 80)
    print("  EXECUTING MERGE & CLEANUP")
    print("=" * 80)
    print(f"  • Source:      {sub_dir}")
    print(f"  • Destination: {dest_dir}")
    print(f"  • Batch ID:    {batch_id}")
    print(f"  • Diff Files to Merge: {len(diff_files)} files ({format_size(overlap['diff_bytes'])})")
    print(f"  • Redundant Duplicates: {overlap['identical_count']} files ({format_size(overlap['identical_bytes'])})")
    print("=" * 80)

    try:
        # Step 1: Determine tags to apply to merged files
        dest_raw_tags = get_finder_tags(dest_dir)
        file_tag_entries = [(t, 0) if isinstance(t, str) else t for t in dest_raw_tags]
        file_tag_entries.append((f"origin:{sub_dir.name}", 0))
        tags_summary_str = ", ".join(dest_raw_tags) + (f", origin:{sub_dir.name}" if dest_raw_tags else f"origin:{sub_dir.name}")

        # Step 2: Copy diff files into target & apply Finder tags
        merged_records = []
        for df in diff_files:
            cand_file = df['cand_file']
            rel_path = df['rel_path']
            dest_file = dest_dir / rel_path
            dest_file.parent.mkdir(parents=True, exist_ok=True)

            is_conflict = False
            if dest_file.exists() and dest_file.stat().st_size != df['size']:
                is_conflict = True
                target_mtime = dest_file.stat().st_mtime
                cand_mtime = df['mtime']
                if cand_mtime > target_mtime:
                    old_date_str = datetime.datetime.fromtimestamp(target_mtime).strftime('%Y%m%d_%H%M%S')
                    bak_path = dest_file.parent / f"{dest_file.stem}_backup_{old_date_str}{dest_file.suffix}"
                    dest_file.rename(bak_path)
                    print(f"    ↳ [Conflict] Existing target file was older; backed up to '{bak_path.name}'")
                else:
                    cand_date_str = datetime.datetime.fromtimestamp(cand_mtime).strftime('%Y%m%d_%H%M%S')
                    dest_file = dest_file.parent / f"{dest_file.stem}_cand_{cand_date_str}{dest_file.suffix}"
                    print(f"    ↳ [Conflict] Existing target file was newer; saved candidate as '{dest_file.name}'")

            shutil.copy2(str(cand_file), str(dest_file))
            set_finder_tags(dest_file, file_tag_entries)
            merged_records.append({
                'cand_file': cand_file,
                'dest_file': dest_file,
                'rel_path': rel_path,
                'size': df['size'],
                'reason': df['reason'],
                'conflict': is_conflict
            })
            print(f"    ✓ Merged & Tagged: '{rel_path}' ({format_size(df['size'])})")

        if merged_records:
            print(f"\n[Success] ✓ Successfully merged and tagged {len(merged_records)} diff files into '{dest_dir.name}'.")

        # Step 3: Delete duplicate candidate folder from disk
        print(f"  ↳ Removing redundant duplicate source folder '{sub_dir.name}' from disk...")
        shutil.rmtree(str(sub_dir))
        print(f"  ✓ Deleted '{sub_dir}' from disk.")

        # Step 4: Purge deleted directory and files from SQLite
        if os.path.exists(db_path):
            c_conn = get_db_connection(db_path)
            c_cur = c_conn.cursor()
            old_p = str(sub_dir.resolve())
            c_cur.execute("""
                DELETE FROM files
                WHERE directory_id IN (
                    SELECT id FROM directories WHERE path = ? OR path LIKE ? || '/%'
                )
            """, (old_p, old_p))
            c_cur.execute("DELETE FROM directories WHERE path = ? OR path LIKE ? || '/%'", (old_p, old_p))
            c_conn.commit()
            c_conn.close()
            print("  ✓ Cleared deleted folder records from SQLite.")

            # Step 5: Re-scan destination directory so merged files are indexed in DB
            print(f"  ↳ Refreshing and indexing destination folder '{dest_dir.name}' in SQLite...")
            perform_directory_scan(dest_dir, db_path, skip_hours=0.0)
            print(f"[Success] ✓ Destination folder '{dest_dir.name}' re-scanned and synchronized.")

            # Step 6: Log all resources into curation_events and file_tags
            c_conn = get_db_connection(db_path)
            c_cur = c_conn.cursor()
            ensure_curation_events_table(c_cur)

            for mr in merged_records:
                dest_f = mr['dest_file']
                parent_p = str(dest_f.parent.resolve())
                row = c_cur.execute("""
                    SELECT f.id, f.directory_id
                    FROM files f
                    JOIN directories d ON f.directory_id = d.id
                    WHERE d.path = ? AND f.name = ?
                """, (parent_p, dest_f.name)).fetchone()

                f_id = row[0] if row else None
                d_id = row[1] if row else None

                detail_json = json.dumps({
                    'relative_path': str(mr['rel_path']),
                    'action': 'merge_copy',
                    'reason': mr['reason'],
                    'conflict': mr['conflict'],
                    'source_folder': sub_dir.name
                })

                c_cur.execute("""
                    INSERT INTO curation_events (
                        batch_id, event_type, created_at, source_path, destination_path,
                        origin_folder, resource_type, resource_path, file_id, directory_id,
                        file_size_bytes, finder_tags, details
                    ) VALUES (?, 'merge_file', ?, ?, ?, ?, 'file', ?, ?, ?, ?, ?, ?)
                """, (
                    batch_id, now_iso, str(mr['cand_file']), str(dest_f),
                    sub_dir.name, str(dest_f.resolve()), f_id, d_id,
                    mr['size'], tags_summary_str, detail_json
                ))

                if f_id:
                    c_cur.execute("""
                        INSERT OR IGNORE INTO file_tags (file_id, tag_name, created_at)
                        VALUES (?, ?, ?)
                    """, (f_id, f"merged_from:{sub_dir.name}", now_iso))
                    c_cur.execute("""
                        INSERT OR IGNORE INTO file_tags (file_id, tag_name, created_at)
                        VALUES (?, ?, ?)
                    """, (f_id, f"curation_batch:{batch_id}", now_iso))

            # Directory-level curation event
            summary_detail = json.dumps({
                'diff_files_merged': len(merged_records),
                'duplicate_files_purged': overlap['identical_count'],
                'purged_bytes': overlap['identical_bytes'],
                'origin_folder': sub_dir.name
            })
            c_cur.execute("""
                INSERT INTO curation_events (
                    batch_id, event_type, created_at, source_path, destination_path,
                    origin_folder, resource_type, resource_path, file_id, directory_id,
                    file_size_bytes, finder_tags, details
                ) VALUES (?, 'merge_folder_cleanup', ?, ?, ?, ?, 'directory', ?, NULL, NULL, ?, ?, ?)
            """, (
                batch_id, now_iso, str(sub_dir), str(dest_dir),
                sub_dir.name, str(dest_dir.resolve()), overlap.get('cand_bytes', 0),
                tags_summary_str, summary_detail
            ))

            c_conn.commit()
            c_conn.close()

            print(f"  ✓ Logged {len(merged_records)} resources into 'curation_events' table (Batch ID: {batch_id})")
            print(f"  ✓ Applied Finder tags and SQLite provenance tags ('merged_from:{sub_dir.name}')")


        return True
    except Exception as e:
        print(f"\n[Error] Merge and cleanup failed: {e}")
        return False


def extract_file_types_interactive(sub_dir: Path, db_path: str, stats: dict | None = None, ft_info: dict | None = None) -> bool:
    """
    Extracts and segregates specific file types (e.g. .doc, .pdf, scripts, code, etc.)
    from a multi-source folder into a dedicated subfolder while strictly preserving
    the nested directory hierarchy. Synchronizes SQLite records and provenance events.
    """
    sub_dir = Path(sub_dir).resolve()
    if not sub_dir.exists() or not sub_dir.is_dir():
        print(f"\n[Error] Directory '{sub_dir}' does not exist.")
        return False

    print(f"\nAnalyzing file structure in '{sub_dir.name}'...")
    files_by_ext = defaultdict(list)
    total_scan_files = 0
    total_scan_bytes = 0

    for root, dirs, filenames in os.walk(sub_dir):
        # Ignore hidden directories
        dirs[:] = [d for d in dirs if not d.startswith('.')]
        for fn in filenames:
            if fn.startswith('.'):
                continue
            fp = Path(root) / fn
            try:
                sz = fp.stat().st_size
                ext = fp.suffix.lower() if fp.suffix else '(no ext)'
                rel = fp.relative_to(sub_dir)
                files_by_ext[ext].append((fp, sz, rel))
                total_scan_files += 1
                total_scan_bytes += sz
            except Exception:
                pass

    if not files_by_ext:
        print(f"\n[Notice] No files found in '{sub_dir.name}' to extract.")
        return False

    # Look up extension metadata from SQLite catalog
    ext_descriptions = {}
    if os.path.exists(db_path):
        try:
            conn = get_db_connection(db_path)
            cur = conn.cursor()
            exts_to_query = [e for e in files_by_ext.keys() if e != '(no ext)']
            if exts_to_query:
                placeholders = ",".join("?" for _ in exts_to_query)
                cur.execute(f"SELECT extension, description, category FROM file_extensions WHERE extension IN ({placeholders})", exts_to_query)
                for row in cur.fetchall():
                    ext_descriptions[row[0].lower()] = (row[1], row[2])
            conn.close()
        except Exception:
            pass

    sorted_exts = sorted(files_by_ext.keys(), key=lambda e: (len(files_by_ext[e]), sum(x[1] for x in files_by_ext[e])), reverse=True)

    print("\n" + "=" * 80)
    print(f"  📂 EXTRACT & SEGREGATE FILE TYPES FROM: '{sub_dir.name}'")
    print("=" * 80)
    print(f"  • Folder Path:    {sub_dir}")
    print(f"  • Total Content:  {total_scan_files:,} files ({format_size(total_scan_bytes)}) across {len(files_by_ext)} distinct file types")
    print("-" * 80)
    print("  Ranked File Types:")

    for idx, ext in enumerate(sorted_exts, 1):
        flist = files_by_ext[ext]
        f_cnt = len(flist)
        f_bytes = sum(x[1] for x in flist)
        desc, cat = ext_descriptions.get(ext, (f"{ext.upper().lstrip('.')} File" if ext != '(no ext)' else "Extensionless / Mystery File", "Other"))
        print(f"    {idx:>2}. {ext:<12} ({desc}) — {f_cnt:,} files ({format_size(f_bytes)})")

    print("-" * 80)
    print("  Selection Options:")
    print("    • Number(s):       e.g., '1' (Top type) or '1, 2'")
    print("    • Extension(s):    e.g., '.doc', 'doc, docx', '.pdf'")
    print("    • Category:        'docs' (Documents: .doc, .docx, .pdf, .rtf, .txt, .odt, .pages)")
    print("                       'code' (Source Code: .rb, .py, .js, .c, .h, .sh, etc.)")
    print("                       'data' (Database & Data: .sql, .csv, .json, .xml, etc.)")
    print("                       'media' (Images & Audio/Video)")
    print("    • 'c' to Cancel")

    top_choice = "1"
    top_ext = sorted_exts[0]
    choice = input(f"\nSelect file type to extract [Default: {top_choice} - {top_ext}]: ").strip().lower()
    if not choice:
        choice = top_choice
    if choice == 'c':
        print("\n[Cancelled] Extraction aborted.")
        return False

    CATEGORY_EXT_MAP = {
        'docs': {'.doc', '.docx', '.rtf', '.odt', '.pdf', '.txt', '.pages', '.wpd', '.wps'},
        'doc': {'.doc', '.docx', '.rtf', '.odt', '.pdf', '.txt', '.pages', '.wpd', '.wps'},
        'documents': {'.doc', '.docx', '.rtf', '.odt', '.pdf', '.txt', '.pages', '.wpd', '.wps'},
        'code': {'.rb', '.py', '.js', '.ts', '.c', '.cpp', '.h', '.hpp', '.java', '.go', '.rs', '.php', '.sh', '.pl', '.html', '.css', '.bat'},
        'scripts': {'.rb', '.py', '.sh', '.pl', '.bat', '.ps1'},
        'data': {'.sql', '.csv', '.tsv', '.json', '.xml', '.yaml', '.yml', '.db', '.sqlite', '.sqlite3', '.mdb', '.accdb'},
        'db': {'.sql', '.csv', '.tsv', '.json', '.xml', '.yaml', '.yml', '.db', '.sqlite', '.sqlite3', '.mdb', '.accdb'},
        'media': {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff', '.tif', '.mp4', '.mov', '.avi', '.mkv', '.mp3', '.wav', '.flac'}
    }

    target_exts = set()
    if choice in CATEGORY_EXT_MAP:
        cat_set = CATEGORY_EXT_MAP[choice]
        target_exts = {e for e in files_by_ext.keys() if e in cat_set}
        if not target_exts:
            print(f"\n[Notice] No files found matching category '{choice}'.")
            return False
    else:
        parts = [p.strip() for p in choice.replace(';', ',').split(',') if p.strip()]
        all_numeric = True
        for p in parts:
            if not p.isdigit():
                all_numeric = False
                break
        if all_numeric:
            for p in parts:
                idx = int(p)
                if 1 <= idx <= len(sorted_exts):
                    target_exts.add(sorted_exts[idx - 1])
                else:
                    print(f"\n[Error] Invalid index '{idx}'. Range is 1 to {len(sorted_exts)}.")
                    return False
        else:
            for p in parts:
                norm = p if p.startswith('.') else f".{p}"
                found = False
                for e in files_by_ext.keys():
                    if e.lower() == norm.lower():
                        target_exts.add(e)
                        found = True
                if not found:
                    print(f"[Warning] Extension '{norm}' not present in this folder.")

    if not target_exts:
        print("\n[Error] No valid file types selected.")
        return False

    if any(e in ('.doc', '.docx', '.rtf', '.odt', '.pages', '.pdf', '.wpd') for e in target_exts):
        default_subfolder = "Documents"
    elif any(e in ('.sql', '.db', '.sqlite', '.sqlite3', '.mdb') for e in target_exts):
        default_subfolder = "Database"
    elif any(e in ('.rb', '.py', '.js', '.c', '.cpp', '.java', '.sh') for e in target_exts):
        default_subfolder = "Source_Code"
    elif any(e in ('.jpg', '.jpeg', '.png', '.gif', '.raw', '.heic') for e in target_exts):
        default_subfolder = "Images"
    elif len(target_exts) == 1:
        ext_clean = list(target_exts)[0].lstrip('.')
        default_subfolder = f"{ext_clean.upper()}_Files" if ext_clean else "Extracted_Files"
    else:
        default_subfolder = "Extracted_Files"

    print(f"\nSelected File Type(s): {', '.join(sorted(target_exts))}")
    dest_input = input(f"Enter target subfolder name or path [Default: '{default_subfolder}' inside '{sub_dir.name}']: ").strip().strip('"').strip("'")
    if not dest_input:
        target_dir = (sub_dir / default_subfolder).resolve()
    elif dest_input.startswith('/'):
        target_dir = Path(dest_input).resolve()
    else:
        target_dir = (sub_dir / dest_input).resolve()

    if target_dir == sub_dir:
        print("\n[Error] Target destination cannot be the source folder itself.")
        return False

    to_move = []
    for ext in target_exts:
        for fp, sz, rel in files_by_ext[ext]:
            if target_dir in fp.parents or fp == target_dir:
                continue
            dest_fp = target_dir / rel
            to_move.append((fp, sz, rel, dest_fp))

    if not to_move:
        print(f"\n[Notice] No files to move (matching files may already be in '{target_dir}').")
        return False

    total_move_bytes = sum(x[1] for x in to_move)
    print("\n" + "=" * 80)
    print("  EXTRACTION & SEGREGATION PREVIEW")
    print("=" * 80)
    print(f"  • Source Folder:    {sub_dir}")
    print(f"  • Selected Type(s): {', '.join(sorted(target_exts))}")
    print(f"  • Files to Move:    {len(to_move):,} files ({format_size(total_move_bytes)})")
    print(f"  • Destination:      {target_dir}")
    print(f"  • Structure:        Folder hierarchy PRESERVED relative to '{sub_dir.name}'")
    print(f"    ↳ Example: '{to_move[0][2]}' → '{to_move[0][3].relative_to(target_dir.parent if target_dir.parent != target_dir else target_dir)}'")
    print("=" * 80)

    confirm = input(f"\nProceed with moving {len(to_move):,} files into '{target_dir.name}'? [y/N]: ").strip().lower()
    if confirm not in ('y', 'yes'):
        print("\n[Cancelled] Extraction aborted.")
        return False

    print(f"\nExecuting extraction to '{target_dir}'...")
    target_dir.mkdir(parents=True, exist_ok=True)
    moved_count = 0
    moved_bytes = 0
    errors = []

    batch_id = f"extract_{uuid.uuid4().hex[:8]}"
    now_iso = datetime.datetime.now().isoformat()

    conn = get_db_connection(db_path) if os.path.exists(db_path) else None
    cur = conn.cursor() if conn else None
    if cur:
        ensure_curation_events_table(cur)

    host_id = 1
    if cur:
        try:
            cur.execute("SELECT host_id FROM directories WHERE path = ?", (str(sub_dir),))
            hr = cur.fetchone()
            if hr:
                host_id = hr[0]
        except Exception:
            pass

    dir_id_cache = {}

    for fp, sz, rel, dest_fp in to_move:
        try:
            dest_fp.parent.mkdir(parents=True, exist_ok=True)
            if dest_fp.exists() and dest_fp.resolve() != fp.resolve():
                base_stem = dest_fp.stem
                suf = dest_fp.suffix
                c = 1
                while dest_fp.exists():
                    dest_fp = dest_fp.parent / f"{base_stem}_{c}{suf}"
                    c += 1

            shutil.move(str(fp), str(dest_fp))
            moved_count += 1
            moved_bytes += sz

            if cur:
                dest_parent_str = str(dest_fp.parent.resolve())
                if dest_parent_str not in dir_id_cache:
                    cur.execute("SELECT id FROM directories WHERE path = ?", (dest_parent_str,))
                    drow = cur.fetchone()
                    if drow:
                        dir_id_cache[dest_parent_str] = drow[0]
                    else:
                        cur.execute("""
                            INSERT INTO directories (host_id, path, name, scanned_at, is_verified)
                            VALUES (?, ?, ?, ?, 0)
                        """, (host_id, dest_parent_str, dest_fp.parent.name, now_iso))
                        dir_id_cache[dest_parent_str] = cur.lastrowid
                new_dir_id = dir_id_cache[dest_parent_str]

                old_parent_str = str(fp.parent.resolve())
                cur.execute("SELECT id FROM directories WHERE path = ?", (old_parent_str,))
                old_drow = cur.fetchone()
                file_id = None
                if old_drow:
                    old_dir_id = old_drow[0]
                    cur.execute("SELECT id FROM files WHERE directory_id = ? AND name = ?", (old_dir_id, fp.name))
                    frow = cur.fetchone()
                    if frow:
                        file_id = frow[0]
                        cur.execute("UPDATE files SET directory_id = ?, name = ? WHERE id = ?", (new_dir_id, dest_fp.name, file_id))

                cur.execute("""
                    INSERT INTO curation_events (
                        batch_id, event_type, created_at, source_path, destination_path,
                        origin_folder, resource_type, resource_path, file_id, directory_id,
                        file_size_bytes, details
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    batch_id, "extract_segregate", now_iso,
                    str(fp), str(dest_fp),
                    sub_dir.name, "file", str(dest_fp),
                    file_id, new_dir_id, sz,
                    json.dumps({"ext": dest_fp.suffix.lower(), "preserved_relative_path": str(rel)})
                ))
        except Exception as e:
            errors.append(f"{fp.name} -> {e}")

    # Prune empty directories in source sub_dir
    pruned_dirs = 0
    for root, dirs, files in os.walk(sub_dir, topdown=False):
        rp = Path(root)
        if rp != sub_dir and target_dir not in rp.parents and rp != target_dir:
            try:
                if not any(rp.iterdir()):
                    rp.rmdir()
                    pruned_dirs += 1
                    if cur:
                        cur.execute("DELETE FROM directories WHERE path = ?", (str(rp.resolve()),))
            except Exception:
                pass

    if cur:
        # Directory-level event
        cur.execute("""
            INSERT INTO curation_events (
                batch_id, event_type, created_at, source_path, destination_path,
                origin_folder, resource_type, resource_path, directory_id,
                file_size_bytes, details
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            batch_id, "extract_folder_created", now_iso,
            str(sub_dir), str(target_dir),
            sub_dir.name, "directory", str(target_dir),
            dir_id_cache.get(str(target_dir.resolve())),
            moved_bytes,
            json.dumps({"extracted_exts": sorted(list(target_exts)), "files_moved": moved_count, "empty_dirs_pruned": pruned_dirs})
        ))
        conn.commit()

    print("\n" + "=" * 80)
    print(f"[Success] ✓ Extraction & Segregation Complete!")
    print(f"  • Files moved:                  {moved_count:,} ({format_size(moved_bytes)})")
    print(f"  • Destination folder:           {target_dir}")
    print(f"  • Folder structure:             Preserved")
    if pruned_dirs > 0:
        print(f"  • Empty directories pruned:     {pruned_dirs}")
    if errors:
        print(f"  • Errors encountered:           {len(errors)}")
        for err in errors[:5]:
            print(f"    - {err}")
    print("=" * 80)

    # Optional prompt to verify / tag the newly created subfolder
    tag_new = input(f"\nDo you want to mark the newly extracted '{target_dir.name}' as Verified? [y/N]: ").strip().lower()
    if tag_new in ('y', 'yes'):
        new_stats = analyze_folder_content(target_dir)
        new_ft = identify_folder_filetypes_and_apps(db_path, new_stats["ext_counts"], sub_dir.name, "")
        new_app = new_ft.get("app_needed") or "General Viewer"
        new_desc = f"{target_dir.name} extracted from {sub_dir.name}"
        custom_desc = input(f"Enter description [Default: '{new_desc}']: ").strip()
        if custom_desc:
            new_desc = custom_desc
        if cur:
            now_v = datetime.datetime.now().isoformat()
            cur.execute("""
                UPDATE directories
                SET is_verified = 1, verified_at = ?, description = ?, app_needed = ?
                WHERE path = ?
            """, (now_v, new_desc, new_app, str(target_dir.resolve())))
            conn.commit()
            print(f"[Success] ✓ '{target_dir.name}' marked as Verified with app '{new_app}'.")

    if conn:
        conn.close()

    return True


def fold_snapshot_folders_interactive(target_dir: Path, db_path: str) -> bool:
    """
    Consolidates historical chronological snapshot folders (e.g. 'Documents 01282009',
    'nested Documents', 'Documents Duplicates', etc.) in-place into target_dir.
    - Hoists nested same-name baseline (e.g. Documents/Documents/* -> Documents/*)
    - Automatically collapses byte-for-byte exact duplicate files
    - Preserves different revision files by appending snapshot date/tag
    - Purges legacy Windows shortcuts, Word backups, and thumbnail caches
    - Organizes family photo scans into 'Family Scans & IDs'
    - Reconciles empty folders and synchronizes SQLite database.
    """
    target_dir = Path(target_dir).resolve()
    if not target_dir.exists() or not target_dir.is_dir():
        print(f"\n[Error] Target directory '{target_dir}' does not exist.")
        return False

    snapshot_dirs = []
    for d in sorted(target_dir.iterdir()):
        if not d.is_dir() or d.name.startswith('.'):
            continue
        name_l = d.name.lower()
        if ('document' in name_l or 'snapshot' in name_l or 'backup' in name_l or
            'duplicate' in name_l or d.name == 'Resume Milena' or d.name == target_dir.name):
            snapshot_dirs.append(d)

    loose_root_files = [f for f in sorted(target_dir.iterdir()) if f.is_file() and not f.name.startswith('.')]

    if not snapshot_dirs and not loose_root_files:
        print(f"\n[Notice] No snapshot folders or root files detected under '{target_dir.name}' to fold.")
        return False

    print("\n" + "=" * 80)
    print(f"  📂 FOLD & CONSOLIDATE SNAPSHOTS IN-PLACE: '{target_dir.name}'")
    print("=" * 80)
    print(f"  • Target Directory:       {target_dir}")
    print(f"  • Detected Snapshots:     {len(snapshot_dirs)} folders:")
    for sd in snapshot_dirs:
        sub_cnt = sum(len(f) for _, _, f in os.walk(sd))
        print(f"    - {sd.name:<32} ({sub_cnt:,} files)")
    if loose_root_files:
        print(f"  • Loose Root Files:       {len(loose_root_files)} files in '{target_dir.name}'")
    print("-" * 80)

    start_c = input("\nProceed with dry-run analysis and collision check? [Y/n]: ").strip().lower()
    if start_c == 'n':
        print("\nConsolidation cancelled.")
        return False

    print("\nScanning files, computing SHA-256 hashes & analyzing collisions... Please wait...")

    def get_hash(fp):
        h = hashlib.sha256()
        with open(fp, 'rb') as f:
            while chunk := f.read(65536):
                h.update(chunk)
        return h.hexdigest()

    def parse_snapshot_date(name):
        m = re.search(r'(\d{2})(\d{2})(\d{4})', name)
        if m:
            month, day, year = m.groups()
            return f"{year}-{month}-{day}"
        return None

    def is_junk(fn, p_str):
        fl = fn.lower()
        ext = Path(fn).suffix.lower()
        if fl in ('thumbs.db', '.picasa.ini', 'picasa.ini', '.ds_store', 'desktop.ini') or fl.startswith('desktop (') or fn.startswith('._'):
            return True
        if ext in ('.lnk', '.wbk') or fn.startswith('~$'):
            return True
        if 'cbp formi-94 - avast yahoo image search results_files' in p_str.lower() and ext == '.jpg' and fl.startswith('th'):
            return True
        return False

    canonical_targets = {}
    to_purge_junk = []
    to_purge_dups = []
    collisions_preserved = []
    to_move_unique = []
    special_mny = []
    total_files_scanned = 0
    total_bytes_scanned = 0

    nested_docs = target_dir / target_dir.name

    # Step A: Baseline from nested directory if exists
    if nested_docs.exists() and nested_docs.is_dir():
        for r, dirs, files in os.walk(nested_docs):
            for fn in files:
                if fn.startswith('.'):
                    continue
                fp = Path(r) / fn
                try:
                    sz = fp.stat().st_size
                    total_files_scanned += 1
                    total_bytes_scanned += sz
                    if is_junk(fn, r):
                        to_purge_junk.append((fp, sz))
                        continue
                    if fp.suffix.lower() in ('.mny', '.mbf'):
                        special_mny.append((fp, sz))
                        continue
                    rel = fp.relative_to(nested_docs)
                    fh = get_hash(fp)
                    canonical_targets[rel] = {
                        'src': fp, 'sz': sz, 'hash': fh,
                        'origin': 'nested_baseline', 'mtime': fp.stat().st_mtime
                    }
                except Exception as e:
                    print(f"    [Warning] Could not process {fp}: {e}")

    # Step B: Loose root files
    for lf in loose_root_files:
        try:
            sz = lf.stat().st_size
            total_files_scanned += 1
            total_bytes_scanned += sz
            if is_junk(lf.name, str(lf)):
                to_purge_junk.append((lf, sz))
                continue
            if lf.suffix.lower() in ('.mny', '.mbf'):
                special_mny.append((lf, sz))
                continue
            rel = Path(lf.name)
            fh = get_hash(lf)
            if rel in canonical_targets:
                existing = canonical_targets[rel]
                if existing['hash'] == fh:
                    to_purge_dups.append((lf, sz, rel, existing['origin']))
                else:
                    dt = datetime.date.fromtimestamp(lf.stat().st_mtime).isoformat()
                    rev_rel = rel.parent / f"{rel.stem} (root_{dt}){rel.suffix}"
                    collisions_preserved.append((lf, sz, rel, rev_rel, 'root'))
                    canonical_targets[rev_rel] = {
                        'src': lf, 'sz': sz, 'hash': fh,
                        'origin': 'root', 'mtime': lf.stat().st_mtime
                    }
            else:
                canonical_targets[rel] = {
                    'src': lf, 'sz': sz, 'hash': fh,
                    'origin': 'root', 'mtime': lf.stat().st_mtime
                }
        except Exception as e:
            print(f"    [Warning] Could not process root file {lf}: {e}")

    # Step C: Walk each snapshot folder
    for sd in snapshot_dirs:
        if sd == nested_docs:
            continue
        s_date = parse_snapshot_date(sd.name)
        for r, dirs, files in os.walk(sd):
            for fn in files:
                if fn.startswith('.'):
                    continue
                fp = Path(r) / fn
                try:
                    sz = fp.stat().st_size
                    total_files_scanned += 1
                    total_bytes_scanned += sz
                    if is_junk(fn, r):
                        to_purge_junk.append((fp, sz))
                        continue
                    if fp.suffix.lower() in ('.mny', '.mbf'):
                        special_mny.append((fp, sz))
                        continue

                    if sd.name == 'FAMILIES DOCUMENTS':
                        rel = Path('Family Scans & IDs') / fp.relative_to(sd)
                    elif sd.name == 'Resume Milena':
                        rel = Path(fn)
                    else:
                        rel = fp.relative_to(sd)
                        if rel.parts and rel.parts[0].lower() in ('docs', 'documents'):
                            rel = Path(*rel.parts[1:]) if len(rel.parts) > 1 else Path(fn)

                    fh = get_hash(fp)

                    if rel in canonical_targets:
                        existing = canonical_targets[rel]
                        if existing['hash'] == fh:
                            to_purge_dups.append((fp, sz, rel, existing['origin']))
                        else:
                            tag = s_date if s_date else sd.name.replace(' ', '_')
                            rev_rel = rel.parent / f"{rel.stem} ({tag}){rel.suffix}"
                            if rev_rel in canonical_targets:
                                if canonical_targets[rev_rel]['hash'] == fh:
                                    to_purge_dups.append((fp, sz, rev_rel, canonical_targets[rev_rel]['origin']))
                                    continue
                                else:
                                    rev_rel = rel.parent / f"{rel.stem} ({tag}_{len(canonical_targets)}){rel.suffix}"
                            collisions_preserved.append((fp, sz, rel, rev_rel, sd.name))
                            canonical_targets[rev_rel] = {
                                'src': fp, 'sz': sz, 'hash': fh,
                                'origin': sd.name, 'mtime': fp.stat().st_mtime
                            }
                    else:
                        canonical_targets[rel] = {
                            'src': fp, 'sz': sz, 'hash': fh,
                            'origin': sd.name, 'mtime': fp.stat().st_mtime
                        }
                        to_move_unique.append((fp, sz, rel, sd.name))
                except Exception as e:
                    print(f"    [Warning] Could not process {fp}: {e}")

    kept_bytes = sum(x['sz'] for x in canonical_targets.values())
    dup_bytes = sum(x[1] for x in to_purge_dups)
    junk_bytes = sum(x[1] for x in to_purge_junk)

    ms_money_dest = Path('/Volumes/LaCie/Storage/Priority 2/Data/Legacy/Windows/MS-Money')
    has_ms_money_repo = ms_money_dest.exists() and ms_money_dest.is_dir()

    print("\n" + "=" * 80)
    print("  CONSOLIDATION & DEDUPLICATION DRY-RUN SUMMARY")
    print("=" * 80)
    print(f"  • Source Repository:            {target_dir}")
    print(f"  • Total Files Processed:        {total_files_scanned:,} ({format_size(total_bytes_scanned)})")
    print("-" * 80)
    print(f"  Plan Actions:")
    print(f"  • Canonical Files to Keep:      {len(canonical_targets):,} files ({format_size(kept_bytes)})")
    print(f"  • Exact Duplicates to Reclaim:  {len(to_purge_dups):,} files ({format_size(dup_bytes)})")
    print(f"  • Collisions Preserved (diff):  {len(collisions_preserved):,} files (dated revision suffix applied)")
    print(f"  • Junk & Cache Files to Purge:  {len(to_purge_junk):,} files ({format_size(junk_bytes)}) (.lnk, .wbk, Thumbs.db)")
    if special_mny:
        dest_mny_label = f" -> '{ms_money_dest}'" if has_ms_money_repo else " (keep in target)"
        print(f"  • MS Money Database Files:      {len(special_mny)} file(s){dest_mny_label}")
    print(f"  • Empty Snapshots to Prune:     {len(snapshot_dirs)} folders")
    print("=" * 80)

    while True:
        prompt_opts = "Select action: [y] Execute consolidation, [v] View collision details, [n] Cancel: "
        user_c = input(prompt_opts).strip().lower()
        if user_c == 'n':
            print("\nConsolidation cancelled.")
            return False
        elif user_c == 'v':
            print("\n" + "-" * 80)
            print(f"COLLISION & REVISION DETAILS ({len(collisions_preserved)} files):")
            print("-" * 80)
            for c_src, c_sz, c_orig, c_new, c_origin_lbl in collisions_preserved:
                print(f"  • [{c_origin_lbl}] '{c_orig}' ({format_size(c_sz)})")
                print(f"     ↳ Saved as: '{c_new}'")
            if to_purge_dups:
                print("\n" + "-" * 80)
                print(f"EXACT DUPLICATES TO RECLAIM ({len(to_purge_dups)} files):")
                print("-" * 80)
                for d_src, d_sz, d_rel, d_orig in to_purge_dups[:20]:
                    print(f"  • '{d_src.name}' ({format_size(d_sz)}) in [{d_src.parent.name}] == identical copy in [{d_orig}]")
                if len(to_purge_dups) > 20:
                    print(f"    ↳ (+ {len(to_purge_dups) - 20} more duplicates)")
            print("-" * 80 + "\n")
        elif user_c in ('y', 'yes'):
            break

    print("\nExecuting consolidation and folding...")
    batch_id = f"fold_{uuid.uuid4().hex[:8]}"
    now_iso = datetime.datetime.now().isoformat()

    conn = get_db_connection(db_path) if os.path.exists(db_path) else None
    cur = conn.cursor() if conn else None
    if cur:
        ensure_curation_events_table(cur)

    # 1. Purge junk
    purged_junk_cnt = 0
    for j_fp, j_sz in to_purge_junk:
        try:
            j_fp.unlink()
            purged_junk_cnt += 1
        except Exception:
            pass

    # 2. Move special MS Money files
    if special_mny and has_ms_money_repo:
        for m_fp, m_sz in special_mny:
            try:
                dest_mny = ms_money_dest / m_fp.name
                if dest_mny.exists():
                    dest_mny = ms_money_dest / f"{m_fp.stem} (from_Documents_{uuid.uuid4().hex[:4]}){m_fp.suffix}"
                shutil.move(str(m_fp), str(dest_mny))
                print(f"  ✓ Moved '{m_fp.name}' -> MS-Money repository ({dest_mny.name})")
            except Exception as e:
                print(f"  [Error] Moving {m_fp.name}: {e}")

    # 3. Purge exact duplicates
    purged_dup_cnt = 0
    for d_fp, d_sz, _, _ in to_purge_dups:
        try:
            d_fp.unlink()
            purged_dup_cnt += 1
        except Exception:
            pass

    # 4. Move canonical files to their destination in target_dir
    moved_cnt = 0
    errors = []
    # Sort items so that loose root files being renamed with tag are moved first, clearing slot
    sorted_targets = sorted(canonical_targets.items(), key=lambda item: (item[1]['origin'] != 'root', str(item[0])))
    for dest_rel, info in sorted_targets:
        src_fp = info['src']
        dest_fp = target_dir / dest_rel
        try:
            if src_fp.resolve() != dest_fp.resolve():
                dest_fp.parent.mkdir(parents=True, exist_ok=True)
                if dest_fp.exists():
                    dest_fp = dest_fp.parent / f"{dest_fp.stem}_{uuid.uuid4().hex[:4]}{dest_fp.suffix}"
                shutil.move(str(src_fp), str(dest_fp))
                moved_cnt += 1
        except Exception as e:
            errors.append(f"{src_fp} -> {dest_fp}: {e}")

    # 5. Prune empty folders bottom-up
    pruned_folders = 0
    for sd in snapshot_dirs:
        if sd.exists():
            for r, dirs, files in os.walk(sd, topdown=False):
                rp = Path(r)
                try:
                    if not any(rp.iterdir()):
                        rp.rmdir()
                        pruned_folders += 1
                except Exception:
                    pass
            try:
                if sd.exists() and not any(sd.iterdir()):
                    sd.rmdir()
                    pruned_folders += 1
            except Exception:
                pass

    if cur:
        cur.execute("""
            INSERT INTO curation_events (
                batch_id, event_type, created_at, source_path, destination_path,
                origin_folder, resource_type, resource_path, file_size_bytes, details
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            batch_id, "snapshot_fold_consolidate", now_iso,
            str(target_dir), str(target_dir),
            target_dir.name, "directory", str(target_dir),
            kept_bytes,
            json.dumps({
                "canonical_kept": len(canonical_targets),
                "duplicates_purged": purged_dup_cnt,
                "junk_purged": purged_junk_cnt,
                "collisions_preserved": len(collisions_preserved),
                "empty_folders_pruned": pruned_folders
            })
        ))
        conn.commit()
        conn.close()

    print("\n" + "=" * 80)
    print(f"[Success] ✓ In-Place Folding & Consolidation Complete!")
    print(f"  • Files in consolidated tree:   {len(canonical_targets):,} ({format_size(kept_bytes)})")
    print(f"  • Reclaimed exact duplicates:   {purged_dup_cnt:,} ({format_size(dup_bytes)})")
    print(f"  • Revisions preserved:          {len(collisions_preserved):,} files")
    print(f"  • Junk & cache files purged:    {purged_junk_cnt:,} files")
    print(f"  • Empty snapshot folders pruned:{pruned_folders:,}")
    if errors:
        print(f"  • Errors:                       {len(errors)}")
        for err in errors[:5]:
            print(f"    - {err}")
    print("=" * 80)

    if os.path.exists(db_path):
        print(f"\nReconciling database index for '{target_dir.name}'...")
        perform_directory_scan(target_dir, db_path, skip_hours=0.0)

    return True


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

    all_locations = get_priority_locations(db_path, active_only=True)
    if not all_locations:
        print("\n[Notice] No active Priority locations mapped. Use 'loc' to map folder locations.")
        return

    target_l1_folders = []
    target_cand_path = None
    curation_mode = 'unverified_only'

    if target_l1_dir:
        tier_name = target_l1_dir.parent.name
        loc_label = target_l1_dir.parent.name
        target_l1_folders = [(tier_name, loc_label, target_l1_dir.parent, target_l1_dir, None)]
    else:
        print("\nSelect Curation Review Mode:")
        print("  1. UNVERIFIED subfolders only (Default: focus on new / pending candidates)")
        print("  2. VERIFIED sets only (Prompt for path of processed set, or browse from DB)")
        print("  3. ALL folders (Both unverified & verified across scope)")
        print("  4. Return to menu")
        mode_input = input("\nSelect mode (1-4) [Default: 1]: ").strip()

        if mode_input == "4":
            return
        elif mode_input == "2":
            curation_mode = 'verified_only'
            print("\n" + "-" * 80)
            print("  REVIEW VERIFIED SETS")
            print("-" * 80)
            print("Enter the full path of the processed folder/set to review,")
            print("or press Enter to browse verified folders from SQLite (or 'a' for all verified).")
            v_path_input = input("\nEnter path or [Enter to browse / 'a' for all]: ").strip()
            clean_v_path = v_path_input.strip("\"'").strip()

            if clean_v_path.lower() == 'a':
                target_cand_path = None
                curation_mode = 'verified_only'
            elif clean_v_path:
                p_obj = Path(clean_v_path).expanduser()
                if p_obj.exists() and p_obj.is_dir():
                    target_cand_path = p_obj
                else:
                    print(f"\n[Warning] Path '{clean_v_path}' not found on disk. Checking SQLite...")
                    if os.path.exists(db_path):
                        with get_db_connection(db_path) as c_db:
                            c_cur = c_db.cursor()
                            c_cur.execute("SELECT path FROM directories WHERE path = ? OR path LIKE ?", (clean_v_path, f"%{clean_v_path}%"))
                            r = c_cur.fetchone()
                            if r and Path(r[0]).exists():
                                target_cand_path = Path(r[0])
                    if not target_cand_path:
                        print(f"[Error] Folder could not be located. Falling back to all verified sets.")
            else:
                # Browse verified folders from SQLite
                if os.path.exists(db_path):
                    with get_db_connection(db_path) as c_db:
                        c_cur = c_db.cursor()
                        c_cur.execute("""
                            SELECT d.path, d.name, d.description, d.app_needed, COUNT(f.id), COALESCE(SUM(f.size_bytes), 0)
                            FROM directories d
                            LEFT JOIN files f ON f.directory_id = d.id
                            WHERE d.is_verified = 1
                            GROUP BY d.id
                            ORDER BY d.path
                        """)
                        verified_rows = c_cur.fetchall()
                    if verified_rows:
                        print(f"\nVerified folders in SQLite ({len(verified_rows)} found):")
                        for v_idx, v_row in enumerate(verified_rows, 1):
                            vp, vname, vdesc, vapp, vfiles, vbytes = v_row
                            v_desc_str = f" — \"{vdesc}\"" if vdesc else ""
                            size_label = f" ({format_size(vbytes)})" if vbytes and vbytes > 0 else ""
                            files_label = f" [{vfiles} files]" if vfiles and vfiles > 0 else ""
                            print(f"  {v_idx}. {vname}{files_label}{size_label}{v_desc_str}")
                            print(f"     📍 {vp}")
                        sel = input(f"\nSelect verified folder (1-{len(verified_rows)}) or paste path [Default: 1]: ").strip()
                        if sel.isdigit() and 1 <= int(sel) <= len(verified_rows):
                            target_cand_path = Path(verified_rows[int(sel) - 1][0])
                        elif sel:
                            p_obj = Path(sel.strip("\"'")).expanduser()
                            if p_obj.exists():
                                target_cand_path = p_obj
                        else:
                            target_cand_path = Path(verified_rows[0][0])
                    else:
                        print("\n[Notice] No verified folders found in SQLite database yet.")
        elif mode_input == "3":
            curation_mode = 'all'
        else:
            curation_mode = 'unverified_only'

        if target_cand_path and target_cand_path.exists():
            cand_loc = None
            for loc in all_locations:
                try:
                    if target_cand_path.resolve().is_relative_to(loc["path"].resolve()):
                        cand_loc = loc
                        break
                except Exception:
                    pass

            if cand_loc:
                c_tier = cand_loc["priority_tier"].title()
                c_label = cand_loc["label"]
                c_loc_path = cand_loc["path"]
            else:
                c_tier = "Priority 2"
                c_label = target_cand_path.parent.name
                c_loc_path = target_cand_path.parent

            if target_cand_path.parent.resolve() == c_loc_path.resolve():
                target_l1_folders = [(c_tier, c_label, c_loc_path, target_cand_path, None)]
            else:
                target_l1_folders = [(c_tier, c_label, c_loc_path, target_cand_path.parent, target_cand_path)]
            curation_mode = 'all'
        else:
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
                            target_l1_folders.append((loc["priority_tier"].title(), loc["label"], p_dir, sub, None))

    if not target_l1_folders:
        print("\n[Notice] No folders found to curate.")
        return

    total_curated = 0
    total_skipped = 0

    conn = get_db_connection(db_path) if os.path.exists(db_path) else None

    for tier_name, loc_label, loc_path, l1_dir, initial_cand in target_l1_folders:
        tier_clean = tier_name.lower()
        tier_info = PRIORITY_TIER_CONFIG.get(tier_clean, {"tag": tier_name, "color": 0, "color_name": "None"})
        tier_emoji = FINDER_COLOR_EMOJI.get(tier_info["color"], "⚪")

        # Navigation stack allows dynamic drill-down (d) and drill-up (u) across directory depth levels
        curr_parent = l1_dir
        curr_candidates = [s for s in sorted(curr_parent.iterdir()) if s.is_dir() and not s.name.startswith('.')]
        if not curr_candidates:
            continue

        if initial_cand and initial_cand in curr_candidates:
            curr_idx = curr_candidates.index(initial_cand)
        else:
            curr_idx = 0

        nav_stack = []
        level_banner_printed = False

        while curr_parent is not None:
            if curr_idx >= len(curr_candidates):
                if nav_stack:
                    prev_parent = curr_parent
                    curr_parent, curr_candidates, curr_idx = nav_stack.pop()
                    curr_idx += 1
                    level_banner_printed = False
                    try:
                        rel_up = curr_parent.resolve().relative_to(loc_path.resolve())
                        up_crumb = " ▸ ".join(rel_up.parts)
                    except Exception:
                        up_crumb = curr_parent.name
                    print(f"\n↳ ⤴️ Completed inspecting subfolders of '{prev_parent.name}'. Resuming '{up_crumb}' (Folder {curr_idx + 1}/{len(curr_candidates)})")
                    continue
                else:
                    break

            sub_dir = curr_candidates[curr_idx]
            if not sub_dir.exists() or not sub_dir.is_dir():
                curr_idx += 1
                continue

            try:
                rel_p = curr_parent.resolve().relative_to(loc_path.resolve())
                breadcrumb_str = " ▸ ".join(rel_p.parts)
            except Exception:
                breadcrumb_str = curr_parent.name

            if not level_banner_printed:
                print(f"\n" + "#" * 80)
                print(f"  {tier_emoji} [{tier_name}] ▸ 📍 {loc_label} ▸ {breadcrumb_str}  ({len(curr_candidates)} subfolders to inspect)")
                print("#" * 80)
                level_banner_printed = True

            res_p = str(sub_dir.resolve())
            is_verified = 0
            existing_desc = None
            existing_app = None
            unverified_sub_count = 0
            verified_sub_count = 0

            if conn:
                cursor = conn.cursor()
                cursor.execute("SELECT is_verified, description, app_needed FROM directories WHERE path = ?", (res_p,))
                row = cursor.fetchone()
                if row:
                    is_verified = row[0] or 0
                    existing_desc = row[1]
                    existing_app = row[2]

                cursor.execute("SELECT COUNT(id) FROM directories WHERE path LIKE ? || '/%' AND (is_verified = 0 OR is_verified IS NULL)", (res_p,))
                row_uv = cursor.fetchone()
                if row_uv:
                    unverified_sub_count = row_uv[0] or 0

                cursor.execute("SELECT COUNT(id) FROM directories WHERE path LIKE ? || '/%' AND is_verified = 1", (res_p,))
                row_v = cursor.fetchone()
                if row_v:
                    verified_sub_count = row_v[0] or 0

            child_subdirs = [s for s in sorted(sub_dir.iterdir()) if s.is_dir() and not s.name.startswith('.')] if sub_dir.exists() and sub_dir.is_dir() else []

            if curation_mode == 'unverified_only' and is_verified == 1:
                if unverified_sub_count == 0:
                    desc_label = f" — \"{existing_desc}\"" if existing_desc else ""
                    print(f"  [{curr_idx + 1}/{len(curr_candidates)}] ✓ Verified: {sub_dir.name}{desc_label} (Skipping)")
                    curr_idx += 1
                    continue
            elif curation_mode == 'verified_only' and is_verified == 0:
                if verified_sub_count == 0:
                    print(f"  [{curr_idx + 1}/{len(curr_candidates)}] ⚪ Unverified: {sub_dir.name} (Skipping)")
                    curr_idx += 1
                    continue

            # Analyze content & identify file types / required applications
            stats = analyze_folder_content(sub_dir)
            ft_info = identify_folder_filetypes_and_apps(db_path, stats["ext_counts"], curr_parent.name, tier_name)
            detected_app = existing_app if existing_app else ft_info.get("app_needed")
            suggested_desc = existing_desc if existing_desc else suggest_folder_description(sub_dir.name, curr_parent.name, tier_name, stats, ft_info)

            # Format stats
            size_str = format_size(stats["total_bytes"])
            files_count = stats["total_files"]
            date_range = f"{stats['earliest_date']} → {stats['latest_date']}" if stats["earliest_date"] else "Unknown dates"
            top_exts = ft_info["file_types_formatted"]
            samples = ", ".join(stats["sample_files"][:3]) if stats["sample_files"] else "None"

            if is_verified == 1:
                if unverified_sub_count > 0:
                    verified_badge = f"✓ Verified Container (⚠️ {unverified_sub_count} unverified subfolder{'s' if unverified_sub_count != 1 else ''} inside)"
                else:
                    verified_badge = "✓ Verified"
            else:
                verified_badge = "⚪ Unverified (Untagged)"

            while True:
                # Detect overlap with already verified database folders
                overlap = detect_verified_folder_overlap(sub_dir, db_path)

                # Analyze mystery / extensionless files if present
                mystery_files = stats.get("no_ext_files", [])
                mystery_summary = ""
                mystery_analyses = []
                if mystery_files:
                    mystery_analyses = [inspect_file_magic(mf, sub_dir) for mf in mystery_files]
                    identified_counts = Counter(m["short_type"] for m in mystery_analyses)
                    identified_parts = [f"{cnt}x {stype}" for stype, cnt in identified_counts.most_common(3)]
                    mystery_summary = f"{len(mystery_files)} (no ext) detected → " + ", ".join(identified_parts)

                print("\n" + "-" * 80)
                print(f"  {tier_emoji} [{tier_name}] ▸ 📍 {loc_label} ▸ {breadcrumb_str}  |  Folder {curr_idx + 1}/{len(curr_candidates)}: '{sub_dir.name}'")
                print("-" * 80)
                print(f"  • Location:       {loc_label} ({loc_path})")
                print(f"  • Full Path:      {sub_dir}")
                print(f"  • Status:         {verified_badge}")
                print(f"  • Storage:        {size_str} across {files_count:,} files ({stats['subfolder_count']} subfolders)")
                print(f"  • Date Range:     {date_range}")

                # Format structured files and applications tree
                app_groups = ft_info.get("app_groups", [])
                no_ext_count = stats["ext_counts"].get('(no ext)', 0)
                total_groups = len(app_groups) + (1 if no_ext_count > 0 else 0)

                if total_groups > 0:
                    print(f"  • Discovered Files & Associated Apps:")
                    curr_item = 0
                    for grp in app_groups:
                        curr_item += 1
                        is_last = (curr_item == total_groups)
                        b_sym = "└──" if is_last else "├──"
                        pipe_sym = "   " if is_last else "│  "
                        print(f"    {b_sym} [{grp['count']:,} files] {grp['name']}:")
                        if grp["exts"]:
                            ext_line = "  •  ".join(grp["exts"][:4])
                            if len(grp["exts"]) > 4:
                                ext_line += f"  •  (+{len(grp['exts']) - 4} more)"
                            print(f"    {pipe_sym}  • {ext_line}")
                        if grp.get("mac_note"):
                            print(f"    {pipe_sym}  ↳ Status: {grp['mac_note']}")

                    if no_ext_count > 0:
                        curr_item += 1
                        print(f"    └── [{no_ext_count:,} files] Extensionless / Mystery Files:")
                        if mystery_summary:
                            print(f"         ↳ 🔍 {mystery_summary}")
                        else:
                            print(f"         ↳ 🔍 {no_ext_count} files with no extension")
                else:
                    print(f"  • Files & Apps:   ⚪ Empty folder (0 files)")

                print(f"  • Category Check: {ft_info['category_match_msg']}")
                print(f"  • Sample Files:   {samples}")
                print(f"\n  💡 Suggested Description:")
                print(f"     \"{suggested_desc}\"")

                if overlap:
                    print(f"\n  🔄 Verified Archive Overlap Detected:")
                    print(f"     ↳ Matching Verified Destination: '{overlap['target_name']}'")
                    print(f"       📍 Path: {overlap['target_path']}")
                    print(f"     ↳ {overlap['identical_count']} of {overlap['total_cand']} files ({overlap['pct']:.1f}%) are IDENTICAL duplicates ({format_size(overlap['identical_bytes'])})")
                    if overlap['diff_count'] > 0:
                        print(f"     ↳ {overlap['diff_count']} unique / diff files found ({format_size(overlap['diff_bytes'])})")
                    else:
                        print(f"     ↳ 100% duplicate — all {overlap['total_cand']} files already safely verified in destination")

                base_actions = []
                if overlap:
                    if overlap['diff_count'] > 0:
                        m_action_lbl = f"Merge {overlap['diff_count']} diff files into '{overlap['target_name']}' & delete duplicate folder on disk"
                    else:
                        m_action_lbl = f"Delete redundant duplicate folder (100% duplicate of '{overlap['target_name']}')"
                    base_actions.append({"key": "g", "label": f"{m_action_lbl} (Recommended)"})

                if child_subdirs:
                    d_badge = " (Recommended: inspect unverified contents)" if (is_verified == 1 and unverified_sub_count > 0) else ""
                    base_actions.append({"key": "d", "label": f"Drill down into '{sub_dir.name}' (Inspect its {len(child_subdirs)} subfolder{'s' if len(child_subdirs) != 1 else ''} at candidate level){d_badge}"})
                if nav_stack:
                    base_actions.append({"key": "u", "label": f"Drill up to '{nav_stack[-1][0].name}' (Return to parent level)"})

                has_snapshot_children = any(
                    re.search(r'(?:documents|\b(?:19\d\d|20\d\d|\d{8})\b|duplicates)', s.name.lower())
                    for s in child_subdirs
                ) or any(s.name.lower() in ('documents', 'my documents', 'nested documents') for s in child_subdirs)

                if child_subdirs and (has_snapshot_children or sub_dir.name.lower() in ('documents', 'my documents')):
                    base_actions.append({"key": "f", "label": f"Fold & consolidate snapshot folders in-place into '{sub_dir.name}' (Deduplicate & un-nest) (Recommended)"})

                base_actions.extend([
                    {"key": "a", "label": f"Approve description & attach app ('{detected_app}') (Mark Verified ✓)"},
                    {"key": "e", "label": "Edit folder name, description or attached app, apply tags & verify"},
                    {"key": "r", "label": "Rename folder on disk & database"},
                ])
                if files_count > 0:
                    mixed_badge = " (Recommended: Mixed sources detected)" if (len(ft_info.get("app_groups", [])) > 1 or len(stats["ext_counts"]) > 2) else ""
                    base_actions.append({"key": "x", "label": f"Extract & segregate file types into subfolder (Preserve folder structure){mixed_badge}"})
                if mystery_files:
                    base_actions.append({"key": "i", "label": f"Inspect & analyze {len(mystery_files)} mystery / extensionless files (Magic signatures & hex dump)"})
                if ft_info.get("has_unusable_app") and "priority 1" in tier_name.lower():
                    m_label = "Move to 'Priority 2 / Data' or 'Priority 2 / Legacy / Windows Data' (Recommended: Cannot be opened directly)"
                elif ft_info.get("suggested_move_tier"):
                    m_label = f"Move to {ft_info['suggested_move_tier']} (Recommended)"
                else:
                    m_label = "Move / Reassign to another Priority tier or parent folder"

                base_actions.extend([
                    {"key": "m", "label": m_label},
                    {"key": "s", "label": "Skip for now (remain unverified)"},
                    {"key": "q", "label": "Quit wizard and return to menu"}
                ])
                w_usage = get_menu_option_usage(db_path, "wizard_action")
                if overlap:
                    top_key = "g"
                    sorted_actions = sorted(base_actions, key=lambda x: (x["key"] != "g", -w_usage.get(x["key"], 0)))
                elif child_subdirs and (has_snapshot_children or sub_dir.name.lower() in ('documents', 'my documents')) and is_verified == 0:
                    top_key = "f"
                    sorted_actions = sorted(base_actions, key=lambda x: (x["key"] != "f", -w_usage.get(x["key"], 0)))
                elif not ft_info.get("is_match", True):
                    top_key = "m"
                    sorted_actions = sorted(base_actions, key=lambda x: (x["key"] != "m", -w_usage.get(x["key"], 0)))
                elif is_verified == 1 and child_subdirs and unverified_sub_count > 0:
                    top_key = "d"
                    sorted_actions = sorted(base_actions, key=lambda x: (x["key"] != "d", -w_usage.get(x["key"], 0)))
                else:
                    sorted_actions = sorted(base_actions, key=lambda x: w_usage.get(x["key"], 0), reverse=True)
                    top_key = sorted_actions[0]["key"] if (w_usage and w_usage.get(sorted_actions[0]["key"], 0) > 0) else ("a" if is_verified == 0 else "s")

                print("\n  Actions:")
                for act in sorted_actions:
                    cnt = w_usage.get(act["key"], 0)
                    cnt_badge = f" (Used {cnt}x) 🔥" if cnt > 0 and cnt == max(w_usage.values()) else (f" (Used {cnt}x)" if cnt > 0 else "")
                    def_badge = " [Default]" if act["key"] == top_key else ""
                    print(f"    [{act['key']}]{def_badge} {act['label']}{cnt_badge}")

                action_prompt_keys = "/".join([act["key"] for act in sorted_actions])
                action = input(f"\nSelect action [{action_prompt_keys}] (Default: {top_key}): ").strip().lower()
                if not action:
                    action = top_key
                record_menu_usage(db_path, "wizard_action", action, next((a["label"] for a in base_actions if a["key"] == action), ""))

                if action == 'd':
                    if not child_subdirs:
                        print(f"\n[Info] '{sub_dir.name}' has no subfolders to drill down into.")
                        continue
                    nav_stack.append((curr_parent, curr_candidates, curr_idx))
                    curr_parent = sub_dir
                    curr_candidates = child_subdirs
                    curr_idx = 0
                    level_banner_printed = False
                    try:
                        rel_down = curr_parent.resolve().relative_to(loc_path.resolve())
                        down_crumb = " ▸ ".join(rel_down.parts)
                    except Exception:
                        down_crumb = curr_parent.name
                    print(f"\n↳ 📂 Drilled down into '{down_crumb}' ({len(child_subdirs)} candidate subfolder{'s' if len(child_subdirs) != 1 else ''} to inspect)")
                    break
                elif action == 'u':
                    if not nav_stack:
                        print(f"\n[Info] Already at top level for this category. Cannot drill up further.")
                        continue
                    curr_parent, curr_candidates, curr_idx = nav_stack.pop()
                    level_banner_printed = False
                    try:
                        rel_up = curr_parent.resolve().relative_to(loc_path.resolve())
                        up_crumb = " ▸ ".join(rel_up.parts)
                    except Exception:
                        up_crumb = curr_parent.name
                    print(f"\n↳ ⤴️ Drilled up to '{up_crumb}' (Folder {curr_idx + 1}/{len(curr_candidates)}: '{curr_candidates[curr_idx].name}')")
                    break
                elif action == 'g' and overlap:
                    print("\n" + "=" * 80)
                    if overlap['diff_count'] > 0:
                        print("  MERGE DIFF FILES & REMOVE DUPLICATE FOLDER")
                    else:
                        print("  DELETE REDUNDANT DUPLICATE FOLDER")
                    print("=" * 80)
                    print(f"  • Source Folder:      {sub_dir}")
                    print(f"  • Destination Folder: {overlap['target_path']}")
                    print(f"  • Identical Files:    {overlap['identical_count']} of {overlap['total_cand']} ({overlap['pct']:.1f}%) — {format_size(overlap['identical_bytes'])}")
                    if overlap['diff_count'] > 0:
                        print(f"  • Diff Files to Merge: {overlap['diff_count']} files ({format_size(overlap['diff_bytes'])})")
                        print("\n  Diff / Unique files list:")
                        for df in overlap['diff_files'][:12]:
                            conflict_note = ""
                            if df.get('conflict'):
                                target_mtime = df['target_match']['mtime']
                                if df['mtime'] > target_mtime:
                                    conflict_note = " [Conflict: target exists → candidate is newer]"
                                else:
                                    conflict_note = " [Conflict: target exists → target is newer]"
                            elif df.get('reason') == 'modified_diff_path':
                                conflict_note = " [Modified revision: alternate path exists in target]"
                            else:
                                conflict_note = " [New file]"
                            print(f"    • {df['rel_path']} ({format_size(df['size'])}){conflict_note}")
                        if len(overlap['diff_files']) > 12:
                            print(f"    ↳ ... (+{len(overlap['diff_files']) - 12} more files)")
                        confirm_prompt = f"\nMerge {overlap['diff_count']} diff files into '{overlap['target_name']}' and delete '{sub_dir.name}'? [Y/n/c] (Default: Y): "
                    else:
                        print(f"  • All {overlap['total_cand']} files are already verified in '{overlap['target_name']}'.")
                        confirm_prompt = f"\nDelete redundant duplicate folder '{sub_dir.name}' from disk and database? [Y/n/c] (Default: Y): "

                    confirm_g = input(confirm_prompt).strip().lower()
                    if confirm_g in ('', 'y', 'yes'):
                        ok = execute_folder_merge_and_cleanup(sub_dir, overlap, db_path)
                        if ok:
                            total_curated += 1
                            curr_candidates = [s for s in sorted(curr_parent.iterdir()) if s.is_dir() and not s.name.startswith('.')]
                            break
                        else:
                            continue
                    else:
                        print("Merge/delete cancelled.")
                        continue
                elif action == 'a':
                    rel_p = sub_dir.resolve().relative_to(loc_path.resolve())
                    tags = [(tier_info["tag"], tier_info["color"])]
                    seen_tags = {tier_info["tag"]}
                    for p in rel_p.parts:
                        clean_p = p.strip()
                        if clean_p and clean_p not in seen_tags:
                            seen_tags.add(clean_p)
                            tags.append((clean_p, 0))

                    set_finder_tags(sub_dir, tags)
                    _sync_directory_tags_to_db(sub_dir, tags, db_path)
                    _set_directory_description_in_db(sub_dir, suggested_desc, db_path, is_verified=True, app_needed=detected_app)
                    print(f"\n[Success] ✓ Approved & verified '{sub_dir.name}'. Tags, description & app '{detected_app}' saved.")
                    total_curated += 1
                    curr_idx += 1
                    break
                elif action == 'e':
                    print(f"\nCurrent folder name: '{sub_dir.name}'")
                    new_fname = input(f"Enter new folder name (or press Enter to keep '{sub_dir.name}'): ").strip()

                    print(f"\nCurrent description: \"{suggested_desc}\"")
                    custom_desc = input("Enter custom description (or press Enter to keep suggestion): ").strip()
                    final_desc = custom_desc if custom_desc else suggested_desc

                    print(f"\nCurrent attached app: '{detected_app}'")
                    custom_app = input(f"Enter attached app (or press Enter to keep '{detected_app}'): ").strip()
                    final_app = custom_app if custom_app else detected_app

                    if new_fname and new_fname != sub_dir.name:
                        renamed_ok, new_renamed_path, rename_err = _rename_directory_on_disk_and_db(sub_dir, new_fname, db_path)
                        if renamed_ok:
                            print(f"[Success] Renamed folder to '{new_fname}'.")
                            sub_dir = new_renamed_path
                        else:
                            print(f"[Error] Failed to rename folder: {rename_err}. Keeping original name.")

                    rel_p = sub_dir.resolve().relative_to(loc_path.resolve())
                    tags = [(tier_info["tag"], tier_info["color"])]
                    seen_tags = {tier_info["tag"]}
                    for p in rel_p.parts:
                        clean_p = p.strip()
                        if clean_p and clean_p not in seen_tags:
                            seen_tags.add(clean_p)
                            tags.append((clean_p, 0))

                    set_finder_tags(sub_dir, tags)
                    _sync_directory_tags_to_db(sub_dir, tags, db_path)
                    _set_directory_description_in_db(sub_dir, final_desc, db_path, is_verified=True, app_needed=final_app)
                    print(f"\n[Success] ✓ Folder '{sub_dir.name}', description & attached app '{final_app}' approved & verified.")
                    total_curated += 1
                    curr_idx += 1
                    break
                elif action == 'r':
                    print(f"\nCurrent folder name: '{sub_dir.name}'")
                    new_fname = input(f"Enter new folder name (or press Enter to cancel): ").strip()
                    if not new_fname or new_fname == sub_dir.name:
                        print("Rename cancelled.")
                        continue
                    renamed_ok, new_renamed_path, rename_err = _rename_directory_on_disk_and_db(sub_dir, new_fname, db_path)
                    if renamed_ok:
                        print(f"\n[Success] Renamed folder on disk and SQLite: '{sub_dir.name}' -> '{new_fname}'")
                        sub_dir = new_renamed_path
                        curr_candidates = [s for s in sorted(curr_parent.iterdir()) if s.is_dir() and not s.name.startswith('.')]
                        if sub_dir in curr_candidates:
                            curr_idx = curr_candidates.index(sub_dir)
                        suggested_desc = suggest_folder_description(sub_dir.name, curr_parent.name, tier_name, stats, ft_info)
                        continue
                    else:
                        print(f"\n[Error] Failed to rename folder: {rename_err}")
                        continue
                elif action == 'm':
                    active_locs = get_priority_locations(db_path, active_only=True)
                    target_loc = None
                    target_l1_dest = None
                    newly_created_l1 = False
                    target_cat_name = ""

                    # If this folder triggered the Priority 1 unusable app rule, provide quick archival targets:
                    if ft_info.get("has_unusable_app") and "priority 1" in tier_name.lower():
                        p2_loc = next((al for al in active_locs if al["priority_tier"].lower() == "priority 2"), None)
                        print("\n" + "=" * 80)
                        print("  RECOMMENDED ARCHIVAL RELOCATION (Priority 1 Storage Mandate)")
                        print("  • Priority 1 Mandate: Reserved ONLY for high-availability internal storage (Internal HD for iMini).")
                        print("  • Archival Target:    MS Money data belongs on external storage (LaCie Priority 2).")
                        print("  • Backup Protection:  Priority 2 preserves iDrive backup inclusion for eventual reference.")
                        print("=" * 80)
                        print("  [1] Move to 'Priority 2 ▸ Data' on LaCie (Recommended)")
                        print("  [2] Move to 'Priority 2 ▸ Data / Legacy / Windows' on LaCie (Recommended Archival)")
                        print("  [3] Choose standard destination location & category")
                        print("  [p] Enter custom target path directly (creates destination folders if needed)")
                        print("  [c] Cancel move")
                        m_rec_choice = input("\nSelect relocation target [1/2/3/p/c] or paste full path (Default: 1): ").strip()
                        if not m_rec_choice:
                            m_rec_choice = "1"
                        if m_rec_choice.lower() == 'c':
                            print("Move cancelled.")
                            continue
                        elif m_rec_choice == '1' and p2_loc:
                            target_loc = p2_loc
                            target_tier_dir = target_loc["path"]
                            target_cat_name = "Data"
                            target_l1_dest = target_tier_dir / target_cat_name
                            if not target_l1_dest.exists():
                                target_l1_dest.mkdir(parents=True, exist_ok=True)
                                newly_created_l1 = True
                        elif m_rec_choice == '2' and p2_loc:
                            target_loc = p2_loc
                            target_tier_dir = target_loc["path"]
                            target_cat_name = "Data / Legacy / Windows"
                            target_l1_dest = target_tier_dir / "Data" / "Legacy" / "Windows"
                            if not target_l1_dest.exists():
                                target_l1_dest.mkdir(parents=True, exist_ok=True)
                                newly_created_l1 = True
                        elif m_rec_choice.lower() == 'p' or '/' in m_rec_choice or m_rec_choice.startswith('~'):
                            path_arg = None if m_rec_choice.lower() == 'p' else m_rec_choice
                            ok = _handle_custom_relocation_target(path_arg, sub_dir, active_locs, db_path, suggested_desc, detected_app)
                            if ok:
                                total_curated += 1
                                curr_candidates = [s for s in sorted(curr_parent.iterdir()) if s.is_dir() and not s.name.startswith('.')]
                                break
                            else:
                                continue

                    # Otherwise, or if user chose [3] Standard / Custom:
                    if not target_loc or not target_l1_dest:
                        print("\nSelect Target Location for move:")
                        for l_idx, al in enumerate(active_locs, 1):
                            p_info = PRIORITY_TIER_CONFIG.get(al["priority_tier"].lower(), {"color": 0})
                            p_em = FINDER_COLOR_EMOJI.get(p_info["color"], "⚪")
                            print(f"  {l_idx}: {p_em} {al['priority_tier'].title()} - {al['label']} ({al['path_str']})")
                        print("  p: 📁 Enter custom target folder path directly (creates destination hierarchy)")
                        l_sel = input(f"Select location (1-{len(active_locs)}), 'p' for custom path, or 'c' to cancel: ").strip()
                        if l_sel.lower() == 'c':
                            print("Move cancelled.")
                            continue
                        elif l_sel.lower() == 'p' or '/' in l_sel or l_sel.startswith('~'):
                            path_arg = None if l_sel.lower() == 'p' else l_sel
                            ok = _handle_custom_relocation_target(path_arg, sub_dir, active_locs, db_path, suggested_desc, detected_app)
                            if ok:
                                total_curated += 1
                                curr_candidates = [s for s in sorted(curr_parent.iterdir()) if s.is_dir() and not s.name.startswith('.')]
                                break
                            else:
                                continue
                        elif not l_sel.isdigit() or int(l_sel) < 1 or int(l_sel) > len(active_locs):
                            print("Move cancelled.")
                            continue
                        
                        target_loc = active_locs[int(l_sel) - 1]
                        target_tier_dir = target_loc["path"]
                        target_l1_subdirs = [s for s in sorted(target_tier_dir.iterdir()) if s.is_dir() and not s.name.startswith('.')]
                        print(f"\nSelect target category in {target_loc['label']}:")
                        for t_idx, tl1 in enumerate(target_l1_subdirs, 1):
                            print(f"  {t_idx}: {tl1.name}")
                        print(f"  {len(target_l1_subdirs) + 1}: Create new category folder...")
                        tl1_sel = input(f"Select category (1-{len(target_l1_subdirs) + 1}) or 'c' to cancel: ").strip()
                        if tl1_sel == str(len(target_l1_subdirs) + 1):
                            new_cat_input = input("Enter new category name: ").strip()
                            if not new_cat_input:
                                print("Move cancelled.")
                                continue
                            target_cat_name = new_cat_input
                            target_l1_dest = target_tier_dir / target_cat_name
                            if not target_l1_dest.exists():
                                target_l1_dest.mkdir(parents=True, exist_ok=True)
                                newly_created_l1 = True
                        elif tl1_sel.isdigit() and 1 <= int(tl1_sel) <= len(target_l1_subdirs):
                            target_l1_dest = target_l1_subdirs[int(tl1_sel) - 1]
                            target_cat_name = target_l1_dest.name
                        else:
                            print("Move cancelled.")
                            continue

                    if not target_cat_name:
                        target_cat_name = target_l1_dest.name

                    clean_suggested = suggest_clean_folder_name(sub_dir.name, detected_app, stats.get("ext_counts", {}))
                    if clean_suggested != sub_dir.name:
                        print(f"\nDestination folder name:")
                        print(f"  • Current name:     '{sub_dir.name}'")
                        print(f"  • Suggested clean:  '{clean_suggested}' (Default)")
                        name_input = input(f"Enter folder name in destination [Press Enter for '{clean_suggested}', '1' for '{sub_dir.name}', or type new name]: ").strip()
                        if not name_input:
                            dest_fname = clean_suggested
                        elif name_input == '1':
                            dest_fname = sub_dir.name
                        else:
                            dest_fname = name_input
                    else:
                        name_input = input(f"\nEnter destination folder name [Press Enter for '{sub_dir.name}', or type new name]: ").strip()
                        dest_fname = name_input if name_input else sub_dir.name

                    if dest_fname.lower() == 'c':
                        print("Move cancelled.")
                        continue

                    target_dest_path = target_l1_dest / dest_fname
                    if target_dest_path.exists():
                        print(f"\n[Error] Destination '{target_dest_path}' already exists!")
                        continue

                    # If the target parent category doesn't exist on disk, create it
                    if not target_l1_dest.exists():
                        target_l1_dest.mkdir(parents=True, exist_ok=True)
                        newly_created_l1 = True

                    confirm_m = input(f"Move '{sub_dir.name}' → '{target_dest_path}'? [y/N]: ").strip().lower()
                    if confirm_m in ('y', 'yes'):
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
                            c_cur.execute("UPDATE directories SET name = ? WHERE path = ?", (target_dest_path.name, new_p))
                            c_conn.commit()
                            c_conn.close()

                        if target_dest_path.name != sub_dir.name:
                            suggested_desc = suggest_folder_description(target_dest_path.name, target_cat_name, target_loc["priority_tier"], stats, ft_info)

                        # Apply hierarchical tags and metadata for each level from root to target
                        apply_hierarchical_tags_for_path(target_dest_path, target_loc, db_path, suggested_desc, detected_app)

                        print(f"\n[Success] ✓ Moved and verified '{sub_dir.name}' → '{target_dest_path.name}' under {target_loc['label']} / {target_cat_name}.")
                        total_curated += 1
                        curr_candidates = [s for s in sorted(curr_parent.iterdir()) if s.is_dir() and not s.name.startswith('.')]
                        break
                    else:
                        print("Move cancelled.")
                        continue
                elif action == 'i' and mystery_files:
                    did_rename = _handle_inspect_mystery_files(sub_dir, mystery_analyses, db_path)
                    if did_rename:
                        stats = analyze_folder_content(sub_dir)
                        ft_info = identify_folder_filetypes_and_apps(db_path, stats["ext_counts"], curr_parent.name, tier_name)
                        if not existing_app:
                            detected_app = ft_info.get("app_needed")
                        if not existing_desc:
                            suggested_desc = suggest_folder_description(sub_dir.name, curr_parent.name, tier_name, stats, ft_info)
                        size_str = format_size(stats["total_bytes"])
                        files_count = stats["total_files"]
                        top_exts = ft_info["file_types_formatted"]
                        samples = ", ".join(stats["sample_files"][:3]) if stats["sample_files"] else "None"
                    continue
                elif action == 'x' and files_count > 0:
                    did_extract = extract_file_types_interactive(sub_dir, db_path, stats, ft_info)
                    if did_extract:
                        stats = analyze_folder_content(sub_dir)
                        ft_info = identify_folder_filetypes_and_apps(db_path, stats["ext_counts"], curr_parent.name, tier_name)
                        if not existing_app:
                            detected_app = ft_info.get("app_needed")
                        if not existing_desc:
                            suggested_desc = suggest_folder_description(sub_dir.name, curr_parent.name, tier_name, stats, ft_info)
                        size_str = format_size(stats["total_bytes"])
                        files_count = stats["total_files"]
                        date_range = f"{stats['earliest_date']} → {stats['latest_date']}" if stats["earliest_date"] else "Unknown dates"
                        top_exts = ft_info["file_types_formatted"]
                        samples = ", ".join(stats["sample_files"][:3]) if stats["sample_files"] else "None"
                        child_subdirs = [s for s in sorted(sub_dir.iterdir()) if s.is_dir() and not s.name.startswith('.')] if sub_dir.exists() and sub_dir.is_dir() else []
                    continue
                elif action == 'f' and child_subdirs:
                    did_fold = fold_snapshot_folders_interactive(sub_dir, db_path)
                    if did_fold:
                        stats = analyze_folder_content(sub_dir)
                        ft_info = identify_folder_filetypes_and_apps(db_path, stats["ext_counts"], curr_parent.name, tier_name)
                        if not existing_app:
                            detected_app = ft_info.get("app_needed")
                        if not existing_desc:
                            suggested_desc = suggest_folder_description(sub_dir.name, curr_parent.name, tier_name, stats, ft_info)
                        size_str = format_size(stats["total_bytes"])
                        files_count = stats["total_files"]
                        date_range = f"{stats['earliest_date']} → {stats['latest_date']}" if stats["earliest_date"] else "Unknown dates"
                        top_exts = ft_info["file_types_formatted"]
                        samples = ", ".join(stats["sample_files"][:3]) if stats["sample_files"] else "None"
                        child_subdirs = [s for s in sorted(sub_dir.iterdir()) if s.is_dir() and not s.name.startswith('.')] if sub_dir.exists() and sub_dir.is_dir() else []
                    continue
                elif action == 's':
                    print(f"\n[Skipped] '{sub_dir.name}' left unverified.")
                    total_skipped += 1
                    curr_idx += 1
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
        app_val = item.get("app_needed")
        print(f"  • App Needed:   {app_val if app_val else 'None'}")
        
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

        level1_actions = [
            {"key": "1", "label": "Apply standard Priority tags (Priority tier with color + folder name tag)"},
            {"key": "2", "label": "Add / Edit folder description & required application (Stored in SQLite)"},
            {"key": "3", "label": "Custom tag & Finder color (Add/edit custom tag and pick color)"},
            {"key": "4", "label": "Move / Reassign to a different Priority Tier (e.g., Priority 2 -> Priority 3)"},
            {"key": "5", "label": "Propagate current tags to all subfolders in this subtree"},
            {"key": "6", "label": "Remove / Clear all tags from this folder"},
            {"key": "7", "label": "Launch Curation Wizard on this folder's subdirectories (Scan & Triage)"},
            {"key": "8", "label": "Add / Sync this folder to iDrive backup set (.plist)"},
            {"key": "9", "label": "Return to folder list"}
        ]
        l1_usage = get_menu_option_usage(db_path, "level1_inspect_menu")
        sorted_l1 = sorted(level1_actions, key=lambda x: l1_usage.get(x["key"], 0), reverse=True)
        top_l1 = sorted_l1[0]["key"] if (l1_usage and l1_usage.get(sorted_l1[0]["key"], 0) > 0) else "2"

        print("\nActions:")
        for la in sorted_l1:
            cnt = l1_usage.get(la["key"], 0)
            badge = f" (Used {cnt}x) 🔥" if cnt > 0 and cnt == max(l1_usage.values()) else (f" (Used {cnt}x)" if cnt > 0 else "")
            def_badge = " [Default]" if la["key"] == top_l1 and l1_usage.get(top_l1, 0) > 0 else ""
            print(f"  {la['key']}. {la['label']}{badge}{def_badge}")

        def_prompt = f" [Default: {top_l1}]" if (l1_usage and l1_usage.get(top_l1, 0) > 0) else ""
        raw_l1 = input(f"\nSelect action (1-9){def_prompt}: ").strip()
        sub_choice = raw_l1 if raw_l1 else (top_l1 if (l1_usage and l1_usage.get(top_l1, 0) > 0) else "")
        record_menu_usage(db_path, "level1_inspect_menu", sub_choice, next((a["label"] for a in level1_actions if a["key"] == sub_choice), ""))

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
            final_desc = new_desc if new_desc else (None if new_desc == "" and not cur_desc else cur_desc)

            cur_app = item.get("app_needed") or ""
            print(f"Current app needed:  {cur_app if cur_app else '(empty)'}")
            new_app = input("Enter required application (or press Enter to keep current): ").strip()
            final_app = new_app if new_app else (None if new_app == "" and not cur_app else cur_app)

            _set_directory_description_in_db(folder_path, final_desc, db_path, app_needed=final_app)
            item["description"] = final_desc
            item["app_needed"] = final_app
            print(f"\n[Success] Folder description and required app saved to SQLite.")
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

def view_file_extensions_catalog(db_path: str):
    """Displays the registered file extensions catalog with categories and required applications."""
    if not os.path.exists(db_path):
        print("\n[Notice] No database found.")
        return
    conn = get_db_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT extension, category, description, primary_app, mac_app, is_critical_format
        FROM file_extensions
        ORDER BY category, extension
    """)
    rows = cursor.fetchall()
    conn.close()

    print("\n" + "=" * 98)
    print(f"FILE EXTENSIONS & APPLICATIONS CATALOG ({len(rows)} registered file types)")
    print("=" * 98)
    print(f"{'Extension':<12} {'Category':<20} {'Description':<32} {'Required App (Primary / Mac)'}")
    print("-" * 98)
    curr_cat = None
    for ext, cat, desc, p_app, m_app, is_crit in rows:
        if cat != curr_cat:
            curr_cat = cat
            print(f"\n📂 [{curr_cat.upper()}]")
        app_disp = f"{p_app} (Mac: {m_app})" if m_app else p_app
        crit_tag = " ⚠️ [Critical]" if is_crit else ""
        print(f"  {ext:<10} {cat:<20} {desc:<32} {app_disp}{crit_tag}")
    print("=" * 98)
    input("\nPress Enter to continue...")


def backfill_curation_events(db_path: str) -> dict:
    """
    Backfills historical verified directories and files into curation_events table.
    Ensures baseline provenance records exist for all previously verified resources.
    """
    if not os.path.exists(db_path):
        return {"backfilled_dirs": 0, "backfilled_files": 0}

    conn = get_db_connection(db_path)
    cur = conn.cursor()
    ensure_curation_events_table(cur)

    ver_dirs = cur.execute("""
        SELECT id, name, path, description, verified_at, app_needed
        FROM directories
        WHERE is_verified = 1
        ORDER BY verified_at ASC
    """).fetchall()

    backfilled_dirs = 0
    backfilled_files = 0

    for d_id, d_name, d_path, d_desc, v_at, app_need in ver_dirs:
        exists = cur.execute("""
            SELECT id FROM curation_events WHERE directory_id = ? AND resource_type = 'directory'
        """, (d_id,)).fetchone()

        v_time = v_at or datetime.datetime.now().isoformat()
        b_date = v_time[:10].replace('-', '')
        batch_id = f"baseline_{b_date}_{d_name.lower().replace(' ', '_')}"

        tags = [r[0] for r in cur.execute("SELECT tag_name FROM directory_tags WHERE directory_id = ?", (d_id,)).fetchall()]
        tags_str = ", ".join(tags)

        if not exists:
            d_size_row = cur.execute("""
                SELECT COALESCE(SUM(f.size_bytes), 0)
                FROM directories sub
                JOIN files f ON f.directory_id = sub.id
                WHERE sub.id = ? OR sub.path LIKE ? || '/%'
            """, (d_id, d_path)).fetchone()
            dir_bytes = d_size_row[0] if d_size_row else 0

            cur.execute("""
                INSERT INTO curation_events (
                    batch_id, event_type, created_at, source_path, destination_path,
                    origin_folder, resource_type, resource_path, file_id, directory_id,
                    file_size_bytes, finder_tags, details
                ) VALUES (?, 'verified_baseline_folder', ?, ?, ?, ?, 'directory', ?, NULL, ?, ?, ?, ?)
            """, (
                batch_id, v_time, d_path, d_path,
                d_name, d_path, d_id,
                dir_bytes, tags_str, json.dumps({
                    'description': d_desc,
                    'app_needed': app_need,
                    'is_backfilled': True
                })
            ))
            backfilled_dirs += 1

        # Files for this folder
        files = cur.execute("""
            SELECT f.id, f.name, f.size_bytes, f.directory_id, f.scanned_at, sub.path
            FROM files f
            JOIN directories sub ON f.directory_id = sub.id
            WHERE sub.id = ? OR sub.path LIKE ? || '/%'
        """, (d_id, d_path)).fetchall()

        for f_id, f_name, f_size, sub_d_id, f_scan_at, sub_path in files:
            f_exists = cur.execute("""
                SELECT id FROM curation_events WHERE file_id = ?
            """, (f_id,)).fetchone()
            if f_exists:
                continue

            f_full = f"{sub_path}/{f_name}"
            f_time = f_scan_at or v_time

            cur.execute("""
                INSERT INTO curation_events (
                    batch_id, event_type, created_at, source_path, destination_path,
                    origin_folder, resource_type, resource_path, file_id, directory_id,
                    file_size_bytes, finder_tags, details
                ) VALUES (?, 'verified_baseline_file', ?, ?, ?, ?, 'file', ?, ?, ?, ?, ?, ?)
            """, (
                batch_id, f_time, f_full, f_full,
                d_name, f_full, f_id, sub_d_id,
                f_size, tags_str, json.dumps({
                    'baseline_folder': d_name,
                    'is_backfilled': True
                })
            ))

            cur.execute("""
                INSERT OR IGNORE INTO file_tags (file_id, tag_name, created_at)
                VALUES (?, ?, ?)
            """, (f_id, f"baseline:{d_name}", f_time))
            cur.execute("""
                INSERT OR IGNORE INTO file_tags (file_id, tag_name, created_at)
                VALUES (?, ?, ?)
            """, (f_id, f"curation_batch:{batch_id}", f_time))

            backfilled_files += 1

    conn.commit()
    conn.close()
    return {"backfilled_dirs": backfilled_dirs, "backfilled_files": backfilled_files}


def view_curation_events_history(db_path: str):
    """Displays chronological history of curation events (merges, relocations, verifications)."""
    if not os.path.exists(db_path):
        print("\n[Notice] Database not found.")
        return

    conn = get_db_connection(db_path)
    cur = conn.cursor()
    ensure_curation_events_table(cur)

    # Check for batches
    batches = cur.execute("""
        SELECT batch_id, event_type, origin_folder, source_path, destination_path,
               COUNT(*) as resource_count, MIN(created_at) as created_at
        FROM curation_events
        GROUP BY batch_id
        ORDER BY created_at DESC
    """).fetchall()

    if not batches:
        print("\n" + "=" * 98)
        print("  CURATION EVENTS & PROVENANCE HISTORY LOG")
        print("=" * 98)
        print("  No curation events logged yet.")
        print("=" * 98)
        conn.close()
        input("\nPress Enter to continue...")
        return

    print("\n" + "=" * 98)
    print("  CURATION EVENTS & PROVENANCE HISTORY LOG")
    print("=" * 98)
    print(f"{'#':<4} {'Date & Time':<20} {'Event Type':<22} {'Origin / Source':<24} {'Destination':<24}")
    print("-" * 98)

    batch_map = {}
    for idx, (b_id, ev_type, orig, src, dest, cnt, dt) in enumerate(batches, 1):
        dt_clean = dt[:19].replace('T', ' ')
        orig_disp = orig if orig else (Path(src).name if src else "N/A")
        dest_disp = Path(dest).name if dest else "N/A"
        batch_map[str(idx)] = b_id
        print(f"{idx:<4} {dt_clean:<20} {ev_type:<22} {orig_disp:<24} {dest_disp:<24}")

    print("-" * 98)
    sel = input("\nEnter event # to inspect individual resources & tags (or press Enter to return): ").strip()
    if sel in batch_map:
        b_id = batch_map[sel]
        items = cur.execute("""
            SELECT resource_type, resource_path, file_size_bytes, finder_tags, created_at, details
            FROM curation_events
            WHERE batch_id = ?
            ORDER BY resource_type DESC, resource_path ASC
        """, (b_id,)).fetchall()

        print("\n" + "=" * 98)
        print(f"  BATCH DETAILS: {b_id} ({len(items)} resources)")
        print("=" * 98)
        for r_type, r_path, f_size, f_tags, c_at, details_str in items:
            sz_str = format_size(f_size) if f_size else ""
            p_name = Path(r_path).name
            print(f"  • [{r_type.upper()}] {p_name} ({sz_str})")
            print(f"    📍 Path: {r_path}")
            if f_tags:
                print(f"    🏷️ Finder Tags: {f_tags}")
            if details_str:
                print(f"    ↳ Details: {details_str}")
        print("=" * 98)
        input("\nPress Enter to continue...")

    conn.close()


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
                    folder_app = None
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

                        cursor.execute("SELECT description, app_needed FROM directories WHERE path = ?", (res_p,))
                        d_row = cursor.fetchone()
                        if d_row:
                            if d_row[0]:
                                folder_desc = d_row[0]
                            folder_app = d_row[1]
                        if not folder_desc:
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
                        "description": folder_desc,
                        "app_needed": folder_app
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
            if item.get("app_needed"):
                print(f"     ↳ 💻 App Needed: {item['app_needed']}")

        print("-" * 98)
        print(f"Total Folders: {len(level1_items)}")
        cmd_options = [
            {"key": "w", "label": "'w' - Launch Sequential Curation Wizard (Triage subfolders across locations)"},
            {"key": "v", "label": "'v' / 'status' - Curation & Verification Report (Separated Approved vs Unapproved folders)"},
            {"key": "events", "label": "'events' / 'history' - View Curation Events History Log (Provenance & tag audit)"},
            {"key": "loc", "label": "'loc' - Manage Priority Locations (Add / Edit / Remove mapped folders for Priority 1-4)"},
            {"key": "idrive", "label": "'idrive' - Audit iDrive backup inclusion (Check Priority 1 & 2 folders in iDrive)"},
            {"key": "ext", "label": "'ext' - View File Extensions & Required Applications Catalog (Database library)"},
            {"key": "a", "label": "'a' - Auto-tag untagged folders with parent Priority & category"},
            {"key": "reset-tags", "label": "'reset-tags' - Reset subfolder tags & verification (Preserve level-1, clear level-2+ tags)"},
            {"key": "r", "label": "'r' - Refresh view from filesystem"},
            {"key": "b", "label": "'b' - Return to main menu"}
        ]
        review_usage = get_menu_option_usage(db_path, "priority_review_menu")
        sorted_cmds = sorted(cmd_options, key=lambda x: review_usage.get(x["key"], 0), reverse=True)
        top_cmd = sorted_cmds[0]["key"] if (review_usage and review_usage.get(sorted_cmds[0]["key"], 0) > 0) else None

        print("\nCommands:")
        for c in sorted_cmds:
            cnt = review_usage.get(c["key"], 0)
            badge = f" (Used {cnt}x) 🔥" if cnt > 0 and cnt == max(review_usage.values()) else (f" (Used {cnt}x)" if cnt > 0 else "")
            def_badge = " [Default]" if c["key"] == top_cmd else ""
            print(f"  • {c['label']}{badge}{def_badge}")
        print(f"  • Enter folder number (1-{len(level1_items)}) to inspect & edit tags / color / description / tier")
        print("  • 'p1'-'p4' - Edit description of a top-level Priority tier (Priority 1-4)")

        def_prompt = f" [Default: {top_cmd}]" if top_cmd else ""
        raw_action = input(f"\nSelect option or folder number{def_prompt}: ").strip().lower()
        action_choice = raw_action if raw_action else (top_cmd if top_cmd else "")
        if action_choice:
            record_menu_usage(db_path, "priority_review_menu", action_choice, next((c["label"] for c in cmd_options if c["key"] == action_choice), ""))

        if action_choice == 'b':
            break
        elif action_choice == 'r':
            continue
        elif action_choice in ['v', 'status']:
            generate_curation_verification_report(db_path)
            continue
        elif action_choice in ['events', 'history']:
            view_curation_events_history(db_path)
            continue
        elif action_choice == 'ext':
            view_file_extensions_catalog(db_path)
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
        if is_volume_mounted(dpath) and not os.path.exists(dpath):
            cursor.execute("SELECT COUNT(*) FROM files WHERE directory_id = ?", (did,))
            del_files += cursor.fetchone()[0]
            cursor.execute("DELETE FROM directory_tags WHERE directory_id = ?", (did,))
            cursor.execute("DELETE FROM directories WHERE id = ?", (did,))
            del_dirs += 1

    # Check remaining files in existing directories
    cursor.execute("SELECT f.id, f.name, d.path FROM files f JOIN directories d ON f.directory_id = d.id")
    all_files = cursor.fetchall()
    print(f"Checking {len(all_files):,} files against filesystem...")

    for fid, fname, dpath in all_files:
        if is_volume_mounted(dpath):
            full_path = os.path.join(dpath, fname)
            if fname == ".DS_Store" or not os.path.exists(full_path):
                cursor.execute("DELETE FROM file_tags WHERE file_id = ?", (fid,))
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
    """Interactively folds snapshots, segregates non-media files, or extracts specific file types while preserving folder structure."""
    print("\n--- FILE CONSOLIDATION, SEGREGATION & EXTRACTION ---")
    print("  1. Fold & consolidate historical snapshot folders in-place (Deduplicate & un-nest) (Recommended)")
    print("  2. Extract specific file types (.doc, .pdf, code, etc.) into subfolder (Preserve folder structure)")
    print("  3. Segregate non-media files from media folder (Keep media, move docs/others)")
    print("  4. Return to menu")
    seg_mode = input("Select mode (1-4) [Default: 1]: ").strip()
    if seg_mode == "4":
        return
    if seg_mode == "1" or not seg_mode:
        last_dir = get_app_setting(db_path, "last_scanned_dir")
        p1_doc = Path("/Volumes/LaCie/Storage/Priority 1/Documents")
        default_dir = str(p1_doc) if p1_doc.exists() else (last_dir if (last_dir and os.path.exists(last_dir)) else "")
        p_msg = f"Enter folder to fold and consolidate [Default: {default_dir}]: " if default_dir else "Enter folder to fold and consolidate: "
        s_in = input(p_msg).strip().strip('"').strip("'")
        s_path = s_in if s_in else default_dir
        if not s_path or not os.path.isdir(s_path):
            print(f"\n[Error] Invalid directory '{s_path}'.")
            return
        fold_snapshot_folders_interactive(Path(s_path), db_path)
        return
    elif seg_mode == "2":
        last_dir = get_app_setting(db_path, "last_scanned_dir")
        p_msg = f"Enter folder to extract from [Default: {last_dir}]: " if (last_dir and os.path.exists(last_dir)) else "Enter folder to extract from: "
        s_in = input(p_msg).strip().strip('"').strip("'")
        s_path = s_in if s_in else (last_dir if last_dir and os.path.exists(last_dir) else "")
        if not s_path or not os.path.isdir(s_path):
            print(f"\n[Error] Invalid directory '{s_path}'.")
            return
        extract_file_types_interactive(Path(s_path), db_path)
        return

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
    # 3. Dedicated db/ subfolder symlink or file
    db_folder_link = Path(__file__).resolve().parent.parent / "db" / "drive_audit.db"
    if db_folder_link.exists():
        return str(db_folder_link)
    # 4. Project root symlink or workspace relative database
    root_link = Path(__file__).resolve().parent.parent / "drive_audit.db"
    if root_link.exists():
        return str(root_link)
    if os.path.exists("db/drive_audit.db"):
        return "db/drive_audit.db"
    return "drive_audit.db"

def main():
    db_file = get_orchestrator_db_path()

    while True:
        print("\n" + "=" * 55)
        print("        DRIVE AUDIT & STORAGE ORCHESTRATOR        ")
        print("=" * 55)
        print(f"  📍 Database: {db_file}")
        print("=" * 55)
        main_options = [
            {"key": "1", "label": "Tagging Review, Curation Wizard & Subfolder Triage"},
            {"key": "2", "label": "Scan & index directory (Read-only catalog & tag sync)"},
            {"key": "3", "label": "View hosts & storage overview"},
            {"key": "4", "label": "View top-level folder scans report"},
            {"key": "5", "label": "Generate report of largest files"},
            {"key": "6", "label": "Prune deleted records from DB (Sync with disk)"},
            {"key": "7", "label": "List all active tags (Directory & File)"},
            {"key": "8", "label": "Tag & sync folders (Priority Tiers, Finder Colors & DB)"},
            {"key": "9", "label": "Search files by tag (Finder & Manual)"},
            {"key": "10", "label": "Consolidate snapshots / Extract file types & non-media files"},
            {"key": "11", "label": "Detect & clean duplicate files (Interactive duplicate resolver)"},
            {"key": "12", "label": "View Curation & Verification Report (Approved vs Unapproved folders)"},
            {"key": "13", "label": "☁️ Launch iDrive Device Backup Wizard (Triage remote devices & create Storage Rules)"},
            {"key": "14", "label": "📋 View all assigned Storage Rules (Full cloud-to-local rules ledger)"},
            {"key": "15", "label": "Exit"}
        ]
        main_usage = get_menu_option_usage(db_file, "main_menu")
        sorted_main = sorted(main_options, key=lambda x: main_usage.get(x["key"], 0), reverse=True)
        top_main = sorted_main[0]["key"] if (main_usage and main_usage.get(sorted_main[0]["key"], 0) > 0) else "1"

        for opt in sorted_main:
            cnt = main_usage.get(opt["key"], 0)
            badge = f" (Used {cnt}x) 🔥" if cnt > 0 and cnt == max(main_usage.values()) else (f" (Used {cnt}x)" if cnt > 0 else "")
            def_badge = " [Default]" if opt["key"] == top_main and main_usage.get(top_main, 0) > 0 else ""
            print(f"{opt['key']:>2}. {opt['label']}{badge}{def_badge}")

        def_prompt = f" [Default: {top_main}]" if (main_usage and main_usage.get(top_main, 0) > 0) else ""
        raw_choice = input(f"\nSelect option (1-15){def_prompt}: ").strip()
        choice = raw_choice if raw_choice else (top_main if (main_usage and main_usage.get(top_main, 0) > 0) else "")
        record_menu_usage(db_file, "main_menu", choice, next((o["label"] for o in main_options if o["key"] == choice), ""))

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
            try:
                from idrive_device_wizard import run_device_backup_wizard
                run_device_backup_wizard()
            except Exception as e:
                print(f"\n[Error] Failed to run iDrive Device Backup Wizard: {e}")
        elif choice == "14":
            try:
                from idrive_device_wizard import display_all_assigned_rules
                conn = sqlite3.connect(db_file)
                display_all_assigned_rules(conn)
                conn.close()
                input("\nPress [Enter] to return to main menu...")
            except Exception as e:
                print(f"\n[Error] Failed to display Storage Rules: {e}")
        elif choice == "15":
            print("\nExiting Storage Orchestrator. Goodbye!")
            break
        else:
            print("\n[Error] Invalid option.")

if __name__ == "__main__":
    main()