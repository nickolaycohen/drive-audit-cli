"""
storage_rules.py — Shared Storage Rules & Device Traversal Registry
===================================================================
Provides a shared, persistent knowledge base for classifying filesystem
structures into semantic categories ("What") and target storage tiers ("Where").
Used jointly across:
  - Pillar 1: idrive-audit (Cloud Discovery & Selective Ingestion)
  - Pillar 2: drive-audit-cli (Local Storage Orchestrator & Curation)
  - Pillar 3: media-organizer-pipeline (Media Intake Classifier)
"""

import os
import re
import fnmatch
import sqlite3
import datetime
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import Optional, List, Dict, Any, Tuple

DEFAULT_DB_PATH = "/Volumes/Extreme Pro/Data/sqlite/drive-audit/drive_audit.db"

def get_shared_db_path() -> str:
    """Return central SQLite DB path, falling back to local fallback if unmounted."""
    if os.path.exists(DEFAULT_DB_PATH):
        return DEFAULT_DB_PATH
    # Fallback to local dev path
    candidate = Path(__file__).resolve().parent.parent / "db" / "drive_audit.db"
    if candidate.exists():
        return str(candidate)
    return DEFAULT_DB_PATH


@dataclass
class StorageRule:
    name: str
    path_pattern: str
    target_tier: str                      # 'priority 1', 'priority 2', 'priority 3', 'priority 4', 'purge'
    action: str                           # 'SURGICAL_RESTORE', 'ARCHIVE_COLD', 'PURGE_SKIP', 'MEDIA_INTAKE'
    category: str = "Uncategorized"
    description: str = ""
    app_needed: str = ""
    tags: str = ""
    device_pattern: str = "ALL"           # 'ALL' or specific device name/pattern
    ext_pattern: str = "*"                # '*' or comma-separated list like '.qdf,.qel'
    target_relative_path: str = ""
    finder_color: str = "Gray"
    is_recursive: int = 1                 # 1 = applies to all child paths unless overridden
    rule_id: Optional[int] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


def init_storage_rules_tables(conn: sqlite3.Connection):
    """Initializes storage_rules and device_crawl_progress tables if not present."""
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS storage_rules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            device_pattern TEXT NOT NULL DEFAULT 'ALL',
            path_pattern TEXT NOT NULL,
            ext_pattern TEXT NOT NULL DEFAULT '*',
            category TEXT NOT NULL DEFAULT 'General',
            description TEXT,
            app_needed TEXT,
            tags TEXT,
            target_tier TEXT NOT NULL DEFAULT 'priority 2',
            target_relative_path TEXT,
            finder_color TEXT DEFAULT 'Gray',
            action TEXT NOT NULL DEFAULT 'SURGICAL_RESTORE',
            is_recursive INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS device_crawl_progress (
            device_id TEXT PRIMARY KEY,
            device_name TEXT NOT NULL,
            latest_lmd TEXT,
            status TEXT NOT NULL DEFAULT 'pending', -- 'pending', 'in_progress', 'completed', 'skipped'
            last_path TEXT,
            classified_folders INTEGER DEFAULT 0,
            skipped_folders INTEGER DEFAULT 0,
            total_files INTEGER DEFAULT 0,
            classified_files INTEGER DEFAULT 0,
            skipped_files INTEGER DEFAULT 0,
            total_folders INTEGER DEFAULT 0,
            updated_at TEXT NOT NULL
        )
    """)

    # Ensure columns exist in existing device_crawl_progress table
    cur.execute("PRAGMA table_info(device_crawl_progress)")
    existing_cols = {r[1] for r in cur.fetchall()}
    for col_name, col_type in [
        ("total_files", "INTEGER DEFAULT 0"),
        ("classified_files", "INTEGER DEFAULT 0"),
        ("skipped_files", "INTEGER DEFAULT 0"),
        ("total_folders", "INTEGER DEFAULT 0")
    ]:
        if col_name not in existing_cols:
            try:
                cur.execute(f"ALTER TABLE device_crawl_progress ADD COLUMN {col_name} {col_type}")
            except Exception:
                pass

    cur.execute("""
        CREATE TABLE IF NOT EXISTS applied_rule_folders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            rule_id INTEGER NOT NULL,
            device_name TEXT NOT NULL,
            folder_path TEXT NOT NULL,
            applied_at TEXT NOT NULL,
            UNIQUE(rule_id, device_name, folder_path)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS ingestion_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ingestion_id TEXT UNIQUE NOT NULL,
            device_name TEXT NOT NULL,
            source_path TEXT NOT NULL,
            rule_id INTEGER,
            target_tier TEXT NOT NULL,
            target_folder TEXT NOT NULL,
            local_destination TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            total_files INTEGER DEFAULT 0,
            total_bytes INTEGER DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (rule_id) REFERENCES storage_rules(id)
        )
    """)

    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_storage_rules_path ON storage_rules(path_pattern);
    """)
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_storage_rules_device ON storage_rules(device_pattern);
    """)
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_applied_rule_id ON applied_rule_folders(rule_id);
    """)
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_ingestion_device_path ON ingestion_records(device_name, source_path);
    """)
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_ingestion_id ON ingestion_records(ingestion_id);
    """)
    # Ensure local_destination in ingestion_records does not have ingestion_id automatically appended
    try:
        cur.execute("""
            UPDATE ingestion_records 
            SET local_destination = SUBSTR(local_destination, 1, INSTR(local_destination, '/' || ingestion_id) - 1)
            WHERE local_destination LIKE '%/' || ingestion_id
        """)
        conn.commit()
    except Exception:
        pass

    conn.commit()


