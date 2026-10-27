"""
Hikvision AI CCTV Platform — Telegram Alert Notifier
Sends rich alert cards with bounding-box-annotated snapshots
to a configured Telegram chat via the Bot API.
"""

import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, List

import cv2
import numpy as np

from app.config import settings

logger = logging.getLogger("cctv.telegram_notifier")


class TelegramNotifier:
    """Async Telegram Bot for sending AI alert notifications with images."""

    def __init__(self):
        self._bot = None
        self._enabled = False

    async def initialize(self):
        """Initialize the Telegram bot. Silently disables if no token configured."""
        if not settings.telegram_bot_token or settings.telegram_bot_token.startswith("your-"):
            logger.warning("Telegram bot token not configured — notifications disabled.")
            self._enabled = False
            return

        try:
            from telegram import Bot
            self._bot = Bot(token=settings.telegram_bot_token)
            bot_info = await self._bot.get_me()
            logger.info(f"Telegram bot initialized: @{bot_info.username}")
            self._enabled = True
        except Exception as e:
            logger.error(f"Failed to initialize Telegram bot: {e}")
            self._enabled = False

    async def send_alert(
        self,
        event_type: str,
        target_type: str,
        camera_name: str,
        confidence: float,
        snapshot_path: Optional[str] = None,
        image: Optional[np.ndarray] = None,
        bboxes: Optional[List[dict]] = None,
        extra_info: str = "",
    ):
        """
        Send an AI detection alert to the configured Telegram chat.

        Args:
            event_type: e.g. "isapi_linedetection", "frigate_detection"
            target_type: e.g. "human", "vehicle", "face"
            camera_name: Human-readable camera name
            confidence: Detection confidence (0.0 - 1.0)
            snapshot_path: Path to saved snapshot JPEG
            image: Optional OpenCV image to annotate and send
            bboxes: Optional list of {"label": str, "bbox": [y1,x1,y2,x2], "conf": float}
            extra_info: Additional text (plate number, face match name, etc.)
        """
        if not self._enabled:
            return

        try:
            # Build alert message
            ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
            severity = self._classify_severity(event_type, target_type)

            message = (
                f"{severity} <b>AI Security Alert</b>\n\n"
                f"📷 <b>Camera:</b> {camera_name}\n"
                f"🏷️ <b>Type:</b> {self._format_event_type(event_type)}\n"
                f"🎯 <b>Target:</b> {target_type.title()}\n"
                f"📊 <b>Confidence:</b> {confidence:.0%}\n"
                f"🕐 <b>Time:</b> {ts}\n"
            )

            if extra_info:
                message += f"\nℹ️ {extra_info}\n"

            # Annotate image with bounding boxes if provided
            annotated_path = None
            if image is not None and bboxes:
                annotated_path = self._annotate_image(image, bboxes)
            elif snapshot_path and Path(snapshot_path).exists():
                annotated_path = snapshot_path

            # Send via Telegram Bot API
            chat_id = settings.telegram_chat_id
            if annotated_path and Path(annotated_path).exists():
                await self._send_photo(chat_id, annotated_path, message)
            else:
                await self._send_text(chat_id, message)

            logger.info(f"Telegram alert sent: {target_type} on {camera_name}")

        except Exception as e:
            logger.error(f"Failed to send Telegram alert: {e}", exc_info=True)

    async def _send_photo(self, chat_id: str, photo_path: str, caption: str):
        """Send a photo with caption to Telegram."""
        try:
            with open(photo_path, "rb") as photo_file:
                await self._bot.send_photo(
                    chat_id=chat_id,
                    photo=photo_file,
                    caption=caption[:1024],  # Telegram caption limit
                    parse_mode="HTML",
                )
        except Exception as e:
            logger.error(f"Telegram send_photo error: {e}")
            # Fallback to text-only
            await self._send_text(chat_id, caption)

    async def _send_text(self, chat_id: str, text: str):
        """Send a text message to Telegram."""
        try:
            await self._bot.send_message(
                chat_id=chat_id,
                text=text[:4096],  # Telegram message limit
                parse_mode="HTML",
            )
        except Exception as e:
            logger.error(f"Telegram send_message error: {e}")

    def _annotate_image(
        self,
        image: np.ndarray,
        bboxes: List[dict],
    ) -> Optional[str]:
        """
        Draw bounding boxes and labels on the image.
        Returns path to the annotated temporary image file.
        """
        try:
            annotated = image.copy()
            h, w = annotated.shape[:2]

            color_map = {
                "human": (0, 200, 255),    # Orange
                "person": (0, 200, 255),
                "vehicle": (255, 180, 0),  # Blue
                "car": (255, 180, 0),
                "truck": (255, 180, 0),
                "face": (0, 255, 100),     # Green
                "plate": (100, 100, 255),  # Red
            }

            for bbox_info in bboxes:
                label = bbox_info.get("label", "unknown")
                bbox = bbox_info.get("bbox", [])
                conf = bbox_info.get("conf", 0.0)

                if len(bbox) != 4:
                    continue

                y1, x1, y2, x2 = bbox
                y1, y2 = max(0, y1), min(h, y2)
                x1, x2 = max(0, x1), min(w, x2)

                color = color_map.get(label.lower(), (200, 200, 200))

                # Draw bounding box
                cv2.rectangle(annotated, (x1, y1), (x2, y2), color, 2)

                # Draw label background
                text = f"{label} {conf:.0%}"
                (tw, th), baseline = cv2.getTextSize(
                    text, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1
                )
                cv2.rectangle(
                    annotated,
                    (x1, y1 - th - baseline - 4),
                    (x1 + tw + 4, y1),
                    color,
                    -1,
                )
                cv2.putText(
                    annotated,
                    text,
                    (x1 + 2, y1 - baseline - 2),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.5,
                    (255, 255, 255),
                    1,
                )

            # Save annotated image
            temp_path = settings.media_path / "snapshots" / f"alert_annotated_{id(image)}.jpg"
            cv2.imwrite(str(temp_path), annotated, [cv2.IMWRITE_JPEG_QUALITY, 90])
            return str(temp_path)

        except Exception as e:
            logger.error(f"Image annotation failed: {e}")
            return None

    def _classify_severity(self, event_type: str, target_type: str) -> str:
        """Map event types to emoji severity indicators."""
        if target_type == "human" and "intrusion" in event_type:
            return "🚨"
        if target_type == "face":
            return "👤"
        if target_type in ("vehicle", "car"):
            return "🚗"
        if "line" in event_type:
            return "⚠️"
        return "🔔"

    def _format_event_type(self, event_type: str) -> str:
        """Human-readable event type formatting."""
        formatting = {
            "isapi_linedetection": "Line Crossing",
            "isapi_fielddetection": "Intrusion Detection",
            "isapi_VMD": "Motion Detected",
            "isapi_facedetection": "Face Detected",
            "frigate_detection": "Object Detected",
            "isapi_regionEntrance": "Region Entry",
            "isapi_regionExiting": "Region Exit",
            "isapi_loitering": "Loitering Alert",
        }
        return formatting.get(event_type, event_type.replace("_", " ").title())

    @property
    def is_enabled(self) -> bool:
        return self._enabled
