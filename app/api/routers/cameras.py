"""
Hikvision AI CCTV Platform — Camera Management API Router
CRUD operations for camera registry and live stream metadata.
"""

import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select, update, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Camera
from app.db.session import get_db

router = APIRouter(prefix="/api/cameras", tags=["cameras"])


# -------------------------------------------------------
# Pydantic Schemas
# -------------------------------------------------------
class CameraCreate(BaseModel):
    name: str = Field(..., max_length=100)
    recorder_type: str = Field(default="hikvision_nvr")
    recorder_ip: str
    channel_number: int
    rtsp_main_url: str
    rtsp_sub_url: str
    isapi_stream_url: Optional[str] = None
    snapshot_url: Optional[str] = None
    location: Optional[str] = None


class CameraUpdate(BaseModel):
    name: Optional[str] = None
    recorder_type: Optional[str] = None
    recorder_ip: Optional[str] = None
    channel_number: Optional[int] = None
    rtsp_main_url: Optional[str] = None
    rtsp_sub_url: Optional[str] = None
    isapi_stream_url: Optional[str] = None
    snapshot_url: Optional[str] = None
    location: Optional[str] = None
    is_active: Optional[bool] = None


class CameraResponse(BaseModel):
    id: uuid.UUID
    name: str
    recorder_type: str
    recorder_ip: str
    channel_number: int
    rtsp_main_url: str
    rtsp_sub_url: str
    isapi_stream_url: Optional[str]
    snapshot_url: Optional[str]
    location: Optional[str]
    is_active: bool
    created_at: str
    updated_at: str

    model_config = {"from_attributes": True}


# -------------------------------------------------------
# Endpoints
# -------------------------------------------------------
@router.get("", response_model=List[CameraResponse])
async def list_cameras(
    active_only: bool = Query(False, description="Filter to active cameras only"),
    db: AsyncSession = Depends(get_db),
):
    """List all registered cameras."""
    query = select(Camera).order_by(Camera.name)
    if active_only:
        query = query.where(Camera.is_active == True)

    result = await db.execute(query)
    cameras = result.scalars().all()
    return [_camera_to_response(c) for c in cameras]


@router.get("/{camera_id}", response_model=CameraResponse)
async def get_camera(
    camera_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """Get a single camera by ID."""
    camera = await db.get(Camera, camera_id)
    if not camera:
        raise HTTPException(status_code=404, detail="Camera not found")
    return _camera_to_response(camera)


@router.post("", response_model=CameraResponse, status_code=201)
async def create_camera(
    data: CameraCreate,
    db: AsyncSession = Depends(get_db),
):
    """Register a new camera."""
    camera = Camera(
        name=data.name,
        recorder_type=data.recorder_type,
        recorder_ip=data.recorder_ip,
        channel_number=data.channel_number,
        rtsp_main_url=data.rtsp_main_url,
        rtsp_sub_url=data.rtsp_sub_url,
        isapi_stream_url=data.isapi_stream_url,
        snapshot_url=data.snapshot_url,
        location=data.location,
    )
    db.add(camera)
    await db.flush()
    await db.refresh(camera)
    return _camera_to_response(camera)


@router.patch("/{camera_id}", response_model=CameraResponse)
async def update_camera(
    camera_id: uuid.UUID,
    data: CameraUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Update camera configuration."""
    camera = await db.get(Camera, camera_id)
    if not camera:
        raise HTTPException(status_code=404, detail="Camera not found")

    update_data = data.model_dump(exclude_unset=True)
    for field_name, value in update_data.items():
        setattr(camera, field_name, value)

    await db.flush()
    await db.refresh(camera)
    return _camera_to_response(camera)


@router.delete("/{camera_id}", status_code=204)
async def delete_camera(
    camera_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """Remove a camera from the registry."""
    camera = await db.get(Camera, camera_id)
    if not camera:
        raise HTTPException(status_code=404, detail="Camera not found")
    await db.delete(camera)


@router.post("/{camera_id}/snapshot")
async def trigger_snapshot(
    camera_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """Trigger a high-res snapshot from the camera via ISAPI."""
    camera = await db.get(Camera, camera_id)
    if not camera:
        raise HTTPException(status_code=404, detail="Camera not found")

    from app.services.rtsp_grabber import SnapshotGrabber
    grabber = SnapshotGrabber()
    snapshot_path = await grabber.grab_snapshot(
        recorder_ip=camera.recorder_ip,
        channel_id=camera.channel_number,
    )

    if snapshot_path:
        return {"status": "ok", "snapshot_path": snapshot_path}
    else:
        raise HTTPException(status_code=500, detail="Failed to capture snapshot")


# -------------------------------------------------------
# Helpers
# -------------------------------------------------------
def _camera_to_response(camera: Camera) -> CameraResponse:
    return CameraResponse(
        id=camera.id,
        name=camera.name,
        recorder_type=camera.recorder_type,
        recorder_ip=camera.recorder_ip,
        channel_number=camera.channel_number,
        rtsp_main_url=camera.rtsp_main_url,
        rtsp_sub_url=camera.rtsp_sub_url,
        isapi_stream_url=camera.isapi_stream_url,
        snapshot_url=camera.snapshot_url,
        location=camera.location,
        is_active=camera.is_active,
        created_at=camera.created_at.isoformat() if camera.created_at else "",
        updated_at=camera.updated_at.isoformat() if camera.updated_at else "",
    )
