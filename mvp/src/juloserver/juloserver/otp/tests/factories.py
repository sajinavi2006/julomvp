import random
import string
import time
from builtins import object
from datetime import date, datetime, timedelta

import pytest
from dateutil.relativedelta import relativedelta
from factory import (
    Iterator,
    LazyAttribute,
    SelfAttribute,
    Sequence,
    SubFactory,
    post_generation,
)
from factory.django import DjangoModelFactory

from juloserver.julo.tests.factories import (
    ApplicationFactory,
    CustomerFactory,
    ImageFactory,
)
from juloserver.otp.models import MisCallOTP, OtpTransactionFlow


class MisCallOTPFactory(DjangoModelFactory):
    class Meta(object):
        model = MisCallOTP

    customer = SubFactory(CustomerFactory)
    application = SubFactory(ApplicationFactory)
    otp_token = '3124'
    miscall_number = '0288233123124'
    dial_code_telco = '200'
    dial_status_telco = 'OK'
    price = '179'


class OtpTransactionFlowFactory(DjangoModelFactory):
    class Meta(object):
        model = OtpTransactionFlow

    customer = SubFactory(CustomerFactory)
    loan_xid = 0
    action_type = ''
    is_allow_blank_token_transaction = False
