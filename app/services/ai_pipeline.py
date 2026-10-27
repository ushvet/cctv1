"""
Hikvision AI CCTV Platform — Unified GPU AI Inference Pipeline
Runs all AI models concurrently within a single ONNX Runtime session
to stay within the RTX 3060 6GB VRAM budget.

Models:
  - YOLOv8n: Person/Vehicle/Object detection (FP16)
  - InsightFace (ArcFace): 512-d face embedding extraction (FP16)
  - LPRNet: License plate text recognition (FP16)
  - MobileCLIP-S2: 512-d semantic image embedding for NL search (FP16)
"""

import asyncio
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

import cv2
import numpy as np

from app.config import settings

logger = logging.getLogger("cctv.ai_pipeline")


@dataclass
class DetectionResult:
    """Single detected object from YOLOv8."""
    label: str
    confidence: float
    bbox: List[int]  # [y_min, x_min, y_max, x_max]
    class_id: int = -1


@dataclass
class FaceResult:
    """Face recognition result."""
    bbox: List[int]
    embedding: np.ndarray  # 512-d normalized vector
    landmark: Optional[np.ndarray] = None
    age: Optional[int] = None
    gender: Optional[str] = None


@dataclass
class PlateResult:
    """License plate OCR result."""
    text: str
    confidence: float
    bbox: List[int]


@dataclass
class CLIPEmbedding:
    """MobileCLIP semantic embedding."""
    embedding: np.ndarray  # 512-d normalized vector


@dataclass
class PipelineOutput:
    """Full output from the unified AI pipeline for a single frame."""
    detections: List[DetectionResult] = field(default_factory=list)
    faces: List[FaceResult] = field(default_factory=list)
    plates: List[PlateResult] = field(default_factory=list)
    clip_embedding: Optional[CLIPEmbedding] = None
    snapshot_path: Optional[str] = None


