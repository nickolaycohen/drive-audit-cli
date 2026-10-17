"""
idrive_device_wizard.py — Interactive Device Backup Curation Wizard
===================================================================
Connects directly to the iDrive EVS API to inventory remote device backups,
calculates the latest backup date per device, orders devices furthest-in-the-past
first, and interactively walks the remote folder trees to establish persistent
Storage Rules in the shared SQLite database.
"""

import os
import sys
import re
import json
import sqlite3
import datetime
import requests
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple

# Add repository root and python directory to path
SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from storage_rules import (
    StorageRule,
    init_storage_rules_tables,
    save_storage_rule,
    delete_storage_rule,
    load_all_storage_rules,
    match_storage_rule,
    record_applied_rule_folder,
    get_applied_folders_for_rule,
    get_all_applied_resources,
    get_shared_db_path,
    get_tier_color
)

BASE_URL = os.environ.get("IDRIVE_EVS_URL", "https://evsweb2652.idrive.com/evs")
COOKIE_CACHE_PATHS = [
    Path.home() / ".idrive_cookie",
    REPO_ROOT / ".idrive_cookie",
    Path("/Users/nickolaycohen/dev/idrive-audit/logs/.idrive_cookie"),
    Path("/Users/nickolaycohen/dev/idrive-audit/.idrive_cookie")
]


def load_cached_cookie() -> Optional[str]:
    """Attempt to load cached iDrive session cookie from standard locations."""
    if "IDRIVE_COOKIE" in os.environ and os.environ["IDRIVE_COOKIE"].strip():
        return os.environ["IDRIVE_COOKIE"].strip()
    for cp in COOKIE_CACHE_PATHS:
        if cp.exists():
            try:
                content = cp.read_text(encoding="utf-8").strip()
                if content and ("EVSID" in content or "JSESSIONID" in content):
                    return content
            except Exception:
                pass
    return None


def save_cached_cookie(cookie_str: str):
    """Persists working cookie to cache file."""
    for cp in [COOKIE_CACHE_PATHS[0], COOKIE_CACHE_PATHS[1]]:
        try:
            cp.parent.mkdir(parents=True, exist_ok=True)
            cp.write_text(cookie_str.strip(), encoding="utf-8")
        except Exception:
            pass


def get_idrive_cookies_from_browser() -> Tuple[Optional[str], Optional[str]]:
    """
    Dynamically extracts active iDrive session cookies from local browser cache
    (Chrome, Safari, Firefox, Brave, Edge). Returns (cookie_str, target_domain).
    """
    try:
        import browser_cookie3
    except ImportError:
        return None, None

    for loader_name in ['chrome', 'safari', 'firefox', 'brave', 'edge']:
        loader = getattr(browser_cookie3, loader_name, None)
        if not loader:
            continue
        try:
            cj = loader(domain_name='idrive.com')
            by_domain = {}
            for c in cj:
                dom = getattr(c, 'domain', '').lower().lstrip('.')
                if 'idrive.com' in dom:
                    if dom not in by_domain:
                        by_domain[dom] = {}
                    if c.name in ('EVSID', 'JSESSIONID', 'WOPI_SESSION', 'CHECKINSESSION', 'SES_TOKEN'):
                        by_domain[dom][c.name] = c.value

            # Prioritize evsweb subdomains
            evs_domains = [d for d in by_domain if 'evsweb' in d]
            target_doms = evs_domains + [d for d in by_domain if d not in evs_domains]

            for dom in target_doms:
                cmap = by_domain[dom]
                if 'EVSID' in cmap or 'JSESSIONID' in cmap:
                    cookie_str = '; '.join([f'{k}={v}' for k, v in cmap.items()])
                    return cookie_str, dom
        except Exception:
            continue
    return None, None


def get_authenticated_session() -> Tuple[requests.Session, str]:
    """
    Ensures an authenticated requests.Session for iDrive EVS API.
    Attempts to read cookies directly from browser cache before prompting user.
    """
    global BASE_URL
    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
        'Accept': 'application/json, text/plain, */*'
    })

    # Try cached cookie first
    cookie_str = load_cached_cookie()

    # If no cached cookie, try reading directly from browser cache
    if not cookie_str:
        print("[*] Checking local browser cache (Chrome/Safari) for active iDrive login...")
        browser_cookie, detected_dom = get_idrive_cookies_from_browser()
        if browser_cookie:
            cookie_str = browser_cookie
            if detected_dom and "evsweb" in detected_dom:
                BASE_URL = f"https://{detected_dom}/evs"
            print(f"[✓] Automatically loaded active session from browser ({detected_dom or 'iDrive'}).")

    for attempt in range(3):
        if cookie_str:
            session.headers.update({'Cookie': cookie_str})
            try:
                r = session.post(f"{BASE_URL}/listDevices", data={'json': 'yes'}, timeout=12)
                data = r.json()
                if isinstance(data, dict) and data.get('message') == 'SUCCESS' and 'contents' in data:
                    save_cached_cookie(cookie_str)
                    return session, cookie_str
            except Exception:
                pass

        if attempt == 0:
            # If cached cookie failed, try browser refresh once
            browser_cookie, detected_dom = get_idrive_cookies_from_browser()
            if browser_cookie and browser_cookie != cookie_str:
                cookie_str = browser_cookie
                if detected_dom and "evsweb" in detected_dom:
                    BASE_URL = f"https://{detected_dom}/evs"
                print(f"[✓] Refreshed active session from browser ({detected_dom}).")
                continue

        print("\n" + "=" * 80)
        print("  🔑 IDRIVE AUTHENTICATION REQUIRED")
        print("=" * 80)
        print("  Could not automatically detect an active iDrive session in your browser.")
        print("  Please log into https://www.idrive.com in Chrome or Safari.")
        print("  Or copy your Cookie header (EVSID/JSESSIONID) from Developer Tools.")
        print("-" * 80)

        try:
            user_input = input("Paste your iDrive Cookie string (or press Enter to exit): ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nWizard cancelled.")
            sys.exit(0)

        if not user_input:
            print("\nNo credentials provided. Exiting.")
            sys.exit(0)

        cookie_str = user_input

    print("\n[Error] Unable to authenticate with iDrive EVS API. Please check your credentials.")
    sys.exit(1)


def fetch_devices(session: requests.Session) -> List[Dict[str, str]]:
    """Fetches list of all backed-up devices from EVS API, excluding system devices."""
    r = session.post(f"{BASE_URL}/listDevices", data={'json': 'yes'}, timeout=15)
    data = r.json()
    devices = []
    if isinstance(data, dict) and data.get('message') == 'SUCCESS' and 'contents' in data:
        for item in data['contents']:
            dev_id = item.get('device_id')
            nick = item.get('nick_name')
            if dev_id and nick and nick != "IDrive Photos":
                devices.append({
                    "device_id": dev_id,
                    "nick_name": nick,
                    "os_type": item.get('os_type', 'Unknown'),
                    "os_family": item.get('os_family', 'Unknown')
                })
    return devices


