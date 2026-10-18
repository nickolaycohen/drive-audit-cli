#!/usr/bin/env python3
"""
storage_manager_merge.py — Storage Manager Folder Merging & Conflict Resolution Engine

Handles merging of incoming/ingested cloud backup folders into local target destinations.
If the destination already contains a folder with the same name:
  • Merges cleanly if filenames are unique (no overlap/collision).
  • Skips and deduplicates identical files (zero storage bloat).
  • Resolves name collisions with differing contents according to configurable policies:
      - Separate Location / Conflict Repository (Default): keeps conflicting files in a dedicated quarantine folder.
      - New Partitioned Folder: creates a separate suffixed folder alongside the destination.
      - Suffix In-Place: appends device / provenance suffix to the filename.
  • Provides human-readable, easily viewable Merging Rules tables and interactive dry-runs.
  • Audits all merge events into SQLite curation_events and synchronizes ingestion_records.
"""

import os
import sys
import shutil
import hashlib
import sqlite3
import datetime
import argparse
from pathlib import Path
from typing import Dict, List, Tuple, Optional, Any

# Ensure python directory is in path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from storage_rules import get_shared_db_path, format_size_human, init_storage_rules_tables, get_all_ingestion_records


# ==============================================================================
# MERGING POLICIES & RULES SPECIFICATION
# ==============================================================================

MERGING_RULES = [
    {
        "id": "RULE-01",
        "name": "Direct Unique Merge",
        "condition": "Destination folder exists; incoming filenames are unique (no collisions)",
        "action": "DIRECT_MERGE",
        "destination": "Destination Folder (Direct Placement)",
        "safety": "Zero Overwrite • Preserves folder structure • Fast direct move/copy",
        "description": "Incoming files with unique names are merged directly into the existing destination folder."
    },
    {
        "id": "RULE-02",
        "name": "Identical File Deduplication",
        "condition": "Incoming file matches an existing destination file in relative path AND size/hash",
        "action": "SKIP_DEDUPLICATE",
        "destination": "Destination Folder (Keep Existing)",
        "safety": "Zero Storage Waste • Verified bit-for-bit duplicate skipped • Logged in audit ledger",
        "description": "Redundant identical files are not re-copied; the existing destination file is preserved."
    },
    {
        "id": "RULE-03",
        "name": "Content Conflict (Separate Location)",
        "condition": "Filename collision where size or hash differs between source and destination",
        "action": "ISOLATE_SEPARATE_LOCATION",
        "destination": "_conflicts/<device_name>_<ingestion_id>/<rel_path>",
        "safety": "100% Data Preservation • Zero Overwrite • Conflicting files quarantined for review",
        "description": "Conflicting files are isolated in a separate subfolder or conflict depot, keeping destination clean."
    },
    {
        "id": "RULE-04",
        "name": "Partitioned Sibling Folder",
        "condition": "High collision density or user prefers keeping incoming folder intact",
        "action": "CREATE_PARTITIONED_FOLDER",
        "destination": "<target_folder> (<device_name>)",
        "safety": "Parallel Preservation • Entire incoming hierarchy kept intact in separate folder",
        "description": "Creates a distinct sibling folder suffixed with the device name or ingestion ID."
    },
    {
        "id": "RULE-05",
        "name": "Side-by-Side Suffix",
        "condition": "Individual file collision where side-by-side comparison in destination is preferred",
        "action": "SUFFIX_IN_PLACE",
        "destination": "<stem>_<device_name>_<date><suffix>",
        "safety": "Dual Versioning • Both revisions coexist in the same directory",
        "description": "Renames incoming conflicting file with provenance tags and places it alongside the existing file."
    }
]


def format_merging_rules_table() -> str:
    """Formats the active Storage Manager Merging Rules into a clear, elegant terminal table."""
    lines = []
    w = 140
    lines.append("=" * w)
    lines.append(f"{'STORAGE MANAGER: ACTIVE MERGING & CONFLICT RESOLUTION RULES':^{w}}")
    lines.append("=" * w)
    lines.append(f"{'Rule ID':<9} | {'Rule Policy Name':<30} | {'Action / Behavior':<28} | {'Destination Handling':<42} | {'Safety Guarantee':<20}")
    lines.append("-" * w)

    for r in MERGING_RULES:
        lines.append(f"{r['id']:<9} | {r['name']:<30} | {r['action']:<28} | {r['destination'][:42]:<42} | {r['safety'][:20]:<20}")
        lines.append(f"          ↳ Details: {r['description']}")
        lines.append("-" * w)

    lines.append("=" * w)
    return "\n".join(lines)