def get_or_create_ingestion_record(
    conn: sqlite3.Connection,
    device_name: str,
    source_path: str,
    rule_id: Optional[int] = None,
    target_tier: str = "priority 2",
    target_folder: str = "Documents",
    status: str = "pending",
    total_files: int = 0,
    total_bytes: int = 0
) -> Dict[str, Any]:
    """
    Fetches or registers an ingestion record with a unique Ingestion ID (e.g. ING-0001).
    Assigns the clean Local Target Destination (e.g. /Volumes/LaCie/Storage/Priority 2/Documents)
    without appending the Ingestion ID, leaving merge and conflict resolution to the Storage Manager.
    """
    cur = conn.cursor()
    norm_source = "/" + source_path.strip().strip("/").replace("\\", "/")
    cur.execute("""
        SELECT id, ingestion_id, device_name, source_path, rule_id, target_tier, 
               target_folder, local_destination, status, total_files, total_bytes, created_at, updated_at
        FROM ingestion_records
        WHERE device_name = ? AND source_path = ?
    """, (device_name, norm_source))
    row = cur.fetchone()
    now_str = datetime.datetime.now().isoformat()

    if row:
        rec_id, ing_id = row[0], row[1]
        if target_tier.lower() in ("discard", "purge") or status == "ignored":
            local_dest = "(Do Not Store / Cloud Ignored)"
        else:
            clean_folder = target_folder.strip("/").split("/")[0] if target_folder else "Documents"
            local_dest = f"/Volumes/LaCie/Storage/{target_tier.title()}/{clean_folder}"
        
        cur.execute("""
            UPDATE ingestion_records
            SET rule_id = ?, target_tier = ?, target_folder = ?, local_destination = ?, status = ?,
                total_files = CASE WHEN ? > 0 THEN ? ELSE total_files END,
                total_bytes = CASE WHEN ? > 0 THEN ? ELSE total_bytes END,
                updated_at = ?
            WHERE id = ?
        """, (rule_id, target_tier, target_folder, local_dest, status, total_files, total_files, total_bytes, total_bytes, now_str, rec_id))
        conn.commit()
        return {
            "id": rec_id,
            "ingestion_id": ing_id,
            "device_name": device_name,
            "source_path": norm_source,
            "rule_id": rule_id,
            "target_tier": target_tier,
            "target_folder": target_folder,
            "local_destination": local_dest,
            "status": status,
            "total_files": total_files or row[9],
            "total_bytes": total_bytes or row[10]
        }

    # Generate next sequential Ingestion ID
    cur.execute("SELECT MAX(id) FROM ingestion_records")
    max_val = cur.fetchone()[0] or 0
    ing_id = f"ING-{max_val + 1:04d}"

    if target_tier.lower() in ("discard", "purge") or status == "ignored":
        local_dest = "(Do Not Store / Cloud Ignored)"
    else:
        clean_folder = target_folder.strip("/").split("/")[0] if target_folder else "Documents"
        local_dest = f"/Volumes/LaCie/Storage/{target_tier.title()}/{clean_folder}"

    cur.execute("""
        INSERT INTO ingestion_records 
        (ingestion_id, device_name, source_path, rule_id, target_tier, target_folder, local_destination, status, total_files, total_bytes, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (ing_id, device_name, norm_source, rule_id, target_tier, target_folder, local_dest, status, total_files, total_bytes, now_str, now_str))
    conn.commit()
    new_id = cur.lastrowid
    return {
        "id": new_id,
        "ingestion_id": ing_id,
        "device_name": device_name,
        "source_path": norm_source,
        "rule_id": rule_id,
        "target_tier": target_tier,
        "target_folder": target_folder,
        "local_destination": local_dest,
        "status": status,
        "total_files": total_files,
        "total_bytes": total_bytes
    }


def get_all_ingestion_records(conn: sqlite3.Connection) -> List[Dict[str, Any]]:
    """Returns all ingestion records joined with their storage rules."""
    cur = conn.cursor()
    cur.execute("""
        SELECT i.id, i.ingestion_id, i.device_name, i.source_path, i.target_tier, 
               r.finder_color, r.name as rule_name, i.local_destination, i.status,
               i.total_files, i.total_bytes, i.created_at, i.target_folder
        FROM ingestion_records i
        LEFT JOIN storage_rules r ON i.rule_id = r.id
        ORDER BY i.id ASC
    """)
    rows = cur.fetchall()
    res = []
    for r in rows:
        res.append({
            "id": r[0],
            "ingestion_id": r[1],
            "device_name": r[2],
            "source_path": r[3],
            "target_tier": r[4],
            "finder_color": r[5] or "Gray",
            "rule_name": r[6] or "Manual Classification",
            "local_destination": r[7],
            "status": r[8],
            "total_files": r[9],
            "total_bytes": r[10],
            "created_at": r[11],
            "target_folder": r[12]
        })
    return res


def record_applied_rule_folder(conn: sqlite3.Connection, rule_id: int, device_name: str, folder_path: str) -> None:
    """Records that a rule was applied to a specific device/folder."""
    if not rule_id:
        return
    now_str = datetime.datetime.now().isoformat()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO applied_rule_folders (rule_id, device_name, folder_path, applied_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(rule_id, device_name, folder_path) DO UPDATE SET applied_at = excluded.applied_at
    """, (rule_id, device_name, folder_path, now_str))
    conn.commit()