def browse_remote_folder(
    session: requests.Session,
    device_id: str,
    path: str = "/"
) -> List[Dict[str, Any]]:
    """Browse a folder on a specific device using EVS API."""
    norm_path = "/" + path.strip().strip("/").replace("\\", "/")
    if norm_path != "/" and norm_path.endswith("/"):
        norm_path = norm_path.rstrip("/")

    payload = {'p': norm_path, 'json': 'yes', 'device_id': device_id}
    try:
        r = session.post(f"{BASE_URL}/browseFolder", data=payload, timeout=20)
        data = r.json()
        if isinstance(data, dict) and data.get('message') == 'SUCCESS':
            return data.get('contents') or []
    except Exception as e:
        print(f"    [Warning] Failed to browse '{norm_path}' on device {device_id}: {e}")
    return []


def parse_lmd_to_datetime(lmd_str: Optional[str]) -> Optional[datetime.datetime]:
    """Parse various EVS date string representations into datetime."""
    if not lmd_str or lmd_str == "-":
        return None
    formats = [
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%m/%d/%Y %H:%M:%S",
        "%m-%d-%Y %H:%M:%S",
        "%Y-%m-%d"
    ]
    for fmt in formats:
        try:
            return datetime.datetime.strptime(lmd_str.strip(), fmt)
        except ValueError:
            pass
    # Try regex search for YYYY-MM-DD or MM/DD/YYYY
    m = re.search(r'(\d{4})-(\d{2})-(\d{2})', lmd_str)
    if m:
        try:
            return datetime.datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except Exception:
            pass
    return None


def calculate_device_latest_backup_date(
    session: requests.Session,
    device: Dict[str, Any]
) -> Tuple[Optional[datetime.datetime], str]:
    """
    Queries the top-level directory items on a device and finds the most recent
    last-modified date (lmd) among them.
    """
    dev_id = device["device_id"]
    top_items = browse_remote_folder(session, dev_id, "/")
    latest_dt = None
    latest_raw = "Unknown"

    for item in top_items:
        lmd_raw = item.get("lmd")
        dt = parse_lmd_to_datetime(lmd_raw)
        if dt:
            if latest_dt is None or dt > latest_dt:
                latest_dt = dt
                latest_raw = lmd_raw

    return latest_dt, latest_raw


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


def format_existing_rules_table(rules: List[StorageRule], conn: Optional[sqlite3.Connection] = None) -> str:
    """Formats active storage rules into a clean terminal table showing DEVICE / [folder]."""
    if not rules:
        return "  (No Storage Rules defined yet. New rules created below will be saved to the database.)"
    lines = []
    lines.append(f"  {'#':<3} | {'Rule Name':<30} | {'Destination / Action':<26} | {'Applied On (DEVICE / [folder])':<40} | {'Pattern'}")
    lines.append("  " + "-" * 125)
    for idx, r in enumerate(rules, 1):
        if r.action == "STAGE_DISCARDABLE" or "temporary" in r.category.lower():
            dest_str = "P4 🟠 (Temp Discard)"
        elif r.action in ("DISCARD_IGNORE", "PURGE_SKIP") or r.target_tier.lower() in ("discard", "purge"):
            dest_str = "🚫 DISCARD / IGNORE"
        else:
            dest_str = f"{r.target_tier.upper()} ({r.target_relative_path or '/'})"

        # Check if we have recorded applied folders
        applied_str = ""
        if conn and r.rule_id:
            applied = get_applied_folders_for_rule(conn, r.rule_id)
            if applied:
                dev, p = applied[0]
                clean_p = p if p.startswith('/') else f"/{p}"
                suffix = f" (+{len(applied)-1} more)" if len(applied) > 1 else ""
                applied_str = f"{dev} {clean_p}{suffix}"

        if not applied_str:
            dev = r.device_pattern if r.device_pattern != "ALL" else "[ALL Devices]"
            clean_p = r.path_pattern.rstrip("*") or "/"
            applied_str = f"{dev} {clean_p}"

        lines.append(f"  {idx:<3} | {r.name[:30]:<30} | {dest_str[:26]:<26} | {applied_str[:40]:<40} | {r.path_pattern}")
    return "\n".join(lines)


