from django.test import TestCase
from mock import patch
from datetime import datetime
from juloserver.customer_module.utils.utils_crm_v1 import (
    get_customer_deletion_type,
    get_timestamp_format_for_email,
)
from juloserver.account.tests.factories import AccountFactory
from juloserver.customer_module.constants import CustomerRemovalDeletionTypes
from juloserver.julo.statuses import ApplicationStatusCodes, JuloOneCodes
from juloserver.julo.tests.factories import (
    ApplicationFactory,
    ApplicationHistoryFactory,
    CustomerFactory,
    ProductLineFactory,
    StatusLookupFactory,
)
from juloserver.julo.product_lines import ProductLineCodes


class TestGetTimestampFormatForEmail(TestCase):
    def test_happy_path(
        self,
    ):
        mock_datetime = datetime(2020, 1, 1, 1, 1, 1)
        expected_timestamp = '01-01-2020 | 01:01:01 WIB'
        timestamp = get_timestamp_format_for_email(mock_datetime)
        self.assertEqual(timestamp, expected_timestamp)

    @patch('juloserver.customer_module.utils.utils_crm_v1.datetime')
    def test_empty(
        self,
        mock_datetime,
    ):
        mock_datetime.now.return_value = datetime(2020, 1, 1, 1, 1, 1)
        expected_timestamp = '01-01-2020 | 01:01:01 WIB'
        timestamp = get_timestamp_format_for_email(None)
        self.assertEqual(timestamp, expected_timestamp)


class TestGetCustomerDeletionType(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()
        self.account = AccountFactory(
            customer=self.customer,
        )

    def test_soft_delete_account_status(self):
        self.account.status = StatusLookupFactory(
            status_code=JuloOneCodes.INACTIVE,
        )
        self.account.save()

        deletion_type = get_customer_deletion_type(self.customer)
        self.assertEqual(deletion_type, CustomerRemovalDeletionTypes.SOFT_DELETE)

    def test_soft_delete_application_status(self):
        app = ApplicationFactory(customer=self.customer)
        app.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_FRAUD,
        )
        app.product_line = ProductLineFactory(
            product_line_code=ProductLineCodes.J1,
        )
        app.save()

        app = ApplicationFactory(customer=self.customer)
        app.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.LOC_APPROVED,
        )
        app.product_line = ProductLineFactory(
            product_line_code=ProductLineCodes.JTURBO,
        )
        app.save()

        deletion_type = get_customer_deletion_type(self.customer)
        self.assertEqual(deletion_type, CustomerRemovalDeletionTypes.SOFT_DELETE)

    def test_deleted_soft_delete_application_status(self):
        app = ApplicationFactory(customer=self.customer)
        app.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.LOC_APPROVED,
        )
        app.product_line = ProductLineFactory(
            product_line_code=ProductLineCodes.DANA,
        )
        app.save()

        app = ApplicationFactory(customer=self.customer)
        app.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.CUSTOMER_DELETED,
        )
        app.product_line = ProductLineFactory(
            product_line_code=ProductLineCodes.J1,
        )
        app.is_deleted = True
        app.save()

        ApplicationHistoryFactory(
            application_id=app.id,
            status_new=ApplicationStatusCodes.CUSTOMER_DELETED,
            status_old=ApplicationStatusCodes.APPLICATION_FLAGGED_FOR_FRAUD,
        )

        deletion_type = get_customer_deletion_type(self.customer)
        self.assertEqual(deletion_type, CustomerRemovalDeletionTypes.SOFT_DELETE)

    def test_hard_delete(self):
        self.account.status = StatusLookupFactory(
            status_code=JuloOneCodes.ACTIVE,
        )
        self.account.save()

        app = ApplicationFactory(customer=self.customer)
        app.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.LOC_APPROVED,
        )
        app.product_line = ProductLineFactory(
            product_line_code=ProductLineCodes.J1,
        )
        app.save()

        app = ApplicationFactory(customer=self.customer)
        app.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.JULO_STARTER_TURBO_UPGRADE,
        )
        app.product_line = ProductLineFactory(
            product_line_code=ProductLineCodes.JTURBO,
        )
        app.save()

        deletion_type = get_customer_deletion_type(self.customer)
        self.assertEqual(deletion_type, CustomerRemovalDeletionTypes.HARD_DELETE)
