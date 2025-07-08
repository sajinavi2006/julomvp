from freezegun import freeze_time
from datetime import datetime, timedelta
from django.utils import timezone
from mock import MagicMock, patch
from rest_framework.test import APIClient
from juloserver.julo.tests.factories import (
    ApplicationFactory,
    AuthUserFactory,
    CustomerFactory,
    FeatureSettingFactory,
    StatusLookupFactory,
    GroupFactory,
    FDCInquiryFactory,
    PartnerFactory,
    FDCInquiryLoanFactory,
    LoanFactory,
    WorkflowFactory,
    ProductLookupFactory,
    FDCActiveLoanCheckingFactory,
    ProductLineFactory,
    BlacklistCustomerFactory
)
from juloserver.account.tests.factories import (
    AccountFactory,
    AccountLimitFactory
)
from juloserver.julo.statuses import ApplicationStatusCodes
from django.test import TestCase
from juloserver.fdc.constants import FDCFileSIKConst, FDCLoanStatus
from juloserver.julo.models import (
    FDCInquiryLoan,
    FDCInquiry,
    FDCActiveLoanChecking,
    FeatureSetting,
    ProductLineCodes,
    Customer,
    WorkflowStatusPath
)
from juloserver.grab.services.fdc import get_fdc_inquiry_data
from juloserver.loan.services.loan_related import (
    get_info_active_loan_from_platforms,
    get_parameters_fs_check_other_active_platforms_using_fdc,
    is_apply_check_other_active_platforms_using_fdc,
    get_fdc_loan_active_checking_for_daily_checker,
)
from dateutil.relativedelta import relativedelta
from juloserver.julo.constants import FeatureNameConst, WorkflowConst
from juloserver.grab.services.loan_related import (
    is_dax_eligible_other_active_platforms,
    create_fdc_inquiry_and_execute_check_active_loans_for_grab
)
from juloserver.ana_api.tests.factories import FDCPlatformCheckBypassFactory
from juloserver.account.constants import AccountConstant
from juloserver.loan.tasks.lender_related import (
    fdc_inquiry_for_active_loan_from_platform_daily_checker_subtask,
    fdc_inquiry_for_active_loan_from_platform_daily_checker_task,
    fdc_inquiry_other_active_loans_from_platforms_task
)
from juloserver.grab.tasks import (
    grab_fdc_inquiry_for_active_loan_from_platform_daily_checker_task,
    grab_app_stuck_150_handler_task,
    grab_app_stuck_150_handler_subtask
)
from juloserver.loan.constants import FDCUpdateTypes
from django.test.utils import override_settings


class TestFDCActiveLoanChecking(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        token = self.user.auth_expiry_token.key
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + token)
        self.customer = CustomerFactory()
        self.fdc_inquiry_data = {'application_xid': 1002931231, 'nik_spouse': '12345678910'}
        self.partner = PartnerFactory(user=self.user)
        self.status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.FORM_PARTIAL,
        )
        self.application = ApplicationFactory(
            application_xid=self.fdc_inquiry_data['application_xid'],
            customer=self.customer,
            status=self.status,
            partner=self.partner,
        )
        self.inquiry_2 = FDCInquiryFactory(
            application_id=self.application.id, inquiry_status='success'
        )
        self.nearest_due_date = datetime(2023, 12, 21).date()
        self.nearest_due_date_2 = datetime(2023, 12, 22).date()
        FDCInquiryLoanFactory.create_batch(
            2,
            fdc_inquiry_id=self.inquiry_2.id,
            is_julo_loan=None,
            id_penyelenggara=1,
            dpd_terakhir=1,
            status_pinjaman=FDCLoanStatus.OUTSTANDING,
            tgl_jatuh_tempo_pinjaman=datetime(2023, 12, 30),
        )
        FDCInquiryLoanFactory.create_batch(
            2,
            fdc_inquiry_id=self.inquiry_2.id,
            is_julo_loan=None,
            id_penyelenggara=2,
            dpd_terakhir=1,
            status_pinjaman=FDCLoanStatus.OUTSTANDING,
            tgl_jatuh_tempo_pinjaman=self.nearest_due_date_2,
        )
        self.list_fdc_3 = FDCInquiryLoanFactory.create_batch(
            2,
            fdc_inquiry_id=self.inquiry_2.id,
            is_julo_loan=None,
            id_penyelenggara=3,
            dpd_terakhir=1,
            status_pinjaman=FDCLoanStatus.OUTSTANDING,
            tgl_jatuh_tempo_pinjaman=self.nearest_due_date,
        )

        FDCInquiryLoanFactory.create_batch(
            2,
            fdc_inquiry_id=self.inquiry_2.id,
            is_julo_loan=None,
            id_penyelenggara=4,
            dpd_terakhir=1,
            status_pinjaman=FDCLoanStatus.FULLY_PAID,
            tgl_jatuh_tempo_pinjaman=datetime(2023, 12, 15),
        )

    def test_check_active_loans_with_n_platform_not_is_eligible(self):
        number_platforms = 3
        day_diff = 2
        inquiry_dict = get_fdc_inquiry_data(self.application.pk, day_diff)
        inquiry = inquiry_dict.get('fdc_inquiry')
        (
            nearest_due_date,
            count_platforms,
            count_active_loans,
        ) = get_info_active_loan_from_platforms(inquiry.pk)

        assert count_platforms == 3
        assert count_active_loans == 6
        assert nearest_due_date == self.nearest_due_date

    @patch('juloserver.fdc.services.timezone.now')
    def test_check_active_loans_with_n_platform_with_out_date(self, mock_time_zone):
        day_diff = 2
        mock_time_zone.return_value = self.inquiry_2.cdate + relativedelta(days=day_diff + 1)
        inquiry_dict = get_fdc_inquiry_data(self.application.pk, day_diff)
        inquiry = inquiry_dict.get('fdc_inquiry')
        self.assertTrue(inquiry_dict.get('is_out_date'), True)
        assert inquiry == None

    def test_check_active_loans_with_n_platform_with_is_eligible(self):
        number_platforms = 3
        day_diff = 2
        list_ids_fdc_3 = [fdc.pk for fdc in self.list_fdc_3]
        FDCInquiryLoan.objects.filter(pk__in=list_ids_fdc_3).update(
            status_pinjaman=FDCLoanStatus.FULLY_PAID
        )
        inquiry_dict = get_fdc_inquiry_data(self.application.pk, day_diff)
        inquiry = inquiry_dict.get('fdc_inquiry')
        (
            nearest_due_date,
            count_platforms,
            count_active_loans,
        ) = get_info_active_loan_from_platforms(inquiry.pk)

        assert count_platforms == 2
        assert count_active_loans == 4
        assert nearest_due_date == self.nearest_due_date_2

    def test_get_fdc_inquiry_data_pending_fdc(self):
        day_diff = 2
        FDCInquiry.objects.filter(application_id=self.application.id).\
            update(inquiry_status='pending')
        inquiry_dict = get_fdc_inquiry_data(self.application.pk, day_diff)
        self.assertTrue(inquiry_dict.get('is_pending'))

    def test_get_fdc_inquiry_data_error_fdc(self):
        day_diff = 2
        FDCInquiry.objects.filter(application_id=self.application.id).\
            update(inquiry_status='error')
        inquiry_dict = get_fdc_inquiry_data(self.application.pk, day_diff)
        self.assertFalse(inquiry_dict.get('is_pending'))


