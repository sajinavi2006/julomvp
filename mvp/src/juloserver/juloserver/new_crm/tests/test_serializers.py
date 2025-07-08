from __future__ import absolute_import

from django.contrib.auth.models import Group
from django.test import TestCase
from django.utils import timezone
from mock import patch
from datetime import (
    date,
    datetime,
)

from mock.mock import MagicMock

from juloserver.application_flow.factories import (
    ApplicationPathTagStatusFactory,
    ApplicationRiskyCheckFactory,
)
from juloserver.julo.constants import WorkflowConst
from juloserver.julo.models import (
    ApplicationCheckListComment,
    LoanPurpose,
    ProductLine,
)
from juloserver.julo.tests.factories import (
    ApplicationExperimentFactory,
    ApplicationFactory,
    AuthUserFactory,
    CreditScoreFactory,
    CustomerFactory,
    DeviceFactory,
    ExperimentFactory,
    FacebookDataFactory,
    ProductLineFactory,
    WorkflowFactory,
)
from juloserver.new_crm.serializers import (
    AppDetailSerializer,
    BasicAppDetailSerializer,
)
from juloserver.new_crm.tests.factories import (
    ApplicationCheckListCommentFactory,
    ApplicationPathTagFactory,
)
from juloserver.portal.object.dashboard.constants import JuloUserRoles


class TestBasicAppDetailSerializer(TestCase):
    def setUp(self):
        self.product_line = ProductLineFactory(product_line_code=1, product_line_type='J1')
        self.workflow = WorkflowFactory(name=WorkflowConst.JULO_ONE)
        self.application = ApplicationFactory(
            product_line=self.product_line,
            workflow=self.workflow
        )

    def test_basic_app_detail_serializer_expected_fields(self):
        serializer = BasicAppDetailSerializer(instance=self.application)
        data = serializer.data

        self.assertCountEqual(set(data.keys()), set(BasicAppDetailSerializer.Meta.fields))

    def test_basic_app_detail_serializer_is_highscore_bypass(self):
        application_path_tag = ApplicationPathTagFactory(
            application_id=self.application.id,
            application_path_tag_status=ApplicationPathTagStatusFactory(
                application_tag='is_hsfbp',
                status=1
            )
        )
        ApplicationExperimentFactory(
            application=self.application,
            experiment=ExperimentFactory(code='ExperimentUwOverhaul')
        )
        serializer = BasicAppDetailSerializer(instance=self.application)
        data = serializer.data
        self.assertEqual(data['is_highscore_full_bypass'], True)

        application_path_tag.delete()
        serializer = BasicAppDetailSerializer(instance=self.application)
        data = serializer.data
        self.assertEqual(data['is_highscore_full_bypass'], False)

    def test_basic_app_detail_serializer_is_sonic_bypass(self):
        application_path_tag = ApplicationPathTagFactory(
            application_id=self.application.id,
            application_path_tag_status=ApplicationPathTagStatusFactory(
                application_tag='is_sonic',
                status=1
            )
        )
        serializer = BasicAppDetailSerializer(instance=self.application)
        data = serializer.data
        self.assertEqual(data['is_sonic_bypass'], True)

        application_path_tag.delete()
        serializer = BasicAppDetailSerializer(instance=self.application)
        data = serializer.data
        self.assertEqual(data['is_sonic_bypass'], False)

    def test_basic_app_detail_serializer_has_fraud_list(self):
        ApplicationRiskyCheckFactory(
            application=self.application,
            is_rooted_device=True,
            is_address_suspicious=True
        )
        expected_fraud_list = ['ROOTED DEVICE', 'ADDRESS SUSPICIOUS']
        serializer = BasicAppDetailSerializer(instance=self.application)
        data = serializer.data

        self.assertEqual(data['fraud_list'], expected_fraud_list)


