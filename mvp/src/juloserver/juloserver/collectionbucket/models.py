from __future__ import unicode_literals

from builtins import object
from django.db import models
from django.conf import settings

from juloserver.julocore.data.models import (
    GetInstanceMixin, JuloModelManager, TimeStampedModel, CustomQuerySet
)
from ..julo.models import (Loan, Payment)

from ..minisquad.models import CollectionSquad
from juloserver.julo.constants import AgentAssignmentTypeConst
from juloserver.julo.statuses import PaymentStatusCodes
from juloserver.julo.models import (
    Application,
    Customer,
)


class CollectionAgentAssignmentQuerySet(CustomQuerySet):
    def get_bucket_2_data(self):
        return self.filter(type=AgentAssignmentTypeConst.DPD11_DPD40,
                           payment__payment_status_id__lt=PaymentStatusCodes.PAID_ON_TIME)

    def get_bucket_3_data(self):
        return self.filter(type=AgentAssignmentTypeConst.DPD41_DPD70,
                           payment__payment_status_id__lt=PaymentStatusCodes.PAID_ON_TIME)

    def get_bucket_4_data(self):
        return self.filter(type=AgentAssignmentTypeConst.DPD71_DPD90,
                           payment__payment_status_id__lt=PaymentStatusCodes.PAID_ON_TIME)

    def get_bucket_5_data(self):
        return self.filter(type=AgentAssignmentTypeConst.DPD91PLUS,
                           payment__payment_status_id__lt=PaymentStatusCodes.PAID_ON_TIME)

    def get_vendor_data(self):
        return self.filter(assign_to_vendor=True)


class CollectionAgentAssignmentManager(GetInstanceMixin, JuloModelManager):
    def get_queryset(self):
        return CollectionAgentAssignmentQuerySet(self.model)

    def get_bucket_2_data(self):
        return self.get_queryset().get_bucket_2_data()

    def get_bucket_3_data(self):
        return self.get_queryset().get_bucket_3_data()

    def get_bucket_4_data(self):
        return self.get_queryset().get_bucket_4_data()

    def get_bucket_5_data(self):
        return self.get_queryset().get_bucket_5_data()

    def get_bucket_2_vendor(self):
        return self.get_queryset()\
                   .get_bucket_2_data()\
                   .get_vendor_data()

    def get_bucket_3_vendor(self):
        return self.get_queryset()\
                   .get_bucket_3_data()\
                   .get_vendor_data()

    def get_bucket_4_vendor(self):
        return self.get_queryset()\
                   .get_bucket_4_data()\
                   .get_vendor_data()


class CollectionAgentTask(TimeStampedModel):
    """
        Agent Assignment 2.0
        Keeps log of agent assignments
    """
    id = models.AutoField(db_column='collection_agent_assignment_id', primary_key=True)
    loan = models.ForeignKey(Loan,
                             models.DO_NOTHING,
                             db_column='loan_id',
                             blank=True,
                             null=True)
    payment = models.ForeignKey(Payment,
                                models.DO_NOTHING,
                                db_column='payment_id',
                                blank=True,
                                null=True)
    agent = models.ForeignKey(settings.AUTH_USER_MODEL,
                              on_delete=models.CASCADE,
                              db_column='agent_id',
                              blank=True,
                              null=True)
    assign_time = models.DateTimeField(blank=True, null=True)
    unassign_time = models.DateTimeField(blank=True, null=True, db_index=True)
    type = models.CharField(max_length=50, blank=True, null=True, db_index=True)
    allocate_by = models.ForeignKey(settings.AUTH_USER_MODEL,
                                    on_delete=models.CASCADE,
                                    related_name="allocate_by",
                                    db_column='allocate_by_id',
                                    blank=True,
                                    null=True)
    assign_to_vendor = models.NullBooleanField()
    actual_agent = models.ForeignKey(settings.AUTH_USER_MODEL,
                                     on_delete=models.CASCADE,
                                     db_column='actual_agent_id',
                                     related_name='actual_agent',
                                     blank=True,
                                     null=True)
    account = models.ForeignKey(
        'account.Account',
        models.DO_NOTHING,
        db_column='account_id',
        blank=True,
        null=True
    )
    account_payment = models.ForeignKey(
        'account_payment.AccountPayment',
        models.DO_NOTHING,
        db_column='account_payment_id',
        blank=True,
        null=True
    )

    objects = CollectionAgentAssignmentManager()

    class Meta(object):
        db_table = 'collection_agent_task'

    def __str__(self):
        return "{loan}:{user}:{type}".format(loan=self.loan.id,
                                                    user=self.agent.username,
                                                    type=self.type)


class CollectionRiskVerificationCallListManager(GetInstanceMixin, JuloModelManager):
    pass


class CollectionRiskVerificationCallList(TimeStampedModel):
    id = models.AutoField(db_column='collection_risk_verification_call_list_id', primary_key=True)
    application = models.ForeignKey(Application, models.DO_NOTHING, db_column='application_id')
    customer = models.ForeignKey(Customer, models.DO_NOTHING, db_column='customer_id')
    account = models.ForeignKey(
        'account.Account',
        models.DO_NOTHING,
        db_column='account_id',
        blank=True,
        null=True
    )
    account_payment = models.ForeignKey(
        'account_payment.AccountPayment',
        models.DO_NOTHING,
        db_column='account_payment_id',
        blank=True,
        null=True
    )
    is_verified = models.BooleanField(default=False)
    is_connected = models.BooleanField(default=False)
    is_passed_minus_11 = models.BooleanField(default=False)
    is_paid_first_installment = models.BooleanField(default=False)

    objects = CollectionRiskVerificationCallListManager()

    class Meta(object):
        db_table = 'collection_risk_verification_call_list'