# ==============================================================================
# HASHING & FILE COMPARISON UTILITIES
# ==============================================================================

def calculate_file_hash(filepath: Path, chunk_size: int = 65536) -> str:
    """Computes SHA-256 hash for a local file to verify bit-level equality."""
    hasher = hashlib.sha256()
    try:
        with open(filepath, "rb") as f:
            while chunk := f.read(chunk_size):
                hasher.update(chunk)
        return hasher.hexdigest()
    except Exception:
        return ""


# ==============================================================================
# MERGE PLAN DATA STRUCTURE
# ==============================================================================

class StorageMergePlan:
    """Encapsulates the pre-computed merge plan for an incoming folder."""
    def __init__(
        self,
        source_dir: Path,
        destination_dir: Path,
        device_name: str = "Unknown_Device",
        ingestion_id: str = "ING-0000",
        conflict_strategy: str = "separate_location"
    ):
        self.source_dir = source_dir
        self.destination_dir = destination_dir
        self.device_name = device_name
        self.ingestion_id = ingestion_id
        self.conflict_strategy = conflict_strategy  # separate_location, new_folder, suffix
        self.destination_exists = destination_dir.exists()

        self.unique_files: List[Dict[str, Any]] = []      # Can be merged cleanly
        self.identical_files: List[Dict[str, Any]] = []   # Duplicate (can skip)
        self.conflict_files: List[Dict[str, Any]] = []    # Collides with differing content

        self.total_source_files: int = 0
        self.total_source_bytes: int = 0
        self.unique_bytes: int = 0
        self.identical_bytes: int = 0
        self.conflict_bytes: int = 0

    def summary(self) -> str:
        w = 110
        lines = []
        lines.append("=" * w)
        lines.append(f"{'MERGE ANALYSIS PLAN PREVIEW':^{w}}")
        lines.append("=" * w)
        lines.append(f"  • Source Directory:       {self.source_dir}")
        lines.append(f"  • Destination Directory:  {self.destination_dir}")
        lines.append(f"  • Destination Exists?     {'YES (Folder collision detected - Applying Merging Rules)' if self.destination_exists else 'NO (Clean initial creation)'}")
        lines.append(f"  • Ingestion Record:       {self.ingestion_id} ({self.device_name})")
        lines.append(f"  • Conflict Strategy:      {self.conflict_strategy.upper()}")
        lines.append("-" * w)
        lines.append(f"  📊 Breakdown of Files:")
        lines.append(f"     [+] Unique Files to Merge:     {len(self.unique_files):>6,} files ({format_size_human(self.unique_bytes):>9}) ➔ Will merge directly into destination")
        lines.append(f"     [=] Identical Duplicates:      {len(self.identical_files):>6,} files ({format_size_human(self.identical_bytes):>9}) ➔ Will skip (zero bloat)")
        lines.append(f"     [!] Conflicting Files:         {len(self.conflict_files):>6,} files ({format_size_human(self.conflict_bytes):>9}) ➔ Strategy: {self.conflict_strategy.upper()}")
        lines.append(f"     --------------------------------------------------------------------------------------")
        lines.append(f"     Total Source Evaluated:        {self.total_source_files:>6,} files ({format_size_human(self.total_source_bytes):>9})")
        lines.append("=" * w)
        return "\n".join(lines)


# ==============================================================================
# MERGE ANALYZER ENGINE
# ==============================================================================

