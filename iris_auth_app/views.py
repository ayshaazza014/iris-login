import collections
import logging
import os
import struct
import threading
import time

import cv2
import numpy as np
from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from .models import IrisTemplate, IrisUser
from .services import (
    TEMPLATE_ENCODING_VERSION,
    ensure_iris_template_for_user,
    extract_template_from_image,
    identify_user_from_iris_result,
    verify_iris_for_user,
)


logger = logging.getLogger(__name__)

MAX_CAPTURE_BYTES = 5 * 1024 * 1024
MAX_CAPTURE_WIDTH = 2048
MAX_CAPTURE_HEIGHT = 2048
MAX_CAPTURE_PIXELS = 16 * 1024 * 1024

DEFAULT_RATE_LIMIT_ATTEMPTS = int(os.environ.get('IRIS_AUTH_RATE_LIMIT_ATTEMPTS', '30'))
DEFAULT_RATE_LIMIT_WINDOW = int(os.environ.get('IRIS_AUTH_RATE_LIMIT_WINDOW', '60'))


class InMemoryRateLimiter:
    """
    Sliding window in-memory rate limiter per IP / action
    to mitigate DoS / brute-force floods of CPU-intensive OpenCV calls.
    """

    def __init__(self, max_attempts=DEFAULT_RATE_LIMIT_ATTEMPTS, window_seconds=DEFAULT_RATE_LIMIT_WINDOW):
        self.max_attempts = max_attempts
        self.window_seconds = window_seconds
        self._records = collections.defaultdict(list)
        self._lock = threading.Lock()

    def is_limited(self, key, max_attempts=None, window_seconds=None):
        limit = max_attempts if max_attempts is not None else self.max_attempts
        window = window_seconds if window_seconds is not None else self.window_seconds
        now = time.time()
        cutoff = now - window
        with self._lock:
            timestamps = self._records[key]
            valid = [t for t in timestamps if t > cutoff]
            if len(valid) >= limit:
                self._records[key] = valid
                return True
            valid.append(now)
            self._records[key] = valid
            return False

    def clear(self):
        with self._lock:
            self._records.clear()


_rate_limiter = InMemoryRateLimiter()


def get_client_ip(request):
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        return x_forwarded_for.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR', '127.0.0.1')


def is_rate_limited(request, action='default', max_attempts=None, window_seconds=None):
    ip = get_client_ip(request)
    key = f"{ip}:{action}"
    return _rate_limiter.is_limited(key, max_attempts=max_attempts, window_seconds=window_seconds)


def _inspect_image_dimensions(data):
    """
    Safely inspect image binary headers to extract (width, height)
    without decompressing image pixel data in memory (DoS / Decompression Bomb protection).
    Supports PNG, JPEG, and WebP.
    """
    if not data or len(data) < 16:
        return None

    # PNG format
    if data.startswith(b'\x89PNG\r\n\x1a\n'):
        if len(data) >= 24:
            try:
                width, height = struct.unpack('>II', data[16:24])
                return width, height
            except struct.error:
                return None
        return None

    # JPEG format
    if data.startswith(b'\xff\xd8'):
        offset = 2
        data_len = len(data)
        while offset < data_len:
            if data[offset] != 0xff:
                return None
            while offset < data_len and data[offset] == 0xff:
                offset += 1
            if offset >= data_len:
                return None
            marker = data[offset]
            offset += 1
            if marker in (0xd8, 0xd9, 0x01) or (0xd0 <= marker <= 0xd7):
                continue
            if offset + 2 > data_len:
                return None
            try:
                seg_len = struct.unpack('>H', data[offset:offset + 2])[0]
            except struct.error:
                return None
            if seg_len < 2:
                return None
            if 0xc0 <= marker <= 0xcf and marker not in (0xc4, 0xc8, 0xcc):
                if offset + 7 > data_len:
                    return None
                try:
                    height, width = struct.unpack('>HH', data[offset + 3:offset + 7])
                    return width, height
                except struct.error:
                    return None
            offset += seg_len
        return None

    # WebP format
    if data.startswith(b'RIFF') and len(data) >= 30 and data[8:12] == b'WEBP':
        chunk = data[12:16]
        if chunk == b'VP8 ' and len(data) >= 30:
            width = (data[26] | (data[27] << 8)) & 0x3fff
            height = (data[28] | (data[29] << 8)) & 0x3fff
            return width, height
        elif chunk == b'VP8L' and len(data) >= 25:
            b0, b1, b2, b3 = data[21:25]
            width = 1 + (((b1 & 0x3f) << 8) | b0)
            height = 1 + (((b3 & 0x0f) << 10) | (b2 << 2) | ((b1 & 0xc0) >> 6))
            return width, height
        elif chunk == b'VP8X' and len(data) >= 30:
            width = 1 + (data[24] | (data[25] << 8) | (data[26] << 16))
            height = 1 + (data[27] | (data[28] << 8) | (data[29] << 16))
            return width, height

    return None


