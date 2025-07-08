from __future__ import unicode_literals
from builtins import str
from builtins import object
import time
import re
import os
import sys
from importlib import import_module
from django import get_version
from django.db.migrations.writer import (MigrationWriter,
                                         OperationWriter)
from django.db.migrations.executor import MigrationExecutor
from django.db.migrations.autodetector import MigrationAutodetector
from django.db.migrations.loader import MigrationLoader
from django.db.migrations.recorder import MigrationRecorder
from django.conf import settings
from django.apps import apps
from django.utils import six
from django.db.migrations.exceptions import (BadMigrationError,
                                             InvalidMigrationPlan,
                                             NodeNotFoundError)

from django.apps.registry import Apps
from django.db import models
from django.db.utils import DatabaseError
from django.utils.encoding import python_2_unicode_compatible
from django.utils.timezone import now

from django.db.migrations.exceptions import MigrationSchemaMissing
from django.db.migrations.utils import COMPILED_REGEX_TYPE, RegexObject
from django.db.migrations.graph import MigrationGraph
from django.core.management.color import color_style


default_app_config = "juloserver.julo.apps.JuloConfig"
MIGRATIONS_MODULE_NAME = 'migrations'

STYLE = color_style()


class CustomMigrationRecorder(MigrationRecorder):
    """
    julo custom migration table
    """

    @python_2_unicode_compatible
    class JuloMigration(models.Model):
        app = models.CharField(max_length=255)
        name = models.CharField(max_length=255)
        applied = models.DateTimeField(default=now)

        class Meta(object):
            apps = Apps()
            app_label = "migrations"
            db_table = "julo_db_migrations"

        def __str__(self):
            return "Migration %s for %s" % (self.name, self.app)

    def __init__(self, connection):
        self.connection = connection

    @property
    def migration_qs(self):
        return self.JuloMigration.objects.using(self.connection.alias)

    def ensure_schema(self):
        """
        Ensures the table exists and has the correct schema.
        """
        # If the table's there, that's fine - we've never changed its schema
        # in the codebase.
        if self.JuloMigration._meta.db_table in self.connection.introspection.table_names(
                self.connection.cursor()):
            return
        # Make the table
        try:
            with self.connection.schema_editor() as editor:
                editor.create_model(self.JuloMigration)
        except DatabaseError as exc:
            raise MigrationSchemaMissing("Unable to create the julo_migrations table (%s)" % exc)

    def applied_migrations(self):
        """
        Returns a set of (app, name) of applied migrations.
        """

        self.ensure_schema()
        # resultset = super(CustomMigrationRecorder, self).applied_migrations()
        # resultset.union(set(tuple(x) for x in self.migration_qs.values_list("app", "name")))
        # return resultset
        return set(tuple(x) for x in self.migration_qs.values_list("app", "name"))

    def record_applied(self, app, name):
        """
        Records that a migration was applied.
        """
        self.ensure_schema()
        self.migration_qs.create(app=app, name=name)

    def record_unapplied(self, app, name):
        """
        Records that a migration was unapplied.
        """
        self.ensure_schema()
        self.migration_qs.filter(app=app, name=name).delete()

    def flush(self):
        """
        Deletes all migration records. Useful if you're testing migrations.
        """
        self.migration_qs.all().delete()


