from datetime import timedelta
from mock import patch
from django.utils import timezone
from django.test.testcases import TestCase

from juloserver.account.models import AccountStatusHistory
from juloserver.cfs.services.core_services import get_activity_based_on_payment_history
from juloserver.cfs.constants import ActionPointsBucket, CfsActionPointsActivity
from juloserver.julo.constants import FeatureNameConst, WorkflowConst
from juloserver.julo.models import LoanHistory, PaymentHistory
from juloserver.account.tests.factories import AccountFactory
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.tests.factories import (
    ApplicationFactory,
    AuthUserFactory,
    CustomerFactory,
    FeatureSettingFactory,
    LoanFactory,
    PartnerFactory,
    PaymentFactory,
    ProductLineFactory,
    StatusLookupFactory,
    WorkflowFactory,
)
from juloserver.cfs.models import (
    CfsActionPoints,
    CfsActionPointsAssignment,
    TotalActionPoints,
    TotalActionPointsHistory,
)
from juloserver.julo.statuses import (
    ApplicationStatusCodes,
    LoanStatusCodes,
    PaymentStatusCodes,
    JuloOneCodes,
)

from juloserver.account_payment.tests.factories import (
    AccountPaymentFactory,
)
from juloserver.cfs.tasks import check_cfs_action_expired, \
    tracking_transaction_case_for_action_points, tracking_repayment_case_for_action_points
from juloserver.loan.constants import LoanStatusChangeReason