def analyze_folder_merge(
    source_dir: Path,
    destination_dir: Path,
    device_name: str = "Unknown",
    ingestion_id: str = "ING-0000",
    conflict_strategy: str = "separate_location"
) -> StorageMergePlan:
    """
    Scans source and destination directories to compare file hierarchies, detecting:
      - Unique files (no name collision)
      - Identical duplicates (name collision + exact same size & hash)
      - Content conflicts (name collision + differing size/content)
    """
    plan = StorageMergePlan(
        source_dir=source_dir,
        destination_dir=destination_dir,
        device_name=device_name,
        ingestion_id=ingestion_id,
        conflict_strategy=conflict_strategy
    )

    if not source_dir.exists():
        return plan

    # Traverse all files in source
    for root, _, files in os.walk(source_dir):
        for f in files:
            if f.startswith("."):
                continue
            src_file = Path(root) / f
            try:
                rel_path = src_file.relative_to(source_dir)
            except Exception:
                rel_path = Path(f)

            try:
                sz = src_file.stat().st_size
                mtime = src_file.stat().st_mtime
            except Exception:
                sz = 0
                mtime = 0

            plan.total_source_files += 1
            plan.total_source_bytes += sz

            dest_file = destination_dir / rel_path

            if not dest_file.exists():
                plan.unique_files.append({
                    "src_path": src_file,
                    "rel_path": rel_path,
                    "dest_path": dest_file,
                    "size": sz,
                    "mtime": mtime
                })
                plan.unique_bytes += sz
            else:
                # File collision: compare sizes first (fast check)
                dest_sz = dest_file.stat().st_size
                if sz == dest_sz:
                    # Sizes match: compute hash to confirm identical content
                    src_h = calculate_file_hash(src_file)
                    dest_h = calculate_file_hash(dest_file)
                    if src_h and dest_h and src_h == dest_h:
                        plan.identical_files.append({
                            "src_path": src_file,
                            "rel_path": rel_path,
                            "dest_path": dest_file,
                            "size": sz,
                            "hash": src_h
                        })
                        plan.identical_bytes += sz
                    else:
                        plan.conflict_files.append({
                            "src_path": src_file,
                            "rel_path": rel_path,
                            "dest_path": dest_file,
                            "src_size": sz,
                            "dest_size": dest_sz,
                            "reason": "Hash mismatch with identical size"
                        })
                        plan.conflict_bytes += sz
                else:
                    plan.conflict_files.append({
                        "src_path": src_file,
                        "rel_path": rel_path,
                        "dest_path": dest_file,
                        "src_size": sz,
                        "dest_size": dest_sz,
                        "reason": f"Size mismatch (Source: {format_size_human(sz)}, Dest: {format_size_human(dest_sz)})"
                    })
                    plan.conflict_bytes += sz

    return plan


# ==============================================================================
# MERGE EXECUTOR ENGINE
# ==============================================================================

def execute_storage_merge(
    plan: StorageMergePlan,
    dry_run: bool = False,
    conn: Optional[sqlite3.Connection] = None
) -> Dict[str, Any]:
    """
    Executes the computed merge plan in accordance with active Merging Rules:
      1. Unique files are copied/moved cleanly to the destination.
      2. Identical duplicates are skipped and logged.
      3. Conflicts are isolated to a separate location, partitioned into a sibling folder, or suffixed.
      4. Events are audited in SQLite curation_events and ingestion_records is updated.
    """
    batch_id = f"merge_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}"
    now_iso = datetime.datetime.now().isoformat()

    results = {
        "batch_id": batch_id,
        "dry_run": dry_run,
        "merged_count": 0,
        "merged_bytes": 0,
        "skipped_count": 0,
        "skipped_bytes": 0,
        "conflicts_isolated": 0,
        "conflicts_bytes": 0,
        "errors": []
    }

    prefix = "[Dry-Run] " if dry_run else ""
    print(f"\n{prefix}Executing Storage Merge (Batch: {batch_id})...")

    # Step 1: Process Unique Files (Direct Merge)
    for u in plan.unique_files:
        src = u["src_path"]
        dest = u["dest_path"]
        rel = u["rel_path"]
        sz = u["size"]

        if not dry_run:
            try:
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dest)
                results["merged_count"] += 1
                results["merged_bytes"] += sz
                log_curation_event(
                    conn, batch_id=batch_id, event_type="merge_file",
                    src=str(src), dest=str(dest), size=sz,
                    details=f"Direct merge unique file for {plan.ingestion_id}"
                )
            except Exception as e:
                results["errors"].append(f"Failed to merge {rel}: {e}")
        else:
            results["merged_count"] += 1
            results["merged_bytes"] += sz

    # Step 2: Process Identical Files (Deduplication Skip)
    for ident in plan.identical_files:
        src = ident["src_path"]
        dest = ident["dest_path"]
        sz = ident["size"]
        results["skipped_count"] += 1
        results["skipped_bytes"] += sz
        if not dry_run:
            log_curation_event(
                conn, batch_id=batch_id, event_type="skip_duplicate",
                src=str(src), dest=str(dest), size=sz,
                details=f"Deduplicated duplicate file for {plan.ingestion_id}"
            )

    # Step 3: Process Conflicting Files according to selected strategy
    conflict_dir = plan.destination_dir / "_conflicts" / f"{plan.device_name}_{plan.ingestion_id}"
    new_partition_dir = plan.destination_dir.parent / f"{plan.destination_dir.name} ({plan.device_name})"

    for c in plan.conflict_files:
        src = c["src_path"]
        rel = c["rel_path"]
        sz = c["src_size"]

        if plan.conflict_strategy == "new_folder":
            final_dest = new_partition_dir / rel
        elif plan.conflict_strategy == "suffix":
            ts_tag = datetime.datetime.now().strftime("%Y%m%d")
            final_dest = plan.destination_dir / rel.parent / f"{src.stem}_{plan.device_name}_{ts_tag}{src.suffix}"
        else:  # separate_location (Default)
            final_dest = conflict_dir / rel

        if not dry_run:
            try:
                final_dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, final_dest)
                results["conflicts_isolated"] += 1
                results["conflicts_bytes"] += sz
                log_curation_event(
                    conn, batch_id=batch_id, event_type="isolate_conflict",
                    src=str(src), dest=str(final_dest), size=sz,
                    details=f"Isolated conflicting file via {plan.conflict_strategy} for {plan.ingestion_id}"
                )
            except Exception as e:
                results["errors"].append(f"Failed to isolate conflict {rel}: {e}")
        else:
            results["conflicts_isolated"] += 1
            results["conflicts_bytes"] += sz

    # Step 4: Update ingestion record status in DB
    if not dry_run and conn and plan.ingestion_id:
        try:
            status_val = "completed" if len(plan.conflict_files) == 0 else "conflicts_isolated"
            cur = conn.cursor()
            cur.execute("""
                UPDATE ingestion_records 
                SET status = ?, updated_at = ?
                WHERE ingestion_id = ?
            """, (status_val, now_iso, plan.ingestion_id))
            conn.commit()
        except Exception:
            pass

    print(f"\n{prefix}Merge Execution Complete:")
    print(f"  • Merged Cleanly:     {results['merged_count']:,} files ({format_size_human(results['merged_bytes'])})")
    print(f"  • Skipped Duplicates: {results['skipped_count']:,} files ({format_size_human(results['skipped_bytes'])})")
    print(f"  • Isolated Conflicts: {results['conflicts_isolated']:,} files ({format_size_human(results['conflicts_bytes'])})")
    if results["errors"]:
        print(f"  [!] Errors encountered: {len(results['errors'])}")
        for err in results["errors"][:5]:
            print(f"      - {err}")

    return results


