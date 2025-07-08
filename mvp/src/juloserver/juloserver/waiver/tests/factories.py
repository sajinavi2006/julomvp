from builtins import object
from factory.django import DjangoModelFactory
from factory import SubFactory
from ..models import WaiverAccountPaymentApproval
from ..models import WaiverAccountPaymentRequest
from juloserver.loan_refinancing.tests.factories import (
    WaiverApprovalFactory,
    WaiverRequestFactory,
)
from juloserver.account_payment.tests.factories import AccountPaymentFactory

class WaiverAccountPaymentApprovalFactory(DjangoModelFactory):
    class Meta(object):
        model = WaiverAccountPaymentApproval

    waiver_approval = SubFactory(WaiverApprovalFactory)
    account_payment = SubFactory(AccountPaymentFactory)
    outstanding_late_fee_amount = 0
    outstanding_interest_amount = 0
    outstanding_principal_amount = 0
    total_outstanding_amount = 0
    approved_late_fee_waiver_amount = 0
    approved_interest_waiver_amount = 0
    approved_principal_waiver_amount = 0
    total_approved_waiver_amount = 0
    remaining_late_fee_amount = 0
    remaining_interest_amount = 0
    remaining_principal_amount = 0
    total_remaining_amount = 0


class WaiverAccountPaymentRequestFactory(DjangoModelFactory):
    class Meta(object):
        model = WaiverAccountPaymentRequest

    waiver_request = SubFactory(WaiverRequestFactory)
    account_payment = SubFactory(AccountPaymentFactory)
    outstanding_late_fee_amount = 0
    outstanding_interest_amount = 0
    outstanding_principal_amount = 0
    total_outstanding_amount = 0
    requested_late_fee_waiver_amount = 0
    requested_interest_waiver_amount = 0
    requested_principal_waiver_amount = 0
    total_requested_waiver_amount = 0
    remaining_late_fee_amount = 0
    remaining_interest_amount = 0
    remaining_principal_amount = 0
    total_remaining_amount = 0
    is_paid_off_after_ptp = True
