from django.test.testcases import TestCase
from rest_framework import status
from rest_framework.test import APIClient
from factory.django import mute_signals
from django.db.models import signals
from juloserver.healthcare.factories import HealthcareUserFactory, HealthcarePlatformFactory
from juloserver.account.constants import AccountConstant
from juloserver.account.tests.factories import AccountFactory
from juloserver.healthcare.constants import FeatureNameConst
from juloserver.julo.constants import WorkflowConst
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.statuses import ApplicationStatusCodes
from juloserver.julo.tests.factories import (
    ApplicationFactory,
    AuthUserFactory,
    CustomerFactory,
    ProductLineFactory,
    StatusLookupFactory,
    WorkflowFactory,
    FeatureSettingFactory,
    BankFactory,
)
from juloserver.healthcare.models import HealthcareUser, HealthcarePlatform
from juloserver.healthcare.services.views_related import (
    get_healthcare_platform_id_by_select_or_self_input,
    create_bank_account_destination,
)
from juloserver.customer_module.constants import BankAccountCategoryConst
from juloserver.customer_module.tests.factories import BankAccountCategoryFactory
from juloserver.disbursement.tests.factories import BankNameValidationLogFactory
from juloserver.disbursement.constants import NameBankValidationVendors
from juloserver.customer_module.models import BankAccountDestination


class TestAPIV1View(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.client.force_login(self.user)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)
        self.account = AccountFactory(
            customer=CustomerFactory(user=self.user),
            status=StatusLookupFactory(status_code=AccountConstant.STATUS_CODE.active),
        )
        self.application = ApplicationFactory(
            customer=self.account.customer,
            account=self.account,
            mobile_phone_1='0123456788',
            mobile_phone_2='0123456789',
            workflow=WorkflowFactory(name=WorkflowConst.JULO_ONE),
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.J1),
        )
        self.application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.LOC_APPROVED
        )
        self.application.save()

    def test_faq_api(self):
        faqs = [{"title": "FAQ #2", "content": "Ini jawaban untuk faq #2"}]
        faq_feature = FeatureSettingFactory(
            feature_name=FeatureNameConst.HEALTHCARE_FAQ, is_active=True, parameters=faqs
        )
        response = self.client.get('/api/healthcare/v1/faq', {})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['data']['faq'], faqs)

        faq_feature.is_active = False
        faq_feature.save()
        response = self.client.get('/api/healthcare/v1/faq', {})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['data']['faq'], [])


