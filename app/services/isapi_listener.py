"""
Hikvision AI CCTV Platform — ISAPI Alert Stream Listener
Long-polls the Hikvision NVR/DVR ISAPI Event notification alertStream
endpoint, parses XML event payloads, and dispatches them to the AI pipeline.
"""

import asyncio
import logging
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional, Callable, Awaitable, List

import httpx

from app.config import settings

logger = logging.getLogger("cctv.isapi_listener")


class ISAPIEventType(str, Enum):
    """Hikvision ISAPI smart event types."""
    LINE_CROSSING = "linedetection"
    INTRUSION = "fielddetection"
    MOTION = "VMD"
    FACE_DETECTION = "facedetection"
    REGION_ENTRANCE = "regionEntrance"
    REGION_EXIT = "regionExiting"
    LOITERING = "loitering"
    SCENE_CHANGE = "scenechangedetection"
    UNATTENDED_BAGGAGE = "unattendedBaggage"
    AUDIO_EXCEPTION = "audioexception"


@dataclass
class ISAPIEvent:
    """Parsed Hikvision ISAPI alert event."""
    event_type: str
    channel_id: int
    timestamp: datetime
    is_active: bool = True
    target_type: str = "unknown"  # 'human', 'vehicle', 'unknown'
    confidence: float = 0.0
    recorder_ip: str = ""
    raw_xml: str = ""
    detection_region: List[dict] = field(default_factory=list)

    @property
    def event_source(self) -> str:
        return f"isapi_{self.event_type}"


def parse_isapi_xml(xml_text: str, recorder_ip: str = "") -> Optional[ISAPIEvent]:
    """
    Parse a Hikvision ISAPI XML event notification block.

    Hikvision uses the namespace: http://www.hikvision.com/ver20/XMLSchema
    The XML contains <EventNotificationAlert> as root with children like:
    - <eventType>
    - <channelID>
    - <dateTime>
    - <activePostCount> / <eventState>
    - <DetectionRegionList> with <DetectionRegionEntry>
        - <targetAttrs> containing <human>/<vehicle>
    """
    try:
        # Strip namespace for simpler parsing
        xml_clean = re.sub(r'xmlns="[^"]+"', '', xml_text)
        root = ET.fromstring(xml_clean)

        event_type_el = root.find(".//eventType")
        channel_el = root.find(".//channelID") or root.find(".//dynChannelID")
        datetime_el = root.find(".//dateTime")
        state_el = root.find(".//eventState")

        if event_type_el is None:
            return None

        event_type = event_type_el.text.strip() if event_type_el.text else "unknown"
        channel_id = int(channel_el.text.strip()) if channel_el is not None and channel_el.text else 1

        # Parse timestamp
        ts = datetime.now(timezone.utc)
        if datetime_el is not None and datetime_el.text:
            try:
                ts_text = datetime_el.text.strip()
                # Hikvision format: 2026-10-26T23:01:56+05:30
                ts = datetime.fromisoformat(ts_text)
            except (ValueError, TypeError):
                pass

        # Determine if event is active or stopped
        is_active = True
        if state_el is not None and state_el.text:
            is_active = state_el.text.strip().lower() in ("active", "1")

        # Extract AcuSense target classification (human/vehicle)
        target_type = "unknown"
        confidence = 0.0
        for target_el in root.findall(".//DetectionRegionEntry"):
            # Check for <sensitivityLevel> or <targetAttrs>
            human_el = target_el.find(".//human")
            vehicle_el = target_el.find(".//vehicle")
            if human_el is not None:
                target_type = "human"
            elif vehicle_el is not None:
                target_type = "vehicle"

            # Extract confidence if available
            conf_el = target_el.find(".//confidence")
            if conf_el is not None and conf_el.text:
                try:
                    confidence = float(conf_el.text.strip()) / 100.0
                except (ValueError, TypeError):
                    pass

        # Also check <targetAttrs> at root level for simpler cameras
        if target_type == "unknown":
            for target_attr in root.findall(".//targetAttrs"):
                human_el = target_attr.find("human")
                vehicle_el = target_attr.find("vehicle")
                if human_el is not None:
                    target_type = "human"
                elif vehicle_el is not None:
                    target_type = "vehicle"

        return ISAPIEvent(
            event_type=event_type,
            channel_id=channel_id,
            timestamp=ts,
            is_active=is_active,
            target_type=target_type,
            confidence=confidence,
            recorder_ip=recorder_ip,
            raw_xml=xml_text,
        )

    except ET.ParseError as e:
        logger.warning(f"Failed to parse ISAPI XML: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error parsing ISAPI event: {e}", exc_info=True)
        return None