def display_all_assigned_rules(conn: sqlite3.Connection):
    """
    Displays a comprehensive, beautifully formatted report split into two distinct tables:
      1. TABLE 1: STORAGE RULES LEDGER (Rule policies, categories, and patterns)
      2. TABLE 2: CLASSIFIED CLOUD RESOURCES (Actual device folders where rules are applied)
    """
    rules = load_all_storage_rules(conn)
    color_icons = {"Red": "🔴", "Blue": "🔵", "Purple": "🟣", "Yellow": "🟡", "Orange": "🟠"}
    tier_counts = {"priority 1": 0, "priority 2": 0, "priority 3": 0, "priority 4": 0, "discard": 0}

    # =========================================================================
    # TABLE 1: STORAGE RULES LEDGER
    # =========================================================================
    print("\n" + "=" * 165)
    print(f"{f'TABLE 1: STORAGE RULES LEDGER ({len(rules)} Active Rules)':^165}")
    print("=" * 165)

    if not rules:
        print("\n  (No Storage Rules have been created yet. Rules will appear here as you triage folders.)\n")
    else:
        print(f"  {'#':<3} | {'Rule Name':<32} | {'Tier & Color':<22} | {'Category':<26} | {'Scope':<16} | {'Target Destination':<32} | {'Path Match Pattern'}")
        print("  " + "-" * 161)

        for idx, r in enumerate(rules, 1):
            t_key = r.target_tier.lower()
            if t_key in tier_counts:
                tier_counts[t_key] += 1
            elif "discard" in t_key or "purge" in t_key:
                tier_counts["discard"] += 1

            icon = color_icons.get(r.finder_color, "⚪")
            if r.action == "STAGE_DISCARDABLE":
                tier_disp = "P4 🟠 (Temp Discard)"
            elif r.action in ("DISCARD_IGNORE", "PURGE_SKIP") or t_key in ("discard", "purge"):
                tier_disp = "DISCARD 🚫 (Ignored)"
            else:
                tier_disp = f"{r.target_tier.upper()} {icon}"

            dest_disp = r.target_relative_path if r.target_relative_path else "(None / Ignored)"
            if dest_disp.startswith("Temporary/"):
                dest_disp = f"P4/{dest_disp}"
            if len(dest_disp) > 30:
                dest_disp = "..." + dest_disp[-27:]

            print(f"  {idx:<3} | {r.name[:32]:<32} | {tier_disp:<22} | {r.category[:26]:<26} | {r.device_pattern[:16]:<16} | {dest_disp:<32} | {r.path_pattern}")

    print("=" * 165)

    # =========================================================================
    # TABLE 2: CLASSIFIED CLOUD RESOURCES (DEVICE / [FOLDER])
    # =========================================================================
    applied_resources = get_all_applied_resources(conn)
    print("\n" + "=" * 165)
    print(f"{f'TABLE 2: CLASSIFIED CLOUD RESOURCES ({len(applied_resources)} Folders Linked to Rules)':^165}")
    print("=" * 165)

    if not applied_resources:
        print("\n  (No cloud folders have matched or been assigned to rules yet. Run the triage wizard to link folders.)\n")
    else:
        print(f"  {'#':<3} | {'Device Name':<22} | {'Remote Folder Path':<42} | {'Assigned Tier & Color':<22} | {'Matched Rule Policy':<30} | {'Local Target Destination'}")
        print("  " + "-" * 161)

        for idx, res in enumerate(applied_resources, 1):
            icon = color_icons.get(res["finder_color"], "⚪")
            tier_str = res["target_tier"].lower()
            act_str = res["action"]

            if act_str == "STAGE_DISCARDABLE":
                tier_disp = "P4 🟠 (Temp Discard)"
            elif act_str in ("DISCARD_IGNORE", "PURGE_SKIP") or tier_str in ("discard", "purge"):
                tier_disp = "DISCARD 🚫 (Ignored)"
            else:
                tier_disp = f"{res['target_tier'].upper()} {icon}"

            dest_disp = res["target_relative_path"] if res["target_relative_path"] else "(Do Not Store / Cloud Ignored)"
            if dest_disp.startswith("Temporary/"):
                dest_disp = f"/Volumes/LaCie/Storage/Priority 4/{dest_disp}"
            elif dest_disp != "(Do Not Store / Cloud Ignored)":
                dest_disp = f"/Volumes/LaCie/Storage/{res['target_tier'].title()}/{dest_disp}"

            if len(dest_disp) > 36:
                dest_disp = "..." + dest_disp[-33:]

            print(f"  {idx:<3} | {res['device_name']:<22} | {res['folder_path']:<42} | {tier_disp:<22} | {res['rule_name'][:30]:<30} | {dest_disp}")

    print("=" * 165)
    print(f"  📊 Summary: Total: {len(rules)} Rules Established across {len(applied_resources)} Classified Cloud Folders")
    print(f"     Priority 1 🔴: {tier_counts['priority 1']} | Priority 2 🔵: {tier_counts['priority 2']} | Priority 3 🟣: {tier_counts['priority 3']} | Priority 4 / Temp 🟠: {tier_counts['priority 4']} | Discarded 🚫: {tier_counts['discard']}")
    print("=" * 165)

    print("\nActions: [e] Edit/Rename Rules  |  [Enter] Return")
    act_c = input("Choice: ").strip().lower()
    if act_c == "e":
        edit_storage_rules_interactive(conn)


def edit_storage_rules_interactive(conn: sqlite3.Connection):
    """
    Interactive editor to view, rename, modify, or delete Storage Rules in SQLite.
    Allows changing rule names, priority tiers, destinations, patterns, and categories.
    """
    color_icons = {"Red": "🔴", "Blue": "🔵", "Purple": "🟣", "Yellow": "🟡", "Orange": "🟠"}

    while True:
        rules = load_all_storage_rules(conn)
        print("\n" + "=" * 135)
        print(f"{f'✏️  STORAGE RULES MANAGER & EDITOR ({len(rules)} Active Rules)':^135}")
        print("=" * 135)

        if not rules:
            print("\n  (No Storage Rules found in database. Rules are created during folder triage.)\n")
            print("=" * 135)
            return

        print(f"  {'#':<3} | {'Rule Name':<32} | {'Tier & Color':<22} | {'Scope':<16} | {'Target Destination':<32} | {'Path Match Pattern'}")
        print("  " + "-" * 131)
        for idx, r in enumerate(rules, 1):
            icon = color_icons.get(r.finder_color, "⚪")
            if r.action == "STAGE_DISCARDABLE":
                tier_disp = "P4 🟠 (Temp Discard)"
            elif r.action in ("DISCARD_IGNORE", "PURGE_SKIP") or r.target_tier.lower() in ("discard", "purge"):
                tier_disp = "DISCARD 🚫 (Ignored)"
            else:
                tier_disp = f"{r.target_tier.upper()} {icon}"

            dest_disp = r.target_relative_path if r.target_relative_path else "(None / Ignored)"
            if dest_disp.startswith("Temporary/"):
                dest_disp = f"P4/{dest_disp}"
            if len(dest_disp) > 30:
                dest_disp = "..." + dest_disp[-27:]

            print(f"  {idx:<3} | {r.name[:32]:<32} | {tier_disp:<22} | {r.device_pattern[:16]:<16} | {dest_disp:<32} | {r.path_pattern}")
        print("=" * 135)

        choice = input(f"\nSelect Rule # to edit (1-{len(rules)}) [or 'd' to delete, 'q' to return]: ").strip().lower()
        if not choice or choice in ("q", "quit", "exit"):
            break

        if choice == "d":
            del_sel = input(f"Enter Rule # to delete (1-{len(rules)}) [or 'c' to cancel]: ").strip()
            if del_sel.isdigit() and 1 <= int(del_sel) <= len(rules):
                target_rule = rules[int(del_sel) - 1]
                confirm = input(f"Are you sure you want to delete Rule #{del_sel} ('{target_rule.name}')? [y/N]: ").strip().lower()
                if confirm == "y":
                    delete_storage_rule(conn, target_rule.rule_id)
                    print(f"\n[✓] Rule #{del_sel} ('{target_rule.name}') deleted successfully.")
            continue

        if choice.isdigit() and 1 <= int(choice) <= len(rules):
            r = rules[int(choice) - 1]
            print("\n" + "=" * 90)
            print(f"  ✏️  EDITING RULE #{choice}: '{r.name}' (ID: {r.rule_id})")
            print("=" * 90)
            print("  (Press [Enter] on any field to keep its current value)")
            print("-" * 90)

            # 1. Rule Name
            new_name = input(f"  1. Rule Name [{r.name}]: ").strip() or r.name

            # 2. Category
            new_cat = input(f"  2. Category [{r.category}]: ").strip() or r.category

            # 3. Target Tier
            print(f"\n  3. Target Tier [Current: {r.target_tier.upper()}]:")
            print("     [1] Priority 1 (Active Personal, Legal, Quicken) 🔴")
            print("     [2] Priority 2 (Systems, Profiles, Legacy Windows) 🔵")
            print("     [3] Priority 3 (Historical Records, Reference Archive) 🟣")
            print("     [4] Priority 4 (Media Intake / Temporary Quarantine) 🟡/🟠")
            print("     [5] Discard / Ignore (Do not store in system) 🚫")
            print("     [Enter] Keep current")
            t_sel = input("     Select Tier (1-5) [Keep]: ").strip()

            tier_map = {
                "1": ("priority 1", "SURGICAL_RESTORE", "Red"),
                "2": ("priority 2", "SURGICAL_RESTORE", "Blue"),
                "3": ("priority 3", "ARCHIVE_COLD", "Purple"),
                "4": ("priority 4", "STAGE_DISCARDABLE" if ("discard" in r.name.lower() or "temp" in r.category.lower()) else "MEDIA_INTAKE", "Orange" if ("discard" in r.name.lower() or "temp" in r.category.lower()) else "Yellow"),
                "5": ("discard", "DISCARD_IGNORE", "Orange")
            }
            if t_sel in tier_map:
                new_tier, new_action, new_color = tier_map[t_sel]
            else:
                new_tier, new_action, new_color = r.target_tier, r.action, r.finder_color

            # 4. Target Destination Path
            new_dest = input(f"\n  4. Destination Path [{r.target_relative_path}]: ").strip()
            if new_dest:
                r.target_relative_path = new_dest

            # 5. Device Scope
            new_scope = input(f"  5. Device Scope ('ALL' or Device Name) [{r.device_pattern}]: ").strip() or r.device_pattern

            # 6. Path Match Pattern
            new_pat = input(f"  6. Path Pattern [{r.path_pattern}]: ").strip() or r.path_pattern

            # 7. Description
            new_desc = input(f"  7. Description [{r.description}]: ").strip() or r.description

            # Save updates
            r.name = new_name
            r.category = new_cat
            r.target_tier = new_tier
            r.action = new_action
            r.finder_color = new_color
            r.device_pattern = new_scope
            r.path_pattern = new_pat
            r.description = new_desc

            save_storage_rule(conn, r)
            print(f"\n[Success] ✓ Rule #{choice} successfully updated: '{r.name}' ➔ {r.target_tier.upper()}")


