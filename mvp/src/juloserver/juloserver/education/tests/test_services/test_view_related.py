from django.db.models import signals
from django.test.testcases import TestCase
from factory.django import mute_signals

from juloserver.account.tests.factories import AccountFactory
from juloserver.education.constants import ErrorMessage
from juloserver.customer_module.constants import BankAccountCategoryConst
from juloserver.customer_module.tests.factories import BankAccountCategoryFactory
from juloserver.disbursement.constants import NameBankValidationVendors
from juloserver.disbursement.tests.factories import BankNameValidationLogFactory
from juloserver.education.models import School
from juloserver.education.services.views_related import (
    is_eligible_for_education,
    assign_student_to_loan,
    get_school_id_by_select_or_self_input,
    create_bank_account_destination,
)
from juloserver.julo.statuses import ApplicationStatusCodes, JuloOneCodes
from juloserver.julo.constants import WorkflowConst
from juloserver.julo.tests.factories import (
    ApplicationFactory,
    AuthUserFactory,
    CustomerFactory,
    StatusLookupFactory,
    WorkflowFactory,
    LoanFactory,
    BankFactory,
)
from juloserver.education.tests.factories import (
    StudentRegisterFactory,
    SchoolFactory,
)
from juloserver.julo.exceptions import JuloException


class TestEligibleForEducation(TestCase):
    def setUp(self):
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user_auth)
        self.account = AccountFactory(customer=self.customer)
        self.application = ApplicationFactory(customer=self.customer, account=self.account)

    def test_invalid_application_status(self):
        is_eligible, error_message = is_eligible_for_education(
            application=self.application, account=self.account
        )
        self.assertEquals(is_eligible, False)
        self.assertEquals(error_message, ErrorMessage.APPLICATION_STATUS_MUST_BE_190)

    def test_invalid_account_status(self):
        self.application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.LOC_APPROVED
        )
        self.application.save()

        is_eligible, error_message = is_eligible_for_education(
            application=self.application, account=self.account
        )
        self.assertEquals(is_eligible, False)
        self.assertEquals(error_message, ErrorMessage.ACCOUNT_STATUS_MUST_BE_420)

    def test_valid_application_and_account(self):
        self.application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.LOC_APPROVED
        )
        self.application.save()

        self.account.status = StatusLookupFactory(status_code=JuloOneCodes.ACTIVE)
        self.account.save()

        is_eligible, error_message = is_eligible_for_education(
            application=self.application, account=self.account
        )
        self.assertEquals(is_eligible, True)
        self.assertEquals(error_message, None)

    def test_application_is_jturbo(self):
        self.application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.JULO_STARTER_AFFORDABILITY_CHECK
        )
        self.application.workflow = WorkflowFactory(name=WorkflowConst.JULO_STARTER)
        self.application.save()

        is_eligible, error_message = is_eligible_for_education(
            application=self.application, account=self.account
        )
        self.assertEquals(is_eligible, False)
        self.assertEquals(error_message, ErrorMessage.APPLICATION_STATUS_AT_LEAST_109)


class TestEducationServicesViewsRelated(TestCase):
    def setUp(self):
        self.student_register = StudentRegisterFactory()
        self.loan = LoanFactory()

    def test_assign_student_to_loan(self):
        with self.assertRaises(JuloException) as context:
            assign_student_to_loan(None, self.loan)
        assert str(context.exception) == 'No student information found'

        self.assertIsNotNone(assign_student_to_loan(self.student_register.id, self.loan))


class TestGetSchoolIdBySelectOrSelfInput(TestCase):
    def setUp(self):
        self.school_name = 'Test School'
        self.school = SchoolFactory(id=1, name=self.school_name, city='')

    def test_get_school_id_with_existing_school_id(self):
        result = get_school_id_by_select_or_self_input(school_id=123, school_name=None)
        self.assertEqual(result, 123)

    def test_get_school_id_with_new_school_name(self):
        school_name = 'New Test School'
        with mute_signals(signals.post_save):
            result = get_school_id_by_select_or_self_input(school_id=None, school_name=school_name)
        new_school = School.objects.get(name=school_name)
        self.assertEqual(result, new_school.id)

    def test_get_school_id_with_existing_school_name(self):
        result = get_school_id_by_select_or_self_input(school_id=None, school_name=self.school_name)
        self.assertEqual(result, self.school.id)


class TestCreateBankAccountDestination(TestCase):
    def test_create_bank_account_destination(self):
        # create test objects
        BankAccountCategoryFactory(
            category=BankAccountCategoryConst.EDUCATION,
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
            BankAccountCategoryConst.EDUCATION,
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
