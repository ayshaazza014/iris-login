import os
import importlib.util
import logging
import math
from pathlib import Path

import cv2
import numpy as np
from django.core.exceptions import ValidationError

from .models import IrisTemplate, IrisUser


logger = logging.getLogger(__name__)
MODULE_PATH = Path(__file__).resolve().parents[1] / 'iris_extract.py'
MATCH_THRESHOLD = float(os.environ.get('IRIS_MATCH_THRESHOLD', '0.35'))
VERIFICATION_THRESHOLD = float(os.environ.get('IRIS_VERIFICATION_THRESHOLD', '0.35'))
FUSION_FACE_WEIGHT = float(os.environ.get('IRIS_FACIAL_FEATURE_WEIGHT', '0.20'))
TEMPLATE_ENCODING_VERSION = 'gabor-eye-crop-v2'

_iris_module = None


def load_iris_module():
    global _iris_module
    if _iris_module is not None:
        return _iris_module
    try:
        import iris_extract
        _iris_module = iris_extract
    except ImportError:
        spec = importlib.util.spec_from_file_location("iris_extract", MODULE_PATH)
        if spec is None or spec.loader is None:
            raise ValidationError("Could not load the iris extraction module.")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _iris_module = module
    return _iris_module


def _coerce_uint8_array(arr, name='array'):
    a = np.asarray(arr)
    if a.dtype != np.uint8:
        if ((a < 0) | (a > 255)).any():
            raise ValidationError(f'Template {name} values are out of bounds for uint8 (0..255).')
        a = a.astype(np.uint8)
    return a


def ensure_iris_template_for_user(
    user,
    code_array,
    mask_array,
    *,
    secondary_code_array=None,
    secondary_mask_array=None,
    facial_features_array=None,
    encoding_version=TEMPLATE_ENCODING_VERSION,
):
    if not isinstance(user, IrisUser):
        raise ValidationError('A valid user instance is required.')
    if code_array is None or mask_array is None:
        raise ValidationError('Both code and mask arrays are required.')

    code = _coerce_uint8_array(code_array, 'code')
    mask = _coerce_uint8_array(mask_array, 'mask')

    if code.shape != mask.shape:
        raise ValidationError('Code and mask shapes must match.')
    if code.size == 0 or mask.size == 0:
        raise ValidationError('Template arrays cannot be empty.')
    if not mask.any():
        raise ValidationError('The iris template contains no usable image data.')

    template, created = IrisTemplate.objects.get_or_create(user=user)
    template.code, code_shape, template.code_dtype = IrisTemplate.serialize_array(code)
    template.mask, mask_shape, template.mask_dtype = IrisTemplate.serialize_array(mask)

    if secondary_code_array is not None and secondary_mask_array is not None:
        sec_code = _coerce_uint8_array(secondary_code_array, 'secondary_code')
        sec_mask = _coerce_uint8_array(secondary_mask_array, 'secondary_mask')
        if sec_code.shape == code.shape and sec_mask.shape == mask.shape and sec_mask.any():
            template.secondary_code, _, _ = IrisTemplate.serialize_array(sec_code)
            template.secondary_mask, _, _ = IrisTemplate.serialize_array(sec_mask)
        else:
            logger.info("Secondary iris template discarded: shape/mask mismatch or empty mask for user '%s'.", user.username)
            template.secondary_code = None
            template.secondary_mask = None
    else:
        template.secondary_code = None
        template.secondary_mask = None

    if facial_features_array is not None:
        facial_arr = np.asarray(facial_features_array, dtype=np.float32)
        template.facial_features = facial_arr.tobytes()

    template.code_shape = ','.join(str(dimension) for dimension in code_shape)
    template.mask_shape = ','.join(str(dimension) for dimension in mask_shape)
    template.encoding_version = encoding_version
    template.enrollment_status = 'active'
    template.save()
    return template


