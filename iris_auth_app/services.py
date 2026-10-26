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
MATCH_THRESHOLD = 0.32
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


def ensure_iris_template_for_user(
    user,
    code_array,
    mask_array,
    *,
    secondary_code_array=None,
    secondary_mask_array=None,
    encoding_version=TEMPLATE_ENCODING_VERSION,
):
    if not isinstance(user, IrisUser):
        raise ValidationError('A valid user instance is required.')
    if code_array is None or mask_array is None:
        raise ValidationError('Both code and mask arrays are required.')

    code = np.asarray(code_array, dtype=np.uint8)
    mask = np.asarray(mask_array, dtype=np.uint8)

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
        sec_code = np.asarray(secondary_code_array, dtype=np.uint8)
        sec_mask = np.asarray(secondary_mask_array, dtype=np.uint8)
        if sec_code.shape == code.shape and sec_mask.shape == mask.shape and sec_mask.any():
            template.secondary_code, _, _ = IrisTemplate.serialize_array(sec_code)
            template.secondary_mask, _, _ = IrisTemplate.serialize_array(sec_mask)
        else:
            template.secondary_code = None
            template.secondary_mask = None
    else:
        template.secondary_code = None
        template.secondary_mask = None

    template.code_shape = ','.join(str(dimension) for dimension in code_shape)
    template.mask_shape = ','.join(str(dimension) for dimension in mask_shape)
    template.encoding_version = encoding_version
    template.enrollment_status = 'active'
    template.save()
    return template


def compare_templates(code_a, mask_a, code_b, mask_b, max_shift=16):
    module = load_iris_module()
    if code_a is None or mask_a is None or code_b is None or mask_b is None:
        raise ValidationError('All template arrays are required for comparison.')

    code_a = np.asarray(code_a, dtype=np.uint8)
    mask_a = np.asarray(mask_a, dtype=np.uint8)
    code_b = np.asarray(code_b, dtype=np.uint8)
    mask_b = np.asarray(mask_b, dtype=np.uint8)

    if code_a.shape != code_b.shape or code_a.shape != mask_a.shape or code_b.shape != mask_b.shape:
        raise ValidationError('Template shapes must match for comparison.')

    return module.hamming(code_a, mask_a, code_b, mask_b, max_shift=max_shift)


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

    x, y, width, height = max(eyes, key=lambda eye: eye[2] * eye[3])
    padding = int(0.15 * width)
    eye_region = image[
        max(0, y - padding):min(image.shape[0], y + height + padding),
        max(0, x - padding):min(image.shape[1], x + width + padding),
    ]
    if eye_region.size == 0:
        raise ValidationError('The detected eye region is invalid.')

    try:
        code, mask = module.process_eye(eye_region, 'capture', out_dir=None)
    except (cv2.error, OSError, ValueError, TypeError) as exc:
        raise ValidationError('Iris feature extraction failed. Improve lighting and capture the eye again.') from exc

    if code is None or mask is None:
        raise ValidationError('Iris feature extraction failed to produce a code and mask. Please capture again.')
    code = np.asarray(code, dtype=np.uint8)
    mask = np.asarray(mask, dtype=np.uint8)
    if code.size == 0 or mask.size == 0 or code.shape != mask.shape or not mask.any():
        raise ValidationError('Iris feature extraction produced an unusable template. Improve lighting and capture again.')

    return code, mask


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


def verify_iris_for_user(identifier, image_array, *, threshold=MATCH_THRESHOLD):
    if not identifier:
        raise ValidationError('A username or student ID is required.')
    _validate_match_inputs(image_array, threshold)

    user = IrisUser.objects.filter(username__iexact=identifier).first()
    if user is None:
        user = IrisUser.objects.filter(student_id__iexact=identifier).first()
    if user is None:
        return None

    try:
        template = IrisTemplate.objects.filter(user=user).first()
        if template is None:
            return None
        stored_templates = template.get_all_templates()
        captured_templates = extract_all_candidate_templates(image_array)
        distances = []
        for s_code, s_mask in stored_templates:
            for c_code, c_mask in captured_templates:
                d = compare_templates(s_code, s_mask, c_code, c_mask)
                if math.isfinite(float(d)):
                    distances.append(d)
        if not distances:
            return None
        best_distance = min(distances)
    except (ValidationError, ValueError, TypeError, AttributeError):
        return None

    if math.isfinite(float(best_distance)) and best_distance <= threshold:
        return user
    return None


def identify_user_from_iris_result(image_array, *, threshold=MATCH_THRESHOLD, staff_only=False):
    _validate_match_inputs(image_array, threshold)
    captured_templates = extract_all_candidate_templates(image_array)

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
    for template in templates:
        try:
            stored_templates = template.get_all_templates()
            distances = []
            for s_code, s_mask in stored_templates:
                for c_code, c_mask in captured_templates:
                    d = compare_templates(
                        s_code,
                        s_mask,
                        c_code,
                        c_mask,
                    )
                    if math.isfinite(float(d)):
                        distances.append(d)
            if not distances:
                continue
            best_distance = min(distances)
        except (ValidationError, ValueError, TypeError, AttributeError):
            logger.warning(
                'Skipping invalid active iris template id=%s during authentication.',
                template.pk,
                exc_info=True,
            )
            continue

        if math.isfinite(float(best_distance)) and best_distance <= threshold:
            matches.append((best_distance, template.user))

    if not matches:
        return None, 'no_match'
    if len(matches) > 1:
        matches.sort(key=lambda m: m[0])
        # Clear winner check: if lowest distance is noticeably better than second-lowest
        if matches[0][0] < matches[1][0] - 0.05:
            return matches[0][1], None
        return None, 'ambiguous'
    return matches[0][1], None


def identify_user_from_iris(image_array, *, threshold=MATCH_THRESHOLD, staff_only=False):
    user, _reason = identify_user_from_iris_result(
        image_array,
        threshold=threshold,
        staff_only=staff_only,
    )
    return user
