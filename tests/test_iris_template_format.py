import importlib.util
from pathlib import Path

import cv2
import numpy as np


MODULE_PATH = Path(__file__).resolve().parents[1] / "iris_extract.py"


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


def test_process_eye_in_memory_when_out_dir_none():
    module = load_module()
    img = np.full((500, 500, 3), 220, dtype=np.uint8)
    cv2.circle(img, (250, 250), 120, (180, 180, 180), -1)
    cv2.circle(img, (250, 250), 60, (90, 90, 90), -1)

    code, cmask = module.process_eye(img, "synthetic_eye", out_dir=None)

    assert code.shape == (256, 512)
    assert cmask.shape == (256, 512)
    assert code.dtype == np.uint8
    assert cmask.dtype == np.uint8


def test_noise_mask_occludes_eyelid_sectors():
    module = load_module()
    polar = np.full((64, 512), 128, dtype=np.uint8)
    valid = np.ones((64, 512), dtype=np.uint8)

    mask = module.noise_mask(polar, valid)

    sec1_start, sec1_end = int(512 * 0.20), int(512 * 0.30)
    sec2_start, sec2_end = int(512 * 0.70), int(512 * 0.80)

    assert np.all(mask[:, sec1_start:sec1_end] == 0)
    assert np.all(mask[:, sec2_start:sec2_end] == 0)
    # Outside sectors should remain valid
    assert np.all(mask[:, :sec1_start] == 1)


def test_gabor_bank_caching():
    module = load_module()
    bank1 = module.gabor_bank()
    bank2 = module.gabor_bank()
    assert bank1 is bank2


def test_find_pupil_empty_vals_fallback():
    module = load_module()
    eye_gray = np.full((100, 100), 128, dtype=np.uint8)
    # Put iris completely outside the image bounds so disk has 0 pixels
    iris = (500, 500, 10)
    cx, cy, r = module.find_pupil(eye_gray, iris)
    assert (cx, cy, r) == (500, 500, int(0.35 * 10))


def test_find_pupil_clamps_drifting_center():
    module = load_module()
    eye_gray = np.full((200, 200), 200, dtype=np.uint8)
    # Draw a dark spot far from iris center (100, 100)
    cv2.circle(eye_gray, (125, 100), 5, 10, -1)
    iris = (100, 100, 50)  # 0.3 * 50 = 15; distance from (125, 100) is 25 > 15
    cx, cy, r = module.find_pupil(eye_gray, iris)
    assert (cx, cy) == (100, 100)


def test_find_iris_fallback_radius_clamped():
    module = load_module()
    # Image where no Hough circles are found, and almost everything is dark
    eye_gray = np.zeros((100, 100), dtype=np.uint8)
    _, _, r = module.find_iris(eye_gray)
    assert r <= int(0.40 * 100)


def test_hamming_insufficient_overlap_returns_one():
    module = load_module()
    code1 = np.ones((256, 512), dtype=np.uint8)
    code2 = np.ones((256, 512), dtype=np.uint8)
    mask1 = np.zeros((256, 512), dtype=np.uint8)
    mask2 = np.zeros((256, 512), dtype=np.uint8)
    # Only 10 overlapping bits (< 64 threshold)
    mask1[:10, 0] = 1
    mask2[:10, 0] = 1

    dist = module.hamming(code1, mask1, code2, mask2)
    assert dist == 1.0