def compare_templates_detailed(code_a, mask_a, code_b, mask_b, max_shift=20, *, feat_a=None, feat_b=None):
    module = load_iris_module()
    if code_a is None or mask_a is None or code_b is None or mask_b is None:
        raise ValidationError('All template arrays are required for comparison.')

    code_a = _coerce_uint8_array(code_a, 'code_a')
    mask_a = _coerce_uint8_array(mask_a, 'mask_a')
    code_b = _coerce_uint8_array(code_b, 'code_b')
    mask_b = _coerce_uint8_array(mask_b, 'mask_b')

    if code_a.shape != code_b.shape or code_a.shape != mask_a.shape or code_b.shape != mask_b.shape:
        raise ValidationError('Template shapes must match for comparison.')

    iris_dist = float(module.hamming(code_a, mask_a, code_b, mask_b, max_shift=max_shift))
    face_dist = None
    weight = 0.0
    fused_dist = iris_dist

    # Multi-feature biometric fusion (iris + facial / periocular features)
    if feat_a is not None and feat_b is not None and hasattr(module, 'compare_facial_features'):
        try:
            fd = module.compare_facial_features(feat_a, feat_b)
            if fd is not None and math.isfinite(fd):
                face_dist = float(fd)
                weight = float(os.environ.get('IRIS_FACIAL_FEATURE_WEIGHT', str(FUSION_FACE_WEIGHT)))
                # Iris gating principle:
                # If iris Hamming distance indicates an impostor eye (> 0.38), facial similarity
                # must NEVER override the non-matching eye to grant access.
                if iris_dist > 0.38:
                    fused_dist = max(iris_dist, (1.0 - weight) * iris_dist + weight * face_dist)
                else:
                    fused_dist = float((1.0 - weight) * iris_dist + weight * face_dist)
        except Exception:
            pass

    return {
        'iris_distance': iris_dist,
        'face_distance': face_dist,
        'fused_distance': fused_dist,
        'weight': weight,
    }


def compare_templates(code_a, mask_a, code_b, mask_b, max_shift=20, *, feat_a=None, feat_b=None):
    details = compare_templates_detailed(
        code_a, mask_a, code_b, mask_b, max_shift=max_shift, feat_a=feat_a, feat_b=feat_b
    )
    return details['fused_distance']


def compare_facial_features(feat_a, feat_b):
    """
    Compare two facial feature vectors and return distance in [0.0, 1.0].
    """
    if feat_a is None or feat_b is None:
        return 1.0
    module = load_iris_module()
    if hasattr(module, 'compare_facial_features'):
        return module.compare_facial_features(feat_a, feat_b)
    return 1.0


def extract_facial_features(image_array):
    """
    Extract complementary facial and periocular feature vector from the image.
    Returns 259-D np.float32 array, or None if extraction fails or no facial region is found.
    """
    if image_array is None:
        return None
    try:
        module = load_iris_module()
        if hasattr(module, 'extract_facial_features'):
            return module.extract_facial_features(image_array)
    except Exception:
        pass
    return None


def extract_template_from_image(image_array):
    module = load_iris_module()
    if image_array is None:
        raise ValidationError('Image data is required.')

    image = np.asarray(image_array)
    if image.ndim != 3 or image.shape[2] != 3:
        raise ValidationError('Image must be a valid BGR array with three channels.')

    try:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        eyes = module.detect_eyes(gray)
    except cv2.error as exc:
        raise ValidationError('Eye detection failed while processing the image. Please capture another image.') from exc
    if not eyes:
        raise ValidationError('No eye was detected in the image. Move closer, face the camera, and try again.')

    sorted_eyes = sorted(eyes, key=lambda eye: eye[2] * eye[3], reverse=True)
    last_error = None
    for eye in sorted_eyes:
        x, y, width, height = eye
        padding = int(0.15 * width)
        eye_region = image[
            max(0, y - padding):min(image.shape[0], y + height + padding),
            max(0, x - padding):min(image.shape[1], x + width + padding),
        ]
        if eye_region.size == 0:
            continue
        try:
            code, mask = module.process_eye(eye_region, 'capture', out_dir=None)
            if code is not None and mask is not None:
                code = np.asarray(code, dtype=np.uint8)
                mask = np.asarray(mask, dtype=np.uint8)
                if code.shape == (256, 512) and mask.shape == (256, 512) and mask.any():
                    if (mask.sum() / mask.size) < 0.20:
                        raise ValidationError('Iris image quality is insufficient (excessive eyelid occlusion or glare).')
                    return code, mask
        except (cv2.error, OSError, ValueError, TypeError) as exc:
            last_error = exc
            continue

    if last_error:
        raise ValidationError('Iris feature extraction failed. Improve lighting and capture the eye again.') from last_error
    raise ValidationError('Iris feature extraction produced an unusable template. Improve lighting and capture again.')


