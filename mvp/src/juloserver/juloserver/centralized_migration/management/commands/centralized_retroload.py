# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import time
import warnings
from collections import OrderedDict
from importlib import import_module

from django.apps import apps
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.core.management.sql import (
    emit_post_migrate_signal, emit_pre_migrate_signal,
)
from django.db import DEFAULT_DB_ALIAS, connections, router, transaction

from django.db.migrations.loader import AmbiguityError
from django.db.migrations.state import ProjectState
from django.utils.deprecation import RemovedInDjango110Warning
from django.utils.module_loading import module_has_submodule
from ..commands import CustomRetroloadExecutor, CustomMigrationAutodetector


class Command(BaseCommand):
    help = "Updates database schema. Manages both apps with migrations and those without."

    def add_arguments(self, parser):
        parser.add_argument('app_label', nargs='?',
            help='App label of an application to synchronize the state.')
        parser.add_argument('--noinput', '--no-input',
            action='store_false', dest='interactive', default=True,
            help='Tells Django to NOT prompt the user for input of any kind.')
        parser.add_argument('--database', action='store', dest='database',
            default=DEFAULT_DB_ALIAS, help='Nominates a database to synchronize. '
                'Defaults to the "default" database.')
        parser.add_argument('--list', '-l', action='store_true', dest='list', default=False,
            help='Show a list of all known retroloads and which are applied.')
        parser.add_argument('--fake', action='store_true', dest='fake', default=False,
                            help='Mark migrations as run without actually running them.')

    def handle(self, *args, **options):

        self.verbosity = options.get('verbosity')
        self.interactive = options.get('interactive')

        # Import the 'management' module within each installed app, to register
        # dispatcher events.
        for app_config in apps.get_app_configs():
            if module_has_submodule(app_config.module, "management"):
                import_module('.management', app_config.name)

        # Get the database we're operating from
        db = options.get('database')
        connection = connections[db]

        # If they asked for a migration listing, quit main execution flow and show it
        if options.get("list", False):
            warnings.warn(
                "The 'migrate --list' command is deprecated. Use 'showmigrations' instead.",
                RemovedInDjango110Warning, stacklevel=2)
            self.stdout.ending = None  # Remove when #21429 is fixed
            return call_command(
                'showmigrations',
                '--list',
                app_labels=[options['app_label']] if options['app_label'] else None,
                database=db,
                no_color=options.get('no_color'),
                settings=options.get('settings'),
                stdout=self.stdout,
                traceback=options.get('traceback'),
                verbosity=self.verbosity,
            )

        # Hook for backends needing any database preparation
        connection.prepare_database()
        # Work out which apps have retroloads and which do not
        executor = CustomRetroloadExecutor(connection, self.migration_progress_callback)

        # If they supplied command line arguments, work out what they mean.
        target_app_labels_only = True
        targets = executor.loader.graph.leaf_nodes()
        targets.sort(key=lambda item: item[1])
        plan = executor.migration_plan(targets)

        # Print some useful info
        if self.verbosity >= 1:
            self.stdout.write(self.style.MIGRATE_HEADING("Operations to perform:"))
            if target_app_labels_only:
                self.stdout.write(
                    self.style.MIGRATE_LABEL("  Apply all retroloads: ") +
                    (", ".join(set(a for a, n in targets)) or "(none)")
                )
            else:
                if targets[0][1] is None:
                    self.stdout.write(self.style.MIGRATE_LABEL(
                        "  Unapply all retroloads: ") + "%s" % (targets[0][0], )
                    )
                else:
                    self.stdout.write(self.style.MIGRATE_LABEL(
                        "  Target specific migration: ") + "%s, from %s"
                        % (targets[0][1], targets[0][0])
                    )

        emit_pre_migrate_signal(self.verbosity, self.interactive, connection.alias)

        # Migrate!
        if self.verbosity >= 1:
            self.stdout.write(self.style.MIGRATE_HEADING("Running retroloads:"))
        if not plan:
            executor.loader.unmigrated_apps = []
            executor.check_replacements()
            if self.verbosity >= 1:
                self.stdout.write("  No retroloads to apply.")
                # If there's changes that aren't in retroloads yet, tell them how to fix it.
                autodetector = CustomMigrationAutodetector(
                    executor.loader.project_state(),
                    ProjectState.from_apps(apps),
                )
        else:
            fake = options.get("fake")
            fake_initial = options.get("fake_initial")
            executor.migrate(targets, plan, fake=fake, fake_initial=fake_initial)

        # Send the post_migrate signal, so individual apps can do whatever they need
        # to do at this point.
        emit_post_migrate_signal(self.verbosity, self.interactive, connection.alias)

    def migration_progress_callback(self, action, migration=None, fake=False):
        if self.verbosity >= 1:
            compute_time = self.verbosity > 1
            if action == "apply_start":
                if compute_time:
                    self.start = time.time()
                self.stdout.write("  Applying %s..." % migration, ending="")
                self.stdout.flush()
            elif action == "apply_success":
                elapsed = " (%.3fs)" % (time.time() - self.start) if compute_time else ""
                if fake:
                    self.stdout.write(self.style.MIGRATE_SUCCESS(" FAKED" + elapsed))
                else:
                    self.stdout.write(self.style.MIGRATE_SUCCESS(" OK" + elapsed))
            elif action == "unapply_start":
                if compute_time:
                    self.start = time.time()
                self.stdout.write("  Unapplying %s..." % migration, ending="")
                self.stdout.flush()
            elif action == "unapply_success":
                elapsed = " (%.3fs)" % (time.time() - self.start) if compute_time else ""
                if fake:
                    self.stdout.write(self.style.MIGRATE_SUCCESS(" FAKED" + elapsed))
                else:
                    self.stdout.write(self.style.MIGRATE_SUCCESS(" OK" + elapsed))
            elif action == "render_start":
                if compute_time:
                    self.start = time.time()
                self.stdout.write("  Rendering model states...", ending="")
                self.stdout.flush()
            elif action == "render_success":
                elapsed = " (%.3fs)" % (time.time() - self.start) if compute_time else ""
                self.stdout.write(self.style.MIGRATE_SUCCESS(" DONE" + elapsed))