class TestCheckActiveLoansUsingFdcFunction(TestCase):
    def setUp(self):
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user_auth)
        self.application = ApplicationFactory(customer=self.customer)
        self.customer_segment = 'activeus_a'
        self.product_lookup = ProductLookupFactory()

        self.fs = FeatureSettingFactory(
            feature_name=FeatureNameConst.GRAB_3_MAX_CREDITORS_CHECK,
            parameters={
                "number_of_allowed_active_loans": 3,
                "number_of_allowed_platforms": 3,
                "whitelist": {
                    "is_active": False,
                    "list_application_id": [],
                },
                "bypass": {
                    "is_active": False,
                    "list_application_id": [],
                },
                "ineligible_message_for_old_application": "ineligible_message_for_old_application",
                "popup": {},
                "ineligible_alert_after_fdc_checking": {},
            },
            is_active=False,
        )

    def test_get_parameters_fs_check_other_active_platforms_using_fdc(self):
        # INACTIVE FS
        # => False
        self.fs.is_active = False
        self.fs.save()
        FeatureSetting.objects.filter(feature_name=FeatureNameConst.GRAB_3_MAX_CREDITORS_CHECK).\
            update(is_active=False)
        result = get_parameters_fs_check_other_active_platforms_using_fdc(
            feature_name=FeatureNameConst.GRAB_3_MAX_CREDITORS_CHECK
        )
        self.assertEqual(result, None)

        # ACTIVE FS
        self.fs.is_active = True
        self.fs.save()
        result = get_parameters_fs_check_other_active_platforms_using_fdc(
            feature_name=FeatureNameConst.GRAB_3_MAX_CREDITORS_CHECK
        )
        self.assertIsNotNone(result)


    def test_is_apply_check_other_active_platforms_using_fdc(self):
        # INACTIVE FS
        # => False
        self.fs.is_active = False
        self.fs.save()
        result = is_apply_check_other_active_platforms_using_fdc(self.application.id, None)
        self.assertEqual(result, False)

        # ACTIVE FS
        self.fs.is_active = True

        # enable whitelist, but the application is not in the whitelist
        # => False
        self.fs.parameters['whitelist']['is_active'] = True
        self.fs.parameters['whitelist']['list_application_id'] = []
        self.fs.save()
        result = is_apply_check_other_active_platforms_using_fdc(self.application.id, self.fs.parameters)
        self.assertEqual(result, False)

        # enable whitelist, and the application is in the whitelist
        # => True
        self.fs.parameters['whitelist']['list_application_id'] = [self.application.id]
        self.fs.save()
        result = is_apply_check_other_active_platforms_using_fdc(self.application.id, self.fs.parameters)
        self.assertEqual(result, True)

        # disable whitelist, disable bypass
        # => True
        self.fs.parameters['bypass']['is_active'] = False
        self.fs.save()
        result = is_apply_check_other_active_platforms_using_fdc(self.application.id, self.fs.parameters)
        self.assertEqual(result, True)

    @patch('juloserver.grab.services.loan_related.get_fdc_inquiry_data')
    @patch('juloserver.grab.services.loan_related.get_info_active_loan_from_platforms')
    def test_is_eligible_other_active_platforms(
        self, mock_get_info_active_loan_from_platforms, mock_get_fdc_inquiry_data
    ):
        # have active loans on Julo -> True
        loan = LoanFactory(customer=self.customer, loan_status=StatusLookupFactory(status_code=220))
        is_eligible_dict = is_dax_eligible_other_active_platforms(
            application_id=self.application.id,
            fdc_data_outdated_threshold_days=1,
            number_of_allowed_platforms=3,
        )
        self.assertEqual(is_eligible_dict.get('is_eligible'), True)
        self.assertEqual(
            FDCActiveLoanChecking.objects.filter(customer_id=self.application.customer_id).count(),
            1,
        )
        fdc_active_loan_checking = FDCActiveLoanChecking.objects.get(
            customer_id=self.application.customer_id
        )
        self.assertEqual(
            fdc_active_loan_checking.last_access_date, timezone.localtime(timezone.now()).date()
        )
        self.assertEqual(fdc_active_loan_checking.number_of_other_platforms, None)
        fdc_active_loan_checking.last_access_date = (
            timezone.localtime(timezone.now()).date() - timedelta(days=2)
        )
        fdc_active_loan_checking.save()
        loan.loan_status = StatusLookupFactory(status_code=216)
        loan.save()

        mock_get_fdc_inquiry_data.return_value = {
            'fdc_inquiry': None,
            'is_out_date': False
        }

        # not exists FDCInquiry not outdated data -> True
        is_eligible_dict = is_dax_eligible_other_active_platforms(
            application_id=self.application.id,
            fdc_data_outdated_threshold_days=1,
            number_of_allowed_platforms=3,
        )
        self.assertEqual(is_eligible_dict.get("is_eligible"), True)
        self.assertEqual(
            FDCActiveLoanChecking.objects.filter(customer_id=self.application.customer_id).count(),
            1,
        )
        fdc_active_loan_checking.refresh_from_db()
        # already exist, but last_access_date is not today -> update last_access_date to today
        self.assertEqual(
            fdc_active_loan_checking.last_access_date, timezone.localtime(timezone.now()).date()
        )
        self.assertEqual(fdc_active_loan_checking.number_of_other_platforms, None)

        # exists FDCInquiry not outdated data
        mock_get_fdc_inquiry_data.return_value = {
            'fdc_inquiry': FDCInquiry(),
            'is_out_date': False
        }

        # number current other platforms = 2 -> True
        mock_get_info_active_loan_from_platforms.return_value = (timezone.now(), 2, 2)
        is_eligible_dict = is_dax_eligible_other_active_platforms(
            application_id=self.application.id,
            fdc_data_outdated_threshold_days=1,
            number_of_allowed_platforms=3,
        )
        self.assertEqual(is_eligible_dict.get("is_eligible"), True)
        self.assertEqual(
            FDCActiveLoanChecking.objects.filter(customer_id=self.application.customer_id).count(),
            1,
        )
        fdc_active_loan_checking.refresh_from_db()

        # number_of_other_platforms already updated
        self.assertIsNotNone(fdc_active_loan_checking.nearest_due_date)
        self.assertEqual(fdc_active_loan_checking.number_of_other_platforms, 2)

        # 3 other platforms + Julo = 4 platforms > 3 allowed platforms
        mock_get_info_active_loan_from_platforms.return_value = (timezone.now(), 3, 1)
        is_eligible_dict = is_dax_eligible_other_active_platforms(
            application_id=self.application.id,
            fdc_data_outdated_threshold_days=1,
            number_of_allowed_platforms=3,
        )
        self.assertEqual(is_eligible_dict.get("is_eligible"), False)
        self.assertEqual(
            FDCActiveLoanChecking.objects.filter(customer_id=self.application.customer_id).count(),
            1,
        )
        fdc_active_loan_checking.refresh_from_db()
        # number_of_other_platforms already updated
        self.assertNotEqual(fdc_active_loan_checking.last_updated_time, None)
        self.assertNotEqual(fdc_active_loan_checking.nearest_due_date, None)
        self.assertEqual(fdc_active_loan_checking.number_of_other_platforms, 3)

    def test_dax_max_creditors_already_have_loans(self):
        pass


