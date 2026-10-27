"""
Hikvision AI CCTV Platform — Events API Router
Filterable event feed with pagination and acknowledgment.
"""

import uuid
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select, func, desc
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import Event, Camera
from app.db.session import get_db

router = APIRouter(prefix="/api/events", tags=["events"])


# -------------------------------------------------------
# Pydantic Schemas
# -------------------------------------------------------
class EventResponse(BaseModel):
    id: uuid.UUID
    camera_id: Optional[uuid.UUID]
    camera_name: Optional[str] = None
    event_source: str
    event_type: str
    target_type: str
    confidence: float
    timestamp: str
    snapshot_path: Optional[str]
    clip_path: Optional[str]
    is_acknowledged: bool
    metadata: Optional[dict] = None

    model_config = {"from_attributes": True}


class EventListResponse(BaseModel):
    events: List[EventResponse]
    total: int
    page: int
    per_page: int


class EventStats(BaseModel):
    total_events: int
    today_events: int
    humans_today: int
    vehicles_today: int
    faces_today: int
    plates_today: int
    unacknowledged: int


# -------------------------------------------------------
# Endpoints
# -------------------------------------------------------
@router.get("", response_model=EventListResponse)
async def list_events(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    target_type: Optional[str] = Query(None, description="Filter by target type: human, vehicle, face, etc."),
    event_source: Optional[str] = Query(None, description="Filter by source: isapi_*, frigate_*"),
    camera_id: Optional[uuid.UUID] = Query(None),
    acknowledged: Optional[bool] = Query(None),
    since: Optional[str] = Query(None, description="ISO datetime filter (events after this time)"),
    db: AsyncSession = Depends(get_db),
):
    """List security events with filtering and pagination."""
    query = select(Event).options(selectinload(Event.camera)).order_by(desc(Event.timestamp))

    # Apply filters
    if target_type:
        query = query.where(Event.target_type == target_type)
    if event_source:
        query = query.where(Event.event_source == event_source)
    if camera_id:
        query = query.where(Event.camera_id == camera_id)
    if acknowledged is not None:
        query = query.where(Event.is_acknowledged == acknowledged)
    if since:
        try:
            since_dt = datetime.fromisoformat(since)
            query = query.where(Event.timestamp >= since_dt)
        except ValueError:
            pass

    # Count total matching
    count_query = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_query)).scalar() or 0

    # Paginate
    offset = (page - 1) * per_page
    query = query.offset(offset).limit(per_page)

    result = await db.execute(query)
    events = result.scalars().all()

    return EventListResponse(
        events=[_event_to_response(e) for e in events],
        total=total,
        page=page,
        per_page=per_page,
    )


@router.get("/stats", response_model=EventStats)
async def get_event_stats(
    db: AsyncSession = Depends(get_db),
):
    """Get event statistics for the dashboard."""
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    # Total events
    total = (await db.execute(select(func.count(Event.id)))).scalar() or 0

    # Today's events
    today_q = select(func.count(Event.id)).where(Event.timestamp >= today_start)
    today = (await db.execute(today_q)).scalar() or 0

    # Humans today
    humans = (await db.execute(
        today_q.where(Event.target_type == "human")
    )).scalar() or 0

    # Vehicles today
    vehicles = (await db.execute(
        select(func.count(Event.id)).where(
            Event.timestamp >= today_start,
            Event.target_type.in_(["vehicle", "car", "truck", "bus", "motorcycle"])
        )
    )).scalar() or 0

    # Faces today
    faces = (await db.execute(
        select(func.count(Event.id)).where(
            Event.timestamp >= today_start,
            Event.target_type == "face"
        )
    )).scalar() or 0

    # Plates today
    plates = (await db.execute(
        select(func.count(Event.id)).where(
            Event.timestamp >= today_start,
            Event.target_type == "license_plate"
        )
    )).scalar() or 0

    # Unacknowledged
    unack = (await db.execute(
        select(func.count(Event.id)).where(Event.is_acknowledged == False)
    )).scalar() or 0

    return EventStats(
        total_events=total,
        today_events=today,
        humans_today=humans,
        vehicles_today=vehicles,
        faces_today=faces,
        plates_today=plates,
        unacknowledged=unack,
    )


@router.get("/{event_id}", response_model=EventResponse)
async def get_event(
    event_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """Get a single event by ID."""
    event = await db.get(Event, event_id, options=[selectinload(Event.camera)])
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    return _event_to_response(event)


@router.post("/{event_id}/acknowledge")
async def acknowledge_event(
    event_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """Mark an event as acknowledged."""
    event = await db.get(Event, event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    event.is_acknowledged = True
    await db.flush()
    return {"status": "acknowledged", "event_id": str(event_id)}


@router.post("/acknowledge-all")
async def acknowledge_all_events(
    db: AsyncSession = Depends(get_db),
):
    """Acknowledge all unacknowledged events."""
    from sqlalchemy import update
    result = await db.execute(
        update(Event).where(Event.is_acknowledged == False).values(is_acknowledged=True)
    )
    return {"status": "ok", "acknowledged_count": result.rowcount}


# -------------------------------------------------------
# Helpers
# -------------------------------------------------------
def _event_to_response(event: Event) -> EventResponse:
    return EventResponse(
        id=event.id,
        camera_id=event.camera_id,
        camera_name=event.camera.name if event.camera else None,
        event_source=event.event_source,
        event_type=event.event_type,
        target_type=event.target_type,
        confidence=event.confidence,
        timestamp=event.timestamp.isoformat() if event.timestamp else "",
        snapshot_path=event.snapshot_path,
        clip_path=event.clip_path,
        is_acknowledged=event.is_acknowledged,
        metadata=event.metadata_json,
    )
