import ast
from datetime import datetime
from unittest import mock
from cuser.middleware import CuserMiddleware
from django.conf import settings
from django.test.testcases import TestCase
from django.utils import timezone
from mock import MagicMock, patch

from juloserver.account.models import Account, AccountStatusHistory
from juloserver.account.tests.factories import (
    AccountFactory,
    AccountStatusHistoryFactory,
    AddressFactory,
)
from juloserver.customer_module.constants import (
    AccountDeletionRequestStatuses,
    AccountDeletionStatusChangeReasons,
    ChangePhoneLostAccess,
    FailedAccountDeletionRequestStatuses,
    CustomerDataChangeRequestConst,
)
from juloserver.customer_module.exceptions import CustomerApiException
from juloserver.customer_module.models import (
    AccountDeletionRequest,
    CustomerDataChangeRequest,
)
from juloserver.customer_module.services.customer_related import (
    CustomerDataChangeRequestHandler,
    CustomerDataChangeRequestNotification,
    CustomerService,
    cancel_account_request_deletion,
    check_if_phone_exists,
    delete_document_payday_customer_change_request_from_oss,
    get_customer_data_request_field_changes,
    get_customer_status,
    get_ongoing_account_deletion_request,
    get_ongoing_account_deletion_requests,
    is_user_delete_allowed,
    is_show_customer_data_menu,
    julo_starter_proven_bypass,
    is_device_reset_phone_number_rate_limited,
    prepare_reset_phone_request,
    process_incoming_change_phone_number_request,
    request_account_deletion,
    update_customer_data_by_application,
    restriction_access,
    get_consent_status_from_application_or_account,
)
from juloserver.customer_module.tests.factories import (
    AccountDeletionRequestFactory,
    CustomerDataChangeRequestFactory,
    CXDocumentFactory,
)
from juloserver.julo.constants import MobileFeatureNameConst, WorkflowConst
from juloserver.julo.models import (
    Application,
    ApplicationHistory,
    AuthUserFieldChange,
    CustomerFieldChange,
    StatusLookup,
    Workflow,
)
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.tests.factories import (
    ApplicationFactory,
    ApplicationHistoryFactory,
    ApplicationJ1Factory,
    AuthUserFactory,
    CustomerFactory,
    LoanFactory,
    FeatureSettingFactory,
    ImageFactory,
    ProductLineFactory,
    WorkflowFactory,
    StatusLookupFactory,
)
from juloserver.julo.statuses import ApplicationStatusCodes, JuloOneCodes, LoanStatusCodes


class TestCustomerService(TestCase):
    def setUp(self):
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.application = ApplicationFactory(customer=self.customer)

    def tearDown(self):
        CuserMiddleware.del_user()

    def test_change_email(self):
        customer_service = CustomerService()
        customer_service.change_email(self.user, 'newemail@gmail.com')
        self.customer.refresh_from_db()
        assert self.customer.email == 'newemail@gmail.com'


class TestGetCustomerStatus(TestCase):
    def test_user_no_pin__customer_cannot_reapply__no_application(self):
        self.user_no_application = AuthUserFactory()
        self.customer_no_application = CustomerFactory(
            user=self.user_no_application, can_reapply=False
        )

        status = get_customer_status(self.customer_no_application)
        use_new_ui = status[0]
        show_setup_pin = status[1]
        self.assertTrue(use_new_ui)
        self.assertTrue(show_setup_pin)

    def test_julovers_application(self):
        julovers_product_line = ProductLineFactory(product_line_code=ProductLineCodes.JULOVER)
        julovers_workflow = WorkflowFactory(name=WorkflowConst.JULOVER)
        customer = CustomerFactory(can_reapply=False)
        ApplicationFactory(
            product_line=julovers_product_line, customer=customer, workflow=julovers_workflow
        )

        use_new_ui, _ = get_customer_status(customer)

        self.assertTrue(use_new_ui)


class TestUpdateCustomerDataByApplication(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()
        self.application = ApplicationFactory(customer=self.customer)

    def test_success(self):
        update_data = {"fullname": "robert", "phone": "0899999999"}
        user = self.customer.user
        update_customer_data_by_application(self.customer, self.application, update_data)
        self.assertEqual(
            (self.customer.fullname, self.customer.phone),
            (update_data['fullname'], update_data['phone']),
        )
        customer_field_changes = CustomerFieldChange.objects.filter(customer=self.customer)
        self.assertEqual(len(customer_field_changes), 2)
        user.refresh_from_db()
        self.assertNotEqual(user.username, update_data['phone'])

        # username is phone number
        update_data = {"phone": "0899999999"}
        user.username = '0833333333'
        user.save()
        update_customer_data_by_application(self.customer, self.application, update_data)
        self.assertTrue(self.customer.phone == update_data['phone'] == self.customer.user.username)
        user_field_change = AuthUserFieldChange.objects.filter(user=user).last()
        self.assertIsNotNone(user_field_change)


class TestBypassIsProven(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()
        self.application = ApplicationFactory(customer=self.customer)
        self.application.workflow = WorkflowFactory(name=WorkflowConst.JULO_STARTER)
        self.application.save()

    def test_bypass_is_proven_121(self):
        self.application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.SCRAPED_DATA_VERIFIED
        )
        self.application.save()

        self.assertTrue(julo_starter_proven_bypass(self.application))

    def test_bypass_is_proven_105(self):
        self.application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.FORM_PARTIAL
        )
        self.application.save()

        self.assertFalse(julo_starter_proven_bypass(self.application))


