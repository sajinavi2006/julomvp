import sys
import time

from django.apps import apps
from django.core.management.base import BaseCommand, CommandError
from django.db.migrations import Migration
from django.db.migrations.questioner import (
    InteractiveMigrationQuestioner,
    NonInteractiveMigrationQuestioner,
)
from django.db.migrations.state import ProjectState
from ..commands import (CustomMigrationWriter,
                        CustomMigrationAutodetector,
                        CustomMigrationLoader)


class Command(BaseCommand):
    help = "Creates new migration(s) for apps."

    def add_arguments(self, parser):
        parser.add_argument('args', metavar='app_label', nargs='*',
            help='Specify the app label(s) to create migrations for.')
        parser.add_argument('--dry-run', action='store_true', dest='dry_run', default=False,
            help="Just show what migrations would be made; don't actually write them.")
        parser.add_argument('--merge', action='store_true', dest='merge', default=False,
            help="Enable fixing of migration conflicts.")
        parser.add_argument('--empty', action='store_true', dest='empty', default=False,
            help="Create an empty migration.")
        parser.add_argument('--noinput', '--no-input',
            action='store_false', dest='interactive', default=True,
            help='Tells Django to NOT prompt the user for input of any kind.')
        parser.add_argument('-n', '--name', action='store', dest='name', default=None,
            help="Use this name for migration file(s).")
        parser.add_argument('-e', '--exit', action='store_true', dest='exit_code', default=False,
            help='Exit with error code 1 if no changes needing migrations are found.')

    def handle(self, *app_labels, **options):
        self.stdout.write(
            self.style.WARNING(
                "Sorry ") +
            self.style.ERROR(
                "manage.py makemigrations") +
            self.style.WARNING(
                " is deprecated, please use ") +
            self.style.SUCCESS(
                "manage.py centralized_makemigrations\n")
        )
