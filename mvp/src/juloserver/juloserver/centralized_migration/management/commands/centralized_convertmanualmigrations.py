from builtins import str
import os
import time
import re
from django.core.management.base import BaseCommand
from django.conf import settings


class Command(BaseCommand):

    help = "Convert manual migration to new format"
    MANUAL_SYNTAX = ('migrations.RunSQL', 'migrations.RunPython')
    AUTOMATED_SYNTAX = ('migrations.AddField', 'migrations.AlterField',
                        'migrations.RemoveField', 'migrations.RenameField',
                        'migrations.CreateModel', 'migrations.DeleteModel',
                        'migrations.RenameModel', 'migrations.AlterModelTable',
                        'migrations.AlterUniqueTogether', 'migrations.AlterIndexTogether',
                        'migrations.AlterOrderWithRespectTo', 'migrations.AlterModelOptions',
                        'migrations.AlterModelManagers'
                        )
    REGEX_PATTERN = re.compile(r"        (?:%s)\(\n[\S\s][\W\w]*?\n        \)\,\n" % '|'.join(AUTOMATED_SYNTAX))
    DEPENDENCY_PATTERN = re.compile(r"    dependencies = \[[\S\s][\W\w]*?\]")
    NON_DEPENDENCY = '    dependencies = [\n    ]'
    MANUAL_MAPPING_FOR_RENAMED_TABLE = {'vendor_data_history': 'comms_data_history'}
    DELETED_MODELS = [
        'loan_agent_assignment',
        'payment_autodialer_session',
        'MobilePaymentMethods']
    SKIPED_MIGRATIONS = ['ALTER TABLE privy_document_data RENAME application TO application_id']
    RELATIVE_PATH_IMPORT = 'from ..'
    PORTAL_PATH_IMPORT = 'from ...'
    GET_MODELS_PATTERN = re.compile(r"[a-zA-Z]+ = +apps.get_model+\([^\)]*\)?")
    FIRST_FUNC_DEF = re.compile(r"\n\s*?def")

    SKIPPED_FILES =['0285_load_guarantor_setting.py',
                    '0148_bri_integration.py',
                    '0078_auto_20170531_1511.py',
                    '0065_load_product_line.py',
                    '0286_reload_guarantor_settings.py',
                    '0543_create_new_status_lookups.py',
                    '0579_initial_token_cootek_auth.py',
                    '0005_add_payment_method_lookup_gopay.py']

    def handle(self, *args, **options):
        apps = settings.JULO_APPS

        for app in apps:
            self.stdout.write(self.style.MIGRATE_HEADING("scaning custom migration for '%s':\n" % app))
            migration_dir = app.replace('.', '/') + '/migrations'
            try:
                migrations_files = os.listdir(migration_dir)
            except OSError:
                continue
            else:
                migrations_files.sort()
                for file_name in migrations_files:
                    if file_name.startswith('__') or file_name.endswith('.pyc'):
                        continue
                    if file_name in self.SKIPPED_FILES:
                        continue
                    with open(migration_dir + '/' + file_name) as f:
                        migration_string = f.read()
                        if any(word in migration_string for word in self.MANUAL_SYNTAX):
                            migration_name = file_name.replace(re.search(r'\d+_',file_name).group(), '')
                            new_name = "%sM__%s__%s" % (
                                str('%.2f' % time.time()).replace('.', ''), app.split('.')[-1], migration_name)
                            time.sleep(0.01)

                            dir_path = settings.NEW_MIGRATIONS_PATH
                            file_path = dir_path + '/' + new_name
                            dest_folder = settings.NEW_MIGRATION_DIR_NAME
                            if self.MANUAL_SYNTAX[1] in migration_string:
                                dir_path = settings.RETROJOB_PATH
                                file_path = dir_path + '/' + new_name
                                dest_folder = settings.RETROJOB_DIR_NAME

                            self.stdout.write(
                                self.style.SUCCESS('   - %s\n    --> %s/%s' % (file_name, dest_folder, new_name)))
                            if any(word in migration_string for word in self.AUTOMATED_SYNTAX):
                                self.stdout.write(
                                    self.style.WARNING(
                                        "     contain automated migration (mixed) please re-check the converted result :\n"))
                                to_be_removed = self.REGEX_PATTERN.findall(migration_string)
                                for automated_syntax in to_be_removed:
                                    migration_string = migration_string.replace(automated_syntax, '')
                            else:
                                self.stdout.write('\n')

                            # remove dependencies
                            dependencies = self.DEPENDENCY_PATTERN.findall(migration_string)
                            for dependency in dependencies:
                                migration_string = migration_string.replace(dependency, self.NON_DEPENDENCY)

                            # check manual mapping if there's any for renamed table
                            if any(word in migration_string for word in list(self.MANUAL_MAPPING_FOR_RENAMED_TABLE.keys())):
                                for renamed_table in list(self.MANUAL_MAPPING_FOR_RENAMED_TABLE.keys()):
                                    migration_string = migration_string.replace(
                                        renamed_table, self.MANUAL_MAPPING_FOR_RENAMED_TABLE[renamed_table])

                            # check deleted model
                            if any(word in migration_string for word in self.DELETED_MODELS):
                                continue

                            # check for unnecessary custom migrations
                            if any(word in migration_string for word in self.SKIPED_MIGRATIONS):
                                continue

                            # check for portal relative import
                            if self.PORTAL_PATH_IMPORT in migration_string:
                                non_relative_path_portal_module = 'from juloserver.'
                                migration_string = migration_string.replace(
                                    self.PORTAL_PATH_IMPORT, non_relative_path_portal_module)

                            # check for relative import
                            if self.RELATIVE_PATH_IMPORT in migration_string:
                                non_relative_path_subapp_module = 'from %s.' % app
                                migration_string = migration_string.replace(
                                    self.RELATIVE_PATH_IMPORT, non_relative_path_subapp_module)

                            # check for apps.get_model
                            get_model_list = self.GET_MODELS_PATTERN.findall(migration_string)
                            if get_model_list:
                                first_func_def = self.FIRST_FUNC_DEF.findall(migration_string)[0]
                                indent = first_func_def.replace('def', '')
                                for get_model in get_model_list:
                                    subapp_name = re.findall(r"[\"\']([a-z_A-Z]+)[\"\']\,", get_model)[0]
                                    model_name = re.findall(r"[\"\']([a-zA-Z]+)[\"\']\)", get_model)[0]
                                    if subapp_name == 'auth':
                                        first_func_def = '%sfrom django.contrib.auth.models import %s\n' % \
                                                         (indent, model_name) + first_func_def
                                    elif subapp_name == 'authtoken':
                                        first_func_def = '%sfrom rest_framework.authtoken.models import %s\n' % \
                                                         (indent, model_name) + first_func_def
                                    else:
                                        first_func_def = '%sfrom juloserver.%s.models import %s\n' % \
                                                         (indent, subapp_name, model_name) + first_func_def
                                    migration_string = migration_string.replace(
                                        get_model, "")
                                migration_string = migration_string.replace(
                                    self.FIRST_FUNC_DEF.findall(migration_string)[0], first_func_def)

                            dest_folder_file_list = os.listdir(dir_path)
                            file_exist = False
                            for filename in dest_folder_file_list:
                                if filename.startswith('__') or filename.endswith('.pyc'):
                                    continue
                                if '%s__%s' % (app.split('.')[-1], migration_name) in filename:
                                    self.stdout.write(
                                        self.style.ERROR('%s has been converted (converted file exist)\n' % file_name))
                                    file_exist = True
                                    break
                            if file_exist:
                                continue
                            with open(file_path, "w") as migration_file:
                                migration_file.write(migration_string)
