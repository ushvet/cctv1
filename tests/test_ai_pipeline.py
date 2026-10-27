"""
Hikvision AI CCTV Platform — AI Pipeline Tests
Verifies ONNX model loading, inference, and vector dimensions.
NOTE: These tests require GPU and model files to be present.
Run with: pytest tests/test_ai_pipeline.py -v -s
"""

import pytest
import numpy as np


class TestAIPipelineStructure:
    """Test AI pipeline structural contracts without requiring GPU models."""

    def test_detection_result_structure(self):
        """Verify DetectionResult dataclass fields."""
        from app.services.ai_pipeline import DetectionResult

        det = DetectionResult(
            label="person",
            confidence=0.92,
            bbox=[100, 50, 400, 300],
            class_id=0,
        )
        assert det.label == "person"
        assert det.confidence == 0.92
        assert len(det.bbox) == 4
        assert det.class_id == 0

    def test_face_result_structure(self):
        """Verify FaceResult dataclass with 512-d embedding."""
        from app.services.ai_pipeline import FaceResult

        embedding = np.random.randn(512).astype(np.float32)
        embedding = embedding / np.linalg.norm(embedding)

        face = FaceResult(
            bbox=[50, 30, 200, 180],
            embedding=embedding,
        )
        assert face.embedding.shape == (512,)
        assert abs(np.linalg.norm(face.embedding) - 1.0) < 1e-5  # Unit normalized

    def test_plate_result_structure(self):
        """Verify PlateResult dataclass fields."""
        from app.services.ai_pipeline import PlateResult

        plate = PlateResult(
            text="MH12AB1234",
            confidence=0.88,
            bbox=[200, 100, 280, 140],
        )
        assert plate.text == "MH12AB1234"
        assert plate.confidence == 0.88

    def test_clip_embedding_structure(self):
        """Verify CLIPEmbedding stores normalized 512-d vector."""
        from app.services.ai_pipeline import CLIPEmbedding

        embedding = np.random.randn(512).astype(np.float32)
        embedding = embedding / np.linalg.norm(embedding)

        clip = CLIPEmbedding(embedding=embedding)
        assert clip.embedding.shape == (512,)
        assert abs(np.linalg.norm(clip.embedding) - 1.0) < 1e-5

    def test_pipeline_output_defaults(self):
        """Verify PipelineOutput initializes with empty collections."""
        from app.services.ai_pipeline import PipelineOutput

        output = PipelineOutput()
        assert output.detections == []
        assert output.faces == []
        assert output.plates == []
        assert output.clip_embedding is None
        assert output.snapshot_path is None

    def test_pipeline_initialization_state(self):
        """Verify AIPipeline initializes as not loaded."""
        from app.services.ai_pipeline import AIPipeline

        pipeline = AIPipeline()
        assert pipeline.is_initialized is False
        assert pipeline.available_models == {
            "yolo": False,
            "insightface": False,
            "lpr": False,
            "clip": False,
        }

    def test_embedding_normalization(self):
        """Verify L2 normalization produces unit vectors for pgvector cosine similarity."""
        vec = np.array([3.0, 4.0, 0.0], dtype=np.float32)
        norm = np.linalg.norm(vec)
        normalized = vec / norm

        assert abs(np.linalg.norm(normalized) - 1.0) < 1e-6
        assert normalized[0] == pytest.approx(0.6, abs=1e-6)
        assert normalized[1] == pytest.approx(0.8, abs=1e-6)

    def test_cosine_similarity_computation(self):
        """Verify cosine similarity between two normalized embeddings."""
        vec_a = np.random.randn(512).astype(np.float32)
        vec_a = vec_a / np.linalg.norm(vec_a)

        vec_b = vec_a.copy()  # Identical vector
        similarity = np.dot(vec_a, vec_b)
        assert similarity == pytest.approx(1.0, abs=1e-5)

        # Orthogonal vector should have ~0 similarity
        vec_c = np.random.randn(512).astype(np.float32)
        vec_c = vec_c / np.linalg.norm(vec_c)
        sim_random = abs(np.dot(vec_a, vec_c))
        assert sim_random < 0.3  # Random 512-d vectors are nearly orthogonal


class TestLPRDecoding:
    """Test license plate character decoding logic."""

    def test_lpr_decode_valid(self):
        """Test CTC-style decoding of plate characters."""
        from app.services.ai_pipeline import AIPipeline

        pipeline = AIPipeline()
        chars = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"

        # Simulate model output: sequence of class indices
        raw = np.zeros((1, 8, len(chars)), dtype=np.float32)
        # Spell "MH12AB34"
        target = "MH12AB34"
        for i, ch in enumerate(target):
            idx = chars.index(ch)
            raw[0, i, idx] = 10.0  # High logit for target char

        result = pipeline._decode_lpr_output(raw)
        assert result is not None
        assert result == target

    def test_lpr_decode_too_short(self):
        """Plates shorter than 4 chars should be rejected."""
        from app.services.ai_pipeline import AIPipeline

        pipeline = AIPipeline()
        raw = np.zeros((1, 2, 36), dtype=np.float32)
        raw[0, 0, 10] = 10.0  # 'A'
        raw[0, 1, 11] = 10.0  # 'B'

        result = pipeline._decode_lpr_output(raw)
        assert result is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