class TestAppDetailSerializer(TestCase):
    def setUp(self):
        self.serializer_fields = ['loan_purpose', 'credit_score', 'credit_score_message', 'imei',
                                  'dob', 'product_line', 'marital_status', 'payday', 'job_start',
                                  'address', 'gender', 'occupied_since', 'dialect',
                                  'close_kin_relationship', 'kin_gender', 'kin_relationship',
                                  'facebook_fullname', 'facebook_email', 'facebook_gender',
                                  'facebook_birth_date', 'facebook_id', 'facebook_friend_count',
                                  'has_whatsapp_1', 'has_whatsapp_2', 'vehicle_ownership_1',
                                  'loan_amount_request', 'loan_duration_request',
                                  'loan_purpose_desc', 'marketing_source', 'referral_code',
                                  'is_own_phone', 'fullname', 'birth_place', 'ktp', 'home_status',
                                  'mobile_phone_1', 'mobile_phone_2', 'email', 'twitter_username',
                                  'instagram_username', 'dependent', 'spouse_name', 'spouse_dob',
                                  'spouse_mobile_phone', 'spouse_has_whatsapp', 'kin_name',
                                  'kin_mobile_phone', 'close_kin_name', 'close_kin_mobile_phone',
                                  'job_type', 'job_industry', 'job_description', 'company_name',
                                  'company_phone_number', 'work_kodepos', 'monthly_income',
                                  'income_1', 'income_2', 'income_3', 'last_education', 'college',
                                  'major', 'graduation_year', 'gpa', 'has_other_income',
                                  'other_income_amount', 'other_income_source',
                                  'monthly_housing_cost', 'monthly_expenses', 'total_current_debt',
                                  'vehicle_type_1', 'bank_name', 'bank_branch',
                                  'bank_account_number', 'name_in_bank', 'app_version', 'hrd_name',
                                  'company_address', 'number_of_employees', 'position_employees',
                                  'employment_status', 'billing_office', 'mutation', 'customer',
                                  'dob_in_nik', 'area_in_nik', 'fraud_report', 'karakter', 'selfie',
                                  'signature', 'voice_recording', 'facebook_open_date', 'kin_dob',
                                  'verified_income']

        self.customer = CustomerFactory()
        self.product_line = ProductLineFactory(product_line_code=1, product_line_type='J1')
        self.application = ApplicationFactory(
            customer=self.customer,
            loan_purpose='Bayar Utang',
            job_start=date(2021, 3, 28),
            occupied_since=date(2022, 3, 28),
            dob=date(1997, 1, 1),
            product_line=self.product_line,
            payday=10
        )
        self.device = DeviceFactory(customer=self.customer)
        self.credit_score = CreditScoreFactory(application_id=self.application.id)
        self.facebook_data = FacebookDataFactory(application=self.application)

        self.user = AuthUserFactory()
        self.group = Group(name=JuloUserRoles.BO_SD_VERIFIER)
        self.group.save()
        self.user.groups.add(self.group)
        with patch.object(timezone, 'now',
                          return_value=datetime(2022, 5, 13, 15, 0, 0)) as mock_timezone:
            mock_context = MagicMock()
            mock_context.user.return_value = self.user
            self.serializer = AppDetailSerializer(instance=self.application, context=mock_context)

    def test_app_detail_serializer_output_filter_groups_expected_group_exist(self):
        filter_groups = AppDetailSerializer.output_filter_groups('loan_purpose_desc')
        expected_filter_groups = ['sd', 'dv']

        self.assertEqual(filter_groups, expected_filter_groups)

    def test_app_detail_serializer_output_filter_groups_expected_group_none(self):
        filter_groups = AppDetailSerializer.output_filter_groups('random_filename')
        expected_filter_groups = []

        self.assertEqual(filter_groups, expected_filter_groups)

    def test_app_detail_serializer_fetch_application_checklist(self):
        application_comment_data = ApplicationCheckListCommentFactory(
            application=self.application,
            field_name='loan_purpose_desc',
            group='sd'
        )
        application_comment_data.cdate = timezone.localtime(timezone.now())
        application_comment_data.save()

        application_comments = (
            ApplicationCheckListComment.objects.filter(
                application=self.application,
            )
            .select_related('agent')
            .values('cdate', 'id', 'agent_id', 'agent__username', 'comment', 'group', 'field_name')
            .order_by('-cdate')
        )

        checklist_groups = AppDetailSerializer.fetch_application_check_list(self.application.id,
            'loan_purpose_desc', ['bo_sd_verifier'], application_comments)
        expected_checklist_groups = {
            'sd': {
                'value': None,
                'comment': [{
                    'id': application_comment_data.id,
                    'comment': application_comment_data.comment,
                    'cdate': str(application_comment_data.cdate),
                    'agent': application_comment_data.agent.username
                }],
                'is_disabled': False
            }
        }

        self.assertEqual(checklist_groups, expected_checklist_groups)

        checklist_groups = AppDetailSerializer.fetch_application_check_list(self.application.id,
            'loan_purpose_desc', ['other_role'], application_comments)
        expected_checklist_groups = {
            'sd': {
                'value': None,
                'comment': [{
                    'id': application_comment_data.id,
                    'comment': application_comment_data.comment,
                    'cdate': str(application_comment_data.cdate),
                    'agent': application_comment_data.agent.username
                }],
                'is_disabled': True
            }
        }

        self.assertEqual(checklist_groups, expected_checklist_groups)

    def test_app_detail_serializer_expected_fields(self):
        data = self.serializer.data
        self.assertCountEqual(set(data.keys()), set(self.serializer_fields))

    def test_app_detail_serializer_expected_modified_fields(self):
        data = self.serializer.data

        expected_loan_purpose = {
            'select': 'Bayar Utang',
            'options': []
        }
        loan_purposes = LoanPurpose.objects.all()
        for loan_purpose in loan_purposes:
            expected_loan_purpose['options'].append({
                'value': loan_purpose.purpose,
                'text': loan_purpose.purpose
            })

        expected_dob = {
            'value': self.application.dob,
            '_meta': {
                'description': f'Usia: 25 Tahun'
            }
        }

        expected_product_lines = {
            'select': self.application.product_line.product_line_code,
            'options': []
        }
        product_lines = ProductLine.objects.all()
        for product_line in product_lines:
            expected_product_lines['options'].append({
                'value': product_line.product_line_code,
                'text': product_line.product_line_type
            })

        expected_payday = {
            'value': self.application.payday,
            '_meta': {
                'min': 1,
                'max': 28
            }
        }

        expected_job_start = {
            'value': self.application.job_start,
            '_meta': {
                'description': f'Lama: 1 Tahun'
            }
        }

        expected_occupied_since = {
            'value': self.application.occupied_since,
            '_meta': {
                'description': f'Lama: 0 Tahun'
            }
        }

        self.assertCountEqual(data['loan_purpose']['value'], expected_loan_purpose)
        self.assertCountEqual(data['dob']['value'], expected_dob)
        self.assertCountEqual(data['payday']['value'], expected_payday)
        self.assertCountEqual(data['job_start']['value'], expected_job_start)
        self.assertCountEqual(data['occupied_since']['value'], expected_occupied_since)