def format_size_human(size_val: Any) -> str:
    """Format bytes into human-readable string."""
    try:
        b = float(size_val)
        if b <= 0:
            return "0 B"
        for unit in ["B", "KB", "MB", "GB", "TB"]:
            if b < 1024.0:
                return f"{b:.1f} {unit}"
            b /= 1024.0
        return f"{b:.1f} PB"
    except Exception:
        return str(size_val or "0 B")


def render_progress_bar(completed: int, total: int, width: int = 20) -> str:
    """Returns a visual unicode progress bar [██████░░░░] 60%."""
    if total <= 0:
        return f"[{'░' * width}] 0%"
    pct = min(1.0, max(0.0, completed / total))
    filled = int(round(width * pct))
    bar = "█" * filled + "░" * (width - filled)
    return f"[{bar}] {int(pct * 100)}%"


def update_device_crawl_progress(
    conn: sqlite3.Connection,
    device_id: str,
    device_name: str,
    latest_lmd: str = "",
    status: str = "in_progress",
    last_path: str = "",
    classified_folders: int = 0,
    skipped_folders: int = 0,
    total_files: int = 0,
    classified_files: int = 0,
    skipped_files: int = 0,
    total_folders: int = 0
) -> None:
    """Updates or inserts the crawl progress for a specific device with file and folder counts."""
    now_str = datetime.datetime.now().isoformat()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO device_crawl_progress (
            device_id, device_name, latest_lmd, status, last_path, 
            classified_folders, skipped_folders, total_files, classified_files, skipped_files, total_folders, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(device_id) DO UPDATE SET
            device_name = excluded.device_name,
            latest_lmd = COALESCE(NULLIF(excluded.latest_lmd, ''), device_crawl_progress.latest_lmd),
            status = excluded.status,
            last_path = excluded.last_path,
            classified_folders = excluded.classified_folders,
            skipped_folders = excluded.skipped_folders,
            total_files = CASE WHEN excluded.total_files > 0 THEN excluded.total_files ELSE device_crawl_progress.total_files END,
            classified_files = excluded.classified_files,
            skipped_files = excluded.skipped_files,
            total_folders = CASE WHEN excluded.total_folders > 0 THEN excluded.total_folders ELSE device_crawl_progress.total_folders END,
            updated_at = excluded.updated_at
    """, (device_id, device_name, latest_lmd, status, last_path, classified_folders, skipped_folders, total_files, classified_files, skipped_files, total_folders, now_str))
    conn.commit()


def get_device_crawl_progress(conn: sqlite3.Connection, device_id: str) -> Optional[Dict[str, Any]]:
    """Fetches the crawl progress record for a specific device."""
    cur = conn.cursor()
    cur.execute("""
        SELECT device_id, device_name, latest_lmd, status, last_path, 
               classified_folders, skipped_folders, total_files, classified_files, skipped_files, total_folders, updated_at
        FROM device_crawl_progress
        WHERE device_id = ?
    """, (device_id,))
    row = cur.fetchone()
    if not row:
        return None
    return {
        "device_id": row[0],
        "device_name": row[1],
        "latest_lmd": row[2],
        "status": row[3],
        "last_path": row[4],
        "classified_folders": row[5],
        "skipped_folders": row[6],
        "total_files": row[7] if len(row) > 7 and row[7] is not None else 0,
        "classified_files": row[8] if len(row) > 8 and row[8] is not None else 0,
        "skipped_files": row[9] if len(row) > 9 and row[9] is not None else 0,
        "total_folders": row[10] if len(row) > 10 and row[10] is not None else 0,
        "updated_at": row[11] if len(row) > 11 else ""
    }


def get_all_device_crawl_progress(conn: sqlite3.Connection) -> Dict[str, Dict[str, Any]]:
    """Returns a map of device_id -> progress record for all tracked devices."""
    cur = conn.cursor()
    cur.execute("""
        SELECT device_id, device_name, latest_lmd, status, last_path, 
               classified_folders, skipped_folders, total_files, classified_files, skipped_files, total_folders, updated_at
        FROM device_crawl_progress
    """)
    res = {}
    for row in cur.fetchall():
        res[row[0]] = {
            "device_id": row[0],
            "device_name": row[1],
            "latest_lmd": row[2],
            "status": row[3],
            "last_path": row[4],
            "classified_folders": row[5],
            "skipped_folders": row[6],
            "total_files": row[7] if len(row) > 7 and row[7] is not None else 0,
            "classified_files": row[8] if len(row) > 8 and row[8] is not None else 0,
            "skipped_files": row[9] if len(row) > 9 and row[9] is not None else 0,
            "total_folders": row[10] if len(row) > 10 and row[10] is not None else 0,
            "updated_at": row[11] if len(row) > 11 else ""
        }
    return res


def get_applied_folders_for_rule(conn: sqlite3.Connection, rule_id: int) -> List[Tuple[str, str]]:
    """Returns list of (device_name, folder_path) tuples where this rule has been applied."""
    cur = conn.cursor()
    cur.execute("""
        SELECT device_name, folder_path FROM applied_rule_folders
        WHERE rule_id = ?
        ORDER BY device_name, folder_path
    """, (rule_id,))
    return [(r[0], r[1]) for r in cur.fetchall()]


def resolve_target_relative_path(template: str, device_name: str, folder_name: str = "") -> str:
    """Resolves dynamic placeholders {device} and {folder} in target destination paths."""
    if not template:
        return ""
    res = template.replace("{device}", device_name)
    if folder_name:
        res = res.replace("{folder}", folder_name)
    return res


def get_all_applied_resources(conn: sqlite3.Connection) -> List[Dict[str, Any]]:
    """Fetches all classified cloud resources joined with their matched storage rules."""
    cur = conn.cursor()
    cur.execute("""
        SELECT a.id, a.device_name, a.folder_path, a.applied_at, 
               r.id as rule_id, r.name as rule_name, r.target_tier, 
               r.finder_color, r.target_relative_path, r.action, r.category
        FROM applied_rule_folders a
        JOIN storage_rules r ON a.rule_id = r.id
        ORDER BY a.device_name, a.folder_path
    """)
    rows = cur.fetchall()
    res = []
    for row in rows:
        dev_name = row[1]
        folder_p = row[2]
        f_name = Path(folder_p).name or folder_p
        raw_target = row[8] or ""
        resolved_target = resolve_target_relative_path(raw_target, dev_name, f_name)

        res.append({
            "id": row[0],
            "device_name": dev_name,
            "folder_path": folder_p,
            "applied_at": row[3],
            "rule_id": row[4],
            "rule_name": row[5],
            "target_tier": row[6],
            "finder_color": row[7],
            "target_relative_path": resolved_target,
            "raw_template": raw_target,
            "action": row[9],
            "category": row[10]
        })
    return res


def save_storage_rule(conn: sqlite3.Connection, rule: StorageRule) -> int:
    """Inserts or updates a StorageRule in SQLite."""
    now = datetime.datetime.now().isoformat()
    cur = conn.cursor()
    if rule.rule_id:
        cur.execute("""
            UPDATE storage_rules
            SET name = ?, device_pattern = ?, path_pattern = ?, ext_pattern = ?,
                category = ?, description = ?, app_needed = ?, tags = ?,
                target_tier = ?, target_relative_path = ?, finder_color = ?,
                action = ?, is_recursive = ?, updated_at = ?
            WHERE id = ?
        """, (
            rule.name, rule.device_pattern, rule.path_pattern, rule.ext_pattern,
            rule.category, rule.description, rule.app_needed, rule.tags,
            rule.target_tier, rule.target_relative_path, rule.finder_color,
            rule.action, rule.is_recursive, now, rule.rule_id
        ))
        conn.commit()
        return rule.rule_id
    else:
        cur.execute("""
            INSERT INTO storage_rules (
                name, device_pattern, path_pattern, ext_pattern,
                category, description, app_needed, tags,
                target_tier, target_relative_path, finder_color,
                action, is_recursive, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            rule.name, rule.device_pattern, rule.path_pattern, rule.ext_pattern,
            rule.category, rule.description, rule.app_needed, rule.tags,
            rule.target_tier, rule.target_relative_path, rule.finder_color,
            rule.action, rule.is_recursive, now, now
        ))
        conn.commit()
        return cur.lastrowid


