from __future__ import print_function
import uuid

from unittest.mock import patch

import jwt
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase
from django.utils import timezone
from dateutil.parser import parse
from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from juloserver.account.models import AdditionalCustomerInfo, ExperimentGroup
from juloserver.application_flow.constants import PartnerNameConstant
from juloserver.balance_consolidation.constants import BalanceConsolidationStatus
from juloserver.balance_consolidation.tests.factories import (
    BalanceConsolidationFactory,
    BalanceConsolidationVerificationFactory,
    FintechFactory,
)
from juloserver.customer_module.tests.factories import BankAccountDestinationFactory
from juloserver.disbursement.tests.factories import DisbursementFactory, NameBankValidationFactory
from juloserver.account.tests.factories import (
    AccountFactory,
    AdditionalCustomerInfoFactory,
)
from juloserver.account_payment.tests.factories import (
    AccountPaymentFactory,
    CheckoutRequestFactory,
)
from juloserver.education.tests.factories import (
    SchoolFactory,
    StudentRegisterFactory,
    LoanStudentRegisterFactory,
)
from juloserver.healthcare.factories import HealthcareUserFactory
from juloserver.healthcare.models import HealthcareUser
from juloserver.julo.models import SepulsaTransaction
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.tests.factories import (
    ApplicationFactory,
    AuthUserFactory,
    CustomerFactory,
    DocumentFactory,
    FaqCheckoutFactory,
    LoanFactory,
    PartnerFactory,
    PaymentMethodFactory,
    PaymentMethodLookupFactory,
    ProductLineFactory,
    StatusLookupFactory,
    CleanLoanFactory,
    SepulsaTransactionFactory,
    BankFactory,
    FeatureSettingFactory,
    ExperimentSettingFactory,
    PaymentFactory,
)
from datetime import datetime, timedelta, date
from django.conf import settings
from juloserver.ecommerce.tests.factories import (
    JuloShopTransactionFactory,
)

from juloserver.credit_card.tests.factiories import CreditCardTransactionFactory

from juloserver.julo_financing.constants import (
    JFINACNING_FE_PRODUCT_CATEGORY,
    JFINANCING_VENDOR_NAME,
)
from juloserver.julo_financing.tests.factories import (
    JFinancingCheckoutFactory,
    JFinancingProductFactory,
    JFinancingVerificationFactory,
)
from juloserver.payment_point.constants import TransactionMethodCode
from juloserver.loan.models import AdditionalLoanInformation
from juloserver.loan.tests.factories import TransactionMethodFactory
from unittest.mock import patch

from juloserver.qris.constants import QrisLinkageStatus, QrisTransactionStatus
from juloserver.qris.tests.factories import QrisPartnerLinkageFactory, QrisPartnerTransactionFactory
from juloserver.julo.constants import ExperimentConst
from juloserver.julo.statuses import PaymentStatusCodes
from juloserver.account.constants import UserType
from juloserver.autodebet.tests.factories import AutodebetAccountFactory


