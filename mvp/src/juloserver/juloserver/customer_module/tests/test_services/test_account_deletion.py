from itertools import product
from unittest import mock
from unittest.mock import patch, Mock
from django.test import TestCase

from juloserver.customer_module.services.account_deletion import (
    customer_deleteable_application_check,
    delete_ktp_and_selfie_file_from_oss,
    get_allowed_product_line_for_deletion,
    get_deleteable_application,
    is_complete_deletion,
    is_customer_manual_deletable,
    is_deleteable_application_already_deleted,
    mark_request_deletion_manual_deleted,
    send_web_account_deletion_received_success,
    send_web_account_deletion_received_failed,
    forward_web_account_deletion_request_to_ops,
)
from juloserver.customer_module.constants import (
    AccountDeletionFeatureName,
    AccountDeletionRequestStatuses,
)
from juloserver.customer_module.tests.factories import AccountDeletionRequestFactory
from juloserver.julo.tests.factories import (
    ApplicationFactory,
    AuthUserFactory,
    CustomerFactory,
    ProductLineFactory,
    WorkflowFactory,
)
from juloserver.account.tests.factories import AccountFactory
from juloserver.julo.constants import WorkflowConst
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.models import FeatureSetting


class TestDeleteKtpAndSelfieFromOSS(TestCase):
    @patch('juloserver.customer_module.services.account_deletion.delete_public_file_from_oss')
    def test_happy_path(
        self,
        mock_delete_public_file_from_oss,
    ):
        mock_delete_public_file_from_oss.return_value = None

        resp = delete_ktp_and_selfie_file_from_oss(
            'image_ktp_filepath',
            'image_selfie_filepath',
        )
        assert resp == None
        assert mock_delete_public_file_from_oss.call_count == 2


class TestSendWebAccountDeletionReceivedSuccess(TestCase):
    @patch('juloserver.customer_module.services.account_deletion.get_first_name')
    @patch('juloserver.customer_module.services.account_deletion.send_email_with_html')
    def test_happy_path(
        self,
        mock_get_first_name,
        mock_send_email_with_html,
    ):

        mock_customer = Mock()
        mock_customer.email = "test@julofinance.com"

        mock_get_first_name.return_value = 'first_name'
        mock_send_email_with_html.return_value = None

        resp = send_web_account_deletion_received_success(
            mock_customer,
        )

        assert resp == None
        mock_get_first_name.assert_called_once()
        mock_send_email_with_html.assert_called_once()


class TestSendWebAccountDeletionReceivedFailed(TestCase):
    @patch('juloserver.customer_module.services.account_deletion.send_email_with_html')
    def test_happy_path(
        self,
        mock_send_email_with_html,
    ):

        mock_send_email_with_html.return_value = None

        resp = send_web_account_deletion_received_failed(
            "test@julofinance.com",
        )

        assert resp == None
        mock_send_email_with_html.assert_called_once()


class TestForwardWebAccountDeletionToOps(TestCase):
    @patch('juloserver.customer_module.services.account_deletion.generate_image_attachment')
    @patch('juloserver.customer_module.services.account_deletion.send_email_with_html')
    def test_happy_path(
        self,
        mock_send_email_with_html,
        mock_generate_image_attachment,
    ):
        mock_generate_image_attachment.return_value = None
        mock_send_email_with_html.return_value = None

        resp = forward_web_account_deletion_request_to_ops(
            "fullname",
            "087777777777",
            "test@julofinance.com",
            "reason",
            "details",
            "image_ktp",
            "image_ktp_file_path.ext",
            "image_selfie",
            "image_selfie_file_path.ext",
        )
        assert resp == None
        assert mock_generate_image_attachment.call_count == 2
        mock_send_email_with_html.assert_called_once()


