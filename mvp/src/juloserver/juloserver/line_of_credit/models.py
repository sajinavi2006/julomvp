from __future__ import unicode_literals
from builtins import object
import logging

from datetime import timedelta

from cuser.fields import CurrentUserField
from django.db import connection
from django.db import models
from django.utils import timezone

from juloserver.julocore.data.models import (
    JuloModelManager, GetInstanceMixin, TimeStampedModel, CustomQuerySet
)
from juloserver.line_of_credit.constants import LocConst
from juloserver.line_of_credit.utils import create_collection


logger = logging.getLogger(__name__)


class LineOfCreditManager(GetInstanceMixin, JuloModelManager):
    pass


class LineOfCredit(TimeStampedModel):
    id = models.AutoField(db_column='line_of_credit_id', primary_key=True)

    customer = models.OneToOneField('julo.Customer',
                                    on_delete=models.CASCADE,
                                    db_column='customer_id')
    limit = models.BigIntegerField()
    available = models.BigIntegerField()
    service_fee_rate = models.FloatField()
    late_fee_rate = models.FloatField()
    interest_rate = models.FloatField()
    status = models.CharField(max_length=100, default=LocConst.STATUS_INACTIVE)
    active_date = models.DateTimeField(null=True, blank=True)
    statement_day = models.IntegerField(null=True, blank=True)
    freeze_date = models.DateTimeField(null=True, blank=True)
    freeze_reason = models.TextField(default='')
    next_statement_date = models.DateTimeField(null=True, blank=True)
    pin = models.CharField(max_length=128, default='0')
    reset_pin_key = models.CharField(max_length=50, blank=True, null=True)
    reset_pin_exp_date = models.DateTimeField(blank=True, null=True)

    objects = LineOfCreditManager()
    class Meta(object):
        db_table = 'line_of_credit'

    def has_resetpin_expired(self):
        return self.reset_pin_exp_date < timezone.now()


class LineOfCreditTransaction(TimeStampedModel):
    id = models.AutoField(db_column='line_of_credit_transaction_id', primary_key=True)

    line_of_credit = models.ForeignKey('LineOfCredit',
                                       models.DO_NOTHING,
                                       db_column='line_of_credit_id')

    type = models.CharField(max_length=100)
    amount = models.FloatField()
    description = models.TextField(null=True, blank=True)
    transaction_date = models.DateTimeField(default=timezone.now)
    status = models.CharField(max_length=100)
    channel = models.CharField(max_length=100)
    loc_statement = models.ForeignKey(
        'LineOfCreditStatement', models.DO_NOTHING, db_column='loc_statement_id',
        null=True, blank=True)

    class Meta(object):
        db_table = 'loc_transaction'


class LineOfCreditStatementQuerySet(CustomQuerySet):

    def run_query(self, query):
        with connection.cursor() as cursor:
            cursor.execute(query)
            row = cursor.fetchall()
        return row

    def not_min_paid(self):
        return self.filter(is_min_paid=False)

    def due_soon(self, due_in_days=1):
        today = timezone.now().date()
        day_delta = timedelta(days=due_in_days)
        days_from_now = today + day_delta
        query = "select app.application_id, app.line_of_credit_id, los.oldest_date, \
             los.oldest_id from application app inner join \
             (select min(payment_due_date) oldest_date, \
             min(loc_statement_id) oldest_id, \
             line_of_credit_id from loc_statement WHERE \
             is_min_paid=False group by line_of_credit_id) los \
             on app.line_of_credit_id = los.line_of_credit_id \
             and cast(los.oldest_date as date) = '%s'" % (days_from_now)
        rows = self.run_query(query)
        fields = ['application_id', 'line_of_credit_id',
                  'payment_due_date', 'loc_statement_id']
        collection = create_collection(fields, rows)
        return collection

    def dpd_group_range(self, range1, range2):
        today = timezone.now().date()
        range1_ago = today - timedelta(days=range1)
        range2_ago = today - timedelta(days=range2)
        query = "select app.application_id, app.line_of_credit_id, los.oldest_date, \
                 los.oldest_id from application app inner join \
                 (select min(payment_due_date) oldest_date, \
                 min(loc_statement_id) oldest_id, \
                 line_of_credit_id from loc_statement WHERE \
                 is_min_paid=False group by line_of_credit_id) los \
                 on app.line_of_credit_id = los.line_of_credit_id \
                 and cast(los.oldest_date as date) BETWEEN '%s' AND '%s'"\
                % (range2_ago, range1_ago)
        rows = self.run_query(query)
        fields = ['application_id', 'line_of_credit_id',
                  'payment_due_date', 'loc_statement_id']
        collection = create_collection(fields, rows)
        return collection

    def overdue(self, overdue_days=1):
        today = timezone.now().date()
        overdue_date = today - timedelta(days=overdue_days)
        query = "select app.application_id, app.line_of_credit_id, los.oldest_date, \
                 los.oldest_id from application app inner join \
                 (select min(payment_due_date) oldest_date, \
                 min(loc_statement_id) oldest_id, \
                 line_of_credit_id from loc_statement WHERE \
                 is_min_paid=False group by line_of_credit_id) los \
                 on app.line_of_credit_id = los.line_of_credit_id \
                 and cast(los.oldest_date as date) < '%s'" % (overdue_date)
        rows = self.run_query(query)
        fields = ['application_id', 'line_of_credit_id',
                  'payment_due_date', 'loc_statement_id']
        collection = create_collection(fields, rows)
        return collection


