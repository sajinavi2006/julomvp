import csv
import io
from datetime import datetime
from unittest.mock import patch, call
from django.core.files import File
from django.test.testcases import TestCase
from juloserver.account.tests.factories import AccountFactory
from juloserver.cfs.tests.factories import AgentFactory
from juloserver.julo.constants import (
    UploadAsyncStateStatus,
    UploadAsyncStateType,
)
from juloserver.julo.models import (
    UploadAsyncState,
)
from juloserver.julo.statuses import ApplicationStatusCodes
from juloserver.julo.tests.factories import (
    ApplicationFactory,
    AuthUserFactory,
    CustomerFactory,
    FeatureSettingFactory,
)
from juloserver.julovers.tests.factories import (
    UploadAsyncStateFactory,
)
from juloserver.sales_ops.constants import SalesOpsPDSConst
from juloserver.sales_ops.models import SalesOpsAgentAssignment, SalesOpsLineup
from juloserver.sales_ops.tasks import update_rpc_from_vendor_task
from juloserver.sales_ops.tests.factories import (
    SalesOpsLineupFactory,
    SalesOpsVendorAgentMappingFactory,
    SalesOpsVendorFactory,
    SalesOpsAgentAssignmentFactory,
)
from juloserver.sales_ops.utils import convert_string_to_datetime
from juloserver.promo.constants import PromoCodeTypeConst
from juloserver.promo.tests.factories import PromoCodeFactory

HEADER = [
    'account_id', 'vendor_id', 'user_extension', 'completed_date', 'is_rpc'
]

PACKAGE_NAME = 'juloserver.sales_ops.services.vendor_rpc_services'


