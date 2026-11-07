import os
import json
import logging
from datetime import datetime
import cv2
import numpy as np
from django.conf import settings

logger = logging.getLogger('iris_debug_logger')

DEBUG_DIR = getattr(settings, 'IRIS_DEBUG_DIR', os.path.join(settings.BASE_DIR, 'debug_captures'))
ENABLE_LOGGING = getattr(settings, 'IRIS_ENABLE_IMAGE_LOGGING', True)


def _ensure_dir(path):
    try:
        os.makedirs(path, exist_ok=True)
    except Exception:
        pass


def _safe_imwrite(filepath, img):
    if img is None or img.size == 0:
        return False
    try:
        ext = os.path.splitext(filepath)[1]
        success, buf = cv2.imencode(ext, img)
        if success:
            with open(filepath, 'wb') as f:
                f.write(buf.tobytes())
            return True
    except Exception as exc:
        logger.warning("Failed to write debug capture to %s: %s", filepath, exc)
    return False


def _annotate_capture(image_array, detection, banner_text, sub_text=""):
    if image_array is None or image_array.size == 0:
        return None
    annotated = image_array.copy()
    h, w = annotated.shape[:2]

    # Draw face box if detected
    face_box = detection.get('face_box')
    if face_box:
        fx, fy, fw, fh = face_box
        cv2.rectangle(annotated, (int(fx), int(fy)), (int(fx + fw), int(fy + fh)), (255, 180, 50), 2)
        cv2.putText(annotated, "FACE", (int(fx), max(20, int(fy) - 8)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 180, 50), 2, cv2.LINE_AA)

    # Draw eye boxes
    eyes = detection.get('eyes', [])
    for idx, (ex, ey, ew, eh) in enumerate(eyes):
        cv2.rectangle(annotated, (int(ex), int(ey)), (int(ex + ew), int(ey + eh)), (0, 220, 0), 2)
        cv2.putText(annotated, f"EYE #{idx+1}", (int(ex), max(20, int(ey) - 6)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 220, 0), 1, cv2.LINE_AA)

    # Draw iris/pupil circles if present
    irises = detection.get('irises', [])
    for iris_info in irises:
        iris_circle = iris_info.get('iris')
        pupil_circle = iris_info.get('pupil')
        if iris_circle:
            cv2.circle(annotated, (int(iris_circle[0]), int(iris_circle[1])),
                       int(iris_circle[2]), (0, 0, 255), 2)
        if pupil_circle:
            cv2.circle(annotated, (int(pupil_circle[0]), int(pupil_circle[1])),
                       int(pupil_circle[2]), (0, 255, 255), 2)

    # Draw header banner for quick visual inspection
    banner_h = 52 if sub_text else 36
    cv2.rectangle(annotated, (0, 0), (w, banner_h), (20, 20, 20), -1)
    cv2.putText(annotated, banner_text, (10, 24),
                cv2.FONT_HERSHEY_SIMPLEX, 0.60, (0, 255, 220), 2, cv2.LINE_AA)
    if sub_text:
        cv2.putText(annotated, sub_text, (10, 44),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (200, 200, 200), 1, cv2.LINE_AA)

    return annotated


def log_debug_capture(
    image_array,
    action,
    status,
    identifier=None,
    matched_user=None,
    failure_reason=None,
    comparisons=None,
    error=None,
    detection=None,
):
    """
    Saves captured frame, crops, annotated visual overlay, and structured JSON record
    to debug_captures/ for real-time triage and biometric debugging.
    """
    if not ENABLE_LOGGING or image_array is None:
        return None

    _ensure_dir(DEBUG_DIR)
    now = datetime.now()
    timestamp_str = now.strftime('%Y%m%d_%H%M%S_%f')[:19]
    iso_time = now.isoformat()

    # Determine detection if not provided
    if detection is None:
        try:
            from iris_auth_app.services import detect_face_and_iris
            detection = detect_face_and_iris(image_array)
        except Exception:
            detection = {'face_detected': False, 'eyes_detected': 0, 'eyes': [], 'irises': []}

    target_name = str(matched_user or identifier or failure_reason or status or 'capture')
    base_filename = f"{timestamp_str}_{action}_{status}_{target_name}"
    raw_path = os.path.join(DEBUG_DIR, f"{base_filename}_raw.jpg")
    annotated_path = os.path.join(DEBUG_DIR, f"{base_filename}_annotated.jpg")

    _safe_imwrite(raw_path, image_array)

    # Save eye crops
    saved_crops = []
    eyes = detection.get('eyes', [])
    for i, (ex, ey, ew, eh) in enumerate(eyes):
        pad = int(0.20 * ew)
        h, w = image_array.shape[:2]
        crop = image_array[max(0, int(ey) - pad):min(h, int(ey + eh) + pad), max(0, int(ex) - pad):min(w, int(ex + ew) + pad)]
        if crop.size > 0:
            crop_path = os.path.join(DEBUG_DIR, f"{base_filename}_eye{i}.jpg")
            if _safe_imwrite(crop_path, crop):
                saved_crops.append(os.path.basename(crop_path))

    # Save annotated overlay
    sub = ""
    if comparisons:
        best = min(comparisons, key=lambda c: c.get('fused_distance', 999))
        sub = f"Best: {best.get('username')} (d_fused={best.get('fused_distance')} face={best.get('face_distance')})"
    elif error:
        sub = f"Error: {error}"

    banner = f"[{action.upper()}] Status: {status} | Target: {target_name}"
    annotated = _annotate_capture(image_array, detection, banner, sub)
    if annotated is not None:
        _safe_imwrite(annotated_path, annotated)

    # Structured JSON log record
    log_entry = {
        'timestamp': iso_time,
        'action': str(action),
        'status': str(status),
        'identifier': str(identifier) if identifier else None,
        'matched_user': str(matched_user) if matched_user else None,
        'failure_reason': str(failure_reason) if failure_reason else None,
        'error': str(error) if error else None,
        'raw_image': os.path.basename(raw_path),
        'annotated_image': os.path.basename(annotated_path),
        'eye_crops': saved_crops,
        'detection': {
            'face_detected': bool(detection.get('face_detected')),
            'eyes_detected': int(detection.get('eyes_detected', len(eyes))),
            'eyes_boxes': [[int(coord) for coord in e] for e in eyes],
        },
        'comparisons': comparisons or [],
    }

    log_file = os.path.join(DEBUG_DIR, 'captures_log.jsonl')
    try:
        with open(log_file, 'a', encoding='utf-8') as f:
            f.write(json.dumps(log_entry, default=str) + '\n')
    except Exception as exc:
        logger.warning("Could not write captures_log.jsonl: %s", exc)

    comp_str = ""
    if comparisons:
        comp_summary = [
            f"{c.get('username')}:fused={c.get('fused_distance')}(face={c.get('face_distance')})"
            for c in comparisons
        ]
        comp_str = f" | comps=[{', '.join(comp_summary)}]"
    print(f"\n[CAPTURE_DEBUG] {iso_time} | action={action} | status={status} | match={matched_user}{comp_str} | saved={os.path.basename(annotated_path)}\n")

    return log_entry