def log_curation_event(
    conn: Optional[sqlite3.Connection],
    batch_id: str,
    event_type: str,
    src: str,
    dest: str,
    size: int,
    details: str = ""
) -> None:
    """Logs individual file operations into curation_events table for audit traceability."""
    if not conn:
        return
    try:
        cur = conn.cursor()
        now_iso = datetime.datetime.now().isoformat()
        cur.execute("""
            INSERT INTO curation_events (
                batch_id, event_type, created_at, source_path, destination_path,
                resource_type, resource_path, file_size_bytes, details
            ) VALUES (?, ?, ?, ?, ?, 'file', ?, ?, ?)
        """, (batch_id, event_type, now_iso, src, dest, dest, size, details))
        conn.commit()
    except Exception:
        pass


# ==============================================================================
# INTERACTIVE CLI & RECORD INSPECTION
# ==============================================================================

def display_ingestion_records_summary(conn: sqlite3.Connection) -> None:
    """Displays all registered ingestion records with local destinations and current status."""
    records = get_all_ingestion_records(conn)
    w = 155
    print("\n" + "=" * w)
    print(f"{'REGISTERED INGESTION RECORDS & LOCAL TARGET DESTINATIONS':^{w}}")
    print("=" * w)
    print(f"{'#':<4} | {'Ingestion ID':<12} | {'Device Name':<20} | {'Remote Folder':<25} | {'Tier':<12} | {'Files':>8} | {'Status':<14} | {'Local Target Destination':<45}")
    print("-" * w)

    for idx, r in enumerate(records, 1):
        fc_str = f"{r['total_files']:,}" if r.get('total_files') else "-"
        dest_display = r['local_destination'] or "(None)"
        print(f"{idx:<4} | {r['ingestion_id']:<12} | {r['device_name']:<20} | {r['source_path']:<25} | {r['target_tier'].title():<12} | {fc_str:>8} | {r['status']:<14} | {dest_display:<45}")

    print("-" * w)
    print(f"Total: {len(records)} Ingestion Records Tracked in Database")
    print("=" * w)


