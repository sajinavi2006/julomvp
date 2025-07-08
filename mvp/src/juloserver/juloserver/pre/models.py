from juloserver.julocore.data.models import JuloModelManager, GetInstanceMixin, TimeStampedModel
from juloserver.julocore.customized_psycopg2.models import BigAutoField
from django.db import models
from django.contrib.postgres.fields import JSONField


class DjangoShellLogManager(GetInstanceMixin, JuloModelManager):
    pass


class DjangoShellLog(TimeStampedModel):
    id = BigAutoField(primary_key=True, db_column='django_shell_log_id')
    description = models.TextField(blank=True, null=True)
    old_data = JSONField(blank=True, null=True)
    new_data = JSONField(blank=True, null=True)
    execute_by = models.BigIntegerField()

    objects = DjangoShellLogManager()

    class Meta(object):
        db_table = 'django_shell_log'
