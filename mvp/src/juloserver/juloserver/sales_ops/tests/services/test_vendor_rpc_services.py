import csv
import io
from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase
from django.contrib.auth.models import Group
from django.core.files import File
from django.utils import timezone

from juloserver.cfs.tests.factories import AgentFactory
from juloserver.julo.constants import UploadAsyncStateStatus, UploadAsyncStateType
from juloserver.julo.models import UploadAsyncState
from juloserver.julo.tests.factories import (
    AuthUserFactory,
    FeatureSettingFactory
)
from juloserver.sales_ops import exceptions as sales_ops_exc
from juloserver.sales_ops.constants import (
    VendorRPCConst,
    SalesOpsPDSConst,
)
from juloserver.sales_ops.services.vendor_rpc_services import (
    check_vendor_rpc_csv_format,
    save_vendor_rpc_csv,
    check_promo_code_for_sales_ops_pds,
)
from juloserver.promo.tests.factories import PromoCodeFactory
from juloserver.promo.constants import PromoCodeTypeConst


class TestVendorRPCCSVFormat(TestCase):
    def setUp(self):
        group = Group(name="sales_ops")
        group.save()
        self.user = AuthUserFactory()
        self.user.groups.add(group)
        self.agent = AgentFactory(user=self.user)
        FeatureSettingFactory(
            feature_name=VendorRPCConst.FS_NAME,
            is_active=True,
            category='sales_ops',
            parameters={
                'csv_headers': [
                    'account_id', 'vendor_id', 'agent_id', 'completed_date', 'is_rpc', 'bucket_code'
                ],
                'digit_fields': ['account_id', 'vendor_id', 'agent_id'],
                'date_fields': ['completed_date'],
                'boolean_fields': ['is_rpc'],
                'datetime_format': '%d/%m/%Y %H:%M:%S'
            },
        )

    def test_missing_headers(self):
        csv_list = [{
            'account_id': '12',
            'vendor_id': '33',
            'agent_id': '44',
            'completed_date': '4/7/2023 13:45:9',
            'is_rpc': 'True'
        }, {
            'account_id': '172',
            'vendor_id': '337',
            'agent_id': '464',
            'completed_date': '4/7/2023 13:45:9',
            'is_rpc': 'False'
        }]

        with self.assertRaises(sales_ops_exc.MissingCSVHeaderException):
            check_vendor_rpc_csv_format(csv_list)

    def test_invalid_digit_value(self):
        csv_list = [{
            'account_id': '1aaa2',
            'vendor_id': '33',
            'agent_id': '44',
            'completed_date': '4/7/2023 13:45:9',
            'is_rpc': 'True',
            'bucket_code': 'bucket_a'
        }]

        with self.assertRaises(sales_ops_exc.InvalidDigitValueException):
            check_vendor_rpc_csv_format(csv_list)

    def test_invalid_datetime_value(self):
        csv_list = [{
            'account_id': '12',
            'vendor_id': '33',
            'agent_id': '44',
            'completed_date': '4/17/2023 13:45:9',
            'is_rpc': 'True',
            'bucket_code': 'bucket_a'
        }]

        with self.assertRaises(sales_ops_exc.InvalidDatetimeValueException):
            check_vendor_rpc_csv_format(csv_list)

        csv_list = [{
            'account_id': '12',
            'vendor_id': '33',
            'agent_id': '44',
            'completed_date': '4/7/2023',
            'is_rpc': 'True',
            'bucket_code': 'bucket_a'
        }]

        with self.assertRaises(sales_ops_exc.InvalidDatetimeValueException):
            check_vendor_rpc_csv_format(csv_list)

    def test_invalid_boolean_value(self):
        csv_list = [{
            'account_id': '12',
            'vendor_id': '33',
            'agent_id': '44',
            'completed_date': '4/7/2023 13:45:9',
            'is_rpc': 'tru3',
            'bucket_code': 'bucket_a'
        }]

        with self.assertRaises(sales_ops_exc.InvalidBooleanValueException):
            check_vendor_rpc_csv_format(csv_list)

    def test_pass_all_checking(self):
        csv_list = [{
            'account_id': '12',
            'vendor_id': '33',
            'agent_id': '44',
            'completed_date': '4/7/2023 13:45:9',
            'is_rpc': 'true',
            'bucket_code': 'bucket_a'
        }]

        self.assertTrue(check_vendor_rpc_csv_format(csv_list))

    @patch('juloserver.sales_ops.services.vendor_rpc_services.upload_vendor_rpc_csv_to_oss')
    def test_upload_async_state(self, mock_upload_vendor_rpc_csv_to_oss):
        csv_data = [
            'account_id', 'vendor_id', 'agent_id', 'completed_date', 'is_rpc', 'bucket_code',
            '12', '22', '33', '4/7/2023 13:45:9', 'true', 'bucket_a',
            '1112', '45622', '657833', '14/7/2023 3:4:9', 'False', 'bucket_b',
        ]
        output = io.StringIO()
        writer = csv.writer(output, delimiter=',')
        writer.writerows(csv_data)
        upload_file = File(output, name='vendor_rpc.csv')

        save_vendor_rpc_csv(upload_file, self.agent)
        UploadAsyncState.objects.filter(
            task_type=UploadAsyncStateType.VENDOR_RPC_DATA,
            task_status=UploadAsyncStateStatus.WAITING,
            agent=self.agent,
        ).last()
        mock_upload_vendor_rpc_csv_to_oss.assert_called_once()


