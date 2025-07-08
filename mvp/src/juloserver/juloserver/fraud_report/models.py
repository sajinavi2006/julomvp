from django.db import models

from juloserver.julo.models import Application, PIIType
from juloserver.julocore.customized_psycopg2.models import BigForeignKey
from juloserver.pii_vault.models import PIIVaultModel, PIIVaultModelManager


class FraudReportManager(PIIVaultModelManager):
    pass


class FraudReport(PIIVaultModel):
    PII_FIELDS = ['nik', 'email', 'phone_number']
    PII_TYPE = PIIType.KV
    PII_ASYNC_QUEUE = 'antifraud_pii_vault'

    id = models.AutoField(db_column='fraud_report_id', primary_key=True)
    application = BigForeignKey(Application, models.DO_NOTHING, db_column="application_id")
    nik = models.TextField()
    email = models.TextField(null=True, blank=True)
    phone_number = models.TextField(null=True, blank=True)
    give_otp_or_pin = models.NullBooleanField()
    accident_date = models.DateField()
    monetary_loss = models.NullBooleanField()
    fraud_type = models.TextField()
    fraud_chronology = models.TextField()
    proof_remote_path = models.TextField()
    email_status = models.CharField(blank=True, null=True,
        max_length=20, choices=(('sent', 'Sent'), ('unsent', 'Unsent')))
    image_url = models.TextField(null=True, blank=True)
    nik_tokenized = models.TextField(blank=True, null=True)
    email_tokenized = models.TextField(blank=True, null=True)
    phone_number_tokenized = models.TextField(blank=True, null=True)

    objects = FraudReportManager()

    def __str__(self):
        return str(self.application_id)

    class Meta(object):
        db_table = 'fraud_report'
