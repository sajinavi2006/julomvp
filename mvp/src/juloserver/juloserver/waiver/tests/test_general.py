from django.test.testcases import TestCase
from ..models import WaiverAccountPaymentApproval
from ..serializers import J1WaiverRequestSerializer
from .factories import WaiverAccountPaymentApprovalFactory


class TestWaiverGeneral(TestCase):
    def setUp(self):
        self.waiver_account_payment_approval = WaiverAccountPaymentApproval()

    def test_waiver_account_payment_approval_models(self):
        waiver_account_payment_approval = self.waiver_account_payment_approval
        assert (waiver_account_payment_approval.requested_late_fee_waiver_amount or 0) == 0
        assert (waiver_account_payment_approval.requested_interest_waiver_amount or 0) == 0
        assert (waiver_account_payment_approval.requested_principal_waiver_amount or 0) == 0
        assert (waiver_account_payment_approval.total_requested_waiver_amount or 0) == 0

    def test_j1_waiver_request_serializer(self):
        data = dict(
            account_id=1,
            bucket_name="2",
            selected_program_name="r6",
            is_covid_risky="yes",
            outstanding_amount=0,
            unpaid_principal=0,
            unpaid_interest=0,
            unpaid_late_fee=0,
            waiver_validity_date="2020-02-02",
            ptp_amount=0,
            calculated_unpaid_waiver_percentage=0.0,
            recommended_unpaid_waiver_percentage=0.0,
            waived_account_payment_count=0,
            partner_product="normal",
            is_automated=False,
            waiver_recommendation_id=0,
            requested_late_fee_waiver_percentage="100%",
            requested_interest_waiver_percentage="100%",
            requested_principal_waiver_percentage="100%",
            requested_late_fee_waiver_amount=0,
            requested_interest_waiver_amount=0,
            requested_principal_waiver_amount=0,
            requested_waiver_amount=0,
            remaining_amount_for_waived_payment=0,
            agent_notes="note",
            first_waived_account_payment=0,
            last_waived_account_payment=0,
            comms_channels="Email",
            is_customer_confirmed=False,
            outstanding_late_fee_amount=0,
            outstanding_interest_amount=0,
            outstanding_principal_amount=0,
            selected_account_payments_waived=[],
            unrounded_requested_interest_waiver_percentage=0.0,
            unrounded_requested_late_fee_waiver_percentage=0.0,
            unrounded_requested_principal_waiver_percentage=0.0,
            agent_group='Desk Collector',
        )
        true_serializer = J1WaiverRequestSerializer(data=data)
        assert true_serializer.is_valid() == True
        assert true_serializer.data['is_covid_risky'] == 'True'

        data['is_covid_risky'] = "no"
        false_serializer = J1WaiverRequestSerializer(data=data)
        assert false_serializer.is_valid() == True
        assert false_serializer.data['is_covid_risky'] == 'False'
