from pathlib import Path

import cv2
from django.conf import settings
from django.core.management.base import BaseCommand

from datetime import time

from iris_auth_app.models import AttendanceRecord, FeeRecord, IrisUser, TimetableEntry
from iris_auth_app.services import (
    ensure_iris_template_for_user,
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
        alice = IrisUser.objects.filter(username='alice').first()

        if not allow_demo_enrollment:
            self.stdout.write(
                self.style.WARNING(
                    'SECURITY NOTICE: Non-debug environment detected. Skipping synthetic biometric enrollment.\n'
                    'Pass --demo explicitly if setting up an isolated test/demo environment.'
                )
            )
            return

        if synthetic_path.exists():
            if alice and not getattr(alice, 'iris_template', None):
                try:
                    img = cv2.imread(str(synthetic_path))
                    if img is not None:
                        code, mask = extract_template_from_image(img)
                        facial_feat = extract_facial_features(img)
                        ensure_iris_template_for_user(alice, code, mask, facial_features_array=facial_feat)
                        self.stdout.write(
                            self.style.WARNING(
                                'SECURITY WARNING: Enrolled demo synthetic template for alice. '
                                'Do not deploy with seeded accounts or demo credentials!'
                            )
                        )
                except Exception as exc:
                    self.stdout.write(self.style.WARNING(f'Could not enroll synthetic template: {exc}'))