def extract_secondary_template_from_image(image_array):
    """
    If multiple eyes are detected in the image (e.g. from an iPhone or mobile camera),
    extracts the secondary eye template. Returns (code, mask) or (None, None).
    """
    module = load_iris_module()
    try:
        image = np.asarray(image_array)
        if image.ndim != 3 or image.shape[2] != 3:
            return None, None
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        eyes = module.detect_eyes(gray)
        if len(eyes) < 2:
            return None, None
        # Sort by area descending. Primary is eyes[0], secondary is eyes[1]
        sorted_eyes = sorted(eyes, key=lambda eye: eye[2] * eye[3], reverse=True)
        x, y, width, height = sorted_eyes[1]
        padding = int(0.15 * width)
        eye_region = image[
            max(0, y - padding):min(image.shape[0], y + height + padding),
            max(0, x - padding):min(image.shape[1], x + width + padding),
        ]
        if eye_region.size == 0:
            return None, None
        code, mask = module.process_eye(eye_region, 'capture_secondary', out_dir=None)
        if code is not None and mask is not None:
            code = np.asarray(code, dtype=np.uint8)
            mask = np.asarray(mask, dtype=np.uint8)
            if code.shape == (256, 512) and mask.shape == (256, 512) and mask.any():
                return code, mask
    except Exception:
        pass
    return None, None


def detect_face_and_iris(image_array):
    """
    Returns structured detection metrics: face_detected, eyes_detected, irises, iris_detected.
    """
    if image_array is None:
        return {'face_detected': False, 'face_box': None, 'eyes_detected': 0, 'eyes': [], 'irises': [], 'iris_detected': False}
    module = load_iris_module()
    if hasattr(module, 'detect_face_and_iris'):
        return module.detect_face_and_iris(image_array)
    eyes = module.detect_eyes(cv2.cvtColor(image_array, cv2.COLOR_BGR2GRAY)) if hasattr(module, 'detect_eyes') else []
    return {
        'face_detected': len(eyes) > 0,
        'face_box': None,
        'eyes_detected': len(eyes),
        'eyes': eyes,
        'irises': [],
        'iris_detected': len(eyes) > 0,
    }


def extract_all_candidate_templates(image_array):
    """
    Extracts all viable eye templates from the image.
    Always includes the primary template from extract_template_from_image(image_array)
    to preserve 100% compatibility with test mocks.
    If a secondary eye is detected, includes it as a candidate.
    """
    primary_code, primary_mask = extract_template_from_image(image_array)
    candidates = [(primary_code, primary_mask)]

    sec_code, sec_mask = extract_secondary_template_from_image(image_array)
    if sec_code is not None and sec_mask is not None:
        candidates.append((sec_code, sec_mask))

    return candidates


def load_user_template(user):
    if not isinstance(user, IrisUser):
        raise ValidationError('A valid user instance is required.')

    template = IrisTemplate.objects.filter(user=user).first()
    if template is None:
        raise ValidationError('No iris template has been enrolled for this user.')
    if template.encoding_version not in (TEMPLATE_ENCODING_VERSION, 'gabor-v1'):
        raise ValidationError('This iris template needs to be enrolled again using the current capture process.')

    code, mask = template.validate_template()
    if template.encoding_version == 'gabor-v1' and (code.shape != (256, 512) or mask.shape != (256, 512)):
        raise ValidationError('This iris template needs to be enrolled again using the current capture process.')
    return code, mask


def _validate_match_inputs(image_array, threshold):
    if image_array is None:
        raise ValidationError('An image is required for iris verification.')
    if not math.isfinite(threshold) or not 0 <= threshold <= 1:
        raise ValidationError('The iris matching threshold must be between 0 and 1.')


def verify_iris_for_user(identifier, image_array, *, threshold=VERIFICATION_THRESHOLD):
    if not identifier:
        raise ValidationError('A username or student ID is required.')
    _validate_match_inputs(image_array, threshold)

    user = IrisUser.objects.filter(username__iexact=identifier).first()
    if user is None:
        user = IrisUser.objects.filter(student_id__iexact=identifier).first()
    if user is None:
        return None

    best_comp = None
    best_distance = 1.0
    try:
        template = IrisTemplate.objects.filter(user=user).first()
        if template is None:
            return None
        stored_templates = template.get_all_templates()
        captured_templates = extract_all_candidate_templates(image_array)
        stored_facial = template.get_facial_features()
        captured_facial = extract_facial_features(image_array)
        distances = []
        for s_code, s_mask in stored_templates:
            for c_code, c_mask in captured_templates:
                d = compare_templates(
                    s_code,
                    s_mask,
                    c_code,
                    c_mask,
                    feat_a=stored_facial,
                    feat_b=captured_facial,
                )
                if math.isfinite(float(d)):
                    distances.append(float(d))
        if not distances:
            return None
        best_distance = min(distances)
    except (ValidationError, ValueError, TypeError, AttributeError):
        return None

    logger.warning('[VERIFY_EVAL] user=%s best_distance=%.4f (threshold=%.2f)', user.username, best_distance, threshold)
    matched = bool(math.isfinite(float(best_distance)) and best_distance <= threshold)

    try:
        from iris_auth_app.debug_logger import log_debug_capture
        face_d = None
        if stored_facial is not None and captured_facial is not None:
            try:
                face_d = compare_facial_features(stored_facial, captured_facial)
            except Exception:
                pass
        comp_records = [{
            'username': user.username,
            'face_distance': round(float(face_d), 4) if face_d is not None else None,
            'fused_distance': round(float(best_distance), 4),
            'threshold': threshold,
            'matched': matched,
        }]
        log_debug_capture(
            image_array=image_array,
            action='verify',
            status='matched' if matched else 'verify_failed',
            identifier=identifier,
            matched_user=user.username if matched else None,
            failure_reason=None if matched else 'threshold_exceeded',
            comparisons=comp_records,
        )
    except Exception as exc:
        logger.warning('Debug capture logging failed: %s', exc)

    if matched:
        return user
    return None


