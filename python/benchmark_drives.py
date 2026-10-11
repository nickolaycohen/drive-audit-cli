#!/usr/bin/env python3
"""
benchmark_drives.py — Drive Performance & I/O Benchmark Utility
===============================================================
Measures direct, uncached sequential read and write throughput (MB/s)
for attached storage volumes on macOS using low-level direct I/O
(fcntl.F_NOCACHE) to bypass the OS buffer cache.

Usage:
  python3 benchmark_drives.py                  # Benchmark all mounted local drives
  python3 benchmark_drives.py --target /Volumes/LaCie
  python3 benchmark_drives.py --size-mb 128    # Use 128 MB test file (default: 256 MB)
  python3 benchmark_drives.py --quick          # 64 MB quick test
  python3 benchmark_drives.py --json           # Machine-readable JSON output
"""

import os
import sys
import time
import fcntl
import argparse
import subprocess
import json
import shutil
import sqlite3
import datetime
from typing import Dict, List, Optional, Tuple

# macOS fcntl command to disable Unified Buffer Cache (UBC)
# Defined in sys/fcntl.h: #define F_NOCACHE 48
F_NOCACHE = getattr(fcntl, 'F_NOCACHE', 48)

CHUNK_SIZE = 4 * 1024 * 1024  # 4 MB chunk size


def get_diskutil_info(mount_point: str) -> Dict[str, str]:
    """Retrieves disk hardware and filesystem metadata via macOS diskutil."""
    info = {
        "volume_name": os.path.basename(mount_point) or "Root",
        "device_node": "Unknown",
        "protocol": "Internal",
        "solid_state": "Unknown",
        "filesystem": "Unknown",
        "total_gb": 0.0,
        "free_gb": 0.0,
    }

    try:
        statvfs = os.statvfs(mount_point)
        info["total_gb"] = round((statvfs.f_frsize * statvfs.f_blocks) / (1024 ** 3), 1)
        info["free_gb"] = round((statvfs.f_frsize * statvfs.f_bavail) / (1024 ** 3), 1)
    except Exception:
        pass

    try:
        proc = subprocess.run(
            ["diskutil", "info", mount_point],
            capture_output=True,
            text=True,
            timeout=5
        )
        if proc.returncode == 0:
            for line in proc.stdout.splitlines():
                line = line.strip()
                if line.startswith("Device Identifier:"):
                    info["device_node"] = line.split(":", 1)[1].strip()
                elif line.startswith("Protocol:"):
                    info["protocol"] = line.split(":", 1)[1].strip()
                elif line.startswith("Solid State:"):
                    val = line.split(":", 1)[1].strip()
                    if val.lower() == "yes":
                        info["solid_state"] = "SSD"
                    elif val.lower() == "no":
                        info["solid_state"] = "HDD"
                    else:
                        info["solid_state"] = "HDD" if "rugged" in mount_point.lower() or "lacie" in mount_point.lower() else "HDD/Ext"
                elif line.startswith("Device / Media Name:"):
                    mname = line.split(":", 1)[1].strip()
                    if "rugged" in mname.lower() and info["solid_state"] in ("Unknown", "Info not available"):
                        info["solid_state"] = "HDD"
                elif line.startswith("Type (Bundle):"):
                    info["filesystem"] = line.split(":", 1)[1].strip()
                elif line.startswith("Volume Name:"):
                    info["volume_name"] = line.split(":", 1)[1].strip()
            if "timemachine" in proc.stdout.lower() or "com.apple.timemachine" in proc.stdout.lower():
                info["is_time_machine"] = True
            else:
                info["is_time_machine"] = False
    except Exception:
        info["is_time_machine"] = False

    return info


