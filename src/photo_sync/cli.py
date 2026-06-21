"""CLI entry point for photo-sync."""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path

from photo_sync import __version__
from photo_sync.db.connection import (
    DatabaseLockedError,
    DatabaseNotFoundError,
)
from photo_sync.db.schema_version import SchemaVersionMismatchError
from photo_sync.operations.dedup import dedup_album_dry_run, dedup_album_execute
from photo_sync.operations.file_copy import DiskFullError
from photo_sync.sync import create_sync_plan, sync_photos

# Exit codes
EXIT_SUCCESS = 0
EXIT_ERROR = 1
EXIT_INVALID_ARGS = 2
EXIT_SOURCE_NOT_FOUND = 3
EXIT_TARGET_NOT_FOUND = 4
EXIT_DB_LOCKED = 5
EXIT_DISK_FULL = 6
EXIT_PERMISSION_DENIED = 7
EXIT_SCHEMA_MISMATCH = 8

logger = logging.getLogger(__name__)


def setup_logging(verbose: bool = False, quiet: bool = False) -> None:
    """Configure logging based on CLI flags.

    Args:
        verbose: Enable debug logging
        quiet: Suppress non-error output
    """
    # Check environment variable
    env_level = os.environ.get("PHOTO_SYNC_LOG_LEVEL", "").upper()

    if env_level:
        level = getattr(logging, env_level, logging.INFO)
    elif quiet:
        level = logging.ERROR
    elif verbose:
        level = logging.DEBUG
    else:
        level = logging.INFO

    logging.basicConfig(
        level=level,
        format="%(levelname)s: %(message)s",
        stream=sys.stderr,
    )


def format_bytes(size: int) -> str:
    """Format byte size as human-readable string.

    Args:
        size: Size in bytes

    Returns:
        Human-readable string (e.g., "45.2 MB")
    """
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} PB"


def progress_bar(current: int, total: int, prefix: str = "", width: int = 28) -> str:
    """Generate a progress bar string.

    Args:
        current: Current progress
        total: Total items
        prefix: Optional prefix text
        width: Width of the bar in characters

    Returns:
        Progress bar string
    """
    if total == 0:
        percent = 100
        filled = width
    else:
        percent = int(100 * current / total)
        filled = int(width * current / total)

    bar = "=" * filled + " " * (width - filled)
    return f"{prefix}[{bar}] {current}/{total} ({percent}%)"


def print_progress(current: int, total: int, message: str, quiet: bool = False) -> None:
    """Print progress update to stdout.

    Args:
        current: Current progress
        total: Total items
        message: Progress message
        quiet: If True, suppress output
    """
    if quiet:
        return

    bar = progress_bar(current, total)
    # Use carriage return to overwrite line
    print(f"\r{bar} {message[:40]:<40}", end="", flush=True)
    if current == total:
        print()  # Newline at end


def format_sync_plan(plan, json_output: bool = False) -> str:
    """Format sync plan for output.

    Args:
        plan: SyncPlan object
        json_output: If True, output JSON format

    Returns:
        Formatted string
    """
    if json_output:
        return json.dumps(plan.to_detailed_dict(), indent=2)

    lines = [
        "DRY RUN - No changes will be made",
        "",
        "Changes that would be synced:",
        f"  Photos to add: {len(plan.photos_to_add)}",
    ]

    # Show photo details (first 5)
    for detail in plan.photo_details[:5]:
        lines.append(f"    - {detail['filename']} ({format_bytes(detail['size'])})")
    if len(plan.photo_details) > 5:
        lines.append(f"    ... and {len(plan.photo_details) - 5} more")

    lines.extend([
        f"  Photos to delete: {len(plan.photos_to_delete)}",
        f"  Albums to add: {len(plan.albums_to_add)}",
    ])

    # Show album details
    for detail in plan.album_details[:5]:
        title = detail.get("title") or detail["uuid"][:8]
        lines.append(f"    - \"{title}\"")
    if len(plan.album_details) > 5:
        lines.append(f"    ... and {len(plan.album_details) - 5} more")

    lines.extend([
        f"  Album memberships to add: {len(plan.memberships_to_add)}",
        f"  Album memberships to remove: {len(plan.memberships_to_remove)}",
        f"  Favourites to sync: {len(plan.favourites_to_sync)}",
        "",
        f"Total data to copy: {format_bytes(plan.total_bytes_to_copy)}",
    ])

    return "\n".join(lines)