class TestAccountPaymentViewEnhV2(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.client.force_login(self.user)
        self.client.force_authenticate(user=self.user)
        self.customer = CustomerFactory(user=self.user)
        self.account = AccountFactory(customer=self.customer)
        self.account_payment = AccountPaymentFactory(account=self.account)
        self.account_payment2 = AccountPaymentFactory(account=self.account)
        self.account_payment_paid = AccountPaymentFactory(
            account=self.account,
            status_id=PaymentStatusCodes.PAID_ON_TIME,
        )
        self.application = ApplicationFactory(account=self.account, customer=self.customer)
        self.fintech = FintechFactory()
        self.document = DocumentFactory()
        self.loan = LoanFactory(
            account=self.account,
            customer=self.customer,
            loan_disbursement_amount=10000000,
            loan_amount=10000000,
        )
        self.payment = PaymentFactory(
            payment_status=self.account_payment_paid.status,
            due_date=self.account_payment_paid.due_date,
            account_payment=self.account_payment_paid,
            loan=self.loan,
            change_due_date_interest=0,
            paid_date=datetime.today().date(),
            paid_amount=self.account_payment_paid.due_amount,
        )

    @patch('juloserver.account.models.Account.is_eligible_for_cashback_new_scheme')
    def test_get_account_payment_list(self, mock_cashback):
        mock_cashback.return_value = True
        res = self.client.get('/api/account/v2/account-payment/')
        self.assertEqual(res.data['page_size'], 2)
        assert res.status_code == 200

    @patch('juloserver.account.models.Account.is_eligible_for_cashback_new_scheme')
    def test_get_account_payment_list_paid_off(self, mock_cashback):
        mock_cashback.return_value = True
        res = self.client.get('/api/account/v2/account-payment/?is_paid_off=true')
        self.assertEqual(res.data['page_size'], 1)
        assert res.status_code == 200


class TestPaymentListViewByLoan(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.client.force_login(self.user)
        self.client.force_authenticate(user=self.user)
        self.customer = CustomerFactory(user=self.user)
        self.account = AccountFactory(customer=self.customer)
        self.account_payment = AccountPaymentFactory(
            account=self.account, principal_amount=500000, interest_amount=0, late_fee_amount=0
        )
        self.account_payment2 = AccountPaymentFactory(
            account=self.account, principal_amount=500000, interest_amount=0, late_fee_amount=0
        )
        self.loan = LoanFactory(
            account=self.account,
            customer=self.customer,
            loan_disbursement_amount=1000000,
            loan_amount=1000000,
        )

    def test_get_payment_list_success(self):
        url = '/api/account/v1/loans/' + str(self.loan.loan_xid) + '/payment-list/'
        res = self.client.get(url)

        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(res.data['data']), 4)


class TestAccountPaymentView(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.client.force_login(self.user)
        self.client.force_authenticate(user=self.user)
        self.customer = CustomerFactory(user=self.user)
        self.account = AccountFactory(customer=self.customer)
        self.account_payment = AccountPaymentFactory(account=self.account)
        self.application = ApplicationFactory(account=self.account, customer=self.customer)
        self.fintech = FintechFactory()
        self.document = DocumentFactory()
        FeatureSettingFactory(
            feature_name='late_fee_grace_period',
            parameters={"daily_late_fee": False, "grade_period": 0},
            is_active=True,
        )

    @patch('juloserver.account.models.Account.is_eligible_for_cashback_new_scheme')
    def test_get_account_payment_list(self, mock_cashback):
        mock_cashback.return_value = False
        res = self.client.get('/api/account/v1/account-payment')
        assert res.status_code == 200

    @patch('juloserver.account.models.Account.is_eligible_for_cashback_new_scheme')
    def test_get_account_payment_list_julover(self, mock_cashback):
        mock_cashback.return_value = False
        application_status = StatusLookupFactory(status_code=190)
        product_line = ProductLineFactory(product_line_code=ProductLineCodes.JULOVER)
        self.application.application_status = application_status
        self.application.product_line = product_line
        self.application.save()
        res = self.client.get('/api/account/v1/account-payment')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data['data']['is_julover'], True)

    def test_get_loans_juloshop(self):
        application_status = StatusLookupFactory(status_code=190)
        product_line = ProductLineFactory(product_line_code=ProductLineCodes.JULOVER)
        self.application.application_status = application_status
        self.application.product_line = product_line
        self.application.save()

        loan = CleanLoanFactory(
            customer=self.customer, application=self.application, loan_amount=100000
        )

        juloshop_transaction = JuloShopTransactionFactory(
            customer=self.customer,
            application=self.application,
            loan=loan,
            seller_name='bukalapak',
            transaction_xid='ba679f4b-4446-4952-a166-ae93f31f1d69',
            product_total_amount=100000,
            checkout_info={
                "items": [
                    {
                        "image": "http:random_link.com",
                        "price": 1725000.0,
                        "quantity": 1,
                        "productID": "618697428",
                        "productName": "AQUA Kulkas 1 Pintu [153 L] AQR-D191 (LB) - Lily Blue",
                    }
                ],
                "discount": 400000,
                "finalAmount": 1725000,
                "shippingFee": 0,
                "insuranceFee": 0,
                "shippingDetail": {
                    "area": "Kelapa Dua",
                    "city": "Kabupaten Tangerang",
                    "province": "Banten",
                    "postalCode": "15810",
                    "fullAddress": "Fiordini 3",
                },
                "recipientDetail": {"name": "Alvin", "phoneNumber": "08110000003"},
                "totalProductAmount": 2125000,
            },
        )

        res = self.client.get('/api/account/v1/loans/', data={"type": "ALL"})
        self.assertEqual(res.status_code, 200)

    def test_get_loans_non_juloshop(self):
        application_status = StatusLookupFactory(status_code=190)
        product_line = ProductLineFactory(product_line_code=ProductLineCodes.JULOVER)
        self.application.application_status = application_status
        self.application.product_line = product_line
        self.application.save()

        self.loan = LoanFactory(
            account=self.account,
            customer=self.customer,
            loan_disbursement_amount=100000,
            loan_amount=105000,
        )
        res = self.client.get('/api/account/v1/loans/', data={"type": "ACTIVE"})
        self.assertEqual(res.status_code, 200)

    def test_get_loan_with_fintech_name(self):
        self.loan = LoanFactory(
            account=self.account,
            customer=self.customer,
            loan_disbursement_amount=100000,
            loan_amount=105000,
        )

        self.balance_consolidation = BalanceConsolidationFactory(
            customer=self.customer, fintech=self.fintech, loan_agreement_document=self.document
        )
        self.balance_consolidation_verification = BalanceConsolidationVerificationFactory(
            balance_consolidation=self.balance_consolidation,
            validation_status=BalanceConsolidationStatus.DISBURSED,
            loan=self.loan
        )

        self.name_bank_validation = NameBankValidationFactory(method="Xfers")
        self.balance_consolidation_verification.name_bank_validation = self.name_bank_validation
        self.balance_consolidation_verification.save()

        application_status = StatusLookupFactory(status_code=190)
        product_line = ProductLineFactory(product_line_code=ProductLineCodes.JULOVER)
        self.application.application_status = application_status
        self.application.product_line = product_line
        self.application.save()

        res = self.client.get('/api/account/v1/loans/', data={"type": "ACTIVE"})
        body = res.json()
        self.assertIsNotNone(body['data'][0]['fintech_name'])


class TestAdditionalAddress(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.client.force_login(self.user)
        self.client.force_authenticate(user=self.user)
        self.customer = CustomerFactory(user=self.user)
        self.account = AccountFactory(customer=self.customer)
        self.account_payment = AccountPaymentFactory(account=self.account)
        self.application = ApplicationFactory(account=self.account, customer=self.customer)
        self.additional_customer_info = AdditionalCustomerInfoFactory(
            additional_customer_info_type='address',
            customer=self.customer,
            additional_address_number=1,
            street_number='jalan',
            provinsi='Jawa Barat',
            kabupaten='Bandung',
            kecamatan='Sumur',
            kelurahan='sumur',
            kode_pos='12345',
            occupied_since=timezone.localtime(timezone.now()).date(),
            home_status='Kos',
            latest_updated_by=self.user,
            latest_action='add',
        )

    def test_get_additional_address(self):
        res = self.client.get(
            '/api/account/v1/address/customer/{}'.format(self.additional_customer_info.customer.id)
        )
        self.assertEqual(res.status_code, 200)
        res = self.client.post(
            '/api/account/v1/address/account/{}'.format(self.additional_customer_info.customer.id)
        )
        self.assertNotEqual(res.status_code, 200)
        res = self.client.get(
            '/api/account/v1/address/customer/{}'.format(
                self.additional_customer_info.customer.id + 123
            )
        )
        response = res.json()
        self.assertNotEqual(response['success'], True)

    def test_create_additional_address(self):
        data = dict(
            application_id=self.application.id,
            additional_address_number=2,
            street_number='jalan',
            provinsi='Jawa Barat',
            kabupaten='Bandung',
            kecamatan='Sumur',
            kelurahan='sumur',
            kode_pos='12345',
            occupied_since='01-01-2020',
            home_status='Kos',
            customer_id=self.customer.id,
        )
        res = self.client.post('/api/account/v1/address/customer', data=data, format='json')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(AdditionalCustomerInfo.objects.all()), 2)
        res = self.client.get('/api/account/v1/address/customer')
        self.assertNotEqual(res.status_code, 200)
        data['application_id'] = self.application.id + 1
        res = self.client.post('/api/account/v1/address/customer', data=data, format='json')
        response = res.json()
        self.assertNotEqual(response['success'], True)

    def test_update_additional_address(self):
        data = dict(
            street_number='kampung',
            provinsi='Jawa Barat',
            kabupaten='Bandung',
            kecamatan='Sumur',
            kelurahan='sumur',
            kode_pos='12345',
            occupied_since='01-01-2020',
            home_status='Kos',
            customer_id=self.customer.id,
            application_id=self.application.id,
        )
        res = self.client.patch(
            '/api/account/v1/address/{}'.format(self.additional_customer_info.id),
            data=data,
            format='json',
        )
        self.assertEqual(res.status_code, 200)
        self.additional_customer_info.refresh_from_db()
        self.assertEqual(self.additional_customer_info.street_number, 'kampung')
        res = self.client.get(
            '/api/account/v1/address/{}'.format(self.additional_customer_info.id),
            data=data,
            format='json',
        )
        self.assertNotEqual(res.status_code, 200)
        res = self.client.patch(
            '/api/account/v1/address/{}'.format(self.additional_customer_info.id + 1),
            data=data,
            format='json',
        )
        response = res.json()
        self.assertNotEqual(response['success'], True)

    def test_delete_additional_address(self):
        data = dict(application_id=self.application.id)
        res = self.client.delete(
            '/api/account/v1/delete-address/{}'.format(self.additional_customer_info.id),
            data=data,
            format='json',
        )
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(AdditionalCustomerInfo.objects.all()), 0)
        res = self.client.get(
            '/api/account/v1/delete-address/{}'.format(self.additional_customer_info.id),
            data=data,
            format='json',
        )
        self.assertNotEqual(res.status_code, 200)
        res = self.client.delete(
            '/api/account/v1/delete-address/{}'.format(self.additional_customer_info.id + 1),
            data=data,
            format='json',
        )
        response = res.json()
        self.assertNotEqual(response['success'], True)

    @patch('juloserver.account_payment.services.earning_cashback.get_cashback_experiment')
    def test_get_account_payment_list_no_application(self, mock_cashback):
        mock_cashback.return_value = False
        self.application = None
        res = self.client.get('/api/account/v1/account-payment')
        assert res.status_code == 200