class TestListHealthCareUser(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.client.force_login(self.user)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)
        self.customer = CustomerFactory(user=self.user)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)
        active_status_code = StatusLookupFactory(status_code=AccountConstant.STATUS_CODE.active)
        self.account = AccountFactory(customer=self.customer, status=active_status_code)
        self.workflow = WorkflowFactory(name=WorkflowConst.JULO_ONE)
        self.product_line = ProductLineFactory(product_line_code=ProductLineCodes.J1)
        self.turbo_product_line = ProductLineFactory(product_line_code=ProductLineCodes.JTURBO)
        self.application = ApplicationFactory(
            customer=self.account.customer,
            account=self.account,
            mobile_phone_1='0123456788',
            mobile_phone_2='0123456789',
            workflow=self.workflow,
            product_line=self.product_line,
        )
        self.application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.LOC_APPROVED
        )
        self.failed_status_code = StatusLookupFactory(
            status_code=ApplicationStatusCodes.FUND_DISBURSAL_FAILED
        )
        self.offer_status_code = StatusLookupFactory(
            status_code=ApplicationStatusCodes.OFFER_REGULAR
        )
        self.application.save()
        self.health_care_user = HealthcareUserFactory(account=self.account)
        self.bank = BankFactory(xfers_bank_code="TEST")
        BankAccountCategoryFactory(
            category=BankAccountCategoryConst.HEALTHCARE,
        )
        self.bank_name_validation_log = BankNameValidationLogFactory(
            account_number="123456790",
            validated_name="Jack Do",
            validation_id="123123",
            validation_status="SUCCESS",
            reason="Test validation",
            method=NameBankValidationVendors.XFERS,
            application=self.application,
        )

    def test_get_list_healthcare_users_success(self):
        # get one
        response = self.client.get('/api/healthcare/v1/users')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.json()['data']['healthcare_users']), 1)

        # not get deleted banks
        self.health_care_user.is_deleted = True
        self.health_care_user.save()
        response = self.client.get('/api/healthcare/v1/users')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.json()['data']['healthcare_users']), 0)

        # get all active banks
        HealthcareUserFactory.create_batch(10, account=self.account)
        response = self.client.get('/api/healthcare/v1/users')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.json()['data']['healthcare_users']), 10)

        self.health_care_user.is_deleted = True
        self.health_care_user.save()

    def test_get_list_healthcare_users_ineligible(self):
        # J1 and application != x190
        self.application.application_status = self.failed_status_code
        self.application.save()
        response = self.client.get('/api/healthcare/v1/users')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

        # turbo, application < x121
        self.application.application_status = self.offer_status_code
        self.application.product_line = self.turbo_product_line
        self.application.save()
        response = self.client.get('/api/healthcare/v1/users')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_put_health_care_api_create_view(self):
        healthcare_id = self.health_care_user.id
        data = {
            "name": "Jane Doe",
            "healthcare_platform": {
                "id": self.health_care_user.healthcare_platform_id
            }
        }
        response = self.client.put('/api/healthcare/v1/user/{}'.format(healthcare_id), data=data, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        updated_healthcare_user = HealthcareUser.objects.get(id=healthcare_id)
        self.assertEqual(updated_healthcare_user.fullname, data['name'])

    def test_put_health_care_api_update_platform_name(self):
        healthcare_id = self.health_care_user.id
        FeatureSettingFactory(
            feature_name=FeatureNameConst.ALLOW_ADD_NEW_HEALTHCARE_PLATFORM, is_active=True
        )
        data = {
            "healthcare_platform": {
                "name": "Healthcare23"
            }
        }
        response = self.client.put('/api/healthcare/v1/user/{}'.format(healthcare_id), data=data, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        updated_healthcare_user = HealthcareUser.objects.get(id=healthcare_id)
        updated_healthcare_platform = HealthcarePlatform.objects.get(id=updated_healthcare_user.healthcare_platform_id)
        self.assertEqual(updated_healthcare_platform.name, data['healthcare_platform']['name'])

    def test_put_health_care_api_update_bank(self):
        healthcare_id = self.health_care_user.id
        data = {
            "healthcare_platform": {
                "id": self.health_care_user.healthcare_platform_id
            },
            "bank": {
                "code": self.bank.xfers_bank_code,
                "validated_id": self.bank_name_validation_log.validation_id
            }
        }
        response = self.client.put('/api/healthcare/v1/user/{}'.format(healthcare_id), data=data, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        updated_healthcare_user = HealthcareUser.objects.get(id=healthcare_id)
        bank_account_destination = BankAccountDestination.objects.get(
            id=updated_healthcare_user.bank_account_destination_id
        )
        self.assertEqual(bank_account_destination.bank, self.bank)
        self.assertEqual(
            bank_account_destination.account_number, self.bank_name_validation_log.account_number
        )
        self.assertEqual(
            bank_account_destination.name_bank_validation.bank_code, self.bank.xfers_bank_code
        )
        self.assertEqual(
            bank_account_destination.name_bank_validation.account_number,
            self.bank_name_validation_log.account_number,
        )
        self.assertEqual(
            bank_account_destination.name_bank_validation.name_in_bank,
            self.bank_name_validation_log.validated_name,
        )
        self.assertEqual(
            bank_account_destination.name_bank_validation.method, NameBankValidationVendors.XFERS
        )
        self.assertEqual(
            bank_account_destination.name_bank_validation.validation_id,
            self.bank_name_validation_log.validation_id,
        )
        self.assertEqual(
            bank_account_destination.name_bank_validation.validation_status,
            self.bank_name_validation_log.validation_status,
        )
        self.assertEqual(
            bank_account_destination.name_bank_validation.validated_name,
            self.bank_name_validation_log.validated_name,
        )


class TestDeleteHealthCareUser(TestCase):
    def setUp(self):
        self.client = APIClient()

        self.user = AuthUserFactory()
        self.user2 = AuthUserFactory()

        self.customer = CustomerFactory(user=self.user)
        self.customer2 = CustomerFactory(user=self.user2)

        self.client.force_login(self.user)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)

        active_status_code = StatusLookupFactory(status_code=AccountConstant.STATUS_CODE.active)

        self.account = AccountFactory(customer=self.customer, status=active_status_code)
        self.account2 = AccountFactory(customer=self.customer2, status=active_status_code)

        self.workflow = WorkflowFactory(name=WorkflowConst.JULO_ONE)
        self.product_line = ProductLineFactory(product_line_code=ProductLineCodes.J1)
        self.turbo_product_line = ProductLineFactory(product_line_code=ProductLineCodes.JTURBO)

        # app
        self.app = ApplicationFactory(
            customer=self.account.customer,
            account=self.account,
            mobile_phone_1='0123456788',
            mobile_phone_2='0123456789',
            workflow=self.workflow,
            product_line=self.product_line,
        )
        self.app.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.LOC_APPROVED
        )
        self.failed_status_code = StatusLookupFactory(
            status_code=ApplicationStatusCodes.FUND_DISBURSAL_FAILED
        )
        self.offer_status_code = StatusLookupFactory(
            status_code=ApplicationStatusCodes.OFFER_REGULAR
        )
        self.app.save()
        self.health_care_user = HealthcareUserFactory(account=self.account, is_deleted=False)

        # heatlh care by other user
        self.health_care_user2 = HealthcareUserFactory(account=self.account2, is_deleted=False)

    def test_success_delete_own_healthcare_user(self):
        response = self.client.delete(f'/api/healthcare/v1/user/{self.health_care_user}')
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        result_user = HealthcareUser.objects.get(pk=self.health_care_user.id)
        self.assertEqual(result_user.is_deleted, True)

    def test_notfound_delete_healthcare_user(self):
        response = self.client.delete(f'/api/healthcare/v1/user/0')
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_delete_other_healthcare_user(self):
        response = self.client.delete(f'/api/healthcare/v1/user/{self.health_care_user2}')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

        result_user = HealthcareUser.objects.get(pk=self.health_care_user2.id)
        self.assertEqual(result_user.is_deleted, False)


class TestGetHealthcareIdBySelectOrSelfInput(TestCase):
    def setUp(self):
        self.name = 'RSU NUSANTARA'
        self.healthcare_platform = HealthcarePlatformFactory(id=1, name=self.name, city='')

    def test_get_healthcare_id_with_existing_healthcare_platform_id(self):
        result = get_healthcare_platform_id_by_select_or_self_input(
            healthcare_platform_id=123,
            healthcare_platform_name=None
        )
        self.assertEqual(result, 123)

    def test_get_healthcare_id_with_new_healthcare_platform_name(self):
        platform_name = 'New Test Platform'
        with mute_signals(signals.post_save):
            result = get_healthcare_platform_id_by_select_or_self_input(
                healthcare_platform_id=None,
                healthcare_platform_name=platform_name
            )
        new_platform_name = HealthcarePlatform.objects.get(name=platform_name)
        self.assertEqual(result, new_platform_name.id)

    def test_get_healthcare_id_with_existing_healthcare_platform_name(self):
        result = get_healthcare_platform_id_by_select_or_self_input(
            healthcare_platform_id=None,
            healthcare_platform_name=self.name
        )
        self.assertEqual(result, self.healthcare_platform.id)


class TestCreateBankAccountDestination(TestCase):
    def test_create_bank_account_destination(self):
        # create test objects
        BankAccountCategoryFactory(
            category=BankAccountCategoryConst.HEALTHCARE,
            parent_category_id=13,
        )
        bank = BankFactory(xfers_bank_code="TEST")
        bank_name_validation_log = BankNameValidationLogFactory(
            account_number="1234567890",
            validated_name="John Doe",
            validation_id="TEST123",
            validation_status="SUCCESS",
            reason="Test validation",
        )
        application = ApplicationFactory(mobile_phone_1="1234567890")
        customer = CustomerFactory()

        # call the function
        bank_account_destination = create_bank_account_destination(
            bank=bank,
            bank_name_validation_log=bank_name_validation_log,
            application=application,
            customer=customer,
        )

        # check that the object was created correctly
        self.assertEqual(
            bank_account_destination.bank_account_category.category,
            BankAccountCategoryConst.HEALTHCARE,
        )
        self.assertEqual(bank_account_destination.customer, customer)
        self.assertEqual(bank_account_destination.bank, bank)
        self.assertEqual(
            bank_account_destination.account_number, bank_name_validation_log.account_number
        )
        self.assertEqual(
            bank_account_destination.name_bank_validation.bank_code, bank.xfers_bank_code
        )
        self.assertEqual(
            bank_account_destination.name_bank_validation.account_number,
            bank_name_validation_log.account_number,
        )
        self.assertEqual(
            bank_account_destination.name_bank_validation.name_in_bank,
            bank_name_validation_log.validated_name,
        )
        self.assertEqual(
            bank_account_destination.name_bank_validation.method, NameBankValidationVendors.XFERS
        )
        self.assertEqual(
            bank_account_destination.name_bank_validation.validation_id,
            bank_name_validation_log.validation_id,
        )
        self.assertEqual(
            bank_account_destination.name_bank_validation.validation_status,
            bank_name_validation_log.validation_status,
        )
        self.assertEqual(
            bank_account_destination.name_bank_validation.validated_name,
            bank_name_validation_log.validated_name,
        )
        self.assertEqual(
            bank_account_destination.name_bank_validation.mobile_phone, application.mobile_phone_1
        )
        self.assertEqual(
            bank_account_destination.name_bank_validation.reason, bank_name_validation_log.reason
        )