def format_result(result, json_output: bool = False, elapsed: float = 0) -> str:
    """Format sync result for output.

    Args:
        result: SyncResult object
        json_output: If True, output JSON format
        elapsed: Elapsed time in seconds

    Returns:
        Formatted string
    """
    if json_output:
        output = {
            "status": "success" if result.success else "error",
            "summary": result.to_dict(),
            "elapsed_seconds": round(elapsed, 1),
        }
        return json.dumps(output, indent=2)

    lines = [
        "",
        "Sync complete!" if result.success else "Sync completed with errors!",
        f"  Photos added: {result.photos_added}",
        f"  Photos deleted: {result.photos_deleted}",
        f"  Albums added: {result.albums_added}",
        f"  Favourites synced: {result.favourites_synced}",
        f"  Files copied: {result.files_copied} ({format_bytes(result.bytes_copied)})",
        f"  Derivatives copied: {result.derivative_files_copied} "
        f"({format_bytes(result.derivative_bytes_copied)})",
        f"  Time elapsed: {elapsed:.1f}s",
    ]

    if result.warnings:
        lines.append("")
        lines.append("Warnings:")
        for warning in result.warnings[:10]:
            lines.append(f"  - {warning}")
        if len(result.warnings) > 10:
            lines.append(f"  ... and {len(result.warnings) - 10} more")

    if result.errors:
        lines.append("")
        lines.append("Errors:")
        for error in result.errors:
            lines.append(f"  - {error}")

    return "\n".join(lines)


def validate_library_path(path: str, name: str) -> tuple[bool, int, str]:
    """Validate a library path exists and is accessible.

    Args:
        path: Path to validate
        name: Name for error messages ("source" or "target")

    Returns:
        Tuple of (valid, exit_code, error_message)
    """
    lib_path = Path(path)

    if not lib_path.exists():
        code = EXIT_SOURCE_NOT_FOUND if name == "source" else EXIT_TARGET_NOT_FOUND
        return False, code, f"{name.capitalize()} library not found: {path}"

    if not lib_path.is_dir():
        return False, EXIT_INVALID_ARGS, f"{name.capitalize()} is not a directory: {path}"

    db_path = lib_path / "database" / "Photos.sqlite"
    if not db_path.exists():
        return False, EXIT_INVALID_ARGS, f"Invalid library format (no database): {path}"

    return True, EXIT_SUCCESS, ""


def format_dedup_report(report: dict, json_output: bool = False) -> str:
    """Format dedup dry-run report for output.

    Args:
        report: Dedup report dict from dedup_album_dry_run
        json_output: If True, output JSON format

    Returns:
        Formatted string
    """
    if json_output:
        return json.dumps(report, indent=2)

    if report["total_duplicates"] == 0:
        return f"No duplicates found in album \"{report['album']}\" ({report['total_assets']} photos scanned)."

    lines = [
        f"DRY RUN - Duplicates found in album \"{report['album']}\"",
        f"  Total photos scanned: {report['total_assets']}",
        f"  Duplicate groups: {report['total_duplicates']}",
        f"  Photos to delete: {report['total_to_delete']}",
        "",
    ]

    for i, group in enumerate(report["groups"], 1):
        lines.append(f"  Group {i}:")
        lines.append(f"    Keep:   {group['keep']['filename']} (uuid={group['keep']['uuid'][:8]}...)")
        for dup in group["delete"]:
            lines.append(f"    Delete: {dup['filename']} (uuid={dup['uuid'][:8]}...)")

    lines.append("")
    lines.append("Summary:")
    lines.append(f"  Total photos scanned: {report['total_assets']}")
    lines.append(f"  Duplicate groups: {report['total_duplicates']}")
    lines.append(f"  Photos to delete: {report['total_to_delete']}")
    lines.append(f"  Photos to keep: {report['total_assets'] - report['total_to_delete']}")
    lines.append("")
    lines.append("Run without --dry-run to delete duplicates.")
    return "\n".join(lines)


