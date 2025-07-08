from builtins import object
from datetime import date

from factory import SubFactory
from factory.django import DjangoModelFactory

from juloserver.account_payment.tests.factories import AccountPaymentFactory
from juloserver.apiv2.models import (
    AutoDataCheck,
    EtlJob,
    EtlStatus,
    FinfiniStatus,
    LoanRefinancingScore,
    PdCollectionModelResult,
    PdCreditModelResult,
    PdFraudModelResult,
    PdIncomeTrustModelResult,
    PdWebModelResult,
    SdDeviceApp,
    PdFraudDetection,
    PdIncomeVerification,
    PdCustomerLifetimeModelResult,
)


class EtlJobFactory(DjangoModelFactory):
    class Meta(object):
        model = EtlJob

    id = 123
    application_id = 0
    customer_id = 0
    data_type = ''
    status = 'initiated'


class PdCreditModelResultFactory(DjangoModelFactory):
    class Meta(object):
        model = PdCreditModelResult

    id = 123
    application_id = 0
    customer_id = 0
    version = 0
    probability_fpd = 0
    pgood = 0.6
    has_fdc = True


class PdWebModelResultFactory(DjangoModelFactory):
    class Meta(object):
        model = PdWebModelResult

    id = 123
    application_id = 0
    customer_id = 0
    probability_fpd = 0
    pgood = 0
    has_fdc = True


class PdFraudModelResultFactory(DjangoModelFactory):
    class Meta(object):
        model = PdFraudModelResult

    probability_fpd = 0
    application_id = 0
    customer_id = 0


class AutoDataCheckFactory(DjangoModelFactory):
    class Meta(object):
        model = AutoDataCheck

    id = 0
    application_id = 0
    is_okay = True


class PdIncomeTrustModelResultFactory(DjangoModelFactory):
    class Meta(object):
        model = PdIncomeTrustModelResult

    id = 0
    application_id = 0
    customer_id = 0
    version = 1
    value = 1


class EtlStatusFactory(DjangoModelFactory):
    class Meta(object):
        model = EtlStatus

    id = 0
    application_id = 0


class FinfiniStatusFactory(DjangoModelFactory):
    class Meta(object):
        model = FinfiniStatus

    id = 0
    name = ''
    status = ''
    vendor_type = ''


class LoanRefinancingScoreFactory(DjangoModelFactory):
    class Meta(object):
        model = LoanRefinancingScore

    application_id = 0
    loan_id = 0
    rem_installment = 0
    ability_score = 0.0
    willingness_score = 0.0
    oldest_payment_num = 0
    is_covid_risky = False
    bucket = ''


class SdDeviceAppFactory(DjangoModelFactory):
    class Meta(object):
        model = SdDeviceApp

    id = 0
    application_id = 0
    app_package_name = ''


class PdCollectionModelResultFactory(DjangoModelFactory):
    class Meta(object):
        model = PdCollectionModelResult

    account_payment = SubFactory(AccountPaymentFactory)
    prediction_before_call = 0
    prediction_after_call = 0
    due_amount = 0
    sort_rank = 0


class PdFraudDetectionFactory(DjangoModelFactory):
    class Meta(object):
        model = PdFraudDetection

    id = 123
    etl_job_id = 0
    application_id = 0
    customer_id = 0
    self_field_name = 'geo location'


class PdIncomeVerificationFactory(DjangoModelFactory):
    class Meta(object):
        model = PdIncomeVerification

    id = 123
    etl_job_id = 0
    application_id = 0
    customer_id = 0
    yes_no_income = 'unverified'


class PdCustomerLifetimeModelResultFactory(DjangoModelFactory):
    class Meta(object):
        model = PdCustomerLifetimeModelResult

    predict_date = date.today()
    lifetime_value = 'high'
    has_transact_in_range_date = 1
    customer_id = 100000000
    model_version = ''
    range_from_x190_date = 7