class TestVendorRPCSalesOpsPDS(TestCase):
    def setUp(self):
        self.feature_setting = FeatureSettingFactory(
            feature_name=SalesOpsPDSConst.PromoCode.FS_NAME,
            is_active=True,
            category=SalesOpsPDSConst.PromoCode.CATEGORY,
            parameters={},
        )
        self.promo_code = PromoCodeFactory(
            type=PromoCodeTypeConst.LOAN,
            is_active=True
        )

    def test_check_inactive_fs(self):
        self.feature_setting.update_safely(is_active=False)
        promo_code = check_promo_code_for_sales_ops_pds()
        self.assertIsNone(promo_code)

    def test_check_fs_non_setup(self):
        self.feature_setting.update_safely(parameters={'promo_code_id': None})
        with self.assertRaises(sales_ops_exc.InvalidSalesOpsPDSPromoCode):
            check_promo_code_for_sales_ops_pds()

    def test_check_fs_inactive_promo_code(self):
        self.promo_code.is_active = False
        self.promo_code.save()
        self.promo_code.refresh_from_db()
        self.feature_setting.update_safely(parameters={'promo_code_id': self.promo_code.id})
        with self.assertRaises(sales_ops_exc.InvalidSalesOpsPDSPromoCode):
            check_promo_code_for_sales_ops_pds()

    def test_check_fs_promo_code_wrong_type(self):
        self.promo_code.type = PromoCodeTypeConst.APPLICATION
        self.promo_code.save()
        self.promo_code.refresh_from_db()
        self.feature_setting.update_safely(parameters={'promo_code_id': self.promo_code.id})
        with self.assertRaises(sales_ops_exc.InvalidSalesOpsPDSPromoCode):
            check_promo_code_for_sales_ops_pds()

    def test_check_fs_promo_code_invalid_date(self):
        self.promo_code.start_date = timezone.localtime(timezone.now()) + timedelta(days=10)
        self.promo_code.save()
        self.promo_code.refresh_from_db()
        self.feature_setting.update_safely(parameters={'promo_code_id': self.promo_code.id})
        with self.assertRaises(sales_ops_exc.InvalidSalesOpsPDSPromoCode):
            check_promo_code_for_sales_ops_pds()

    def test_check_fs_valid_promo_code(self):
        self.feature_setting.update_safely(parameters={'promo_code_id': self.promo_code.id})
        promo_code = check_promo_code_for_sales_ops_pds()
        self.assertEqual(self.promo_code, promo_code)