class TestIsUserDeleteAllowed(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()

    @mock.patch('juloserver.customer_module.services.customer_related.get_active_loan_ids')
    def test_no_loan(self, mock_get_active_loan_ids):
        mock_get_active_loan_ids.return_value = None
        is_allowed, failed_status = is_user_delete_allowed(self.customer)
        self.assertTrue(is_allowed)
        self.assertIsNone(failed_status)

    def test_loan_on_disbursement(self):
        LoanFactory(
            customer=self.customer,
            loan_status=StatusLookup.objects.filter(
                status_code=LoanStatusCodes.FUND_DISBURSAL_ONGOING
            ).first(),
        )
        is_allowed, failed_status = is_user_delete_allowed(self.customer)
        self.assertFalse(is_allowed)
        self.assertEqual(failed_status, FailedAccountDeletionRequestStatuses.LOANS_ON_DISBURSEMENT)

    def test_active_loans(self):
        LoanFactory(
            customer=self.customer,
            loan_status=StatusLookup.objects.filter(status_code=LoanStatusCodes.LOAN_1DPD).first(),
        )
        is_allowed, failed_status = is_user_delete_allowed(self.customer)
        self.assertFalse(is_allowed)
        self.assertEqual(failed_status, FailedAccountDeletionRequestStatuses.ACTIVE_LOANS)

    @mock.patch('juloserver.customer_module.services.customer_related.get_active_loan_ids')
    def test_forbidden_application_statuses(self, mock_get_active_loan_ids):
        mock_get_active_loan_ids.return_value = []
        application = ApplicationFactory(customer=self.customer)
        app = Application.objects.get(id=application.id)
        app.change_status(ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_FRAUD)
        app.save()

        is_allowed, failed_status = is_user_delete_allowed(self.customer)
        self.assertFalse(is_allowed)
        self.assertEqual(
            failed_status, FailedAccountDeletionRequestStatuses.APPLICATION_NOT_ELIGIBLE
        )

    @mock.patch('juloserver.customer_module.services.customer_related.get_active_loan_ids')
    def test_forbidden_account_statuses(self, mock_get_active_loan_ids):
        mock_get_active_loan_ids.return_value = []
        AccountFactory(
            customer=self.customer,
            status=StatusLookup.objects.filter(status_code=JuloOneCodes.SUSPENDED).first(),
        )

        is_allowed, failed_status = is_user_delete_allowed(self.customer)
        self.assertFalse(is_allowed)
        self.assertEqual(failed_status, FailedAccountDeletionRequestStatuses.ACCOUNT_NOT_ELIGIBLE)

    @mock.patch('juloserver.customer_module.services.customer_related.get_active_loan_ids')
    def test_success(self, mock_get_active_loan_ids):
        mock_get_active_loan_ids.return_value = []

        is_allowed, failed_status = is_user_delete_allowed(self.customer)
        self.assertTrue(is_allowed)
        self.assertIsNone(failed_status)


class TestRequestAccountDeletion(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()
        self.reason = 'Pengajuan ditolak'
        self.detail_reason = 'ini contoh text lebih dari 40 characters hehehehahahha kamekameha'
        self.survey_submission_uid = "6ebb30b2-a920-4acb-965c-39be489de77a"
        self.workflow = Workflow.objects.get(name=WorkflowConst.JULO_ONE)
        self.product_line = ProductLineFactory(
            product_line_code=ProductLineCodes.J1,
        )

    def test_empty_reason(self):
        AccountFactory(
            customer=self.customer,
        )
        result, failed_status = request_account_deletion(self.customer, '', self.detail_reason)
        self.assertIsNone(result)
        self.assertEqual(failed_status, FailedAccountDeletionRequestStatuses.EMPTY_REASON)

    def test_empty_reason_with_survey_submission(self):
        AccountFactory(
            customer=self.customer,
        )
        result, _ = request_account_deletion(
            self.customer, '', self.detail_reason, self.survey_submission_uid
        )
        self.assertIsNotNone(result)

    def test_empty_detail_reason(self):
        AccountFactory(
            customer=self.customer,
        )
        result, failed_status = request_account_deletion(self.customer, self.reason, '')
        self.assertIsNone(result)
        self.assertEqual(failed_status, FailedAccountDeletionRequestStatuses.EMPTY_DETAIL_REASON)

    def test_empty_detail_reason_with_survey_submission(self):
        AccountFactory(
            customer=self.customer,
        )
        result, _ = request_account_deletion(
            self.customer, self.reason, '', self.survey_submission_uid
        )
        self.assertIsNotNone(result)

    def test_detail_reason_too_short(self):
        AccountFactory(
            customer=self.customer,
        )
        result, failed_status = request_account_deletion(
            self.customer, self.reason, 'pendek banget', self.survey_submission_uid
        )
        self.assertIsNone(result)
        self.assertEqual(failed_status, FailedAccountDeletionRequestStatuses.INVALID_DETAIL_REASON)

    def test_detail_reason_too_long(self):
        AccountFactory(
            customer=self.customer,
        )
        result, failed_status = request_account_deletion(
            self.customer,
            self.reason,
            'Lorem ipsum dolor sit amet, consectetur adipiscing elit, sed do eiusmod tempor incididunt ut labore et dolore magna aliqua. Ut enim ad minim veniam, quis nostrud exercitation ullamco laboris nisi ut aliquip ex ea commodo consequat. Duis aute irure dolor in reprehenderit in voluptate velit esse cillum dolore eu fugiat nulla pariatur. Excepteur sint occaecat cupidatat non proident, sunt in culpa qui officia deserunt mollit anim id est laborum. Sed ut perspiciatis unde omnis iste natus error sit voluptatem accusantium doloremque laudantium, totam rem aperiam, eaque ipsa quae ab illo inventore veritatis et quasi architecto beatae vitae dicta sunt explicabo',
            self.survey_submission_uid,
        )
        self.assertIsNone(result)
        self.assertEqual(failed_status, FailedAccountDeletionRequestStatuses.INVALID_DETAIL_REASON)

    @mock.patch('juloserver.customer_module.services.customer_related.is_user_delete_allowed')
    def test_delete_not_allowed(self, mock_is_user_delete_allowed):
        AccountFactory(
            customer=self.customer,
        )
        mock_is_user_delete_allowed.return_value = (
            False,
            FailedAccountDeletionRequestStatuses.ACTIVE_LOANS,
        )

        result, failed_status = request_account_deletion(
            self.customer, self.reason, self.detail_reason, self.survey_submission_uid
        )
        self.assertIsNone(result)
        self.assertEqual(failed_status, FailedAccountDeletionRequestStatuses.ACTIVE_LOANS)

    @mock.patch('juloserver.customer_module.services.customer_related.is_user_delete_allowed')
    def test_no_account(self, mock_is_user_delete_allowed):
        mock_is_user_delete_allowed.return_value = True, None

        result, failed_status = request_account_deletion(
            self.customer, self.reason, self.detail_reason, self.survey_submission_uid
        )
        self.assertIsNotNone(result)
        self.assertIsNone(failed_status)

        inserted_request = AccountDeletionRequest.objects.filter(customer=self.customer).first()
        self.assertIsNotNone(inserted_request)
        self.assertEqual(inserted_request.reason, self.reason)
        self.assertEqual(inserted_request.detail_reason, self.detail_reason)

    @mock.patch('juloserver.customer_module.services.customer_related.is_user_delete_allowed')
    def test_no_application(self, mock_is_user_delete_allowed):
        AccountFactory(
            customer=self.customer,
        )
        mock_is_user_delete_allowed.return_value = True, None

        result, failed_status = request_account_deletion(
            self.customer, self.reason, self.detail_reason, self.survey_submission_uid
        )
        self.assertIsNotNone(result)
        self.assertIsNone(failed_status)

        inserted_request = AccountDeletionRequest.objects.filter(customer=self.customer).first()
        self.assertIsNotNone(inserted_request)
        self.assertEqual(inserted_request.reason, self.reason)
        self.assertEqual(inserted_request.detail_reason, self.detail_reason)

    @mock.patch('juloserver.customer_module.services.customer_related.is_user_delete_allowed')
    def test_success_no_account_update(self, mock_is_user_delete_allowed):
        initial_account = AccountFactory(
            customer=self.customer,
        )
        application = ApplicationFactory(
            customer=self.customer,
            workflow=WorkflowFactory(name=WorkflowConst.GRAB),
        )
        old_app_status = application.application_status_id
        mock_is_user_delete_allowed.return_value = True, None

        result, failed_status = request_account_deletion(
            self.customer, self.reason, self.detail_reason, self.survey_submission_uid
        )
        self.assertIsNotNone(result)
        self.assertIsNone(failed_status)

        inserted_request = AccountDeletionRequest.objects.filter(customer=self.customer).first()
        self.assertIsNotNone(inserted_request)
        self.assertEqual(inserted_request.reason, self.reason)
        self.assertEqual(inserted_request.detail_reason, self.detail_reason)

        account = self.customer.account_set.last()
        self.assertEqual(account.status_id, initial_account.status_id)

        application.refresh_from_db()
        self.assertEqual(application.application_status_id, old_app_status)

    @mock.patch('juloserver.customer_module.services.customer_related.is_user_delete_allowed')
    def test_success(self, mock_is_user_delete_allowed):
        initial_account = AccountFactory(
            customer=self.customer,
        )
        application = ApplicationFactory(
            customer=self.customer,
            workflow=self.workflow,
            product_line=self.product_line,
        )
        old_app_status = application.application_status_id
        mock_is_user_delete_allowed.return_value = True, None

        result, failed_status = request_account_deletion(
            self.customer, self.reason, self.detail_reason, self.survey_submission_uid
        )
        self.assertIsNotNone(result)
        self.assertIsNone(failed_status)

        inserted_request = AccountDeletionRequest.objects.filter(customer=self.customer).first()
        self.assertIsNotNone(inserted_request)
        self.assertEqual(inserted_request.reason, self.reason)
        self.assertEqual(inserted_request.detail_reason, self.detail_reason)

        account = self.customer.account_set.last()
        self.assertEqual(account.status_id, JuloOneCodes.ACCOUNT_DELETION_ON_REVIEW)

        status_history = AccountStatusHistory.objects.filter(
            change_reason=AccountDeletionStatusChangeReasons.REQUEST_REASON,
            account=account,
        ).last()
        self.assertIsNotNone(status_history)
        self.assertEqual(status_history.status_new_id, JuloOneCodes.ACCOUNT_DELETION_ON_REVIEW)
        self.assertEqual(status_history.status_old_id, initial_account.status_id)

        application.refresh_from_db()
        self.assertEqual(
            application.application_status_id, ApplicationStatusCodes.CUSTOMER_ON_DELETION
        )

        app_history = ApplicationHistory.objects.filter(
            change_reason=AccountDeletionStatusChangeReasons.REQUEST_REASON,
            application=application,
            status_new=ApplicationStatusCodes.CUSTOMER_ON_DELETION,
        ).first()
        self.assertIsNotNone(app_history)
        self.assertEqual(app_history.status_new, ApplicationStatusCodes.CUSTOMER_ON_DELETION)
        self.assertEqual(app_history.status_old, old_app_status)


class TestCancelAccountRequestDeletion(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()
        self.workflow = Workflow.objects.get(name=WorkflowConst.JULO_ONE)

    def test_customer_none(self):
        result = cancel_account_request_deletion(None)
        self.assertIsNone(result)

    def test_no_deletion_request(self):
        result = cancel_account_request_deletion(self.customer)
        self.assertIsNone(result)

    def test_forbidden_status(self):
        # Cancelled
        AccountDeletionRequestFactory(
            customer=self.customer, request_status=AccountDeletionRequestStatuses.CANCELLED
        )
        result = cancel_account_request_deletion(self.customer)
        self.assertIsNone(result)

        # Rejected
        AccountDeletionRequestFactory(
            customer=self.customer, request_status=AccountDeletionRequestStatuses.REJECTED
        )
        result = cancel_account_request_deletion(self.customer)
        self.assertIsNone(result)

    def test_no_account(self):
        AccountDeletionRequestFactory(customer=self.customer)
        result = cancel_account_request_deletion(self.customer)
        self.assertIsNotNone(result)

    def test_no_application(self):
        AccountDeletionRequestFactory(customer=self.customer)
        AccountFactory(customer=self.customer)
        result = cancel_account_request_deletion(self.customer)
        self.assertIsNotNone(result)

    def test_last_status_not_exists(self):
        AccountDeletionRequestFactory(customer=self.customer)
        account = AccountFactory(customer=self.customer)
        result = cancel_account_request_deletion(self.customer)
        self.assertIsNotNone(result)

        account_after_cancel = Account.objects.filter(customer=self.customer).first()
        self.assertEqual(account.status_id, account_after_cancel.status_id)

    def test_application_status_not_exists(self):
        AccountDeletionRequestFactory(customer=self.customer)
        app = ApplicationFactory(
            customer=self.customer,
        )
        app.update_safely(
            application_status_id=ApplicationStatusCodes.CUSTOMER_ON_DELETION,
        )
        result = cancel_account_request_deletion(self.customer)
        self.assertIsNotNone(result)

    def test_success(self):
        AccountDeletionRequestFactory(customer=self.customer)
        account = AccountFactory(customer=self.customer)
        old_status_id = account.status_id
        account.status_id = JuloOneCodes.ACCOUNT_DELETION_ON_REVIEW
        account.save()
        AccountStatusHistoryFactory(
            account=account,
            status_old=account.status,
            status_new=StatusLookupFactory(status_code=JuloOneCodes.ACCOUNT_DELETION_ON_REVIEW),
            change_reason=AccountDeletionStatusChangeReasons.REQUEST_REASON,
        )

        app = ApplicationFactory(
            customer=self.customer,
            workflow=self.workflow,
        )
        initial_app_status = app.application_status_id
        ApplicationHistoryFactory(
            application_id=app.id,
            status_old=app.application_status_id,
            status_new=ApplicationStatusCodes.CUSTOMER_ON_DELETION,
            change_reason=AccountDeletionStatusChangeReasons.REQUEST_REASON,
        )
        app.update_safely(
            application_status_id=ApplicationStatusCodes.CUSTOMER_ON_DELETION,
        )

        result = cancel_account_request_deletion(self.customer)
        self.assertIsNotNone(result)

        updated_request = self.customer.accountdeletionrequest_set.last()
        self.assertEqual(updated_request.request_status, AccountDeletionRequestStatuses.CANCELLED)
        self.assertEqual(updated_request.verdict_reason, None)
        self.assertEqual(updated_request.verdict_date, None)
        self.assertEqual(updated_request.agent, None)

        updated_account = self.customer.account_set.last()
        self.assertEqual(updated_account.status_id, old_status_id)

        status_history = AccountStatusHistory.objects.filter(
            change_reason=AccountDeletionStatusChangeReasons.CANCEL_REASON,
            account=updated_account,
        ).last()
        self.assertIsNotNone(status_history)
        self.assertEqual(status_history.status_old_id, JuloOneCodes.ACCOUNT_DELETION_ON_REVIEW)
        self.assertEqual(status_history.status_new_id, updated_account.status_id)

        app_history = ApplicationHistory.objects.filter(
            change_reason=AccountDeletionStatusChangeReasons.CANCEL_REASON,
            application=app,
        ).last()
        self.assertIsNotNone(app_history)
        self.assertEqual(app_history.status_old, ApplicationStatusCodes.CUSTOMER_ON_DELETION)
        self.assertEqual(app_history.status_new, initial_app_status)


class TestGetOngoingAccountDeletionRequest(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()

    def test_not_exists(self):
        request = get_ongoing_account_deletion_request(self.customer)
        self.assertIsNone(request)

    def test_cancelled(self):
        AccountDeletionRequestFactory(
            customer=self.customer,
            request_status=AccountDeletionRequestStatuses.CANCELLED,
        )
        request = get_ongoing_account_deletion_request(self.customer)
        self.assertIsNone(request)

    def test_rejected(self):
        AccountDeletionRequestFactory(
            customer=self.customer,
            request_status=AccountDeletionRequestStatuses.REJECTED,
        )
        request = get_ongoing_account_deletion_request(self.customer)
        self.assertIsNone(request)

    def test_exists(self):
        deletion_request = AccountDeletionRequestFactory(
            customer=self.customer,
            request_status=AccountDeletionRequestStatuses.PENDING,
        )
        request = get_ongoing_account_deletion_request(self.customer)
        self.assertIsNotNone(request)

        self.assertEqual(deletion_request.id, request.id)
        self.assertEqual(deletion_request.customer, request.customer)
        self.assertEqual(deletion_request.request_status, request.request_status)
        self.assertEqual(deletion_request.reason, request.reason)
        self.assertEqual(deletion_request.detail_reason, request.detail_reason)


class TestGetOngoingAccountDeletionRequests(TestCase):
    def test_none_customer_ids(self):
        req = get_ongoing_account_deletion_requests(None)
        self.assertEqual(req, [])

    def test_empty_customer_ids(self):
        req = get_ongoing_account_deletion_requests([])
        self.assertEqual(req, [])

    def test_not_exists(self):
        req = get_ongoing_account_deletion_requests([1, 2, 3])
        self.assertEqual(len(req), 0)

    def test_exists(self):
        req1 = AccountDeletionRequestFactory()
        req2 = AccountDeletionRequestFactory()
        AccountDeletionRequestFactory()

        customer_ids = [
            -1,
            req1.customer_id,
            req2.customer_id,
        ]
        req = get_ongoing_account_deletion_requests(customer_ids)
        self.assertEqual(len(req), 2)


class TestIsShowCustomerDataMenu(TestCase):
    def setUp(self):
        self.setting = FeatureSettingFactory(
            feature_name='customer_data_change_request',
            is_active=True,
        )
        self.application = ApplicationJ1Factory()
        self.customer = self.application.customer

    def test_show_the_menu(self):
        self.assertTrue(is_show_customer_data_menu(self.customer))

    def test_feature_is_not_active(self):
        self.setting.is_active = False
        self.setting.save()
        self.assertFalse(is_show_customer_data_menu(self.customer))

    def test_no_application(self):
        customer = CustomerFactory()
        self.assertFalse(is_show_customer_data_menu(customer))

    def test_not_x190_application(self):
        self.application.application_status_id = ApplicationStatusCodes.FORM_PARTIAL
        self.application.save()
        self.assertFalse(is_show_customer_data_menu(self.customer))

    def test_not_a_julo_product(self):
        self.application.product_line_id = ProductLineCodes.GRAB
        self.application.save()
        self.assertFalse(is_show_customer_data_menu(self.customer))

    def test_show_menu_with_x185_application(self):
        self.application.application_status_id = ApplicationStatusCodes.CUSTOMER_ON_DELETION
        self.application.save()
        self.assertTrue(is_show_customer_data_menu(self.customer))


class TestCustomerDataChangeRequestHandler(TestCase):
    def setUp(self):
        self.setting = FeatureSettingFactory(
            feature_name='customer_data_change_request',
            is_active=True,
        )
        self.application = ApplicationJ1Factory()
        self.customer = self.application.customer
        self.handler = CustomerDataChangeRequestHandler(self.customer)

    def test_is_submitted_no_change_request(self):
        ret_val = self.handler.is_submitted()
        self.assertFalse(ret_val)

    def test_is_submitted_has_change_request(self):
        CustomerDataChangeRequestFactory(customer=self.customer, status='submitted')
        ret_val = self.handler.is_submitted()
        self.assertTrue(ret_val)

    def test_is_submitted_has_change_request_rejected(self):
        CustomerDataChangeRequestFactory(customer=self.customer, status='rejected')
        ret_val = self.handler.is_submitted()
        self.assertFalse(ret_val)

    def test_is_limit_reached_no_request(self):
        ret_val = self.handler.is_limit_reached()
        self.assertFalse(ret_val)

    def test_is_limit_reached_has_change_request_less_than_interval(self):
        with mock.patch.object(timezone, 'now') as mock_now:
            mock_now.return_value = datetime(2022, 10, 20, 12, 0, 0)
            CustomerDataChangeRequestFactory(customer=self.customer, status='approved')
            mock_now.return_value = datetime(2022, 10, 26, 0, 0, 0)
            ret_val = self.handler.is_limit_reached()
            self.assertTrue(ret_val)

    def test_is_limit_reached_has_change_request_more_than_interval(self):
        with mock.patch.object(timezone, 'now') as mock_now:
            mock_now.return_value = datetime(2022, 10, 20, 12, 0, 0)
            CustomerDataChangeRequestFactory(customer=self.customer, status='approved')

            mock_now.return_value = datetime(2022, 10, 27, 0, 0, 0)
            ret_val = self.handler.is_limit_reached()
            self.assertFalse(ret_val)

    def test_is_limit_reached_has_change_request_rejected(self):
        with mock.patch.object(timezone, 'now') as mock_now:
            mock_now.return_value = datetime(2022, 10, 20, 12, 0, 0)
            CustomerDataChangeRequestFactory(customer=self.customer, status='rejected')

            mock_now.return_value = datetime(2022, 10, 20, 12, 0, 1)
            ret_val = self.handler.is_limit_reached()
            self.assertFalse(ret_val)

    def test_get_permission_status(self):
        self.assertEqual('enabled', self.handler.get_permission_status())

        self.handler.is_show_customer_data_menu = mock.MagicMock(return_value=False)
        self.assertEqual('disabled', self.handler.get_permission_status())

        self.handler.is_show_customer_data_menu = mock.MagicMock(return_value=True)
        self.handler.is_submitted = mock.MagicMock(return_value=True)
        self.assertEqual('disabled', self.handler.get_permission_status())

        self.handler.is_show_customer_data_menu = mock.MagicMock(return_value=True)
        self.handler.is_submitted = mock.MagicMock(return_value=False)
        self.handler.is_limit_reached = mock.MagicMock(return_value=True)
        self.assertEqual('not_allowed', self.handler.get_permission_status())

        self.handler.is_show_customer_data_menu = mock.MagicMock(return_value=True)
        self.handler.is_submitted = mock.MagicMock(return_value=False)
        self.handler.is_limit_reached = mock.MagicMock(return_value=False)
        self.assertEqual('enabled', self.handler.get_permission_status())

    def test_last_approved_change_request(self):
        change_request = CustomerDataChangeRequestFactory(
            customer=self.customer,
            status='approved',
        )
        CustomerDataChangeRequestFactory(customer=self.customer, status='rejected')
        ret_val = self.handler.last_approved_change_request()
        self.assertEquals(change_request, ret_val)

    def test_last_submitted_change_request(self):
        CustomerDataChangeRequestFactory(
            customer=self.customer, status=CustomerDataChangeRequestConst.SubmissionStatus.SUBMITTED
        )
        last_request = CustomerDataChangeRequestFactory(
            customer=self.customer,
            status=CustomerDataChangeRequestConst.SubmissionStatus.SUBMITTED,
        )
        ret_val = self.handler.last_submitted_change_request()
        self.assertEquals(last_request, ret_val)

    def test_convert_application_data_to_change_request(self):
        ApplicationJ1Factory(
            customer=self.customer,
            address_provinsi='DKI JAKARTA',
            address_kabupaten='JAKARTA TIMUR',
            address_kecamatan='PASAR REBO',
            address_kelurahan='CIPINANG BESAR SELATAN',
            address_kodepos=13760,
            address_street_num='JL. RAYA BOGOR KM. 20',
            job_type='KARYAWAN',
            job_industry='PERDAGANGAN',
            job_description='KARYAWAN SWASTA',
            company_name='PT. JULO INDONESIA JAYA',
            company_phone_number='02112345678',
            payday=15,
            monthly_income=10000000,
            monthly_expenses=5000000,
            monthly_housing_cost=2000000,
            total_current_debt=1000000,
        )
        ret_val = self.handler.convert_application_data_to_change_request()
        self.assertIsInstance(ret_val, CustomerDataChangeRequest)
        self.assertEquals(0, CustomerDataChangeRequest.objects.count())
        self.assertEquals(self.customer, ret_val.customer)
        self.assertEquals('DKI JAKARTA', ret_val.address.provinsi)
        self.assertEquals('JAKARTA TIMUR', ret_val.address.kabupaten)
        self.assertEquals('PASAR REBO', ret_val.address.kecamatan)
        self.assertEquals('CIPINANG BESAR SELATAN', ret_val.address.kelurahan)
        self.assertEquals('13760', ret_val.address.kodepos)
        self.assertEquals('JL. RAYA BOGOR KM. 20', ret_val.address.detail)
        self.assertEquals('KARYAWAN', ret_val.job_type)
        self.assertEquals('PERDAGANGAN', ret_val.job_industry)
        self.assertEquals('KARYAWAN SWASTA', ret_val.job_description)
        self.assertEquals('PT. JULO INDONESIA JAYA', ret_val.company_name)
        self.assertEquals('02112345678', ret_val.company_phone_number)
        self.assertEquals(15, ret_val.payday)
        self.assertEquals(10000000, ret_val.monthly_income)
        self.assertEquals(5000000, ret_val.monthly_expenses)
        self.assertEquals(2000000, ret_val.monthly_housing_cost)
        self.assertEquals(1000000, ret_val.total_current_debt)

    @patch(
        'juloserver.customer_module.services.customer_related.CustomerDataChangeRequestHandler.store_payday_change_from_redis_to_raw_data'
    )
    def test_create_change_request(self, mock_store_payday_change_from_redis_to_raw_data):
        mock_store_payday_change_from_redis_to_raw_data.return_value = True
        raw_data = {
            'address_street_num': 'Jl. Gandaria I No. 1',
            'address_provinsi': 'DKI Jakarta',
            'address_kabupaten': 'Jakarta Selatan',
            'address_kecamatan': 'Kebayoran Baru',
            'address_kelurahan': 'Gandaria Utara',
            'address_kodepos': '12140',
            'address_latitude': 1.2,
            'address_longitude': 3.4,
            'job_type': 'Pegawai negeri',
            'job_industry': 'perbankan',
            'job_description': 'mengelola uang',
            'company_name': 'PT. Bank Julo',
            'company_phone_number': '0211234567',
            'payday': 15,
            'monthly_income': 10000000,
            'monthly_expenses': 5000000,
            'monthly_housing_cost': 2000000,
            'total_current_debt': 1000000,
            'last_education': 'S1',
            'app_version': '1.0.0',
            'android_id': '1234567890',
            'latitude': 1.0,
            'longitude': 2.0,
            'company_proof_image_id': ImageFactory(
                image_source=self.customer.id,
                image_type='company_proof',
            ).id,
            'paystub_image_id': ImageFactory(
                image_source=self.customer.id,
                image_type='paystub',
            ).id,
            'address_transfer_certificate_image_id': ImageFactory(
                image_source=self.customer.id,
                image_type='address_transfer_certificate',
            ).id,
            'payday_change_reason': None,
            'payday_change_proof_image_id': None,
        }
        status, ret_val = self.handler.create_change_request(raw_data, source='App')
        self.assertEquals(True, status)
        self.assertIsInstance(ret_val, CustomerDataChangeRequest)
        self.assertEquals(1, CustomerDataChangeRequest.objects.count())
        self.assertEquals(self.customer, ret_val.customer)
        self.assertEquals(self.application, ret_val.application)
        self.assertIsNotNone(ret_val.company_proof_image_id)
        self.assertIsNotNone(ret_val.paystub_image_id)
        self.assertIsNotNone(ret_val.address_transfer_certificate_image_id)
        self.assertEquals('Jl. Gandaria I No. 1', ret_val.address.detail)
        self.assertEquals('DKI Jakarta', ret_val.address.provinsi)
        self.assertEquals('Jakarta Selatan', ret_val.address.kabupaten)
        self.assertEquals('Kebayoran Baru', ret_val.address.kecamatan)
        self.assertEquals('Gandaria Utara', ret_val.address.kelurahan)
        self.assertEquals('12140', ret_val.address.kodepos)
        self.assertEquals(1.2, ret_val.address.latitude)
        self.assertEquals(3.4, ret_val.address.longitude)
        self.assertEquals('Pegawai negeri', ret_val.job_type)
        self.assertEquals('perbankan', ret_val.job_industry)
        self.assertEquals('mengelola uang', ret_val.job_description)
        self.assertEquals('PT. Bank Julo', ret_val.company_name)
        self.assertEquals('0211234567', ret_val.company_phone_number)
        self.assertEquals(15, ret_val.payday)
        self.assertEquals(10000000, ret_val.monthly_income)
        self.assertEquals(5000000, ret_val.monthly_expenses)
        self.assertEquals(2000000, ret_val.monthly_housing_cost)
        self.assertEquals(1000000, ret_val.total_current_debt)
        self.assertEquals('App', ret_val.source)
        self.assertEquals('1.0.0', ret_val.app_version)
        self.assertEquals('1234567890', ret_val.android_id)
        self.assertEquals(1.0, ret_val.latitude)
        self.assertEquals(2.0, ret_val.longitude)
        self.assertEquals('submitted', ret_val.status)
        self.assertEquals(None, ret_val.payday_change_reason)
        self.assertIsNone(ret_val.payday_change_proof_image_id)

    @patch(
        'juloserver.customer_module.services.customer_related.CustomerDataChangeRequestHandler.store_payday_change_from_redis_to_raw_data'
    )
    def test_create_change_request_not_changed_address(
        self, mock_store_payday_change_from_redis_to_raw_data
    ):
        mock_store_payday_change_from_redis_to_raw_data.return_value = True
        change_request = CustomerDataChangeRequestFactory(
            customer=self.customer,
            status='approved',
            address=AddressFactory(
                provinsi='DKI Jakarta',
                kabupaten='Jakarta Selatan',
                kecamatan='Kebayoran Baru',
                kelurahan='Gandaria Utara',
                kodepos='12140',
                detail='Jl. Gandaria I No. 1',
                latitude=1.2,
                longitude=3.4,
            ),
        )
        raw_data = {
            'address_street_num': 'Jl. Gandaria I No. 1',
            'address_provinsi': 'DKI Jakarta',
            'address_kabupaten': 'Jakarta Selatan',
            'address_kecamatan': 'Kebayoran Baru',
            'address_kelurahan': 'Gandaria Utara',
            'address_kodepos': '12140',
            'address_latitude': 1.2,
            'address_longitude': 3.4,
            'job_type': 'Pegawai negeri',
            'job_industry': 'perbankan',
            'job_description': 'mengelola uang',
            'company_name': 'PT. Bank Julo',
            'company_phone_number': '0211234567',
            'payday': 15,
            'monthly_income': 10000000,
            'monthly_expenses': 5000000,
            'monthly_housing_cost': 2000000,
            'total_current_debt': 1000000,
            'last_education': 'S1',
            'app_version': '1.0.0',
            'android_id': '1234567890',
            'latitude': 1.0,
            'longitude': 2.0,
            'company_proof_image_id': ImageFactory(
                image_source=self.customer.id,
                image_type='company_proof',
            ).id,
            'paystub_image_id': ImageFactory(
                image_source=self.customer.id,
                image_type='paystub',
            ).id,
        }
        status, ret_val = self.handler.create_change_request(raw_data, source='App')
        self.assertEquals(change_request.address.id, ret_val.address.id)

    @patch(
        'juloserver.customer_module.services.customer_related.CustomerDataChangeRequestHandler.store_payday_change_from_redis_to_raw_data'
    )
    def test_create_change_request_not_changed_occupation(
        self, mock_store_payday_change_from_redis_to_raw_data
    ):
        mock_store_payday_change_from_redis_to_raw_data.return_value = None
        change_request = CustomerDataChangeRequestFactory(
            customer=self.customer,
            status='approved',
            job_type='Pegawai negeri',
            job_industry='perbankan',
            job_description='mengelola uang',
            company_name='PT. Bank Julo',
            company_phone_number='0211234567',
            payday=15,
        )
        raw_data = {
            'address_street_num': 'Jl. Gandaria I No. 1',
            'address_provinsi': 'DKI Jakarta',
            'address_kabupaten': 'Jakarta Selatan',
            'address_kecamatan': 'Kebayoran Baru',
            'address_kelurahan': 'Gandaria Utara',
            'address_kodepos': '12140',
            'address_latitude': 1.2,
            'address_longitude': 3.4,
            'job_type': 'Pegawai negeri',
            'job_industry': 'perbankan',
            'job_description': 'mengelola uang',
            'company_name': 'PT. Bank Julo',
            'company_phone_number': '0211234567',
            'payday': 15,
            'monthly_income': 10000000,
            'monthly_expenses': 5000000,
            'monthly_housing_cost': 2000000,
            'total_current_debt': 1000000,
            'last_education': 'S1',
            'app_version': '1.0.0',
            'android_id': '1234567890',
            'latitude': 1.0,
            'longitude': 2.0,
            'paystub_image_id': ImageFactory(
                image_source=self.customer.id,
                image_type='paystub',
            ).id,
        }
        ret_val = self.handler.create_change_request(raw_data, source='App')
        self.assertIsNotNone(ret_val)

    @patch(
        'juloserver.customer_module.services.customer_related.CustomerDataChangeRequestHandler.store_payday_change_from_redis_to_raw_data'
    )
    def test_create_change_request_previous_approved_request(
        self, mock_store_payday_change_from_redis_to_raw_data
    ):
        mock_store_payday_change_from_redis_to_raw_data.return_value = True
        approved_change_request = CustomerDataChangeRequestFactory(
            customer=self.customer,
            status='approved',
        )
        rejected_change_request = CustomerDataChangeRequestFactory(
            customer=self.customer,
            status='rejected',
            job_type='Pegawai negeri',
            job_industry='perbankan',
            job_description='mengelola uang',
            company_name='PT. Bank Julo',
            company_phone_number='0211234567',
            payday=15,
            monthly_income=10000000,
            monthly_expenses=5000000,
            monthly_housing_cost=2000000,
            total_current_debt=1000000,
        )

        raw_data = {
            'address_street_num': 'Jl. Gandaria I No. 1',
            'address_provinsi': 'DKI Jakarta',
            'address_kabupaten': 'Jakarta Selatan',
            'address_kecamatan': 'Kebayoran Baru',
            'address_kelurahan': 'Gandaria Utara',
            'address_kodepos': '12140',
            'address_latitude': 1.2,
            'address_longitude': 3.4,
            'job_type': 'Pegawai negeri',
            'job_industry': 'perbankan',
            'job_description': 'mengelola uang',
            'company_name': 'PT. Bank Julo',
            'company_phone_number': '0211234567',
            'payday': 15,
            'monthly_income': 10000000,
            'monthly_expenses': 5000000,
            'monthly_housing_cost': 2000000,
            'last_education': 'S1',
            'total_current_debt': 1000000,
            'app_version': '1.0.0',
            'android_id': '1234567890',
            'latitude': 1.0,
            'longitude': 2.0,
        }
        with self.assertRaises(CustomerApiException) as context:
            self.handler.create_change_request(raw_data, source='App')

        res = ast.literal_eval(str(context.exception))
        self.assertIn('paystub_image_id', res)

    @patch(
        'juloserver.customer_module.services.customer_related.CustomerDataChangeRequestHandler.store_payday_change_from_redis_to_raw_data'
    )
    def test_create_change_request_invalid_characters(
        self, mock_store_payday_change_from_redis_to_raw_data
    ):
        mock_store_payday_change_from_redis_to_raw_data.return_value = True
        raw_data = {
            'address_street_num': 'Jl. Gandaria I No. 1^^**',
            'address_provinsi': 'DKI Jakarta',
            'address_kabupaten': 'Jakarta Selatan',
            'address_kecamatan': 'Kebayoran Baru',
            'address_kelurahan': 'Gandaria Utara',
            'address_kodepos': '12140',
            'address_latitude': 1.2,
            'address_longitude': 3.4,
            'job_type': 'Pegawai negeri',
            'job_industry': 'perbankan',
            'job_description': 'mengelola uang',
            'company_name': 'PT. Bank Julo',
            'company_phone_number': '0211234567',
            'payday': 15,
            'monthly_income': 10000000,
            'monthly_expenses': 5000000,
            'monthly_housing_cost': 2000000,
            'total_current_debt': 1000000,
            'app_version': '1.0.0',
            'android_id': '1234567890',
            'latitude': 1.0,
            'longitude': 2.0,
            'company_proof_image_id': ImageFactory(
                image_source=self.customer.id,
                image_type='company_proof',
            ).id,
            'paystub_image_id': ImageFactory(
                image_source=self.customer.id,
                image_type='paystub',
            ).id,
            'address_transfer_certificate_image_id': ImageFactory(
                image_source=self.customer.id,
                image_type='address_transfer_certificate',
            ).id,
            'payday_change_reason': 'lainnya',
            'payday_change_proof_image_id': CXDocumentFactory(
                document_source=self.customer.id,
                document_type='payday_customer_change_request',
            ).id,
        }
        with self.assertRaises(CustomerApiException) as ctx:
            self.handler.create_change_request(raw_data, source='App')


class TestCustomerDataChangeRequestNotification(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()
        self.application = ApplicationFactory(customer=self.customer)
        self.mock_email_service = mock.MagicMock()
        self.mock_email_service.send_email.return_value.sg_message_id = '1234'
        self.mock_pn_client = mock.MagicMock()
        self.mock_pn_client.send_downstream_message.return_value.status_code = 201
        self.mock_setting = mock.MagicMock()
        self.mock_setting.is_active.return_value = True
        self.mock_device_repository = mock.MagicMock()
        self.mock_device_repository.get_active_fcm_id.return_value = 'fcm-id'

    @mock.patch(
        'juloserver.customer_module.tasks.customer_related_tasks.send_customer_data_change_request_notification_email'
    )
    @mock.patch(
        'juloserver.customer_module.tasks.customer_related_tasks.send_customer_data_change_request_notification_pn'
    )
    def test_send_notification(self, mock_pn_task, mock_email_task):
        change_request = CustomerDataChangeRequestFactory()
        notification = CustomerDataChangeRequestNotification(
            change_request=change_request,
        )
        notification.email_service = self.mock_email_service
        notification.setting = self.mock_setting
        notification.pn_client = self.mock_pn_client

        notification.send_notification()
        mock_pn_task.delay.assert_called_once_with(change_request.id)
        mock_email_task.delay.assert_called_once_with(change_request.id)

    def test_send_email(self):
        change_request = CustomerDataChangeRequestFactory(
            address=AddressFactory(
                provinsi='DKI Jakarta',
                kabupaten='Jakarta Selatan',
                kecamatan='Kebayoran Baru',
                kelurahan='Gandaria Utara',
                kodepos='12140',
                detail='Jl. Gandaria I No. 1',
                latitude=1.2,
                longitude=3.4,
            ),
            payday=10,
            job_type="Pegawai negeri",
            job_industry="perbankan",
            job_description="mengelola uang",
            company_name="PT. JULO",
            company_phone_number='0211234567',
            monthly_income=10000000,
            monthly_expenses=2000000,
            monthly_housing_cost=3000000,
            total_current_debt=4000000,
            status='approved',
        )
        notification = CustomerDataChangeRequestNotification(
            change_request=change_request,
        )
        notification.email_service = self.mock_email_service
        notification.setting = self.mock_setting
        notification.pn_client = self.mock_pn_client

        ret_val = notification.send_email()
        self.assertTrue(ret_val)
        self.mock_email_service.prepare_email_context.assert_called_once_with(
            change_request.customer,
            application_id=change_request.application_id,
            changes_data=[
                (
                    'address',
                    'Alamat Tempat Tinggal',
                    None,
                    'Jl. Gandaria I No. 1, Gandaria Utara, Kebayoran Baru, Jakarta Selatan, DKI Jakarta, 12140',
                ),
                ('job_type', 'Tipe Pekerjaan', '', 'Pegawai negeri'),
                ('job_industry', 'Bidang Pekerjaan', '', 'perbankan'),
                ('job_description', 'Posisi Pekerjaan', '', 'mengelola uang'),
                ('company_name', 'Nama Perusahaan', '', 'PT. JULO'),
                ('company_phone_number', 'Nomor Telepon Perusahaan', '', '0211234567'),
                ('payday', 'Tanggal Gajian', None, 10),
                ('monthly_income', 'Total Penghasilan Bulanan', None, 'Rp 10.000.000'),
                (
                    'monthly_expenses',
                    'Total Pengeluaran Rumah Tangga Bulanan',
                    None,
                    'Rp 2.000.000',
                ),
                ('monthly_housing_cost', 'Total Cicilan/Sewa Rumah Bulanan', None, 'Rp 3.000.000'),
                ('total_current_debt', 'Total Cicilan Hutang Bulanan', None, 'Rp 4.000.000'),
            ],
        )
        self.mock_email_service.send_email.assert_called_once_with(
            template_code='customer_data_change_request_approved',
            subject='Perubahan Data Pribadi Berhasil',
            email_to=change_request.customer.email,
            context=mock.ANY,
            content=mock.ANY,
        )

    def test_send_email_rejected(self):
        change_request = CustomerDataChangeRequestFactory(
            address=AddressFactory(
                provinsi='DKI Jakarta',
                kabupaten='Jakarta Selatan',
                kecamatan='Kebayoran Baru',
                kelurahan='Gandaria Utara',
                kodepos='12140',
                detail='Jl. Gandaria I No. 1',
                latitude=1.2,
                longitude=3.4,
            ),
            payday=10,
            job_type="Pegawai negeri",
            job_industry="perbankan",
            job_description="mengelola uang",
            company_name="PT. JULO",
            company_phone_number='0211234567',
            monthly_income=10000000,
            monthly_expenses=2000000,
            monthly_housing_cost=3000000,
            total_current_debt=4000000,
            status='rejected',
        )
        notification = CustomerDataChangeRequestNotification(
            change_request=change_request,
        )
        notification.email_service = self.mock_email_service
        notification.setting = self.mock_setting
        notification.pn_client = self.mock_pn_client

        ret_val = notification.send_email()
        self.assertTrue(ret_val)
        self.mock_email_service.prepare_email_context.assert_called_once_with(
            change_request.customer,
            application_id=change_request.application_id,
            changes_data=[
                (
                    'address',
                    'Alamat Tempat Tinggal',
                    None,
                    'Jl. Gandaria I No. 1, Gandaria Utara, Kebayoran Baru, Jakarta Selatan, DKI Jakarta, 12140',
                ),
                ('job_type', 'Tipe Pekerjaan', '', 'Pegawai negeri'),
                ('job_industry', 'Bidang Pekerjaan', '', 'perbankan'),
                ('job_description', 'Posisi Pekerjaan', '', 'mengelola uang'),
                ('company_name', 'Nama Perusahaan', '', 'PT. JULO'),
                ('company_phone_number', 'Nomor Telepon Perusahaan', '', '0211234567'),
                ('payday', 'Tanggal Gajian', None, 10),
                ('monthly_income', 'Total Penghasilan Bulanan', None, 'Rp 10.000.000'),
                (
                    'monthly_expenses',
                    'Total Pengeluaran Rumah Tangga Bulanan',
                    None,
                    'Rp 2.000.000',
                ),
                ('monthly_housing_cost', 'Total Cicilan/Sewa Rumah Bulanan', None, 'Rp 3.000.000'),
                ('total_current_debt', 'Total Cicilan Hutang Bulanan', None, 'Rp 4.000.000'),
            ],
        )
        self.mock_email_service.send_email.assert_called_once_with(
            template_code='customer_data_change_request_rejected',
            subject='Perubahan Data Pribadi Gagal',
            email_to=change_request.customer.email,
            context=mock.ANY,
            content=mock.ANY,
        )

    def test_send_email_no_template(self):
        change_request = CustomerDataChangeRequestFactory(status='submitted')
        notification = CustomerDataChangeRequestNotification(change_request=change_request)
        notification.email_service = self.mock_email_service
        notification.setting = self.mock_setting
        notification.pn_client = self.mock_pn_client

        ret_val = notification.send_email()
        self.assertFalse(ret_val)

    def test_send_pn(self):
        change_request = CustomerDataChangeRequestFactory(status='approved')
        notification = CustomerDataChangeRequestNotification(change_request=change_request)
        notification.email_service = self.mock_email_service
        notification.setting = self.mock_setting
        notification.pn_client = self.mock_pn_client
        notification.device_repository = self.mock_device_repository

        ret_val = notification.send_pn()
        self.assertTrue(ret_val)

        expected_pn_data = {
            "customer_id": change_request.customer_id,
            "application_id": change_request.application_id,
            "destination_page": 'profile',
            'title': 'Perubahan Data Pribadi Disetujui',
            'body': 'Cek data pribadi terbaru kamu di sini, ya!',
        }
        self.mock_pn_client.send_downstream_message.assert_called_once_with(
            registration_ids=['fcm-id'],
            template_code='customer_data_change_request_approved',
            data=expected_pn_data,
        )
        self.mock_device_repository.get_active_fcm_id.assert_called_once_with(
            change_request.customer_id,
        )

    def test_send_pn_rejected(self):
        change_request = CustomerDataChangeRequestFactory(status='rejected')
        notification = CustomerDataChangeRequestNotification(change_request=change_request)
        notification.email_service = self.mock_email_service
        notification.setting = self.mock_setting
        notification.pn_client = self.mock_pn_client
        notification.device_repository = self.mock_device_repository

        ret_val = notification.send_pn()
        self.assertTrue(ret_val)

        expected_pn_data = {
            "customer_id": change_request.customer_id,
            "application_id": change_request.application_id,
            "destination_page": 'profile',
            'title': 'Perubahan Data Pribadi Ditolak',
            'body': (
                'Data pribadimu gagal diubah. '
                'Kamu bisa coba ubah data lagi dalam beberapa saat, ya.'
            ),
        }
        self.mock_pn_client.send_downstream_message.assert_called_once_with(
            registration_ids=['fcm-id'],
            template_code='customer_data_change_request_rejected',
            data=expected_pn_data,
        )

    def test_send_pn_no_template(self):
        change_request = CustomerDataChangeRequestFactory(status='submitted')
        notification = CustomerDataChangeRequestNotification(change_request=change_request)
        notification.email_service = self.mock_email_service
        notification.setting = self.mock_setting
        notification.pn_client = self.mock_pn_client
        notification.device_repository = self.mock_device_repository

        ret_val = notification.send_pn()
        self.assertFalse(ret_val)

    def test_send_pn_no_fcm(self):
        change_request = CustomerDataChangeRequestFactory(status='rejected')
        notification = CustomerDataChangeRequestNotification(change_request=change_request)
        notification.email_service = self.mock_email_service
        notification.setting = self.mock_setting
        notification.pn_client = self.mock_pn_client
        notification.device_repository = self.mock_device_repository
        self.mock_device_repository.get_active_fcm_id.return_value = None

        ret_val = notification.send_pn()
        self.assertFalse(ret_val)


class TestGetCustomerDataRequestFieldChanges(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()
        self.application = ApplicationJ1Factory(customer=self.customer)
        self.prev_change_request = CustomerDataChangeRequestFactory(
            customer=self.customer,
            application=self.application,
            address=AddressFactory(
                provinsi='DKI Jakarta',
                kabupaten='Jakarta Selatan',
                kecamatan='Kebayoran Baru',
                kelurahan='Gandaria Utara',
                kodepos='12140',
                detail='Jl. Gandaria I No. 1',
                latitude=1.2,
                longitude=3.4,
            ),
            payday=10,
            job_type="Pegawai negeri",
            job_industry="perbankan",
            job_description="mengelola uang",
            company_name="PT. JULO",
            company_phone_number='0211234567',
            monthly_income=10000000,
            monthly_expenses=2000000,
            monthly_housing_cost=3000000,
            total_current_debt=4000000,
            status='approved',
        )

    def test_no_changes(self):
        change_request = CustomerDataChangeRequestFactory(
            customer=self.customer,
            application=self.application,
            address=AddressFactory(
                provinsi='DKI Jakarta',
                kabupaten='Jakarta Selatan',
                kecamatan='Kebayoran Baru',
                kelurahan='Gandaria Utara',
                kodepos='12140',
                detail='Jl. Gandaria I No. 1',
                latitude=1.2,
                longitude=3.4,
            ),
            payday=10,
            job_type="Pegawai negeri",
            job_industry="perbankan",
            job_description="mengelola uang",
            company_name="PT. JULO",
            company_phone_number='0211234567',
            monthly_income=10000000,
            monthly_expenses=2000000,
            monthly_housing_cost=3000000,
            total_current_debt=4000000,
            status='approved',
        )
        changes, _, _ = get_customer_data_request_field_changes(change_request)
        self.assertEqual(changes, [])

    def test_changes_to_empty(self):
        change_request = CustomerDataChangeRequestFactory(
            customer=self.customer,
            application=self.application,
            address=None,
            payday=0,
            job_type="",
            job_industry="",
            job_description="",
            company_name="",
            company_phone_number="",
            monthly_income=0,
            monthly_expenses=0,
            monthly_housing_cost=0,
            total_current_debt=0,
            status='approved',
        )
        changes, _, _ = get_customer_data_request_field_changes(change_request)
        expected_changes = [
            (
                'address',
                'Alamat Tempat Tinggal',
                'Jl. Gandaria I No. 1, Gandaria Utara, Kebayoran Baru, Jakarta Selatan, DKI '
                'Jakarta, 12140',
                None,
            ),
            ('job_type', 'Tipe Pekerjaan', 'Pegawai negeri', ''),
            ('job_industry', 'Bidang Pekerjaan', 'perbankan', ''),
            ('job_description', 'Posisi Pekerjaan', 'mengelola uang', ''),
            ('company_name', 'Nama Perusahaan', 'PT. JULO', ''),
            ('company_phone_number', 'Nomor Telepon Perusahaan', '0211234567', ''),
            ('payday', 'Tanggal Gajian', 10, 0),
            ('monthly_income', 'Total Penghasilan Bulanan', 'Rp 10.000.000', None),
            ('monthly_expenses', 'Total Pengeluaran Rumah Tangga Bulanan', 'Rp 2.000.000', None),
            ('monthly_housing_cost', 'Total Cicilan/Sewa Rumah Bulanan', 'Rp 3.000.000', None),
            ('total_current_debt', 'Total Cicilan Hutang Bulanan', 'Rp 4.000.000', None),
        ]
        self.assertEqual(expected_changes, changes)


class TestIsCustomerResetPhoneNumberRateLimited(TestCase):
    @mock.patch('juloserver.customer_module.services.customer_related.get_redis_client')
    def test_not_rate_limited(
        self,
        mock_get_redis_client,
    ):
        mock_redis_client = mock.MagicMock()
        mock_redis_client.get.return_value = 0
        mock_get_redis_client.return_value = mock_redis_client

        feature_setting = FeatureSettingFactory(
            feature_name='reset_phone_number',
            is_active=True,
            parameters={
                "ttl": 1,
                "max_count": 1,
            },
        )

        val = is_device_reset_phone_number_rate_limited(0, feature_setting)
        self.assertFalse(val)

    @mock.patch('juloserver.customer_module.services.customer_related.get_redis_client')
    def test_rate_limited(
        self,
        mock_get_redis_client,
    ):
        mock_redis_client = mock.MagicMock()
        mock_redis_client.get.return_value = 1
        mock_get_redis_client.return_value = mock_redis_client

        feature_setting = FeatureSettingFactory(
            feature_name='reset_phone_number',
            is_active=True,
            parameters={
                "ttl": 1,
                "max_count": 1,
            },
        )

        val = is_device_reset_phone_number_rate_limited(0, feature_setting)
        self.assertTrue(val)

    @mock.patch('juloserver.customer_module.services.customer_related.get_redis_client')
    def test_not_rate_limited_none_value(
        self,
        mock_get_redis_client,
    ):
        mock_redis_client = mock.MagicMock()
        mock_redis_client.get.return_value = None
        mock_get_redis_client.return_value = mock_redis_client

        feature_setting = FeatureSettingFactory(
            feature_name='reset_phone_number',
            is_active=True,
            parameters={
                "ttl": 1,
                "max_count": 1,
            },
        )

        val = is_device_reset_phone_number_rate_limited(0, feature_setting)
        self.assertFalse(val)


class TestPrepareResetPhoneRequest(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()

    @mock.patch('juloserver.customer_module.services.customer_related.generate_phone_number_key')
    def test_happy_path(
        self,
        mock_generate_phone_number_key,
    ):
        mock_generate_phone_number_key.return_value = 'key'

        feature_setting = FeatureSettingFactory(
            feature_name=MobileFeatureNameConst.RESET_PHONE_NUMBER,
            is_active=True,
            parameters={
                "ttl": 1,
                "max_count": 1,
                "link_exp_time": {"days": 0, "hours": 24, "minutes": 0},
            },
        )

        val = prepare_reset_phone_request(self.customer, feature_setting)
        self.assertIsNotNone(val)


class TestProcessIncomingAccountDeletionRequest(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()

    @mock.patch(
        'juloserver.customer_module.services.customer_related.get_ongoing_account_deletion_requests'
    )
    @mock.patch('juloserver.julo.models.Customer.account', new_callable=mock.PropertyMock)
    @mock.patch(
        'juloserver.customer_module.services.customer_related.increment_device_reset_phone_number_rate_limiter'
    )
    @mock.patch(
        'juloserver.customer_module.services.customer_related.send_reset_phone_number_email_task.delay'
    )
    @mock.patch('juloserver.customer_module.services.customer_related.prepare_reset_phone_request')
    @mock.patch(
        'juloserver.customer_module.services.customer_related.is_device_reset_phone_number_rate_limited'
    )
    @mock.patch('juloserver.customer_module.services.customer_related.MobileFeatureSetting')
    def test_happy_path(
        self,
        mock_mobile_feature_setting,
        mock_is_device_reset_phone_number_rate_limited,
        mock_prepare_reset_phone_request,
        mock_send_reset_phone_number_email,
        mock_increment_device_reset_phone_number_rate_limiter,
        mock_account_property,
        mock_get_ongoing_account_deletion_requests,
    ):
        mock_get_ongoing_account_deletion_requests.return_value = []
        mock_account = mock.MagicMock(status_id=420)
        mock_account_property.return_value = mock_account
        mock_mobile_feature_setting.objects.get.return_value = FeatureSettingFactory(
            feature_name='account_deletion',
            is_active=True,
            parameters={
                "ttl": 1,
                "max_count": 1,
            },
        )
        mock_is_device_reset_phone_number_rate_limited.return_value = False
        mock_prepare_reset_phone_request.return_value = 'key'

        mock_result = mock.MagicMock()
        mock_result.exists.return_value = False

        mock_customer = mock.MagicMock()
        mock_customer.application_set.filter.return_value = mock_result

        val = process_incoming_change_phone_number_request(mock_customer, 'key')
        self.assertIsNone(val)

    @mock.patch(
        'juloserver.customer_module.services.customer_related.get_ongoing_account_deletion_requests'
    )
    @mock.patch(
        'juloserver.customer_module.services.customer_related.increment_device_reset_phone_number_rate_limiter'
    )
    @mock.patch('juloserver.customer_module.services.customer_related.prepare_reset_phone_request')
    @mock.patch(
        'juloserver.customer_module.services.customer_related.is_device_reset_phone_number_rate_limited'
    )
    @mock.patch('juloserver.customer_module.services.customer_related.MobileFeatureSetting')
    def test_invalid_application_status(
        self,
        mock_mobile_feature_setting,
        mock_is_device_reset_phone_number_rate_limited,
        mock_prepare_reset_phone_request,
        mock_increment_device_reset_phone_number_rate_limiter,
        mock_get_ongoing_account_deletion_requests,
    ):
        mock_get_ongoing_account_deletion_requests.return_value = []
        mock_mobile_feature_setting.objects.get.return_value = FeatureSettingFactory(
            feature_name='account_deletion',
            is_active=True,
            parameters={
                "ttl": 1,
                "max_count": 1,
            },
        )
        mock_is_device_reset_phone_number_rate_limited.return_value = False
        mock_prepare_reset_phone_request.return_value = 'key'

        mock_result = mock.MagicMock()
        mock_result.exists.return_value = True

        mock_customer = mock.MagicMock()
        mock_customer.application_set.filter.return_value = mock_result

        val = process_incoming_change_phone_number_request(mock_customer, 'key')
        self.assertEqual(val, ChangePhoneLostAccess.ErrorMessages.DEFAULT)

    @mock.patch(
        'juloserver.customer_module.services.customer_related.get_ongoing_account_deletion_requests'
    )
    @mock.patch(
        'juloserver.customer_module.services.customer_related.increment_device_reset_phone_number_rate_limiter'
    )
    @mock.patch('juloserver.julo.models.Customer.account', new_callable=mock.PropertyMock)
    @mock.patch(
        'juloserver.customer_module.services.customer_related.send_reset_phone_number_email_task.delay'
    )
    @mock.patch('juloserver.customer_module.services.customer_related.prepare_reset_phone_request')
    @mock.patch(
        'juloserver.customer_module.services.customer_related.is_device_reset_phone_number_rate_limited'
    )
    @mock.patch('juloserver.customer_module.services.customer_related.MobileFeatureSetting')
    def test_invalid_account_status(
        self,
        mock_mobile_feature_setting,
        mock_is_device_reset_phone_number_rate_limited,
        mock_prepare_reset_phone_request,
        mock_send_reset_phone_number_email,
        mock_account_property,
        mock_increment_device_reset_phone_number_rate_limiter,
        mock_get_ongoing_account_deletion_requests,
    ):
        mock_get_ongoing_account_deletion_requests.return_value = []
        mock_account = mock.MagicMock(status_id=425)
        mock_account_property.return_value = mock_account

        mock_mobile_feature_setting.objects.get.return_value = FeatureSettingFactory(
            feature_name='account_deletion',
            is_active=True,
            parameters={
                "ttl": 1,
                "max_count": 1,
            },
        )
        mock_is_device_reset_phone_number_rate_limited.return_value = False
        mock_prepare_reset_phone_request.return_value = 'key'

        val = process_incoming_change_phone_number_request(self.customer, 'key')
        self.assertEqual(val, ChangePhoneLostAccess.ErrorMessages.DEFAULT)

    @mock.patch(
        'juloserver.customer_module.services.customer_related.is_device_reset_phone_number_rate_limited'
    )
    @mock.patch('juloserver.customer_module.services.customer_related.MobileFeatureSetting')
    def test_device_is_rate_limited(
        self,
        mock_mobile_feature_setting,
        mock_is_device_reset_phone_number_rate_limited,
    ):
        mock_mobile_feature_setting.objects.get.return_value = FeatureSettingFactory(
            feature_name='account_deletion',
            is_active=True,
            parameters={
                "ttl": 1,
                "max_count": 1,
            },
        )
        mock_is_device_reset_phone_number_rate_limited.return_value = True

        val = process_incoming_change_phone_number_request(self.customer, 'key')
        self.assertEqual(val, ChangePhoneLostAccess.ErrorMessages.RATE_LIMIT_ERROR)

    @mock.patch('juloserver.julo.models.Customer.account', new_callable=mock.PropertyMock)
    @mock.patch(
        'juloserver.customer_module.services.customer_related.increment_device_reset_phone_number_rate_limiter'
    )
    @mock.patch(
        'juloserver.customer_module.services.customer_related.is_device_reset_phone_number_rate_limited'
    )
    @mock.patch('juloserver.customer_module.services.customer_related.MobileFeatureSetting')
    def test_customer_no_account(
        self,
        mock_mobile_feature_setting,
        mock_is_device_reset_phone_number_rate_limited,
        mock_increment_device_reset_phone_number_rate_limiter,
        mock_account_property,
    ):
        mock_account_property.return_value = None
        mock_mobile_feature_setting.objects.get.return_value = FeatureSettingFactory(
            feature_name='account_deletion',
            is_active=True,
            parameters={
                "ttl": 1,
                "max_count": 1,
            },
        )
        mock_is_device_reset_phone_number_rate_limited.return_value = False

        val = process_incoming_change_phone_number_request(self.customer, 'key')
        self.assertEqual(val, ChangePhoneLostAccess.ErrorMessages.DEFAULT)

    @mock.patch('juloserver.julo.models.Customer.account', new_callable=mock.PropertyMock)
    @mock.patch(
        'juloserver.customer_module.services.customer_related.increment_device_reset_phone_number_rate_limiter'
    )
    @mock.patch(
        'juloserver.customer_module.services.customer_related.is_device_reset_phone_number_rate_limited'
    )
    @mock.patch('juloserver.customer_module.services.customer_related.MobileFeatureSetting')
    def test_customer_no_phone(
        self,
        mock_mobile_feature_setting,
        mock_is_device_reset_phone_number_rate_limited,
        mock_increment_device_reset_phone_number_rate_limiter,
        mock_account_property,
    ):
        mock_account = mock.MagicMock(status_id=420)
        mock_account_property.return_value = mock_account
        mock_mobile_feature_setting.objects.get.return_value = FeatureSettingFactory(
            feature_name='account_deletion',
            is_active=True,
            parameters={
                "ttl": 1,
                "max_count": 1,
            },
        )
        mock_is_device_reset_phone_number_rate_limited.return_value = False

        customer = self.customer
        customer.phone = None

        val = process_incoming_change_phone_number_request(customer, 'key')
        self.assertEqual(val, ChangePhoneLostAccess.ErrorMessages.DEFAULT)

    @mock.patch(
        'juloserver.customer_module.services.customer_related.get_ongoing_account_deletion_requests'
    )
    @mock.patch('juloserver.julo.models.Customer.account', new_callable=mock.PropertyMock)
    @mock.patch(
        'juloserver.customer_module.services.customer_related.increment_device_reset_phone_number_rate_limiter'
    )
    @mock.patch(
        'juloserver.customer_module.services.customer_related.is_device_reset_phone_number_rate_limited'
    )
    @mock.patch('juloserver.customer_module.services.customer_related.MobileFeatureSetting')
    def test_customer_ongoing_deletion(
        self,
        mock_mobile_feature_setting,
        mock_is_device_reset_phone_number_rate_limited,
        mock_increment_device_reset_phone_number_rate_limiter,
        mock_account_property,
        mock_get_ongoing_account_deletion_requests,
    ):
        mock_account = mock.MagicMock(status_id=420)
        mock_account_property.return_value = mock_account
        mock_mobile_feature_setting.objects.get.return_value = FeatureSettingFactory(
            feature_name='account_deletion',
            is_active=True,
            parameters={
                "ttl": 1,
                "max_count": 1,
            },
        )
        mock_is_device_reset_phone_number_rate_limited.return_value = False
        mock_get_ongoing_account_deletion_requests.return_value = ['something']

        val = process_incoming_change_phone_number_request(self.customer, 'key')
        self.assertEqual(val, ChangePhoneLostAccess.ErrorMessages.DEFAULT)

    @mock.patch('juloserver.customer_module.services.customer_related.MobileFeatureSetting')
    def test_no_active_mobile_feature_settings(
        self,
        mock_mobile_feature_setting,
    ):
        mock_mobile_feature_setting.objects.get.return_value = []
        val = process_incoming_change_phone_number_request(self.customer, 'key')
        self.assertEqual(val, ChangePhoneLostAccess.ErrorMessages.DEFAULT)


class TestChangePhoneByCRM(TestCase):
    def setUp(self):
        self.user = AuthUserFactory()
        self.user2 = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user, phone="081111111111")
        self.customer2 = CustomerFactory(user=self.user2, phone="081111111112")

    def test_phone_already_use(self):
        response = check_if_phone_exists(self.customer.phone, self.customer2)
        self.assertTrue(response)

    def test_phone_not_use(self):
        response = check_if_phone_exists("081111111113", self.customer2)
        self.assertFalse(response)


class TestDeleteImagePaydayCustomerChangeRequestFromOss(TestCase):
    def test_delete_document_payday_customer_change_request_from_oss_empty_image_id(self):
        """
        Test delete_document_payday_customer_change_request_from_oss with an empty image_id.
        """
        result = delete_document_payday_customer_change_request_from_oss("")
        self.assertFalse(result)

    @patch('juloserver.customer_module.services.customer_related.Image.objects.get')
    @patch('juloserver.customer_module.services.customer_related.delete_public_file_from_oss')
    def test_delete_document_payday_customer_change_request_from_oss_empty_input(
        self, mock_delete, mock_get
    ):
        result = delete_document_payday_customer_change_request_from_oss("")
        self.assertFalse(result)
        mock_get.assert_not_called()
        mock_delete.assert_not_called()

    @patch('juloserver.customer_module.services.customer_related.Image.objects.get')
    @patch('juloserver.customer_module.services.customer_related.delete_public_file_from_oss')
    def test_delete_document_payday_customer_change_request_from_oss_exception(
        self, mock_delete, mock_get
    ):
        mock_image = MagicMock()
        mock_image.image_url = "http://example.com/path/to/image.jpg"
        mock_get.return_value = mock_image
        mock_delete.side_effect = Exception("Test exception")

        result = delete_document_payday_customer_change_request_from_oss("valid_id")
        self.assertFalse(result)

    @patch('juloserver.customer_module.services.customer_related.delete_public_file_from_oss')
    def test_delete_document_payday_customer_change_request_from_oss_success(
        self, mock_delete_file
    ):
        """
        Test case for successful deletion of image from OSS.
        """
        user = AuthUserFactory()
        customer = CustomerFactory(user=user)
        image = CXDocumentFactory(
            document_source=customer.id,
            document_type='payday_customer_change_request',
        )

        mock_delete_file.return_value = None

        result = delete_document_payday_customer_change_request_from_oss(image.id)

        self.assertTrue(result)
        mock_delete_file.assert_called_once_with(
            settings.OSS_MEDIA_BUCKET, "/example.com%2Ftest.pdf"
        )


class TestGetConsentStatusFromApplicationOrAccount(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()

    def test_get_consent_status_from_application_or_account_not_have_data_concern(self):
        status_withdraw_consent = get_consent_status_from_application_or_account(self.customer)
        self.assertEqual(status_withdraw_consent, None)

    def test_get_consent_status_from_application_or_account_application_183(self):
        self.application = ApplicationFactory(customer=self.customer)
        self.application.application_status_id = 183
        self.application.save()
        status_withdraw_consent = get_consent_status_from_application_or_account(self.customer)

        self.assertEqual(status_withdraw_consent, "requested")

    def test_get_consent_status_from_application_or_account_application_184(self):
        self.application = ApplicationFactory(customer=self.customer)
        self.application.application_status_id = 184
        self.application.save()
        status_withdraw_consent = get_consent_status_from_application_or_account(self.customer)

        self.assertEqual(status_withdraw_consent, "approved")

    def test_get_consent_status_from_application_or_account_account_463(self):
        self.application = ApplicationFactory(customer=self.customer)
        self.application.application_status_id = 190
        self.application.save()

        self.account = AccountFactory(customer=self.customer)
        self.account.status_id = 463
        self.account.save()
        status_withdraw_consent = get_consent_status_from_application_or_account(self.customer)

        self.assertEqual(status_withdraw_consent, "requested")

    def test_get_consent_status_from_application_or_account_account_464(self):
        self.application = ApplicationFactory(customer=self.customer)
        self.application.application_status_id = 190
        self.application.save()

        self.account = AccountFactory(customer=self.customer)
        self.account.status_id = 464
        self.account.save()
        status_withdraw_consent = get_consent_status_from_application_or_account(self.customer)

        self.assertEqual(status_withdraw_consent, "approved")


# class TestRestrictionAccess(TestCase):
#     def setUp(self):
#         self.customer = CustomerFactory()

#     @patch('juloserver.customer_module.services.customer_related.get_withdrawal_consent_status')
#     def test_restriction_access(self, mock_get_withdrawal_consent_status):
#         is_feature_lock, status_withdraw_consent = restriction_access(customer=self.customer)
#         self.assertFalse(is_feature_lock)
#         self.assertEqual(status_withdraw_consent, "")