def format_dedup_result(result: dict, json_output: bool = False, elapsed: float = 0) -> str:
    """Format dedup execution result for output.

    Args:
        result: Dedup result dict from dedup_album_execute
        json_output: If True, output JSON format
        elapsed: Elapsed time in seconds

    Returns:
        Formatted string
    """
    if json_output:
        output = {**result, "elapsed_seconds": round(elapsed, 1)}
        return json.dumps(output, indent=2)

    lines = [
        f"Dedup complete for album \"{result['album']}\"!",
        f"  Duplicate groups: {result['groups']}",
        f"  Photos deleted: {result['deleted']}",
        f"  Time elapsed: {elapsed:.1f}s",
    ]

    if result["errors"]:
        lines.append("")
        lines.append("Errors:")
        for error in result["errors"]:
            lines.append(f"  - {error}")

    return "\n".join(lines)


def create_parser() -> argparse.ArgumentParser:
    """Create the CLI argument parser with subcommands.

    Returns:
        Configured ArgumentParser
    """
    parser = argparse.ArgumentParser(
        prog="photo-sync",
        description="Synchronize photos and albums between Apple Photos libraries",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # --- sync subcommand ---
    sync_parser = subparsers.add_parser(
        "sync",
        help="Sync photos and albums between libraries",
        description="Synchronize photos and albums from source to target library",
    )
    sync_parser.add_argument(
        "source",
        metavar="SOURCE",
        help="Path to source Photos library (.photoslibrary)",
    )
    sync_parser.add_argument(
        "target",
        metavar="TARGET",
        help="Path to target Photos library (.photoslibrary)",
    )
    sync_parser.add_argument(
        "-n", "--dry-run",
        action="store_true",
        help="Preview changes without executing",
    )
    sync_parser.add_argument(
        "-j", "--json",
        action="store_true",
        help="Output in JSON format",
    )
    sync_parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose logging",
    )
    sync_parser.add_argument(
        "-q", "--quiet",
        action="store_true",
        help="Suppress non-error output",
    )
    sync_parser.add_argument(
        "--no-delete",
        action="store_true",
        help="Skip deletion sync (add-only mode)",
    )
    sync_parser.add_argument(
        "--no-albums",
        action="store_true",
        help="Skip album sync (photos only)",
    )
    sync_parser.add_argument(
        "--verify",
        action="store_true",
        help="Verify file integrity after copy",
    )
    sync_parser.add_argument(
        "--full", "--reconcile",
        dest="full",
        action="store_true",
        help="Ignore incremental state; do a full comparison of all dimensions",
    )

    # --- dedup subcommand ---
    dedup_parser = subparsers.add_parser(
        "dedup",
        help="Deduplicate photos within an album",
        description="Find and remove duplicate photos within an album",
    )
    dedup_parser.add_argument(
        "library",
        metavar="LIBRARY",
        help="Path to Photos library (.photoslibrary)",
    )
    dedup_parser.add_argument(
        "--album",
        required=True,
        help="Album name to deduplicate",
    )
    dedup_parser.add_argument(
        "-n", "--dry-run",
        action="store_true",
        help="Preview duplicates without deleting",
    )
    dedup_parser.add_argument(
        "-j", "--json",
        action="store_true",
        help="Output in JSON format",
    )
    dedup_parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose logging",
    )
    dedup_parser.add_argument(
        "-q", "--quiet",
        action="store_true",
        help="Suppress non-error output",
    )

    # --- sync-all subcommand ---
    sync_all_parser = subparsers.add_parser(
        "sync-all",
        help="Sync every library pair listed in a config file",
        description="Sync every source/target library pair listed in a JSON config file.",
    )
    sync_all_parser.add_argument(
        "--config",
        default=DEFAULT_SYNC_ALL_CONFIG,
        metavar="PATH",
        help=f"JSON file listing library pairs (default: {DEFAULT_SYNC_ALL_CONFIG}). "
             "See sync-all.config.example.json for the format.",
    )
    sync_all_parser.add_argument(
        "-n", "--dry-run",
        action="store_true",
        help="Preview changes for all libraries without executing",
    )
    sync_all_parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose logging",
    )
    sync_all_parser.add_argument(
        "-q", "--quiet",
        action="store_true",
        help="Suppress non-error output",
    )
    sync_all_parser.add_argument(
        "--no-delete",
        action="store_true",
        help="Skip deletion sync (add-only mode)",
    )
    sync_all_parser.add_argument(
        "--no-albums",
        action="store_true",
        help="Skip album sync (photos only)",
    )
    sync_all_parser.add_argument(
        "--verify",
        action="store_true",
        help="Verify file integrity after copy",
    )
    sync_all_parser.add_argument(
        "--full", "--reconcile",
        dest="full",
        action="store_true",
        help="Ignore incremental state; do a full comparison of all dimensions",
    )

    # --- fix-trash subcommand ---
    fix_trash_parser = subparsers.add_parser(
        "fix-trash",
        help="Fix Recently Deleted album counts",
        description="Update the Recently Deleted (trash) album cached counts to match actual trashed assets",
    )
    fix_trash_parser.add_argument(
        "library",
        metavar="LIBRARY",
        help="Path to Photos library (.photoslibrary)",
    )
    fix_trash_parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose logging",
    )
    fix_trash_parser.add_argument(
        "-q", "--quiet",
        action="store_true",
        help="Suppress non-error output",
    )

    return parser


