import mock
from mock import patch, MagicMock

from datetime import timedelta, datetime

from django.utils import timezone
from django.test.testcases import TestCase

from juloserver.julo.tests.factories import *
from juloserver.loan_refinancing.tests.factories import *
from juloserver.julo.models import CootekRobocall, VendorDataHistory, ExperimentSetting
from .factories import *
from juloserver.cootek.constants import CriteriaChoices, DpdConditionChoices
from juloserver.account_payment.models import AccountPayment
from juloserver.account.tests.factories import (
    AccountFactory,
    AccountLookupFactory,
    AccountwithApplicationFactory,
    ExperimentGroupFactory,
)
from juloserver.account_payment.tests.factories import (
    AccountPaymentFactory,
    AccountPaymentwithPaymentFactory,
)
from juloserver.apiv2.models import PdCollectionModelResult
from juloserver.cootek.services import (
    get_payment_details_for_cootek_data,
    get_payment_details_for_intelix,
    get_j1_account_payment_for_cootek,
    get_payment_details_cootek_for_intelix,
    get_payment_details_cootek_for_centerix,
    upload_payment_details,
    update_cootek_data,
    excluding_risky_account_payment_dpd_minus,
    create_task_to_send_data_customer_to_cootek,
)
from juloserver.autodebet.tests.factories import AutodebetAccountFactory
from ...collection_vendor.tests.factories import SkiptraceHistoryFactory, SkipTraceFactory
from ...julo.constants import WorkflowConst
from ...minisquad.tests.factories import SentToDialerFactory
from juloserver.minisquad.constants import ExperimentConst as MinisquadExperimentConstants


