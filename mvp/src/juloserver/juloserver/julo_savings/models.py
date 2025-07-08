from django.db import models
from django.contrib.postgres.fields import JSONField
from ckeditor.fields import RichTextField

from juloserver.julocore.data.models import TimeStampedModel, JuloModelManager, GetInstanceMixin
from juloserver.julocore.customized_psycopg2.models import BigForeignKey
from juloserver.julo.models import Application


class JuloSavingsMobileContentSetting(TimeStampedModel):
    id = models.AutoField(db_column='julo_savings_mobile_content_setting_id', primary_key=True)

    content_name = models.CharField(max_length=100)
    description = models.CharField(max_length=200)
    content = RichTextField(blank=True, null=True)
    parameters = JSONField(blank=True, null=True)
    is_active = models.BooleanField(default=False)

    class Meta(object):
        db_table = 'julo_savings_mobile_content_setting'


class JuloSavingsWhitelistApplicationManager(GetInstanceMixin, JuloModelManager):
    pass


class JuloSavingsWhitelistApplication(TimeStampedModel):
    id = models.AutoField(db_column='julo_savings_whitelist_user_id', primary_key=True)
    application = BigForeignKey(
        Application,
        models.DO_NOTHING,
        db_column='application_id',
        db_index=True,
        unique=True,
        db_constraint=False,
    )

    objects = JuloSavingsWhitelistApplicationManager()

    class Meta(object):
        db_table = 'julo_savings_whitelist_user'
