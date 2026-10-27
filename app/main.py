"""
Hikvision AI CCTV Platform — FastAPI Application Entrypoint
Orchestrates all services: ISAPI listener, MQTT subscriber,
AI pipeline, Telegram notifier, retention manager, and serves
the web dashboard.
"""

import asyncio
import logging
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.config import settings

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s │ %(name)-28s │ %(levelname)-7s │ %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("cctv.main")

# -------------------------------------------------------
# Global service instances
# -------------------------------------------------------
from app.services.ai_pipeline import AIPipeline
from app.services.isapi_listener import ISAPIListener, ISAPIEvent
from app.services.mqtt_subscriber import MQTTSubscriber, FrigateEvent
from app.services.rtsp_grabber import SnapshotGrabber
from app.services.telegram_notifier import TelegramNotifier
from app.services.retention_manager import RetentionManager

ai_pipeline = AIPipeline()
snapshot_grabber = SnapshotGrabber()
telegram_notifier = TelegramNotifier()
retention_manager = RetentionManager()


# -------------------------------------------------------
# Event Processing Pipeline
# -------------------------------------------------------
async def handle_isapi_event(event: ISAPIEvent):
    """
    Process an ISAPI event from a Hikvision recorder.
    1. Grab a high-res snapshot
    2. Run through the unified AI pipeline
    3. Store results in PostgreSQL
    4. Broadcast via WebSocket & Telegram
    """
    logger.info(
        f"Processing ISAPI event: {event.event_type} ch:{event.channel_id} "
        f"target:{event.target_type} from {event.recorder_ip}"
    )

    try:
        # Determine recorder credentials
        username = settings.hik_nvr_user
        password = settings.hik_nvr_password
        if event.recorder_ip == settings.hik_dvr_ip:
            username = settings.hik_dvr_user
            password = settings.hik_dvr_password

        # 1. Grab high-res snapshot
        snapshot_path = await snapshot_grabber.grab_snapshot(
            recorder_ip=event.recorder_ip,
            channel_id=event.channel_id,
            username=username,
            password=password,
        )

        if not snapshot_path:
            logger.warning("Could not grab snapshot — skipping AI pipeline.")
            return

        # 2. Load image for AI processing
        image = cv2.imread(snapshot_path)
        if image is None:
            logger.warning(f"Could not read snapshot image: {snapshot_path}")
            return

        # 3. Run AI pipeline (selective based on target type)
        run_face = event.target_type in ("human", "unknown")
        run_lpr = event.target_type in ("vehicle", "unknown")
        pipeline_output = await ai_pipeline.process_frame(
            image,
            run_detection=True,
            run_face=run_face,
            run_lpr=run_lpr,
            run_clip=True,
        )

        # 4. Store results in database
        await _store_event_results(
            event_source=event.event_source,
            target_type=event.target_type,
            confidence=event.confidence,
            snapshot_path=snapshot_path,
            pipeline_output=pipeline_output,
            recorder_ip=event.recorder_ip,
            channel_id=event.channel_id,
            image=image,
        )

        # 5. Broadcast to WebSocket clients
        from app.api.routers.websocket import ws_manager
        camera_name = f"Ch{event.channel_id}@{event.recorder_ip}"
        await ws_manager.broadcast_event(
            event_type=event.event_source,
            target_type=event.target_type,
            camera_name=camera_name,
            confidence=event.confidence,
            snapshot_path=snapshot_path,
            extra={
                "detections": len(pipeline_output.detections),
                "faces": len(pipeline_output.faces),
                "plates": len(pipeline_output.plates),
            },
        )

        # 6. Send Telegram alert
        bboxes = [
            {"label": d.label, "bbox": d.bbox, "conf": d.confidence}
            for d in pipeline_output.detections
        ]
        await telegram_notifier.send_alert(
            event_type=event.event_source,
            target_type=event.target_type,
            camera_name=camera_name,
            confidence=event.confidence,
            image=image,
            bboxes=bboxes,
        )

    except Exception as e:
        logger.error(f"Error processing ISAPI event: {e}", exc_info=True)


