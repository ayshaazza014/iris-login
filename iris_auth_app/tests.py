from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np
from django.contrib import admin
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import Client, TestCase

from .models import IrisTemplate, IrisUser
from .services import (
    TEMPLATE_ENCODING_VERSION,
    ensure_iris_template_for_user,
    extract_template_from_image,
    identify_user_from_iris_result,
    load_iris_module,
    load_user_template,
    verify_iris_for_user,
)


def make_capture():
    success, encoded = cv2.imencode('.png', np.full((80, 80, 3), 180, dtype=np.uint8))
    if not success:
        raise AssertionError('Could not encode test capture.')
    return SimpleUploadedFile('capture.png', encoded.tobytes(), content_type='image/png')


def make_sample_eye_capture():
    sample_path = Path(__file__).resolve().parent.parent / 'synthetic_eye.png'
    return SimpleUploadedFile(
        sample_path.name,
        sample_path.read_bytes(),
        content_type='image/png',
    )


class IrisTemplateModelTests(TestCase):
    def test_image_without_a_detectable_eye_is_rejected(self):
        with self.assertRaisesMessage(ValidationError, 'No eye was detected'):
            extract_template_from_image(np.full((160, 160, 3), 180, dtype=np.uint8))

    def test_sample_image_extracts_current_template_shape(self):
        image = cv2.imread(str(Path(__file__).resolve().parent.parent / 'synthetic_eye.png'))

        code, mask = extract_template_from_image(image)

        self.assertEqual(code.shape, (256, 512))
        self.assertEqual(mask.shape, code.shape)
        self.assertEqual(code.dtype, np.uint8)
        self.assertTrue(mask.any())

    def test_template_round_trip_serialization(self):
        user = IrisUser.objects.create_user(username='demo', password='StrongPass123', display_name='Demo User')
        code = np.array([[0, 1], [1, 0]], dtype=np.uint8)
        mask = np.array([[1, 0], [1, 1]], dtype=np.uint8)

        template = IrisTemplate.create_for_user(user, code, mask)

        restored_code, restored_mask = template.validate_template()

        assert np.array_equal(restored_code, code)
        assert np.array_equal(restored_mask, mask)
        assert template.code_shape == '2,2'
        assert template.mask_shape == '2,2'
        assert template.code_dtype == 'uint8'
        assert template.mask_dtype == 'uint8'

    def test_template_reader_accepts_legacy_tuple_shape_metadata(self):
        user = IrisUser.objects.create_user(username='legacy-template', password='StrongPass123')
        template = IrisTemplate.objects.create(
            user=user,
            code=np.zeros((2, 3), dtype=np.uint8).tobytes(),
            mask=np.ones((2, 3), dtype=np.uint8).tobytes(),
            code_shape='(2, 3)',
            mask_shape='(2, 3)',
        )

        code, mask = template.validate_template()

        self.assertEqual(code.shape, (2, 3))
        self.assertEqual(mask.shape, (2, 3))

    def test_template_service_saves_parseable_shape_metadata(self):
        user = IrisUser.objects.create_user(username='shape-template', password='StrongPass123')
        code = np.zeros((2, 3), dtype=np.uint8)
        mask = np.ones((2, 3), dtype=np.uint8)

        template = ensure_iris_template_for_user(user, code, mask)

        self.assertEqual(template.code_shape, '2,3')
        self.assertEqual(template.mask_shape, '2,3')
        self.assertEqual(template.validate_template()[0].shape, (2, 3))

    def test_duplicate_student_id_is_rejected(self):
        IrisUser.objects.create_user(
            username='student1',
            password='StrongPass123',
            display_name='Student One',
            student_id='S-100',
        )

        with self.assertRaises(Exception):
            IrisUser.objects.create_user(
                username='student2',
                password='StrongPass123',
                display_name='Student Two',
                student_id='S-100',
            )

    def test_register_with_valid_iris_capture_creates_user_and_template(self):
        client = Client()
        code = np.array([[0, 1], [1, 0]], dtype=np.uint8)
        mask = np.ones((2, 2), dtype=np.uint8)
        with patch('iris_auth_app.views.extract_template_from_image', return_value=(code, mask)):
            response = client.post(
                '/register/',
                {
                    'username': 'new-iris-user',
                    'display_name': 'New Iris User',
                    'student_id': 'S-9999',
                    'capture': make_capture(),
                },
            )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, '/login/')
        user = IrisUser.objects.get(username='new-iris-user')
        self.assertTrue(hasattr(user, 'iris_template'))
        self.assertIsNotNone(user.iris_template)
        self.assertFalse(user.has_usable_password())

    def test_sample_eye_enrollment_then_scan_only_login(self):
        client = Client()
        response = client.post(
            '/register/',
            {
                'username': 'sample-eye-user',
                'display_name': 'Sample Eye User',
                'student_id': 'S-SAMPLE-EYE',
                'capture': make_sample_eye_capture(),
            },
        )

        self.assertEqual(response.status_code, 302)
        user = IrisUser.objects.get(username='sample-eye-user')
        stored_code, stored_mask = user.iris_template.validate_template()
        self.assertTrue(stored_code.size)
        self.assertTrue(stored_mask.any())

        response = client.post('/login/', {'capture': make_sample_eye_capture()})

        self.assertRedirects(response, '/dashboard/')
        self.assertEqual(int(client.session['_auth_user_id']), user.pk)

    def test_student_login_page_has_no_identity_fields(self):
        response = self.client.get('/login/')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Student Login')
        self.assertContains(response, '>Scan Iris<')
        self.assertContains(
            response,
            '<input id="capture" type="file" name="capture" accept="image/png,image/jpeg" required>',
        )
        self.assertContains(response, 'Choose an iris image below, or optionally use the camera.')
        self.assertContains(response, 'href="/register/"')
        self.assertContains(response, 'Register')
        self.assertNotContains(response, 'name="username"')
        self.assertNotContains(response, 'name="password"')
        self.assertNotContains(response, 'name="student_id"')
        self.assertNotContains(response, 'name="email"')

    def test_registration_page_allows_image_upload_without_camera(self):
        response = self.client.get('/register/')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'enroll your iris using an image upload or camera capture')
        self.assertContains(
            response,
            '<input id="capture" type="file" name="capture" accept="image/png,image/jpeg" required>',
        )

    def test_staff_login_page_allows_iris_image_upload(self):
        response = self.client.get('/staff/login/')

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            '<input id="capture" type="file" name="capture" accept="image/png,image/jpeg" required>',
        )
        self.assertContains(response, 'Choose an iris image below, or optionally use the camera.')

    def test_registration_failure_rolls_back_user_creation(self):
        code = np.array([[0, 1], [1, 0]], dtype=np.uint8)
        mask = np.ones((2, 2), dtype=np.uint8)
        with (
            patch('iris_auth_app.views.extract_template_from_image', return_value=(code, mask)),
            patch(
                'iris_auth_app.views.ensure_iris_template_for_user',
                side_effect=ValidationError('Template persistence failed.'),
            ),
        ):
            response = self.client.post(
                '/register/',
                {
                    'username': 'rolled-back-user',
                    'display_name': 'Rolled Back',
                    'student_id': 'S-ROLLBACK',
                    'capture': make_capture(),
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(IrisUser.objects.filter(username='rolled-back-user').exists())

    def test_registration_duplicate_username_has_clear_message(self):
        IrisUser.objects.create_user(username='duplicate-user', password=None, student_id='S-DUPLICATE')

        response = self.client.post(
            '/register/',
            {
                'username': 'duplicate-user',
                'display_name': 'Duplicate',
                'student_id': 'S-OTHER',
            },
        )

        self.assertContains(response, 'An account with this username already exists.')
        self.assertEqual(IrisUser.objects.filter(username='duplicate-user').count(), 1)

    def test_registration_duplicate_student_id_explains_reenrollment(self):
        IrisUser.objects.create_user(username='existing-student-id', student_id='S-EXISTING-ID')

        response = self.client.post(
            '/register/',
            {
                'username': 'new-account-same-id',
                'display_name': 'Existing Student ID',
                'student_id': 's-existing-id',
                'capture': make_capture(),
            },
        )

        self.assertContains(response, 'An account with this student ID already exists.')
        self.assertFalse(IrisUser.objects.filter(username='new-account-same-id').exists())

    def test_scan_only_login_authenticates_unique_template_match(self):
        user = IrisUser.objects.create_user(
            username='scan-user',
            password=None,
            student_id='S-SCAN',
        )
        code = np.zeros((8, 64), dtype=np.uint8)
        mask = np.ones((8, 64), dtype=np.uint8)
        IrisTemplate.create_for_user(
            user,
            code,
            mask,
            encoding_version=TEMPLATE_ENCODING_VERSION,
        )
        client = Client()

        with (
            patch('iris_auth_app.services.extract_template_from_image', return_value=(code, mask)),
            patch('iris_auth_app.services.compare_templates', return_value=0.0),
        ):
            response = client.post('/login/', {'capture': make_capture()})

        self.assertRedirects(response, '/dashboard/')
        self.assertEqual(int(client.session['_auth_user_id']), user.pk)

    def test_scan_only_login_rejects_no_match(self):
        user = IrisUser.objects.create_user(
            username='scan-no-match',
            password=None,
            student_id='S-NOMATCH',
        )
        code = np.zeros((8, 64), dtype=np.uint8)
        mask = np.ones((8, 64), dtype=np.uint8)
        IrisTemplate.create_for_user(
            user,
            code,
            mask,
            encoding_version=TEMPLATE_ENCODING_VERSION,
        )
        client = Client()

        with (
            patch('iris_auth_app.services.extract_template_from_image', return_value=(code, mask)),
            patch('iris_auth_app.services.compare_templates', return_value=1.0),
        ):
            response = client.post('/login/', {'capture': make_capture()})

        self.assertEqual(response.status_code, 200)
        self.assertNotIn('_auth_user_id', client.session)
        self.assertContains(response, 'Iris not recognized. Please try again.')

    def test_scan_only_login_rejects_ambiguous_match(self):
        code = np.zeros((8, 64), dtype=np.uint8)
        mask = np.ones((8, 64), dtype=np.uint8)
        for username in ('ambiguous-one', 'ambiguous-two'):
            user = IrisUser.objects.create_user(username=username, password=None)
            IrisTemplate.create_for_user(
                user,
                code,
                mask,
                encoding_version=TEMPLATE_ENCODING_VERSION,
            )
        client = Client()

        with (
            patch('iris_auth_app.services.extract_template_from_image', return_value=(code, mask)),
            patch('iris_auth_app.services.compare_templates', return_value=0.0),
        ):
            response = client.post('/login/', {'capture': make_capture()})

        self.assertEqual(response.status_code, 200)
        self.assertNotIn('_auth_user_id', client.session)
        self.assertContains(response, 'More than one account matched this iris.')

    def test_match_service_reports_ambiguous_result(self):
        code = np.zeros((8, 64), dtype=np.uint8)
        mask = np.ones((8, 64), dtype=np.uint8)
        for username in ('result-ambiguous-one', 'result-ambiguous-two'):
            user = IrisUser.objects.create_user(username=username)
            IrisTemplate.create_for_user(
                user,
                code,
                mask,
                encoding_version=TEMPLATE_ENCODING_VERSION,
            )

        with (
            patch('iris_auth_app.services.extract_template_from_image', return_value=(code, mask)),
            patch('iris_auth_app.services.compare_templates', return_value=0.0),
        ):
            user, reason = identify_user_from_iris_result(np.zeros((80, 80, 3), dtype=np.uint8))

        self.assertIsNone(user)
        self.assertEqual(reason, 'ambiguous')

    def test_match_service_reports_when_no_compatible_template_exists(self):
        with patch(
            'iris_auth_app.services.extract_template_from_image',
            return_value=(np.zeros((8, 64), dtype=np.uint8), np.ones((8, 64), dtype=np.uint8)),
        ):
            user, reason = identify_user_from_iris_result(np.zeros((80, 80, 3), dtype=np.uint8))

        self.assertIsNone(user)
        self.assertEqual(reason, 'no_templates')

    def test_student_login_does_not_authenticate_a_matching_staff_template(self):
        staff = IrisUser.objects.create_user(username='staff-only-match', is_staff=True)
        code = np.zeros((8, 64), dtype=np.uint8)
        mask = np.ones((8, 64), dtype=np.uint8)
        IrisTemplate.create_for_user(
            staff,
            code,
            mask,
            encoding_version=TEMPLATE_ENCODING_VERSION,
        )

        with (
            patch('iris_auth_app.services.extract_template_from_image', return_value=(code, mask)),
            patch('iris_auth_app.services.compare_templates', return_value=0.0),
        ):
            response = self.client.post('/login/', {'capture': make_capture()})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'No compatible student iris templates are enrolled.')
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_scan_only_login_ignores_previous_pipeline_templates(self):
        user = IrisUser.objects.create_user(username='old-pipeline-user', password=None)
        code = np.zeros((8, 64), dtype=np.uint8)
        mask = np.ones((8, 64), dtype=np.uint8)
        IrisTemplate.create_for_user(user, code, mask, encoding_version='gabor-v1')
        client = Client()

        with (
            patch('iris_auth_app.services.extract_template_from_image', return_value=(code, mask)),
            patch('iris_auth_app.services.compare_templates', return_value=0.0),
        ):
            response = client.post('/login/', {'capture': make_capture()})

        self.assertEqual(response.status_code, 200)
        self.assertNotIn('_auth_user_id', client.session)
        self.assertContains(response, 'No compatible student iris templates are enrolled.')

    def test_login_rejects_oversized_capture(self):
        response = self.client.post(
            '/login/',
            {'capture': SimpleUploadedFile('large.png', b'x' * (5 * 1024 * 1024 + 1), content_type='image/png')},
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_invalid_template_payload_raises_error(self):
        user = IrisUser.objects.create_user(username='demo2', password='StrongPass123', display_name='Demo Two')
        template = IrisTemplate(
            user=user,
            code=b'not-valid-bytes',
            mask=b'not-valid-bytes',
            code_shape='2,2',
            code_dtype='uint8',
            mask_shape='2,2',
            mask_dtype='uint8',
        )

        with self.assertRaises(ValidationError):
            template.validate_template()


class IrisVerificationTests(TestCase):
    def test_verify_iris_for_user_accepts_matching_template(self):
        user = IrisUser.objects.create_user(username='iris_user', password='StrongPass123', display_name='Iris User')
        eye = np.full((80, 80, 3), 180, dtype=np.uint8)
        code = np.zeros((8, 64), dtype=np.uint8)
        mask = np.ones((8, 64), dtype=np.uint8)
        IrisTemplate.create_for_user(
            user,
            code,
            mask,
            encoding_version=TEMPLATE_ENCODING_VERSION,
        )

        with (
            patch('iris_auth_app.services.extract_template_from_image', return_value=(code, mask)),
            patch('iris_auth_app.services.compare_templates', return_value=0.0),
        ):
            verified = verify_iris_for_user('iris_user', eye)

        self.assertIsNotNone(verified)

    def test_dashboard_requires_login(self):
        response = self.client.get('/dashboard/')
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.startswith('/login/'))

    def test_logged_in_user_can_access_dashboard(self):
        user = IrisUser.objects.create_user(username='logged_in', password='StrongPass123', display_name='Logged In User')
        self.client.force_login(user)
        response = self.client.get('/dashboard/')
        self.assertEqual(response.status_code, 200)

    def test_staff_cannot_access_student_dashboard(self):
        staff = IrisUser.objects.create_user(username='staff-on-student-dashboard', is_staff=True)
        self.client.force_login(staff)

        self.assertEqual(self.client.get('/dashboard/').status_code, 403)

    def test_staff_dashboard_requires_login(self):
        response = self.client.get('/staff/dashboard/')

        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.startswith('/staff/login/'))

    def test_student_cannot_access_staff_dashboard(self):
        student = IrisUser.objects.create_user(username='student-on-staff-dashboard')
        self.client.force_login(student)

        self.assertEqual(self.client.get('/staff/dashboard/').status_code, 403)

    def test_staff_can_access_staff_dashboard(self):
        staff = IrisUser.objects.create_user(username='authorized-dashboard-staff', is_staff=True)
        self.client.force_login(staff)

        response = self.client.get('/staff/dashboard/')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Staff Dashboard')

    def test_logout_invalidates_session(self):
        user = IrisUser.objects.create_user(username='logout_user', password='StrongPass123')
        self.client.force_login(user)

        response = self.client.post('/logout/')

        self.assertRedirects(response, '/')
        self.assertNotIn('_auth_user_id', self.client.session)
        self.assertEqual(self.client.get('/dashboard/').status_code, 302)

    def test_staff_can_open_reenrollment_page(self):
        staff = IrisUser.objects.create_user(
            username='staff-user',
            password='StrongPass123',
            is_staff=True,
        )
        self.client.force_login(staff)

        response = self.client.get('/staff/re-enroll/')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Iris Re-enrollment')

    def test_non_staff_cannot_open_reenrollment_page(self):
        student = IrisUser.objects.create_user(username='ordinary-student', password='StrongPass123')
        self.client.force_login(student)

        response = self.client.get('/staff/re-enroll/')

        self.assertEqual(response.status_code, 403)

    def test_staff_login_page_has_no_identity_fields(self):
        response = self.client.get('/staff/login/')

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Staff Login')
        self.assertContains(response, 'Scan Iris &amp; Login')
        self.assertNotContains(response, 'name="username"')
        self.assertNotContains(response, 'name="password"')
        self.assertNotContains(response, 'name="student_id"')

    def test_staff_login_authenticates_a_unique_staff_iris(self):
        staff = IrisUser.objects.create_user(username='staff-iris-user', is_staff=True)
        code = np.zeros((8, 64), dtype=np.uint8)
        mask = np.ones((8, 64), dtype=np.uint8)
        IrisTemplate.create_for_user(
            staff,
            code,
            mask,
            encoding_version=TEMPLATE_ENCODING_VERSION,
        )

        with (
            patch('iris_auth_app.services.extract_template_from_image', return_value=(code, mask)),
            patch('iris_auth_app.services.compare_templates', return_value=0.0),
        ):
            response = self.client.post('/staff/login/', {'capture': make_capture()})

        self.assertRedirects(response, '/staff/dashboard/')
        self.assertEqual(int(self.client.session['_auth_user_id']), staff.pk)

    def test_staff_sample_iris_authenticates_through_real_extraction_and_matching(self):
        sample_path = Path(__file__).resolve().parent.parent / 'synthetic_eye.png'
        image = cv2.imread(str(sample_path))
        code, mask = extract_template_from_image(image)
        staff = IrisUser.objects.create_user(username='sample-staff-iris', is_staff=True)
        IrisTemplate.create_for_user(
            staff,
            code,
            mask,
            encoding_version=TEMPLATE_ENCODING_VERSION,
        )

        response = self.client.post('/staff/login/', {'capture': make_sample_eye_capture()})

        self.assertRedirects(response, '/staff/dashboard/')
        self.assertEqual(int(self.client.session['_auth_user_id']), staff.pk)

    def test_staff_login_rejects_a_matching_student_iris(self):
        student = IrisUser.objects.create_user(username='student-on-staff-login')
        code = np.zeros((8, 64), dtype=np.uint8)
        mask = np.ones((8, 64), dtype=np.uint8)
        IrisTemplate.create_for_user(
            student,
            code,
            mask,
            encoding_version=TEMPLATE_ENCODING_VERSION,
        )

        with (
            patch('iris_auth_app.services.extract_template_from_image', return_value=(code, mask)),
            patch('iris_auth_app.services.compare_templates', return_value=0.0),
        ):
            response = self.client.post('/staff/login/', {'capture': make_capture()})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'No compatible staff iris templates are enrolled.')
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_staff_registration_is_forbidden_to_regular_staff(self):
        staff = IrisUser.objects.create_user(
            username='regular-staff',
            password='StrongPass123!',
            is_staff=True,
        )
        self.client.force_login(staff)

        response = self.client.get('/staff/register/')

        self.assertEqual(response.status_code, 403)

    def test_superuser_can_create_staff_account_without_superuser_privileges(self):
        superuser = IrisUser.objects.create_superuser(
            username='account-admin',
            email='admin@example.com',
            password='AdminStrongPass123!',
        )
        self.client.force_login(superuser)

        code = np.zeros((8, 64), dtype=np.uint8)
        mask = np.ones((8, 64), dtype=np.uint8)
        with patch('iris_auth_app.views.extract_template_from_image', return_value=(code, mask)):
            response = self.client.post(
                '/staff/register/',
                {
                    'username': 'created-staff',
                    'display_name': 'Created Staff',
                    'email': 'staff@example.com',
                    'capture': make_capture(),
                },
            )

        self.assertRedirects(response, '/staff/login/')
        created = IrisUser.objects.get(username='created-staff')
        self.assertTrue(created.is_staff)
        self.assertFalse(created.is_superuser)
        self.assertFalse(created.has_usable_password())
        self.assertEqual(created.iris_template.encoding_version, TEMPLATE_ENCODING_VERSION)

    def test_failed_staff_template_creation_rolls_back_staff_account(self):
        superuser = IrisUser.objects.create_superuser(
            username='template-admin',
            email='template-admin@example.com',
            password='AdminStrongPass123!',
        )
        self.client.force_login(superuser)

        with (
            patch('iris_auth_app.views.extract_template_from_image', return_value=(
                np.zeros((8, 64), dtype=np.uint8),
                np.ones((8, 64), dtype=np.uint8),
            )),
            patch(
                'iris_auth_app.views.ensure_iris_template_for_user',
                side_effect=ValidationError('Template persistence failed.'),
            ),
        ):
            response = self.client.post(
                '/staff/register/',
                {
                    'username': 'rolled-back-staff',
                    'display_name': 'Rolled Back Staff',
                    'capture': make_capture(),
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(IrisUser.objects.filter(username='rolled-back-staff').exists())

    def test_staff_reenrollment_creates_template_for_student_without_one(self):
        staff = IrisUser.objects.create_user(username='enrollment-staff', password='StrongPass123', is_staff=True)
        student = IrisUser.objects.create_user(username='unenrolled-student', password=None, student_id='S-NEW')
        code = np.zeros((8, 64), dtype=np.uint8)
        mask = np.ones((8, 64), dtype=np.uint8)
        self.client.force_login(staff)

        with patch('iris_auth_app.views.extract_template_from_image', return_value=(code, mask)):
            response = self.client.post(
                '/staff/re-enroll/',
                {'user_id': str(student.pk), 'capture': make_capture()},
            )

        self.assertRedirects(response, '/staff/re-enroll/')
        self.assertEqual(student.iris_template.encoding_version, TEMPLATE_ENCODING_VERSION)
        self.assertTrue(student.iris_template.validate_template()[1].any())

    def test_failed_staff_reenrollment_preserves_existing_template(self):
        staff = IrisUser.objects.create_user(username='failed-enrollment-staff', password='StrongPass123', is_staff=True)
        student = IrisUser.objects.create_user(username='existing-template-student', password=None)
        old_code = np.zeros((8, 64), dtype=np.uint8)
        old_mask = np.ones((8, 64), dtype=np.uint8)
        template = IrisTemplate.create_for_user(
            student,
            old_code,
            old_mask,
            encoding_version=TEMPLATE_ENCODING_VERSION,
        )
        original_bytes = bytes(template.code)
        self.client.force_login(staff)

        with patch(
            'iris_auth_app.views.extract_template_from_image',
            side_effect=ValidationError('No eye was detected.'),
        ):
            response = self.client.post(
                '/staff/re-enroll/',
                {'user_id': str(student.pk), 'capture': make_capture()},
            )

        self.assertEqual(response.status_code, 200)
        template.refresh_from_db()
        self.assertEqual(bytes(template.code), original_bytes)


class IrisServiceRefactorTests(TestCase):
    def test_load_iris_module_is_singleton(self):
        mod1 = load_iris_module()
        mod2 = load_iris_module()
        self.assertIs(mod1, mod2)

    def test_load_user_template_accepts_current_version(self):
        user = IrisUser.objects.create_user(username='current-user', password='StrongPass123')
        code = np.ones((256, 512), dtype=np.uint8)
        mask = np.ones((256, 512), dtype=np.uint8)
        IrisTemplate.create_for_user(user, code, mask, encoding_version=TEMPLATE_ENCODING_VERSION)

        loaded_code, loaded_mask = load_user_template(user)
        self.assertEqual(loaded_code.shape, (256, 512))
        self.assertEqual(loaded_mask.shape, (256, 512))

    def test_load_user_template_accepts_gabor_v1_if_shape_matches(self):
        user = IrisUser.objects.create_user(username='gabor-v1-user', password='StrongPass123')
        code = np.ones((256, 512), dtype=np.uint8)
        mask = np.ones((256, 512), dtype=np.uint8)
        IrisTemplate.create_for_user(user, code, mask, encoding_version='gabor-v1')

        loaded_code, loaded_mask = load_user_template(user)
        self.assertEqual(loaded_code.shape, (256, 512))
        self.assertEqual(loaded_mask.shape, (256, 512))

    def test_load_user_template_rejects_gabor_v1_with_invalid_shape(self):
        user = IrisUser.objects.create_user(username='gabor-v1-old-shape', password='StrongPass123')
        code = np.ones((8, 64), dtype=np.uint8)
        mask = np.ones((8, 64), dtype=np.uint8)
        IrisTemplate.create_for_user(user, code, mask, encoding_version='gabor-v1')

        with self.assertRaises(ValidationError):
            load_user_template(user)

    def test_load_user_template_rejects_unsupported_version(self):
        user = IrisUser.objects.create_user(username='unsupported-version-user', password='StrongPass123')
        code = np.ones((256, 512), dtype=np.uint8)
        mask = np.ones((256, 512), dtype=np.uint8)
        IrisTemplate.create_for_user(user, code, mask, encoding_version='legacy-v0')

        with self.assertRaises(ValidationError):
            load_user_template(user)

    def test_extract_template_calls_process_eye_with_no_out_dir(self):
        image = cv2.imread(str(Path(__file__).resolve().parent.parent / 'synthetic_eye.png'))
        with patch('iris_extract.process_eye', wraps=load_iris_module().process_eye) as mock_process:
            code, mask = extract_template_from_image(image)
            mock_process.assert_called_once()
            _, kwargs = mock_process.call_args
            self.assertIsNone(kwargs.get('out_dir'))



class SecurityAndAuthenticationHardeningTests(TestCase):
    def setUp(self):
        from iris_auth_app.views import _rate_limiter
        _rate_limiter.clear()

    def tearDown(self):
        from iris_auth_app.views import _rate_limiter
        _rate_limiter.clear()

    def test_security_settings(self):
        from django.conf import settings
        self.assertTrue(settings.SESSION_COOKIE_HTTPONLY)
        self.assertEqual(settings.SESSION_COOKIE_SAMESITE, 'Lax')
        self.assertFalse(settings.CSRF_COOKIE_HTTPONLY)
        self.assertEqual(settings.CSRF_COOKIE_SAMESITE, 'Lax')
        self.assertEqual(settings.X_FRAME_OPTIONS, 'DENY')

    def test_allowed_hosts_parsing(self):
        import importlib
        import os
        from iris_auth_project import settings as project_settings

        orig_env = os.environ.get('DJANGO_ALLOWED_HOSTS')
        try:
            os.environ['DJANGO_ALLOWED_HOSTS'] = 'custom.domain.com, api.internal '
            importlib.reload(project_settings)
            self.assertIn('custom.domain.com', project_settings.ALLOWED_HOSTS)
            self.assertIn('api.internal', project_settings.ALLOWED_HOSTS)

            os.environ.pop('DJANGO_ALLOWED_HOSTS', None)
            importlib.reload(project_settings)
            self.assertEqual(project_settings.ALLOWED_HOSTS, ['localhost', '127.0.0.1', '[::1]', 'testserver'])
        finally:
            if orig_env is not None:
                os.environ['DJANGO_ALLOWED_HOSTS'] = orig_env
            else:
                os.environ.pop('DJANGO_ALLOWED_HOSTS', None)
            importlib.reload(project_settings)

    def test_iris_template_deserialize_dtype_whitelist(self):
        payload = np.zeros((2, 2), dtype=np.uint8).tobytes()
        arr_uint8 = IrisTemplate.deserialize_array(payload, '2,2', 'uint8')
        self.assertEqual(arr_uint8.dtype, np.uint8)
        arr_int8 = IrisTemplate.deserialize_array(payload, '2,2', 'int8')
        self.assertEqual(arr_int8.dtype, np.int8)

        for bad_dtype in ['float32', 'float64', 'int32', 'int64', 'object']:
            with self.assertRaises(ValidationError) as ctx:
                IrisTemplate.deserialize_array(payload, '2,2', bad_dtype)
            self.assertIn('Unsupported array dtype', str(ctx.exception))

    def test_decode_capture_rejects_decompression_bomb(self):
        import struct
        from iris_auth_app.views import _decode_capture

        bomb_bytes = (
            b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR'
            + struct.pack('>II', 5000, 5000)
            + b'\x08\x02\x00\x00\x00'
            + b'\x00' * 20
        )
        file = SimpleUploadedFile('bomb.png', bomb_bytes, content_type='image/png')
        with self.assertRaises(ValidationError) as ctx:
            _decode_capture(file)
        self.assertIn('dimensions are invalid or too large', str(ctx.exception))

    def test_rate_limiter_throttles_excessive_attempts(self):
        from iris_auth_app.views import _rate_limiter
        _rate_limiter.clear()

        for _ in range(30):
            response = self.client.post('/login/', {'capture': make_capture()})
            self.assertIn(response.status_code, (200, 302))

        response = self.client.post('/login/', {'capture': make_capture()})
        self.assertEqual(response.status_code, 429)

        _rate_limiter.clear()
        for _ in range(30):
            response = self.client.post('/verify-iris/', {'capture': make_capture()})
            self.assertIn(response.status_code, (200, 302))
        response = self.client.post('/verify-iris/', {'capture': make_capture()})
        self.assertEqual(response.status_code, 429)

    def test_login_view_1_to_1_verification_success(self):
        student = IrisUser.objects.create_user(
            username='verified_student',
            student_id='STU-999',
            display_name='Verified Student',
        )
        code = np.zeros((8, 64), dtype=np.uint8)
        mask = np.ones((8, 64), dtype=np.uint8)
        IrisTemplate.create_for_user(student, code, mask, encoding_version=TEMPLATE_ENCODING_VERSION)

        with (
            patch('iris_auth_app.views.extract_template_from_image', return_value=(code, mask)),
            patch('iris_auth_app.services.extract_template_from_image', return_value=(code, mask)),
            patch('iris_auth_app.services.compare_templates', return_value=0.0),
        ):
            response = self.client.post('/login/', {
                'identifier': 'verified_student',
                'capture': make_capture(),
            })
            self.assertRedirects(response, '/dashboard/')
            self.assertEqual(int(self.client.session['_auth_user_id']), student.pk)

            self.client.logout()

            response = self.client.post('/login/', {
                'identifier': 'STU-999',
                'capture': make_capture(),
            })
            self.assertRedirects(response, '/dashboard/')
            self.assertEqual(int(self.client.session['_auth_user_id']), student.pk)

    def test_login_view_1_to_1_verification_mismatch(self):
        student = IrisUser.objects.create_user(
            username='mismatched_student',
            student_id='STU-888',
        )
        code = np.zeros((8, 64), dtype=np.uint8)
        mask = np.ones((8, 64), dtype=np.uint8)
        IrisTemplate.create_for_user(student, code, mask, encoding_version=TEMPLATE_ENCODING_VERSION)

        with (
            patch('iris_auth_app.views.extract_template_from_image', return_value=(code, mask)),
            patch('iris_auth_app.services.extract_template_from_image', return_value=(code, mask)),
            patch('iris_auth_app.services.compare_templates', return_value=0.8),
        ):
            response = self.client.post('/login/', {
                'identifier': 'mismatched_student',
                'capture': make_capture(),
            })
            self.assertEqual(response.status_code, 200)
            self.assertNotIn('_auth_user_id', self.client.session)

    def test_login_view_1_to_1_verification_rejects_staff_account(self):
        staff = IrisUser.objects.create_user(
            username='staff_as_student',
            is_staff=True,
        )
        code = np.zeros((8, 64), dtype=np.uint8)
        mask = np.ones((8, 64), dtype=np.uint8)
        IrisTemplate.create_for_user(staff, code, mask, encoding_version=TEMPLATE_ENCODING_VERSION)

        with (
            patch('iris_auth_app.views.extract_template_from_image', return_value=(code, mask)),
            patch('iris_auth_app.services.extract_template_from_image', return_value=(code, mask)),
            patch('iris_auth_app.services.compare_templates', return_value=0.0),
        ):
            response = self.client.post('/login/', {
                'identifier': 'staff_as_student',
                'capture': make_capture(),
            })
            self.assertEqual(response.status_code, 200)
            self.assertNotIn('_auth_user_id', self.client.session)

    def test_staff_login_view_1_to_1_verification_success(self):
        staff = IrisUser.objects.create_user(
            username='staff_auth_1to1',
            is_staff=True,
        )
        code = np.zeros((8, 64), dtype=np.uint8)
        mask = np.ones((8, 64), dtype=np.uint8)
        IrisTemplate.create_for_user(staff, code, mask, encoding_version=TEMPLATE_ENCODING_VERSION)

        with (
            patch('iris_auth_app.views.extract_template_from_image', return_value=(code, mask)),
            patch('iris_auth_app.services.extract_template_from_image', return_value=(code, mask)),
            patch('iris_auth_app.services.compare_templates', return_value=0.0),
        ):
            response = self.client.post('/staff/login/', {
                'identifier': 'staff_auth_1to1',
                'capture': make_capture(),
            })
            self.assertRedirects(response, '/staff/dashboard/')
            self.assertEqual(int(self.client.session['_auth_user_id']), staff.pk)

    def test_staff_login_view_1_to_1_verification_rejects_student(self):
        student = IrisUser.objects.create_user(
            username='student_for_staff_login',
            is_staff=False,
        )
        code = np.zeros((8, 64), dtype=np.uint8)
        mask = np.ones((8, 64), dtype=np.uint8)
        IrisTemplate.create_for_user(student, code, mask, encoding_version=TEMPLATE_ENCODING_VERSION)

        with (
            patch('iris_auth_app.views.extract_template_from_image', return_value=(code, mask)),
            patch('iris_auth_app.services.extract_template_from_image', return_value=(code, mask)),
            patch('iris_auth_app.services.compare_templates', return_value=0.0),
        ):
            response = self.client.post('/staff/login/', {
                'identifier': 'student_for_staff_login',
                'capture': make_capture(),
            })
            self.assertEqual(response.status_code, 200)
            self.assertNotIn('_auth_user_id', self.client.session)

    def test_staff_reenroll_logs_audit_info(self):
        staff = IrisUser.objects.create_user(username='audit_staff', is_staff=True)
        student = IrisUser.objects.create_user(username='audit_student')
        code = np.zeros((8, 64), dtype=np.uint8)
        mask = np.ones((8, 64), dtype=np.uint8)
        self.client.force_login(staff)

        with (
            patch('iris_auth_app.views.extract_template_from_image', return_value=(code, mask)),
            patch('iris_auth_app.views.logger.info') as mock_logger_info,
        ):
            response = self.client.post(
                '/staff/re-enroll/',
                {'user_id': str(student.pk), 'capture': make_capture()},
            )
            self.assertRedirects(response, '/staff/re-enroll/')
            mock_logger_info.assert_called_with(
                f"Staff '{staff.username}' re-enrolled iris template for student '{student.username}' (id={student.pk})."
            )

    def test_admin_models_registered(self):
        self.assertIn(IrisUser, admin.site._registry)
        self.assertIn(IrisTemplate, admin.site._registry)

    def test_seed_users_management_command(self):
        call_command('seed_users')
        self.assertTrue(IrisUser.objects.filter(username='alice').exists())
        self.assertTrue(IrisUser.objects.filter(username='bob').exists())
        self.assertTrue(IrisUser.objects.filter(username='staff_alice', is_staff=True).exists())