def interactive_storage_manager() -> None:
    """Primary interactive CLI console for Storage Manager folder merges."""
    db_path = get_shared_db_path()
    conn = sqlite3.connect(db_path)
    init_storage_rules_tables(conn)

    active_strategy = "separate_location"

    while True:
        print("\n" + "=" * 85)
        print("  🗄️  STORAGE MANAGER — FOLDER MERGE & CONFLICT RESOLUTION CONSOLE")
        print("=" * 85)
        print(f"  • Knowledge Hub Database: {db_path}")
        print(f"  • Active Conflict Strategy: {active_strategy.upper()} (Safe Isolation)")
        print("-" * 85)
        print("  [1] View Storage Merging Rules & Conflict Policies 📋")
        print("  [2] List Ingestion Records & Local Target Destinations 📦")
        print("  [3] Analyze / Preview Merge for an Ingestion Record (Dry Run) 🔍")
        print("  [4] Execute Folder Merge for an Ingestion Record 🚀")
        print("  [5] Custom Path Merge (Specify arbitrary Source & Target) 📂")
        print("  [6] Change Conflict Resolution Strategy ⚙️")
        print("  [q] Exit Storage Manager")
        print("-" * 85)

        choice = input("Choice [1-6, q]: ").strip().lower()

        if choice == "q":
            print("\nExiting Storage Manager. Goodbye!")
            conn.close()
            break

        elif choice == "1":
            print("\n" + format_merging_rules_table())
            input("\nPress [Enter] to return...")

        elif choice == "2":
            display_ingestion_records_summary(conn)
            input("\nPress [Enter] to return...")

        elif choice == "3":
            display_ingestion_records_summary(conn)
            ing_input = input("\nEnter Ingestion ID or Row Number to Preview [or 'c' to cancel]: ").strip()
            if ing_input.lower() == 'c':
                continue
            records = get_all_ingestion_records(conn)
            selected_rec = None
            if ing_input.isdigit() and 1 <= int(ing_input) <= len(records):
                selected_rec = records[int(ing_input) - 1]
            else:
                for r in records:
                    if r["ingestion_id"].lower() == ing_input.lower():
                        selected_rec = r
                        break

            if not selected_rec:
                print("[!] Ingestion Record not found.")
                continue

            target_dest = Path(selected_rec["local_destination"])
            source_cand = Path(f"/Volumes/Extreme Pro/Staging/{selected_rec['device_name']}{selected_rec['source_path']}")

            print(f"\nTarget Destination: {target_dest}")
            custom_src = input(f"Source Folder Path [{source_cand}]: ").strip()
            src_path = Path(custom_src) if custom_src else source_cand

            plan = analyze_folder_merge(
                source_dir=src_path,
                destination_dir=target_dest,
                device_name=selected_rec["device_name"],
                ingestion_id=selected_rec["ingestion_id"],
                conflict_strategy=active_strategy
            )
            print("\n" + plan.summary())
            input("\nPress [Enter] to return...")

        elif choice == "4":
            display_ingestion_records_summary(conn)
            ing_input = input("\nEnter Ingestion ID or Row Number to EXECUTE [or 'c' to cancel]: ").strip()
            if ing_input.lower() == 'c':
                continue
            records = get_all_ingestion_records(conn)
            selected_rec = None
            if ing_input.isdigit() and 1 <= int(ing_input) <= len(records):
                selected_rec = records[int(ing_input) - 1]
            else:
                for r in records:
                    if r["ingestion_id"].lower() == ing_input.lower():
                        selected_rec = r
                        break

            if not selected_rec:
                print("[!] Ingestion Record not found.")
                continue

            target_dest = Path(selected_rec["local_destination"])
            source_cand = Path(f"/Volumes/Extreme Pro/Staging/{selected_rec['device_name']}{selected_rec['source_path']}")

            print(f"\nTarget Destination: {target_dest}")
            custom_src = input(f"Source Folder Path [{source_cand}]: ").strip()
            src_path = Path(custom_src) if custom_src else source_cand

            if not src_path.exists():
                print(f"[!] Source path does not exist on disk: {src_path}")
                print("    (If files are still in cloud, restore them to staging first, or specify a valid local folder)")
                continue

            plan = analyze_folder_merge(
                source_dir=src_path,
                destination_dir=target_dest,
                device_name=selected_rec["device_name"],
                ingestion_id=selected_rec["ingestion_id"],
                conflict_strategy=active_strategy
            )
            print("\n" + plan.summary())
            confirm = input("\nProceed with merge execution? [y/N]: ").strip().lower()
            if confirm == "y":
                execute_storage_merge(plan, dry_run=False, conn=conn)
            else:
                print("Merge cancelled.")

        elif choice == "5":
            src_str = input("Source Folder Path: ").strip()
            dest_str = input("Destination Folder Path: ").strip()
            if not src_str or not dest_str:
                print("[!] Both source and destination paths are required.")
                continue
            s_path = Path(src_str)
            d_path = Path(dest_str)
            if not s_path.exists():
                print(f"[!] Source directory does not exist: {s_path}")
                continue
            plan = analyze_folder_merge(s_path, d_path, conflict_strategy=active_strategy)
            print("\n" + plan.summary())
            confirm = input("\nExecute merge now? [y/N]: ").strip().lower()
            if confirm == "y":
                execute_storage_merge(plan, dry_run=False, conn=conn)
            else:
                print("Merge cancelled.")

        elif choice == "6":
            print("\nSelect Conflict Resolution Strategy:")
            print("  [1] Separate Location (_conflicts/<device>/...) (Default / Recommended) 🛡️")
            print("  [2] Create Partitioned Sibling Folder (<folder> (<device>)) 📁")
            print("  [3] Suffix In-Place (<file>_<device>_<date>.<ext>) 🏷️")
            st_choice = input("Select [1-3]: ").strip()
            if st_choice == "1":
                active_strategy = "separate_location"
            elif st_choice == "2":
                active_strategy = "new_folder"
            elif st_choice == "3":
                active_strategy = "suffix"
            print(f"[✓] Active Conflict Strategy set to: {active_strategy.upper()}")


