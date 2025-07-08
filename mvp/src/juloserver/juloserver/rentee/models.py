import string
import random

from django.db import models

from juloserver.julocore.data.models import JuloModelManager, GetInstanceMixin, TimeStampedModel
from .constants import PaymentDepositStatus


class CommonManager(GetInstanceMixin, JuloModelManager):
    pass


class PaymentDeposit(TimeStampedModel):
    id = models.AutoField(db_column='payment_deposit_id', primary_key=True)
    loan = models.OneToOneField('julo.Loan',
                                models.DO_NOTHING,
                                db_column='loan_id')
    total_deposit_amount = models.IntegerField(default=0)
    deposit_amount = models.IntegerField(default=0)
    admin_fee = models.IntegerField(default=0)
    protection_fee = models.IntegerField(default=0)
    status = models.TextField(default='PENDING')
    paid_total_deposit_amount = models.IntegerField(default=0)
    verification_code = models.TextField(null=True, blank=True)
    is_verified_code = models.BooleanField(default=False)
    rentee_invoice = models.TextField(null=True)
    paid_date = models.DateTimeField(null=True)
    rentee_device = models.ForeignKey('RenteeDeviceList',
                                      models.DO_NOTHING,
                                      db_column='rentee_device_id',
                                      null=True)

    objects = CommonManager()

    class Meta:
        db_table = "payment_deposit"

    def new_verification_code(self, size=6):
        self.verification_code = ''.join(random.choice(string.digits) for x in range(size))

    @property
    def due_amount(self):
        return self.total_deposit_amount - self.paid_total_deposit_amount

    def lock(self):
        return PaymentDeposit.objects.select_for_update().get(pk=self.id)

    def is_success(self):
        return self.status == PaymentDepositStatus.SUCCESS and self.is_verified_code


class RenteeDeviceList(TimeStampedModel):
    id = models.AutoField(db_column='rentee_device_list_id', primary_key=True)
    price = models.IntegerField()
    device_name = models.TextField()
    store = models.TextField()
    is_active = models.BooleanField()

    objects = CommonManager()

    class Meta:
        db_table = "rentee_device_list"
