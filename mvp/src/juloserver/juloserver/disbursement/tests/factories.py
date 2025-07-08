from builtins import object
from datetime import datetime, date, timedelta
from dateutil.relativedelta import relativedelta
import random
import string
import time

import pytest

from factory.django import DjangoModelFactory
from factory import SubFactory

from juloserver.disbursement.models import (
    NameBankValidation,
    Disbursement,
    BankNameValidationLog,
    PaymentGatewayCustomerDataLoan,
    DailyDisbursementLimitWhitelist,
    DailyDisbursementLimitWhitelistHistory,
)
from juloserver.disbursement.constants import NameBankValidationVendors


class NameBankValidationFactory(DjangoModelFactory):
    class Meta(object):
        model = NameBankValidation

    account_number = "4760157576"
    method = NameBankValidationVendors.XFERS


class DisbursementFactory(DjangoModelFactory):
    class Meta(object):
        model = Disbursement

    name_bank_validation = SubFactory(NameBankValidationFactory)
    amount = 1000000


class BankNameValidationLogFactory(DjangoModelFactory):
    class Meta(object):
        model = BankNameValidationLog


class PaymentGatewayCustomerDataLoanFactory(DjangoModelFactory):
    class Meta(object):
        model = PaymentGatewayCustomerDataLoan


class DailyDisbursementLimitWhitelistFactory(DjangoModelFactory):
    class Meta(object):
        model = DailyDisbursementLimitWhitelist


class DailyDisbursementLimitWhitelistHistoryFactory(DjangoModelFactory):
    class Meta(object):
        model = DailyDisbursementLimitWhitelistHistory
