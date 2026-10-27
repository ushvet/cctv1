"""
Hikvision AI CCTV Platform — Semantic Search API Router
Natural language video search powered by MobileCLIP + pgvector.
"""

import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db

router = APIRouter(prefix="/api/search", tags=["search"])


# -------------------------------------------------------
# Pydantic Schemas
# -------------------------------------------------------
class SearchResult(BaseModel):
    event_id: uuid.UUID
    snapshot_path: Optional[str]
    camera_name: Optional[str]
    target_type: Optional[str]
    timestamp: Optional[str]
    similarity: float
    description: Optional[str] = None


class SearchResponse(BaseModel):
    query: str
    results: List[SearchResult]
    total: int


# -------------------------------------------------------
# Endpoints
# -------------------------------------------------------
@router.get("", response_model=SearchResponse)
async def semantic_search(
    q: str = Query(..., min_length=3, max_length=500, description="Natural language search query"),
    limit: int = Query(20, ge=1, le=100),
    threshold: float = Query(0.2, description="Minimum similarity score (0.0-1.0)"),
    db: AsyncSession = Depends(get_db),
):
    """
    Search events using natural language queries via MobileCLIP embeddings.
    
    Examples:
      - "person in dark clothing near the gate"
      - "red car in parking lot"
      - "delivery truck at night"
      - "dog in backyard"
    
    The query text is encoded into a 512-d CLIP vector and compared
    against stored event embeddings using pgvector cosine similarity.
    """
    # Encode text query to CLIP vector
    from app.services.ai_pipeline import AIPipeline
    pipeline = AIPipeline()

    if not pipeline.is_initialized:
        await pipeline.initialize()

    query_vector = await pipeline.encode_text_query(q)

    if query_vector is None:
        # Fallback: text-based metadata search when CLIP text encoder unavailable
        return await _fallback_text_search(q, limit, db)

    # pgvector cosine similarity search
    vector_str = "[" + ",".join(str(x) for x in query_vector.tolist()) + "]"

    result = await db.execute(
        text("""
            SELECT 
                ee.event_id,
                e.snapshot_path,
                c.name AS camera_name,
                e.target_type,
                e.timestamp,
                1 - (ee.embedding <=> :query_vec::vector) AS similarity,
                ee.description_caption
            FROM event_embeddings ee
            JOIN events e ON e.id = ee.event_id
            LEFT JOIN cameras c ON c.id = e.camera_id
            WHERE 1 - (ee.embedding <=> :query_vec::vector) >= :threshold
            ORDER BY ee.embedding <=> :query_vec::vector
            LIMIT :limit
        """),
        {"query_vec": vector_str, "threshold": threshold, "limit": limit},
    )

    rows = result.fetchall()

    results = [
        SearchResult(
            event_id=row[0],
            snapshot_path=row[1],
            camera_name=row[2],
            target_type=row[3],
            timestamp=row[4].isoformat() if row[4] else None,
            similarity=round(float(row[5]), 4),
            description=row[6],
        )
        for row in rows
    ]

    return SearchResponse(query=q, results=results, total=len(results))


async def _fallback_text_search(
    query: str,
    limit: int,
    db: AsyncSession,
) -> SearchResponse:
    """
    Fallback search using PostgreSQL full-text matching on event metadata
    when CLIP text encoder is not available.
    """
    search_terms = query.lower().split()

    # Build JSONB / target_type matching
    conditions = []
    params = {"limit": limit}

    for i, term in enumerate(search_terms[:5]):  # Max 5 terms
        key = f"term_{i}"
        conditions.append(
            f"(LOWER(e.target_type) LIKE :{key} OR "
            f"LOWER(COALESCE(c.name, '')) LIKE :{key} OR "
            f"LOWER(COALESCE(c.location, '')) LIKE :{key})"
        )
        params[key] = f"%{term}%"

    where_clause = " AND ".join(conditions) if conditions else "TRUE"

    result = await db.execute(
        text(f"""
            SELECT 
                e.id AS event_id,
                e.snapshot_path,
                c.name AS camera_name,
                e.target_type,
                e.timestamp
            FROM events e
            LEFT JOIN cameras c ON c.id = e.camera_id
            WHERE {where_clause}
            ORDER BY e.timestamp DESC
            LIMIT :limit
        """),
        params,
    )

    rows = result.fetchall()

    results = [
        SearchResult(
            event_id=row[0],
            snapshot_path=row[1],
            camera_name=row[2],
            target_type=row[3],
            timestamp=row[4].isoformat() if row[4] else None,
            similarity=0.5,  # Flat score for text fallback
        )
        for row in rows
    ]

    return SearchResponse(query=query, results=results, total=len(results))