def run_sync(parsed: argparse.Namespace) -> int:
    """Run the sync subcommand.

    Args:
        parsed: Parsed command line arguments

    Returns:
        Exit code
    """
    # Validate paths
    valid, code, error = validate_library_path(parsed.source, "source")
    if not valid:
        print(f"Error: {error}", file=sys.stderr)
        return code

    valid, code, error = validate_library_path(parsed.target, "target")
    if not valid:
        print(f"Error: {error}", file=sys.stderr)
        return code

    # Print header
    if not parsed.quiet and not parsed.json:
        print(f"Syncing from: {parsed.source}")
        print(f"          to: {parsed.target}")
        print()

    try:
        start_time = time.time()

        if parsed.dry_run:
            # Dry-run mode
            if not parsed.quiet and not parsed.json:
                print("Analyzing libraries...")

            plan = create_sync_plan(
                parsed.source,
                parsed.target,
                skip_delete=parsed.no_delete,
                skip_albums=parsed.no_albums,
            )

            output = format_sync_plan(plan, json_output=parsed.json)
            print(output)
            return EXIT_SUCCESS

        else:
            # Actual sync
            def progress_callback(current: int, total: int, message: str):
                print_progress(current, total, message, quiet=parsed.quiet)

            result = sync_photos(
                parsed.source,
                parsed.target,
                skip_delete=parsed.no_delete,
                skip_albums=parsed.no_albums,
                verify=parsed.verify,
                full=parsed.full,
                progress_callback=None if parsed.quiet else progress_callback,
            )

            elapsed = time.time() - start_time
            output = format_result(result, json_output=parsed.json, elapsed=elapsed)
            print(output)

            return EXIT_SUCCESS if result.success else EXIT_ERROR

    except SchemaVersionMismatchError as e:
        logger.error(f"Schema version mismatch: {e}")
        if parsed.json:
            print(json.dumps({"status": "error", "error": str(e)}))
        else:
            print(f"Error: {e}", file=sys.stderr)
        return EXIT_SCHEMA_MISMATCH

    except DatabaseLockedError as e:
        logger.error(f"Database locked: {e}")
        if parsed.json:
            print(json.dumps({"status": "error", "error": str(e)}))
        else:
            print("Error: Database is locked. Close Photos app and try again.", file=sys.stderr)
        return EXIT_DB_LOCKED

    except DatabaseNotFoundError as e:
        logger.error(f"Database not found: {e}")
        if parsed.json:
            print(json.dumps({"status": "error", "error": str(e)}))
        else:
            print(f"Error: {e}", file=sys.stderr)
        return EXIT_SOURCE_NOT_FOUND

    except DiskFullError as e:
        logger.error(f"Disk full: {e}")
        if parsed.json:
            print(json.dumps({"status": "error", "error": str(e)}))
        else:
            print(f"Error: Insufficient disk space. {e}", file=sys.stderr)
        return EXIT_DISK_FULL

    except PermissionError as e:
        logger.error(f"Permission denied: {e}")
        if parsed.json:
            print(json.dumps({"status": "error", "error": str(e)}))
        else:
            print("Error: Permission denied. Check file permissions.", file=sys.stderr)
        return EXIT_PERMISSION_DENIED

    except Exception as e:
        logger.exception(f"Unexpected error: {e}")
        if parsed.json:
            print(json.dumps({"status": "error", "error": str(e)}))
        else:
            print(f"Error: {e}", file=sys.stderr)
        return EXIT_ERROR