class LineOfCreditStatementManager(GetInstanceMixin, JuloModelManager):
    def get_queryset(self):
        return LineOfCreditStatementQuerySet(self.model)

    def not_min_paid(self):
        return self.get_queryset().not_min_paid()

    def due_today(self):
        return self.get_queryset().due_soon(due_in_days=0)

    def dpd_1_to_30(self):
        return self.get_queryset().dpd_group_range(1, 30)

    def overdue_more_than30(self):
        return self.get_queryset().overdue(overdue_days=30)

    def due_soon(self):
        return self.get_queryset().due_soon(due_in_days=1)


class LineOfCreditStatement(TimeStampedModel):
    id = models.AutoField(db_column='loc_statement_id', primary_key=True)

    line_of_credit = models.ForeignKey('LineOfCredit',
                                       models.DO_NOTHING,
                                       db_column='line_of_credit_id')

    last_billing_amount = models.BigIntegerField(null=True, blank=True)
    last_minimum_payment = models.BigIntegerField(null=True, blank=True)
    last_payment_due_date = models.DateTimeField(null=True, blank=True)
    last_payment_overpaid = models.BigIntegerField(null=True, blank=True)
    payment_amount = models.BigIntegerField()
    late_fee_rate = models.FloatField()
    late_fee_amount = models.BigIntegerField()
    interest_rate = models.FloatField()
    interest_amount = models.BigIntegerField()
    purchase_amount = models.BigIntegerField()
    payment_overpaid = models.BigIntegerField(default=0)
    billing_amount = models.BigIntegerField()
    minimum_payment = models.BigIntegerField()
    payment_due_date = models.DateTimeField()
    statement_code = models.CharField(max_length=100)
    is_min_paid = models.BooleanField(default=False)

    objects = LineOfCreditStatementManager()

    class Meta(object):
        db_table = 'loc_statement'


class LineOfCreditNotification(TimeStampedModel):
    id = models.AutoField(db_column='loc_notification_id', primary_key=True)

    loc_statement = models.ForeignKey(
        'LineOfCreditStatement', models.DO_NOTHING, db_column='line_of_credit_statement_id',
        null=True, blank=True)

    channel = models.CharField(max_length=100)
    type = models.CharField(max_length=100)
    send_date = models.DateTimeField()
    is_sent = models.BooleanField(default=False)
    is_cancel = models.BooleanField(default=False)

    class Meta(object):
        db_table = 'loc_notification'


class LineOfCreditNote(TimeStampedModel):
    id = models.AutoField(db_column='loc_note_id', primary_key=True)
    line_of_credit = models.ForeignKey('LineOfCredit',
                                       models.DO_NOTHING,
                                       db_index=True,
                                       db_column='line_of_credit_id')
    loc_statement = models.ForeignKey('LineOfCreditStatement',
                                      models.DO_NOTHING,
                                      db_column='line_of_credit_statement_id',
                                      null=True, blank=True)
    note_text = models.TextField()
    added_by = CurrentUserField(related_name="loc_notes")

    class Meta(object):
        db_table = 'loc_note'