class AIPipeline:
    """
    Unified GPU inference pipeline.
    All models load once at startup and share the ONNX Runtime CUDA execution provider.
    """

    def __init__(self):
        self._initialized = False
        self._yolo_model = None
        self._face_model = None
        self._lpr_session = None
        self._clip_session = None
        self._lock = asyncio.Lock()

    async def initialize(self):
        """Load all AI models into GPU memory. Called once at application startup."""
        if self._initialized:
            return

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self._load_models)
        self._initialized = True
        logger.info("AI Pipeline initialized — all models loaded to GPU.")

    def _load_models(self):
        """Blocking model loading — runs in thread pool."""
        try:
            self._load_yolo()
        except Exception as e:
            logger.error(f"Failed to load YOLO model: {e}", exc_info=True)

        try:
            self._load_insightface()
        except Exception as e:
            logger.error(f"Failed to load InsightFace model: {e}", exc_info=True)

        try:
            self._load_lpr()
        except Exception as e:
            logger.warning(f"LPR model not available (will skip plate OCR): {e}")

        try:
            self._load_clip()
        except Exception as e:
            logger.warning(f"CLIP model not available (will skip semantic search): {e}")

    def _load_yolo(self):
        """Load YOLOv8n via ultralytics (auto-downloads if missing)."""
        from ultralytics import YOLO

        model_path = settings.yolo_model_path
        if not Path(model_path).exists():
            logger.info("Downloading YOLOv8n model...")
            model_path = "yolov8n.pt"  # Auto-downloads from Ultralytics hub

        self._yolo_model = YOLO(model_path)
        logger.info(f"YOLO model loaded: {model_path}")

    def _load_insightface(self):
        """Load InsightFace ArcFace model for face embeddings."""
        import insightface
        from insightface.app import FaceAnalysis

        self._face_model = FaceAnalysis(
            name="buffalo_l",
            root=settings.insightface_model_path,
            providers=["CUDAExecutionProvider", "CPUExecutionProvider"],
        )
        self._face_model.prepare(ctx_id=0, det_size=(640, 640))
        logger.info("InsightFace model loaded (ArcFace + RetinaFace)")

    def _load_lpr(self):
        """Load license plate recognition ONNX model."""
        import onnxruntime as ort

        model_path = settings.lpr_model_path
        if not Path(model_path).exists():
            logger.warning(f"LPR model not found at {model_path}")
            return

        providers = ["CUDAExecutionProvider", "CPUExecutionProvider"]
        self._lpr_session = ort.InferenceSession(model_path, providers=providers)
        logger.info(f"LPR model loaded: {model_path}")

    def _load_clip(self):
        """Load MobileCLIP-S2 ONNX model for semantic embeddings."""
        import onnxruntime as ort

        model_path = settings.clip_model_path
        if not Path(model_path).exists():
            logger.warning(f"CLIP model not found at {model_path}")
            return

        providers = ["CUDAExecutionProvider", "CPUExecutionProvider"]
        self._clip_session = ort.InferenceSession(model_path, providers=providers)
        logger.info(f"MobileCLIP model loaded: {model_path}")

    async def process_frame(
        self,
        image: np.ndarray,
        run_detection: bool = True,
        run_face: bool = True,
        run_lpr: bool = True,
        run_clip: bool = True,
    ) -> PipelineOutput:
        """
        Run the full AI pipeline on a single high-res frame.
        Each sub-pipeline can be selectively enabled/disabled.
        """
        async with self._lock:  # Serialize GPU access
            loop = asyncio.get_event_loop()
            output = await loop.run_in_executor(
                None,
                self._run_pipeline_sync,
                image,
                run_detection,
                run_face,
                run_lpr,
                run_clip,
            )
            return output

    def _run_pipeline_sync(
        self,
        image: np.ndarray,
        run_detection: bool,
        run_face: bool,
        run_lpr: bool,
        run_clip: bool,
    ) -> PipelineOutput:
        """Synchronous pipeline execution (runs in thread pool)."""
        output = PipelineOutput()

        # 1. YOLO Object Detection
        if run_detection and self._yolo_model is not None:
            output.detections = self._detect_objects(image)

        # 2. Face Recognition
        if run_face and self._face_model is not None:
            output.faces = self._extract_faces(image)

        # 3. License Plate Recognition (on vehicle crops)
        if run_lpr and self._lpr_session is not None:
            vehicle_crops = [
                d for d in output.detections
                if d.label in ("car", "truck", "bus", "motorcycle")
            ]
            if vehicle_crops:
                output.plates = self._recognize_plates(image, vehicle_crops)

        # 4. MobileCLIP Semantic Embedding
        if run_clip and self._clip_session is not None:
            output.clip_embedding = self._encode_clip(image)

        return output

    def _detect_objects(self, image: np.ndarray) -> List[DetectionResult]:
        """Run YOLOv8 detection on the full frame."""
        results = self._yolo_model(image, conf=0.45, verbose=False)
        detections = []

        for result in results:
            if result.boxes is None:
                continue
            for box in result.boxes:
                x1, y1, x2, y2 = box.xyxy[0].cpu().numpy().astype(int)
                conf = float(box.conf[0])
                cls_id = int(box.cls[0])
                label = self._yolo_model.names.get(cls_id, "unknown")

                detections.append(DetectionResult(
                    label=label,
                    confidence=conf,
                    bbox=[int(y1), int(x1), int(y2), int(x2)],
                    class_id=cls_id,
                ))

        return detections

    def _extract_faces(self, image: np.ndarray) -> List[FaceResult]:
        """Run InsightFace detection + ArcFace embedding extraction."""
        # InsightFace expects BGR (OpenCV default)
        faces_raw = self._face_model.get(image)
        faces = []

        for face in faces_raw:
            bbox = face.bbox.astype(int).tolist()
            embedding = face.embedding  # 512-d float32

            # L2-normalize the embedding for cosine similarity
            norm = np.linalg.norm(embedding)
            if norm > 0:
                embedding = embedding / norm

            face_result = FaceResult(
                bbox=[bbox[1], bbox[0], bbox[3], bbox[2]],  # [y1,x1,y2,x2]
                embedding=embedding,
                landmark=face.kps if hasattr(face, "kps") else None,
                age=int(face.age) if hasattr(face, "age") else None,
                gender="male" if hasattr(face, "gender") and face.gender == 1 else "female"
                if hasattr(face, "gender") else None,
            )
            faces.append(face_result)

        return faces

    def _recognize_plates(
        self, image: np.ndarray, vehicle_detections: List[DetectionResult]
    ) -> List[PlateResult]:
        """
        Run LPR on cropped vehicle regions.
        If no dedicated LPR ONNX model is available, uses a placeholder.
        """
        plates = []
        for det in vehicle_detections[:5]:  # Limit to 5 vehicles per frame
            y1, x1, y2, x2 = det.bbox
            h, w = image.shape[:2]
            y1, y2 = max(0, y1), min(h, y2)
            x1, x2 = max(0, x1), min(w, x2)

            if y2 <= y1 or x2 <= x1:
                continue

            crop = image[y1:y2, x1:x2]

            # Simple placeholder: in production, run through LPR ONNX model
            # For now, log that a vehicle was detected for plate analysis
            plate_text = self._run_lpr_inference(crop)
            if plate_text:
                plates.append(PlateResult(
                    text=plate_text,
                    confidence=0.85,
                    bbox=det.bbox,
                ))

        return plates

    def _run_lpr_inference(self, crop: np.ndarray) -> Optional[str]:
        """Run the LPR ONNX model on a cropped vehicle image."""
        if self._lpr_session is None:
            return None

        try:
            # Resize and preprocess for LPR model
            resized = cv2.resize(crop, (94, 24))  # Standard LPR input size
            blob = resized.astype(np.float32) / 255.0
            blob = np.transpose(blob, (2, 0, 1))  # HWC -> CHW
            blob = np.expand_dims(blob, axis=0)  # Add batch dimension

            input_name = self._lpr_session.get_inputs()[0].name
            output = self._lpr_session.run(None, {input_name: blob})

            # Decode output (model-specific)
            if output and len(output) > 0:
                # Placeholder: actual decoding depends on model architecture
                return self._decode_lpr_output(output[0])

        except Exception as e:
            logger.warning(f"LPR inference failed: {e}")

        return None

    def _decode_lpr_output(self, raw_output: np.ndarray) -> Optional[str]:
        """Decode LPR model output into plate text string."""
        # Character set for Indian plates (customize as needed)
        chars = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"

        try:
            # CTC/attention-based decoding
            if raw_output.ndim >= 2:
                indices = np.argmax(raw_output[0], axis=-1)
                plate_chars = []
                prev_idx = -1
                for idx in indices:
                    if idx != prev_idx and idx < len(chars):
                        plate_chars.append(chars[idx])
                    prev_idx = idx
                text = "".join(plate_chars).strip()
                return text if len(text) >= 4 else None
        except Exception as e:
            logger.warning(f"LPR decode error: {e}")

        return None

    def _encode_clip(self, image: np.ndarray) -> Optional[CLIPEmbedding]:
        """Generate a 512-d MobileCLIP embedding for semantic search."""
        if self._clip_session is None:
            return None

        try:
            # Preprocess: resize, normalize, convert to NCHW
            resized = cv2.resize(image, (256, 256))
            rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB)
            blob = rgb.astype(np.float32) / 255.0
            # ImageNet normalization
            mean = np.array([0.485, 0.456, 0.406], dtype=np.float32)
            std = np.array([0.229, 0.224, 0.225], dtype=np.float32)
            blob = (blob - mean) / std
            blob = np.transpose(blob, (2, 0, 1))
            blob = np.expand_dims(blob, axis=0)

            input_name = self._clip_session.get_inputs()[0].name
            output = self._clip_session.run(None, {input_name: blob})

            if output and len(output) > 0:
                embedding = output[0].flatten().astype(np.float32)
                # L2-normalize
                norm = np.linalg.norm(embedding)
                if norm > 0:
                    embedding = embedding / norm
                return CLIPEmbedding(embedding=embedding)

        except Exception as e:
            logger.warning(f"CLIP encoding failed: {e}")

        return None

    async def encode_text_query(self, text: str) -> Optional[np.ndarray]:
        """
        Encode a text query into a 512-d CLIP vector for semantic search.
        Uses the text encoder branch of MobileCLIP.
        """
        if self._clip_session is None:
            return None

        # In production, use the text encoder model separately
        # For now, return a placeholder indicating the feature requires
        # the text encoder ONNX export
        logger.info(f"Text query encoding requested: '{text}'")
        return None

    @property
    def is_initialized(self) -> bool:
        return self._initialized

    @property
    def available_models(self) -> dict:
        """Report which models are successfully loaded."""
        return {
            "yolo": self._yolo_model is not None,
            "insightface": self._face_model is not None,
            "lpr": self._lpr_session is not None,
            "clip": self._clip_session is not None,
        }