class CustomMigrationLoader(MigrationLoader):

    def load_disk(self):
        # super(CustomMigrationLoader, self).load_disk()

        self.disk_migrations = {}
        self.unmigrated_apps = set()
        self.migrated_apps = set()
        new_migration_directory = settings.NEW_MIGRATIONS_PATH
        new_migration_module = settings.NEW_MIGRATION_MODULE
        migration_names = set()
        for name in os.listdir(new_migration_directory):
            if name.endswith(".py"):
                import_name = name.rsplit(".", 1)[0]
                if import_name[0] not in "_.~":
                    migration_names.add(import_name)

        # Load them
        migrated_labels = []
        for migration_name in migration_names:
            migration_module = import_module("%s.%s" % (new_migration_module, migration_name))
            if not hasattr(migration_module, "Migration"):
                raise BadMigrationError(
                    "Migration %s  has no Migration class" % (migration_name)
                )
            app_label = migration_name.split('__')[1]
            migrated_labels.append(app_label)
            self.disk_migrations[app_label, migration_name] = migration_module.Migration(
                migration_name,
                app_label,
            )
        for app_config in apps.get_app_configs():
            if app_config.label in migrated_labels:
                self.migrated_apps.add(app_config.label)
            else:
                self.unmigrated_apps.add(app_config.label)

    def build_graph(self):
        """
        Builds a migration dependency graph using both the disk and database.
        You'll need to rebuild the graph if you apply migrations. This isn't
        usually a problem as generally migration stuff runs in a one-shot process.
        """
        # Load disk data
        self.load_disk()
        # Load database data
        if self.connection is None:
            self.applied_migrations = set()
        else:
            recorder = CustomMigrationRecorder(self.connection)
            self.applied_migrations = recorder.applied_migrations()
        # Do a first pass to separate out replacing and non-replacing migrations
        normal = {}
        replacing = {}
        for key, migration in list(self.disk_migrations.items()):
            if migration.replaces:
                replacing[key] = migration
            else:
                normal[key] = migration
        # Calculate reverse dependencies - i.e., for each migration, what depends on it?
        # This is just for dependency re-pointing when applying replacements,
        # so we ignore run_before here.
        reverse_dependencies = {}
        for key, migration in list(normal.items()):
            for parent in migration.dependencies:
                reverse_dependencies.setdefault(parent, set()).add(key)
        # Remember the possible replacements to generate more meaningful error
        # messages
        reverse_replacements = {}
        for key, migration in list(replacing.items()):
            for replaced in migration.replaces:
                reverse_replacements.setdefault(replaced, set()).add(key)
        # Carry out replacements if we can - that is, if all replaced migrations
        # are either unapplied or missing.
        for key, migration in list(replacing.items()):
            # Ensure this replacement migration is not in applied_migrations
            self.applied_migrations.discard(key)
            # Do the check. We can replace if all our replace targets are
            # applied, or if all of them are unapplied.
            applied_statuses = [
                (target in self.applied_migrations) for target in migration.replaces]
            can_replace = all(applied_statuses) or (not any(applied_statuses))
            if not can_replace:
                continue
            # Alright, time to replace. Step through the replaced migrations
            # and remove, repointing dependencies if needs be.
            for replaced in migration.replaces:
                if replaced in normal:
                    # We don't care if the replaced migration doesn't exist;
                    # the usage pattern here is to delete things after a while.
                    del normal[replaced]
                for child_key in reverse_dependencies.get(replaced, set()):
                    if child_key in migration.replaces:
                        continue
                    # List of migrations whose dependency on `replaced` needs
                    # to be updated to a dependency on `key`.
                    to_update = []
                    # Child key may itself be replaced, in which case it might
                    # not be in `normal` anymore (depending on whether we've
                    # processed its replacement yet). If it's present, we go
                    # ahead and update it; it may be deleted later on if it is
                    # replaced, but there's no harm in updating it regardless.
                    if child_key in normal:
                        to_update.append(normal[child_key])
                    # If the child key is replaced, we update its replacement's
                    # dependencies too, if necessary. (We don't know if this
                    # replacement will actually take effect or not, but either
                    # way it's OK to update the replacing migration).
                    if child_key in reverse_replacements:
                        for replaces_child_key in reverse_replacements[child_key]:
                            if replaced in replacing[replaces_child_key].dependencies:
                                to_update.append(replacing[replaces_child_key])
                    # Actually perform the dependency update on all migrations
                    # that require it.
                    for migration_needing_update in to_update:
                        migration_needing_update.dependencies.remove(replaced)
                        migration_needing_update.dependencies.append(key)
            normal[key] = migration
            # Mark the replacement as applied if all its replaced ones are
            if all(applied_statuses):
                self.applied_migrations.add(key)
        # Store the replacement migrations for later checks
        self.replacements = replacing
        # Finally, make a graph and load everything into it
        self.graph = MigrationGraph()
        for key, migration in list(normal.items()):
            self.graph.add_node(key, migration)

        def _reraise_missing_dependency(migration, missing, exc):
            """
            Checks if ``missing`` could have been replaced by any squash
            migration but wasn't because the the squash migration was partially
            applied before. In that case raise a more understandable exception.

            #23556
            """
            if missing in reverse_replacements:
                candidates = reverse_replacements.get(missing, set())
                is_replaced = any(candidate in self.graph.nodes for candidate in candidates)
                if not is_replaced:
                    tries = ', '.join('%s.%s' % c for c in candidates)
                    exc_value = NodeNotFoundError(
                        "Migration {0} depends on nonexistent node ('{1}', '{2}'). "
                        "Django tried to replace migration {1}.{2} with any of [{3}] "
                        "but wasn't able to because some of the replaced migrations "
                        "are already applied.".format(
                            migration, missing[0], missing[1], tries
                        ),
                        missing)
                    exc_value.__cause__ = exc
                    six.reraise(NodeNotFoundError, exc_value, sys.exc_info()[2])
            raise exc

        # Add all internal dependencies first to ensure __first__ dependencies
        # find the correct root node.
        for key, migration in list(normal.items()):
            for parent in migration.dependencies:
                if parent[0] != key[0] or parent[1] == '__first__':
                    # Ignore __first__ references to the same app (#22325)
                    continue
                try:
                    self.graph.add_dependency(migration, key, parent)
                except NodeNotFoundError as e:
                    # Since we added "key" to the nodes before this implies
                    # "parent" is not in there. To make the raised exception
                    # more understandable we check if parent could have been
                    # replaced but hasn't (eg partially applied squashed
                    # migration)
                    _reraise_missing_dependency(migration, parent, e)
        for key, migration in list(normal.items()):
            for parent in migration.dependencies:
                if parent[0] == key[0]:
                    # Internal dependencies already added.
                    continue
                parent = self.check_key(parent, key[0])
                if parent is not None:
                    try:
                        self.graph.add_dependency(migration, key, parent)
                    except NodeNotFoundError as e:
                        # Since we added "key" to the nodes before this implies
                        # "parent" is not in there.
                        _reraise_missing_dependency(migration, parent, e)
            for child in migration.run_before:
                child = self.check_key(child, key[0])
                if child is not None:
                    try:
                        self.graph.add_dependency(migration, child, key)
                    except NodeNotFoundError as e:
                        # Since we added "key" to the nodes before this implies
                        # "child" is not in there.
                        _reraise_missing_dependency(migration, child, e)