def prompt_user_for_storage_rule(
    device_name: str,
    folder_path: str,
    children_items: List[Dict[str, Any]],
    conn: sqlite3.Connection,
    rules: Optional[List[StorageRule]] = None
) -> Optional[StorageRule]:
    """
    Interactive prompt presenting unclassified folder details and guiding
    the user to create or customize a persistent StorageRule.
    """
    if rules is None:
        rules = load_all_storage_rules(conn)

    norm_path = "/" + folder_path.strip().strip("/").replace("\\", "/")
    folder_name = Path(norm_path).name or norm_path

    # Compute quick stats
    total_files = 0
    total_bytes = 0
    subdirs = []
    ext_counts = {}
    sample_files = []

    for item in children_items:
        is_dir = item.get('is_dir') is True or str(item.get('is_dir')).lower() in ('1', 'true')
        name = item.get('name') or item.get('p') or "unknown"
        sz = item.get('size')
        try:
            sz_int = int(sz) if sz and str(sz).isdigit() else 0
        except Exception:
            sz_int = 0

        if is_dir:
            subdirs.append(name)
        else:
            total_files += 1
            total_bytes += sz_int
            ext = Path(name).suffix.lower() or "(no ext)"
            ext_counts[ext] = ext_counts.get(ext, 0) + 1
            if len(sample_files) < 4 and not name.startswith('.'):
                sample_files.append(name)

    top_exts = ", ".join([f"{k} ({v})" for k, v in sorted(ext_counts.items(), key=lambda x: -x[1])[:5]]) or "None"
    sample_str = ", ".join(sample_files) if sample_files else "None"

    # Intelligent Auto-Suggestions based on path name and extensions
    name_l = folder_name.lower()
    path_l = norm_path.lower()

    if any(k in path_l for k in ["family", "families documents", "adoption", "passport", "legal", "scans"]):
        suggested_tier = "priority 1"
        suggested_action = "SURGICAL_RESTORE"
        suggested_category = "Vital Legal, Tax & Family Documents"
        suggested_color = "Red"
        suggested_rel_path = "Family & IDs"
        suggested_dest = "/Volumes/LaCie/Storage/Priority 1/Family & IDs/"
        suggested_impact = "Will be restored directly into high-availability Priority 1 storage"
    elif any(k in path_l for k in ["quicken", ".qdf", ".qel"]):
        suggested_tier = "priority 1"
        suggested_action = "SURGICAL_RESTORE"
        suggested_category = "Active Financial Databases (Quicken)"
        suggested_color = "Red"
        suggested_rel_path = "Data"
        suggested_dest = "/Volumes/LaCie/Storage/Priority 1/Data/"
        suggested_impact = "Will be restored directly into high-availability Priority 1 storage"
    elif any(k in path_l for k in ["ms-money", "ms money", ".mny", "legacy", "windows"]):
        suggested_tier = "priority 2"
        suggested_action = "SURGICAL_RESTORE"
        suggested_category = "Legacy Windows Data (MS Money)"
        suggested_color = "Blue"
        suggested_rel_path = "Data/Legacy/Windows/MS-Money"
        suggested_dest = "/Volumes/LaCie/Storage/Priority 2/Data/Legacy/Windows/MS-Money/"
        suggested_impact = "Will be preserved in external Priority 2 reference storage with iDrive backup"
    elif any(k in path_l for k in ["cache", "thumbs.db", "desktop.ini", "imgcache", "tmp", "trash", "temp", "logs", "crash"]) or any(k in path_l for k in ["old backup", "backup-restore", "copies from", "snapshot", "documents 0", "documents 1", "documents duplicates"]):
        suggested_tier = "priority 4"
        suggested_action = "STAGE_DISCARDABLE"
        suggested_category = "Temporary / Discardable / Old Backups"
        suggested_color = "Orange"
        suggested_rel_path = f"Temporary/Discardable/Old Backups/{{device}}/{folder_name}"
        suggested_dest = f"/Volumes/LaCie/Storage/Priority 4/Temporary/Discardable/Old Backups/{device_name}/{folder_name}/"
        suggested_impact = f"Quarantined in Priority 4 temporary staging ({device_name}/{folder_name}) — keeps active priorities clean, safe to purge later"
    elif any(k in path_l for k in ["photo", "pictures", "camera", "dcim", "videos", "media"]):
        suggested_tier = "priority 4"
        suggested_action = "MEDIA_INTAKE"
        suggested_category = "Raw Photos & Home Videos"
        suggested_color = "Yellow"
        suggested_rel_path = "Pictures/Intake"
        suggested_dest = "/Volumes/LaCie/Storage/Priority 4/Pictures/Intake/"
        suggested_impact = "Will be routed to Media Organizer Pipeline for Apple Photos curation"
    elif any(k in path_l for k in ["archive", "backup", "199", "200", "201", "old-"]):
        suggested_tier = "priority 3"
        suggested_action = "ARCHIVE_COLD"
        suggested_category = "Historical Documents & Archives (Pre-2015)"
        suggested_color = "Purple"
        suggested_rel_path = "Archives"
        suggested_dest = "/Volumes/LaCie/Storage/Priority 3/Archives/"
        suggested_impact = "Will be archived in external Priority 3 cold storage"
    else:
        suggested_tier = "priority 2"
        suggested_action = "SURGICAL_RESTORE"
        suggested_category = "Personal & Work Documents"
        suggested_color = "Blue"
        suggested_rel_path = f"Documents/{folder_name}"
        suggested_dest = f"/Volumes/LaCie/Storage/Priority 2/Documents/{folder_name}/"
        suggested_impact = "Will be restored and organized in external Priority 2 reference storage"

    color_icons = {
        "Red": "🔴",
        "Blue": "🔵",
        "Purple": "🟣",
        "Yellow": "🟡",
        "Orange": "🟠"
    }
    tier_icon = color_icons.get(suggested_color, "⚪")

    print("\n" + "=" * 120)
    print(f"  ☁️  UNCLASSIFIED FOLDER FOUND: '{folder_name}'")
    print("=" * 120)
    print(f"  • Device:                 {device_name}")
    print(f"  • Remote Path:            {norm_path}")
    print(f"  • Size / Direct Contents: {format_size_human(total_bytes)} ({total_files} files, {len(subdirs)} subfolders)")
    print(f"  • Top File Types:         {top_exts}")
    print(f"  • Sample Files:           {sample_str}")
    print("-" * 120)
    print(f"  📋 Active Storage Rules in Database ({len(rules)} established):")
    print(format_existing_rules_table(rules[:5]))
    if len(rules) > 5:
        print(f"     (... and {len(rules) - 5} more rules in database)")
    print("-" * 120)
    print("  💡 Recommended Classification & Storage Plan:")
    print(f"     • Classification:      {suggested_category}")
    print(f"     • Storage Tier:        {suggested_tier.upper()} {tier_icon}")
    print(f"     • Target Destination:  {suggested_dest}")
    print(f"     • Operational Meaning: {suggested_impact}")
    print("-" * 120)

    while True:
        print("\nSelect Action:")
        print(f"  [1] Accept Recommended Rule (Store in {suggested_tier.upper()} {tier_icon}) [Default]")
        print(f"  [2] Route to Priority 4 (Temporary - Discardable - Old Backups - {device_name} - {folder_name}) 🟠")
        print(f"  [3] Complete Ignore / Skip (Never download from cloud) 🚫")
        print(f"  [4] Custom Storage Rule (Specify tier, destination, and match pattern)")
        if rules:
            print(f"  [5] Match with an Existing Storage Rule (Pick from #1 - #{len(rules)})")
        print(f"  [6] Drill down into subfolders (Classify contents individually)")
        print(f"  [7] Skip this folder for now (Decide later)")
        print(f"  [v] View all assigned Storage Rules ({len(rules)} active rules) 📋")
        print(f"  [e] Edit / Rename existing Storage Rules ✏️")
        print(f"  [q] Save progress & Exit wizard (Restartable anytime)")

        choice = input("\nChoice (Default: 1): ").strip().lower()
        if not choice:
            choice = "1"

        if choice == "q":
            return None

        if choice == "e":
            edit_storage_rules_interactive(conn)
            rules = load_all_storage_rules(conn)
            print("\n" + "=" * 120)
            print(f"  ☁️  UNCLASSIFIED FOLDER FOUND: '{folder_name}'")
            print("=" * 120)
            print(f"  • Device:                 {device_name}")
            print(f"  • Remote Path:            {norm_path}")
            print(f"  • Size / Direct Contents: {format_size_human(total_bytes)} ({total_files} files, {len(subdirs)} subfolders)")
            print(f"  • Top File Types:         {top_exts}")
            print(f"  • Sample Files:           {sample_str}")
            print("-" * 120)
            print(f"  📋 Active Storage Rules in Database ({len(rules)} established):")
            print(format_existing_rules_table(rules[:5]))
            if len(rules) > 5:
                print(f"     (... and {len(rules) - 5} more rules in database)")
            print("-" * 120)
            print("  💡 Recommended Classification & Storage Plan:")
            print(f"     • Classification:      {suggested_category}")
            print(f"     • Storage Tier:        {suggested_tier.upper()} {tier_icon}")
            print(f"     • Target Destination:  {suggested_dest}")
            print(f"     • Operational Meaning: {suggested_impact}")
            print("-" * 120)
            continue

        if choice == "v":
            display_all_assigned_rules(conn)
            rules = load_all_storage_rules(conn)
            print("\n" + "=" * 120)
            print(f"  ☁️  UNCLASSIFIED FOLDER FOUND: '{folder_name}'")
            print("=" * 120)
            print(f"  • Device:                 {device_name}")
            print(f"  • Remote Path:            {norm_path}")
            print(f"  • Size / Direct Contents: {format_size_human(total_bytes)} ({total_files} files, {len(subdirs)} subfolders)")
            print(f"  • Top File Types:         {top_exts}")
            print(f"  • Sample Files:           {sample_str}")
            print("-" * 120)
            print(f"  📋 Active Storage Rules in Database ({len(rules)} established):")
            print(format_existing_rules_table(rules[:5]))
            if len(rules) > 5:
                print(f"     (... and {len(rules) - 5} more rules in database)")
            print("-" * 120)
            print("  💡 Recommended Classification & Storage Plan:")
            print(f"     • Classification:      {suggested_category}")
            print(f"     • Storage Tier:        {suggested_tier.upper()} {tier_icon}")
            print(f"     • Target Destination:  {suggested_dest}")
            print(f"     • Operational Meaning: {suggested_impact}")
            print("-" * 120)
            continue

        if choice == "6":
            return "DRILL"

        if choice == "7":
            return "SKIP"

        if choice == "1":
            print(f"\n--- ESTABLISH STORAGE RULE FOR '{folder_name}' ---")
            print("Select Scope:")
            print(f"  [1] Universal / Generic across ALL devices (*{folder_name}*) (Recommended) [Default]")
            print(f"  [2] Device-specific only ('{device_name}' / {folder_name} only)")
            scope_c = input("Scope [1-2] (Default: 1): ").strip()
            
            if scope_c == "2":
                r_scope = device_name
                r_pat = norm_path + "*"
                r_name = f"{device_name} - {folder_name}"
                r_rel = suggested_rel_path.replace("{device}", device_name)
            else:
                r_scope = "ALL"
                r_pat = f"*{folder_name}*"
                r_name = f"{suggested_category} ({folder_name})"
                r_rel = suggested_rel_path

            rule = StorageRule(
                name=r_name,
                device_pattern=r_scope,
                path_pattern=r_pat,
                ext_pattern="*",
                category=suggested_category,
                description=suggested_impact,
                target_tier=suggested_tier,
                target_relative_path=r_rel,
                finder_color=suggested_color,
                action=suggested_action,
                is_recursive=1
            )
            rule_id = save_storage_rule(conn, rule)
            rule.rule_id = rule_id
            record_applied_rule_folder(conn, rule_id, device_name, norm_path)
            print(f"\n[Success] ✓ Saved Generic Rule #{rule_id}: '{rule.name}' ➔ {rule.target_tier.upper()} {tier_icon} (Scope: {r_scope})")
            return rule

        if choice == "2":
            # Priority 4 Temporary Discardable Old Backups quarantine depot
            print(f"\n--- ROUTE TO PRIORITY 4 TEMPORARY DISCARDABLE ---")
            print(f"Folder: '{folder_name}' on '{device_name}'")
            print("Select Scope:")
            print(f"  [1] Universal / Generic across ALL devices (*{folder_name}*) (Recommended) [Default]")
            print(f"  [2] Device-specific only ('{device_name}' only)")
            scope_c = input("Scope [1-2] (Default: 1): ").strip()
            
            if scope_c == "2":
                r_scope = device_name
                r_pat = norm_path + "*"
                r_name = f"Temporary Discardable - {device_name} - {folder_name}"
                r_rel = f"Temporary/Discardable/Old Backups/{device_name}/{folder_name}"
            else:
                r_scope = "ALL"
                r_pat = f"*{folder_name}*"
                r_name = f"Temporary Discardable - {folder_name}"
                r_rel = f"Temporary/Discardable/Old Backups/{{device}}/{folder_name}"

            rule = StorageRule(
                name=r_name,
                device_pattern=r_scope,
                path_pattern=r_pat,
                ext_pattern="*",
                category="Temporary / Discardable / Old Backups",
                description="Universal staging rule: routes old backup folders into Priority 4 quarantine depot per device",
                target_tier="priority 4",
                target_relative_path=r_rel,
                finder_color="Orange",
                action="STAGE_DISCARDABLE",
                is_recursive=1
            )
            rule_id = save_storage_rule(conn, rule)
            rule.rule_id = rule_id
            record_applied_rule_folder(conn, rule_id, device_name, norm_path)
            resolved_dest = resolve_target_relative_path(r_rel, device_name, folder_name)
            print(f"\n[Success] 🟠 Rule #{rule_id} Created: Routed to Priority 4 (Temporary - Discardable - Old Backups) [Scope: {r_scope}]")
            print(f"  📍 Target Depot: /Volumes/LaCie/Storage/Priority 4/{resolved_dest}/")
            print(f"  ✓ Generic policy safely applies to all matching devices.")
            return rule

        if choice == "3":
            print(f"\n--- COMPLETE IGNORE / SKIP ---")
            print(f"Folder: '{norm_path}'")
            print("Select Match Scope:")
            print(f"  [1] Universal across ALL devices: '*{folder_name}*' (Recommended) [Default]")
            print(f"  [2] Device & Folder only: '{norm_path}*' on '{device_name}'")
            pat_choice = input("Scope [1-2] (Default: 1): ").strip()
            
            if pat_choice == "2":
                pat_val = norm_path + "*"
                dev_scope = device_name
                r_name = f"Ignore - {device_name} - {folder_name}"
            else:
                pat_val = f"*{folder_name}*"
                dev_scope = "ALL"
                r_name = f"Ignore - {folder_name}"

            rule = StorageRule(
                name=r_name,
                device_pattern=dev_scope,
                path_pattern=pat_val,
                ext_pattern="*",
                category="Ignored Cloud Files",
                description="Universal ignore rule — will never be downloaded from the cloud",
                target_tier="discard",
                target_relative_path="",
                finder_color="Orange",
                action="DISCARD_IGNORE",
                is_recursive=1
            )
            rule_id = save_storage_rule(conn, rule)
            rule.rule_id = rule_id
            record_applied_rule_folder(conn, rule_id, device_name, norm_path)
            print(f"\n[Success] 🚫 Rule #{rule_id} Created: Complete Ignore ({pat_val}) [Scope: {dev_scope}]")
            return rule

        if choice == "4":
            print("\n--- DEFINE CUSTOM STORAGE RULE ---")
            r_name = input(f"Rule Name [{suggested_category} - {folder_name}]: ").strip() or f"{suggested_category} - {folder_name}"
            
            p_scope = input(f"Device Scope ('ALL' or '{device_name}') [Default: ALL]: ").strip() or "ALL"
            default_pat = f"*{folder_name}*" if p_scope == "ALL" else (norm_path + "*")
            p_pat = input(f"Path Pattern [Default: {default_pat}]: ").strip() or default_pat
            
            print("\nTarget Tier:")
            print("  [1] Priority 1 (Active Personal, Legal, Quicken) 🔴")
            print("  [2] Priority 2 (Systems, Profiles, Legacy Windows) 🔵")
            print("  [3] Priority 3 (Historical Records, Reference Archive) 🟣")
            print("  [4] Priority 4 (Media Intake / Temporary Quarantine) 🟡/🟠")
            print("  [5] Complete Ignore (Never download) 🚫")
            t_choice = input("Select Tier (1-5) [Default: 2]: ").strip()
            
            tier_map = {
                "1": ("priority 1", "SURGICAL_RESTORE", "Red", f"Documents/{folder_name}"),
                "2": ("priority 2", "SURGICAL_RESTORE", "Blue", f"Documents/{folder_name}"),
                "3": ("priority 3", "ARCHIVE_COLD", "Purple", f"Archives/{folder_name}"),
                "4": ("priority 4", "STAGE_DISCARDABLE", "Orange", f"Temporary/Discardable/Old Backups/{device_name}/{folder_name}"),
                "5": ("discard", "DISCARD_IGNORE", "Orange", "")
            }
            tier_val, act_val, col_val, default_rel = tier_map.get(t_choice, ("priority 2", "SURGICAL_RESTORE", "Blue", f"Documents/{folder_name}"))

            cat_val = input(f"Category Description [{suggested_category}]: ").strip() or suggested_category
            rel_val = input(f"Relative Destination Path [{default_rel}]: ").strip() or default_rel
            desc_val = input("Human Story / Context (Optional): ").strip()
            
            rule = StorageRule(
                name=r_name,
                device_pattern=p_scope,
                path_pattern=p_pat,
                ext_pattern="*",
                category=cat_val,
                description=desc_val,
                target_tier=tier_val,
                target_relative_path=rel_val,
                finder_color=col_val,
                action=act_val,
                is_recursive=1
            )
            rule_id = save_storage_rule(conn, rule)
            rule.rule_id = rule_id
            record_applied_rule_folder(conn, rule_id, device_name, norm_path)
            print(f"\n[Success] ✓ Saved Custom Storage Rule #{rule_id}: '{rule.name}' ➔ {rule.target_tier}")
            return rule

        if choice == "5" and rules:
            print("\n--- MATCH WITH EXISTING STORAGE RULE ---")
            print(format_existing_rules_table(rules, conn=conn))
            sel = input(f"\nSelect Rule Number (1-{len(rules)}) [or 'c' to cancel]: ").strip()
            if sel.isdigit() and 1 <= int(sel) <= len(rules):
                selected_rule = rules[int(sel) - 1]
                rule = StorageRule(
                    name=f"{selected_rule.name} ({folder_name})",
                    device_pattern=device_name,
                    path_pattern=norm_path + "*",
                    ext_pattern=selected_rule.ext_pattern,
                    category=selected_rule.category,
                    description=selected_rule.description,
                    target_tier=selected_rule.target_tier,
                    target_relative_path=selected_rule.target_relative_path or folder_name,
                    finder_color=selected_rule.finder_color,
                    action=selected_rule.action,
                    is_recursive=selected_rule.is_recursive
                )
                rule_id = save_storage_rule(conn, rule)
                rule.rule_id = rule_id
                record_applied_rule_folder(conn, rule_id, device_name, norm_path)
                print(f"\n[Success] ✓ Applied Rule #{rule_id} (based on '{selected_rule.name}') ➔ {rule.target_tier}")
                return rule