class TestFDCActiveLoanDailyChecker(TestCase):
    def setUp(self):
        self.fs = FeatureSettingFactory(
            feature_name=FeatureNameConst.CHECK_OTHER_ACTIVE_PLATFORMS_USING_FDC,
            parameters={
                "fdc_data_outdated_threshold_days": 3,
                "number_of_allowed_platforms": 3,
                "fdc_inquiry_api_config": {
                    "max_retries": 3,
                    "retry_interval_seconds": 30
                },
                "whitelist": {
                    "is_active": True,
                    "list_application_id": [],
                },
                "daily_checker_config": {
                    "rps_throttling": 3,
                    "nearest_due_date_from_days": 5,
                    "batch_size": 1000,
                    "last_access_days": 7,
                    "retry_per_days": 1
                }
            },
            is_active=True,
        )

        self.grab_fs = FeatureSettingFactory(
            feature_name=FeatureNameConst.GRAB_3_MAX_CREDITORS_CHECK,
            parameters={
                "fdc_data_outdated_threshold_days": 3,
                "number_of_allowed_platforms": 3,
                "fdc_inquiry_api_config": {
                    "max_retries": 3,
                    "retry_interval_seconds": 30
                },
                "whitelist": {
                    "is_active": True,
                    "list_application_id": [],
                },
                "daily_checker_config": {
                    "rps_throttling": 3,
                    "nearest_due_date_from_days": 5,
                    "batch_size": 1000,
                    "last_access_days": 7,
                    "retry_per_days": 1
                }
            },
            is_active=True,
        )

        FDCActiveLoanCheckingFactory.create_batch(
            5, number_of_other_platforms=4
        )
        self.customer = CustomerFactory(nik='123321123321')
        self.customer_segment = 'activeus_a'
        self.active_status_code = StatusLookupFactory(status_code=AccountConstant.STATUS_CODE.active)
        self.account = AccountFactory(
            customer=self.customer,
            status=self.active_status_code
        )
        self.workflow = WorkflowFactory(name=WorkflowConst.JULO_ONE)
        self.product_line = ProductLineFactory(product_line_code=ProductLineCodes.J1)
        self.application = ApplicationFactory(
            customer=self.account.customer,
            account=self.account,
            mobile_phone_1='0123456788',
            workflow=self.workflow,
            product_line=self.product_line,
        )
        self.application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.LOC_APPROVED
        )
        AccountLimitFactory(account=self.account, available_limit=1000000)
        self.application.save()
        self.fdc_inquiry = FDCInquiryFactory(
            application_id=self.application.id, inquiry_status='success'
        )
        self.nearest_due_date = datetime(2024, 1, 15).date()
        self.fdc_inquiry = FDCInquiry.objects.create(
            nik=self.customer.nik, customer_id=self.customer.pk, application_id=self.application.pk
        )
        FDCInquiryLoanFactory.create_batch(
            2,
            fdc_inquiry_id=self.fdc_inquiry.id,
            is_julo_loan=None,
            id_penyelenggara=2,
            dpd_terakhir=1,
            status_pinjaman=FDCLoanStatus.OUTSTANDING,
            tgl_jatuh_tempo_pinjaman=self.nearest_due_date,
        )
        self.list_fdc_3 = FDCInquiryLoanFactory.create_batch(
            2,
            fdc_inquiry_id=self.fdc_inquiry.id,
            is_julo_loan=None,
            id_penyelenggara=3,
            dpd_terakhir=1,
            status_pinjaman=FDCLoanStatus.OUTSTANDING,
            tgl_jatuh_tempo_pinjaman=datetime(2024, 2, 1),
        )

    def test_get_fdc_loan_active_checking_for_daily_checker(self):
        current_time = datetime(2024, 1, 10, 15)
        FDCActiveLoanChecking.objects.all().update(
            last_access_date=current_time.date(),
            last_updated_time=current_time - relativedelta(days=1),
            nearest_due_date=current_time
        )
        total_customer_ids = FDCActiveLoanChecking.objects.all().values_list('customer_id', flat=True)

        # 1 last_access_days
        # 1.1 Get all match condition from config
        customer_ids = get_fdc_loan_active_checking_for_daily_checker(
            self.fs.parameters, current_time
        )
        assert len(total_customer_ids) == len(customer_ids)

        # 1.2 Two records > the config
        time_last_access_days = current_time - relativedelta(days=self.fs.parameters['daily_checker_config']['last_access_days'] + 1)
        total_exclude = 2

        # 2. last_updated_time
        FDCActiveLoanChecking.objects.all().update(
            last_access_date=current_time.date(),
            last_updated_time=current_time - relativedelta(
                days=self.fs.parameters['daily_checker_config']['retry_per_days']),
            nearest_due_date=current_time
        )
        # 2.1 Get all match condition from config
        customer_ids = get_fdc_loan_active_checking_for_daily_checker(
            self.fs.parameters, current_time
        )
        assert len(total_customer_ids) == len(customer_ids)

        # 2.2 exclude last_updated_time of Two records < the config (1) or null
        total_exclude = 2
        for fdc_active in FDCActiveLoanChecking.objects.filter()[:total_exclude]:
            fdc_active.update_safely(last_updated_time=current_time)
        customer_ids = get_fdc_loan_active_checking_for_daily_checker(
            self.fs.parameters, current_time
        )
        # 2.2.2 None case
        assert len(total_customer_ids) - total_exclude == len(customer_ids)
        FDCActiveLoanChecking.objects.all().update(
            last_access_date=current_time.date(),
            last_updated_time=current_time - relativedelta(days=1),
            nearest_due_date=current_time
        )
        total_exclude = 2
        for fdc_active in FDCActiveLoanChecking.objects.filter()[:total_exclude]:
            fdc_active.update_safely(last_updated_time=None)
        customer_ids = get_fdc_loan_active_checking_for_daily_checker(
            self.fs.parameters, current_time
        )
        assert len(total_customer_ids) - total_exclude == len(customer_ids)

        # 3. number_of_other_platforms
        FDCActiveLoanChecking.objects.all().update(
            last_access_date=current_time.date(),
            last_updated_time=current_time - relativedelta(days=1),
            nearest_due_date=current_time
        )
        total_exclude = 2
        for fdc_active in FDCActiveLoanChecking.objects.filter()[:total_exclude]:
            fdc_active.update_safely(number_of_other_platforms=2)
        customer_ids = get_fdc_loan_active_checking_for_daily_checker(
            self.fs.parameters, current_time
        )
        assert len(total_customer_ids) - total_exclude == len(customer_ids)

        # 4. Nearest due date, nearest_due_date is far from config
        FDCActiveLoanChecking.objects.all().update(
            last_access_date=current_time.date(),
            last_updated_time=current_time - relativedelta(days=1),
            nearest_due_date=current_time,
            number_of_other_platforms=4
        )
        nearest_due_date = current_time.date() + relativedelta(
            days=self.fs.parameters['daily_checker_config']['nearest_due_date_from_days'] + 1
        )
        total_exclude = 2
        for fdc_active in FDCActiveLoanChecking.objects.filter()[:total_exclude]:
            fdc_active.update_safely(nearest_due_date=nearest_due_date)
        customer_ids = get_fdc_loan_active_checking_for_daily_checker(
            self.fs.parameters, current_time
        )
        assert len(total_customer_ids) - total_exclude == len(customer_ids)

        # 4.1 nearest_due_date is null
        FDCActiveLoanChecking.objects.all().update(
            number_of_other_platforms=4,
            last_access_date=current_time.date(),
            last_updated_time=current_time - relativedelta(days=1),
            nearest_due_date=current_time,
        )
        for fdc_active in FDCActiveLoanChecking.objects.filter()[:total_exclude]:
            fdc_active.update_safely(nearest_due_date=None)
        customer_ids = get_fdc_loan_active_checking_for_daily_checker(
            self.fs.parameters, current_time
        )
        assert len(total_customer_ids) - total_exclude == len(customer_ids)

        # 5 FDCActiveLoanChecking don't have data.
        FDCActiveLoanChecking.objects.all().update(
            number_of_other_platforms=None,
            last_access_date=current_time.date(),
            last_updated_time=None,
            nearest_due_date=None,
        )
        customer_ids = get_fdc_loan_active_checking_for_daily_checker(
            self.fs.parameters, current_time
        )
        assert len(total_customer_ids) == len(customer_ids)

    @freeze_time("2024-01-01 15:00:00")
    @patch(
        'juloserver.loan.tasks.lender_related.fdc_inquiry_for_active_loan_from_platform_daily_checker_subtask')
    def test_fdc_inquiry_for_active_loan_from_platform_daily_checker_task(self, _mock_sub_task):
        current_time = datetime(2024, 1, 1, 15)
        FDCActiveLoanChecking.objects.all().update(
            last_access_date=current_time.date(),
            last_updated_time=current_time - relativedelta(days=1),
            nearest_due_date=current_time
        )
        total_customer_ids = FDCActiveLoanChecking.objects.all().values_list('customer_id', flat=True)

        fdc_inquiry_for_active_loan_from_platform_daily_checker_task()
        call_count = _mock_sub_task.apply_async.call_count
        self.assertEqual(call_count, len(total_customer_ids))
        self.assertNotEqual(call_count, 0)

    @freeze_time("2024-01-01 15:00:00")
    @patch("juloserver.grab.utils.GrabUtils.set_redis_client")
    @patch(
        'juloserver.loan.tasks.lender_related.fdc_inquiry_for_active_loan_from_platform_daily_checker_subtask')
    def test_grab_fdc_inquiry_for_active_loan_from_platform_daily_checker_task(
        self,
        _mock_sub_task,
        mock_set_redis_client
    ):
        mock_set_redis_client.return_value = None
        from juloserver.grab.tests.factories import GrabCustomerDataFactory

        current_time = datetime(2024, 1, 1, 15)
        FDCActiveLoanChecking.objects.all().update(
            last_access_date=current_time.date(),
            last_updated_time=current_time - relativedelta(days=1),
            nearest_due_date=current_time
        )
        total_customer_ids = FDCActiveLoanChecking.objects.all().values_list('customer_id', flat=True)
        grab_customers = []
        for customer_id in total_customer_ids:
            temp_customer = Customer.objects.get(id=customer_id)
            grab_customers.append(GrabCustomerDataFactory(customer=temp_customer))

        grab_fdc_inquiry_for_active_loan_from_platform_daily_checker_task()
        self.assertEqual(_mock_sub_task.apply_async.call_count, len(total_customer_ids))
        self.assertTrue(FDCUpdateTypes.GRAB_DAILY_CHECKER in str(_mock_sub_task.apply_async.call_args))
        self.assertNotEqual(_mock_sub_task.apply_async.call_count, 0)

    @override_settings(CELERY_ALWAYS_EAGER=True)
    @freeze_time("2024-01-01 15:00:00")
    @patch("juloserver.grab.utils.GrabUtils.set_redis_client")
    @patch("juloserver.julo.services.process_application_status_change")
    @patch(
        'juloserver.loan.tasks.lender_related.fdc_inquiry_for_active_loan_from_platform_daily_checker_subtask')
    def test_grab_fdc_inquiry_for_active_loan_from_platform_daily_checker_task_blacklisted_users(
        self,
        _mock_sub_task,
        mock_process_application_status_change,
        mock_set_redis_client
    ):
        mock_set_redis_client.return_value = None

        from juloserver.grab.tests.factories import GrabCustomerDataFactory

        current_time = datetime(2024, 1, 1, 15)
        FDCActiveLoanChecking.objects.all().update(
            last_access_date=current_time.date(),
            last_updated_time=current_time - relativedelta(days=1),
            nearest_due_date=current_time
        )
        total_customer_ids = FDCActiveLoanChecking.objects.all().values_list('customer_id', flat=True)
        grab_customers = []

        for customer_id in total_customer_ids:
            temp_customer = Customer.objects.get(id=customer_id)
            AccountFactory(
                customer=temp_customer,
                status=self.active_status_code
            )
            grab_customers.append(GrabCustomerDataFactory(customer=temp_customer))
            BlacklistCustomerFactory(
                fullname_trim=temp_customer.fullname,
                name=temp_customer.fullname
            )
            temp_app = ApplicationFactory(customer=temp_customer, account=temp_customer.account)
            temp_app.application_status = StatusLookupFactory(
                status_code=ApplicationStatusCodes.FUND_DISBURSAL_SUCCESSFUL
            )
            temp_app.save()

        self.application.save()

        grab_fdc_inquiry_for_active_loan_from_platform_daily_checker_task()
        self.assertEqual(_mock_sub_task.apply_async.call_count, 0)
        _mock_sub_task.assert_not_called()
        self.assertEqual(_mock_sub_task.apply_async.call_count, 0)
        self.assertEqual(mock_process_application_status_change.call_count, len(total_customer_ids))

    @patch('juloserver.loan.tasks.lender_related.fdc_inquiry_other_active_loans_from_platforms_task')
    def test_fdc_inquiry_for_active_loan_from_platform_daily_checker_subtask(
        self, _mock_fdc_inquiry_active_loans_task):
        current_time = datetime(2024, 10, 1, 15)
        FDCActiveLoanChecking.objects.all().update(
            last_access_date=current_time.date(),
            last_updated_time=current_time - relativedelta(days=1),
            nearest_due_date=current_time
        )
        fdc_checking = FDCActiveLoanChecking.objects.first()
        fdc_checking.customer_id = self.customer.pk
        fdc_checking.save()

        fdc_inquiry_for_active_loan_from_platform_daily_checker_subtask(
            fdc_checking.customer_id, self.fs.parameters)
        _mock_fdc_inquiry_active_loans_task.assert_called()

    @patch(
        'juloserver.loan.services.loan_related'
        '.send_user_attributes_to_moengage_for_active_platforms_rule.delay'
    )
    @patch('juloserver.loan.tasks.lender_related.get_and_save_fdc_data')
    def test_fdc_inquiry_other_active_loans_from_platforms_task_success(
        self, _mock_get_and_save_fdc_data,
        mock_send_user_attributes_to_moengage_for_active_platforms_rule
    ):
        current_time = datetime(2024, 10, 1, 15)
        FDCActiveLoanChecking.objects.all().update(
            last_access_date=current_time.date(),
            last_updated_time=current_time - relativedelta(days=1),
            nearest_due_date=current_time
        )
        fdc_checking = FDCActiveLoanChecking.objects.first()
        fdc_checking.customer_id = self.customer.pk
        fdc_checking.save()
        params = dict(
            application_id=self.application.pk,
            fdc_inquiry_api_config=self.fs.parameters['fdc_inquiry_api_config'],
            number_of_allowed_platforms=self.fs.parameters['number_of_allowed_platforms'],
            fdc_inquiry_id=self.fdc_inquiry.pk
        )
        fdc_inquiry_data = {'id': self.fdc_inquiry.pk, 'nik': self.fdc_inquiry.nik}

        fdc_inquiry_other_active_loans_from_platforms_task(
            fdc_inquiry_data, self.customer.pk, FDCUpdateTypes.DAILY_CHECKER, params
        )
        fdc_checking.refresh_from_db()
        fdc_checking.nearest_due_date == self.nearest_due_date
        fdc_checking.number_of_other_platforms == 2
        mock_send_user_attributes_to_moengage_for_active_platforms_rule.assert_called_once_with(
            customer_id=self.customer.id, is_eligible=True
        )

    @patch("juloserver.loan.services.loan_related.move_grab_app_to_190")
    @patch(
        'juloserver.loan.services.loan_related'
        '.send_user_attributes_to_moengage_for_active_platforms_rule.delay'
    )
    @patch('juloserver.loan.tasks.lender_related.get_and_save_fdc_data')
    def test_grab_fdc_inquiry_other_active_loans_from_platforms_task_success(
        self, _mock_get_and_save_fdc_data,
        mock_send_user_attributes_to_moengage_for_active_platforms_rule,
        mock_move_grab_app_to_190
    ):
        self.application.workflow = WorkflowFactory(name=WorkflowConst.GRAB)
        self.application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.FUND_DISBURSAL_SUCCESSFUL
        )
        self.application.save()

        current_time = datetime(2024, 10, 1, 15)
        FDCActiveLoanChecking.objects.all().update(
            last_access_date=current_time.date(),
            last_updated_time=current_time - relativedelta(days=1),
            nearest_due_date=current_time
        )
        fdc_checking = FDCActiveLoanChecking.objects.first()
        fdc_checking.customer_id = self.customer.pk
        fdc_checking.save()
        params = dict(
            application_id=self.application.pk,
            fdc_inquiry_api_config=self.fs.parameters['fdc_inquiry_api_config'],
            number_of_allowed_platforms=self.fs.parameters['number_of_allowed_platforms'],
            fdc_inquiry_id=self.fdc_inquiry.pk
        )
        fdc_inquiry_data = {'id': self.fdc_inquiry.pk, 'nik': self.fdc_inquiry.nik}

        fdc_inquiry_other_active_loans_from_platforms_task(
            fdc_inquiry_data, self.customer.pk, FDCUpdateTypes.GRAB_DAILY_CHECKER, params
        )
        fdc_checking.refresh_from_db()
        fdc_checking.nearest_due_date == self.nearest_due_date
        fdc_checking.number_of_other_platforms == 2

        mock_move_grab_app_to_190.assert_called()

    @patch("juloserver.loan.services.loan_related.move_grab_app_to_190")
    @patch(
        'juloserver.loan.services.loan_related'
        '.send_user_attributes_to_moengage_for_active_platforms_rule.delay'
    )
    @patch('juloserver.loan.tasks.lender_related.get_and_save_fdc_data')
    def test_grab_fdc_inquiry_other_active_loans_from_platforms_task_success_above_limit(
        self, _mock_get_and_save_fdc_data,
        mock_send_user_attributes_to_moengage_for_active_platforms_rule,
        mock_move_grab_app_to_190
    ):
        FDCInquiryLoanFactory.create_batch(
            2,
            fdc_inquiry_id=self.fdc_inquiry.id,
            is_julo_loan=None,
            id_penyelenggara=4,
            dpd_terakhir=1,
            status_pinjaman=FDCLoanStatus.OUTSTANDING,
            tgl_jatuh_tempo_pinjaman=datetime(2024, 2, 1),
        )

        self.application.workflow = WorkflowFactory(name=WorkflowConst.GRAB)
        self.application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.FUND_DISBURSAL_SUCCESSFUL
        )
        self.application.save()

        current_time = datetime(2024, 10, 1, 15)
        FDCActiveLoanChecking.objects.all().update(
            last_access_date=current_time.date(),
            last_updated_time=current_time - relativedelta(days=1),
            nearest_due_date=current_time
        )
        fdc_checking = FDCActiveLoanChecking.objects.first()
        fdc_checking.customer_id = self.customer.pk
        fdc_checking.save()
        params = dict(
            application_id=self.application.pk,
            fdc_inquiry_api_config=self.fs.parameters['fdc_inquiry_api_config'],
            number_of_allowed_platforms=self.fs.parameters['number_of_allowed_platforms'],
            fdc_inquiry_id=self.fdc_inquiry.pk
        )
        fdc_inquiry_data = {'id': self.fdc_inquiry.pk, 'nik': self.fdc_inquiry.nik}

        fdc_inquiry_other_active_loans_from_platforms_task(
            fdc_inquiry_data, self.customer.pk, FDCUpdateTypes.GRAB_DAILY_CHECKER, params
        )
        fdc_checking.refresh_from_db()
        fdc_checking.nearest_due_date == self.nearest_due_date
        fdc_checking.number_of_other_platforms == 2

        mock_move_grab_app_to_190.assert_not_called()