class CustomMigrationExecutor(MigrationExecutor):
    """
    End-to-end migration execution - loads migrations, and runs them
    up or down to a specified set of targets.
    """
    def __init__(self, connection, progress_callback=None):
        self.connection = connection
        self.loader = CustomMigrationLoader(self.connection)
        self.recorder = CustomMigrationRecorder(self.connection)
        self.progress_callback = progress_callback

    def migrate(self, targets, plan=None, fake=False, fake_initial=False):
        """
        Migrates the database up to the given targets.

        Django first needs to create all project states before a migration is
        (un)applied and in a second step run all the database operations.
        """
        if plan is None:
            plan = self.migration_plan(targets)
        # Create the forwards plan Django would follow on an empty database
        full_targets = self.loader.graph.leaf_nodes()
        full_targets.sort(key=lambda item: item[1])
        full_plan = self.migration_plan(full_targets, clean_start=True)
        all_forwards = all(not backwards for mig, backwards in plan)
        all_backwards = all(backwards for mig, backwards in plan)

        if not plan:
            pass  # Nothing to do for an empty plan
        elif all_forwards == all_backwards:
            # This should only happen if there's a mixed plan
            raise InvalidMigrationPlan(
                "Migration plans with both forwards and backwards migrations "
                "are not supported. Please split your migration process into "
                "separate plans of only forwards OR backwards migrations.",
                plan
            )
        elif all_forwards:
            self._migrate_all_forwards(plan, full_plan, fake=fake, fake_initial=fake_initial)
        else:
            # No need to check for `elif all_backwards` here, as that condition
            # would always evaluate to true.
            self._migrate_all_backwards(plan, full_plan, fake=fake)

        self.check_replacements()


