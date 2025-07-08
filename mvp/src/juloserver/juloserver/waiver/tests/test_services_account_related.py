from mock import patch
import pytz
from datetime import datetime
from django.utils import timezone
from dateutil.relativedelta import relativedelta
from django.test.testcases import TestCase
from juloserver.julo.tests.factories import (
    ApplicationFactory,
    AccountingCutOffDateFactory,
    AuthUserFactory,
    FeatureSettingFactory,
    LoanFactory,
    StatusLookupFactory,
    LenderFactory,
)
from juloserver.account.tests.factories import AccountFactory
from juloserver.account.models import AccountTransaction
from juloserver.account_payment.tests.factories import AccountPaymentFactory
from juloserver.loan_refinancing.tests.factories import (
    LoanRefinancingRequestFactory,
    WaiverRequestFactory,
    WaiverApprovalFactory,
    WaiverRecommendationFactory,
)
from juloserver.loan_refinancing.constants import CovidRefinancingConst
from juloserver.waiver.services.account_related import (
    get_is_covid_risky,
    get_data_for_agent_portal,
    get_data_for_approver_portal,
    get_account_ids_for_bucket_tree,
)
from juloserver.waiver.tests.factories import (
    WaiverAccountPaymentApprovalFactory,
    WaiverAccountPaymentRequestFactory,
)
from django.contrib.auth.models import Group
from juloserver.loan_refinancing.constants import (
    WAIVER_SPV_APPROVER_GROUP,
    WAIVER_COLL_HEAD_APPROVER_GROUP,
    WAIVER_OPS_TL_APPROVER_GROUP,
    WAIVER_B1_CURRENT_APPROVER_GROUP,
    WAIVER_B2_APPROVER_GROUP,
    WAIVER_B3_APPROVER_GROUP,
    WAIVER_B4_APPROVER_GROUP,
    WAIVER_B5_APPROVER_GROUP,
)
from juloserver.julo.constants import FeatureNameConst
from juloserver.julo.statuses import LoanStatusCodes
from juloserver.waiver.services.account_related import can_account_get_refinancing