def run_device_backup_wizard():
    """
    Primary orchestrator for the Device Backup Wizard.
    Connects to EVS, calculates device ages, sorts oldest-first, and interactively
    walks unclassified paths to build Storage Rules.
    """
    db_path = get_shared_db_path()
    conn = sqlite3.connect(db_path)
    init_storage_rules_tables(conn)

    print("\n" + "=" * 80)
    print("  🚀 IDRIVE CLOUD DEVICE BACKUP WIZARD")
    print("=" * 80)
    print(f"  • Knowledge Hub Database: {db_path}")
    print("  • Connecting to iDrive EVS Cloud Backend...")
    print("-" * 80)

    session, _ = get_authenticated_session()
    print("[✓] Authenticated successfully with iDrive EVS API.")

    print("\nDiscovering registered cloud devices...")
    devices = fetch_devices(session)
    if not devices:
        print("[!] No devices found in this iDrive account.")
        return

    print(f"Found {len(devices)} device backups in account. Calculating latest update dates...")

    # Step 1: Build complete storage summary catalog (utilizing idrive_audit.db cache when available)
    idrive_db_path = "/Users/nickolaycohen/dev/idrive-audit/idrive_audit.db"
    cached_info = {}
    if os.path.exists(idrive_db_path):
        try:
            idb_conn = sqlite3.connect(idrive_db_path)
            idb_conn.row_factory = sqlite3.Row
            idb_cur = idb_conn.cursor()
            for dev in devices:
                dev_id = dev["device_id"]
                idb_cur.execute(
                    "SELECT path, lmd FROM api_calls WHERE device_id = ? AND lmd IS NOT NULL AND lmd != '' AND lmd != '-' ORDER BY lmd DESC LIMIT 1",
                    (dev_id,)
                )
                lr = idb_cur.fetchone()
                lmd_val = lr["lmd"] if lr else ""
                lmd_p = lr["path"] if lr else ""

                idb_cur.execute(
                    "SELECT SUM(size) as total_sz FROM api_calls WHERE device_id = ? AND endpoint = 'getProperties'",
                    (dev_id,)
                )
                sr = idb_cur.fetchone()
                tot_sz = sr["total_sz"] if sr and sr["total_sz"] else 0

                idb_cur.execute(
                    "SELECT MAX(timestamp) as max_ts FROM api_calls WHERE device_id = ?",
                    (dev_id,)
                )
                tr = idb_cur.fetchone()
                max_ts = tr["max_ts"] if tr and tr["max_ts"] else ""

                cached_info[dev_id] = {
                    "lmd": lmd_val,
                    "lmd_path": lmd_p,
                    "size_bytes": tot_sz,
                    "last_scan": max_ts.replace("T", " ")[:16] if max_ts else "[never]"
                }
            idb_conn.close()
        except Exception:
            pass

    device_catalog = []
    for dev in devices:
        dev_id = dev["device_id"]
        c_data = cached_info.get(dev_id, {})
        lmd_str = c_data.get("lmd")
        lmd_path = c_data.get("lmd_path", "")
        size_bytes = c_data.get("size_bytes", 0)
        last_scan = c_data.get("last_scan", "[never]")

        # If not cached or unknown, check live EVS
        if not lmd_str or lmd_str == "Unknown":
            dt_live, raw_live = calculate_device_latest_backup_date(session, dev)
            if dt_live:
                lmd_str = dt_live.isoformat()
                lmd_path = "/"

        dt = parse_lmd_to_datetime(lmd_str)
        dev["latest_dt"] = dt
        dev["latest_lmd"] = lmd_str or "Unknown"
        dev["lmd_path"] = lmd_path
        dev["size_gb"] = size_bytes / (1024 ** 3)
        dev["last_scan"] = last_scan
        dev["status_str"] = "Active"
        device_catalog.append(dev)

    # Step 2: Sort devices for the summary table (Inverted: most recent updates at top down to oldest updates at bottom)
    epoch_past = datetime.datetime(1970, 1, 1)
    device_catalog.sort(key=lambda d: d["latest_dt"] if d["latest_dt"] else epoch_past, reverse=True)

    # Print standard IDRIVE STORAGE SUMMARY table
    print("\n" + "=" * 155)
    print(f"{'IDRIVE STORAGE SUMMARY (Recent → Oldest)':^155}")
    print("=" * 155)
    print(f"{'No.':<4} | {'Device Name':<22} | {'Scanned Size':>12} | {'Last Scanned':<16} | {'Status':<8} | {'Last Modified (Folder)':<50} | {'Device ID':<22}")
    print("-" * 155)

    total_account_gb = 0.0
    for idx, d in enumerate(device_catalog, 1):
        total_account_gb += d["size_gb"]
        l_display = f"{d['latest_lmd'][:19]} ({d['lmd_path'][-25:]})" if d["lmd_path"] else d["latest_lmd"][:19]
        print(f"{idx:<4} | {d['nick_name']:<22} | {d['size_gb']:>9.2f} GB | {d['last_scan']:<16} | {d['status_str']:<8} | {l_display:<50} | {d['device_id']:<22}")

    print("-" * 155)
    print(f"TOTAL ACCOUNT STORAGE: {total_account_gb:.2f} GB Across {len(device_catalog)} Devices")
    print("=" * 155)

    rules = load_all_storage_rules(conn)
    print(f"\n[✓] Loaded {len(rules)} persistent Storage Rules from {db_path}")

    # Triage Queue: Walk devices starting with the OLDEST modified device first!
    triage_catalog = sorted(
        [d for d in device_catalog if d["nick_name"] not in ("Y",)],
        key=lambda d: d["latest_dt"] if d["latest_dt"] else epoch_past
    )
    if not triage_catalog:
        triage_catalog = list(reversed(device_catalog))

    target_dev = triage_catalog[0]
    target_date_str = target_dev["latest_dt"].strftime("%Y-%m-%d") if target_dev["latest_dt"] else "Legacy"
    print("\n" + "=" * 155)
    print(f"  🎯 TARGETING OLDEST MODIFIED DEVICE FIRST: '{target_dev['nick_name']}' (Last Modified: {target_date_str})")
    print("=" * 155)

    # Step 3: Walk devices and folders automatically without pause
    total_classified = 0
    total_skipped = 0

    for dev_idx, dev in enumerate(triage_catalog, 1):
        dev_name = dev["nick_name"]
        dev_id = dev["device_id"]
        dev_date = dev["latest_dt"].strftime("%Y-%m-%d") if dev["latest_dt"] else "Legacy"

        print("\n" + "#" * 80)
        print(f"  DEVICE [{dev_idx}/{len(triage_catalog)}]: '{dev_name}' (Last Backup: {dev_date})")
        print("#" * 80)

        # Queue of paths to inspect: starts with top-level items
        queue = ["/"]

        while queue:
            current_path = queue.pop(0)

            # Skip checking root "/" for rule matching; browse it directly
            if current_path == "/":
                top_items = browse_remote_folder(session, dev_id, "/")
                for item in top_items:
                    is_dir = item.get('is_dir') is True or str(item.get('is_dir')).lower() in ('1', 'true')
                    name = item.get('name') or item.get('p')
                    if is_dir and name:
                        queue.append("/" + name.strip("/"))
                continue

            # Check if this folder matches an existing storage rule
            matched_rule = match_storage_rule(dev_name, current_path, rules=rules)
            if matched_rule:
                record_applied_rule_folder(conn, matched_rule.rule_id, dev_name, current_path)
                if matched_rule.action == "STAGE_DISCARDABLE":
                    print(f"  [🟠 Temp Discardable] '{current_path}' (Rule: '{matched_rule.name}')")
                elif matched_rule.action in ("DISCARD_IGNORE", "PURGE_SKIP") or matched_rule.target_tier.lower() in ("discard", "purge"):
                    print(f"  [🚫 Discarded / Ignored] '{current_path}' (Rule: '{matched_rule.name}')")
                else:
                    print(f"  [✓ Rule Matched] '{current_path}' ➔ '{matched_rule.name}' ({matched_rule.target_tier.upper()})")
                total_classified += 1
                # If recursive rule covers everything underneath, skip enqueuing children
                if matched_rule.is_recursive:
                    continue

            # Fetch folder children to evaluate or prompt
            children = browse_remote_folder(session, dev_id, current_path)
            
            # If no rule matched, trigger interactive prompt
            if not matched_rule:
                action_res = prompt_user_for_storage_rule(dev_name, current_path, children, conn, rules=rules)
                
                if action_res is None:
                    print("\n[Paused] Wizard progress saved to database. Run anytime to resume.")
                    conn.close()
                    return
                elif action_res == "SKIP":
                    total_skipped += 1
                    continue
                elif action_res == "DRILL":
                    # Add child directories to front of queue
                    for item in children:
                        is_dir = item.get('is_dir') is True or str(item.get('is_dir')).lower() in ('1', 'true')
                        name = item.get('name') or item.get('p')
                        if is_dir and name:
                            queue.insert(0, current_path.rstrip("/") + "/" + name.strip("/"))
                    continue
                elif isinstance(action_res, StorageRule):
                    rules = load_all_storage_rules(conn)
                    total_classified += 1
                    # If user chose recursive rule, don't drill deeper
                    if action_res.is_recursive:
                        continue

            # Enqueue any subdirectories if we didn't prune
            for item in children:
                is_dir = item.get('is_dir') is True or str(item.get('is_dir')).lower() in ('1', 'true')
                name = item.get('name') or item.get('p')
                if is_dir and name:
                    queue.append(current_path.rstrip("/") + "/" + name.strip("/"))

    print("\n" + "=" * 80)
    print("  🎉 ALL REGISTERED DEVICES TRIAGED & CLASSIFIED!")
    print("=" * 80)
    print(f"  • Total Folders Classified: {total_classified}")
    print(f"  • Total Folders Skipped:    {total_skipped}")
    print(f"  • Total Storage Rules:      {len(load_all_storage_rules(conn))}")
    print("=" * 80)
    conn.close()


if __name__ == "__main__":
    if any(arg in sys.argv for arg in ("--rules", "-v", "rules", "--list-rules", "--edit", "-e", "edit")):
        conn = sqlite3.connect(get_shared_db_path())
        init_storage_rules_tables(conn)
        if any(arg in sys.argv for arg in ("--edit", "-e", "edit")):
            edit_storage_rules_interactive(conn)
        else:
            display_all_assigned_rules(conn)
        conn.close()
        sys.exit(0)

    try:
        run_device_backup_wizard()
    except KeyboardInterrupt:
        print("\n\n[Interrupted] Device Backup Wizard paused cleanly. Run again to resume.")
        sys.exit(0)
