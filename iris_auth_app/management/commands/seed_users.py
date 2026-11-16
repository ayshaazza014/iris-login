from pathlib import Path

import cv2
from django.conf import settings
from django.core.management.base import BaseCommand

from datetime import time

from iris_auth_app.models import AttendanceRecord, FeeRecord, IrisUser, TimetableEntry
from iris_auth_app.services import (
    ensure_iris_template_for_user,
    extract_face_embedding,
    extract_facial_features,
    extract_template_from_image,
)


class Command(BaseCommand):
    help = 'Create sample user accounts and enroll demo iris templates for development.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--demo',
            action='store_true',
            help='Enroll sample synthetic biometric templates for local testing/demo only.',
        )

    def handle(self, *args, **options):
        sample_users = [
            {'username': 'alice', 'display_name': 'Alice Demo', 'student_id': 'S-1001', 'is_staff': False},
            {'username': 'bob', 'display_name': 'Bob Demo', 'student_id': 'S-1002', 'is_staff': False},
            {'username': 'charlie', 'display_name': 'Charlie Demo', 'student_id': 'S-1003', 'is_staff': False},
            {'username': 'staff_alice', 'display_name': 'Staff Alice Demo', 'student_id': None, 'is_staff': True},
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
                # The portal is iris-only; demo accounts intentionally have no
                # usable password so they cannot be used for password login.
                user.set_unusable_password()
                user.save(update_fields=['password'])
                self.stdout.write(self.style.SUCCESS(f'Created {user.username}'))
            else:
                self.stdout.write(self.style.WARNING(f'Already exists: {user.username}'))

        # Demo portal data (attendance/fees) for all registered students
        students = IrisUser.objects.filter(is_staff=False, is_superuser=False)
        attendance_data = [
            ('AI', 12, 15),
            ('EVS', 14, 15),
            ('GT', 10, 15),
            ('CN', 13, 15),
            ('SC', 11, 15),
        ]
        for student in students:
            for subject, attended, total in attendance_data:
                AttendanceRecord.objects.update_or_create(
                    student=student,
                    subject=subject,
                    defaults={'attended_classes': attended, 'total_classes': total},
                )
            FeeRecord.objects.update_or_create(
                student=student,
                fee_type='Tuition Fee',
                defaults={
                    'amount_due': 50000,
                    'amount_paid': 150000,
                    'due_date': None,
                },
            )

            # Demo timetable (Mon-Fri, 9am-4pm, 1hr periods, lunch 1-2pm)
            TimetableEntry.objects.filter(student=student).delete()
            timetable = {
                'Mon': [('09:00','10:00','AI','R201',''), ('10:00','11:00','EVS','R201',''), ('11:00','12:00','GT','R202',''), ('12:00','13:00','CN','Lab 1',''), ('14:00','15:00','SC','R203',''), ('15:00','16:00','AI','R201','')],
                'Tue': [('09:00','10:00','CN','Lab 1',''), ('10:00','11:00','AI','R201',''), ('11:00','12:00','SC','R203',''), ('12:00','13:00','EVS','R201',''), ('14:00','15:00','GT','R202',''), ('15:00','16:00','CN','Lab 1','')],
                'Wed': [('09:00','10:00','GT','R202',''), ('10:00','11:00','SC','R203',''), ('11:00','12:00','AI','R201',''), ('12:00','13:00','GT','R202',''), ('14:00','15:00','EVS','R201',''), ('15:00','16:00','SC','R203','')],
                'Thu': [('09:00','10:00','EVS','R201',''), ('10:00','11:00','CN','Lab 1',''), ('11:00','12:00','EVS','R201',''), ('12:00','13:00','SC','R203',''), ('14:00','15:00','AI','R201',''), ('15:00','16:00','GT','R202','')],
                'Fri': [('09:00','10:00','SC','R203',''), ('10:00','11:00','GT','R202',''), ('11:00','12:00','CN','Lab 1',''), ('12:00','13:00','AI','R201',''), ('14:00','15:00','CN','Lab 1',''), ('15:00','16:00','EVS','R201','')],
            }
            for day, slots in timetable.items():
                for start, end, subject, room, faculty in slots:
                    sh, sm = map(int, start.split(':'))
                    eh, em = map(int, end.split(':'))
                    TimetableEntry.objects.create(
                        student=student, day=day,
                        start_time=time(sh, sm), end_time=time(eh, em),
                        subject=subject, room=room, faculty=faculty,
                    )

        subject_names = [s for s, _, _ in attendance_data]
        self.stdout.write(self.style.SUCCESS(f'Seeded demo attendance ({", ".join(subject_names)}) with varied values, fees, and timetable for {students.count()} registered student(s)'))

        # Gate synthetic enrollment behind settings.DEBUG or explicit --demo flag
        allow_demo_enrollment = getattr(settings, 'DEBUG', False) or options.get('demo')
        synthetic_path = Path(settings.BASE_DIR) / 'synthetic_eye.png'

        if not allow_demo_enrollment:
            self.stdout.write(
                self.style.WARNING(
                    'SECURITY NOTICE: Non-debug environment detected. Skipping synthetic biometric enrollment.\n'
                    'Pass --demo explicitly if setting up an isolated test/demo environment.'
                )
            )
            return

        if not synthetic_path.exists():
            self.stdout.write(
                self.style.WARNING(
                    'Demo iris image synthetic_eye.png is missing, so no demo templates were enrolled.\n'
                    'Register your own iris at /register/ before logging in.'
                )
            )
            return

        # Enroll both a student and a staff demo account. The login views filter
        # by role, so sharing the demo image does not make the 1:N search
        # ambiguous across the student and staff populations.
        demo_accounts = ('alice', 'staff_alice')
        enrolled = []
        try:
            img = cv2.imread(str(synthetic_path))
            if img is None:
                raise ValueError('synthetic_eye.png could not be read')
            code, mask = extract_template_from_image(img)
            facial_feat = extract_facial_features(img)
            face_embedding = extract_face_embedding(img)
        except Exception as exc:
            self.stdout.write(self.style.WARNING(f'Could not extract the demo iris template: {exc}'))
            return

        for username in demo_accounts:
            user = IrisUser.objects.filter(username=username).first()
            if user is None or getattr(user, 'iris_template', None):
                continue
            try:
                ensure_iris_template_for_user(
                    user,
                    code,
                    mask,
                    facial_features_array=facial_feat,
                    face_embedding_array=face_embedding,
                )
                enrolled.append(username)
            except Exception as exc:
                self.stdout.write(self.style.WARNING(f'Could not enroll {username}: {exc}'))

        if enrolled:
            self.stdout.write(
                self.style.WARNING(
                    'SECURITY WARNING: Enrolled the demo synthetic template for '
                    f'{", ".join(enrolled)}. Do not deploy with seeded accounts!'
                )
            )
            self.stdout.write(
                self.style.SUCCESS(
                    'Demo login: open /login/ (student) or /staff/login/ (staff) and upload '
                    'synthetic_eye.png from the project root. The camera will not match this image '
                    'unless it is shown to the camera.'
                )
            )
            self.stdout.write(
                self.style.SUCCESS(
                    'To use your own eye instead, create an account at /register/ (students) or '
                    'have an administrator create a staff account.'
                )
            )