def delete_storage_rule(conn: sqlite3.Connection, rule_id: int) -> bool:
    """Deletes a StorageRule and its applied folder records from SQLite."""
    cur = conn.cursor()
    cur.execute("DELETE FROM applied_rule_folders WHERE rule_id = ?", (rule_id,))
    cur.execute("DELETE FROM storage_rules WHERE id = ?", (rule_id,))
    conn.commit()
    return cur.rowcount > 0


def load_all_storage_rules(conn: sqlite3.Connection) -> List[StorageRule]:
    """Loads all active storage rules from SQLite ordered by specificity."""
    cur = conn.cursor()
    cur.execute("""
        SELECT id, name, device_pattern, path_pattern, ext_pattern,
               category, description, app_needed, tags,
               target_tier, target_relative_path, finder_color,
               action, is_recursive, created_at, updated_at
        FROM storage_rules
        ORDER BY
            CASE WHEN device_pattern != 'ALL' THEN 0 ELSE 1 END,
            LENGTH(path_pattern) DESC,
            id ASC
    """)
    rules = []
    for r in cur.fetchall():
        rules.append(StorageRule(
            rule_id=r[0],
            name=r[1],
            device_pattern=r[2],
            path_pattern=r[3],
            ext_pattern=r[4],
            category=r[5],
            description=r[6] or "",
            app_needed=r[7] or "",
            tags=r[8] or "",
            target_tier=r[9],
            target_relative_path=r[10] or "",
            finder_color=r[11] or "Gray",
            action=r[12],
            is_recursive=r[13],
            created_at=r[14],
            updated_at=r[15]
        ))
    return rules


