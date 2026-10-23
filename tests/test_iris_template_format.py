import importlib.util
from pathlib import Path

import cv2
import numpy as np


MODULE_PATH = Path(r"c:\Users\Aysha\OneDrive\Desktop\iris_extract.py")


def load_module():
    spec = importlib.util.spec_from_file_location("iris_extract", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_encode_returns_binary_code_and_mask_shape():
    module = load_module()
    enhanced = np.full((64, 512), 128, dtype=np.uint8)
    mask = np.ones((64, 512), dtype=np.uint8)

    code, cmask = module.encode(enhanced, mask)

    assert code.shape == (256, 512)
    assert cmask.shape == (256, 512)
    assert code.dtype == np.uint8
    assert cmask.dtype == np.uint8
    assert set(np.unique(code)).issubset({0, 1})
    assert set(np.unique(cmask)).issubset({0, 1})


def test_hamming_distance_is_zero_for_identical_templates():
    module = load_module()
    enhanced = np.full((64, 512), 128, dtype=np.uint8)
    mask = np.ones((64, 512), dtype=np.uint8)

    code, cmask = module.encode(enhanced, mask)
    distance = module.hamming(code, cmask, code, cmask)

    assert distance == 0.0


def test_hamming_distance_is_positive_for_different_templates():
    module = load_module()
    enhanced = np.full((64, 512), 128, dtype=np.uint8)
    mask = np.ones((64, 512), dtype=np.uint8)

    code, cmask = module.encode(enhanced, mask)
    other_code = code.copy()
    other_code[:, 1:] = 1 - other_code[:, 1:]
    distance = module.hamming(code, cmask, other_code, cmask)

    assert 0.0 < distance < 1.0


def test_process_eye_produces_template_and_debug_files(tmp_path):
    module = load_module()
    img = np.full((500, 500, 3), 220, dtype=np.uint8)
    cv2.circle(img, (250, 250), 120, (180, 180, 180), -1)
    cv2.circle(img, (250, 250), 60, (90, 90, 90), -1)

    code, cmask = module.process_eye(img, "synthetic_eye", str(tmp_path))

    assert code.shape == (256, 512)
    assert cmask.shape == (256, 512)
    assert code.dtype == np.uint8
    assert cmask.dtype == np.uint8
    assert (tmp_path / "synthetic_eye_segmented.png").exists()
    assert (tmp_path / "synthetic_eye_normalised.png").exists()
    assert (tmp_path / "synthetic_eye_structure.png").exists()
    assert (tmp_path / "synthetic_eye_iriscode.png").exists()
    assert (tmp_path / "synthetic_eye_code.npz").exists()
