from __future__ import unicode_literals

from builtins import str
from builtins import object
import logging
from datetime import date

from juloserver.julocore.data.models import JuloModelManager, GetInstanceMixin, TimeStampedModel
from juloserver.julo.models import Payment
from juloserver.julo.statuses import LoanStatusCodes
from juloserver.julo.statuses import PaymentStatusCodes
from django.contrib.gis.db import models
from django.contrib.auth.models import User
from cuser.fields import CurrentUserField

logger = logging.getLogger(__name__)


class GhostPayment(Payment):
    class Meta(object):
        proxy = True
        app_label = 'payment_status'
        auto_created = True

    @property
    def dpd(self):
        if self.due_date is not None and self.loan.status != LoanStatusCodes.INACTIVE:
            ref_date = self.paid_date if self.status in PaymentStatusCodes.paid_status_codes() else date.today()
            return str((ref_date - self.due_date).days)
        else:
            return '-'

    @property
    def dpd_ptp(self):
        if self.ptp_date is not None and self.loan.status != LoanStatusCodes.INACTIVE:
            return str((date.today() - self.ptp_date).days)
        else:
            return '-'
    @property
    def int_dpd(self):
        return int(self.dpd)


class PaymentLockedManager(GetInstanceMixin, models.Manager):
    pass


class PaymentLocked(models.Model):
    """
    models for Payment was Locked for agents until change status take in
    """
    id = models.AutoField(db_column='payment_locked_id', primary_key=True)

    user_lock = models.ForeignKey(
        User, models.DO_NOTHING, db_column='user_lock_id', related_name="payment_user_lock")
    user_unlock = models.ForeignKey(
        User, models.DO_NOTHING, null=True, blank=True,
        db_column='user_unlock_id', related_name="payment_user_unlock")

    payment = models.ForeignKey(
        Payment, models.DO_NOTHING, db_column='payment_id')

    status_code_locked = models.IntegerField(null=True, blank=True)
    status_code_unlocked = models.IntegerField(null=True, blank=True)

    locked = models.BooleanField(default=True)
    status_obsolete = models.BooleanField(default=False)

    ts_locked = models.DateTimeField(auto_now_add=True, editable=False)
    ts_unlocked = models.DateTimeField(
        auto_now=True, null=True, blank=True, editable=False)

    objects = PaymentLockedManager()

    class Meta(object):
        db_table = 'payment_locked'
        verbose_name_plural = "Payment Locked"

    def __unicode__(self):
        return "%s - %s" % (self.user_lock, self.payment)

    def __str__(self):
        return '[%s:%s]' % (self.user_lock, self.payment)

    @classmethod
    def create(cls, user, payment, status_code_locked, locked=None):
        if(locked):
            payment_locked = cls(user_lock=user,
                           payment=payment,
                           status_code_locked=status_code_locked,
                           locked=locked)
        else:
            payment_locked = cls(user_lock=user,
                           payment=payment,
                           status_code_locked=status_code_locked
                           )

        return payment_locked.save()


class PaymentLockedMaster(models.Model):
    """
    models for Only One payment at that time for user to lock
    """
    id = models.AutoField(db_column='payment_locked_master_id', primary_key=True)

    user_lock = models.ForeignKey(
        User, models.DO_NOTHING, db_column='user_lock_id', related_name="payment_user_lock_master")
    payment = models.OneToOneField(
        Payment, models.DO_NOTHING, db_column='payment_id')

    ts_locked = models.DateTimeField(auto_now_add=True, editable=False)

    objects = PaymentLockedManager()

    class Meta(object):
        db_table = 'payment_locked_master'
        verbose_name_plural = "Payment Lock Master"

    def __unicode__(self):
        return "%s - %s" % (self.user_lock, self.payment)

    def __str__(self):
        return '[%s:%s]' % (self.user_lock, self.payment)

    @classmethod
    def create(cls, user, payment, locked):
        ret_create = None
        try:
            payment_locked = cls(user_lock=user,
                           payment=payment)
            payment_locked.save()
            ret_create = 1

        except Exception as e:
            #there is an error
            err_msg = """
                Payment locked master was locked again for agent : %s with err: %s
            """
            err_msg = err_msg % (user, e)
            logger.info({
                'payment_id': payment.id,
                'user' : user,
                'error': err_msg
            })
        return ret_create


class CsvFileManualPaymentRecordManager(GetInstanceMixin, JuloModelManager):
    pass


class CsvFileManualPaymentRecord(TimeStampedModel):
    id = models.AutoField(db_column='csv_file_manual_payment_record_id', primary_key=True)
    filename = models.CharField(max_length=200, unique=True)
    agent = CurrentUserField()
    objects = CsvFileManualPaymentRecordManager()

    class Meta(object):
        db_table = 'csv_file_manual_payment_record'