async def handle_frigate_event(event: FrigateEvent):
    """
    Process a Frigate MQTT detection event.
    Similar pipeline to ISAPI but uses Frigate's snapshot API.
    """
    logger.info(
        f"Processing Frigate event: {event.label} on {event.camera} "
        f"(conf: {event.confidence:.2f})"
    )

    try:
        # Get snapshot from Frigate API
        import httpx

        snapshot_url = (
            f"http://{settings.frigate_host}:{settings.frigate_port}"
            f"/api/events/{event.event_id}/snapshot.jpg"
        )

        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(snapshot_url)
            if resp.status_code != 200:
                logger.warning(f"Frigate snapshot not available for {event.event_id}")
                return

            # Decode image
            nparr = np.frombuffer(resp.content, np.uint8)
            image = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            if image is None:
                return

        # Save snapshot locally
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
        snapshot_path = str(settings.media_path / "snapshots" / f"frigate_{event.camera}_{ts}.jpg")
        cv2.imwrite(snapshot_path, image, [cv2.IMWRITE_JPEG_QUALITY, 92])

        # Run secondary AI
        run_face = event.label in ("person",)
        run_lpr = event.label in ("car", "truck", "bus", "motorcycle")
        pipeline_output = await ai_pipeline.process_frame(
            image,
            run_detection=False,  # Already detected by Frigate
            run_face=run_face,
            run_lpr=run_lpr,
            run_clip=True,
        )

        # Store and broadcast
        await _store_event_results(
            event_source=event.event_source,
            target_type=event.target_type,
            confidence=event.confidence,
            snapshot_path=snapshot_path,
            pipeline_output=pipeline_output,
            recorder_ip="frigate",
            channel_id=0,
            image=image,
        )

        from app.api.routers.websocket import ws_manager
        await ws_manager.broadcast_event(
            event_type="frigate_detection",
            target_type=event.label,
            camera_name=event.camera,
            confidence=event.confidence,
            snapshot_path=snapshot_path,
        )

        await telegram_notifier.send_alert(
            event_type="frigate_detection",
            target_type=event.label,
            camera_name=event.camera,
            confidence=event.confidence,
            snapshot_path=snapshot_path,
        )

    except Exception as e:
        logger.error(f"Error processing Frigate event: {e}", exc_info=True)


async def _store_event_results(
    event_source: str,
    target_type: str,
    confidence: float,
    snapshot_path: str,
    pipeline_output,
    recorder_ip: str,
    channel_id: int,
    image: np.ndarray,
):
    """Store AI pipeline results in PostgreSQL."""
    from app.db.session import async_session_factory
    from app.db.models import Event, FaceDetection, PlateDetection, EventEmbedding, Camera

    async with async_session_factory() as session:
        try:
            # Find camera by IP + channel
            from sqlalchemy import select
            cam_result = await session.execute(
                select(Camera).where(
                    Camera.recorder_ip == recorder_ip,
                    Camera.channel_number == channel_id,
                )
            )
            camera = cam_result.scalar()

            # Create main event
            event = Event(
                camera_id=camera.id if camera else None,
                event_source=event_source,
                target_type=target_type,
                confidence=confidence,
                snapshot_path=snapshot_path,
            )
            session.add(event)
            await session.flush()

            # Store face detections
            for face in pipeline_output.faces:
                # Search for matching enrolled face
                matched_id = None
                similarity = 0.0

                if face.embedding is not None:
                    from sqlalchemy import text
                    emb_str = "[" + ",".join(str(x) for x in face.embedding.tolist()) + "]"
                    match_result = await session.execute(
                        text("""
                            SELECT id, 1 - (embedding <=> :vec::vector) AS sim
                            FROM faces
                            WHERE 1 - (embedding <=> :vec::vector) >= 0.55
                            ORDER BY embedding <=> :vec::vector
                            LIMIT 1
                        """),
                        {"vec": emb_str},
                    )
                    match_row = match_result.fetchone()
                    if match_row:
                        matched_id = match_row[0]
                        similarity = float(match_row[1])

                crop_path = snapshot_grabber.save_crop(image, face.bbox, label="face")
                face_det = FaceDetection(
                    event_id=event.id,
                    matched_face_id=matched_id,
                    similarity_score=similarity,
                    bounding_box=face.bbox,
                    crop_path=crop_path,
                    embedding=face.embedding.tolist() if face.embedding is not None else None,
                    is_unknown=matched_id is None,
                )
                session.add(face_det)

            # Store plate detections
            for plate in pipeline_output.plates:
                from sqlalchemy import select as sa_select
                matched_plate_result = await session.execute(
                    sa_select(
                        __import__("app.db.models", fromlist=["LicensePlate"]).LicensePlate
                    ).where(
                        __import__("app.db.models", fromlist=["LicensePlate"]).LicensePlate.plate_number == plate.text
                    )
                )
                matched_plate = matched_plate_result.scalar()

                plate_det = PlateDetection(
                    event_id=event.id,
                    matched_plate_id=matched_plate.id if matched_plate else None,
                    detected_text=plate.text,
                    confidence=plate.confidence,
                    bounding_box=plate.bbox,
                )
                session.add(plate_det)

            # Store CLIP embedding for semantic search
            if pipeline_output.clip_embedding is not None:
                clip_emb = EventEmbedding(
                    event_id=event.id,
                    embedding=pipeline_output.clip_embedding.embedding.tolist(),
                )
                session.add(clip_emb)

            await session.commit()
            logger.info(f"Event stored: {event.id} ({event_source}:{target_type})")

        except Exception as e:
            await session.rollback()
            logger.error(f"Failed to store event: {e}", exc_info=True)