class ISAPIListener:
    """
    Async long-polling listener for Hikvision ISAPI alertStream.
    Connects to each recorder and streams multipart HTTP events continuously.
    """

    def __init__(
        self,
        on_event: Callable[[ISAPIEvent], Awaitable[None]],
    ):
        self.on_event = on_event
        self._tasks: List[asyncio.Task] = []
        self._running = False

    async def start(self):
        """Start listening to all configured recorder ISAPI streams."""
        self._running = True

        recorders = [
            {
                "ip": settings.hik_nvr_ip,
                "user": settings.hik_nvr_user,
                "password": settings.hik_nvr_password,
                "label": "NVR",
            },
            {
                "ip": settings.hik_dvr_ip,
                "user": settings.hik_dvr_user,
                "password": settings.hik_dvr_password,
                "label": "DVR",
            },
        ]

        for rec in recorders:
            task = asyncio.create_task(
                self._listen_recorder(rec), name=f"isapi_{rec['label']}"
            )
            self._tasks.append(task)
            logger.info(f"Started ISAPI listener for {rec['label']} @ {rec['ip']}")

    async def stop(self):
        """Stop all listener tasks gracefully."""
        self._running = False
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
        logger.info("All ISAPI listeners stopped.")

    async def _listen_recorder(self, recorder: dict):
        """
        Long-poll a single recorder's ISAPI alert stream.
        Hikvision sends multipart/mixed HTTP response with XML blocks
        separated by boundary markers.
        """
        url = f"http://{recorder['ip']}/ISAPI/Event/notification/alertStream"
        auth = httpx.DigestAuth(recorder["user"], recorder["password"])
        reconnect_delay = 5

        while self._running:
            try:
                logger.info(
                    f"Connecting to ISAPI alertStream: {recorder['label']} @ {recorder['ip']}"
                )

                async with httpx.AsyncClient(
                    auth=auth,
                    timeout=httpx.Timeout(connect=10, read=None, write=10, pool=10),
                    verify=False,
                ) as client:
                    async with client.stream("GET", url) as response:
                        response.raise_for_status()
                        logger.info(
                            f"Connected to {recorder['label']} ISAPI stream (HTTP {response.status_code})"
                        )

                        xml_buffer = ""
                        async for chunk in response.aiter_text(chunk_size=4096):
                            if not self._running:
                                break

                            xml_buffer += chunk

                            # Hikvision separates XML blocks with boundaries
                            # like: --boundary\r\nContent-Type: ...\r\nContent-Length: ...\r\n\r\n<XML>
                            while "<EventNotificationAlert" in xml_buffer and "</EventNotificationAlert>" in xml_buffer:
                                start = xml_buffer.index("<EventNotificationAlert")
                                end = xml_buffer.index("</EventNotificationAlert>") + len("</EventNotificationAlert>")
                                xml_block = xml_buffer[start:end]
                                xml_buffer = xml_buffer[end:]

                                event = parse_isapi_xml(xml_block, recorder_ip=recorder["ip"])
                                if event and event.is_active:
                                    logger.info(
                                        f"[{recorder['label']}] Event: {event.event_type} "
                                        f"ch:{event.channel_id} target:{event.target_type}"
                                    )
                                    try:
                                        await self.on_event(event)
                                    except Exception as e:
                                        logger.error(
                                            f"Error handling ISAPI event: {e}",
                                            exc_info=True,
                                        )

            except httpx.HTTPStatusError as e:
                logger.error(
                    f"ISAPI HTTP error for {recorder['label']}: {e.response.status_code}"
                )
            except (httpx.ConnectError, httpx.ReadTimeout, httpx.RemoteProtocolError) as e:
                logger.warning(
                    f"ISAPI connection lost for {recorder['label']}: {type(e).__name__}"
                )
            except asyncio.CancelledError:
                logger.info(f"ISAPI listener for {recorder['label']} cancelled.")
                return
            except Exception as e:
                logger.error(
                    f"Unexpected ISAPI error for {recorder['label']}: {e}",
                    exc_info=True,
                )

            if self._running:
                logger.info(
                    f"Reconnecting to {recorder['label']} ISAPI in {reconnect_delay}s..."
                )
                await asyncio.sleep(reconnect_delay)
                reconnect_delay = min(reconnect_delay * 2, 60)  # Exponential backoff
