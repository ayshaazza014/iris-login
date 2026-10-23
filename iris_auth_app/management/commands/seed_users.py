from django.core.management.base import BaseCommand

from iris_auth_app.models import IrisUser


class Command(BaseCommand):
    help = 'Create a few sample user accounts for the demo.'

    def handle(self, *args, **options):
        sample_users = [
            {'username': 'alice', 'display_name': 'Alice Demo', 'student_id': 'S-1001', 'password': 'DemoPass123!'},
            {'username': 'bob', 'display_name': 'Bob Demo', 'student_id': 'S-1002', 'password': 'DemoPass123!'},
            {'username': 'charlie', 'display_name': 'Charlie Demo', 'student_id': 'S-1003', 'password': 'DemoPass123!'},
        ]

        for payload in sample_users:
            user, created = IrisUser.objects.get_or_create(
                username=payload['username'],
                defaults={
                    'display_name': payload['display_name'],
                    'student_id': payload['student_id'],
                },
            )
            if created:
                user.set_password(payload['password'])
                user.save()
                self.stdout.write(self.style.SUCCESS(f'Created {user.username}'))
            else:
                self.stdout.write(self.style.WARNING(f'Already exists: {user.username}'))