class TestCootekServices(TestCase):

    def setUp(self):
        self.loan = LoanFactory(is_ignore_calls=False, id=200030)
        self.cootek_config_ = CootekConfigurationFactory(
            task_type='test3',
            strategy_name='testing_L00-L33',
            called_at=-1,
            loan_ids=['00-33'],
            product='mtl')
        self.task_details = {
            'TaskID': 5,
            'Status': 'pending',
            'detail': [{
                'Comments': 12345,
                'RingType': 'test',
                'Intention': 'test',
                'HangupType': 'test',
                'CallEndTime': '2020-01-17 16:00:00',
                'CallStartTime': '2020-01-17 16:30:00',
                'Status': 'pending',
                'RobotID': '3f53ac78e7fea695a164f55a6ff4de21'
            }]
        }

    @patch('juloserver.cootek.services.get_payment_details_for_cootek')
    @patch('juloserver.cootek.services.check_cootek_experiment')
    def test_get_payment_details_for_intelix_no_payment(
            self, mock_check_cootek_experiment,
            mock_get_payment_details_for_cootek):
        mock_check_cootek_experiment.return_value.criteria.return_value = {
            'dpd': [0, -1, -2],
            "loan_id": "#last:1:0,1,2,3,4,5,6,7,8,9"
        }
        mock_get_payment_details_for_cootek.return_value = []
        result = get_payment_details_for_intelix(-1, 'L00-L33')
        assert not result

    @patch('juloserver.cootek.services.get_payment_details_for_cootek')
    @patch('juloserver.cootek.services.check_cootek_experiment')
    def test_get_payment_details_for_intelix(
            self, mock_check_cootek_experiment,
            mock_get_payment_details_for_cootek):
        mock_check_cootek_experiment.return_value.criteria.return_value = {
            'dpd': [0, -1, -2],
            "loan_id": "#last:1:0,1,2,3,4,5,6,7,8,9"
        }
        mock_get_payment_details_for_cootek.return_value = self.loan.payment_set.all()
        result = get_payment_details_for_intelix(-1, 'L00-L33')
        assert result

    def test_get_j1_account_payment_for_cootek(self):
        account_payment_filter = {}
        result = get_j1_account_payment_for_cootek(account_payment_filter)

        assert not result

    def test_get_payment_details_cootek_for_intelix(self):
        dpd = 0
        loan_ids = [123444, 12344]
        payments, account_payments = get_payment_details_cootek_for_intelix(dpd, loan_ids)
        assert not payments
        assert not account_payments

    def test_get_payment_details_cootek_for_intelix_with_filter_autodebet(self):
        dpd = 0
        parameters = {
            "dpd_minus": False,
            "dpd_zero": True,
            "dpd_plus": False
        }
        FeatureSettingFactory(
            feature_name=FeatureNameConst.AUTODEBET_CUSTOMER_EXCLUDE_FROM_INTELIX_CALL,
            parameters=parameters,
            is_active=True
        )
        account = AccountwithApplicationFactory(id=1)
        account2 = AccountwithApplicationFactory(id=2)
        account_payment = AccountPaymentFactory(
            id=11,
            account=account,
        )
        account_payment2 = AccountPaymentFactory(
            id=12,
            account=account2
        )
        AutodebetAccountFactory(
            account = account,
            vendor = "BCA",
            is_use_autodebet = True,
            is_deleted_autodebet = False
        )
        CootekRobocallFactory(
            called_at=dpd,
            cdate=timezone.localtime(timezone.now()),
            call_status='calling',
            campaign_or_strategy='12344412344',
            intention='B',
            account_payment_id=account_payment.id
        )
        CootekRobocallFactory(
            called_at=dpd,
            cdate=timezone.localtime(timezone.now()),
            call_status='calling',
            campaign_or_strategy='12344412344',
            intention='B',
            account_payment_id=account_payment2.id
        )
        payments, account_payments, not_sent_payments, not_sent_account_payments = \
            get_payment_details_cootek_for_intelix(dpd=dpd, for_intelix=True)
        self.assertTrue(not payments)
        self.assertTrue(account_payment2 in account_payments)
        self.assertTrue(not not_sent_payments)
        self.assertEqual([
            {
                'reason': 'excluded due to autodebet',
                'id': 11
            }
        ], not_sent_account_payments)

    def test_get_payment_details_cootek_for_intelix_with_filter_due_amount(self):
        dpd = 0
        account = AccountwithApplicationFactory(id=1)
        account2 = AccountwithApplicationFactory(id=2)
        account_payment = AccountPaymentFactory(
            id=11,
            account=account,
            due_amount=0
        )
        account_payment2 = AccountPaymentFactory(
            id=12,
            account=account2
        )
        CootekRobocallFactory(
            called_at=dpd,
            cdate=timezone.localtime(timezone.now()),
            call_status='calling',
            campaign_or_strategy='12344412344',
            intention='B',
            account_payment_id=account_payment.id
        )
        CootekRobocallFactory(
            called_at=dpd,
            cdate=timezone.localtime(timezone.now()),
            call_status='calling',
            campaign_or_strategy='12344412344',
            intention='B',
            account_payment_id=account_payment2.id
        )
        payments, account_payments, not_sent_payments, not_sent_account_payments = \
            get_payment_details_cootek_for_intelix(dpd=dpd, for_intelix=True)
        self.assertTrue(not payments)
        self.assertTrue(account_payment2 in account_payments)
        self.assertTrue(not not_sent_payments)
        self.assertTrue(not not_sent_account_payments)

    def test_get_payment_details_cootek_for_intelix_when_data_robocall_empty(self):
        dpd = 0
        today = timezone.localtime(timezone.now()).date()
        self.workflow_j1 = WorkflowFactory(name='JuloOneWorkflow', handler='JuloOneWorkflowHandler')
        self.account_lookup_j1 = AccountLookupFactory(
            partner=None, workflow=self.workflow_j1, name='JULO1')
        account = AccountwithApplicationFactory(id=1, account_lookup=self.account_lookup_j1)
        account2 = AccountwithApplicationFactory(id=2, account_lookup=self.account_lookup_j1)
        account3 = AccountwithApplicationFactory(id=3, account_lookup=self.account_lookup_j1)
        account_payment = AccountPaymentFactory(
            id=11,
            account=account,
            due_amount=0,
            due_date=today
        )
        account_payment2 = AccountPaymentFactory(
            id=12,
            account=account2,
            due_date=today
        )
        account_payment3 = AccountPaymentFactory(
            id=13,
            account=account3,
            due_date=today
        )
        payments, account_payments, not_sent_payments, not_sent_account_payments = \
            get_payment_details_cootek_for_intelix(dpd=dpd, for_intelix=True)
        self.assertTrue(not payments)
        self.assertTrue(account_payment not in account_payments)
        self.assertTrue(
            account_payment2 in account_payments and account_payment3 in account_payments)
        self.assertTrue(not not_sent_payments)
        self.assertTrue(not not_sent_account_payments)

    def test_get_payment_details_cootek_for_centerix(self):
        dpd = 0
        result = get_payment_details_cootek_for_centerix(dpd)
        assert not result


    def test_upload_payment_details(self):
        result = upload_payment_details([], 'TEST')
        self.assertEqual(result, 'No data to upload to centerix')

    def update_cootek_data_case_1(self):
        update_cootek_data(
            self.task_details,
            None,
            True,
            False
        )

        cootek_robocall = CootekRobocall.objects.all()
        assert cootek_robocall.count() > 1

    def update_cootek_data_case_2(self):
        update_cootek_data(
            self.task_details,
            None,
            False,
            True
        )

        cootek_robocall = CootekRobocall.objects.all()
        assert cootek_robocall.count() > 1

    def update_cootek_data_case_3(self):
        update_cootek_data(
            self.task_details,
            CriteriaChoices.REFINANCING_PENDING,
            False,
            False
        )
        cootek_robocall = CootekRobocall.objects.all()
        assert cootek_robocall.count() > 1


