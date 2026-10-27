"""
Hikvision AI CCTV Platform — FastAPI Endpoint Integration Tests
Tests API routes using httpx async test client.
Run with: pytest tests/test_api_endpoints.py -v
"""

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport

from app.main import app


@pytest_asyncio.fixture
async def client():
    """Create an async test client for the FastAPI app."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# -------------------------------------------------------
# Health & System Endpoints
# -------------------------------------------------------
class TestHealthEndpoints:
    @pytest.mark.asyncio
    async def test_health_check(self, client):
        """Verify /api/health returns 200 with expected fields."""
        response = await client.get("/api/health")
        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert data["status"] == "healthy"
        assert "ai_models" in data
        assert "storage" in data

    @pytest.mark.asyncio
    async def test_system_info(self, client):
        """Verify /api/system/info returns platform configuration."""
        response = await client.get("/api/system/info")
        assert response.status_code == 200
        data = response.json()
        assert data["platform"] == "Hikvision AI CCTV Platform"
        assert data["version"] == "1.0.0"
        assert "recorders" in data


# -------------------------------------------------------
# Camera Endpoints
# -------------------------------------------------------
class TestCameraEndpoints:
    @pytest.mark.asyncio
    async def test_list_cameras(self, client):
        """Verify GET /api/cameras returns a list."""
        response = await client.get("/api/cameras")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

    @pytest.mark.asyncio
    async def test_create_camera(self, client):
        """Verify POST /api/cameras creates a new camera entry."""
        camera_data = {
            "name": "Test Camera Unit",
            "recorder_type": "hikvision_nvr",
            "recorder_ip": "192.168.1.100",
            "channel_number": 99,
            "rtsp_main_url": "rtsp://admin:pass@192.168.1.100:554/Streaming/Channels/9901",
            "rtsp_sub_url": "rtsp://admin:pass@192.168.1.100:554/Streaming/Channels/9902",
            "location": "Test Location",
        }
        response = await client.post("/api/cameras", json=camera_data)
        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "Test Camera Unit"
        assert data["channel_number"] == 99
        assert "id" in data

    @pytest.mark.asyncio
    async def test_get_camera_not_found(self, client):
        """Verify GET /api/cameras/{id} returns 404 for non-existent camera."""
        response = await client.get("/api/cameras/00000000-0000-0000-0000-000000000000")
        assert response.status_code == 404


# -------------------------------------------------------
# Event Endpoints
# -------------------------------------------------------
class TestEventEndpoints:
    @pytest.mark.asyncio
    async def test_list_events(self, client):
        """Verify GET /api/events returns paginated response."""
        response = await client.get("/api/events")
        assert response.status_code == 200
        data = response.json()
        assert "events" in data
        assert "total" in data
        assert "page" in data
        assert "per_page" in data

    @pytest.mark.asyncio
    async def test_event_stats(self, client):
        """Verify GET /api/events/stats returns aggregated statistics."""
        response = await client.get("/api/events/stats")
        assert response.status_code == 200
        data = response.json()
        assert "total_events" in data
        assert "today_events" in data
        assert "humans_today" in data
        assert "vehicles_today" in data
        assert "unacknowledged" in data

    @pytest.mark.asyncio
    async def test_acknowledge_all(self, client):
        """Verify POST /api/events/acknowledge-all completes successfully."""
        response = await client.post("/api/events/acknowledge-all")
        assert response.status_code == 200
        data = response.json()
        assert "acknowledged_count" in data


# -------------------------------------------------------
# Face Endpoints
# -------------------------------------------------------
class TestFaceEndpoints:
    @pytest.mark.asyncio
    async def test_list_faces(self, client):
        """Verify GET /api/faces returns a list."""
        response = await client.get("/api/faces")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

    @pytest.mark.asyncio
    async def test_list_faces_by_category(self, client):
        """Verify category filter query parameter works."""
        response = await client.get("/api/faces?category=vip")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_face_not_found(self, client):
        """Verify GET /api/faces/{id} returns 404."""
        response = await client.get("/api/faces/00000000-0000-0000-0000-000000000000")
        assert response.status_code == 404


# -------------------------------------------------------
# Plate Endpoints
# -------------------------------------------------------
class TestPlateEndpoints:
    @pytest.mark.asyncio
    async def test_list_plates(self, client):
        """Verify GET /api/plates returns a list."""
        response = await client.get("/api/plates")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

    @pytest.mark.asyncio
    async def test_create_plate(self, client):
        """Verify POST /api/plates creates a new plate entry."""
        plate_data = {
            "plate_number": "TEST0000",
            "owner_name": "Test User",
            "category": "whitelist",
            "vehicle_description": "Blue Test Car",
        }
        response = await client.post("/api/plates", json=plate_data)
        assert response.status_code == 201
        data = response.json()
        assert data["plate_number"] == "TEST0000"
        assert data["category"] == "whitelist"

    @pytest.mark.asyncio
    async def test_duplicate_plate_rejected(self, client):
        """Verify duplicate plate numbers are rejected with 409."""
        plate_data = {
            "plate_number": "DUPE1234",
            "category": "registered",
        }
        await client.post("/api/plates", json=plate_data)
        response = await client.post("/api/plates", json=plate_data)
        assert response.status_code == 409

    @pytest.mark.asyncio
    async def test_list_plate_detections(self, client):
        """Verify GET /api/plates/detections returns a list."""
        response = await client.get("/api/plates/detections")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)


# -------------------------------------------------------
# Search Endpoints
# -------------------------------------------------------
class TestSearchEndpoints:
    @pytest.mark.asyncio
    async def test_search_requires_query(self, client):
        """Verify search requires minimum 3-char query."""
        response = await client.get("/api/search?q=ab")
        assert response.status_code == 422  # Validation error

    @pytest.mark.asyncio
    async def test_search_valid_query(self, client):
        """Verify search returns structured response."""
        response = await client.get("/api/search?q=person%20near%20gate")
        assert response.status_code == 200
        data = response.json()
        assert "query" in data
        assert "results" in data
        assert "total" in data


# -------------------------------------------------------
# Dashboard HTML
# -------------------------------------------------------
class TestDashboardServing:
    @pytest.mark.asyncio
    async def test_serve_dashboard(self, client):
        """Verify root URL serves the HTML dashboard."""
        response = await client.get("/")
        assert response.status_code == 200
        assert "CCTV" in response.text or "html" in response.headers.get("content-type", "")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
