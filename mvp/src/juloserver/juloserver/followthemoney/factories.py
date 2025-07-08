from builtins import object
from datetime import datetime, date, timedelta
from dateutil.relativedelta import relativedelta
import random
import string
import time

import pytest

from factory.django import DjangoModelFactory
from factory import SubFactory

from juloserver.julo.tests.factories import PaymentEventFactory, PartnerFactory, ApplicationFactory
from .models import LenderCurrent, LenderRepaymentTransaction, LenderBucket, LenderBalanceCurrent, \
    LoanAgreementTemplate, ApplicationLenderHistory, SbDailyOspProductLender
from .models import LenderReversalTransaction
from .models import LenderReversalTransactionHistory
from .models import LenderBankAccount
from ..julo.models import RepaymentTransaction, Partner, Customer, Loan, Payment, \
    ApplicationHistory, FeatureSetting
from django.contrib.auth.models import User
from django.contrib.auth.hashers import make_password


class LenderCurrentFactory(DjangoModelFactory):
    class Meta(object):
        model = LenderCurrent

    service_fee = 0
    company_name = 'Company'
    poc_name = 'Full name'
    poc_email = 'mail@mail.com'
    lender_address_province = 'province'
    lender_address_city = 'city'
    lender_address = 'address'


class LenderReversalTransactionFactory(DjangoModelFactory):
    class Meta(object):
        model = LenderReversalTransaction

    source_lender = SubFactory(LenderCurrentFactory)
    voided_payment_event = SubFactory(PaymentEventFactory)
    amount = 0


class LenderReversalTransactionHistoryFactory(DjangoModelFactory):
    class Meta(object):
        model = LenderReversalTransactionHistory

    lender_reversal_transaction = SubFactory(LenderReversalTransactionFactory)
    amount = 0


class LenderBankAccountFactory(DjangoModelFactory):
    class Meta(object):
        model = LenderBankAccount

    lender = SubFactory(LenderCurrentFactory)
    bank_account_type = ''
    bank_name = ''
    account_name = ''
    account_number = ''
    bank_account_status = ''


class LenderRepaymentTransactionFactory(DjangoModelFactory):
    class Meta(object):
        model = LenderRepaymentTransaction

    lender = SubFactory(LenderCurrentFactory)
    transaction_date = datetime.now()
    amount = 0
    group_id = '1'


class RepaymentTransactionFactory(DjangoModelFactory):
    class Meta(object):
        model = RepaymentTransaction

    partner = SubFactory(Partner)
    customer = SubFactory(Customer)
    loan = SubFactory(Loan)
    payment = SubFactory(Payment)


class LenderBucketFactory(DjangoModelFactory):
    class Meta(object):
        model = LenderBucket

    partner = SubFactory(PartnerFactory)
    is_active = True
    application_ids = {"approved": ['2000000141'], "rejected": ['2000000146']}


class InventorUserWithEmailFactory(DjangoModelFactory):
    class Meta(object):
        model = User

    email = 'test@gmail.com'


class InventorUserFactory(DjangoModelFactory):
    class Meta(object):
        model = User

    username = 'test'
    password = make_password('password@123')


class LenderBalanceCurrentFactory(DjangoModelFactory):
    class Meta(object):
        model = LenderBalanceCurrent

    lender = SubFactory(LenderCurrentFactory)


class LoanAgreementTemplateFactory(DjangoModelFactory):
    class Meta(object):
        model = LoanAgreementTemplate

    lender = SubFactory(LenderCurrentFactory)
    is_active = True
    agreement_type = "general"


class ApplicationHistoryFactory(DjangoModelFactory):
    class Meta(object):
        model = ApplicationHistory

    application = SubFactory(ApplicationFactory)
    status_new = 170
    status_old = 172


class ApplicationLenderHistoryFactory(DjangoModelFactory):
    class Meta(object):
        model = ApplicationLenderHistory

    application = SubFactory(ApplicationFactory)


class FeatureSettingHistoryFactory(DjangoModelFactory):
    class Meta(object):
        model = FeatureSetting

    feature_name = 'ftm_configuration'
    category = 'followthemoney'
    is_active = True
    parameters = {'reassign_count': 0}


class SbDailyOspProductLenderFactory(DjangoModelFactory):
    class Meta(object):
        model = SbDailyOspProductLender

    product = 'J1_reg'
    current = 0
    dpd1 = 0
    dpd30 = 0
    dpd60 = 0
    dpd90 = 0
    dpd120 = 0
    dpd150 = 0
    dpd180 = 0
    npl90 = 0