class CustomMigrationWriter(MigrationWriter):
    """
    Takes a Migration instance and is able to produce the contents
    of the migration file from it.
    """

    def as_string(self):
        """
        Returns a string of the file contents.
        """
        items = {
            "replaces_str": "",
            "initial_str": "",
        }

        imports = set()

        # Deconstruct operations
        operations = []
        for operation in self.migration.operations:
            operation_string, operation_imports = OperationWriter(operation).serialize()
            imports.update(operation_imports)
            operations.append(operation_string)
        items["operations"] = "\n".join(operations) + "\n" if operations else ""

        # Format dependencies and write out swappable dependencies right
        dependencies = []
        for dependency in self.migration.dependencies:
            if dependency[0] == "__setting__":
                dependencies.append(
                    "        migrations.swappable_dependency(settings.%s)," % dependency[1])
                imports.add("from django.conf import settings")
        items["dependencies"] = "\n".join(dependencies) + "\n" if dependencies else ""

        # Format imports nicely, swapping imports of functions from migration files
        # for comments
        migration_imports = set()
        for line in list(imports):
            if re.match("^import (.*)\.\d+[^\s]*$", line):
                migration_imports.add(line.split("import")[1].strip())
                imports.remove(line)
                self.needs_manual_porting = True

        # django.db.migrations is always used, but models import may not be.
        # If models import exists, merge it with migrations import.
        if "from django.db import models" in imports:
            imports.discard("from django.db import models")
            imports.add("from django.db import migrations, models")
        else:
            imports.add("from django.db import migrations")

        # Sort imports by the package / module to be imported (the part after
        # "from" in "from ... import ..." or after "import" in "import ...").
        sorted_imports = sorted(imports, key=lambda i: i.split()[1])
        items["imports"] = "\n".join(sorted_imports) + "\n" if imports else ""
        if migration_imports:
            items["imports"] += (
                "\n\n# Functions from the following migrations need manual "
                "copying.\n# Move them and any dependencies into this file, "
                "then update the\n# RunPython operations to refer to the local "
                "versions:\n# %s"
            ) % "\n# ".join(sorted(migration_imports))
        # If there's a replaces, make a string for it
        if self.migration.replaces:
            items['replaces_str'] = "\n    replaces = %s\n" % self.serialize(
                self.migration.replaces)[0]
        # Hinting that goes into comment
        items.update(
            version=get_version(),
            timestamp=now().strftime("%Y-%m-%d %H:%M"),
        )

        if self.migration.initial:
            items['initial_str'] = "\n    initial = True\n"

        return (MIGRATION_TEMPLATE % items).encode("utf8")

    @property
    def path(self):
        basedir = settings.NEW_MIGRATIONS_PATH
        return os.path.join(basedir, self.filename)

    @property
    def retroload_path(self):
        basedir = settings.RETROJOB_PATH
        return os.path.join(basedir, self.filename)