def match_storage_rule(
    device_name: str,
    path: str,
    ext: Optional[str] = None,
    rules: Optional[List[StorageRule]] = None,
    conn: Optional[sqlite3.Connection] = None
) -> Optional[StorageRule]:
    """
    Evaluates whether a given device and path matches any defined StorageRule.
    Supports wildcards (*, ?), regex, and case-insensitive matching.
    """
    if rules is None:
        if conn is None:
            raise ValueError("Either rules list or database conn must be supplied.")
        rules = load_all_storage_rules(conn)

    norm_path = "/" + path.strip().strip("/").replace("\\", "/")
    norm_path_lower = norm_path.lower()
    dev_lower = device_name.strip().lower()

    for rule in rules:
        # Check device pattern
        if rule.device_pattern != "ALL":
            if not fnmatch.fnmatch(dev_lower, rule.device_pattern.strip().lower()):
                continue

        # Check path pattern (case-insensitive)
        pat = rule.path_pattern.strip()
        pat_lower = pat.lower()

        matched = False
        # If pattern starts with regex flag 'regex:'
        if pat_lower.startswith("regex:"):
            try:
                rx = re.compile(pat[6:], re.IGNORECASE)
                if rx.search(norm_path):
                    matched = True
            except re.error:
                pass
        else:
            # Standard glob / wildcard matching
            # Ensure pattern has wildcards if simple substring is intended
            if not any(c in pat for c in ("*", "?", "[")):
                # If substring
                matched = pat_lower in norm_path_lower
            else:
                matched = fnmatch.fnmatch(norm_path_lower, pat_lower) or fnmatch.fnmatch(norm_path_lower, f"*{pat_lower}*")

        if not matched and rule.is_recursive:
            # Check if norm_path is a descendant of a matching directory
            if not pat_lower.endswith("*"):
                dir_pat = pat_lower.rstrip("/") + "/*"
                matched = fnmatch.fnmatch(norm_path_lower, dir_pat)

        if not matched:
            continue

        # Check extension filter if supplied
        if ext and rule.ext_pattern and rule.ext_pattern != "*":
            allowed_exts = [e.strip().lower() for e in rule.ext_pattern.split(",") if e.strip()]
            ext_clean = ("." + ext.lstrip(".")).lower()
            if ext_clean not in allowed_exts:
                continue

        return rule

    return None


def get_tier_color(tier: str, action: str = "") -> str:
    """Returns standard macOS Finder tag color for each Priority tier."""
    t = tier.lower().strip()
    a = action.lower().strip()
    if "priority 1" in t or t == "p1":
        return "Red"
    elif "priority 2" in t or t == "p2":
        return "Blue"
    elif "priority 3" in t or t == "p3":
        return "Purple"
    elif any(k in t for k in ["discard", "temporary", "temp", "purge", "skip", "trash"]) or "stage_discardable" in a or "discard" in a:
        return "Orange"
    elif "priority 4" in t or t == "p4":
        return "Yellow"
    return "Gray"