class TestTrackingActivityForActionPoints(TestCase):
    def setUp(self):
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user_auth)
        self.account = AccountFactory(customer=self.customer)
        self.workflow = WorkflowFactory(name=WorkflowConst.JULO_ONE)
        self.product_line = ProductLineFactory(product_line_code=ProductLineCodes.J1)
        self.application = ApplicationFactory(
            customer=self.customer,
            account=self.account,
            workflow=self.workflow,
            product_line=self.product_line,
        )
        self.application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.LOC_APPROVED,
        )
        self.application.save()
        self.mock_cfs_action_point = CfsActionPoints(
            id=1, multiplier=0.001, floor=5, ceiling=25, default_expiry=180)

        self.today = timezone.localtime(timezone.now()).date()

        self.feature_setting = FeatureSettingFactory(
            is_active=True,
            feature_name=FeatureNameConst.CFS,
        )

    @patch('juloserver.cfs.models.CfsActionPoints.objects')
    def test_signal_tracking_transaction(self, mock):
        code = StatusLookupFactory(status_code=220)
        loan = LoanFactory(account=self.account, customer=self.customer,
                                loan_status=code, application=self.application, loan_amount=10000000)

        mock.get.return_value = self.mock_cfs_action_point

        x = LoanHistory.objects.create(loan=loan, status_old=212, status_new=LoanStatusCodes.CURRENT,
            change_reason=LoanStatusChangeReason.ACTIVATED)
        tracking_transaction_case_for_action_points.delay(
            loan.id, CfsActionPointsActivity.TRANSACT
        )
        assignment = CfsActionPointsAssignment.objects.all().filter(
            customer_id=self.customer.id, loan_id=loan.id
        ).first()

        total_point_history = TotalActionPointsHistory.objects.all().filter(
            customer_id=self.customer.id, cfs_action_point_assignment_id=assignment.id
        ).first()

        action_point = TotalActionPoints.objects.all().filter(
            customer_id=self.customer.id
        ).first()

        self.assertIsNotNone(assignment)
        self.assertIsNotNone(total_point_history)
        self.assertIsNotNone(action_point)

        self.assertEqual(assignment.points_changed, 25) # it can be 25 because in setUp we gave mock_cfs_action_points static values
        self.assertEqual(total_point_history.new_point, total_point_history.old_point + assignment.points_changed)


    @patch('juloserver.cfs.models.CfsActionPoints.objects')
    def test_signal_tracking_payment_types(self, mock):
        code = StatusLookupFactory(status_code=220)
        loan = LoanFactory(account=self.account, customer=self.customer,
                                loan_status=code, application=self.application)

        mock.get.return_value = self.mock_cfs_action_point

        payment = PaymentFactory(loan=loan, installment_principal=10000000)
        # test activity repayment types: on time, b1/b2/b3...

        # test activity == None
        x = PaymentHistory.objects.create( paid_date=self.today - timedelta(days=1), due_date=self.today,
            loan=loan, payment=payment, due_amount=100, payment_new_status_code=PaymentStatusCodes.PAYMENT_30DPD)
        tracking_repayment_case_for_action_points(payment.id, None)
        activity_id = get_activity_based_on_payment_history(x)
        self.assertIsNone(activity_id)

        # Early
        x = PaymentHistory.objects.create(
            paid_date=self.today, due_date=self.today - timedelta(days=2),
            loan=loan, payment=payment, due_amount=0, payment_new_status_code=PaymentStatusCodes.PAID_ON_TIME)
        activity_id = get_activity_based_on_payment_history(x)
        tracking_repayment_case_for_action_points(payment.id, activity_id)
        self.assertEquals(activity_id, CfsActionPointsActivity.EARLY_REPAYMENT)

        # On time
        x = PaymentHistory.objects.create(
            paid_date=self.today, due_date=self.today,
            loan=loan, payment=payment, due_amount=0, payment_new_status_code=PaymentStatusCodes.PAID_ON_TIME)
        activity_id = get_activity_based_on_payment_history(x)
        tracking_repayment_case_for_action_points(payment.id, activity_id)
        self.assertEquals(activity_id, CfsActionPointsActivity.ON_TIME_REPAYMENT)

        # GRACE
        x = PaymentHistory.objects.create(
            paid_date=self.today + timedelta(days=1), due_date=self.today,
            loan=loan, payment=payment, due_amount=0, payment_new_status_code=PaymentStatusCodes.PAID_WITHIN_GRACE_PERIOD)
        activity_id = get_activity_based_on_payment_history(x)
        tracking_repayment_case_for_action_points(payment.id, activity_id)
        self.assertEquals(activity_id, CfsActionPointsActivity.GRACE_REPAYMENT)

        # B1
        x = PaymentHistory.objects.create(
            paid_date=self.today + timedelta(days=ActionPointsBucket.B1_DPD['from'] + 1), due_date=self.today,
            loan=loan, payment=payment, due_amount=0, payment_new_status_code=PaymentStatusCodes.PAID_LATE)
        activity_id = get_activity_based_on_payment_history(x)
        tracking_repayment_case_for_action_points(payment.id, activity_id)
        self.assertEquals(activity_id, CfsActionPointsActivity.B1_REPAYMENT)

        # B2
        x = PaymentHistory.objects.create(
            paid_date=self.today + timedelta(days=ActionPointsBucket.B2_DPD['from'] + 1), due_date=self.today,
            loan=loan, payment=payment, due_amount=0, payment_new_status_code=PaymentStatusCodes.PAID_LATE)
        activity_id = get_activity_based_on_payment_history(x)
        tracking_repayment_case_for_action_points(payment.id, activity_id)
        self.assertEquals(activity_id, CfsActionPointsActivity.B2_REPAYMENT)

        # B3
        x = PaymentHistory.objects.create(
            paid_date=self.today + timedelta(days=ActionPointsBucket.B3_DPD['from'] + 1), due_date=self.today,
            loan=loan, payment=payment, due_amount=0, payment_new_status_code=PaymentStatusCodes.PAID_LATE)
        activity_id = get_activity_based_on_payment_history(x)
        tracking_repayment_case_for_action_points(payment.id, activity_id)
        self.assertEquals(activity_id, CfsActionPointsActivity.B3_REPAYMENT)

        # B4
        x = PaymentHistory.objects.create(
            paid_date=self.today + timedelta(days=ActionPointsBucket.B4_DPD['from'] + 1), due_date=self.today,
            loan=loan, payment=payment, due_amount=0, payment_new_status_code=PaymentStatusCodes.PAID_LATE)
        activity_id = get_activity_based_on_payment_history(x)
        tracking_repayment_case_for_action_points(payment.id, activity_id)
        self.assertEquals(activity_id, CfsActionPointsActivity.B4_REPAYMENT)

        # WO
        x = PaymentHistory.objects.create(
            paid_date=self.today + timedelta(days=ActionPointsBucket.B4_DPD['to'] + 1), due_date=self.today,
            loan=loan, payment=payment, due_amount=0, payment_new_status_code=PaymentStatusCodes.PAID_LATE)

        activity_id = get_activity_based_on_payment_history(x)
        tracking_repayment_case_for_action_points(payment.id, activity_id)
        self.assertEquals(activity_id, CfsActionPointsActivity.WO)

        assignment = CfsActionPointsAssignment.objects.all().filter(
            payment_id=payment.id, customer_id=self.customer.id).first()
        total_point_history = TotalActionPointsHistory.objects.all().filter(
            customer_id=self.customer.id, cfs_action_point_assignment_id=assignment.id
        ).first()

        action_point = TotalActionPoints.objects.all().filter(
            customer_id=self.customer.id
        ).first()

        self.assertIsNotNone(assignment)
        self.assertIsNotNone(total_point_history)
        self.assertIsNotNone(action_point)

        self.assertEqual(assignment.points_changed, 25) # it can be 25 because in setUp we gave mock_cfs_action_points static values
        self.assertEqual(total_point_history.new_point, total_point_history.old_point + assignment.points_changed)


    @patch('juloserver.cfs.models.CfsActionPoints.objects')
    def test_signal_tracking_account(self, mock): # frauster
        account_payment1 = AccountPaymentFactory(account=self.account, due_amount=5000)
        account_payment2 = AccountPaymentFactory(account=self.account, due_amount=5000)
        code = StatusLookupFactory(status_code=220)
        loan = LoanFactory(account=self.account, customer=self.customer,
                                loan_status=code, application=self.application)

        mock.get.return_value = self.mock_cfs_action_point

        history = AccountStatusHistory.objects.create(
            account=self.account, status_old=StatusLookupFactory(status_code=420),
            status_new=StatusLookupFactory(status_code=JuloOneCodes.APPLICATION_OR_FRIENDLY_FRAUD),
        )

        assignment = CfsActionPointsAssignment.objects.all().filter(
            customer_id=self.customer.id).order_by('cdate').last()
        total_point_history = TotalActionPointsHistory.objects.all().filter(
            customer_id=self.customer.id, cfs_action_point_assignment_id=assignment.id
        ).first()

        action_point = TotalActionPoints.objects.all().filter(
            customer_id=self.customer.id
        ).first()

        self.assertIsNotNone(assignment)
        self.assertIsNotNone(total_point_history)
        self.assertIsNotNone(action_point)

        self.assertEqual(assignment.extra_data['amount'], account_payment1.due_amount + account_payment2.due_amount)

    @patch('juloserver.cfs.models.CfsActionPoints.objects')
    def test_action_expired_script(self, mock):
        code = StatusLookupFactory(status_code=220)
        loan = LoanFactory(account=self.account, customer=self.customer,
                                loan_status=code, application=self.application, loan_amount=10000000)

        mock.get.return_value = self.mock_cfs_action_point

        x = LoanHistory.objects.create(loan=loan, status_old=212, status_new=LoanStatusCodes.CURRENT,
            change_reason=LoanStatusChangeReason.ACTIVATED)

        tracking_transaction_case_for_action_points(loan.id, CfsActionPointsActivity.TRANSACT)
        # tracking_repayment_case_for_action_points()
        action_point = TotalActionPoints.objects.all().filter(
            customer_id=self.customer.id
        ).first()
        self.assertEqual(action_point.point, 25)

        assignment1 = CfsActionPointsAssignment.objects.all().filter(
            customer_id=self.customer.id, loan_id=loan.id
        ).order_by('cdate').first()

        y = LoanHistory.objects.create(loan=loan, status_old=212, status_new=LoanStatusCodes.CURRENT,
            change_reason=LoanStatusChangeReason.ACTIVATED)
        tracking_transaction_case_for_action_points(loan.id, CfsActionPointsActivity.TRANSACT)
        action_point = TotalActionPoints.objects.all().filter(
            customer_id=self.customer.id
        ).first()

        self.assertEqual(action_point.point, 50)

        assignment2 = CfsActionPointsAssignment.objects.all().filter(
            customer_id=self.customer.id).order_by('cdate').last()

        assignment1.expiry_date = self.today - timedelta(days=1)
        assignment1.save()
        assignment2.expiry_date = self.today - timedelta(days=1)
        assignment2.save()

        check_cfs_action_expired()
        action_point = TotalActionPoints.objects.all().filter(
            customer=self.customer
        ).first()

        lastest_point = TotalActionPointsHistory.objects.all().filter(
            customer_id=self.customer.id
        ).order_by('cdate').last().new_point

        self.assertEquals(action_point.point, 0)
        self.assertEqual(action_point.point, lastest_point)

        assignment1.refresh_from_db()
        assignment2.refresh_from_db()
        self.assertEqual(assignment1.is_processed, True)
        self.assertEqual(assignment2.is_processed, True)


    @patch('juloserver.julo.signals.track_transact_for_action_points')
    @patch('juloserver.julo.signals.track_repayment_for_action_points')
    @patch('juloserver.account.signals.track_frausdster_for_action_points')
    def test_tracking_case_partners(self, mock_track_frauster, mock_track_payment, mock_track_loan):
        self.application.update_safely(
            partner=PartnerFactory(name='grab'),
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.GRAB)
        )

        # case loan
        code = StatusLookupFactory(status_code=220)
        loan = LoanFactory(account=self.account, customer=self.customer,
                                loan_status=code, application=self.application, loan_amount=10000000)

        x = LoanHistory.objects.create(loan=loan, status_old=212, status_new=LoanStatusCodes.CURRENT,
            change_reason=LoanStatusChangeReason.ACTIVATED)

        mock_track_loan.assert_not_called()

        # case payment
        payment = PaymentFactory(loan=loan, installment_principal=10000000)

        x = PaymentHistory.objects.create(
            paid_date=self.today, due_date=self.today - timedelta(days=2),
            loan=loan, payment=payment, due_amount=0, payment_new_status_code=PaymentStatusCodes.PAID_ON_TIME)

        mock_track_payment.assert_not_called()

        # case fraudster
        history = AccountStatusHistory.objects.create(
            account=self.account, status_old=StatusLookupFactory(status_code=420),
            status_new=StatusLookupFactory(status_code=JuloOneCodes.APPLICATION_OR_FRIENDLY_FRAUD),
        )
        mock_track_frauster.assert_not_called()

        # check if there's assignment row
        assignment = CfsActionPointsAssignment.objects.first()
        self.assertIsNone(assignment)
