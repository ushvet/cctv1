"""
Hikvision AI CCTV Platform — WebSocket Hub
Real-time event broadcast to connected dashboard clients.
"""

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Set

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = logging.getLogger("cctv.websocket")

router = APIRouter(tags=["websocket"])


class ConnectionManager:
    """Manages active WebSocket connections for real-time broadcasting."""

    def __init__(self):
        self._active: Set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket):
        """Accept and register a new WebSocket client."""
        await websocket.accept()
        async with self._lock:
            self._active.add(websocket)
        logger.info(f"WebSocket client connected. Total: {len(self._active)}")

    async def disconnect(self, websocket: WebSocket):
        """Remove a disconnected WebSocket client."""
        async with self._lock:
            self._active.discard(websocket)
        logger.info(f"WebSocket client disconnected. Total: {len(self._active)}")

    async def broadcast(self, message: dict):
        """Broadcast a JSON message to all connected clients."""
        if not self._active:
            return

        payload = json.dumps(message, default=str)
        disconnected = set()

        async with self._lock:
            for ws in self._active:
                try:
                    await ws.send_text(payload)
                except Exception:
                    disconnected.add(ws)

            self._active -= disconnected

    async def broadcast_event(
        self,
        event_type: str,
        target_type: str,
        camera_name: str,
        confidence: float,
        snapshot_path: str = None,
        extra: dict = None,
    ):
        """Broadcast a structured AI detection event."""
        message = {
            "type": "ai_alert",
            "event_type": event_type,
            "target_type": target_type,
            "camera_name": camera_name,
            "confidence": round(confidence, 3),
            "snapshot_path": snapshot_path,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        if extra:
            message.update(extra)

        await self.broadcast(message)

    @property
    def client_count(self) -> int:
        return len(self._active)


# Singleton connection manager
ws_manager = ConnectionManager()


@router.websocket("/ws/events")
async def websocket_events(websocket: WebSocket):
    """
    WebSocket endpoint for real-time AI alert streaming.
    
    Clients connect to receive live JSON event payloads:
    {
        "type": "ai_alert",
        "event_type": "isapi_linedetection",
        "target_type": "human",
        "camera_name": "Front Gate Panoramic",
        "confidence": 0.87,
        "snapshot_path": "/media/snapshots/snap_xxx.jpg",
        "timestamp": "2026-10-26T23:15:00Z"
    }
    """
    await ws_manager.connect(websocket)
    try:
        while True:
            # Keep connection alive, handle client messages
            data = await websocket.receive_text()
            try:
                msg = json.loads(data)
                msg_type = msg.get("type")

                if msg_type == "ping":
                    await websocket.send_text(json.dumps({"type": "pong"}))
                elif msg_type == "acknowledge":
                    event_id = msg.get("event_id")
                    if event_id:
                        logger.info(f"WebSocket client acknowledged event: {event_id}")

            except json.JSONDecodeError:
                pass

    except WebSocketDisconnect:
        await ws_manager.disconnect(websocket)
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        await ws_manager.disconnect(websocket)