class TestMarkRequestDeletionManualDeleted(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()
        self.agent = AuthUserFactory()

    def test_customer_nil(self):
        try:
            mark_request_deletion_manual_deleted(self.agent, None, "test reason")
        except Exception as e:
            self.fail("should not raise error")

    def test_success(self):
        req = AccountDeletionRequestFactory(
            customer=self.customer,
            request_status=AccountDeletionRequestStatuses.PENDING,
        )
        mark_request_deletion_manual_deleted(self.agent, self.customer, "test reason")
        req.refresh_from_db()
        self.assertEqual(req.request_status, AccountDeletionRequestStatuses.MANUAL_DELETED)
        self.assertEqual(req.agent, self.agent)
        self.assertEqual(req.verdict_reason, "test reason")


class TestIsCustomerManualDeletable(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()
        AccountFactory(
            customer=self.customer,
        )

    @patch('juloserver.customer_module.services.account_deletion.is_account_status_deleteable')
    def test_account_status_not_deletable(self, mock_is_account_status_deleteable):
        mock_is_account_status_deleteable.return_value = False

        res, msg = is_customer_manual_deletable(self.customer)
        self.assertFalse(res)
        self.assertEqual(msg, 'Account status not deletable')

    @patch('juloserver.customer_module.services.account_deletion.is_account_status_deleteable')
    def test_already_deleted(self, mock_is_account_status_deleteable):
        mock_is_account_status_deleteable.return_value = True
        app1 = ApplicationFactory(
            customer=self.customer,
            workflow=WorkflowFactory(name=WorkflowConst.JULO_ONE),
            product_line=ProductLineFactory(product_line_code=ProductLineCodes.J1),
        )
        app1.update_safely(is_deleted=True)
        app2 = ApplicationFactory(
            customer=self.customer,
            workflow=WorkflowFactory(name=WorkflowConst.JULO_STARTER),
        )
        app2.update_safely(is_deleted=True)

        res, msg = is_customer_manual_deletable(self.customer)
        self.assertFalse(res)
        self.assertEqual(msg, 'Deleteable applications already deleted')

    @patch('juloserver.customer_module.services.account_deletion.is_account_status_deleteable')
    def test_deletable(self, mock_is_account_status_deleteable):
        mock_is_account_status_deleteable.return_value = True

        res, msg = is_customer_manual_deletable(self.customer)
        self.assertTrue(res)
        self.assertEqual(msg, '')


class TestGetDeleteableApplication(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()

    @patch(
        'juloserver.customer_module.services.account_deletion.get_allowed_product_line_for_deletion'
    )
    def test_success(self, mock_get_allowed_product_line_for_deletion):
        allowed_product_line_deletion = [
            ProductLineCodes.J1,
            ProductLineCodes.JTURBO,
            ProductLineCodes.MTL1,
            ProductLineCodes.MTL2,
            ProductLineCodes.CTL1,
            ProductLineCodes.CTL2,
            ProductLineCodes.STL1,
            ProductLineCodes.STL2,
            ProductLineCodes.LOC,
        ]
        mock_get_allowed_product_line_for_deletion.return_value = allowed_product_line_deletion

        for product_line_id in allowed_product_line_deletion:
            ApplicationFactory(
                customer=self.customer,
                product_line=ProductLineFactory(
                    product_line_code=product_line_id,
                ),
            )

        ApplicationFactory(
            customer=self.customer,
            product_line=ProductLineFactory(
                product_line_code=ProductLineCodes.GRAB,
            ),
        )

        deleteable_applications = get_deleteable_application(self.customer)
        self.assertEqual(len(deleteable_applications), len(allowed_product_line_deletion))


class TestCustomerDeleteableApplicationCheck(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()

    def test_no_application(self):
        is_deleteable = customer_deleteable_application_check(self.customer)
        self.assertTrue(is_deleteable)

    @patch(
        'juloserver.customer_module.services.account_deletion.get_allowed_product_line_for_deletion'
    )
    def test_deleteable_application_exists(self, mock_get_allowed_product_line_for_deletion):
        allowed_product_line_deletion = [
            ProductLineCodes.J1,
            ProductLineCodes.JTURBO,
            ProductLineCodes.MTL1,
            ProductLineCodes.MTL2,
            ProductLineCodes.CTL1,
            ProductLineCodes.CTL2,
            ProductLineCodes.STL1,
            ProductLineCodes.STL2,
            ProductLineCodes.LOC,
        ]
        mock_get_allowed_product_line_for_deletion.return_value = allowed_product_line_deletion
        for product_line_id in allowed_product_line_deletion:
            ApplicationFactory(
                customer=self.customer,
                product_line=ProductLineFactory(
                    product_line_code=product_line_id,
                ),
            )

        ApplicationFactory(
            customer=self.customer,
            product_line=ProductLineFactory(
                product_line_code=ProductLineCodes.GRAB,
            ),
        )

        is_deleteable = customer_deleteable_application_check(self.customer)
        self.assertTrue(is_deleteable)

    def test_no_deleteable_application(self):
        ApplicationFactory(
            customer=self.customer,
            product_line=ProductLineFactory(
                product_line_code=ProductLineCodes.GRAB,
            ),
        )

        is_deleteable = customer_deleteable_application_check(self.customer)
        self.assertFalse(is_deleteable)


class TestIsCompleteDeletion(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()

    @patch(
        'juloserver.customer_module.services.account_deletion.get_allowed_product_line_for_deletion'
    )
    def test_uncomplete_deletion(self, mock_get_allowed_product_line_for_deletion):
        allowed_product_line_deletion = [
            ProductLineCodes.J1,
            ProductLineCodes.JTURBO,
            ProductLineCodes.MTL1,
            ProductLineCodes.MTL2,
            ProductLineCodes.CTL1,
            ProductLineCodes.CTL2,
            ProductLineCodes.STL1,
            ProductLineCodes.STL2,
            ProductLineCodes.LOC,
        ]
        mock_get_allowed_product_line_for_deletion.return_value = allowed_product_line_deletion
        for product_line_id in allowed_product_line_deletion:
            ApplicationFactory(
                customer=self.customer,
                product_line=ProductLineFactory(
                    product_line_code=product_line_id,
                ),
            )

        ApplicationFactory(
            customer=self.customer,
            product_line=ProductLineFactory(
                product_line_code=ProductLineCodes.GRAB,
            ),
        )

        res = is_complete_deletion(self.customer)
        self.assertFalse(res)

    @patch(
        'juloserver.customer_module.services.account_deletion.get_allowed_product_line_for_deletion'
    )
    def test_complete_deletion(self, mock_get_allowed_product_line_for_deletion):
        allowed_product_line_deletion = [
            ProductLineCodes.J1,
            ProductLineCodes.JTURBO,
            ProductLineCodes.MTL1,
            ProductLineCodes.MTL2,
            ProductLineCodes.CTL1,
            ProductLineCodes.CTL2,
            ProductLineCodes.STL1,
            ProductLineCodes.STL2,
            ProductLineCodes.LOC,
        ]
        mock_get_allowed_product_line_for_deletion.return_value = allowed_product_line_deletion
        for product_line_id in allowed_product_line_deletion:
            ApplicationFactory(
                customer=self.customer,
                product_line=ProductLineFactory(
                    product_line_code=product_line_id,
                ),
            )

        res = is_complete_deletion(self.customer)
        self.assertTrue(res)


class TestIsDeleteableApplicationAlreadyDeleted(TestCase):
    def setUp(self):
        self.customer = CustomerFactory()

    def test_no_application(self):
        is_deleted = is_deleteable_application_already_deleted(self.customer)
        self.assertFalse(is_deleted)

    @patch(
        'juloserver.customer_module.services.account_deletion.get_allowed_product_line_for_deletion'
    )
    def test_one_active(self, mock_get_allowed_product_line_for_deletion):
        allowed_product_line_deletion = [
            ProductLineCodes.J1,
            ProductLineCodes.JTURBO,
            ProductLineCodes.MTL1,
            ProductLineCodes.MTL2,
            ProductLineCodes.CTL1,
            ProductLineCodes.CTL2,
            ProductLineCodes.STL1,
            ProductLineCodes.STL2,
            ProductLineCodes.LOC,
        ]
        mock_get_allowed_product_line_for_deletion.return_value = allowed_product_line_deletion
        for product_line_id in allowed_product_line_deletion:
            ApplicationFactory(
                customer=self.customer,
                product_line=ProductLineFactory(
                    product_line_code=product_line_id,
                ),
                is_deleted=True,
            )

        app = self.customer.application_set.last()
        app.is_deleted = False
        app.save()

        is_deleted = is_deleteable_application_already_deleted(self.customer)
        self.assertFalse(is_deleted)

    @patch(
        'juloserver.customer_module.services.account_deletion.get_allowed_product_line_for_deletion'
    )
    def test_all_deleted(self, mock_get_allowed_product_line_for_deletion):
        allowed_product_line_deletion = [
            ProductLineCodes.J1,
            ProductLineCodes.JTURBO,
            ProductLineCodes.MTL1,
            ProductLineCodes.MTL2,
            ProductLineCodes.CTL1,
            ProductLineCodes.CTL2,
            ProductLineCodes.STL1,
            ProductLineCodes.STL2,
            ProductLineCodes.LOC,
        ]
        mock_get_allowed_product_line_for_deletion.return_value = allowed_product_line_deletion
        for product_line_id in allowed_product_line_deletion:
            ApplicationFactory(
                customer=self.customer,
                product_line=ProductLineFactory(
                    product_line_code=product_line_id,
                ),
                is_deleted=True,
            )

        is_deleted = is_deleteable_application_already_deleted(self.customer)
        self.assertTrue(is_deleted)


class TestGetAllowedProductLineForDeletion(TestCase):
    def setUp(self):
        self.supported_plines = [
            None,
            ProductLineCodes.J1,
            ProductLineCodes.JTURBO,
            ProductLineCodes.MTL1,
            ProductLineCodes.MTL2,
            ProductLineCodes.CTL1,
            ProductLineCodes.CTL2,
            ProductLineCodes.STL1,
            ProductLineCodes.STL2,
            ProductLineCodes.LOC,
        ]
        self.feature_setting = FeatureSetting.objects.filter(
            feature_name=AccountDeletionFeatureName.SUPPORTED_PRODUCT_LINE_DELETION,
        ).first()
        if self.feature_setting:
            self.feature_setting.parameters = {
                'supported_product_line': self.supported_plines,
            }
            self.feature_setting.is_active = True
            self.feature_setting.save()
        else:
            self.feature_setting = FeatureSetting.objects.create(
                feature_name=AccountDeletionFeatureName.SUPPORTED_PRODUCT_LINE_DELETION,
                is_active=True,
                parameters={
                    'supported_product_line': self.supported_plines,
                },
            )

    def test_feature_setting_not_active(self):
        self.feature_setting.is_active = False
        self.feature_setting.save()

        allowed_plines = get_allowed_product_line_for_deletion()
        self.assertEqual(
            allowed_plines,
            [
                None,
                ProductLineCodes.J1,
                ProductLineCodes.JTURBO,
                ProductLineCodes.MTL1,
                ProductLineCodes.MTL2,
                ProductLineCodes.CTL1,
                ProductLineCodes.CTL2,
                ProductLineCodes.STL1,
                ProductLineCodes.STL2,
                ProductLineCodes.LOC,
            ],
        )

    def test_feature_setting_active(self):
        allowed_plines = get_allowed_product_line_for_deletion()
        self.assertEqual(allowed_plines, self.supported_plines)
