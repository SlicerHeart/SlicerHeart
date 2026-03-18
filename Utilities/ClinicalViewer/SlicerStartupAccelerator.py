#!/usr/bin/env python3

"""
Makes Slicer startup faster by loading Slicer application files into operating system caches.
Recursively reads all compiled Python scripts (.pyc) and dynamic link libraries (.dll, .pyd)
in the application directory.

Dynamic link libraries on Windows are loaded using Win32 API (LoadLibraryExW) with flags that
prevent running initialization code (LOAD_LIBRARY_AS_DATAFILE | LOAD_LIBRARY_AS_IMAGE_RESOURCE),
then immediately freed. This maps the DLL into memory without executing DllMain, thereby warming the cache
but avoiding potential side effects.
All other files are simply read in blocks, which increases the probability that the file content
will be quickly accessible in read caches.

Files are read on multiple threads in parallel to reduce loading time (e.g., 16 seconds instead of 225 seconds).

Example usage in Windows Task scheduler (full paths must be used and quotes must be used around paths with spaces; log file is recommended only for debugging):
    Program/script: "c:/Users/andra/appdata/Local/slicer.org/3D Slicer 5.10.0/bin/PythonSlicer.exe"
    Add arguments: "c:/D/SlicerHeartPrivate/Utilities/SlicerStartupAccelerator.py" --log-file "c:/tmp/SlicerStartupAccelerator.log"

Optional arguments:
    --root path/to/application   Top-level application folder (default: parent folder of the folder that contains the Python interpreter)
    --extensions .dll .pyc       Space-separated list of extensions to include (case-insensitive)
    --workers 4                  Number of concurrent worker threads (default: number of CPUs / 2 to not hog resources when ran as a background process)
    --follow-symlinks            Follow symbolic links when traversing
    --verbose                    Log information on each cached file
    --strict                     Return non-zero exit code if any file failed
    --log-file path/to/log.txt   Redirect output to log file (default: log to standard output)

Exit codes:
    0 on success (even if some files could not be read, unless --strict used)
    1 on fatal argument or runtime error
    2 if --strict and at least one file failed to read

"""

from __future__ import annotations

import argparse
import atexit
import concurrent.futures
import os
import sys
import threading
import time
import ctypes
import platform
from pathlib import Path
from typing import Iterable, List, Tuple

# Global counters protected by a lock for thread-safe updates
_stats_lock = threading.Lock()
_files_read = 0
_bytes_read = 0
_files_failed = 0


def parse_args(argv: List[str]) -> argparse.Namespace:

    # Default root is the folder that contains the Python interpreter's parent folder.
    # Typically python executable is in '../AppData/Local/slicer.org/3D Slicer 5.10.0/bin/python-real.exe'
    # and so the root is '../AppData/Local/slicer.org/3D Slicer 5.10.0'
    defaultRoot = Path(sys.executable).parent.parent
    if hasattr(sys, 'real_prefix'):
        defaultRoot = Path(sys.executable).parent.parent

    # Only use half of the CPU cores by default to avoid consuming too much resources
    # when running this as a background process.
    defaultCpuCount = int(os.cpu_count() / 2)
    if defaultCpuCount < 1:
        defaultCpuCount = 1

    parser = argparse.ArgumentParser(description="Warm disk cache by reading selected files.")
    parser.add_argument("--root", required=False, default=defaultRoot,
                        help="Root directory to traverse (default: parent folder of the folder that contains the Python interpreter)")
    parser.add_argument("--log-file", required=False, default=None,
                        help="Path to log file (default: no log file)")
    parser.add_argument("--extensions", nargs="*", default=[".dll", ".pyc", ".pyd"],
                        help="Extensions to include (case-insensitive, include leading dot)")
    parser.add_argument("--workers", type=int, default=defaultCpuCount,
                        help="Number of worker threads (default: CPU count / 2)")
    parser.add_argument("--follow-symlinks", action="store_true", help="Follow symbolic links while walking")
    parser.add_argument("--verbose", action="store_true", help="Show information on each cached file")
    parser.add_argument("--strict", action="store_true", help="Return non-zero exit code if any file failed")
    return parser.parse_args(argv)


def should_include(path: Path, args: argparse.Namespace) -> bool:
    if not path.is_file():
        return False
    ext = path.suffix.lower()
    if args.extensions and ext not in [e.lower() for e in args.extensions]:
        return False
    return True