def _decode_capture(uploaded_file):
    if uploaded_file is None:
        raise ValidationError('Please upload an iris image or capture one with the camera before continuing.')
    if uploaded_file.size > MAX_CAPTURE_BYTES:
        raise ValidationError('The image is too large. Please capture an image under 5 MB.')

    image_bytes = uploaded_file.read(MAX_CAPTURE_BYTES + 1)
    if len(image_bytes) > MAX_CAPTURE_BYTES:
        raise ValidationError('The image is too large. Please capture an image under 5 MB.')

    # Inspect image dimensions from header before calling cv2.imdecode
    dims = _inspect_image_dimensions(image_bytes)
    if dims is None:
        raise ValidationError('The uploaded file is not a readable PNG or JPEG image. Please capture it again.')
    header_width, header_height = dims
    if (
        header_width <= 0
        or header_height <= 0
        or header_width > MAX_CAPTURE_WIDTH
        or header_height > MAX_CAPTURE_HEIGHT
        or (header_width * header_height) > MAX_CAPTURE_PIXELS
    ):
        raise ValidationError('The image dimensions are invalid or too large.')

    try:
        image = cv2.imdecode(np.frombuffer(image_bytes, dtype=np.uint8), cv2.IMREAD_COLOR)
    except cv2.error as exc:
        raise ValidationError('The uploaded image could not be decoded. Please capture a new PNG or JPEG image.') from exc
    if image is None:
        raise ValidationError('The uploaded file is not a readable PNG or JPEG image. Please capture it again.')
    height, width = image.shape[:2]
    if (
        width <= 0
        or height <= 0
        or width > MAX_CAPTURE_WIDTH
        or height > MAX_CAPTURE_HEIGHT
        or (width * height) > MAX_CAPTURE_PIXELS
    ):
        raise ValidationError('The image dimensions are invalid or too large.')
    return image


@require_http_methods(["GET"])
def home(request):
    return render(request, 'iris_auth_app/home.html')


@require_http_methods(["GET", "POST"])
def register_view(request):
    if request.method == 'POST':
        if is_rate_limited(request, action='register'):
            return HttpResponse('Too many attempts. Please try again later.', status=429)

        username = request.POST.get('username', '').strip()
        display_name = request.POST.get('display_name', '').strip()
        student_id = request.POST.get('student_id', '').strip()
        uploaded_file = request.FILES.get('capture')

        if not username or not display_name or not student_id:
            messages.error(request, 'Please complete all account fields.')
            return render(request, 'iris_auth_app/register.html')

        if IrisUser.objects.filter(username__iexact=username).exists():
            messages.error(
                request,
                'An account with this username already exists. Do not register it again; ask authorized staff to re-enroll its iris.',
            )
            return render(request, 'iris_auth_app/register.html')

        if IrisUser.objects.filter(student_id__iexact=student_id).exists():
            messages.error(
                request,
                'An account with this student ID already exists. Do not register it again; ask authorized staff to re-enroll its iris.',
            )
            return render(request, 'iris_auth_app/register.html')

        if uploaded_file is None:
            messages.error(request, 'Please upload an iris image or capture one with the camera before creating the account.')
            return render(request, 'iris_auth_app/register.html')

        try:
            image = _decode_capture(uploaded_file)
            code, mask = extract_template_from_image(image)
            with transaction.atomic():
                user = IrisUser.objects.create_user(
                    username=username,
                    display_name=display_name,
                    student_id=student_id,
                    password=None,
                )
                ensure_iris_template_for_user(user, code, mask)

            messages.success(request, f'Enrollment successful for {user.display_name}. You can now log in using your iris.')
            return redirect('login')

        except ValidationError as exc:
            messages.error(request, str(exc))
            return render(request, 'iris_auth_app/register.html')
        except IntegrityError:
            messages.error(request, 'That username or student ID was registered at the same time. Please check the values and try again.')
            return render(request, 'iris_auth_app/register.html')
        except (cv2.error, ImportError, OSError, TypeError, ValueError, AttributeError):
            logger.exception('Unexpected error while enrolling an iris account.')
            messages.error(request, 'Iris enrollment failed. Please capture a clearer eye image and try again.')
            return render(request, 'iris_auth_app/register.html')

    return render(request, 'iris_auth_app/register.html')