class TestExecuteCheckActiveLoans(TestCase):
    def setUp(self):
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user_auth)
        self.account = AccountFactory(customer=self.customer)
        self.application = ApplicationFactory(customer=self.customer, account=self.account)
        self.status_lookup = StatusLookupFactory()
        self.product_lookup = ProductLookupFactory()

    @patch("juloserver.grab.services.loan_related.execute_fdc_inquiry_other_active_loans_from_platforms_task_grab")
    def test_create_fdc_inquiry_and_execute_check_active_loans(
        self,
        mock_execute_fdc_inquiry_other_active_loans_from_platforms_task_grab
    ):
        self.assertFalse(
            FDCInquiry.objects.filter(application_id=self.application.id).exists()
        )
        params = dict(
            application_id=self.application.pk,
            loan_id=None,
            fdc_data_outdated_threshold_days=1,
            number_of_allowed_platforms=3,
            fdc_inquiry_api_config={},
        )
        create_fdc_inquiry_and_execute_check_active_loans_for_grab(
            customer=self.customer,
            params=params,
            update_type=FDCUpdateTypes.GRAB_STUCK_150
        )
        self.assertTrue(
            FDCInquiry.objects.filter(application_id=self.application.id).exists()
        )
        mock_execute_fdc_inquiry_other_active_loans_from_platforms_task_grab.assert_called_once()