# ==============================================================================
# CLI DISPATCHER
# ==============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Storage Manager Folder Merging & Conflict Resolution Engine"
    )
    parser.add_argument("--rules", "-r", action="store_true", help="Display Storage Merging Rules & Policies table")
    parser.add_argument("--list", "-l", action="store_true", help="List registered ingestion records and destinations")
    parser.add_argument("--preview", "-p", metavar="INGESTION_ID", help="Preview/dry-run merge for an Ingestion ID")
    parser.add_argument("--execute", "-x", metavar="INGESTION_ID", help="Execute merge for an Ingestion ID")
    parser.add_argument("--source", "-s", metavar="PATH", help="Source directory path for direct folder merge")
    parser.add_argument("--dest", "-d", metavar="PATH", help="Destination directory path for direct folder merge")
    parser.add_argument("--strategy", choices=["separate_location", "new_folder", "suffix"], default="separate_location", help="Conflict resolution strategy")
    parser.add_argument("--dry-run", action="store_true", help="Simulate merge execution without writing files")

    args = parser.parse_args()
    db_path = get_shared_db_path()
    conn = sqlite3.connect(db_path)
    init_storage_rules_tables(conn)

    if args.rules:
        print("\n" + format_merging_rules_table())
        conn.close()
        return

    if args.list:
        display_ingestion_records_summary(conn)
        conn.close()
        return

    if args.source and args.dest:
        s_path = Path(args.source)
        d_path = Path(args.dest)
        plan = analyze_folder_merge(s_path, d_path, conflict_strategy=args.strategy)
        print("\n" + plan.summary())
        if not args.dry_run:
            execute_storage_merge(plan, dry_run=False, conn=conn)
        else:
            execute_storage_merge(plan, dry_run=True, conn=conn)
        conn.close()
        return

    if args.preview or args.execute:
        target_ing = args.preview or args.execute
        records = get_all_ingestion_records(conn)
        sel = next((r for r in records if r["ingestion_id"].lower() == target_ing.lower()), None)
        if not sel:
            print(f"[!] Ingestion ID '{target_ing}' not found.")
            conn.close()
            return
        target_dest = Path(sel["local_destination"])
        source_cand = Path(f"/Volumes/Extreme Pro/Staging/{sel['device_name']}{sel['source_path']}")
        plan = analyze_folder_merge(source_cand, target_dest, device_name=sel["device_name"], ingestion_id=sel["ingestion_id"], conflict_strategy=args.strategy)
        print("\n" + plan.summary())
        if args.execute and not args.dry_run:
            execute_storage_merge(plan, dry_run=False, conn=conn)
        conn.close()
        return

    # Default: Interactive console
    interactive_storage_manager()


if __name__ == "__main__":
    main()