class TestActivePaymentCheckout(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user_auth)
        token = self.user_auth.auth_expiry_token.key
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + token)
        self.account = AccountFactory(customer=self.customer)
        self.loan = LoanFactory(account=self.account, customer=self.customer)
        self.account_payment = AccountPaymentFactory(
            id=1,
            account=self.account,
            late_fee_amount=0,
            paid_amount=0,
            due_amount=10000,
            principal_amount=9000,
            interest_amount=1000,
        )
        self.virtual_account_postfix = '123456789'
        self.company_code = '10994'
        self.virtual_account = '{}{}'.format(self.company_code, self.virtual_account_postfix)
        self.payment_method = PaymentMethodFactory(
            id=10,
            customer=self.customer,
            virtual_account=self.virtual_account,
            payment_method_name='test',
        )
        self.payment_method_lookup = PaymentMethodLookupFactory(
            name='test', image_logo_url='test.jpg'
        )
        self.checkout_request = CheckoutRequestFactory(
            account_id=self.account,
            total_payments=20000,
            status='active',
            account_payment_ids=[self.account_payment.id],
            checkout_payment_method_id=self.payment_method,
        )

    @patch('juloserver.account.views.get_cashback_experiment')
    def test_active_payment_checkout(self, mock_cashback):
        mock_cashback.return_value = False
        res = self.client.get('/api/account/v1/active-payment')
        self.assertEqual(res.status_code, 200)