class CustomMigrationAutodetector(MigrationAutodetector):
    def arrange_for_graph(self, changes, graph, migration_name=None):
        """
        custom migration filename using timestamp
        """
        name_map = {}
        for app_label, migrations in list(changes.items()):
            if not migrations:
                continue
            # Name each migration
            for i, migration in enumerate(migrations):
                suggested_name = migration_name or self.suggest_name(migration.operations)[:100]
                new_name = "%s__%s__%s" % (
                    str('%.2f' % time.time()).replace('.', ''), app_label, suggested_name)
                name_map[(app_label, migration.name)] = (app_label, new_name)
                migration.name = new_name
                time.sleep(0.01)

        return changes

    def deep_deconstruct(self, obj):
        """
        Recursive deconstruction for a field and its arguments.
        Used for full comparison for rename/alter; sometimes a single-level
        deconstruction will not compare correctly.
        """
        if isinstance(obj, list):
            return [self.deep_deconstruct(value) for value in obj]
        elif isinstance(obj, tuple):
            return tuple(self.deep_deconstruct(value) for value in obj)
        elif isinstance(obj, dict):
            return {
                key: self.deep_deconstruct(value)
                for key, value in list(obj.items())
            }
        elif isinstance(obj, COMPILED_REGEX_TYPE):
            return RegexObject(obj)
        elif isinstance(obj, type):
            # If this is a type that implements 'deconstruct' as an instance method,
            # avoid treating this as being deconstructible itself - see #22951
            return obj
        elif hasattr(obj, 'deconstruct'):
            deconstructed = obj.deconstruct()
            if isinstance(obj, models.Field):
                # we have a field which also returns a name
                deconstructed = deconstructed[1:]
            path, args, kwargs = deconstructed
            return (
                path,
                [self.deep_deconstruct(value) for value in args],
                {
                    key: self.deep_deconstruct(value)
                    for key, value in list(kwargs.items())
                },
            )
        else:
            if hasattr(obj, 'decode'):
                obj = obj.decode()
            return obj


MIGRATION_TEMPLATE = """\
# -*- coding: utf-8 -*-
# Generated by Django %(version)s on %(timestamp)s
from __future__ import unicode_literals

%(imports)s

class Migration(migrations.Migration):
%(replaces_str)s%(initial_str)s
    dependencies = [
%(dependencies)s\
    ]

    operations = [
%(operations)s\
    ]
"""


class CustomRetroloadExecutor(CustomMigrationExecutor):
    """
    End-to-end migration execution - loads migrations, and runs them
    up or down to a specified set of targets.
    """
    def __init__(self, connection, progress_callback=None):
        self.connection = connection
        self.loader = CustomRetroloadLoader(self.connection)
        self.recorder = CustomMigrationRecorder(self.connection)
        self.progress_callback = progress_callback


class CustomRetroloadLoader(CustomMigrationLoader):
    def load_disk(self):
        # super(CustomMigrationLoader, self).load_disk()

        self.disk_migrations = {}
        self.unmigrated_apps = set()
        self.migrated_apps = set()
        new_migration_directory = settings.RETROJOB_PATH
        new_migration_module = settings.RETROJOB_MODULE
        migration_names = set()
        for name in os.listdir(new_migration_directory):
            if name.endswith(".py"):
                import_name = name.rsplit(".", 1)[0]
                if import_name[0] not in "_.~":
                    migration_names.add(import_name)

        # Load them
        migrated_labels = []
        sys.stdout.write(
            STYLE.NOTICE('skipped retrojob file probably causing by the destination model is no '
                          'longer exist, please check if it necessary to fixed  \n'))
        for migration_name in migration_names:
            try:
                migration_module = import_module("%s.%s" % (new_migration_module, migration_name))
            except ImportError as error:
                sys.stdout.write(
                    STYLE.WARNING('%s.%s file skiped caused by this error: \n' % (
                        new_migration_module, migration_name)))
                sys.stdout.write(
                    STYLE.ERROR(' %s \n\n' % error))
            if not hasattr(migration_module, "Migration"):
                raise BadMigrationError(
                    "Migration %s  has no Migration class" % (migration_name)
                )
            app_label = migration_name.split('__')[1]
            migrated_labels.append(app_label)
            self.disk_migrations[app_label, migration_name] = migration_module.Migration(
                migration_name,
                app_label,
            )
        for app_config in apps.get_app_configs():
            self.unmigrated_apps.add(app_config.label)