@require_http_methods(["GET", "POST"])
def staff_login_view(request):
    if request.method == 'POST':
        if is_rate_limited(request, action='staff_login'):
            return HttpResponse('Too many attempts. Please try again later.', status=429)

        identifier = request.POST.get('identifier', '').strip()
        try:
            image = _decode_capture(request.FILES.get('capture'))
            if identifier:
                user = verify_iris_for_user(identifier, image)
                if user is not None:
                    if not user.is_staff or not user.is_active:
                        logger.warning('Iris identification returned a non-staff user for staff login.')
                        messages.error(request, 'Iris not recognized or not authorized. Please try again.')
                        return render(request, 'iris_auth_app/staff_login.html')

                    login(request, user)
                    messages.success(request, f'Staff iris verification succeeded for {user.display_name or user.username}.')
                    return redirect('staff_dashboard')

                messages.error(request, _iris_login_failure_message('no_match', staff_only=True))
                return render(request, 'iris_auth_app/staff_login.html')

            user, failure_reason = identify_user_from_iris_result(image, staff_only=True)
            if user is None:
                messages.error(request, _iris_login_failure_message(failure_reason, staff_only=True))
                return render(request, 'iris_auth_app/staff_login.html')

            if not user.is_staff:
                logger.warning('Iris identification returned a non-staff user for staff login.')
                messages.error(request, 'Iris not recognized or not authorized. Please try again.')
                return render(request, 'iris_auth_app/staff_login.html')

            login(request, user)
            messages.success(request, f'Staff iris verification succeeded for {user.display_name or user.username}.')
            return redirect('staff_dashboard')
        except ValidationError as exc:
            messages.error(request, str(exc))
            return render(request, 'iris_auth_app/staff_login.html')
        except (cv2.error, ImportError, OSError, TypeError, ValueError, AttributeError):
            logger.exception('Unexpected error while processing a staff iris login.')
            messages.error(request, 'An unexpected error occurred while processing the iris image.')
            return render(request, 'iris_auth_app/staff_login.html')

    return render(request, 'iris_auth_app/staff_login.html')


@login_required(login_url='staff_login')
@require_http_methods(["GET", "POST"])
def staff_register_view(request):
    if not request.user.is_superuser:
        raise PermissionDenied

    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        display_name = request.POST.get('display_name', '').strip()
        email = request.POST.get('email', '').strip()
        uploaded_file = request.FILES.get('capture')

        if not username or not display_name:
            messages.error(request, 'Please enter the staff username and name.')
            return render(request, 'iris_auth_app/staff_register.html')

        if IrisUser.objects.filter(username__iexact=username).exists():
            messages.error(request, 'That username is already registered.')
            return render(request, 'iris_auth_app/staff_register.html')

        try:
            image = _decode_capture(uploaded_file)
            code, mask = extract_template_from_image(image)
        except ValidationError as exc:
            messages.error(request, str(exc))
            return render(request, 'iris_auth_app/staff_register.html')
        except (cv2.error, ImportError, OSError, TypeError, ValueError, AttributeError):
            logger.exception('Unexpected error while extracting a staff enrollment template.')
            messages.error(request, 'Staff enrollment failed. Please capture a clearer eye image and try again.')
            return render(request, 'iris_auth_app/staff_register.html')

        try:
            with transaction.atomic():
                staff_user = IrisUser.objects.create_user(
                    username=username,
                    display_name=display_name,
                    email=email,
                    password=None,
                    is_staff=True,
                    is_superuser=False,
                )
                ensure_iris_template_for_user(staff_user, code, mask)
        except ValidationError as exc:
            messages.error(request, str(exc))
            return render(request, 'iris_auth_app/staff_register.html')
        except IntegrityError:
            messages.error(request, 'That username was registered at the same time. Please choose another username.')
            return render(request, 'iris_auth_app/staff_register.html')
        except (cv2.error, ImportError, OSError, TypeError, ValueError, AttributeError):
            logger.exception('Unexpected error while creating a staff iris account.')
            messages.error(request, 'Staff enrollment failed. No staff account was created.')
            return render(request, 'iris_auth_app/staff_register.html')

        messages.success(request, f'Staff account {username} was created and enrolled.')
        return redirect('staff_login')

    return render(request, 'iris_auth_app/staff_register.html')


