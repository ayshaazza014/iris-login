from pathlib import Path

import cv2
from django.conf import settings
from django.core.management.base import BaseCommand

from iris_auth_app.models import IrisUser
from iris_auth_app.services import ensure_iris_template_for_user, extract_template_from_image


class Command(BaseCommand):
    help = 'Create sample user accounts and enroll demo iris templates for development.'

    def handle(self, *args, **options):
        sample_users = [
            {'username': 'alice', 'display_name': 'Alice Demo', 'student_id': 'S-1001', 'password': 'DemoPass123!', 'is_staff': False},
            {'username': 'bob', 'display_name': 'Bob Demo', 'student_id': 'S-1002', 'password': 'DemoPass123!', 'is_staff': False},
            {'username': 'charlie', 'display_name': 'Charlie Demo', 'student_id': 'S-1003', 'password': 'DemoPass123!', 'is_staff': False},
            {'username': 'staff_alice', 'display_name': 'Staff Alice Demo', 'student_id': None, 'password': 'StaffPass123!', 'is_staff': True},
        ]

        for payload in sample_users:
            user, created = IrisUser.objects.get_or_create(
                username=payload['username'],
                defaults={
                    'display_name': payload['display_name'],
                    'student_id': payload['student_id'],
                    'is_staff': payload['is_staff'],
                },
            )
            if created:
                user.set_password(payload['password'])
                user.save()
                self.stdout.write(self.style.SUCCESS(f'Created {user.username}'))
            else:
                self.stdout.write(self.style.WARNING(f'Already exists: {user.username}'))

        # Enroll synthetic_eye.png for alice if not already enrolled
        synthetic_path = Path(settings.BASE_DIR) / 'synthetic_eye.png'
        if synthetic_path.exists():
            alice = IrisUser.objects.filter(username='alice').first()
            if alice and not getattr(alice, 'iris_template', None):
                try:
                    img = cv2.imread(str(synthetic_path))
                    if img is not None:
                        code, mask = extract_template_from_image(img)
                        ensure_iris_template_for_user(alice, code, mask)
                        self.stdout.write(self.style.SUCCESS('Enrolled synthetic_eye.png template for alice.'))
                except Exception as exc:
                    self.stdout.write(self.style.WARNING(f'Could not enroll synthetic template: {exc}'))
