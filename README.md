# Hikvision AI CCTV Command Center & Surveillance Platform

An enterprise-grade, GPU-accelerated AI CCTV surveillance platform designed for **Hikvision NVRs (DS-7608NXI-K1)**, **Hikvision DVRs (DS-7A08HQHI-K1)**, and **CP Plus IP cameras**. Features real-time WebRTC live streaming, two-way audio intercom talkback, object detection (YOLOv8), face recognition (InsightFace), license plate recognition (PaddleOCR), and semantic natural language video search (MobileCLIP + pgvector).

---

## 🌟 Key Features

- **⚡ Real-Time Live Streaming**: Ultra-low-latency WebRTC streaming powered by `go2rtc` and Frigate NVR.
- **🎙️ Two-Way Audio Intercom**: Talkback functionality allowing operators to broadcast voice from the browser directly through the camera's built-in speaker via Hikvision ISAPI backchannels.
- **🧠 Hardware-Accelerated AI Pipeline**:
  - **Object Tracking**: YOLOv8 (humans, vehicles, animals) with TensorRT/CUDA acceleration on NVIDIA GPUs.
  - **Face Recognition**: InsightFace ArcFace with VIP, Staff, Family, and Blacklist registries.
  - **License Plate Recognition (ANPR)**: Text detection & OCR for vehicle monitoring and access control.
  - **Natural Language Search**: Semantic video footage retrieval using MobileCLIP embeddings stored in PostgreSQL (`pgvector`).
- **📊 Modern Web Command Center**: Responsive dark-mode dashboard with real-time WebSocket alerts, per-camera live audio listening, snapshot triggers, and event log auditing.

---

## 🏗️ Architecture

```
[Hikvision NVR / DVR / IP Cameras]
       │ (RTSP / ISAPI Backchannel)
       ▼
 [Frigate NVR + go2rtc] ──────► Port 1984 (WebRTC / MSE / RTSP Restream)
       │ (MQTT Events / Frames)
       ▼
 [Mosquitto MQTT Broker]
       │
       ▼
 [FastAPI AI Backend] ────────► GPU Inference (YOLOv8 + InsightFace + MobileCLIP)
       │
       ├──► [PostgreSQL + pgvector] (Events, Faces, Plates, Embeddings)
       ├──► [Redis] (Cache & PubSub)
       └──► Port 8000 (REST API + Web UI + WebSocket Alerts)
```

---

## 🚀 Quick Start

### Prerequisites

- **Docker Desktop** with WSL2 and NVIDIA Container Toolkit enabled
- NVIDIA GPU (RTX 3060 or higher recommended)
- Network connectivity to camera recorders (NVR / DVR)

### 1. Configuration

Copy the example environment file and configure credentials:

```bash
cp .env.example .env
```

Review camera channel mappings in `config/frigate.yml`:

```yaml
go2rtc:
  streams:
    front_gate_panoramic:
      - "rtsp://admin:password@192.168.0.29:554/Streaming/Channels/201"
      - "isapi://admin:password@192.168.0.65:80/" # Two-way audio speaker backchannel
```

### 2. Launch Services

Start the full stack with Docker Compose:

```bash
docker compose up -d
```

### 3. Access Services

- **Main AI Dashboard**: `http://localhost:8000/`
- **go2rtc Web Console**: `http://localhost:1984/`
- **Frigate NVR Console**: `http://localhost:5000/`
- **Backend API Docs**: `http://localhost:8000/docs`

---

## 🔒 Security Notice

Do not commit private credentials, passwords, or production `.env` files to public repositories. Ensure network firewalls restrict camera RTSP/ISAPI ports to the local network or VPN.