class TestProcessSalesOpsUploadRPCTask(TestCase):
    def setUp(self):
        self.user = AuthUserFactory(is_superuser=True, is_staff=True)
        self.agent = AgentFactory(user=self.user, user_extension='agent_test_1')
        # Sales Ops 1
        self.customer_1 = CustomerFactory()
        self.account_1 = AccountFactory()
        self.application_1 = ApplicationFactory(
            account=self.account_1,
            customer=self.customer_1,
        )
        self.application_1.application_status_id = ApplicationStatusCodes.LOC_APPROVED
        self.application_1.save()
        self.sales_ops_lineup_1 = SalesOpsLineupFactory(
            account=self.account_1,
            latest_application=self.application_1,
            is_active=True,
        )

        # Sales Ops 2
        self.customer_2 = CustomerFactory()
        self.account_2 = AccountFactory()
        self.application_2 = ApplicationFactory(
            account=self.account_2,
            customer=self.customer_2,
        )
        self.application_2.application_status_id = ApplicationStatusCodes.LOC_APPROVED
        self.application_2.save()
        self.sales_ops_lineup_2 = SalesOpsLineupFactory(
            account=self.account_2,
            latest_application=self.application_2,
            is_active=True,
        )

        self.vendor = SalesOpsVendorFactory()
        SalesOpsVendorAgentMappingFactory(
            agent_id=self.agent.id, vendor=self.vendor, is_active=True
        )
        self.promo_code = PromoCodeFactory(type=PromoCodeTypeConst.LOAN, is_active=True)

    @patch('django.utils.timezone.now')
    @patch(f'{PACKAGE_NAME}.read_csv_file')
    def test_update_rpc_from_vendor_partial_task(self, mock_read_csv_file, mock_now):
        mock_now.return_value = datetime(2024, 3, 26, 12, 0, 0)
        invalid_data = [
            HEADER,
            [
                '12345', str(self.vendor.id), self.agent.user_extension, '01-01-2023 10:10:10', 'RPC',
            ],
            [
                str(self.account_1.id), 1000, self.agent.user_extension, '01-01-2023 10:10:10', 'RPC',
            ],
            [
                str(self.account_1.id), str(self.vendor.id), self.agent.user_extension,
                '01-01-2023 10:10:10', 'true',
            ],
            [
                str(self.account_1.id), str(self.vendor.id), 'wrong_agent',
                '01-01-2023 10:10:10', 'true',
            ],
            [
                str(self.account_1.id), str(self.vendor.id), self.agent.user_extension,
                '01-01-9999 10:10:10', 'true',
            ],
            [
                str(self.account_1.id), str(self.vendor.id), self.agent.user_extension,
                '57934789 $%^', 'true',
            ],
        ]
        upload_async_state = UploadAsyncStateFactory(
            task_status=UploadAsyncStateStatus.WAITING,
            task_type=UploadAsyncStateType.VENDOR_RPC_DATA,
        )
        upload_async_state.save()
        upload_async_state.update_safely(url='vendor_rpc/{}/sales_ops_vendor_rpc.csv'.format(
            upload_async_state.id
        ))
        output = io.StringIO()
        writer = csv.writer(output, delimiter=',')
        writer.writerows(invalid_data)
        upload_file = File(output, name='vendor_rpc.csv')
        reader = csv.DictReader(upload_file, delimiter=',')
        mock_read_csv_file.return_value = reader
        # no 1 => sales ops does not existed
        # no 2 => sales ops agent mapping does not existed
        # no 3 => success
        # no 4 => agent does not existed
        # no 5 => wrong completed date
        # no 6 => invalid format completed date
        update_rpc_from_vendor_task(upload_async_state.id)
        upload_async_state = UploadAsyncState.objects.filter(id=upload_async_state.id).first()
        sales_ops_agent_assignment = SalesOpsAgentAssignment.objects.get(
            agent_id=self.agent.id, lineup_id=self.sales_ops_lineup_1.id
        )
        self.assertEqual(sales_ops_agent_assignment.is_rpc, True)
        completed_date = convert_string_to_datetime(
            '01-01-2023 10:10:10', "%d-%m-%Y %H:%M:%S"
        )
        self.assertEqual(sales_ops_agent_assignment.completed_date, completed_date)
        self.assertEqual(upload_async_state.task_status, UploadAsyncStateStatus.PARTIAL_COMPLETED)
        self.assertEqual(upload_async_state.error_detail, "Data invalid please check")

    @patch('django.utils.timezone.now')
    @patch(f'{PACKAGE_NAME}.read_csv_file')
    def test_update_rpc_from_vendor_completed_task(self, mock_read_csv_file, mock_now):
        mock_now.return_value = datetime(2024, 3, 26, 12, 0, 0)
        valid_data = [
            HEADER,
            [
                str(self.account_1.id), str(self.vendor.id), self.agent.user_extension,
                '01-01-2023 10:10:10', 'false',
            ],
            [
                str(self.account_2.id), str(self.vendor.id), self.agent.user_extension,
                '01-01-2023 10:10:10', 'true',
            ]
        ]
        upload_async_state = UploadAsyncStateFactory(
            task_status=UploadAsyncStateStatus.WAITING,
            task_type=UploadAsyncStateType.VENDOR_RPC_DATA,
        )
        upload_async_state.save()
        upload_async_state.update_safely(url='vendor_rpc/{}/sales_ops_vendor_rpc.csv'.format(
            upload_async_state.id
        ))
        output = io.StringIO()
        writer = csv.writer(output, delimiter=',')
        writer.writerows(valid_data)
        upload_file = File(output, name='vendor_rpc.csv')
        reader = csv.DictReader(upload_file, delimiter=',')
        mock_read_csv_file.return_value = reader

        update_rpc_from_vendor_task(upload_async_state.id)
        upload_async_state = UploadAsyncState.objects.filter(id=upload_async_state.id).first()
        sales_ops_agent_assignment_1 = SalesOpsAgentAssignment.objects.get(
            agent_id=self.agent.id, lineup_id=self.sales_ops_lineup_1.id
        )
        sales_ops_agent_assignment_2 = SalesOpsAgentAssignment.objects.get(
            agent_id=self.agent.id, lineup_id=self.sales_ops_lineup_2.id
        )

        completed_date = convert_string_to_datetime(
            '01-01-2023 10:10:10', "%d-%m-%Y %H:%M:%S"
        )
        self.assertEqual(sales_ops_agent_assignment_1.completed_date, completed_date)
        self.assertEqual(sales_ops_agent_assignment_2.completed_date, completed_date)
        self.assertEqual(upload_async_state.task_status, UploadAsyncStateStatus.COMPLETED)

    @patch('django.utils.timezone.now')
    @patch(f'{PACKAGE_NAME}.read_csv_file')
    def test_update_rpc_from_vendor_latest_rpc_agent_assignment(self, mock_read_csv_file, mock_now):
        mock_now.return_value = datetime(2024, 3, 26, 12, 0, 0)
        valid_data = [
            HEADER,
            [
                str(self.account_1.id), str(self.vendor.id), self.agent.user_extension,
                '01-01-2023 10:10:10', 'false',
            ],
            [
                str(self.account_2.id), str(self.vendor.id), self.agent.user_extension,
                '01-01-2023 10:10:10', 'true',
            ]
        ]
        upload_async_state = UploadAsyncStateFactory(
            task_status=UploadAsyncStateStatus.WAITING,
            task_type=UploadAsyncStateType.VENDOR_RPC_DATA,
        )
        upload_async_state.save()
        upload_async_state.update_safely(url='vendor_rpc/{}/sales_ops_vendor_rpc.csv'.format(
            upload_async_state.id
        ))
        output = io.StringIO()
        writer = csv.writer(output, delimiter=',')
        writer.writerows(valid_data)
        upload_file = File(output, name='vendor_rpc.csv')
        reader = csv.DictReader(upload_file, delimiter=',')
        mock_read_csv_file.return_value = reader

        update_rpc_from_vendor_task(upload_async_state.id)
        upload_async_state = UploadAsyncState.objects.filter(id=upload_async_state.id).first()
        sales_ops_agent_assignment_1 = SalesOpsAgentAssignment.objects.get(
            agent_id=self.agent.id, lineup_id=self.sales_ops_lineup_1.id
        )
        sales_ops_agent_assignment_2 = SalesOpsAgentAssignment.objects.get(
            agent_id=self.agent.id, lineup_id=self.sales_ops_lineup_2.id
        )

        completed_date = convert_string_to_datetime(
            '01-01-2023 10:10:10', "%d-%m-%Y %H:%M:%S"
        )

        self.sales_ops_lineup_1.refresh_from_db()
        self.sales_ops_lineup_2.refresh_from_db()

        self.assertEqual(
            self.sales_ops_lineup_1.latest_agent_assignment_id, sales_ops_agent_assignment_1.id
        )
        self.assertIsNone(self.sales_ops_lineup_1.latest_rpc_agent_assignment_id)
        self.assertEqual(sales_ops_agent_assignment_1.is_rpc, False)
        self.assertEqual(sales_ops_agent_assignment_1.completed_date, completed_date)

        self.assertEqual(
            self.sales_ops_lineup_2.latest_agent_assignment_id, sales_ops_agent_assignment_2.id
        )
        self.assertEqual(
            self.sales_ops_lineup_2.latest_rpc_agent_assignment_id, sales_ops_agent_assignment_2.id
        )
        self.assertEqual(sales_ops_agent_assignment_2.is_rpc, True)
        self.assertEqual(sales_ops_agent_assignment_2.completed_date, completed_date)
        self.assertEqual(upload_async_state.task_status, UploadAsyncStateStatus.COMPLETED)

    @patch('django.utils.timezone.now')
    @patch(f'{PACKAGE_NAME}.read_csv_file')
    def test_update_rpc_from_vendor_full_non_rpc_no_agent_assignment(self,
                                                                     mock_read_csv_file,
                                                                     mock_now):
        mock_now.return_value = datetime(2024, 3, 26, 12, 0, 0)
        valid_data = [
            HEADER,
            [
                str(self.account_1.id), str(self.vendor.id), self.agent.user_extension,
                '25-03-2024 10:10:10', 'false',
            ],
            [
                str(self.account_1.id), str(self.vendor.id), self.agent.user_extension,
                '25-03-2024 10:10:10', 'false',
            ]
        ]
        upload_async_state = UploadAsyncStateFactory(
            task_status=UploadAsyncStateStatus.WAITING,
            task_type=UploadAsyncStateType.VENDOR_RPC_DATA,
        )
        upload_async_state.save()
        upload_async_state.update_safely(url='vendor_rpc/{}/sales_ops_vendor_rpc.csv'.format(
            upload_async_state.id
        ))
        output = io.StringIO()
        writer = csv.writer(output, delimiter=',')
        writer.writerows(valid_data)
        upload_file = File(output, name='vendor_rpc.csv')
        reader = csv.DictReader(upload_file, delimiter=',')
        mock_read_csv_file.return_value = reader

        update_rpc_from_vendor_task(upload_async_state.id)
        upload_async_state = UploadAsyncState.objects.filter(id=upload_async_state.id).first()
        latest_agent_assignment = (
            SalesOpsAgentAssignment.objects.filter(
                agent_id=self.agent.id, lineup_id=self.sales_ops_lineup_1.id
            )
            .order_by('completed_date', 'id')
            .last()
        )
        self.sales_ops_lineup_1.refresh_from_db()

        lineup_latest_agent_assignment_id = self.sales_ops_lineup_1.latest_agent_assignment_id
        lineup_latest_agent_assignment = SalesOpsAgentAssignment.objects.get_or_none(
            pk=lineup_latest_agent_assignment_id
        )

        # Check lineup
        self.assertEqual(lineup_latest_agent_assignment_id, latest_agent_assignment.id)

        # Check lineup latest agent assignment
        self.assertEqual(lineup_latest_agent_assignment.is_rpc, False)
        self.assertEqual(
            lineup_latest_agent_assignment.completed_date, convert_string_to_datetime(
                '25-03-2024 10:10:10', "%d-%m-%Y %H:%M:%S"
            )
        )
        self.assertEqual(lineup_latest_agent_assignment.non_rpc_attempt, 2)
        self.assertEqual(upload_async_state.task_status, UploadAsyncStateStatus.COMPLETED)

    @patch('django.utils.timezone.now')
    @patch(f'{PACKAGE_NAME}.read_csv_file')
    def test_update_rpc_from_vendor_full_non_rpc_correct_day(self,
                                                             mock_read_csv_file,
                                                             mock_now):
        mock_now.return_value = datetime(2024, 3, 26, 12, 0, 0)
        agent_assignment = SalesOpsAgentAssignmentFactory(
            lineup_id=self.sales_ops_lineup_1.id,
            agent_id=self.agent.id,
            completed_date=datetime(2024, 3, 24, 12, 23, 34),
            non_rpc_attempt=2,
            is_rpc=False
        )
        self.sales_ops_lineup_1.update_safely(latest_agent_assignment_id=agent_assignment.id)

        valid_data = [
            HEADER,
            [
                str(self.account_1.id), str(self.vendor.id), self.agent.user_extension,
                '25-03-2024 10:10:10', 'false',
            ],
            [
                str(self.account_1.id), str(self.vendor.id), self.agent.user_extension,
                '25-03-2024 10:10:10', 'false',
            ]
        ]
        upload_async_state = UploadAsyncStateFactory(
            task_status=UploadAsyncStateStatus.WAITING,
            task_type=UploadAsyncStateType.VENDOR_RPC_DATA,
        )
        upload_async_state.save()
        upload_async_state.update_safely(url='vendor_rpc/{}/sales_ops_vendor_rpc.csv'.format(
            upload_async_state.id
        ))
        output = io.StringIO()
        writer = csv.writer(output, delimiter=',')
        writer.writerows(valid_data)
        upload_file = File(output, name='vendor_rpc.csv')
        reader = csv.DictReader(upload_file, delimiter=',')
        mock_read_csv_file.return_value = reader

        update_rpc_from_vendor_task(upload_async_state.id)
        upload_async_state = UploadAsyncState.objects.filter(id=upload_async_state.id).first()
        latest_agent_assignment = (
            SalesOpsAgentAssignment.objects.filter(
                agent_id=self.agent.id, lineup_id=self.sales_ops_lineup_1.id
            )
            .order_by('completed_date', 'id')
            .last()
        )
        self.sales_ops_lineup_1.refresh_from_db()

        lineup_latest_agent_assignment_id = self.sales_ops_lineup_1.latest_agent_assignment_id
        lineup_latest_agent_assignment = SalesOpsAgentAssignment.objects.get(
            pk=lineup_latest_agent_assignment_id
        )

        # Check lineup
        self.assertEqual(lineup_latest_agent_assignment_id, latest_agent_assignment.id)
        self.assertNotEqual(lineup_latest_agent_assignment_id, agent_assignment.id)

        # Check lineup latest agent assignment
        self.assertEqual(lineup_latest_agent_assignment.is_rpc, False)
        self.assertEqual(
            lineup_latest_agent_assignment.completed_date, convert_string_to_datetime(
                '25-03-2024 10:10:10', "%d-%m-%Y %H:%M:%S"
            )
        )
        self.assertEqual(lineup_latest_agent_assignment.non_rpc_attempt, 4)
        self.assertEqual(upload_async_state.task_status, UploadAsyncStateStatus.COMPLETED)

    @patch('django.utils.timezone.now')
    @patch(f'{PACKAGE_NAME}.read_csv_file')
    def test_update_rpc_from_vendor_full_non_rpc_incorrect_day(self,
                                                               mock_read_csv_file,
                                                               mock_now):
        mock_now.return_value = datetime(2024, 3, 26, 12, 0, 0)
        agent_assignment = SalesOpsAgentAssignmentFactory(
            lineup_id=self.sales_ops_lineup_1.id,
            agent_id=self.agent.id,
            completed_date=datetime(2024, 3, 25, 12, 23, 34),
            non_rpc_attempt=2,
            is_rpc=False
        )
        self.sales_ops_lineup_1.update_safely(latest_agent_assignment_id=agent_assignment.id)

        valid_data = [
            HEADER,
            [
                str(self.account_1.id), str(self.vendor.id), self.agent.user_extension,
                '24-03-2024 10:10:10', 'false',
            ],
            [
                str(self.account_1.id), str(self.vendor.id), self.agent.user_extension,
                '24-03-2024 10:10:10', 'false',
            ]
        ]
        upload_async_state = UploadAsyncStateFactory(
            task_status=UploadAsyncStateStatus.WAITING,
            task_type=UploadAsyncStateType.VENDOR_RPC_DATA,
        )
        upload_async_state.save()
        upload_async_state.update_safely(url='vendor_rpc/{}/sales_ops_vendor_rpc.csv'.format(
            upload_async_state.id
        ))
        output = io.StringIO()
        writer = csv.writer(output, delimiter=',')
        writer.writerows(valid_data)
        upload_file = File(output, name='vendor_rpc.csv')
        reader = csv.DictReader(upload_file, delimiter=',')
        mock_read_csv_file.return_value = reader

        update_rpc_from_vendor_task(upload_async_state.id)
        upload_async_state = UploadAsyncState.objects.filter(id=upload_async_state.id).first()
        latest_agent_assignment = (
            SalesOpsAgentAssignment.objects.filter(
                agent_id=self.agent.id, lineup_id=self.sales_ops_lineup_1.id
            )
            .order_by('completed_date', 'id')
            .last()
        )
        self.sales_ops_lineup_1.refresh_from_db()

        lineup_latest_agent_assignment_id = self.sales_ops_lineup_1.latest_agent_assignment_id
        lineup_latest_agent_assignment = SalesOpsAgentAssignment.objects.get(
            pk=lineup_latest_agent_assignment_id
        )

        # Check lineup
        self.assertEqual(lineup_latest_agent_assignment, latest_agent_assignment)
        self.assertEqual(lineup_latest_agent_assignment, agent_assignment)

        # Check lineup agent assignment
        self.assertEqual(lineup_latest_agent_assignment.is_rpc, False)
        self.assertEqual(
            lineup_latest_agent_assignment.completed_date, convert_string_to_datetime(
                '25-03-2024 12:23:34', "%d-%m-%Y %H:%M:%S"
            )
        )
        self.assertEqual(lineup_latest_agent_assignment.non_rpc_attempt, 4)
        self.assertEqual(upload_async_state.task_status, UploadAsyncStateStatus.COMPLETED)

    @patch('django.utils.timezone.now')
    @patch(f'{PACKAGE_NAME}.read_csv_file')
    def test_update_rpc_from_vendor_correct_day_1(self, mock_read_csv_file, mock_now):
        mock_now.return_value = datetime(2024, 3, 26, 12, 0, 0)
        agent_assignment = SalesOpsAgentAssignmentFactory(
            lineup_id=self.sales_ops_lineup_1.id,
            agent_id=self.agent.id,
            completed_date=datetime(2024, 3, 24, 12, 23, 34),
            non_rpc_attempt=2,
            is_rpc=False
        )
        self.sales_ops_lineup_1.update_safely(latest_agent_assignment_id=agent_assignment.id)

        valid_data = [
            HEADER,
            [
                str(self.account_1.id), str(self.vendor.id), self.agent.user_extension,
                '25-03-2024 10:10:10', 'false',
            ],
            [
                str(self.account_1.id), str(self.vendor.id), self.agent.user_extension,
                '25-03-2024 10:10:10', 'true',
            ]
        ]
        upload_async_state = UploadAsyncStateFactory(
            task_status=UploadAsyncStateStatus.WAITING,
            task_type=UploadAsyncStateType.VENDOR_RPC_DATA,
        )
        upload_async_state.save()
        upload_async_state.update_safely(url='vendor_rpc/{}/sales_ops_vendor_rpc.csv'.format(
            upload_async_state.id
        ))
        output = io.StringIO()
        writer = csv.writer(output, delimiter=',')
        writer.writerows(valid_data)
        upload_file = File(output, name='vendor_rpc.csv')
        reader = csv.DictReader(upload_file, delimiter=',')
        mock_read_csv_file.return_value = reader

        update_rpc_from_vendor_task(upload_async_state.id)
        upload_async_state = UploadAsyncState.objects.filter(id=upload_async_state.id).first()
        latest_non_rpc_agent_assignment = (
            SalesOpsAgentAssignment.objects.filter(
                agent_id=self.agent.id, lineup_id=self.sales_ops_lineup_1.id, is_rpc=False
            )
            .order_by('completed_date', 'id')
            .last()
        )
        latest_rpc_agent_assignment = (
            SalesOpsAgentAssignment.objects.filter(
                agent_id=self.agent.id, lineup_id=self.sales_ops_lineup_1.id, is_rpc=True
            )
            .order_by('completed_date', 'id')
            .last()
        )
        self.sales_ops_lineup_1.refresh_from_db()

        lineup_latest_agent_assignment_id = self.sales_ops_lineup_1.latest_agent_assignment_id
        lineup_latest_rpc_agent_assignment_id = (
            self.sales_ops_lineup_1.latest_rpc_agent_assignment_id
        )

        # Check lineup
        self.assertEqual(lineup_latest_agent_assignment_id, latest_rpc_agent_assignment.id)
        self.assertEqual(lineup_latest_rpc_agent_assignment_id, latest_rpc_agent_assignment.id)

        # Check non RPC agent assignment
        self.assertEqual(
            latest_non_rpc_agent_assignment.completed_date, convert_string_to_datetime(
                '25-03-2024 10:10:10', "%d-%m-%Y %H:%M:%S"
            )
        )
        self.assertEqual(latest_non_rpc_agent_assignment.non_rpc_attempt, 3)

        # Check RPC agent assignment
        self.assertEqual(
            latest_rpc_agent_assignment.completed_date, convert_string_to_datetime(
                '25-03-2024 10:10:10', "%d-%m-%Y %H:%M:%S"
            )
        )
        self.assertEqual(latest_rpc_agent_assignment.non_rpc_attempt, 0)
        self.assertEqual(upload_async_state.task_status, UploadAsyncStateStatus.COMPLETED)

    @patch('django.utils.timezone.now')
    @patch(f'{PACKAGE_NAME}.read_csv_file')
    def test_update_rpc_from_vendor_correct_day_2(self, mock_read_csv_file, mock_now):
        mock_now.return_value = datetime(2024, 3, 26, 12, 0, 0)
        agent_assignment = SalesOpsAgentAssignmentFactory(
            lineup_id=self.sales_ops_lineup_1.id,
            agent_id=self.agent.id,
            completed_date=datetime(2024, 3, 24, 12, 23, 34),
            non_rpc_attempt=2,
            is_rpc=False
        )
        self.sales_ops_lineup_1.update_safely(latest_agent_assignment_id=agent_assignment.id)

        valid_data = [
            HEADER,
            [
                str(self.account_1.id), str(self.vendor.id), self.agent.user_extension,
                '25-03-2024 10:10:10', 'true',
            ],
            [
                str(self.account_1.id), str(self.vendor.id), self.agent.user_extension,
                '25-03-2024 10:10:10', 'false',
            ]
        ]
        upload_async_state = UploadAsyncStateFactory(
            task_status=UploadAsyncStateStatus.WAITING,
            task_type=UploadAsyncStateType.VENDOR_RPC_DATA,
        )
        upload_async_state.save()
        upload_async_state.update_safely(url='vendor_rpc/{}/sales_ops_vendor_rpc.csv'.format(
            upload_async_state.id
        ))
        output = io.StringIO()
        writer = csv.writer(output, delimiter=',')
        writer.writerows(valid_data)
        upload_file = File(output, name='vendor_rpc.csv')
        reader = csv.DictReader(upload_file, delimiter=',')
        mock_read_csv_file.return_value = reader

        update_rpc_from_vendor_task(upload_async_state.id)
        upload_async_state = UploadAsyncState.objects.filter(id=upload_async_state.id).first()
        latest_non_rpc_agent_assignment = (
            SalesOpsAgentAssignment.objects.filter(
                agent_id=self.agent.id, lineup_id=self.sales_ops_lineup_1.id, is_rpc=False
            )
            .order_by('completed_date', 'id')
            .last()
        )
        latest_rpc_agent_assignment = (
            SalesOpsAgentAssignment.objects.filter(
                agent_id=self.agent.id, lineup_id=self.sales_ops_lineup_1.id, is_rpc=True
            )
            .order_by('completed_date', 'id')
            .last()
        )
        self.sales_ops_lineup_1.refresh_from_db()

        lineup_latest_agent_assignment_id = self.sales_ops_lineup_1.latest_agent_assignment_id
        lineup_latest_rpc_agent_assignment_id = (
            self.sales_ops_lineup_1.latest_rpc_agent_assignment_id
        )

        # Check lineup
        self.assertEqual(lineup_latest_agent_assignment_id, latest_rpc_agent_assignment.id)
        self.assertEqual(lineup_latest_rpc_agent_assignment_id, latest_rpc_agent_assignment.id)

        # Check non RPC agent assignment
        self.assertEqual(
            latest_non_rpc_agent_assignment.completed_date, convert_string_to_datetime(
                '24-03-2024 12:23:34', "%d-%m-%Y %H:%M:%S"
            )
        )
        self.assertEqual(latest_non_rpc_agent_assignment.non_rpc_attempt, 2)

        # Check RPC agent assignment
        self.assertEqual(
            latest_rpc_agent_assignment.completed_date, convert_string_to_datetime(
                '25-03-2024 10:10:10', "%d-%m-%Y %H:%M:%S"
            )
        )
        self.assertEqual(latest_rpc_agent_assignment.non_rpc_attempt, 0)
        self.assertEqual(upload_async_state.task_status, UploadAsyncStateStatus.PARTIAL_COMPLETED)

    @patch('django.utils.timezone.now')
    @patch(f'{PACKAGE_NAME}.read_csv_file')
    def test_update_rpc_from_vendor_incorrect_day_1(self, mock_read_csv_file, mock_now):
        mock_now.return_value = datetime(2024, 3, 26, 12, 0, 0)
        agent_assignment = SalesOpsAgentAssignmentFactory(
            lineup_id=self.sales_ops_lineup_1.id,
            agent_id=self.agent.id,
            completed_date=datetime(2024, 3, 25, 12, 23, 34),
            non_rpc_attempt=2,
            is_rpc=False
        )
        self.sales_ops_lineup_1.update_safely(latest_agent_assignment_id=agent_assignment.id)

        valid_data = [
            HEADER,
            [
                str(self.account_1.id), str(self.vendor.id), self.agent.user_extension,
                '24-03-2024 10:10:10', 'false',
            ],
            [
                str(self.account_1.id), str(self.vendor.id), self.agent.user_extension,
                '24-03-2024 10:10:10', 'true',
            ]
        ]
        upload_async_state = UploadAsyncStateFactory(
            task_status=UploadAsyncStateStatus.WAITING,
            task_type=UploadAsyncStateType.VENDOR_RPC_DATA,
        )
        upload_async_state.save()
        upload_async_state.update_safely(url='vendor_rpc/{}/sales_ops_vendor_rpc.csv'.format(
            upload_async_state.id
        ))
        output = io.StringIO()
        writer = csv.writer(output, delimiter=',')
        writer.writerows(valid_data)
        upload_file = File(output, name='vendor_rpc.csv')
        reader = csv.DictReader(upload_file, delimiter=',')
        mock_read_csv_file.return_value = reader

        update_rpc_from_vendor_task(upload_async_state.id)
        upload_async_state = UploadAsyncState.objects.filter(id=upload_async_state.id).first()
        latest_non_rpc_agent_assignment = (
            SalesOpsAgentAssignment.objects.filter(
                agent_id=self.agent.id, lineup_id=self.sales_ops_lineup_1.id, is_rpc=False
            )
            .order_by('completed_date', 'id')
            .last()
        )
        latest_rpc_agent_assignment = (
            SalesOpsAgentAssignment.objects.filter(
                agent_id=self.agent.id, lineup_id=self.sales_ops_lineup_1.id, is_rpc=True
            )
            .order_by('completed_date', 'id')
            .last()
        )
        self.sales_ops_lineup_1.refresh_from_db()

        lineup_latest_agent_assignment_id = self.sales_ops_lineup_1.latest_agent_assignment_id
        lineup_latest_rpc_agent_assignment_id = (
            self.sales_ops_lineup_1.latest_rpc_agent_assignment_id
        )

        # Check lineup
        self.assertEqual(lineup_latest_agent_assignment_id, latest_non_rpc_agent_assignment.id)
        self.assertEqual(lineup_latest_rpc_agent_assignment_id, latest_rpc_agent_assignment.id)

        # Check non RPC agent assignment
        self.assertEqual(
            latest_non_rpc_agent_assignment.completed_date, convert_string_to_datetime(
                '25-03-2024 12:23:34', "%d-%m-%Y %H:%M:%S"
            )
        )
        self.assertEqual(latest_non_rpc_agent_assignment.non_rpc_attempt, 3)

        # Check RPC agent assignment
        self.assertEqual(
            latest_rpc_agent_assignment.completed_date, convert_string_to_datetime(
                '24-03-2024 10:10:10', "%d-%m-%Y %H:%M:%S"
            )
        )
        self.assertEqual(latest_rpc_agent_assignment.non_rpc_attempt, 0)
        self.assertEqual(upload_async_state.task_status, UploadAsyncStateStatus.COMPLETED)

    @patch('django.utils.timezone.now')
    @patch(f'{PACKAGE_NAME}.read_csv_file')
    def test_update_rpc_from_vendor_incorrect_day_2(self, mock_read_csv_file, mock_now):
        mock_now.return_value = datetime(2024, 3, 26, 12, 0, 0)
        agent_assignment = SalesOpsAgentAssignmentFactory(
            lineup_id=self.sales_ops_lineup_1.id,
            agent_id=self.agent.id,
            completed_date=datetime(2024, 3, 25, 12, 23, 34),
            non_rpc_attempt=2,
            is_rpc=False
        )
        self.sales_ops_lineup_1.update_safely(latest_agent_assignment_id=agent_assignment.id)

        valid_data = [
            HEADER,
            [
                str(self.account_1.id), str(self.vendor.id), self.agent.user_extension,
                '24-03-2024 10:10:10', 'true',
            ],
            [
                str(self.account_1.id), str(self.vendor.id), self.agent.user_extension,
                '24-03-2024 10:10:10', 'false',
            ]
        ]
        upload_async_state = UploadAsyncStateFactory(
            task_status=UploadAsyncStateStatus.WAITING,
            task_type=UploadAsyncStateType.VENDOR_RPC_DATA,
        )
        upload_async_state.save()
        upload_async_state.update_safely(url='vendor_rpc/{}/sales_ops_vendor_rpc.csv'.format(
            upload_async_state.id
        ))
        output = io.StringIO()
        writer = csv.writer(output, delimiter=',')
        writer.writerows(valid_data)
        upload_file = File(output, name='vendor_rpc.csv')
        reader = csv.DictReader(upload_file, delimiter=',')
        mock_read_csv_file.return_value = reader

        update_rpc_from_vendor_task(upload_async_state.id)
        upload_async_state = UploadAsyncState.objects.filter(id=upload_async_state.id).first()
        latest_non_rpc_agent_assignment = (
            SalesOpsAgentAssignment.objects.filter(
                agent_id=self.agent.id, lineup_id=self.sales_ops_lineup_1.id, is_rpc=False
            )
            .order_by('completed_date', 'id')
            .last()
        )
        latest_rpc_agent_assignment = (
            SalesOpsAgentAssignment.objects.filter(
                agent_id=self.agent.id, lineup_id=self.sales_ops_lineup_1.id, is_rpc=True
            )
            .order_by('completed_date', 'id')
            .last()
        )
        self.sales_ops_lineup_1.refresh_from_db()

        lineup_latest_agent_assignment_id = self.sales_ops_lineup_1.latest_agent_assignment_id
        lineup_latest_rpc_agent_assignment_id = (
            self.sales_ops_lineup_1.latest_rpc_agent_assignment_id
        )

        # Check lineup
        self.assertEqual(lineup_latest_agent_assignment_id, latest_non_rpc_agent_assignment.id)
        self.assertEqual(lineup_latest_rpc_agent_assignment_id, latest_rpc_agent_assignment.id)

        # Check non RPC agent assignment
        self.assertEqual(
            latest_non_rpc_agent_assignment.completed_date, convert_string_to_datetime(
                '25-03-2024 12:23:34', "%d-%m-%Y %H:%M:%S"
            )
        )
        self.assertEqual(latest_non_rpc_agent_assignment.non_rpc_attempt, 2)

        # Check RPC agent assignment
        self.assertEqual(
            latest_rpc_agent_assignment.completed_date, convert_string_to_datetime(
                '24-03-2024 10:10:10', "%d-%m-%Y %H:%M:%S"
            )
        )
        self.assertEqual(latest_rpc_agent_assignment.non_rpc_attempt, 0)
        self.assertEqual(
            upload_async_state.task_status, UploadAsyncStateStatus.PARTIAL_COMPLETED
        )

    @patch('django.utils.timezone.now')
    @patch(f'{PACKAGE_NAME}.send_event_moengage_for_rpc_sales_ops_pds.delay')
    @patch(f'{PACKAGE_NAME}.read_csv_file')
    def test_update_rpc_pds_moengage_calls_all_rpc(
        self, mock_read_csv_file, mock_send_to_moengage, mock_now
    ):
        mock_now.return_value = datetime(2024, 3, 26, 12, 0, 0)
        FeatureSettingFactory(
            feature_name=SalesOpsPDSConst.PromoCode.FS_NAME,
            is_active=True,
            category=SalesOpsPDSConst.PromoCode.CATEGORY,
            parameters={'promo_code_id': self.promo_code.id}
        )
        valid_data = [
            HEADER,
            [
                str(self.account_1.id), str(self.vendor.id), self.agent.user_extension,
                '24-03-2024 10:23:50', 'true',
            ],
            [
                str(self.account_2.id), str(self.vendor.id), self.agent.user_extension,
                '24-03-2024 10:40:50', 'true',
            ]
        ]
        upload_async_state = UploadAsyncStateFactory(
            task_status=UploadAsyncStateStatus.WAITING,
            task_type=UploadAsyncStateType.VENDOR_RPC_DATA,
        )
        upload_async_state.save()
        upload_async_state.update_safely(url='vendor_rpc/{}/sales_ops_vendor_rpc.csv'.format(
            upload_async_state.id
        ))
        output = io.StringIO()
        writer = csv.writer(output, delimiter=',')
        writer.writerows(valid_data)
        upload_file = File(output, name='vendor_rpc.csv')
        reader = csv.DictReader(upload_file, delimiter=',')
        mock_read_csv_file.return_value = reader

        update_rpc_from_vendor_task(upload_async_state.id)

        sales_ops_agent_assignment_1 = SalesOpsAgentAssignment.objects.get(
            agent_id=self.agent.id, lineup_id=self.sales_ops_lineup_1.id
        )
        sales_ops_agent_assignment_2 = SalesOpsAgentAssignment.objects.get(
            agent_id=self.agent.id, lineup_id=self.sales_ops_lineup_2.id
        )

        mock_send_to_moengage.assert_has_calls([
            call(
                agent_assignment_id=sales_ops_agent_assignment_1.id,
                promo_code_id=self.promo_code.id,
            ),
            call(
                agent_assignment_id=sales_ops_agent_assignment_2.id,
                promo_code_id=self.promo_code.id,
            ),
        ])

    @patch('django.utils.timezone.now')
    @patch(f'{PACKAGE_NAME}.send_event_moengage_for_rpc_sales_ops_pds.delay')
    @patch(f'{PACKAGE_NAME}.read_csv_file')
    def test_update_rpc_pds_moengage_calls_partial_rpc(
        self, mock_read_csv_file, mock_send_to_moengage, mock_now
    ):
        mock_now.return_value = datetime(2024, 3, 26, 12, 0, 0)
        FeatureSettingFactory(
            feature_name=SalesOpsPDSConst.PromoCode.FS_NAME,
            is_active=True,
            category=SalesOpsPDSConst.PromoCode.CATEGORY,
            parameters={'promo_code_id': self.promo_code.id}
        )
        valid_data = [
            HEADER,
            [
                str(self.account_1.id), str(self.vendor.id), self.agent.user_extension,
                '24-03-2024 10:23:50', 'true',
            ],
            [
                str(self.account_2.id), str(self.vendor.id), self.agent.user_extension,
                '24-03-2024 10:40:50', 'false',
            ]
        ]
        upload_async_state = UploadAsyncStateFactory(
            task_status=UploadAsyncStateStatus.WAITING,
            task_type=UploadAsyncStateType.VENDOR_RPC_DATA,
        )
        upload_async_state.save()
        upload_async_state.update_safely(url='vendor_rpc/{}/sales_ops_vendor_rpc.csv'.format(
            upload_async_state.id
        ))
        output = io.StringIO()
        writer = csv.writer(output, delimiter=',')
        writer.writerows(valid_data)
        upload_file = File(output, name='vendor_rpc.csv')
        reader = csv.DictReader(upload_file, delimiter=',')
        mock_read_csv_file.return_value = reader

        update_rpc_from_vendor_task(upload_async_state.id)

        sales_ops_agent_assignment_1 = SalesOpsAgentAssignment.objects.get(
            agent_id=self.agent.id, lineup_id=self.sales_ops_lineup_1.id
        )

        mock_send_to_moengage.assert_has_calls([
            call(
                agent_assignment_id=sales_ops_agent_assignment_1.id,
                promo_code_id=self.promo_code.id,
            ),
        ])

    @patch('django.utils.timezone.now')
    @patch(f'{PACKAGE_NAME}.send_event_moengage_for_rpc_sales_ops_pds.delay')
    @patch(f'{PACKAGE_NAME}.read_csv_file')
    def test_update_rpc_pds_moengage_calls_all_non_rpc(
        self, mock_read_csv_file, mock_send_to_moengage, mock_now
    ):
        mock_now.return_value = datetime(2024, 3, 26, 12, 0, 0)
        FeatureSettingFactory(
            feature_name=SalesOpsPDSConst.PromoCode.FS_NAME,
            is_active=True,
            category=SalesOpsPDSConst.PromoCode.CATEGORY,
            parameters={'promo_code_id': self.promo_code.id}
        )
        valid_data = [
            HEADER,
            [
                str(self.account_1.id), str(self.vendor.id), self.agent.user_extension,
                '24-03-2024 10:23:50', 'false',
            ],
            [
                str(self.account_2.id), str(self.vendor.id), self.agent.user_extension,
                '24-03-2024 10:40:50', 'false',
            ]
        ]
        upload_async_state = UploadAsyncStateFactory(
            task_status=UploadAsyncStateStatus.WAITING,
            task_type=UploadAsyncStateType.VENDOR_RPC_DATA,
        )
        upload_async_state.save()
        upload_async_state.update_safely(url='vendor_rpc/{}/sales_ops_vendor_rpc.csv'.format(
            upload_async_state.id
        ))
        output = io.StringIO()
        writer = csv.writer(output, delimiter=',')
        writer.writerows(valid_data)
        upload_file = File(output, name='vendor_rpc.csv')
        reader = csv.DictReader(upload_file, delimiter=',')
        mock_read_csv_file.return_value = reader

        update_rpc_from_vendor_task(upload_async_state.id)
        mock_send_to_moengage.assert_not_called()
