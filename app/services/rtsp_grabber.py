"""
Hikvision AI CCTV Platform — High-Res Snapshot Grabber
Extracts full-resolution JPEG snapshots from cameras via:
  1. Hikvision ISAPI /picture endpoint (fastest, no decode)
  2. FFmpeg RTSP single-frame grab (fallback)
"""

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import cv2
import httpx
import numpy as np

from app.config import settings

logger = logging.getLogger("cctv.rtsp_grabber")


class SnapshotGrabber:
    """Grabs high-resolution snapshots from cameras using ISAPI or RTSP fallback."""

    def __init__(self):
        self.media_dir = settings.media_path / "snapshots"
        self.crops_dir = settings.media_path / "crops"
        self.media_dir.mkdir(parents=True, exist_ok=True)
        self.crops_dir.mkdir(parents=True, exist_ok=True)

    async def grab_snapshot(
        self,
        recorder_ip: str,
        channel_id: int,
        username: str = None,
        password: str = None,
    ) -> Optional[str]:
        """
        Grab a high-res snapshot, preferring ISAPI HTTP then falling back to RTSP.
        Returns the saved file path relative to media_dir, or None on failure.
        """
        username = username or settings.hik_nvr_user
        password = password or settings.hik_nvr_password

        # Try ISAPI snapshot first (fastest — no RTSP decode needed)
        snapshot_path = await self._grab_isapi(recorder_ip, channel_id, username, password)
        if snapshot_path:
            return snapshot_path

        # Fallback: RTSP single-frame grab
        return await self._grab_rtsp_frame(recorder_ip, channel_id, username, password)

    async def _grab_isapi(
        self,
        recorder_ip: str,
        channel_id: int,
        username: str,
        password: str,
    ) -> Optional[str]:
        """Grab snapshot via Hikvision ISAPI HTTP /picture endpoint."""
        # Channel mapping: channel_id 1 → Channels/101, channel 2 → Channels/201
        channel_str = f"{channel_id}01"
        url = f"http://{recorder_ip}/ISAPI/Streaming/channels/{channel_str}/picture"

        try:
            async with httpx.AsyncClient(
                auth=httpx.DigestAuth(username, password),
                timeout=httpx.Timeout(connect=5, read=10, write=5, pool=5),
                verify=False,
            ) as client:
                response = await client.get(url)
                response.raise_for_status()

                if response.headers.get("content-type", "").startswith("image/"):
                    filename = self._generate_filename(recorder_ip, channel_id)
                    filepath = self.media_dir / filename
                    filepath.write_bytes(response.content)
                    logger.info(f"ISAPI snapshot saved: {filepath}")
                    return str(filepath)
                else:
                    logger.warning(
                        f"ISAPI snapshot returned non-image content-type: "
                        f"{response.headers.get('content-type')}"
                    )
                    return None

        except httpx.HTTPStatusError as e:
            logger.warning(f"ISAPI snapshot HTTP {e.response.status_code} for ch:{channel_id}")
            return None
        except Exception as e:
            logger.warning(f"ISAPI snapshot failed for ch:{channel_id}: {e}")
            return None

    async def _grab_rtsp_frame(
        self,
        recorder_ip: str,
        channel_id: int,
        username: str,
        password: str,
    ) -> Optional[str]:
        """Grab a single frame from RTSP main stream using OpenCV."""
        channel_str = f"{channel_id}01"
        rtsp_url = (
            f"rtsp://{username}:{password}@{recorder_ip}:554"
            f"/Streaming/Channels/{channel_str}"
        )

        try:
            # Run blocking OpenCV capture in thread pool
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None, self._capture_rtsp_frame, rtsp_url, recorder_ip, channel_id
            )
            return result
        except Exception as e:
            logger.error(f"RTSP frame grab failed for ch:{channel_id}: {e}")
            return None

    def _capture_rtsp_frame(
        self, rtsp_url: str, recorder_ip: str, channel_id: int
    ) -> Optional[str]:
        """Blocking RTSP single-frame capture via OpenCV."""
        cap = cv2.VideoCapture(rtsp_url, cv2.CAP_FFMPEG)
        try:
            if not cap.isOpened():
                logger.warning(f"Cannot open RTSP stream: {rtsp_url}")
                return None

            ret, frame = cap.read()
            if not ret or frame is None:
                logger.warning(f"Failed to read frame from: {rtsp_url}")
                return None

            filename = self._generate_filename(recorder_ip, channel_id)
            filepath = self.media_dir / filename
            cv2.imwrite(str(filepath), frame, [cv2.IMWRITE_JPEG_QUALITY, 92])
            logger.info(f"RTSP snapshot saved: {filepath}")
            return str(filepath)

        finally:
            cap.release()

    def save_crop(
        self,
        image: np.ndarray,
        bbox: list,
        label: str = "crop",
    ) -> Optional[str]:
        """
        Crop and save a sub-region from an image (for face/plate crops).
        bbox format: [y_min, x_min, y_max, x_max]
        """
        try:
            y1, x1, y2, x2 = bbox
            h, w = image.shape[:2]
            # Clamp coordinates
            y1, y2 = max(0, y1), min(h, y2)
            x1, x2 = max(0, x1), min(w, x2)

            if y2 <= y1 or x2 <= x1:
                return None

            crop = image[y1:y2, x1:x2]
            crop_id = uuid.uuid4().hex[:12]
            ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            filename = f"{label}_{ts}_{crop_id}.jpg"
            filepath = self.crops_dir / filename
            cv2.imwrite(str(filepath), crop, [cv2.IMWRITE_JPEG_QUALITY, 95])
            return str(filepath)

        except Exception as e:
            logger.error(f"Failed to save crop: {e}")
            return None

    def _generate_filename(self, recorder_ip: str, channel_id: int) -> str:
        """Generate a unique timestamped filename for snapshots."""
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
        ip_short = recorder_ip.replace(".", "-")
        return f"snap_{ip_short}_ch{channel_id}_{ts}.jpg"