@login_required(login_url='staff_login')
@require_http_methods(["GET", "POST"])
def staff_reenroll_view(request):
    if not request.user.is_staff:
        raise PermissionDenied

    students = IrisUser.objects.filter(is_staff=False, is_superuser=False).order_by('username')

    if request.method == 'POST':
        user_id = request.POST.get('user_id', '').strip()
        student = students.filter(pk=user_id).first()
        if student is None:
            messages.error(request, 'Select a valid student account.')
            return render(request, 'iris_auth_app/staff_reenroll.html', {'students': students})

        try:
            image = _decode_capture(request.FILES.get('capture'))
            code, mask = extract_template_from_image(image)
            with transaction.atomic():
                student = IrisUser.objects.select_for_update().get(
                    pk=student.pk,
                    is_staff=False,
                    is_superuser=False,
                )
                ensure_iris_template_for_user(student, code, mask)

            logger.info(f"Staff '{request.user.username}' re-enrolled iris template for student '{student.username}' (id={student.pk}).")
            messages.success(request, f'Iris enrollment updated for {student.display_name or student.username}.')
            return redirect('staff_reenroll')
        except IrisUser.DoesNotExist:
            messages.error(request, 'That student account is no longer available.')
        except ValidationError as exc:
            messages.error(request, str(exc))
        except (cv2.error, ImportError, OSError, TypeError, ValueError, AttributeError):
            logger.exception('Unexpected error while staff re-enrolling an iris template.')
            messages.error(request, 'Re-enrollment failed. The previous template, if any, was not changed.')

    return render(request, 'iris_auth_app/staff_reenroll.html', {'students': students})


@require_http_methods(["GET", "POST"])
def login_view(request):
    if request.method == 'POST':
        if not getattr(request, '_rate_limited_checked', False):
            if is_rate_limited(request, action='login'):
                return HttpResponse('Too many attempts. Please try again later.', status=429)

        identifier = request.POST.get('identifier', '').strip()
        uploaded_file = request.FILES.get('capture')

        try:
            image = _decode_capture(uploaded_file)
            if identifier:
                user = verify_iris_for_user(identifier, image)
                if user is not None and not user.is_staff and not user.is_superuser and user.is_active:
                    login(request, user)
                    messages.success(request, f'Iris verification succeeded for {user.display_name or user.username}.')
                    return redirect('dashboard')

                messages.error(request, _iris_login_failure_message('no_match', staff_only=False))
                return render(request, 'iris_auth_app/login.html')

            user, failure_reason = identify_user_from_iris_result(image, staff_only=False)
            if user is not None:
                login(request, user)
                messages.success(request, f'Iris verification succeeded for {user.display_name or user.username}.')
                return redirect('dashboard')

            messages.error(request, _iris_login_failure_message(failure_reason, staff_only=False))
            return render(request, 'iris_auth_app/login.html')

        except ValidationError as exc:
            messages.error(request, str(exc))
            return render(request, 'iris_auth_app/login.html')
        except (cv2.error, ImportError, OSError, TypeError, ValueError, AttributeError):
            logger.exception('Unexpected error while processing an iris login.')
            messages.error(request, 'An unexpected error occurred while processing the iris image.')
            return render(request, 'iris_auth_app/login.html')

    return render(request, 'iris_auth_app/login.html')


@require_http_methods(["POST"])
def verify_iris(request):
    if is_rate_limited(request, action='verify_iris'):
        return HttpResponse('Too many attempts. Please try again later.', status=429)
    request._rate_limited_checked = True
    return login_view(request)


def _iris_login_failure_message(reason, *, staff_only):
    if reason == 'no_templates':
        if staff_only:
            return 'No compatible staff iris templates are enrolled. Contact an administrator to enroll staff.'
        return 'No compatible student iris templates are enrolled. Ask authorized staff to re-enroll your iris.'
    if reason == 'ambiguous':
        return 'More than one account matched this iris. Access was denied; contact an administrator.'
    if staff_only:
        return 'Iris not recognized or not authorized. Please try again.'
    return 'Iris not recognized. Please try again.'


@login_required(login_url='login')
def dashboard(request):
    if request.user.is_staff or request.user.is_superuser:
        raise PermissionDenied
    return render(request, 'iris_auth_app/dashboard.html', {'user': request.user})


@login_required(login_url='staff_login')
def staff_dashboard(request):
    if not request.user.is_staff:
        raise PermissionDenied
    return render(request, 'iris_auth_app/staff_dashboard.html', {'user': request.user})


@require_http_methods(["POST"])
def logout_view(request):
    logout(request)
    return redirect('home')