def run_dedup(parsed: argparse.Namespace) -> int:
    """Run the dedup subcommand.

    Args:
        parsed: Parsed command line arguments

    Returns:
        Exit code
    """
    valid, code, error = validate_library_path(parsed.library, "library")
    if not valid:
        print(f"Error: {error}", file=sys.stderr)
        return code

    try:
        start_time = time.time()

        if parsed.dry_run:
            if not parsed.quiet and not parsed.json:
                print(f"Analyzing album \"{parsed.album}\" for duplicates...")

            from photo_sync.db.connection import connect_readonly
            conn = connect_readonly(parsed.library)
            try:
                report = dedup_album_dry_run(conn, album_title=parsed.album)
                output = format_dedup_report(report, json_output=parsed.json)
                print(output)
                return EXIT_SUCCESS
            finally:
                conn.close()

        else:
            if not parsed.quiet and not parsed.json:
                print(f"Deduplicating album \"{parsed.album}\"...")

            from photo_sync.db.connection import connect_readwrite
            conn = connect_readwrite(parsed.library)
            try:
                result = dedup_album_execute(conn, album_title=parsed.album)
                elapsed = time.time() - start_time
                output = format_dedup_result(result, json_output=parsed.json, elapsed=elapsed)
                print(output)
                return EXIT_SUCCESS if not result["errors"] else EXIT_ERROR
            finally:
                conn.close()

    except ValueError as e:
        if parsed.json:
            print(json.dumps({"status": "error", "error": str(e)}))
        else:
            print(f"Error: {e}", file=sys.stderr)
        return EXIT_INVALID_ARGS

    except DatabaseLockedError as e:
        logger.error(f"Database locked: {e}")
        if parsed.json:
            print(json.dumps({"status": "error", "error": str(e)}))
        else:
            print("Error: Database is locked. Close Photos app and try again.", file=sys.stderr)
        return EXIT_DB_LOCKED

    except Exception as e:
        logger.exception(f"Unexpected error: {e}")
        if parsed.json:
            print(json.dumps({"status": "error", "error": str(e)}))
        else:
            print(f"Error: {e}", file=sys.stderr)
        return EXIT_ERROR


