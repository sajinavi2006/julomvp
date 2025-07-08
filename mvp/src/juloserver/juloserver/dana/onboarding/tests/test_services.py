import uuid

from django.test.testcases import TestCase

from juloserver.account.tests.factories import (
    AccountFactory,
    AccountLimitFactory,
    AccountLookupFactory,
)
from juloserver.application_flow.constants import PartnerNameConstant
from juloserver.dana.constants import (
    DANA_BANK_NAME,
    DANA_ACCOUNT_LOOKUP_NAME,
)

from juloserver.dana.onboarding.services import dana_populate_pusdafil_data
from juloserver.dana.tests.factories import (
    DanaCustomerDataFactory,
    DanaApplicationReferenceFactory,
    DanaFDCResultFactory,
)
from juloserver.disbursement.constants import NameBankValidationStatus
from juloserver.disbursement.tests.factories import NameBankValidationFactory
from juloserver.julo.constants import WorkflowConst, FeatureNameConst
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.tests.factories import (
    PartnerFactory,
    ProductLineFactory,
    WorkflowFactory,
    CustomerFactory,
    ApplicationFactory,
    FeatureSettingFactory,
)


class TestDanaOnboardingService(TestCase):
    def setUp(self) -> None:
        self.partner = PartnerFactory(name=PartnerNameConstant.DANA, is_active=True)
        self.workflow = WorkflowFactory(name=WorkflowConst.DANA)
        self.account_lookup = AccountLookupFactory(
            partner=self.partner, workflow=self.workflow, name=DANA_ACCOUNT_LOOKUP_NAME
        )

        product_line_code = ProductLineCodes.DANA
        self.product_line = ProductLineFactory(
            product_line_type=DANA_ACCOUNT_LOOKUP_NAME, product_line_code=product_line_code
        )

        self.customer = CustomerFactory()
        self.account = AccountFactory()
        self.account_limit_factory = AccountLimitFactory(
            account=self.account,
            max_limit=500000,
            set_limit=500000,
            available_limit=200000,
            used_limit=300000,
        )
        self.name_bank_validation = NameBankValidationFactory(
            bank_code='BCA',
            account_number='9999999999999',
            name_in_bank=DANA_BANK_NAME,
            validation_status=NameBankValidationStatus.SUCCESS,
            mobile_phone='087790909090',
            method='xfers',
        )
        self.application = ApplicationFactory(
            account=self.account,
            customer=self.customer,
            product_line=self.product_line,
            name_bank_validation=self.name_bank_validation,
            partner=self.partner,
        )
        self.dana_customer_data = DanaCustomerDataFactory(
            account=self.account,
            customer=self.customer,
            partner=self.partner,
            application=self.application,
            dana_customer_identifier="12345679237",
            credit_score=750,
            lender_product_id='LP0001',
        )

        application_id = self.application.id
        self.dana_application_reference = DanaApplicationReferenceFactory(
            application_id=application_id,
            partner_reference_no='1234555',
            reference_no=uuid.uuid4(),
        )

        self.dana_fdc_result = DanaFDCResultFactory(
            fdc_status="Approve1",
            status="success",
            dana_customer_identifier="12345679237",
            application_id=application_id,
            lender_product_id="LP0001",
        )

        mapping_province_parameters = {
            "city": {"KAB BURU": "Kab. Buru"},
            "province": {"BALI": "Bali"},
        }

        job_mapping_parameters = {"job": {"PNS": "Pegawai Negeri Sipil"}}
        self.dana_mapping_address_factory = FeatureSettingFactory(
            is_active=True,
            feature_name=FeatureNameConst.DANA_PROVINCE_AND_CITY,
            description="address",
            parameters=mapping_province_parameters,
        )
        self.dana_occupation_factory = FeatureSettingFactory(
            is_active=True,
            feature_name=FeatureNameConst.DANA_JOB,
            description="occupation",
            parameters=job_mapping_parameters,
        )

    def test_populate_pusdafil_data(self) -> None:
        self.dana_customer_data.city_home_address = 'Kab bURU'
        self.dana_customer_data.province_home_address = 'bali'
        self.dana_customer_data.occupation = 'pns'
        self.dana_customer_data.save()
        self.dana_customer_data.refresh_from_db()
        dana_populate_pusdafil_data(self.dana_customer_data)

        self.application.refresh_from_db()
        self.assertEqual(self.application.address_provinsi, "Bali")
        self.assertEqual(self.application.address_kabupaten, "Kab. Buru")
        self.assertEqual(self.application.job_type, "Pegawai Negeri Sipil")
        self.assertEqual(self.application.job_industry, "Service")