def benchmark_volume(mount_point: str, test_size_bytes: int) -> Dict[str, any]:
    """
    Performs direct uncached write and read throughput tests on a mount point.
    Returns a dictionary of metrics.
    """
    info = get_diskutil_info(mount_point)
    result = {
        "mount_point": mount_point,
        "volume_name": info["volume_name"],
        "device_node": info["device_node"],
        "protocol": info["protocol"],
        "media_type": info["solid_state"],
        "total_gb": info["total_gb"],
        "free_gb": info["free_gb"],
        "test_size_mb": round(test_size_bytes / (1024 * 1024), 1),
        "write_mb_s": None,
        "read_mb_s": None,
        "status": "OK",
        "error": None,
    }

    # Generate pseudo-random test pattern to prevent inline hardware compression from skewing results
    pattern = os.urandom(min(CHUNK_SIZE, test_size_bytes))

    test_file = os.path.join(mount_point, f".disk_benchmark_test_{os.getpid()}_{int(time.time())}.tmp")

    # If the root of the volume isn't directly writable, try a temporary fallback folder (e.g. user home for /)
    if mount_point == "/":
        test_file = os.path.expanduser(f"~/.disk_benchmark_test_{os.getpid()}_{int(time.time())}.tmp")

    fd = None
    try:
        # Check free disk space before writing
        free_bytes = 0
        try:
            statvfs = os.statvfs(mount_point)
            free_bytes = statvfs.f_frsize * statvfs.f_bavail
        except Exception:
            pass

        if free_bytes > 0 and free_bytes < (test_size_bytes * 2):
            result["status"] = "Skipped (Insufficient space)"
            return result

        # ==========================================
        # 1. DIRECT WRITE BENCHMARK
        # ==========================================
        bytes_to_write = test_size_bytes
        fd = os.open(test_file, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)

        # Disable cache on macOS
        try:
            fcntl.fcntl(fd, F_NOCACHE, 1)
        except Exception:
            pass

        start_write = time.perf_counter()
        written = 0
        while written < bytes_to_write:
            chunk = pattern[:min(CHUNK_SIZE, bytes_to_write - written)]
            os.write(fd, chunk)
            written += len(chunk)

        # Force physical sync to storage medium
        os.fsync(fd)
        write_duration = time.perf_counter() - start_write
        os.close(fd)
        fd = None

        if write_duration > 0:
            result["write_mb_s"] = round((written / (1024 * 1024)) / write_duration, 1)

        # ==========================================
        # 2. DIRECT READ BENCHMARK
        # ==========================================
        fd = os.open(test_file, os.O_RDONLY)

        # Disable read cache on macOS
        try:
            fcntl.fcntl(fd, F_NOCACHE, 1)
        except Exception:
            pass

        start_read = time.perf_counter()
        read_bytes = 0
        while read_bytes < bytes_to_write:
            to_read = min(CHUNK_SIZE, bytes_to_write - read_bytes)
            data = os.read(fd, to_read)
            if not data:
                break
            read_bytes += len(data)

        read_duration = time.perf_counter() - start_read
        os.close(fd)
        fd = None

        if read_duration > 0:
            result["read_mb_s"] = round((read_bytes / (1024 * 1024)) / read_duration, 1)

    except PermissionError:
        # If writing is restricted (e.g. APFS Time Machine Backup volume or read-only volume),
        # attempt an uncached direct read benchmark on an existing sample file if FDA allows reading.
        sample_file = find_readable_sample_file(mount_point)
        if sample_file:
            try:
                fd_sample = os.open(sample_file, os.O_RDONLY)
                try:
                    fcntl.fcntl(fd_sample, F_NOCACHE, 1)
                except Exception:
                    pass
                start_read = time.perf_counter()
                read_bytes = 0
                target_read = min(test_size_bytes, 64 * 1024 * 1024)
                while read_bytes < target_read:
                    to_read = min(CHUNK_SIZE, target_read - read_bytes)
                    chunk = os.read(fd_sample, to_read)
                    if not chunk:
                        if read_bytes >= 4 * 1024 * 1024:
                            break
                        try:
                            os.lseek(fd_sample, 0, os.SEEK_SET)
                            chunk = os.read(fd_sample, to_read)
                            if not chunk:
                                break
                        except Exception:
                            break
                    read_bytes += len(chunk)
                duration = time.perf_counter() - start_read
                os.close(fd_sample)
                if duration > 0 and read_bytes > 0:
                    result["read_mb_s"] = round((read_bytes / (1024 * 1024)) / duration, 1)
                    result["status"] = "Write-Protected (Time Machine)" if info.get("is_time_machine") else "Write-Protected (Read-Only)"
            except Exception:
                pass

        if result.get("read_mb_s") is None:
            if info.get("is_time_machine"):
                result["status"] = "Protected (Time Machine / FDA Required)"
            else:
                result["status"] = "Protected (FDA Permission Required)"
    except OSError as e:
        if "Read-only file system" in str(e) or e.errno == 30:
            result["status"] = "Read-only volume"
        else:
            result["status"] = f"Error ({e})"
            result["error"] = str(e)
    finally:
        if fd is not None:
            try:
                os.close(fd)
            except Exception:
                pass
        if os.path.exists(test_file):
            try:
                os.remove(test_file)
            except Exception:
                pass

    return result