# -------------------------------------------------------
# Application Lifecycle
# -------------------------------------------------------
isapi_listener = ISAPIListener(on_event=handle_isapi_event)
mqtt_subscriber = MQTTSubscriber(on_event=handle_frigate_event)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown lifecycle."""
    logger.info("=" * 60)
    logger.info("  Hikvision AI CCTV Platform — Starting Up")
    logger.info("=" * 60)

    # Initialize AI pipeline (load models to GPU)
    try:
        await ai_pipeline.initialize()
        logger.info(f"AI Models: {ai_pipeline.available_models}")
    except Exception as e:
        logger.error(f"AI pipeline initialization failed: {e}")

    # Initialize Telegram bot
    await telegram_notifier.initialize()

    # Start background services
    await isapi_listener.start()
    await mqtt_subscriber.start()
    await retention_manager.start()

    # Ensure media directories exist
    for subdir in ["snapshots", "clips", "crops"]:
        (settings.media_path / subdir).mkdir(parents=True, exist_ok=True)

    logger.info("All services started. Platform is operational.")
    logger.info(f"Dashboard: http://localhost:{settings.api_port}")
    logger.info(f"API Docs:  http://localhost:{settings.api_port}/docs")

    yield  # Application is running

    # Shutdown
    logger.info("Shutting down services...")
    await isapi_listener.stop()
    await mqtt_subscriber.stop()
    await retention_manager.stop()
    logger.info("All services stopped. Goodbye.")


# -------------------------------------------------------
# FastAPI Application
# -------------------------------------------------------
app = FastAPI(
    title="Hikvision AI CCTV Platform",
    description=(
        "Custom AI-powered CCTV management platform with face recognition, "
        "license plate detection, and natural language video search."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static files (CSS, JS)
ui_dir = Path(__file__).parent / "ui"
if ui_dir.exists():
    app.mount("/static", StaticFiles(directory=str(ui_dir)), name="static")

# Mount media directory for snapshot serving
media_mount_path = settings.media_path
if media_mount_path.exists():
    app.mount("/media", StaticFiles(directory=str(media_mount_path)), name="media")

# -------------------------------------------------------
# Include API Routers
# -------------------------------------------------------
from app.api.routers.cameras import router as cameras_router
from app.api.routers.events import router as events_router
from app.api.routers.faces import router as faces_router
from app.api.routers.plates import router as plates_router
from app.api.routers.search import router as search_router
from app.api.routers.websocket import router as websocket_router

app.include_router(cameras_router)
app.include_router(events_router)
app.include_router(faces_router)
app.include_router(plates_router)
app.include_router(search_router)
app.include_router(websocket_router)


# -------------------------------------------------------
# Dashboard & Health Endpoints
# -------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
async def serve_dashboard():
    """Serve the main dashboard HTML."""
    index_path = ui_dir / "index.html"
    if index_path.exists():
        return HTMLResponse(content=index_path.read_text(encoding="utf-8"))
    return HTMLResponse(
        content="<h1>Hikvision AI CCTV Platform</h1>"
        "<p>Dashboard UI not found. API is running at <a href='/docs'>/docs</a></p>"
    )


@app.get("/api/health")
async def health_check():
    """System health check endpoint."""
    from app.api.routers.websocket import ws_manager

    return {
        "status": "healthy",
        "ai_models": ai_pipeline.available_models if ai_pipeline.is_initialized else "loading",
        "telegram": telegram_notifier.is_enabled,
        "websocket_clients": ws_manager.client_count,
        "storage": retention_manager.get_storage_stats(),
    }


@app.get("/api/system/info")
async def system_info():
    """Return system configuration info."""
    return {
        "platform": "Hikvision AI CCTV Platform",
        "version": "1.0.0",
        "gpu": "NVIDIA RTX 3060 (6GB VRAM)",
        "recorders": {
            "nvr": {"ip": settings.hik_nvr_ip, "type": "DS-7608NXI-K1"},
            "dvr": {"ip": settings.hik_dvr_ip, "type": "DS-7A08HQHI-K1"},
        },
        "frigate": f"http://{settings.frigate_host}:{settings.frigate_port}",
        "media_retention_days": settings.media_retention_days,
        "media_max_gb": settings.media_max_size_gb,
    }
