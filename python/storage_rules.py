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
            updated_at TEXT NOT NULL
        )
    """)

    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_storage_rules_path ON storage_rules(path_pattern);
    """)
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_storage_rules_device ON storage_rules(device_pattern);
    """)
    conn.commit()


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