class TestFAQCheckoutList(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user_auth = AuthUserFactory()
        token = self.user_auth.auth_expiry_token.key
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + token)

    def test_faq_checkout_list_not_found(self):
        res = self.client.get('/api/account/v1/checkout-faq')
        self.assertEqual(res.status_code, 404)

    def test_faq_checkout_list(self):
        faq = FaqCheckoutFactory()
        res = self.client.get('/api/account/v1/checkout-faq')
        self.assertEqual(res.status_code, 200)


class TestZendeskJwtTokenGenerator(APITestCase):

    client = APIClient()

    def setUp(self):
        self.user = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)

    def test_zendeskJwtTokenGenerator(self):
        response = self.client.get("/api/account/v1/zendesk-token/", data={}, format='json')
        self.assertEqual(response.status_code, 200)


class TestGetListLoan(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user_auth)
        self.account = AccountFactory(customer=self.customer)
        self.status_220 = StatusLookupFactory(status_code=220)
        self.status_212 = StatusLookupFactory(status_code=212)
        self.disbursement = DisbursementFactory()
        self.loan = LoanFactory(
            customer=self.customer,
            account=self.account,
            loan_status=self.status_220,
            disbursement_id=self.disbursement.id,
        )
        self.loan.cdate = datetime(2022, 11, 29, 4, 15, 0)
        self.loan.save()
        self.disbursement.cdate = datetime(2022, 11, 29, 5, 15, 0)
        self.disbursement.save()
        self.sepulsa_transaction = SepulsaTransactionFactory(loan=self.loan)
        self.sepulsa_transaction.cdate = datetime(2022, 11, 29, 5, 15, 0)
        self.sepulsa_transaction.save()
        token = self.user_auth.auth_expiry_token.key
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + token)

    def test_get_list_loan_with_UTC7(self):
        res = self.client.get('/api/account/v1/loans/?type=ACTIVE')
        loan_cdate = parse(res.json()['data'][0]['loan_date']).date()
        loan_original_cdate = parse(str(timezone.localtime(self.loan.cdate))).date()

        # Sepulsa transaction
        assert loan_cdate == loan_original_cdate
        disbursement_cdate = parse(res.json()['data'][0]['disbursement_date']).date()
        disbursement_original_cdate = parse(
            str(timezone.localtime(self.sepulsa_transaction.cdate))
        ).date()

        assert disbursement_cdate == disbursement_original_cdate

        self.sepulsa_transaction.delete()

        # disbursement
        assert loan_cdate == loan_original_cdate
        disbursement_cdate = parse(res.json()['data'][0]['disbursement_date']).date()
        disbursement_original_cdate = parse(str(timezone.localtime(self.disbursement.cdate))).date()

        assert disbursement_cdate == disbursement_original_cdate

    def test_get_list_loan_for_education(self):
        SepulsaTransaction.objects.all().delete()

        self.loan.loan_status = self.status_220
        self.loan.save()
        school = SchoolFactory()
        bank_account_destination = BankAccountDestinationFactory()
        student_register = StudentRegisterFactory(
            account=self.account,
            school=school,
            bank_account_destination=bank_account_destination,
            student_fullname='This is full name',
            note='123456789',
        )

        LoanStudentRegisterFactory(loan=self.loan, student_register=student_register)

        self.disbursement.reference_id = 'contract_0b797cb8f5984e0e89eb802a009fa5f4'
        self.disbursement.save()

        response = self.client.get('/api/account/v1/loans/?type=ACTIVE')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        loan_info_response = response.data['data'][0]
        self.assertEqual(loan_info_response['bank_reference_number'], '079785984089')
        self.assertEqual(loan_info_response['education_data']['school_name'], school.name)
        self.assertEqual(
            loan_info_response['education_data']['student_fullname'],
            student_register.student_fullname,
        )
        self.assertEqual(loan_info_response['education_data']['note'], student_register.note)

        # test bank_reference_number is null when loan status < 220
        self.loan.loan_status = self.status_212
        self.loan.save()
        response = self.client.get('/api/account/v1/loans/?type=ACTIVE')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['data'][0]['bank_reference_number'], None)

    def test_get_list_loan_for_healthcare(self):
        SepulsaTransaction.objects.all().delete()

        self.loan.transaction_method = TransactionMethodFactory(
            id=TransactionMethodCode.HEALTHCARE.code, method=TransactionMethodCode.HEALTHCARE
        )
        self.loan.loan_status = self.status_220
        self.loan.save()
        healthcare_user = HealthcareUserFactory(account=self.account)
        AdditionalLoanInformation.objects.create(
            content_type=ContentType.objects.get_for_model(HealthcareUser),
            object_id=healthcare_user.pk,
            loan=self.loan,
        )

        self.disbursement.reference_id = 'contract_0b123cb4f5678ee9eb100a109fa5f4'
        self.disbursement.save()

        response = self.client.get('/api/account/v1/loans/?type=ACTIVE')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        loan_info_response = response.data['data'][0]
        self.assertEqual(loan_info_response['bank_reference_number'], '012345678910')
        self.assertEqual(
            loan_info_response['healthcare_data']['healthcare_platform_name'],
            healthcare_user.healthcare_platform.name,
        )
        self.assertEqual(
            loan_info_response['healthcare_data']['healthcare_user_fullname'],
            healthcare_user.fullname,
        )

        # test bank_reference_number is null when loan status < 220
        self.loan.loan_status = self.status_212
        self.loan.save()
        response = self.client.get('/api/account/v1/loans/?type=ACTIVE')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['data'][0]['bank_reference_number'], None)

    def test_get_list_loan_jfinancing(self):
        product_quantity = 10
        product = JFinancingProductFactory(quantity=product_quantity)
        checkout = JFinancingCheckoutFactory(
            customer=self.customer,
            additional_info={},
            j_financing_product=product,
            price=900_000,
        )
        JFinancingVerificationFactory(j_financing_checkout=checkout, loan=self.loan)
        self.loan.transaction_method = TransactionMethodFactory.jfinancing()

        self.loan.loan_status = self.status_220
        self.loan.save()

        response = self.client.get('/api/account/v1/loans/?type=ACTIVE')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        loan_info_response = response.data['data'][0]
        self.assertEqual(
            loan_info_response['qris_data']['product_category'],
            JFINACNING_FE_PRODUCT_CATEGORY,
        )
        self.assertEqual(
            loan_info_response['qris_data']['nominal'],
            checkout.price,
        )
        self.assertEqual(
            loan_info_response['qris_data']['name'],
            JFINANCING_VENDOR_NAME,
        )

    def test_get_list_loan_qris_1(self):
        merchant_name = "brian johnson"
        partner_user = AuthUserFactory()
        partner = PartnerFactory(
            user=partner_user,
            name=PartnerNameConstant.AMAR,
        )

        linkage = QrisPartnerLinkageFactory(
            status=QrisLinkageStatus.SUCCESS,
            customer_id=self.customer.id,
            partner_id=partner.id,
            partner_callback_payload={"any": "any"},
        )
        transaction = QrisPartnerTransactionFactory(
            loan_id=self.loan.id,
            status=QrisTransactionStatus.SUCCESS,
            qris_partner_linkage=linkage,
            merchant_name=merchant_name,
            from_partner_transaction_xid=uuid.uuid4().hex,
        )

        self.loan.transaction_method = TransactionMethodFactory.qris_1()

        self.loan.loan_status = self.status_220
        self.loan.save()

        response = self.client.get('/api/account/v1/loans/?type=ACTIVE')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        loan_info_response = response.data['data'][0]
        self.assertEqual(loan_info_response['qris_data']['product_category'], "QRIS")
        self.assertEqual(
            loan_info_response['qris_data']['nominal'],
            transaction.total_amount,
        )
        self.assertEqual(
            loan_info_response['qris_data']['name'],
            transaction.merchant_name,
        )

        # failed loan status
        self.loan.loan_status_id = 215
        self.loan.save()

        response = self.client.get('/api/account/v1/loans/?type=ACTIVE')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data_response = response.data['data']
        assert len(data_response) == 0


