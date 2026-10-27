"""
Hikvision AI CCTV Platform — Faces API Router
Face enrollment, watchlist management, and similarity search.
"""

import uuid
from typing import List, Optional

import numpy as np
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Form
from pydantic import BaseModel, Field
from sqlalchemy import select, text, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Face, FaceDetection
from app.db.session import get_db

router = APIRouter(prefix="/api/faces", tags=["faces"])


# -------------------------------------------------------
# Pydantic Schemas
# -------------------------------------------------------
class FaceResponse(BaseModel):
    id: uuid.UUID
    name: str
    category: str
    sample_image_path: Optional[str]
    notes: Optional[str]
    detection_count: int = 0
    created_at: str

    model_config = {"from_attributes": True}


class FaceDetectionResponse(BaseModel):
    id: uuid.UUID
    event_id: uuid.UUID
    matched_face_id: Optional[uuid.UUID]
    matched_name: Optional[str] = None
    similarity_score: Optional[float]
    crop_path: Optional[str]
    is_unknown: bool
    created_at: str

    model_config = {"from_attributes": True}


class FaceEnrollRequest(BaseModel):
    name: str = Field(..., max_length=100)
    category: str = Field(default="general")
    notes: Optional[str] = None


# -------------------------------------------------------
# Endpoints
# -------------------------------------------------------
@router.get("", response_model=List[FaceResponse])
async def list_faces(
    category: Optional[str] = Query(None, description="Filter by category: vip, staff, blacklist, family"),
    db: AsyncSession = Depends(get_db),
):
    """List all enrolled faces in the watchlist."""
    query = select(Face).order_by(Face.name)
    if category:
        query = query.where(Face.category == category)

    result = await db.execute(query)
    faces = result.scalars().all()

    responses = []
    for face in faces:
        # Count detections for this face
        det_count = (await db.execute(
            select(func.count(FaceDetection.id)).where(FaceDetection.matched_face_id == face.id)
        )).scalar() or 0

        responses.append(FaceResponse(
            id=face.id,
            name=face.name,
            category=face.category,
            sample_image_path=face.sample_image_path,
            notes=face.notes,
            detection_count=det_count,
            created_at=face.created_at.isoformat() if face.created_at else "",
        ))

    return responses


@router.post("/enroll", response_model=FaceResponse, status_code=201)
async def enroll_face(
    name: str = Form(...),
    category: str = Form(default="general"),
    notes: Optional[str] = Form(default=None),
    photo: UploadFile = File(..., description="Face photo for embedding extraction"),
    db: AsyncSession = Depends(get_db),
):
    """
    Enroll a new face into the watchlist.
    Uploads a photo, runs InsightFace to extract the 512-d embedding,
    and stores it in the database for future matching.
    """
    import cv2

    # Read and decode uploaded image
    image_bytes = await photo.read()
    nparr = np.frombuffer(image_bytes, np.uint8)
    image = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

    if image is None:
        raise HTTPException(status_code=400, detail="Invalid image file")

    # Extract face embedding via AI pipeline
    from app.services.ai_pipeline import AIPipeline
    pipeline = AIPipeline()

    if not pipeline.is_initialized:
        await pipeline.initialize()

    result = await pipeline.process_frame(
        image, run_detection=False, run_face=True, run_lpr=False, run_clip=False
    )

    if not result.faces:
        raise HTTPException(
            status_code=400,
            detail="No face detected in the uploaded photo. Please use a clear frontal face image."
        )

    # Use the first detected face
    face_result = result.faces[0]

    # Save sample image
    from app.services.rtsp_grabber import SnapshotGrabber
    grabber = SnapshotGrabber()
    sample_path = grabber.save_crop(image, face_result.bbox, label="face_enrolled")

    # Create database entry
    face = Face(
        name=name,
        category=category,
        embedding=face_result.embedding.tolist(),
        sample_image_path=sample_path,
        notes=notes,
    )
    db.add(face)
    await db.flush()
    await db.refresh(face)

    return FaceResponse(
        id=face.id,
        name=face.name,
        category=face.category,
        sample_image_path=face.sample_image_path,
        notes=face.notes,
        detection_count=0,
        created_at=face.created_at.isoformat(),
    )


@router.get("/{face_id}", response_model=FaceResponse)
async def get_face(
    face_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """Get a specific enrolled face."""
    face = await db.get(Face, face_id)
    if not face:
        raise HTTPException(status_code=404, detail="Face not found")

    det_count = (await db.execute(
        select(func.count(FaceDetection.id)).where(FaceDetection.matched_face_id == face.id)
    )).scalar() or 0

    return FaceResponse(
        id=face.id,
        name=face.name,
        category=face.category,
        sample_image_path=face.sample_image_path,
        notes=face.notes,
        detection_count=det_count,
        created_at=face.created_at.isoformat(),
    )


@router.delete("/{face_id}", status_code=204)
async def delete_face(
    face_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """Remove a face from the watchlist."""
    face = await db.get(Face, face_id)
    if not face:
        raise HTTPException(status_code=404, detail="Face not found")
    await db.delete(face)


@router.get("/{face_id}/detections", response_model=List[FaceDetectionResponse])
async def get_face_detections(
    face_id: uuid.UUID,
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    """Get recent detections of a specific enrolled face."""
    result = await db.execute(
        select(FaceDetection)
        .where(FaceDetection.matched_face_id == face_id)
        .order_by(FaceDetection.created_at.desc())
        .limit(limit)
    )
    detections = result.scalars().all()

    return [
        FaceDetectionResponse(
            id=d.id,
            event_id=d.event_id,
            matched_face_id=d.matched_face_id,
            similarity_score=d.similarity_score,
            crop_path=d.crop_path,
            is_unknown=d.is_unknown,
            created_at=d.created_at.isoformat(),
        )
        for d in detections
    ]


@router.get("/search/similar")
async def search_similar_faces(
    face_id: uuid.UUID = Query(..., description="Face ID to search similar detections for"),
    threshold: float = Query(0.6, description="Minimum cosine similarity (0.0-1.0)"),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """
    Search for face detections similar to an enrolled face
    using pgvector cosine similarity (HNSW index).
    """
    face = await db.get(Face, face_id)
    if not face:
        raise HTTPException(status_code=404, detail="Face not found")

    # Use pgvector cosine distance operator <=>
    embedding_str = str(face.embedding)
    result = await db.execute(
        text("""
            SELECT fd.id, fd.event_id, fd.crop_path, fd.created_at,
                   1 - (fd.embedding <=> :query_vec) AS similarity
            FROM face_detections fd
            WHERE fd.embedding IS NOT NULL
              AND 1 - (fd.embedding <=> :query_vec) >= :threshold
            ORDER BY fd.embedding <=> :query_vec
            LIMIT :limit
        """),
        {"query_vec": embedding_str, "threshold": threshold, "limit": limit},
    )

    rows = result.fetchall()
    return [
        {
            "detection_id": str(row[0]),
            "event_id": str(row[1]),
            "crop_path": row[2],
            "created_at": row[3].isoformat() if row[3] else None,
            "similarity": round(float(row[4]), 4),
        }
        for row in rows
    ]