def identify_user_from_iris_result(image_array, *, threshold=MATCH_THRESHOLD, staff_only=False):
    _validate_match_inputs(image_array, threshold)
    captured_templates = extract_all_candidate_templates(image_array)
    captured_facial = extract_facial_features(image_array)

    templates = IrisTemplate.objects.filter(
        enrollment_status='active',
        encoding_version=TEMPLATE_ENCODING_VERSION,
        user__is_active=True,
        user__is_staff=staff_only,
    ).select_related('user')
    if not staff_only:
        templates = templates.filter(user__is_superuser=False)
    templates = list(templates)
    if not templates:
        return None, 'no_templates'

    matches = []
    all_comparison_records = []
    for template in templates:
        try:
            stored_templates = template.get_all_templates()
            stored_facial = template.get_facial_features()
            distances = []
            for s_code, s_mask in stored_templates:
                for c_code, c_mask in captured_templates:
                    d = compare_templates(
                        s_code,
                        s_mask,
                        c_code,
                        c_mask,
                        feat_a=stored_facial,
                        feat_b=captured_facial,
                    )
                    if math.isfinite(float(d)):
                        distances.append(float(d))
            if not distances:
                continue
            best_distance = min(distances)
            is_match = bool(math.isfinite(float(best_distance)) and best_distance <= threshold)
            face_d = None
            if stored_facial is not None and captured_facial is not None:
                try:
                    face_d = compare_facial_features(stored_facial, captured_facial)
                except Exception:
                    pass
            all_comparison_records.append({
                'username': template.user.username,
                'face_distance': round(float(face_d), 4) if face_d is not None else None,
                'fused_distance': round(float(best_distance), 4),
                'threshold': threshold,
                'matched': is_match,
            })
        except (ValidationError, ValueError, TypeError, AttributeError):
            logger.warning(
                'Skipping invalid active iris template id=%s during authentication.',
                template.pk,
                exc_info=True,
            )
            continue

        logger.warning('[SCAN_EVAL] compared with user=%s best_d=%.4f (threshold=%.2f)', template.user.username, best_distance, threshold)
        if is_match:
            matches.append((best_distance, template.user))

    final_user = None
    final_reason = None
    if not matches:
        final_reason = 'no_match'
    elif len(matches) > 1:
        matches.sort(key=lambda m: m[0])
        # If two matches have virtually identical distance (e.g. mock test collisions), reject as ambiguous
        if matches[0][0] >= matches[1][0] - 0.01:
            final_reason = 'ambiguous'
        else:
            final_user = matches[0][1]
    else:
        final_user = matches[0][1]

    try:
        from iris_auth_app.debug_logger import log_debug_capture
        log_debug_capture(
            image_array=image_array,
            action='staff_login' if staff_only else 'login',
            status='matched' if final_user else (final_reason or 'failed'),
            matched_user=final_user.username if final_user else None,
            failure_reason=final_reason,
            comparisons=all_comparison_records,
        )
    except Exception as exc:
        logger.warning('Debug capture logging failed: %s', exc)

    return final_user, final_reason


def identify_user_from_iris(image_array, *, threshold=MATCH_THRESHOLD, staff_only=False):
    """Public convenience helper resolving IrisUser directly from an image capture (BUG-020)."""
    user, _reason = identify_user_from_iris_result(
        image_array,
        threshold=threshold,
        staff_only=staff_only,
    )
    return user
