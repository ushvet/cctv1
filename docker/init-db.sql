-- ============================================================
-- Hikvision AI CCTV Platform — PostgreSQL Initialization
-- Executed once on first container start
-- ============================================================

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- -------------------------------------------------------
-- Camera Registry
-- -------------------------------------------------------
CREATE TABLE IF NOT EXISTS cameras (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(100) NOT NULL,
    recorder_type VARCHAR(50) NOT NULL DEFAULT 'hikvision_nvr',
    recorder_ip VARCHAR(45) NOT NULL,
    channel_number INT NOT NULL,
    rtsp_main_url TEXT NOT NULL,
    rtsp_sub_url TEXT NOT NULL,
    isapi_stream_url TEXT,
    snapshot_url TEXT,
    location VARCHAR(200),
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- -------------------------------------------------------
-- Known Faces / Watchlist
-- -------------------------------------------------------
CREATE TABLE IF NOT EXISTS faces (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(100) NOT NULL,
    category VARCHAR(50) NOT NULL DEFAULT 'general',
    embedding vector(512) NOT NULL,
    sample_image_path TEXT,
    notes TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- -------------------------------------------------------
-- Registered License Plates
-- -------------------------------------------------------
CREATE TABLE IF NOT EXISTS license_plates (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    plate_number VARCHAR(32) UNIQUE NOT NULL,
    owner_name VARCHAR(100),
    category VARCHAR(50) NOT NULL DEFAULT 'registered',
    vehicle_description TEXT,
    notes TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- -------------------------------------------------------
-- AI Security Events
-- -------------------------------------------------------
CREATE TABLE IF NOT EXISTS events (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    camera_id UUID REFERENCES cameras(id) ON DELETE CASCADE,
    event_source VARCHAR(50) NOT NULL,
    event_type VARCHAR(50) NOT NULL DEFAULT 'detection',
    target_type VARCHAR(50) NOT NULL,
    confidence FLOAT DEFAULT 0.0,
    bounding_box INT[],
    timestamp TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    snapshot_path TEXT,
    clip_path TEXT,
    is_acknowledged BOOLEAN DEFAULT FALSE,
    metadata JSONB DEFAULT '{}'::jsonb
);

-- -------------------------------------------------------
-- Face Detections
-- -------------------------------------------------------
CREATE TABLE IF NOT EXISTS face_detections (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    event_id UUID REFERENCES events(id) ON DELETE CASCADE,
    matched_face_id UUID REFERENCES faces(id) ON DELETE SET NULL,
    similarity_score FLOAT,
    bounding_box INT[],
    crop_path TEXT,
    embedding vector(512),
    is_unknown BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- -------------------------------------------------------
-- License Plate Detections
-- -------------------------------------------------------
CREATE TABLE IF NOT EXISTS plate_detections (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    event_id UUID REFERENCES events(id) ON DELETE CASCADE,
    matched_plate_id UUID REFERENCES license_plates(id) ON DELETE SET NULL,
    detected_text VARCHAR(32) NOT NULL,
    confidence FLOAT,
    bounding_box INT[],
    crop_path TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- -------------------------------------------------------
-- CLIP Semantic Embeddings for Natural Language Search
-- -------------------------------------------------------
CREATE TABLE IF NOT EXISTS event_embeddings (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    event_id UUID REFERENCES events(id) ON DELETE CASCADE,
    embedding vector(512) NOT NULL,
    description_caption TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- -------------------------------------------------------
-- Alert / Notification Log
-- -------------------------------------------------------
CREATE TABLE IF NOT EXISTS alert_log (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    event_id UUID REFERENCES events(id) ON DELETE CASCADE,
    channel VARCHAR(50) NOT NULL DEFAULT 'telegram',
    status VARCHAR(50) NOT NULL DEFAULT 'sent',
    message_id VARCHAR(100),
    error_message TEXT,
    sent_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- -------------------------------------------------------
-- HNSW Vector Indexes for fast cosine similarity
-- -------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_face_embedding_hnsw
ON faces USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64);

CREATE INDEX IF NOT EXISTS idx_clip_embedding_hnsw
ON event_embeddings USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64);

CREATE INDEX IF NOT EXISTS idx_face_det_embedding_hnsw
ON face_detections USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64);

-- -------------------------------------------------------
-- B-Tree Performance Indexes
-- -------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_events_camera_id ON events(camera_id);
CREATE INDEX IF NOT EXISTS idx_events_target_type ON events(target_type);
CREATE INDEX IF NOT EXISTS idx_events_source ON events(event_source);
CREATE INDEX IF NOT EXISTS idx_plate_detected_text ON plate_detections(detected_text);
CREATE INDEX IF NOT EXISTS idx_face_det_matched ON face_detections(matched_face_id);
CREATE INDEX IF NOT EXISTS idx_cameras_active ON cameras(is_active);

-- -------------------------------------------------------
-- Seed default cameras (update IPs/passwords after deploy)
-- -------------------------------------------------------
INSERT INTO cameras (name, recorder_type, recorder_ip, channel_number, rtsp_main_url, rtsp_sub_url, isapi_stream_url, snapshot_url, location)
VALUES
    ('Front Gate Panoramic', 'hikvision_nvr', '192.168.1.100', 1,
     'rtsp://admin:YourNVRPassword123@192.168.1.100:554/Streaming/Channels/101',
     'rtsp://admin:YourNVRPassword123@192.168.1.100:554/Streaming/Channels/102',
     'http://192.168.1.100/ISAPI/Event/notification/alertStream',
     'http://192.168.1.100/ISAPI/Streaming/channels/101/picture',
     'Main entrance - DS-2CD2T67G2P-LSU/SL'),
    ('Backyard Turret', 'hikvision_nvr', '192.168.1.100', 2,
     'rtsp://admin:YourNVRPassword123@192.168.1.100:554/Streaming/Channels/201',
     'rtsp://admin:YourNVRPassword123@192.168.1.100:554/Streaming/Channels/202',
     'http://192.168.1.100/ISAPI/Event/notification/alertStream',
     'http://192.168.1.100/ISAPI/Streaming/channels/201/picture',
     'Backyard - DS-2CD1343G2-LIU'),
    ('Parking Area 4K', 'hikvision_nvr', '192.168.1.100', 3,
     'rtsp://admin:YourNVRPassword123@192.168.1.100:554/Streaming/Channels/301',
     'rtsp://admin:YourNVRPassword123@192.168.1.100:554/Streaming/Channels/302',
     'http://192.168.1.100/ISAPI/Event/notification/alertStream',
     'http://192.168.1.100/ISAPI/Streaming/channels/301/picture',
     'Parking lot - CP-UNC-TA81L3C-LQ'),
    ('Side Entrance DVR', 'hikvision_dvr', '192.168.1.101', 1,
     'rtsp://admin:YourDVRPassword123@192.168.1.101:554/Streaming/Channels/101',
     'rtsp://admin:YourDVRPassword123@192.168.1.101:554/Streaming/Channels/102',
     'http://192.168.1.101/ISAPI/Event/notification/alertStream',
     'http://192.168.1.101/ISAPI/Streaming/channels/101/picture',
     'Side entrance - DVR Channel 1')
ON CONFLICT DO NOTHING;
