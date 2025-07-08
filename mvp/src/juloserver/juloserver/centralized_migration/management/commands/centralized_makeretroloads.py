from builtins import str
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
        parser.add_argument('--empty', action='store_true', dest='empty', default=True,
            help="Create an empty migration.")
        parser.add_argument('--noinput', '--no-input',
            action='store_false', dest='interactive', default=True,
            help='Tells Django to NOT prompt the user for input of any kind.')
        parser.add_argument('-n', '--name', action='store', dest='name', default=None,
            help="Use this name for migration file(s).")
        parser.add_argument('-e', '--exit', action='store_true', dest='exit_code', default=False,
            help='Exit with error code 1 if no changes needing migrations are found.')

    def handle(self, *app_labels, **options):

        self.verbosity = options.get('verbosity')
        self.interactive = options.get('interactive')
        self.dry_run = options.get('dry_run', False)
        self.merge = options.get('merge', False)
        self.empty = options.get('empty', False)
        self.migration_name = options.get('name')
        self.exit_code = options.get('exit_code', False)

        # Make sure the app they asked for exists
        app_labels = set(app_labels)
        bad_app_labels = set()
        for app_label in app_labels:
            try:
                apps.get_app_config(app_label)
            except LookupError:
                bad_app_labels.add(app_label)
        if bad_app_labels:
            for app_label in bad_app_labels:
                self.stderr.write("App '%s' could not be found. Is it in INSTALLED_APPS?" % app_label)
            sys.exit(2)

        # Load the current graph state. Pass in None for the connection so
        # the loader doesn't try to resolve replaced migrations from DB.
        # loader = MigrationLoader(None, ignore_no_migrations=True)
        loader = CustomMigrationLoader(None, ignore_no_migrations=True)
        if self.interactive:
            questioner = InteractiveMigrationQuestioner(specified_apps=app_labels, dry_run=self.dry_run)
        else:
            questioner = NonInteractiveMigrationQuestioner(specified_apps=app_labels, dry_run=self.dry_run)
        # Set up autodetector
        autodetector = CustomMigrationAutodetector(
            loader.project_state(),
            ProjectState.from_apps(apps),
            questioner,
        )

        # If they want to make an empty migration, make one for each app
        if self.empty:
            if not app_labels:
                raise CommandError("You must supply at least one app label")
            # Make a fake changes() result we can pass to arrange_for_graph
            changes = {
                app: [Migration("custom", app)]
                for app in app_labels
            }


            changes = autodetector.arrange_for_graph(
                changes=changes,
                graph=loader.graph,
                migration_name=self.migration_name,
            )
            self.write_migration_files(changes)
            return

    def write_migration_files(self, changes):
        """
        Takes a changes dict and writes them out as migration files.
        """
        directory_created = {}
        writers = []
        for app_label, app_migrations in list(changes.items()):
            # if app_label not in [app_label.split('.')[-1] for app_label in settings.JULO_APPS]:
            #     continue
            for migration in app_migrations:
                # Describe the migration
                writer = CustomMigrationWriter(migration)
                writers.append(writer)

        writers.sort(key=lambda item: self.count_dependencies(item))
        for writer in writers:
            _, subapp_name, migration_name = writer.migration.name.split('__')
            new_name = "%s__%s__%s" % (str('%.2f' % time.time()).replace('.', ''), subapp_name, migration_name)
            writer.migration.name = new_name
            time.sleep(0.01)
            if self.verbosity >= 1:
                self.stdout.write(self.style.MIGRATE_HEADING("Migrations for '%s':" % subapp_name) + "\n")
            if self.verbosity >= 1:
                self.stdout.write("  %s:\n" % (self.style.MIGRATE_LABEL(writer.filename),))
                for operation in writer.migration.operations:
                    self.stdout.write("    - %s\n" % operation.describe())
            if not self.dry_run:
                # Write the migrations file to the disk.
                migration_string = writer.as_string()
                with open(writer.retroload_path, "wb") as fh:
                    fh.write(migration_string)
            elif self.verbosity == 3:
                # Alternatively, makemigrations --dry-run --verbosity 3
                # will output the migrations to stdout rather than saving
                # the file to the disk.
                self.stdout.write(self.style.MIGRATE_HEADING(
                    "Full migrations file '%s':" % writer.filename) + "\n"
                )
                self.stdout.write("%s\n" % writer.as_string())

    def count_dependencies(self, writer):
        return len(writer.migration.dependencies)