def run_fix_trash(parsed: argparse.Namespace) -> int:
    """Run the fix-trash subcommand."""
    valid, code, error = validate_library_path(parsed.library, "library")
    if not valid:
        print(f"Error: {error}", file=sys.stderr)
        return code

    try:
        from photo_sync.db.connection import connect_readwrite
        conn = connect_readwrite(parsed.library)
        try:
            # Get current state
            row = conn.execute(
                "SELECT ZCACHEDCOUNT FROM ZGENERICALBUM WHERE ZKIND = 3999"
            ).fetchone()
            if row is None:
                print("Error: No trash album found in this library.", file=sys.stderr)
                return EXIT_ERROR

            old_count = row[0]

            # Count trashed assets and update
            counts = conn.execute(
                """
                SELECT COUNT(*),
                       SUM(CASE WHEN ZKIND = 0 THEN 1 ELSE 0 END),
                       SUM(CASE WHEN ZKIND = 1 THEN 1 ELSE 0 END)
                FROM ZASSET WHERE ZTRASHEDSTATE = 1
                """
            ).fetchone()

            total = counts[0] or 0
            photos = counts[1] or 0
            videos = counts[2] or 0

            conn.execute(
                """
                UPDATE ZGENERICALBUM
                SET ZCACHEDCOUNT = ?, ZCACHEDPHOTOSCOUNT = ?, ZCACHEDVIDEOSCOUNT = ?,
                    Z_OPT = Z_OPT + 1
                WHERE ZKIND = 3999
                """,
                (total, photos, videos)
            )
            conn.commit()

            if not parsed.quiet:
                print(f"Trash album updated: {old_count} -> {total} ({photos} photos, {videos} videos)")

            return EXIT_SUCCESS
        finally:
            conn.close()

    except DatabaseLockedError:
        print("Error: Database is locked. Close Photos app and try again.", file=sys.stderr)
        return EXIT_DB_LOCKED

    except Exception as e:
        logger.exception(f"Unexpected error: {e}")
        print(f"Error: {e}", file=sys.stderr)
        return EXIT_ERROR


DEFAULT_SYNC_ALL_CONFIG = "sync-all.config.json"


def load_sync_all_pairs(config_path: str) -> list[tuple[str, str]]:
    """Load source/target library pairs from a JSON config file.

    Expected format::

        {"pairs": [{"source": "/path/a.photoslibrary",
                    "target": "/path/b.photoslibrary"}]}

    Args:
        config_path: Path to the JSON config file.

    Returns:
        List of (source, target) path tuples.

    Raises:
        FileNotFoundError: If the config file does not exist.
        ValueError: If the config is malformed.
    """
    path = Path(config_path)
    if not path.is_file():
        raise FileNotFoundError(config_path)

    data = json.loads(path.read_text())
    pairs: list[tuple[str, str]] = []
    for entry in data.get("pairs", []):
        try:
            pairs.append((entry["source"], entry["target"]))
        except (TypeError, KeyError) as exc:
            raise ValueError(
                f"each pair needs 'source' and 'target' keys, got: {entry!r}"
            ) from exc
    return pairs


def _mount_roots(pairs: list[tuple[str, str]]) -> list[str]:
    """Derive the distinct `/Volumes/<name>` mount roots referenced by pairs."""
    roots = set()
    for source, target in pairs:
        for p in (source, target):
            parts = Path(p).parts
            if len(parts) >= 3 and parts[1] == "Volumes":
                roots.add(str(Path(parts[0], parts[1], parts[2])))
    return sorted(roots)


