# -*- coding: utf-8 -*-
from __future__ import unicode_literals

from builtins import filter
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
from django.db.migrations.autodetector import MigrationAutodetector
from django.db.migrations.executor import MigrationExecutor
from django.db.migrations.loader import AmbiguityError
from django.db.migrations.state import ProjectState
from django.utils.deprecation import RemovedInDjango110Warning
from django.utils.module_loading import module_has_submodule


class Command(BaseCommand):
    help = "Updates database schema. Manages both apps with migrations and those without."

    def add_arguments(self, parser):
        parser.add_argument('app_label', nargs='?',
            help='App label of an application to synchronize the state.')
        parser.add_argument('migration_name', nargs='?',
            help=(
                'Database state will be brought to the state after that '
                'migration. Use the name "zero" to unapply all migrations.'
            ),
        )
        parser.add_argument('--noinput', '--no-input',
            action='store_false', dest='interactive', default=False,
            help='Tells Django to NOT prompt the user for input of any kind.')
        parser.add_argument('--database', action='store', dest='database',
            default=DEFAULT_DB_ALIAS, help='Nominates a database to synchronize. '
                'Defaults to the "default" database.')
        parser.add_argument('--fake', action='store_true', dest='fake', default=False,
            help='Mark migrations as run without actually running them.')
        parser.add_argument('--fake-initial', action='store_true', dest='fake_initial', default=False,
            help='Detect if tables already exist and fake-apply initial migrations if so. Make sure '
                 'that the current database schema matches your initial migration before using this '
                 'flag. Django will only check for an existing table name.')
        parser.add_argument('--list', '-l', action='store_true', dest='list', default=False,
            help='Show a list of all known migrations and which are applied.')
        parser.add_argument('--run-syncdb', action='store_true', dest='run_syncdb',
            help='Creates tables for apps without migrations.')

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

        # Hook for backends needing any database preparation
        connection.prepare_database()
        # Work out which apps have migrations and which do not
        executor = MigrationExecutor(connection, self.migration_progress_callback)

        # If they supplied command line arguments, work out what they mean.
        target_app_labels_only = True
        targets = executor.loader.graph.leaf_nodes()

        plan = executor.migration_plan(targets)
        run_syncdb = options.get('run_syncdb') and executor.loader.unmigrated_apps

        # Print some useful info
        if self.verbosity >= 1:
            self.stdout.write(self.style.MIGRATE_HEADING("Operations to perform:"))
            if run_syncdb:
                self.stdout.write(
                    self.style.MIGRATE_LABEL("  Synchronize unmigrated apps: ") +
                    (", ".join(executor.loader.unmigrated_apps))
                )

        emit_pre_migrate_signal(self.verbosity, self.interactive, connection.alias)

        # Run the syncdb phase.
        if run_syncdb:
            if self.verbosity >= 1:
                self.stdout.write(self.style.MIGRATE_HEADING("Synchronizing apps without migrations:"))
            self.sync_apps(connection, executor.loader.unmigrated_apps)

            fake = options.get("fake")
            fake_initial = options.get("fake_initial")
            executor.migrate(targets, plan, fake=fake, fake_initial=fake_initial)
        else:
            self.stdout.write(
                self.style.WARNING(
                    "Sorry ") +
                self.style.ERROR(
                    "manage.py migrate") +
                self.style.WARNING(
                    " is deprecated, please use ") +
                self.style.SUCCESS(
                    "manage.py centralized_migrate\n")
            )

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

    def sync_apps(self, connection, app_labels):
        "Runs the old syncdb-style operation on a list of app_labels."
        cursor = connection.cursor()

        try:
            # Get a list of already installed *models* so that references work right.
            tables = connection.introspection.table_names(cursor)
            created_models = set()

            # Build the manifest of apps and models that are to be synchronized
            all_models = [
                (app_config.label,
                    router.get_migratable_models(app_config, connection.alias, include_auto_created=False))
                for app_config in apps.get_app_configs()
                if app_config.models_module is not None and app_config.label in app_labels
            ]

            def model_installed(model):
                opts = model._meta
                converter = connection.introspection.table_name_converter
                # Note that if a model is unmanaged we short-circuit and never try to install it
                return not ((converter(opts.db_table) in tables) or
                    (opts.auto_created and converter(opts.auto_created._meta.db_table) in tables))

            manifest = OrderedDict(
                (app_name, list(filter(model_installed, model_list)))
                for app_name, model_list in all_models
            )

            # Create the tables for each model
            if self.verbosity >= 1:
                self.stdout.write("  Creating tables...\n")
            with transaction.atomic(using=connection.alias, savepoint=connection.features.can_rollback_ddl):
                deferred_sql = []
                for app_name, model_list in list(manifest.items()):
                    for model in model_list:
                        if not model._meta.can_migrate(connection):
                            continue
                        if self.verbosity >= 3:
                            self.stdout.write(
                                "    Processing %s.%s model\n" % (app_name, model._meta.object_name)
                            )
                        with connection.schema_editor() as editor:
                            if self.verbosity >= 1:
                                self.stdout.write("    Creating table %s\n" % model._meta.db_table)
                            editor.create_model(model)
                            deferred_sql.extend(editor.deferred_sql)
                            editor.deferred_sql = []
                        created_models.add(model)

                if self.verbosity >= 1:
                    self.stdout.write("    Running deferred SQL...\n")
                for statement in deferred_sql:
                    cursor.execute(statement)
        finally:
            cursor.close()

        return created_models
