from __future__ import division
from builtins import object

from factory import SubFactory
from factory.django import DjangoModelFactory
from faker import Faker

from juloserver.channeling_loan.models import (
    ChannelingLoanStatus,
    ChannelingEligibilityStatus,
    ChannelingLoanPayment,
    LenderOspAccount,
    LenderOspTransaction,
    LenderLoanLedger,
    LoanLenderTaggingDpdTemp,
    ChannelingLoanCityArea,
    ChannelingLoanSendFileTracking,
    ChannelingLoanApprovalFile,
    ChannelingPaymentEvent,
    DBSChannelingApplicationJob,
    ChannelingBScore,
)
from juloserver.core.utils import JuloFakerProvider
from juloserver.channeling_loan.constants import ChannelingLenderLoanLedgerConst

from juloserver.julo.tests.factories import PaymentEventFactory, PaymentFactory

fake = Faker()
fake.add_provider(JuloFakerProvider)


class ChannelingEligibilityStatusFactory(DjangoModelFactory):
    class Meta(object):
        model = ChannelingEligibilityStatus

    channeling_type = "BSS"
    eligibility_status = "eligible"
    reason = "eligible"
    version = 1


class ChannelingLoanStatusFactory(DjangoModelFactory):
    class Meta(object):
        model = ChannelingLoanStatus

    channeling_eligibility_status = SubFactory(ChannelingEligibilityStatusFactory)
    channeling_type = "BSS"
    channeling_status = "pending"
    channeling_interest_amount = 0
    channeling_interest_percentage = 0
    actual_interest_percentage = 0
    risk_premium_percentage = 0

class ChannelingLoanPaymentFactory(DjangoModelFactory):
    class Meta(object):
        model = ChannelingLoanPayment

    due_amount = 0
    principal_amount = 0
    interest_amount = 0
    actual_daily_interest = 0
    paid_interest = 0
    paid_principal = 0


class ChannelingLoanCityAreaFactory(DjangoModelFactory):
    class Meta(object):
        model = ChannelingLoanCityArea

    city_area = "DI LUAR INDONESIA"
    city_area_code = "9999"


class LenderOspAccountFactory(DjangoModelFactory):
    class Meta(object):
        model = LenderOspAccount

    lender_account_partner = "lender account partner"
    lender_account_name = "FAMA"
    lender_account_note = "notes"
    lender_withdrawal_percentage = 115

    balance_amount = 10000000
    fund_by_lender = 0
    fund_by_julo = 0
    total_outstanding_principal = 0
    priority = 1

class LoanLenderTaggingDpdTempFactory(DjangoModelFactory):
    class Meta(object):
        model = LoanLenderTaggingDpdTemp

    loan_id = 123123123
    loan_dpd = 0


class LenderOspTransactionFactory(DjangoModelFactory):
    class Meta(object):
        model = LenderOspTransaction

    lender_osp_account = SubFactory(LenderOspAccountFactory)
    balance_amount = 100000000
    transaction_type = ChannelingLenderLoanLedgerConst.WITHDRAWAL


class LenderLoanLedgerFactory(DjangoModelFactory):
    class Meta(object):
        model = LenderLoanLedger

    lender_osp_account = SubFactory(LenderOspAccountFactory)
    application_id = 123123123
    loan_xid = 123123123
    loan_id = 123123123
    osp_amount = 500000
    tag_type = ChannelingLenderLoanLedgerConst.INITIAL_TAG


class ChannelingLoanSendFileTrackingFactory(DjangoModelFactory):
    class Meta(object):
        model = ChannelingLoanSendFileTracking


class ChannelingLoanApprovalFileFactory(DjangoModelFactory):
    class Meta(object):
        model = ChannelingLoanApprovalFile

    channeling_type = 'FAMA'
    file_type = 'disbursement'


class ChannelingPaymentEventFactory(DjangoModelFactory):
    class Meta(object):
        model = ChannelingPaymentEvent

    payment_event = SubFactory(PaymentEventFactory)
    payment = SubFactory(PaymentFactory)
    installment_amount = 50000
    payment_amount = 50000
    paid_interest = 5000
    paid_principal = 45000
    outstanding_amount = 50000
    outstanding_principal = 45000
    outstanding_interest = 5000
    adjusted_principal = 0
    adjusted_interest = 0


class DBSChannelingApplicationJobFactory(DjangoModelFactory):
    class Meta(object):
        model = DBSChannelingApplicationJob


class ChannelingBScoreFactory(DjangoModelFactory):
    class Meta(object):
        model = ChannelingBScore