class TestAccountRelatedWaiverServices(TestCase):
    def setUp(self):
        AccountingCutOffDateFactory()
        self.account = AccountFactory()
        ApplicationFactory(account=self.account)
        new_due_date = timezone.localtime(timezone.now()).date() - relativedelta(days=1)
        account_payment1 = AccountPaymentFactory(account=self.account, due_date=new_due_date)
        account_payment2 = AccountPaymentFactory(account=self.account)
        loan_refinancing_request = LoanRefinancingRequestFactory(
            account=self.account, loan=None,
            status=CovidRefinancingConst.STATUSES.offer_generated
        )
        self.waiver_request = WaiverRequestFactory(
            account=self.account, loan=None,
            loan_refinancing_request=loan_refinancing_request,
            waiver_recommendation=WaiverRecommendationFactory(),
            is_automated=False,
            is_approved=None,
            waiver_validity_date=timezone.localtime(timezone.now()).date() + relativedelta(days=1),
            first_waived_account_payment=account_payment1,
            last_waived_account_payment=account_payment2,
        )
        self.waiver_approval = WaiverApprovalFactory(waiver_request=self.waiver_request)
        WaiverAccountPaymentApprovalFactory(
            waiver_approval=self.waiver_approval, account_payment=account_payment1
        )
        WaiverAccountPaymentRequestFactory(
            waiver_request=self.waiver_request, account_payment=account_payment1
        )
        self.base_data = {
            'ongoing_account_payments': [],
            'account_id': '',
            'show': False,
            'is_covid_risky': '',
            'bucket': '',
            'loan_refinancing_request_count': 0,
            'account_id_list': [],
            'is_approver': False,
        }
        AccountTransaction.objects.filter(account=self.account).delete()

    @patch('django.utils.timezone.now')
    def test_get_is_covid_risky(self, mock_now):
        """
        is covid risky now set to no for all condition
        obsolete
        """
        mock_now.return_value = datetime(2020, 10, 10, tzinfo=pytz.UTC)
        today_date = timezone.localtime(timezone.now()).date()
        dob = today_date - relativedelta(years=20)
        application = self.account.application_set.last()

        application.dob = dob + relativedelta(months=1)
        application.save()
        assert get_is_covid_risky(self.account) == 'no'

        application.dob = dob + relativedelta(days=1)
        application.save()
        assert get_is_covid_risky(self.account) == 'no'

        application.address_provinsi = "Jawa Barat"
        application.address_kabupaten = "Bandung"
        application.job_industry = "kesehatan"
        application.job_type = ""
        application.job_description = ""
        application.save()
        assert get_is_covid_risky(self.account) == 'no'

    def test_get_data_for_agent_portal(self):
        data = get_data_for_agent_portal(self.base_data, 0)
        assert data['show'] == False

        data = get_data_for_agent_portal(self.base_data, self.account.id)
        assert data['show'] == True

    def test_get_data_for_approver_portal_normal(self):
        data = get_data_for_approver_portal(self.base_data, self.account.id)
        assert data['show'] == True

        self.waiver_approval.waiver_request = None
        self.waiver_approval.save()
        data = get_data_for_approver_portal(self.base_data, self.account.id)
        assert data['show'] == True

    def test_get_data_for_approver_portal_partial_paid(self):
        AccountTransaction.objects.create(
            account=self.account,
            transaction_type="payment",
            transaction_amount=1000,
            transaction_date=timezone.localtime(timezone.now()),
        )
        data = get_data_for_approver_portal(self.base_data, self.account.id)
        assert data['show'] == True

    def test_get_data_for_approver_portal_paid_waiver(self):
        self.waiver_request.waiver_validity_date = timezone.localtime(timezone.now()).date() - relativedelta(days=1)
        self.waiver_request.save()
        data = get_data_for_approver_portal(self.base_data, self.account.id)
        assert data['show'] == False

        self.waiver_request.is_automated = True
        self.waiver_request.save()
        data = get_data_for_approver_portal(self.base_data, self.account.id)
        assert data['show'] == False

    def test_get_account_ids_for_bucket_tree_bucket_current_and_bucket_1(self):
        user = AuthUserFactory()
        group = Group.objects.create(name=WAIVER_B1_CURRENT_APPROVER_GROUP)
        user.groups.add(group)

        user_groups = user.groups.values_list('name', flat=True)
        account_id_list = get_account_ids_for_bucket_tree(user_groups)
        assert ("bucket_0" in list(account_id_list)) == True
        assert ("bucket_1" in list(account_id_list)) == True

    def test_get_account_ids_for_bucket_tree_bucket_2(self):
        user = AuthUserFactory()
        group = Group.objects.create(name=WAIVER_B2_APPROVER_GROUP)
        user.groups.add(group)

        user_groups = user.groups.values_list('name', flat=True)
        account_id_list = get_account_ids_for_bucket_tree(user_groups)
        assert ("bucket_2" in list(account_id_list)) == True

    def test_get_account_ids_for_bucket_tree_bucket_3(self):
        user = AuthUserFactory()
        group = Group.objects.create(name=WAIVER_B3_APPROVER_GROUP)
        user.groups.add(group)

        group = Group.objects.create(name=WAIVER_OPS_TL_APPROVER_GROUP)
        user.groups.add(group)

        user_groups = user.groups.values_list('name', flat=True)
        account_id_list = get_account_ids_for_bucket_tree(user_groups)
        assert ("bucket_3" in list(account_id_list)) == True

    def test_get_account_ids_for_bucket_tree_bucket_4(self):
        user = AuthUserFactory()
        group = Group.objects.create(name=WAIVER_B4_APPROVER_GROUP)
        user.groups.add(group)
        group = Group.objects.create(name=WAIVER_COLL_HEAD_APPROVER_GROUP)
        user.groups.add(group)

        user_groups = user.groups.values_list('name', flat=True)
        account_id_list = get_account_ids_for_bucket_tree(user_groups)
        assert ("bucket_4" in list(account_id_list)) == True

    def test_get_account_ids_for_bucket_tree_bucket_5(self):
        user = AuthUserFactory()
        group = Group.objects.create(name=WAIVER_B5_APPROVER_GROUP)
        user.groups.add(group)

        group = Group.objects.create(name=WAIVER_SPV_APPROVER_GROUP)
        user.groups.add(group)

        user_groups = user.groups.values_list('name', flat=True)
        account_id_list = get_account_ids_for_bucket_tree(user_groups)
        assert ("bucket_5" in list(account_id_list)) == True


