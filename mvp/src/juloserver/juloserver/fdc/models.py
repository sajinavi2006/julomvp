from builtins import object

from django.db import models
from django.contrib.postgres.fields import JSONField

from juloserver.julo.models import Application, Customer, FDCInquiry
from juloserver.julocore.data.models import TimeStampedModel


class FDCDeliveryReport(TimeStampedModel):
    id = models.AutoField(db_column='fdc_delivery_report_id', primary_key=True)
    generated_at = models.DateTimeField(null=True, blank=True)
    last_reporting_loan = models.DateField(blank=True, null=True)
    last_uploaded_sik = models.DateTimeField(null=True, blank=True)
    last_uploaded_file_name = models.TextField(blank=True, null=True)
    total_outstanding = models.IntegerField(null=True, blank=True)
    total_paid_off = models.IntegerField(null=True, blank=True)
    total_written_off = models.IntegerField(null=True, blank=True)
    total_outstanding_outdated = models.IntegerField(null=True, blank=True)
    percentage_updated = models.FloatField(blank=True, null=True)
    threshold = models.FloatField(blank=True, null=True)
    access_status = models.TextField(blank=True, null=True)

    class Meta(object):
        db_table = 'fdc_delivery_report'


class FDCOutdatedLoan(TimeStampedModel):
    """
    We already moved this table to separate DB server instance. There is no longer foreign key for
    customer, application and loan.
    """

    id = models.AutoField(db_column='fdc_outdated_loan_id', primary_key=True)
    customer = models.ForeignKey(
        Customer, models.DO_NOTHING, db_column='customer_id', db_constraint=False
    )
    application = models.ForeignKey(
        Application,
        models.DO_NOTHING,
        db_column='application_id',
        blank=True,
        null=True,
        db_constraint=False,
    )
    report_date = models.DateField(null=True, blank=True)
    reported_status = models.TextField(blank=True, null=True)
    loan = models.BigIntegerField(null=True, blank=True)

    class Meta(object):
        db_table = 'fdc_outdated_loan'


class InitialFDCInquiryLoanData(TimeStampedModel):
    id = models.AutoField(db_column='initial_fdc_inquiry_loan_data_id', primary_key=True)
    fdc_inquiry = models.ForeignKey(FDCInquiry, models.DO_NOTHING, db_column='fdc_inquiry_id')
    initial_outstanding_loan_count_x100 = models.IntegerField(null=True, blank=True)
    initial_outstanding_loan_amount_x100 = models.BigIntegerField(null=True, blank=True)

    class Meta(object):
        db_table = 'initial_fdc_inquiry_loan_data'


class FDCDeliveryStatistic(TimeStampedModel):
    id = models.AutoField(db_column='fdc_delivery_statistic_id', primary_key=True)
    statistic_loan_generated_at = models.DateTimeField(null=True, blank=True)
    statistic_file_generated_at = models.DateTimeField(null=True, blank=True)
    status_file = JSONField(blank=True, null=True)
    status_loan = JSONField(blank=True, null=True)
    quality_loan = JSONField(blank=True, null=True)

    class Meta(object):
        db_table = 'fdc_delivery_statistic'