class TestCootekExcludeIsRisky(TestCase):
    def setUp(self):
        self.account = AccountFactory()
        self.account_payment_1 = AccountPaymentFactory(id=1234, account=self.account)
        self.account_payment_2 = AccountPaymentFactory(id=1235, account=self.account)
        self.account_payments = [self.account_payment_1, self.account_payment_2]
        self.today = timezone.localtime(timezone.now()).date()

    def test_excluding_risky_account_payment_dpd_minus(self):
        account_payments = AccountPayment.objects.filter(account=self.account)
        excluded_payments = excluding_risky_account_payment_dpd_minus(account_payments)
        self.assertEqual(len(account_payments), len(excluded_payments))

        PdCollectionModelResult.objects.create(
            account_payment=self.account_payment_1,
            model_version='Now or Never v4',
            prediction_before_call=0.2977949614,
            prediction_after_call=0.1,
            due_amount=2266000,
            sort_rank=4,
            range_from_due_date=-1,
            account=self.account,
            prediction_date=self.today,
        )
        self.account_payment_1.due_date = self.today + timedelta(days=1)
        self.account_payment_1.save()
        print(self.account_payment_1.due_date)
        excluded_payments = excluding_risky_account_payment_dpd_minus(account_payments)
        self.assertNotEqual(len(account_payments), len(excluded_payments))


