"""
Hikvision AI CCTV Platform — Media Retention Manager
Background worker that enforces a rolling storage buffer (30-50 GB)
by pruning the oldest snapshots, clips, and crops using a FIFO strategy.
"""

import asyncio
import logging
import os
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Tuple

from app.config import settings

logger = logging.getLogger("cctv.retention_manager")


class RetentionManager:
    """
    Background service that monitors and prunes the media directory
    to keep disk usage within configured limits.
    """

    def __init__(self):
        self.media_dir = settings.media_path
        self.max_size_bytes = settings.media_max_size_gb * (1024 ** 3)  # Convert GB to bytes
        self.retention_days = settings.media_retention_days
        self._task = None
        self._running = False

    async def start(self):
        """Start the background retention worker."""
        self._running = True
        self._task = asyncio.create_task(self._pruning_loop(), name="retention_manager")
        logger.info(
            f"Retention manager started — max {settings.media_max_size_gb}GB, "
            f"retention {self.retention_days} days"
        )

    async def stop(self):
        """Stop the retention worker."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Retention manager stopped.")

    async def _pruning_loop(self):
        """Run pruning checks every 30 minutes."""
        while self._running:
            try:
                await self._run_pruning_cycle()
            except asyncio.CancelledError:
                return
            except Exception as e:
                logger.error(f"Pruning cycle error: {e}", exc_info=True)

            # Check every 30 minutes
            await asyncio.sleep(1800)

    async def _run_pruning_cycle(self):
        """Execute a single pruning cycle."""
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self._prune_sync)

    def _prune_sync(self):
        """Synchronous pruning logic (runs in thread pool)."""
        if not self.media_dir.exists():
            return

        # Phase 1: Remove files older than retention_days
        self._prune_by_age()

        # Phase 2: If still over quota, remove oldest files until under limit
        self._prune_by_size()

    def _prune_by_age(self):
        """Remove media files older than the retention period."""
        cutoff = datetime.now(timezone.utc) - timedelta(days=self.retention_days)
        cutoff_ts = cutoff.timestamp()
        removed_count = 0

        for subdir in ["snapshots", "clips", "crops"]:
            dir_path = self.media_dir / subdir
            if not dir_path.exists():
                continue

            for file_path in dir_path.iterdir():
                if file_path.is_file():
                    try:
                        file_mtime = file_path.stat().st_mtime
                        if file_mtime < cutoff_ts:
                            file_path.unlink()
                            removed_count += 1
                    except OSError as e:
                        logger.warning(f"Cannot remove {file_path}: {e}")

        if removed_count > 0:
            logger.info(f"Age pruning: removed {removed_count} files older than {self.retention_days} days")

    def _prune_by_size(self):
        """Remove oldest files until total usage is under the size limit."""
        total_size = self._get_total_size()

        if total_size <= self.max_size_bytes:
            return

        logger.info(
            f"Size pruning: {total_size / (1024**3):.1f}GB exceeds "
            f"{settings.media_max_size_gb}GB limit"
        )

        # Collect all media files with their timestamps
        all_files: List[Tuple[float, Path, int]] = []

        for subdir in ["snapshots", "clips", "crops"]:
            dir_path = self.media_dir / subdir
            if not dir_path.exists():
                continue

            for file_path in dir_path.iterdir():
                if file_path.is_file():
                    try:
                        stat = file_path.stat()
                        all_files.append((stat.st_mtime, file_path, stat.st_size))
                    except OSError:
                        pass

        # Sort by modification time (oldest first)
        all_files.sort(key=lambda x: x[0])

        removed_count = 0
        freed_bytes = 0

        for mtime, file_path, file_size in all_files:
            if total_size - freed_bytes <= self.max_size_bytes * 0.85:  # Prune to 85% to avoid frequent runs
                break

            try:
                file_path.unlink()
                freed_bytes += file_size
                removed_count += 1
            except OSError as e:
                logger.warning(f"Cannot remove {file_path}: {e}")

        if removed_count > 0:
            logger.info(
                f"Size pruning: removed {removed_count} files, "
                f"freed {freed_bytes / (1024**2):.1f}MB"
            )

    def _get_total_size(self) -> int:
        """Calculate total size of the media directory in bytes."""
        total = 0
        for subdir in ["snapshots", "clips", "crops"]:
            dir_path = self.media_dir / subdir
            if dir_path.exists():
                for file_path in dir_path.rglob("*"):
                    if file_path.is_file():
                        try:
                            total += file_path.stat().st_size
                        except OSError:
                            pass
        return total

    def get_storage_stats(self) -> dict:
        """Return current storage usage statistics."""
        total = self._get_total_size()
        return {
            "total_bytes": total,
            "total_mb": round(total / (1024 ** 2), 1),
            "total_gb": round(total / (1024 ** 3), 2),
            "max_gb": settings.media_max_size_gb,
            "usage_percent": round((total / self.max_size_bytes) * 100, 1) if self.max_size_bytes > 0 else 0,
            "retention_days": self.retention_days,
        }
