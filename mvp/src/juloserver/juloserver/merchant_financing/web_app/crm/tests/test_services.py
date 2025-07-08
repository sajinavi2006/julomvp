import csv
import io
import mock

from django.core.files import File
from django.test.testcases import TestCase
from django.db.utils import IntegrityError
from mock import patch

from juloserver.julo.tests.factories import (
    PartnerFactory,
    WorkflowFactory,
    ProductLineFactory,
)
from juloserver.account.tests.factories import AccountLookupFactory
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julovers.tests.factories import WorkflowStatusNodeFactory
from juloserver.julovers.tests.factories import WorkflowStatusPathFactory
from juloserver.julo.constants import WorkflowConst
from juloserver.partnership.models import PartnershipCustomerData
from juloserver.merchant_financing.web_app.services import (
    run_mf_web_app_register_upload_csv,
)


class TestProcessMFWebAppRegisterResult(TestCase):
    def setUp(self) -> None:
        self.data ={
            'nik_number': '2339860101912711',
            'email_borrower': 'prod+testaxiataupload10322@julofinance.com',
            'customer_name': 'Prod Only',
            'date_of_birth': '1997-04-28',
            'place_of_birth': 'Denpasar',
            'zipcode': '23611',
            'marital_status': 'Menikah',
            'handphone_number': '082218021557',
            'company_name': 'PT PROD ONLY',
            'address': 'Jl. Indonesia no 42',
            'provinsi': 'JAWA BARAT',
            'kabupaten':'BOGOR',
            'education': 'S1',
            'total_revenue_per_year': '50000000',
            'gender': 'Wanita',
            'business_category': 'Advertising',
            'proposed_limit': '50000000',
            'product_line': '501',
            'nib_number': '1234567891111',
            'user_type': 'lembaga',
            'kin_name': 'yaya',
            'kin_mobile_phone': '082218021557',
            'home_status': 'Milik sendiri, mencicil',
            'certificate_number': '1234567810',
            'certificate_date': '1997-04-28',
            'npwp': '1234567812345678',
            'business_entity': 'PERORANGAN',
        }
        self.partner = PartnerFactory(
            is_active=True,
            name="Axiata Web"
        )

        self.workflow = WorkflowFactory(name=WorkflowConst.MF_STANDARD_PRODUCT_WORKFLOW)
        self.product_line = ProductLineFactory(product_line_code=ProductLineCodes.AXIATA_WEB)
        self.account_lookup = AccountLookupFactory(workflow=self.workflow)

        WorkflowStatusPathFactory(
            status_previous=0,
            status_next=100,
            type='happy',
            is_active=True,
            workflow=self.workflow,
        )

        WorkflowStatusPathFactory(
            status_previous=100,
            status_next=105,
            type='happy',
            is_active=True,
            workflow=self.workflow,
        )

        WorkflowStatusPathFactory(
            status_previous=105,
            status_next=120,
            type='happy',
            is_active=True,
            workflow=self.workflow,
        )

        WorkflowStatusPathFactory(
            status_previous=120,
            status_next=121,
            type='happy',
            is_active=True,
            workflow=self.workflow,
        )

        WorkflowStatusPathFactory(
            status_previous=121,
            status_next=130,
            type='happy',
            is_active=True,
            workflow=self.workflow,
        )

        WorkflowStatusPathFactory(
            status_previous=130,
            status_next=190,
            type='happy',
            is_active=True,
            workflow=self.workflow,
        )

        WorkflowStatusPathFactory(
            status_previous=121,
            status_next=135,
            type='graveyard',
            is_active=True,
            workflow=self.workflow,
        )

        WorkflowStatusNodeFactory(status_node=100, workflow=self.workflow, handler='PartnershipMF100Handler')

        WorkflowStatusNodeFactory(status_node=105, workflow=self.workflow, handler='PartnershipMF105Handler')

        WorkflowStatusNodeFactory(status_node=120, workflow=self.workflow, handler='PartnershipMF120Handler')

        WorkflowStatusNodeFactory(status_node=121, workflow=self.workflow, handler='PartnershipMF121Handler')

        WorkflowStatusNodeFactory(status_node=130, workflow=self.workflow, handler='PartnershipMF130Handler')

        WorkflowStatusNodeFactory(status_node=135, workflow=self.workflow, handler='PartnershipMF135Handler')

        WorkflowStatusNodeFactory(status_node=190, workflow=self.workflow, handler='PartnershipMF190Handler')

    def test_service_csv_upload_web_app_registration_success(self) -> None:
        is_success, message = run_mf_web_app_register_upload_csv(
            self.data,
            self.partner
        )
        self.assertEqual(is_success, True)
        self.assertEqual(message, 'Success Create Application')

        customer_data  = PartnershipCustomerData.objects.filter(nik=self.data['nik_number']).last()
        application_status = customer_data.application.application_status_id

        self.assertIsNotNone(customer_data)

    @patch('juloserver.merchant_financing.web_app.services.process_application_status_change')
    def test_service_csv_upload_web_app_registration_failed(
        self,
        mock_process_application_status_change
    ) -> None:
        mock_process_application_status_change.side_effect = IntegrityError()
        is_success, message = run_mf_web_app_register_upload_csv(
            self.data,
            self.partner
        )
        self.assertEqual(is_success, False)
