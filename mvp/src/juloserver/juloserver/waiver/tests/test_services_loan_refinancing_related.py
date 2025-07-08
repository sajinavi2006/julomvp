from django.test.testcases import TestCase
from django.utils import timezone
from dateutil.relativedelta import relativedelta

from juloserver.account.tests.factories import AccountFactory
from juloserver.account_payment.tests.factories import AccountPaymentFactory
from juloserver.loan_refinancing.tests.factories import (
    LoanRefinancingRequestFactory,
    LoanRefinancingOfferFactory,
)
from juloserver.payback.tests.factories import WaiverTempFactory

from juloserver.loan_refinancing.constants import CovidRefinancingConst
from juloserver.payback.constants import WaiverConst

from ..services.loan_refinancing_related import (
    loan_refinancing_request_update_for_j1_waiver,
    get_j1_loan_refinancing_request,
    check_eligibility_of_j1_loan_refinancing,
    activate_j1_loan_refinancing_waiver,
)


class TestLoanRefinancingRelatedWaiverServices(TestCase):
    def setUp(self):
        self.account = AccountFactory()
        self.account_payment = AccountPaymentFactory(account=self.account)
        self.loan_refinancing_request = LoanRefinancingRequestFactory(
            account=self.account, loan=None,
            status=CovidRefinancingConst.STATUSES.offer_generated,
            prerequisite_amount=0,
            expire_in_days=0,
        )

    def test_loan_refinancing_request_update_for_j1_waiver(self):
        old_prerequsite_amount = self.loan_refinancing_request.prerequisite_amount
        loan_refinancing_request_update_for_j1_waiver(self.account_payment)
        self.loan_refinancing_request.refresh_from_db()
        assert old_prerequsite_amount == self.loan_refinancing_request.prerequisite_amount

        old_prerequsite_amount = self.loan_refinancing_request.prerequisite_amount
        self.loan_refinancing_request.status = CovidRefinancingConst.STATUSES.offer_selected
        self.loan_refinancing_request.save()
        loan_refinancing_request_update_for_j1_waiver(self.account_payment)
        self.loan_refinancing_request.refresh_from_db()
        assert old_prerequsite_amount == self.loan_refinancing_request.prerequisite_amount

        old_prerequsite_amount = self.loan_refinancing_request.prerequisite_amount
        LoanRefinancingOfferFactory(
            loan_refinancing_request=self.loan_refinancing_request,
            product_type=CovidRefinancingConst.PRODUCTS.r6,
            is_accepted=True,
            is_latest=True,
        )
        loan_refinancing_request_update_for_j1_waiver(self.account_payment)
        self.loan_refinancing_request.refresh_from_db()
        assert old_prerequsite_amount == self.loan_refinancing_request.prerequisite_amount

        waiver_temp = WaiverTempFactory(
            account=self.account,
            status=WaiverConst.ACTIVE_STATUS,
            payment=None,
        )
        self.loan_refinancing_request.product_type = CovidRefinancingConst.PRODUCTS.r4
        self.loan_refinancing_request.save()
        loan_refinancing_request_update_for_j1_waiver(self.account_payment)
        self.loan_refinancing_request.refresh_from_db()
        assert waiver_temp.need_to_pay == self.loan_refinancing_request.prerequisite_amount

        self.loan_refinancing_request.channel = CovidRefinancingConst.CHANNELS.reactive
        self.loan_refinancing_request.comms_channel_1 = CovidRefinancingConst.COMMS_CHANNELS.sms
        self.loan_refinancing_request.save()
        loan_refinancing_request_update_for_j1_waiver(self.account_payment)
        self.loan_refinancing_request.refresh_from_db()
        assert waiver_temp.need_to_pay == self.loan_refinancing_request.prerequisite_amount

        self.loan_refinancing_request.product_type = CovidRefinancingConst.PRODUCTS.r5
        self.loan_refinancing_request.status = CovidRefinancingConst.STATUSES.offer_selected
        self.loan_refinancing_request.save()
        loan_refinancing_request_update_for_j1_waiver(self.account_payment)
        self.loan_refinancing_request.refresh_from_db()
        assert waiver_temp.need_to_pay == self.loan_refinancing_request.prerequisite_amount

        self.loan_refinancing_request.product_type = CovidRefinancingConst.PRODUCTS.r6
        self.loan_refinancing_request.status = CovidRefinancingConst.STATUSES.offer_selected
        self.loan_refinancing_request.save()
        loan_refinancing_request_update_for_j1_waiver(self.account_payment)
        self.loan_refinancing_request.refresh_from_db()
        assert waiver_temp.need_to_pay == self.loan_refinancing_request.prerequisite_amount

    def test_get_j1_loan_refinancing_request(self):
        loan_refinancing_request = get_j1_loan_refinancing_request(self.account)
        assert loan_refinancing_request == None

    def test_check_eligibility_of_j1_loan_refinancing(self):
        paid_date = timezone.localtime(timezone.now()).date()

        self.loan_refinancing_request.status = CovidRefinancingConst.STATUSES.expired
        self.loan_refinancing_request.save()
        is_eligible = check_eligibility_of_j1_loan_refinancing(
            self.loan_refinancing_request, paid_date, paid_amount=0
        )
        assert is_eligible == False

        self.loan_refinancing_request.status = CovidRefinancingConst.STATUSES.offer_selected
        self.loan_refinancing_request.save()
        is_eligible = check_eligibility_of_j1_loan_refinancing(
            self.loan_refinancing_request, paid_date, paid_amount=0
        )
        assert is_eligible == True

        LoanRefinancingOfferFactory(
            loan_refinancing_request=self.loan_refinancing_request,
            product_type=CovidRefinancingConst.PRODUCTS.r6,
            is_accepted=True,
            is_latest=True,
            offer_accepted_ts=timezone.localtime(timezone.now()),
        )
        is_eligible = check_eligibility_of_j1_loan_refinancing(
            self.loan_refinancing_request, paid_date + relativedelta(days=1), paid_amount=0
        )
        assert is_eligible == False

        self.loan_refinancing_request.status = CovidRefinancingConst.STATUSES.offer_selected
        self.loan_refinancing_request.prerequisite_amount = 1
        self.loan_refinancing_request.save()
        is_eligible = check_eligibility_of_j1_loan_refinancing(
            self.loan_refinancing_request, paid_date, paid_amount=0
        )
        assert is_eligible == False

    def test_activate_j1_loan_refinancing_waiver(self):
        paid_date = timezone.localtime(timezone.now())

        self.loan_refinancing_request.status = CovidRefinancingConst.STATUSES.approved
        self.loan_refinancing_request.save()
        activate_j1_loan_refinancing_waiver(self.account, paid_date, 1)
        self.loan_refinancing_request.refresh_from_db()
        assert self.loan_refinancing_request.status == CovidRefinancingConst.STATUSES.activated
