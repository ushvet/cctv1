"""
Hikvision AI CCTV Platform — Frigate MQTT Event Subscriber
Listens to Frigate MQTT topics for real-time motion/detection events
and dispatches them for secondary AI processing.
"""

import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Awaitable, Optional

from app.config import settings

logger = logging.getLogger("cctv.mqtt_subscriber")


@dataclass
class FrigateEvent:
    """Parsed Frigate MQTT event."""
    event_id: str
    camera: str
    label: str  # person, car, etc.
    confidence: float
    top_score: float
    start_time: float
    end_time: Optional[float]
    has_snapshot: bool
    has_clip: bool
    event_type: str  # "new", "update", "end"
    zones: list
    region: list
    area: Optional[int] = None

    @property
    def event_source(self) -> str:
        return "frigate_detection"

    @property
    def target_type(self) -> str:
        return self.label

    @property
    def timestamp(self) -> datetime:
        return datetime.fromtimestamp(self.start_time, tz=timezone.utc)


class MQTTSubscriber:
    """
    Subscribes to Frigate MQTT topics and dispatches parsed events.

    Key topics:
      - frigate/events          → Full event lifecycle (new/update/end)
      - frigate/+/person        → Per-camera person detection counts
      - frigate/+/car           → Per-camera car detection counts
      - frigate/available       → Frigate online/offline status
    """

    def __init__(self, on_event: Callable[[FrigateEvent], Awaitable[None]]):
        self.on_event = on_event
        self._task: Optional[asyncio.Task] = None
        self._running = False

    async def start(self):
        """Start the MQTT subscriber background task."""
        self._running = True
        self._task = asyncio.create_task(self._subscribe_loop(), name="mqtt_subscriber")
        logger.info(f"MQTT subscriber started — connecting to {settings.mqtt_host}:{settings.mqtt_port}")

    async def stop(self):
        """Stop the MQTT subscriber."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("MQTT subscriber stopped.")

    async def _subscribe_loop(self):
        """Main subscription loop with automatic reconnection."""
        import aiomqtt

        reconnect_delay = 5

        while self._running:
            try:
                async with aiomqtt.Client(
                    hostname=settings.mqtt_host,
                    port=settings.mqtt_port,
                    identifier="cctv_ai_backend",
                ) as client:
                    # Subscribe to Frigate event topics
                    await client.subscribe("frigate/events")
                    await client.subscribe("frigate/+/person")
                    await client.subscribe("frigate/+/car")
                    await client.subscribe("frigate/+/motorcycle")
                    await client.subscribe("frigate/+/truck")
                    await client.subscribe("frigate/available")

                    logger.info("MQTT: Subscribed to Frigate topics.")
                    reconnect_delay = 5  # Reset backoff on successful connection

                    async for message in client.messages:
                        if not self._running:
                            break

                        topic = str(message.topic)
                        payload = message.payload

                        try:
                            if topic == "frigate/events":
                                await self._handle_event(payload)
                            elif topic == "frigate/available":
                                status = payload.decode("utf-8") if isinstance(payload, bytes) else str(payload)
                                logger.info(f"Frigate status: {status}")
                            else:
                                # Per-camera object count updates (e.g., frigate/front_gate/person)
                                await self._handle_object_count(topic, payload)

                        except Exception as e:
                            logger.error(f"Error processing MQTT message on {topic}: {e}", exc_info=True)

            except asyncio.CancelledError:
                logger.info("MQTT subscriber cancelled.")
                return
            except Exception as e:
                logger.warning(f"MQTT connection error: {type(e).__name__}: {e}")

            if self._running:
                logger.info(f"MQTT reconnecting in {reconnect_delay}s...")
                await asyncio.sleep(reconnect_delay)
                reconnect_delay = min(reconnect_delay * 2, 60)

    async def _handle_event(self, payload: bytes):
        """Parse and dispatch a Frigate event payload."""
        try:
            data = json.loads(payload)
        except json.JSONDecodeError as e:
            logger.warning(f"Invalid JSON in Frigate event: {e}")
            return

        before = data.get("before", {})
        after = data.get("after", {})
        event_type = data.get("type", "update")  # "new", "update", "end"

        # Use 'after' state for current event info
        event_data = after if after else before

        if not event_data:
            return

        frigate_event = FrigateEvent(
            event_id=event_data.get("id", ""),
            camera=event_data.get("camera", "unknown"),
            label=event_data.get("label", "unknown"),
            confidence=event_data.get("current_score", 0.0),
            top_score=event_data.get("top_score", 0.0),
            start_time=event_data.get("start_time", 0.0),
            end_time=event_data.get("end_time"),
            has_snapshot=event_data.get("has_snapshot", False),
            has_clip=event_data.get("has_clip", False),
            event_type=event_type,
            zones=event_data.get("current_zones", []),
            region=event_data.get("region", []),
            area=event_data.get("area"),
        )

        # Only process "new" events to avoid duplicate processing
        if event_type == "new" and frigate_event.confidence >= 0.55:
            logger.info(
                f"Frigate event: {frigate_event.label} on {frigate_event.camera} "
                f"(conf: {frigate_event.confidence:.2f}, zones: {frigate_event.zones})"
            )
            try:
                await self.on_event(frigate_event)
            except Exception as e:
                logger.error(f"Error dispatching Frigate event: {e}", exc_info=True)

    async def _handle_object_count(self, topic: str, payload: bytes):
        """Handle per-camera object count MQTT messages."""
        try:
            parts = topic.split("/")
            if len(parts) >= 3:
                camera = parts[1]
                obj_type = parts[2]
                count = int(payload.decode("utf-8")) if isinstance(payload, bytes) else 0
                if count > 0:
                    logger.debug(f"Frigate count: {camera}/{obj_type} = {count}")
        except (ValueError, IndexError):
            pass
