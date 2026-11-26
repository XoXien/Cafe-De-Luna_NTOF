"""Set up the first local administrator without default accounts or demo data."""
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = 'Prompt for the first administrator if no active superuser exists. Existing accounts are left unchanged.'

    def add_arguments(self, parser):
        parser.add_argument('--noinput', '--no-input', dest='interactive', action='store_false', default=True,
                            help='Fail with instructions instead of asking for credentials when no administrator exists.')

    def handle(self, *args, **options):
        if get_user_model().objects.filter(is_superuser=True, is_active=True).exists():
            self.stdout.write('An active administrator already exists. Account details are unchanged.')
            return
        if not options['interactive']:
            raise CommandError('No active administrator exists. Run: python manage.py createsuperuser')
        self.stdout.write('Create your first Coffee de Luna administrator. Choose your own username and password.')
        call_command('createsuperuser', interactive=True, stdout=self.stdout, stderr=self.stderr)