def find_readable_sample_file(mount_point: str, min_size_bytes: int = 1024 * 1024, max_depth: int = 4) -> Optional[str]:
    """Finds an existing readable file on a volume to benchmark read throughput without modifying files."""
    def _search(curr_dir: str, depth: int, min_size: int) -> Optional[str]:
        if depth > max_depth:
            return None
        try:
            for entry in os.scandir(curr_dir):
                if entry.name in ('.Spotlight-V100', '.fseventsd', '.DocumentRevisions-V100', '.Trashes'):
                    continue
                try:
                    if entry.is_file(follow_symlinks=False):
                        if entry.stat().st_size >= min_size:
                            # Verify that the current process has permission to read the file
                            test_fd = os.open(entry.path, os.O_RDONLY)
                            os.close(test_fd)
                            return entry.path
                    elif entry.is_dir(follow_symlinks=False):
                        res = _search(entry.path, depth + 1, min_size)
                        if res:
                            return res
                except (PermissionError, OSError):
                    continue
        except (PermissionError, OSError):
            pass
        return None

    # 1. Search for larger files (>= 1 MB) for optimal sequential throughput measurement
    sample = _search(mount_point, 0, min_size_bytes)
    if sample:
        return sample
    # 2. Fall back to any readable file (>= 1 KB, e.g. backup_manifest.plist) if snapshots are restricted
    return _search(mount_point, 0, 1024)


def discover_candidate_volumes() -> List[str]:
    """Finds all mounted non-virtual local volumes."""
    candidates = ["/"]
    volumes_dir = "/Volumes"
    if os.path.exists(volumes_dir):
        for entry in sorted(os.listdir(volumes_dir)):
            full_path = os.path.join(volumes_dir, entry)
            # Skip hidden, symlinks, or special volumes like .timemachine
            if entry.startswith(".") or not os.path.isdir(full_path):
                continue
            if os.path.islink(full_path):
                continue
            # Skip installer DMGs or known read-only mounts if obvious
            if entry in ("Antigravity", "Recovery"):
                continue
            candidates.append(full_path)
    return candidates


def print_table(results: List[Dict[str, any]]):
    """Prints a styled terminal table of benchmark results."""
    print("\n" + "=" * 96)
    print("                      STORAGE DRIVES PERFORMANCE BENCHMARK                      ")
    print("                    (Direct Uncached Sequential I/O via F_NOCACHE)              ")
    print("=" * 96)
    print(f"{'Volume / Mount Point':<26} | {'Media':<6} | {'Interface':<12} | {'Write Speed':<14} | {'Read Speed':<14} | {'Free Space'}")
    print("-" * 96)

    for r in results:
        vol_label = r["volume_name"]
        if len(vol_label) > 24:
            vol_label = vol_label[:21] + "..."

        media = r.get("media_type") or "N/A"
        protocol = r.get("protocol") or "Internal"

        if r.get("write_mb_s") is not None:
            w_str = f"{r['write_mb_s']:,} MB/s"
        elif "Time Machine" in r.get("status", "") or "Protected" in r.get("status", ""):
            w_str = "Write-Protected"
        else:
            w_str = r.get("status", "N/A")

        if r.get("read_mb_s") is not None:
            r_str = f"{r['read_mb_s']:,} MB/s"
        elif "FDA Required" in r.get("status", ""):
            r_str = "FDA Required"
        else:
            r_str = "-"

        free_str = f"{r['free_gb']:,} GB free" if r.get("free_gb") else "N/A"

        print(f"{vol_label:<26} | {media:<6} | {protocol:<12} | {w_str:<14} | {r_str:<14} | {free_str}")

    print("=" * 96)
    print("💡 Notes:")
    print(" • Benchmarks use uncompressed pseudo-random blocks with direct I/O to measure hardware throughput.")
    print(" • Time Machine volumes restrict write operations by default to prevent corruption of backup snapshots.")
    print(" • NVMe SSDs (e.g. Extreme Pro) deliver ~10x-100x superior random 4K I/O vs mechanical HDDs (LaCie / asd).")
    print("=" * 96 + "\n")