class TestGrabAppStuck150HandlerTask(TestCase):
    def setUp(self):
        self.customer = CustomerFactory(nik='123321123321')
        self.customer_segment = 'activeus_a'
        active_status_code = StatusLookupFactory(status_code=AccountConstant.STATUS_CODE.active)
        self.account = AccountFactory(
            customer=self.customer,
            status=active_status_code
        )

        FeatureSetting.objects.\
            filter(feature_name=FeatureNameConst.GRAB_3_MAX_CREDITORS_CHECK).\
                delete()

        self.fs = FeatureSettingFactory(
            feature_name=FeatureNameConst.GRAB_3_MAX_CREDITORS_CHECK,
            parameters={
                "fdc_data_outdated_threshold_days": 3,
                "number_of_allowed_platforms": 3,
                "fdc_inquiry_api_config": {
                    "max_retries": 3,
                    "retry_interval_seconds": 30
                },
                "whitelist": {
                    "is_active": True,
                    "list_application_id": [],
                },
                "daily_checker_config": {
                    "rps_throttling": 3,
                    "nearest_due_date_from_days": 5,
                    "batch_size": 1000,
                    "last_access_days": 7,
                    "retry_per_days": 1
                }
            },
            is_active=True,
        )

    def create_application_stuck_150(self):
        self.workflow = WorkflowFactory(name=WorkflowConst.GRAB)
        self.product_line = ProductLineFactory(product_line_code=ProductLineCodes.J1)
        application = ApplicationFactory(
            customer=self.account.customer,
            account=self.account,
            mobile_phone_1='0123456788',
            workflow=self.workflow,
            product_line=self.product_line
        )
        application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.ACTIVATION_CALL_SUCCESS_AND_BANK_VALIDATE_ONGOING
        )
        application.save()

        self.inquiry_2 = FDCInquiryFactory(
            application_id=application.id, inquiry_status='success'
        )
        self.nearest_due_date = datetime(2023, 12, 21).date()
        self.nearest_due_date_2 = datetime(2023, 12, 22).date()
        FDCInquiryLoanFactory.create_batch(
            2,
            fdc_inquiry_id=self.inquiry_2.id,
            is_julo_loan=None,
            id_penyelenggara=1,
            dpd_terakhir=1,
            status_pinjaman=FDCLoanStatus.OUTSTANDING,
            tgl_jatuh_tempo_pinjaman=datetime(2023, 12, 30),
        )

        return application

    @patch("juloserver.grab.tasks.grab_app_stuck_150_handler_subtask")
    def test_grab_app_stuck_150_handler_task_feature_settings_active(
        self,
        mock_grab_app_stuck_150_handler_subtask
    ):
        result = grab_app_stuck_150_handler_task()
        self.assertNotEqual(result, None)
        mock_grab_app_stuck_150_handler_subtask.asert_not_called()

    def test_grab_app_stuck_150_handler_task_feature_settings_not_active(self):
        self.fs.is_active = False
        self.fs.save()

        self.assertEqual(grab_app_stuck_150_handler_task(), None)

    @patch("juloserver.grab.tasks.grab_app_stuck_150_handler_subtask")
    def test_grab_app_stuck_150_handler_task_subtask_called(
        self,
        mock_grab_app_stuck_150_handler_subtask
    ):
        for _ in range(5):
            self.create_application_stuck_150()

        grab_app_stuck_150_handler_task()
        mock_grab_app_stuck_150_handler_subtask.delay.assert_called()

    @patch("juloserver.grab.tasks.register_privy")
    @patch("juloserver.julo.services.process_application_status_change")
    def test_grab_app_stuck_150_handler_subtask_eligible(
        self,
        mock_process_application_status_change,
        mock_register_privy
    ):
        application = self.create_application_stuck_150()
        grab_applications = [(application.id, application.customer.id)]
        grab_app_stuck_150_handler_subtask(grab_applications, self.fs.parameters)
        mock_register_privy.assert_called_with(application_id=application.id)
        mock_process_application_status_change.assert_called_with(
            application.id,
            ApplicationStatusCodes.LOC_APPROVED,
            'Credit limit activated'
        )

    @patch("juloserver.julo.services.process_application_status_change")
    def test_grab_app_stuck_150_handler_subtask_not_eligible(self, mock_process_application_status_change):
        application = self.create_application_stuck_150()
        for i in range(4):
            FDCInquiryLoanFactory.create_batch(
                2,
                fdc_inquiry_id=self.inquiry_2.id,
                is_julo_loan=None,
                id_penyelenggara=int('10{}'.format(i)),
                dpd_terakhir=1,
                status_pinjaman=FDCLoanStatus.OUTSTANDING,
                tgl_jatuh_tempo_pinjaman=datetime(2023, 12, 30),
            )

        grab_applications = [(application.id, application.customer.id)]
        grab_app_stuck_150_handler_subtask(grab_applications, self.fs.parameters)
        mock_process_application_status_change.assert_called_with(
            application.id,
            ApplicationStatusCodes.FUND_DISBURSAL_SUCCESSFUL,
            'Failed 3 max creditors check'
        )

    @patch("juloserver.grab.tasks.register_privy")
    @patch("juloserver.julo.services.process_application_status_change")
    def test_grab_app_stuck_150_handler_subtask_use_old_data(
        self,
        mock_process_application_status_change,
        mock_register_privy
    ):
        application = self.create_application_stuck_150()
        with freeze_time("2024-01-01"):
            self.inquiry_2.udate = datetime(2024, 1, 1)
            self.inquiry_2.save()
            self.inquiry_2.refresh_from_db()

        grab_applications = [(application.id, application.customer.id)]
        grab_app_stuck_150_handler_subtask(grab_applications, self.fs.parameters)
        mock_register_privy.assert_called_with(application_id=application.id)
        mock_process_application_status_change.assert_called_with(
            application.id,
            ApplicationStatusCodes.LOC_APPROVED,
            'Credit limit activated'
        )

    @patch("juloserver.julo.services.process_application_status_change")
    def test_grab_app_stuck_150_handler_subtask_no_fdc_data(
        self,
        mock_process_application_status_change
    ):
        application = self.create_application_stuck_150()
        self.inquiry_2.delete()

        grab_applications = [(application.id, application.customer.id)]
        grab_app_stuck_150_handler_subtask(grab_applications, self.fs.parameters)
        mock_process_application_status_change.assert_called_with(
            application.id,
            ApplicationStatusCodes.LOC_APPROVED,
            'Credit limit activated'
        )