class TestChannelingAccountRefinancing(TestCase):
    def setUp(self):
        self.account = AccountFactory()
        self.feature_setting = FeatureSettingFactory(
            feature_name=FeatureNameConst.REFINANCING_RESTRICT_CHANNELING_LOAN,
            is_active=True,
            parameters={
                'data': {
                    'BSS': {
                        "query": {
                            'loan_status__status_code__in': [
                                LoanStatusCodes.CURRENT,
                                LoanStatusCodes.LOAN_1DPD,
                                LoanStatusCodes.LOAN_5DPD,
                                LoanStatusCodes.LOAN_30DPD,
                                LoanStatusCodes.LOAN_60DPD,
                                LoanStatusCodes.LOAN_90DPD,
                                LoanStatusCodes.RENEGOTIATED,
                                LoanStatusCodes.PAID_OFF,
                            ],
                            'lender__lender_name': 'bss_channeling'
                        },
                    },
                    'FAMA': {
                        "query": {
                            'loan_status__status_code__in': [
                                LoanStatusCodes.CURRENT,
                                LoanStatusCodes.LOAN_1DPD,
                                LoanStatusCodes.LOAN_5DPD,
                                LoanStatusCodes.LOAN_30DPD,
                                LoanStatusCodes.LOAN_60DPD,
                                LoanStatusCodes.LOAN_90DPD,
                                LoanStatusCodes.LOAN_120DPD,
                                LoanStatusCodes.LOAN_150DPD,
                                LoanStatusCodes.LOAN_180DPD,
                                LoanStatusCodes.RENEGOTIATED,
                                LoanStatusCodes.PAID_OFF,
                            ],
                            'lender__lender_name': 'fama_channeling'
                        },
                    },
                },
                'message': "Account ini tidak dapat didaftarkan ke refinancing program. Silahkan contact administrator",
            },
        )

    def test_bss_channeling_block_refinanced(self):
        # BSS case blocked
        LoanFactory(
            account=self.account,
            lender=LenderFactory(lender_name='bss_channeling'),
            loan_status=StatusLookupFactory(status_code=LoanStatusCodes.LOAN_90DPD),
        )
        allow_refinancing_program, _ = can_account_get_refinancing(self.account.id)

        self.assertFalse(allow_refinancing_program)

    def test_other_channeling_block_refinanced(self):
        # Other loan case case blocked
        LoanFactory(
            account=self.account,
            lender=LenderFactory(lender_name='fama_channeling'),
            loan_status=StatusLookupFactory(status_code=LoanStatusCodes.LOAN_120DPD),
        )
        allow_refinancing_program, _ = can_account_get_refinancing(self.account.id)

        self.assertFalse(allow_refinancing_program)

    def test_bss_channeling_can_refinanced(self):
        # BSS case can refinance (above DPD90)
        LoanFactory(
            account=self.account,
            lender=LenderFactory(lender_name='bss_channeling'),
            loan_status=StatusLookupFactory(status_code=LoanStatusCodes.LOAN_120DPD),
        )
        allow_refinancing_program, _ = can_account_get_refinancing(self.account.id)

        self.assertTrue(allow_refinancing_program)

    def test_bss_channeling_can_refinanced_and_block_other_loan_refinanced(self):
        # BSS case can refinance (above DPD90), but other loan cannot
        LoanFactory(
            account=self.account,
            lender=LenderFactory(lender_name='bss_channeling'),
            loan_status=StatusLookupFactory(status_code=LoanStatusCodes.LOAN_120DPD),
        )
        LoanFactory(
            account=self.account,
            lender=LenderFactory(lender_name='fama_channeling'),
            loan_status=StatusLookupFactory(status_code=LoanStatusCodes.LOAN_120DPD),
        )
        allow_refinancing_program, _ = can_account_get_refinancing(self.account.id)

        self.assertFalse(allow_refinancing_program)

    def test_bss_channeling_can_refinanced_and_other_loan_can_refinanced(self):
        # both BSS and other loan can refinanced
        LoanFactory(
            account=self.account,
            lender=LenderFactory(lender_name='bss_channeling'),
            loan_status=StatusLookupFactory(status_code=LoanStatusCodes.LENDER_REJECT),
        )
        LoanFactory(
            account=self.account,
            lender=LenderFactory(lender_name='fama_channeling'),
            loan_status=StatusLookupFactory(status_code=LoanStatusCodes.LENDER_REJECT),
        )
        allow_refinancing_program, _ = can_account_get_refinancing(self.account.id)

        self.assertTrue(allow_refinancing_program)