def get_default_db_path() -> Optional[str]:
    """Finds drive_audit.db in standard storage locations, matching drive_audit_finder priority."""
    env_p = os.environ.get("DRIVE_AUDIT_DB")
    if env_p and os.path.exists(env_p):
        return os.path.abspath(env_p)
    ext_pro = "/Volumes/Extreme Pro/Data/sqlite/drive-audit/drive_audit.db"
    if os.path.exists(ext_pro):
        return os.path.abspath(ext_pro)
    candidates = [
        str(Path(__file__).resolve().parent.parent / "db" / "drive_audit.db"),
        "db/drive_audit.db",
        "drive_audit.db",
        str(Path(__file__).resolve().parent.parent / "drive_audit.db"),
        os.path.expanduser("~/dev/drive-audit-cli/db/drive_audit.db"),
        os.path.expanduser("~/dev/drive-audit-cli/drive_audit.db"),
    ]
    for c in candidates:
        if os.path.exists(c):
            return os.path.abspath(c)
    return None


def init_benchmark_table(conn: sqlite3.Connection):
    """Ensures drive_benchmarks table exists in SQLite database."""
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS drive_benchmarks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            mount_point TEXT UNIQUE,
            volume_name TEXT,
            device_node TEXT,
            protocol TEXT,
            media_type TEXT,
            total_gb REAL,
            free_gb REAL,
            test_size_mb REAL,
            write_mb_s REAL,
            read_mb_s REAL,
            status TEXT,
            benchmark_at TEXT
        )
    """)
    conn.commit()


def save_benchmark_results_to_db(db_path: str, results: List[Dict[str, any]]) -> bool:
    """Saves or updates benchmark results for volumes in SQLite."""
    if not db_path or not os.path.exists(db_path):
        return False
    try:
        conn = sqlite3.connect(db_path)
        init_benchmark_table(conn)
        cursor = conn.cursor()
        now = datetime.datetime.now().isoformat()
        for r in results:
            cursor.execute("""
                INSERT INTO drive_benchmarks (
                    mount_point, volume_name, device_node, protocol, media_type,
                    total_gb, free_gb, test_size_mb, write_mb_s, read_mb_s, status, benchmark_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(mount_point) DO UPDATE SET
                    volume_name = excluded.volume_name,
                    device_node = excluded.device_node,
                    protocol = excluded.protocol,
                    media_type = excluded.media_type,
                    total_gb = excluded.total_gb,
                    free_gb = excluded.free_gb,
                    test_size_mb = excluded.test_size_mb,
                    write_mb_s = excluded.write_mb_s,
                    read_mb_s = excluded.read_mb_s,
                    status = excluded.status,
                    benchmark_at = excluded.benchmark_at
            """, (
                r.get("mount_point"),
                r.get("volume_name"),
                r.get("device_node"),
                r.get("protocol"),
                r.get("media_type"),
                r.get("total_gb"),
                r.get("free_gb"),
                r.get("test_size_mb"),
                r.get("write_mb_s"),
                r.get("read_mb_s"),
                r.get("status"),
                now
            ))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"[Warning] Failed to persist benchmark results to DB: {e}")
        return False


def get_saved_benchmarks(db_path: str) -> List[Dict[str, any]]:
    """Loads previously saved benchmark results from SQLite."""
    if not db_path or not os.path.exists(db_path):
        return []
    try:
        conn = sqlite3.connect(db_path)
        init_benchmark_table(conn)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM drive_benchmarks ORDER BY mount_point")
        rows = [dict(r) for r in cursor.fetchall()]
        conn.close()
        return rows
    except Exception:
        return []


def run_benchmark_interactive(default_quick: bool = False, db_path: Optional[str] = None):
    """Interactive helper designed to be called directly or from the main orchestrator."""
    active_db = db_path or get_default_db_path()

    print("\n" + "=" * 60)
    print("      STORAGE PERFORMANCE & DIRECT I/O BENCHMARK      ")
    print("=" * 60)
    print("Tests uncached sequential write and read throughput (MB/s).")
    print("Uses low-level direct I/O (fcntl.F_NOCACHE) to bypass RAM cache.")
    print("\nOptions:")
    print("  1. Quick Test (64 MB test file per drive)")
    print("  2. Standard Test (256 MB test file per drive - Recommended)")
    print("  3. Thorough Test (512 MB test file per drive)")
    print("  4. Cancel")
    
    choice = input("\nSelect test size (1-4, default 2): ").strip()
    if choice == "4":
        return
    elif choice == "1":
        size_mb = 64
    elif choice == "3":
        size_mb = 512
    else:
        size_mb = 256

    test_size_bytes = size_mb * 1024 * 1024
    volumes = discover_candidate_volumes()

    print(f"\n[INFO] Starting benchmark with {size_mb} MB payload per drive...")
    results = []
    for vol in volumes:
        print(f"  ⏳ Testing: {vol} ...", end="", flush=True)
        res = benchmark_volume(vol, test_size_bytes)
        results.append(res)
        if res["status"] == "OK":
            print(f" Done! (Write: {res['write_mb_s']} MB/s | Read: {res['read_mb_s']} MB/s)")
        else:
            print(f" {res['status']}")

    print_table(results)

    if active_db:
        if save_benchmark_results_to_db(active_db, results):
            print(f"[Success] Benchmark results saved to database ({active_db})")


def main():
    parser = argparse.ArgumentParser(description="Direct I/O Storage Performance Benchmark for macOS")
    parser.add_argument("--target", "-t", type=str, help="Specific volume or mount point to benchmark")
    parser.add_argument("--size-mb", "-s", type=int, default=256, help="Test payload size in MB (default: 256)")
    parser.add_argument("--quick", "-q", action="store_true", help="Quick mode (64 MB payload)")
    parser.add_argument("--interactive", "-i", action="store_true", help="Run interactive menu")
    parser.add_argument("--json", action="store_true", help="Output results in JSON format")
    parser.add_argument("--db", type=str, help="SQLite database path to persist benchmark results")

    args = parser.parse_args()
    db_target = args.db or get_default_db_path()

    if args.interactive:
        run_benchmark_interactive(db_path=db_target)
        return

    size_mb = 64 if args.quick else args.size_mb
    test_size_bytes = size_mb * 1024 * 1024

    if args.target:
        if not os.path.exists(args.target):
            print(f"[Error] Target path '{args.target}' does not exist.", file=sys.stderr)
            sys.exit(1)
        volumes = [args.target]
    else:
        volumes = discover_candidate_volumes()

    if not args.json:
        print(f"\n[INFO] Initializing direct I/O benchmark ({size_mb} MB payload per drive)...")

    results = []
    for vol in volumes:
        if not args.json:
            print(f"  ⏳ Testing: {vol} ...", end="", flush=True)
        res = benchmark_volume(vol, test_size_bytes)
        results.append(res)
        if not args.json:
            if res["status"] == "OK":
                print(f" Done! (Write: {res['write_mb_s']} MB/s | Read: {res['read_mb_s']} MB/s)")
            else:
                print(f" {res['status']}")

    if db_target:
        save_benchmark_results_to_db(db_target, results)

    if args.json:
        print(json.dumps(results, indent=2))
    else:
        print_table(results)


if __name__ == "__main__":
    main()

