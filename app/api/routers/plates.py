"""
Hikvision AI CCTV Platform — License Plates API Router
Plate whitelist/blacklist management and detection log.
"""

import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select, func, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import LicensePlate, PlateDetection
from app.db.session import get_db

router = APIRouter(prefix="/api/plates", tags=["plates"])


# -------------------------------------------------------
# Pydantic Schemas
# -------------------------------------------------------
class PlateCreate(BaseModel):
    plate_number: str = Field(..., max_length=32)
    owner_name: Optional[str] = None
    category: str = Field(default="registered")
    vehicle_description: Optional[str] = None
    notes: Optional[str] = None


class PlateUpdate(BaseModel):
    owner_name: Optional[str] = None
    category: Optional[str] = None
    vehicle_description: Optional[str] = None
    notes: Optional[str] = None


class PlateResponse(BaseModel):
    id: uuid.UUID
    plate_number: str
    owner_name: Optional[str]
    category: str
    vehicle_description: Optional[str]
    notes: Optional[str]
    detection_count: int = 0
    last_seen: Optional[str] = None
    created_at: str

    model_config = {"from_attributes": True}


class PlateDetectionResponse(BaseModel):
    id: uuid.UUID
    event_id: uuid.UUID
    detected_text: str
    confidence: Optional[float]
    matched_plate_id: Optional[uuid.UUID]
    matched_category: Optional[str] = None
    crop_path: Optional[str]
    created_at: str

    model_config = {"from_attributes": True}


# -------------------------------------------------------
# Endpoints
# -------------------------------------------------------
@router.get("", response_model=List[PlateResponse])
async def list_plates(
    category: Optional[str] = Query(None, description="Filter: registered, whitelist, blacklist, resident"),
    db: AsyncSession = Depends(get_db),
):
    """List all registered license plates."""
    query = select(LicensePlate).order_by(LicensePlate.plate_number)
    if category:
        query = query.where(LicensePlate.category == category)

    result = await db.execute(query)
    plates = result.scalars().all()

    responses = []
    for plate in plates:
        det_count = (await db.execute(
            select(func.count(PlateDetection.id)).where(
                PlateDetection.matched_plate_id == plate.id
            )
        )).scalar() or 0

        last_det = (await db.execute(
            select(PlateDetection.created_at)
            .where(PlateDetection.matched_plate_id == plate.id)
            .order_by(desc(PlateDetection.created_at))
            .limit(1)
        )).scalar()

        responses.append(PlateResponse(
            id=plate.id,
            plate_number=plate.plate_number,
            owner_name=plate.owner_name,
            category=plate.category,
            vehicle_description=plate.vehicle_description,
            notes=plate.notes,
            detection_count=det_count,
            last_seen=last_det.isoformat() if last_det else None,
            created_at=plate.created_at.isoformat(),
        ))

    return responses


@router.post("", response_model=PlateResponse, status_code=201)
async def create_plate(
    data: PlateCreate,
    db: AsyncSession = Depends(get_db),
):
    """Register a new license plate."""
    # Check for duplicate
    existing = (await db.execute(
        select(LicensePlate).where(
            LicensePlate.plate_number == data.plate_number.upper().strip()
        )
    )).scalar()
    if existing:
        raise HTTPException(status_code=409, detail="Plate number already registered")

    plate = LicensePlate(
        plate_number=data.plate_number.upper().strip(),
        owner_name=data.owner_name,
        category=data.category,
        vehicle_description=data.vehicle_description,
        notes=data.notes,
    )
    db.add(plate)
    await db.flush()
    await db.refresh(plate)

    return PlateResponse(
        id=plate.id,
        plate_number=plate.plate_number,
        owner_name=plate.owner_name,
        category=plate.category,
        vehicle_description=plate.vehicle_description,
        notes=plate.notes,
        detection_count=0,
        created_at=plate.created_at.isoformat(),
    )


@router.patch("/{plate_id}", response_model=PlateResponse)
async def update_plate(
    plate_id: uuid.UUID,
    data: PlateUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Update plate registration details."""
    plate = await db.get(LicensePlate, plate_id)
    if not plate:
        raise HTTPException(status_code=404, detail="Plate not found")

    update_data = data.model_dump(exclude_unset=True)
    for field_name, value in update_data.items():
        setattr(plate, field_name, value)

    await db.flush()
    await db.refresh(plate)

    return PlateResponse(
        id=plate.id,
        plate_number=plate.plate_number,
        owner_name=plate.owner_name,
        category=plate.category,
        vehicle_description=plate.vehicle_description,
        notes=plate.notes,
        detection_count=0,
        created_at=plate.created_at.isoformat(),
    )


@router.delete("/{plate_id}", status_code=204)
async def delete_plate(
    plate_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """Remove a plate from the registry."""
    plate = await db.get(LicensePlate, plate_id)
    if not plate:
        raise HTTPException(status_code=404, detail="Plate not found")
    await db.delete(plate)


@router.get("/detections", response_model=List[PlateDetectionResponse])
async def list_plate_detections(
    plate_number: Optional[str] = Query(None, description="Filter by exact plate number"),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    """List recent license plate detections."""
    query = select(PlateDetection).order_by(desc(PlateDetection.created_at)).limit(limit)

    if plate_number:
        query = query.where(PlateDetection.detected_text == plate_number.upper().strip())

    result = await db.execute(query)
    detections = result.scalars().all()

    responses = []
    for d in detections:
        matched_cat = None
        if d.matched_plate_id:
            plate = await db.get(LicensePlate, d.matched_plate_id)
            matched_cat = plate.category if plate else None

        responses.append(PlateDetectionResponse(
            id=d.id,
            event_id=d.event_id,
            detected_text=d.detected_text,
            confidence=d.confidence,
            matched_plate_id=d.matched_plate_id,
            matched_category=matched_cat,
            crop_path=d.crop_path,
            created_at=d.created_at.isoformat(),
        ))

    return responses