def run_sync_all(parsed: argparse.Namespace) -> int:
    """Run the sync-all subcommand — sync every library pair from the config."""
    try:
        pairs = load_sync_all_pairs(parsed.config)
    except FileNotFoundError:
        print(
            f"Error: sync-all config not found: {parsed.config}\n"
            f"Copy sync-all.config.example.json to {parsed.config} and edit it.",
            file=sys.stderr,
        )
        return EXIT_ERROR
    except (json.JSONDecodeError, ValueError) as e:
        print(f"Error: invalid sync-all config {parsed.config}: {e}", file=sys.stderr)
        return EXIT_INVALID_ARGS

    if not pairs:
        print(f"Error: no library pairs configured in {parsed.config}", file=sys.stderr)
        return EXIT_ERROR

    # Check any external drives referenced by the config are mounted
    for drive in _mount_roots(pairs):
        if not Path(drive).is_dir():
            print(f"Error: Drive not mounted: {drive}", file=sys.stderr)
            return EXIT_ERROR

    # Validate all libraries exist before starting
    for source, target in pairs:
        valid, code, error = validate_library_path(source, "source")
        if not valid:
            print(f"Error: {error}", file=sys.stderr)
            return code
        valid, code, error = validate_library_path(target, "target")
        if not valid:
            print(f"Error: {error}", file=sys.stderr)
            return code

    overall_start = time.time()
    failed = []

    for i, (source, target) in enumerate(pairs, 1):
        source_name = Path(source).name
        separator = "=" * 60
        if not parsed.quiet:
            print(f"\n{separator}")
            print(f"[{i}/{len(pairs)}] {source_name}")
            print(f"  src: {source}")
            print(f"  dst: {target}")
            print(separator)

        try:
            start_time = time.time()

            if parsed.dry_run:
                plan = create_sync_plan(
                    source, target,
                    skip_delete=parsed.no_delete,
                    skip_albums=parsed.no_albums,
                )
                print(format_sync_plan(plan))
            else:
                def progress_callback(current: int, total: int, message: str):
                    print_progress(current, total, message, quiet=parsed.quiet)

                result = sync_photos(
                    source, target,
                    skip_delete=parsed.no_delete,
                    skip_albums=parsed.no_albums,
                    verify=parsed.verify,
                    full=parsed.full,
                    progress_callback=None if parsed.quiet else progress_callback,
                )
                elapsed = time.time() - start_time
                print(format_result(result, elapsed=elapsed))
                if not result.success:
                    failed.append(source_name)

        except SchemaVersionMismatchError as e:
            print(f"  Skipped — schema version mismatch.\n  {e}", file=sys.stderr)
            failed.append(source_name)

        except Exception as e:
            logger.exception(f"Error syncing {source_name}: {e}")
            print(f"Error: {e}", file=sys.stderr)
            failed.append(source_name)

    overall_elapsed = time.time() - overall_start
    if not parsed.quiet:
        print(f"\n{'=' * 60}")
        print(f"All done in {overall_elapsed:.1f}s — "
              f"{len(pairs) - len(failed)}/{len(pairs)} succeeded")
        if failed:
            print(f"Failed: {', '.join(failed)}")

    return EXIT_ERROR if failed else EXIT_SUCCESS


def main(args: list[str] | None = None) -> int:
    """Main CLI entry point.

    Args:
        args: Command line arguments (defaults to sys.argv)

    Returns:
        Exit code
    """
    parser = create_parser()
    parsed = parser.parse_args(args)

    if not parsed.command:
        parser.print_help()
        return EXIT_INVALID_ARGS

    # Setup logging
    setup_logging(verbose=parsed.verbose, quiet=parsed.quiet)

    if parsed.command == "sync":
        return run_sync(parsed)
    elif parsed.command == "dedup":
        return run_dedup(parsed)
    elif parsed.command == "fix-trash":
        return run_fix_trash(parsed)
    elif parsed.command == "sync-all":
        return run_sync_all(parsed)
    else:
        parser.print_help()
        return EXIT_INVALID_ARGS


if __name__ == "__main__":
    sys.exit(main())