class TestCootekLateDPD(TestCase):
    def setUp(self):
        self.today = timezone.localtime(timezone.now())
        self.cootek_record = CootekConfigurationFactory(
            task_type='test_late_dpd',
            strategy_name='test_late_dpd_afternoon',
            called_at=1,
            called_to=4,
            number_of_attempts=3,
            time_to_start='12:00:00',
            is_active=True,
            dpd_condition=DpdConditionChoices.RANGE,
            criteria=CriteriaChoices.UNCONNECTED_LATE_DPD,
            time_to_prepare='11:50',
            product='J1',
        )
        feature_setting = FeatureSettingFactory(
            feature_name=FeatureNameConst.COOTEK_LATE_DPD_SETTING,
            is_active=True,
            parameters={
                'evening': 120,
                'afternoon': 60,
                'skiptrace_minimum_time_evening': '13:10',
            }
        )

    @patch('juloserver.cootek.services.get_julo_cootek_client')
    def test_create_cootek_task_for_late_dpd(self, mocking_cootek_client):
        workflow = WorkflowFactory(name=WorkflowConst.JULO_ONE)
        account_lookup = AccountLookupFactory(workflow=workflow)
        account = AccountFactory(id=1000, account_lookup=account_lookup)
        account2 = AccountFactory(id=1001, account_lookup=account_lookup)
        account_payment_1 = AccountPaymentFactory(
            id=12355, account=account, due_date=self.today.date() - relativedelta(days=2)
        )
        account_payment_2 = AccountPaymentFactory(
            id=12366, account=account2, due_date=self.today.date() - relativedelta(days=3)
        )
        application = ApplicationFactory(
            account=account, workflow=WorkflowFactory(name=WorkflowConst.JULO_ONE)
        )
        application2 = ApplicationFactory(
            account=account2, workflow=WorkflowFactory(name=WorkflowConst.JULO_ONE)
        )
        loan1 = LoanFactory(account=account, application=application)
        PaymentFactory(loan=loan1)
        payment = loan1.payment_set.first()
        payment.due_date = account_payment_1.due_date
        payment.account_payment = account_payment_1
        payment.save()

        loan2 = LoanFactory(account=account, application=application2)
        PaymentFactory(loan=loan2)
        payment2 = loan2.payment_set.first()
        payment2.due_date = account_payment_2.due_date
        payment2.account_payment = account_payment_2
        payment2.save()

        call_result = SkiptraceResultChoiceFactory(name="test_uncalled")
        skiptrace = SkipTraceFactory(
            application=None, customer=account.customer)
        sk1 = SkiptraceHistoryFactory(
            account=account, skiptrace=skiptrace,
            account_payment=account_payment_1,
            call_result=call_result,
            loan=None, application=None, payment=None, agent=None
        )
        sk1.call_result = call_result
        sk1.cdate = timezone.localtime(timezone.now()).replace(
            hour=10, minute=50, second=00, microsecond=00)
        sk1.save()
        std = SentToDialerFactory(
            account=account2,
            account_payment=account_payment_2
        )
        std.cdate = timezone.localtime(timezone.now()).replace(
            hour=6, minute=50, second=00, microsecond=00)
        std.save()
        mocking_cootek_client.return_value.create_task.return_value = 'unit_test_task'
        create_task_to_send_data_customer_to_cootek(
            self.cootek_record, start_time=self.today + relativedelta(hours=1)
        )
        created_robocall_count = CootekRobocall.objects.filter(
            account_payment_id__in=(account_payment_1.id, account_payment_2.id)
        ).count()
        self.assertEqual(created_robocall_count, 1)