class TestAccountLoan(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.client = APIClient()
        user = AuthUserFactory()
        self.client.force_login(user)
        self.client.force_authenticate(user=user)
        customer = CustomerFactory(user=user)
        account = AccountFactory(customer=customer)
        ApplicationFactory(account=account, customer=customer)
        self.loan = LoanFactory(
            account=account,
            customer=customer,
            transaction_method_id=TransactionMethodCode.CREDIT_CARD.code,
            loan_disbursement_amount=100000,
            loan_amount=105000,
        )
        self.credit_card_transaction = CreditCardTransactionFactory(
            loan=self.loan, amount=self.loan.loan_disbursement_amount
        )
        self.url_account_loan = "/api/account/v1/loans/"

    def test_account_loan_should_success_when_transaction_method_is_julo_card(self):
        response = self.client.get(self.url_account_loan, data={"type": "ACTIVE"})
        self.assertEqual(response.status_code, 200)
        response = response.json()
        self.assertIn('julo_card_data', response['data'][0])
        expected_response = {
            'product_category': 'JULO Card',
            'nominal': self.credit_card_transaction.amount,
            'name': self.credit_card_transaction.terminal_location,
        }
        self.assertEqual(expected_response, response['data'][0]['julo_card_data'])

    def test_account_loan_should_success_when_transaction_method_is_not_julo_card(self):
        self.loan.update_safely(transaction_method_id=TransactionMethodCode.BPJS_KESEHATAN.code)
        response = self.client.get(self.url_account_loan, data={"type": "ACTIVE"})
        self.assertEqual(response.status_code, 200)
        response = response.json()
        self.assertNotIn('julo_card_data', response['data'][0])


class TestAccountPaymentDpd(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.client.force_login(self.user)
        self.client.force_authenticate(user=self.user)
        self.customer = CustomerFactory(user=self.user)
        self.account = AccountFactory(customer=self.customer)
        self.account_payment = AccountPaymentFactory(account=self.account)
        self.application = ApplicationFactory(account=self.account, customer=self.customer)
        self.feature_setting = FeatureSettingFactory(
            feature_name='dpd_warning_color_treshold',
            is_active=True,
            parameters={"dpd_warning_color_treshold": -3},
        )

    @patch('juloserver.account.views.get_cashback_experiment')
    def test_get_account_payment_dpd(self, mock_cashback):
        mock_cashback.return_value = False
        res = self.client.get('/api/account/v1/account-payment/dpd')
        print(res.data)
        assert res.status_code == 200

    @patch('juloserver.account.views.get_cashback_experiment')
    def test_get_account_payment_dpd_with_account(self, mock_cashback):
        application_status = StatusLookupFactory(status_code=190)
        product_line = ProductLineFactory(product_line_code=ProductLineCodes.JULOVER)
        self.application.application_status = application_status
        self.application.product_line = product_line
        self.application.save()
        mock_cashback.return_value = False
        res = self.client.get('/api/account/v1/account-payment/dpd')
        self.assertEqual(res.status_code, 200)

        response_data = res.data['data']
        print(res.data)

        self.assertIn('dpd', response_data)
        self.assertIn('total_loan_amount', response_data)
        self.assertIn('due_date', response_data)
        self.assertIn('dpd_warning_threshold', response_data)
        self.assertIn('cashback_counter', response_data)

        self.assertEqual(
            self.feature_setting.parameters['dpd_warning_color_treshold'],
            response_data['dpd_warning_threshold'],
        )


class TestAccountPaymentSummary(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.client.force_login(self.user)
        self.client.force_authenticate(user=self.user)
        self.customer = CustomerFactory(user=self.user)
        self.account = AccountFactory(customer=self.customer)
        self.account_payment = AccountPaymentFactory(account=self.account)
        self.product_line = ProductLineFactory.julover()
        self.application = ApplicationFactory(
            account=self.account, customer=self.customer, product_line=self.product_line
        )
        self.payment_method = PaymentMethodFactory(
            id=10,
            customer=self.customer,
            payment_method_name='test',
        )
        self.payment_method_lookup = PaymentMethodLookupFactory(
            name='test', image_logo_url='test.jpg'
        )
        self.autodebet_account = AutodebetAccountFactory(account=self.account)

    @patch('juloserver.account.views.get_payment_method_type')
    @patch('juloserver.account.views.get_checkout_experience_setting')
    @patch('juloserver.account.views.get_disable_payment_methods')
    def test_account_payment_summary_success(
        self,
        mock_get_disable_payment_methods,
        mock_get_checkout_experience_setting,
        mock_get_payment_method_type,
    ):
        mock_get_checkout_experience_setting.return_value = True, True
        mock_get_payment_method_type.return_value = 'Virtual Account'
        mock_get_disable_payment_methods.return_value = []

        res = self.client.get('/api/account/v2/account-payment-summary/')
        json_res = res.json()['data']
        print('json_res', json_res)

        self.assertEqual(res.status_code, 200)
        self.assertEqual(json_res['info']['user_type'], UserType.JULOVERS)
        self.assertIsNotNone(json_res['payment_method'])
        self.assertIsNotNone(json_res['autodebit_data'])


class TestAccountPaymentViewV2(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.client.force_login(self.user)
        self.client.force_authenticate(user=self.user)
        self.customer = CustomerFactory(user=self.user)
        self.account = AccountFactory(customer=self.customer)
        self.account_payment = AccountPaymentFactory(account=self.account)
        self.application = ApplicationFactory(account=self.account, customer=self.customer)

    @patch('juloserver.account.models.Account.is_eligible_for_cashback_new_scheme')
    def test_get_account_payment_list_v2(self, mock_cashback):
        mock_cashback.return_value = True
        res = self.client.get('/api/account/v2/active-payment')
        assert res.status_code == 200

    @patch('juloserver.account.models.Account.is_eligible_for_cashback_new_scheme')
    def test_get_account_payment_list_v2_inactive(self, mock_cashback):
        mock_cashback.__bool__.return_value = False
        res = self.client.get('/api/account/v2/active-payment')
        assert res.status_code == 400


class TestTagihanRevampExperimentView(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user_auth = AuthUserFactory()
        self.customer = CustomerFactory(user=self.user_auth)
        token = self.user_auth.auth_expiry_token.key
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + token)
        self.account = AccountFactory(customer=self.customer)
        mobile_phone_1 = '081234567890'
        self.application = ApplicationFactory(
            customer=self.customer, account=self.account, mobile_phone_1=mobile_phone_1
        )
        self.experiment_setting = ExperimentSettingFactory(
            code=ExperimentConst.TAGIHAN_REVAMP_EXPERIMENT,
            is_active=True,
        )
        self.url = "/api/account/v1/tagihan-revamp-experiment"

    def test_tagihan_revamp_should_success(self):
        response = self.client.post(self.url, data={"experiment_id": 1})
        self.assertEqual(response.status_code, 200)
        experiment_group = ExperimentGroup.objects.last()
        self.assertIsNotNone(experiment_group)
        self.assertEqual(experiment_group.group, "control")
        response = self.client.post(self.url, data={"experiment_id": 2})
        self.assertEqual(response.status_code, 200)
        experiment_group = ExperimentGroup.objects.last()
        self.assertIsNotNone(experiment_group)
        self.assertEqual(experiment_group.group, "experiment")

    def test_tagihan_revamp_should_failed_when_experiment_turned_off(self):
        self.experiment_setting.update_safely(is_active=False)
        response = self.client.post(self.url, data={"experiment_id": 1})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(ExperimentGroup.objects.exists())

    def test_tagihan_revamp_should_not_stored_when_experiment_not_found(self):
        self.experiment_setting.delete()
        response = self.client.post(self.url, data={"experiment_id": 1})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(ExperimentGroup.objects.exists())

    def test_tagihan_revamp_should_failed_when_experiment_id_invalid(self):
        response = self.client.post(self.url, data={"experiment_id": 3})
        self.assertEqual(response.status_code, 400)
        self.assertFalse(ExperimentGroup.objects.exists())