def discover_files(root: Path, args: argparse.Namespace) -> List[Path]:
    results: List[Path] = []
    walk_follow = args.follow_symlinks
    for dirpath, dirnames, filenames in os.walk(root, followlinks=walk_follow):
        for name in filenames:
            p = Path(dirpath) / name
            if should_include(p, args):
                results.append(p)
    return results


def read_file(path: Path, block_size: int = 1000000) -> Tuple[int, int]:
    """Read file in blocks.

    Default block size is set to be large enough to have small overhead, but small enough to use negligible memory.
    Returns (bytes_read: int, failed: bool)
    """
    failed = False
    total = 0
    try:
        with open(path, 'rb') as f:
            while True:
                chunk = f.read(block_size)
                if not chunk:
                    break
                total += len(chunk)
    except Exception:
        total = 0
        failed = True
    return total, failed


def load_library(path: Path) -> Tuple[int, int]:
    """Load a DLL using LoadLibraryEx with safe flags and immediately free it.

    Returns (bytes_read: int, failed: bool)
    """
    failed = False
    total = 0
    if platform.system() == "Windows":
        # Flags to prevent executing code: LOAD_LIBRARY_AS_DATAFILE (0x00000002) and
        # LOAD_LIBRARY_AS_IMAGE_RESOURCE (0x00000020)
        LOAD_LIBRARY_AS_DATAFILE = 0x00000002
        LOAD_LIBRARY_AS_IMAGE_RESOURCE = 0x00000020
        flags = LOAD_LIBRARY_AS_DATAFILE | LOAD_LIBRARY_AS_IMAGE_RESOURCE
        kernel32 = ctypes.windll.kernel32
        kernel32.SetLastError(0)
        try:
            h_module = kernel32.LoadLibraryExW(str(path), None, flags)
            if not h_module:
                failed = True
            else:
                # Immediately free; cache warming happens on load.
                kernel32.FreeLibrary(h_module)
                total = path.stat().st_size
        except Exception:
            # Unknown error
            failed = True
    else:
        # shared library loading is currently only implemented for Windows
        pass
    return total, failed

def update_stats(bytes_read: int, failed: bool):
    global _files_read, _bytes_read, _files_failed
    with _stats_lock:
        if failed:
            _files_failed += 1
        else:
            _files_read += 1
            _bytes_read += bytes_read


def process_file(path: Path, args: argparse.Namespace):
    if path.suffix.lower() in [".dll", ".pyd", ".exe"]:
        bytes_read, failed = load_library(path)
        if args.verbose:
            status = "FAIL" if failed else "LOADED"
            print(f"[{status}] {path} (size={bytes_read} bytes)")
    else:
        bytes_read, failed = read_file(path)
        if args.verbose:
            status = "FAIL" if failed else "OK"
            print(f"[{status}] {path} ({bytes_read} bytes)")
    update_stats(bytes_read, failed)


def main(argv: List[str]) -> int:
    args = parse_args(argv)
    root = Path(args.root)
    root = root.absolute()
    if not root.exists() or not root.is_dir():
        raise RuntimeError(f"Error: root directory '{root}' does not exist or is not a directory", file=sys.stderr)

    # Write to log file, append mode
    if args.log_file:
        log_file = open(args.log_file, "a+")
        sys.stdout = log_file
        sys.stderr = log_file
        atexit.register(log_file.close)
        # print date and time to log
        from datetime import datetime
        print(f"----------\nLog started at {datetime.now()}")

    start = time.time()
    files = discover_files(root, args)
    if args.verbose:
        print(f"Discovered {len(files)} file(s) matching criteria.")

    if files and args.workers > 1:
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures = [pool.submit(process_file, f, args) for f in files]
            for fut in concurrent.futures.as_completed(futures):
                # Exceptions in threads should surface.
                try:
                    fut.result()
                except Exception as e:
                    if args.verbose:
                        print(f"Thread error: {e}")
    else:
        for f in files:
            process_file(f, args)

    return_code = 0
    if args.strict and _files_failed > 0:
        return_code = 2

    elapsed = time.time() - start
    if args.verbose:
        print("\nSummary:")
    print(f"Number of workers: {args.workers}")
    print(f"Files successfully read: {_files_read}")
    print(f"Files failed: {_files_failed}")
    print(f"Total MB read: {_bytes_read/1024/1024:.1f} MB")
    print(f"Elapsed time: {elapsed:.2f} s")
    print(f"Return code: {return_code}")

    return return_code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