class TestPaymentDetailForCootek(TestCase):
    def setUp(self):
        time = timezone.localtime(timezone.now())
        self.product_line_j1 = ProductLineFactory(product_line_code=1, product_line_type='J1')
        self.cootek_configuration_initial = CootekConfigurationFactory(
            task_type='JULO_T-3',
            strategy_name='J1 T-3',
            called_at=-3,
            number_of_attempts=3,
            time_to_prepare=time.replace(hour=10, minute=0),
            time_to_start=time.replace(hour=10, minute=10),
            time_to_query_result=time.replace(hour=11, minute=0),
            is_active=True,
            dpd_condition=DpdConditionChoices.EXACTLY,
            product='J1',
            from_previous_cootek_result=False,
            exclude_autodebet=True,
            tag_status='{C}'
        )
        self.cootek_configuration_later = CootekConfigurationFactory(
            task_type='JULO_T-3',
            strategy_name='J1 T-3',
            called_at=-3,
            number_of_attempts=3,
            time_to_prepare=time.replace(hour=11, minute=50),
            time_to_start=time.replace(hour=12, minute=0),
            time_to_query_result=time.replace(hour=13, minute=0),
            is_active=True,
            dpd_condition=DpdConditionChoices.EXACTLY,
            product='J1',
            from_previous_cootek_result=True,
            exclude_autodebet=True,
            tag_status='{C,F}'
        )
        self.cootek_configuration_no_autodebet = CootekConfigurationFactory(
            task_type='JULO_T0',
            strategy_name='J1 T0',
            called_at=0,
            number_of_attempts=3,
            time_to_prepare=time.replace(hour=9, minute=0),
            time_to_start=time.replace(hour=9, minute=10),
            time_to_query_result=time.replace(hour=10, minute=0),
            is_active=True,
            dpd_condition=DpdConditionChoices.EXACTLY,
            product='J1',
            from_previous_cootek_result=False,
            exclude_autodebet=False,
            tag_status='{C}'
        )
        self.cootek_late_fee_experiment = CootekConfigurationFactory(
            task_type='JULO_T0_LATE_FEE_EXPERIMENT',
            strategy_name='J1 T0 LATE FEE EXPERIMENT',
            called_at=0,
            number_of_attempts=3,
            time_to_prepare=time.replace(hour=9, minute=0),
            time_to_start=time.replace(hour=9, minute=10),
            time_to_query_result=time.replace(hour=10, minute=0),
            is_active=True,
            dpd_condition=DpdConditionChoices.EXACTLY,
            product='J1',
            from_previous_cootek_result=False,
            exclude_autodebet=False,
            tag_status='{C}',
        )
        self.workflow_j1 = WorkflowFactory(name='JuloOneWorkflow', handler='JuloOneWorkflowHandler')
        self.account_lookup_j1 = AccountLookupFactory(
            partner=None, workflow=self.workflow_j1, name='JULO1')
        for index in range(4):
            account = AccountwithApplicationFactory(account_lookup=self.account_lookup_j1)

            if index > 0:
                AutodebetAccountFactory(account=account, is_use_autodebet=True)
            else:
                AutodebetAccountFactory(account=account, is_use_autodebet=False)

            AccountPaymentwithPaymentFactory(
                account=account, is_robocall_active=True, due_date='2022-05-10')

        applications = Application.objects.all()
        for index, application in enumerate(applications):
            application.product_line = self.product_line_j1
            application.save()

        self.account_experiment = AccountFactory.create_batch(2, account_lookup=self.account_lookup_j1)
        self.applications_experiment = ApplicationJ1Factory.create_batch(
            2,
            account=Iterator(self.account_experiment),
            mobile_phone_1=Iterator(['081234567890', '081234567899'])
        )
        AccountPaymentwithPaymentFactory.create_batch(
            2,
            due_amount=10000,
            account=Iterator([application.account for application in self.applications_experiment]),
            due_date=timezone.localtime(timezone.now()).date()
        )
        self.late_fee_experiment = ExperimentSettingFactory(
            is_active=True,
            code=MinisquadExperimentConstants.LATE_FEE_EARLIER_EXPERIMENT,
            criteria={
                "url": "http://localhost:8000",
                "account_id_tail": {"control": [0, 1, 2, 3, 4], "experiment": [5, 6, 7, 8, 9]}
            },
        )
        self.payment_filter = {
            'due_date': timezone.localtime(timezone.now())
        }
        ExperimentGroupFactory(account=self.account_experiment[0], group='experiment',
                               experiment_setting=self.late_fee_experiment)

    @patch('juloserver.cootek.services.get_experiment_setting_data_on_growthbook')    
    def test_get_payment_details_cootek_for_j1_not_late_dpd_exclude_autodebet(self, mock_experiment_setting):
        mock_experiment_setting.return_value = None

        account_payments = get_payment_details_for_cootek_data(
            self.cootek_configuration_initial,
            None,
            {'due_date': timezone.localtime(timezone.now()).replace(
                year=2022, month=5, day=10)}
        )

        self.assertEqual(1, len(account_payments))

    @patch('juloserver.cootek.services.get_experiment_setting_data_on_growthbook')
    @patch('juloserver.cootek.services.get_payment_with_specific_intention_from_cootek',
           return_value=[[2], [1]])
    def test_get_payment_details_cootek_for_j1_from_previous_cootek_result_exclude_autodebet(
            self, mock_get_payment_specific_intention, mock_experiment_setting):
        mock_experiment_setting.return_value = None
        get_payment_details_for_cootek_data(
            self.cootek_configuration_initial,
            None,
            {'due_date': timezone.localtime(timezone.now()).replace(
                year=2022, month=5, day=10)}
        )
        account_payments = get_payment_details_for_cootek_data(
            self.cootek_configuration_later,
            None,
            {'due_date': timezone.localtime(timezone.now()).replace(
                year=2022, month=5, day=10)}
        )

        self.assertTrue(mock_get_payment_specific_intention.called)
        self.assertEqual(1, mock_get_payment_specific_intention.call_count)
        self.assertEqual(1, len(account_payments))

    @patch('juloserver.cootek.services.get_experiment_setting_data_on_growthbook')
    def test_get_payment_details_cootek_for_j1_exclude_autodebet_false(self, mock_experiment_setting):
        mock_experiment_setting.return_value = None
        account_payments = get_payment_details_for_cootek_data(
            self.cootek_configuration_no_autodebet,
            None,
            {'due_date': timezone.localtime(timezone.now()).replace(
                year=2022, month=5, day=10)}
        )

        self.assertEqual(4, len(account_payments))

    @patch('juloserver.cootek.services.get_j1_turbo_late_dpd_account_payment_for_cootek')
    def test_get_payment_details_cootek_for_j1_is_unconnected_late_dpd(
        self,
        mock_get_j1_turbo_late_dpd_account_payment_for_cootek
    ):
        time = timezone.localtime(timezone.now())
        cootek_config = CootekConfigurationFactory(
            task_type='JULO_T0',
            strategy_name='J1 T0',
            called_at=0,
            number_of_attempts=3,
            time_to_prepare=time.replace(hour=9, minute=0),
            time_to_start=time.replace(hour=9, minute=10),
            time_to_query_result=time.replace(hour=10, minute=0),
            is_active=True,
            dpd_condition=DpdConditionChoices.EXACTLY,
            product='J1',
            from_previous_cootek_result=False,
            exclude_autodebet=False,
            tag_status='{C}',
            criteria=CriteriaChoices.UNCONNECTED_LATE_DPD
        )
        applications = ApplicationJ1Factory.create_batch(
            2,
            account=Iterator(
                AccountFactory.create_batch(
                    2,
                    customer=Iterator(
                        CustomerFactory.create_batch(2, phone=Iterator(['081234567890', None]))
                    ),
                )
            ),
            mobile_phone_1=Iterator(['081234567890', None])
        )
        account_payments = AccountPaymentwithPaymentFactory.create_batch(
            2,
            due_amount=10000,
            account=Iterator([application.account for application in applications])
        )
        mock_get_j1_turbo_late_dpd_account_payment_for_cootek.return_value = [
            SentToDialerFactory(account_payment=account_payments[0]),
            SentToDialerFactory(account_payment=account_payments[1]),
        ]
        ret_val = get_payment_details_for_cootek_data(
            cootek_config,
            None,
            {'due_date': timezone.localtime(timezone.now()).replace(
                year=2022, month=5, day=10
            )}
        )

        self.assertEqual(1, len(ret_val))
        self.assertEqual(account_payments[0].id, ret_val[0]['Comments'])

    def test_unhandled_cootek_configuration(self):
        time = timezone.localtime(timezone.now())
        cootek_config = CootekConfigurationFactory(
            task_type='JULO_T0',
            strategy_name='J1 T0',
            called_at=0,
            number_of_attempts=3,
            time_to_prepare=time.replace(hour=9, minute=0),
            time_to_start=time.replace(hour=9, minute=10),
            time_to_query_result=time.replace(hour=10, minute=0),
            is_active=True,
            dpd_condition=DpdConditionChoices.EXACTLY,
            product='product',
            from_previous_cootek_result=False,
            exclude_autodebet=False,
            tag_status='{C}',
            criteria=CriteriaChoices.UNCONNECTED_LATE_DPD
        )
        with self.assertRaises(Exception) as context:
            get_payment_details_for_cootek_data(cootek_config, None, None)

        self.assertEquals('Unhandled cootek configuration configuration', str(context.exception))

    @patch('juloserver.cootek.services.get_experiment_setting_data_on_growthbook')
    def test_active_and_is_cootek_config_late_fee_experiment_earlier(self, mock_experiment_setting):
        # handle late fee earlier experiment active
        # and cootek configuration for late fee experiment
        self.cootek_late_fee_experiment.criteria = CriteriaChoices.LATE_FEE_EARLIER_EXPERIMENT
        self.cootek_late_fee_experiment.save()
        self.late_fee_experiment.is_permanent = True
        self.late_fee_experiment.save()
        mock_experiment_setting.return_value = None

        result = get_payment_details_for_cootek_data(
            self.cootek_late_fee_experiment, None, self.payment_filter)
        account_payment = AccountPayment.objects.filter(account=self.account_experiment[0]).last()
        self.assertEqual(1, len(result))
        self.assertEqual(account_payment.id, result[0]['Comments'])

    @patch('juloserver.cootek.services.get_experiment_setting_data_on_growthbook')
    def test_active_and_is_not_cootek_config_late_fee_experiment_earlier(self, mock_experiment_setting):
        # handle late fee earlier experiment active
        # and cootek configuration not for late fee experiment
        self.cootek_late_fee_experiment.criteria = None
        self.cootek_late_fee_experiment.save()
        self.late_fee_experiment.is_permanent = True
        self.late_fee_experiment.save()
        mock_experiment_setting.return_value = None
        result = get_payment_details_for_cootek_data(
            self.cootek_late_fee_experiment, None, self.payment_filter)
        account_payment = AccountPayment.objects.filter(account=self.account_experiment[1]).last()
        self.assertEqual(1, len(result))
        self.assertEqual(account_payment.id, result[0]['Comments'])

    @patch('juloserver.cootek.services.get_experiment_setting_data_on_growthbook')
    def test_not_active_and_is_cootek_config_late_fee_experiment_earlier(self, mock_experiment_setting):
        # handle late fee earlier experiment inactive
        # and cootek configuration for late fee experiment
        self.cootek_late_fee_experiment.criteria = CriteriaChoices.LATE_FEE_EARLIER_EXPERIMENT
        self.cootek_late_fee_experiment.save()
        self.late_fee_experiment.is_active = False
        self.late_fee_experiment.save()
        mock_experiment_setting.return_value = None

        result = get_payment_details_for_cootek_data(
            self.cootek_late_fee_experiment, None, self.payment_filter)
        self.assertEqual(0, len(result))

    @patch('juloserver.cootek.services.get_experiment_setting_data_on_growthbook')
    def test_not_active_and_is_not_cootek_config_late_fee_experiment_earlier(self, mock_experiment_setting):
        mock_experiment_setting.return_value = None
        # handle late fee earlier experiment inactive
        # and cootek configuration not for late fee experiment
        self.cootek_late_fee_experiment.criteria = None
        self.cootek_late_fee_experiment.save()
        self.late_fee_experiment.is_active = False
        self.late_fee_experiment.save()

        result = get_payment_details_for_cootek_data(
            self.cootek_late_fee_experiment, None, self.payment_filter)
        self.assertEqual(2, len(result))
