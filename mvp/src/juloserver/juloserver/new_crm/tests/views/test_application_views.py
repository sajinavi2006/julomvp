from datetime import datetime, timedelta
import io
from unittest.mock import patch
from django.utils import timezone

from PIL import Image
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient
from rest_framework.test import APITestCase
from django.contrib.auth.models import Group

from juloserver.apiv2.tests.factories import (
    EtlJobFactory,
    PdFraudDetectionFactory,
    PdIncomeVerificationFactory
)
from juloserver.collection_vendor.tests.factories import SkiptraceHistoryFactory
from juloserver.cfs.tests.factories import AgentFactory
from juloserver.new_crm.tests.factories import ApplicationCheckListCommentFactory
from juloserver.new_crm.views.application_views import AppDetail
from juloserver.julo.application_checklist import application_checklist_update
from juloserver.portal.object.dashboard.constants import JuloUserRoles
from juloserver.account.constants import AccountConstant
from juloserver.account.tests.factories import (
    AccountFactory,
)
from juloserver.julo.constants import (
    SkiptraceResultChoiceConst,
    WorkflowConst,
)
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.statuses import ApplicationStatusCodes
from juloserver.julo.tests.factories import (
    ApplicationFactory,
    ApplicationFieldChangeFactory,
    ApplicationJ1Factory,
    AuthUserFactory,
    CustomerFactory,
    GroupFactory,
    ProductLineFactory,
    SkiptraceFactory,
    SkiptraceResultChoiceFactory,
    StatusLookupFactory,
    WorkflowFactory,
    ApplicationHistoryFactory,
    ExperimentSettingFactory,
    ExperimentFactory,
    ApplicationExperimentFactory,
    ImageFactory,
    SkiptraceFactory,
    SkiptraceResultChoiceFactory,
)
from juloserver.julo.models import (
    Image as ImageModel,
    ApplicationHistory,
    ApplicationNote,
)
from juloserver.account.models import AccountNote, AccountStatusHistory
from juloserver.new_crm.serializers import AppDetailSerializer
from juloserver.julovers.tests.factories import (
    WorkflowStatusPathFactory,
)
from juloserver.portal.object.product_profile.tests.test_product_profile_services import ProductProfileFactory


class TestApplication(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.group = Group(name=JuloUserRoles.BO_SD_VERIFIER)
        self.group.save()
        self.user = AuthUserFactory()
        self.user.groups.add(self.group)
        self.client.force_login(self.user)
        self.customer = CustomerFactory(user=self.user)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)
        self.active_status_code = StatusLookupFactory(status_code=AccountConstant.STATUS_CODE.active)
        self.terminated_status_code = StatusLookupFactory(status_code=AccountConstant.STATUS_CODE.terminated)
        self.account = AccountFactory(
            customer=self.customer,
            status=self.active_status_code
        )
        self.workflow = WorkflowFactory(name=WorkflowConst.JULO_ONE)
        self.product_line = ProductLineFactory(product_line_code=ProductLineCodes.J1)
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
        self.application.save()
        self.image = ImageFactory(image_type='ktp_self',
                                  image_source=self.application.id)
        self.skiptrace = SkiptraceFactory(
            customer=self.customer, application=self.application,
            contact_source="Test contact source", contact_name='Test contact name',
            phone_number='9999999999'
        )
        self.skiptrace_result_choice = SkiptraceResultChoiceFactory(name='RPC')
        today = timezone.localtime(timezone.now()).date()
        self.skiptrace_history = SkiptraceHistoryFactory(
            cdate=today, skiptrace=self.skiptrace, call_result=self.skiptrace_result_choice,
            agent=self.user, application=self.application
        )

    @staticmethod
    def create_image(size=(100, 100), image_format='PNG'):
        data = io.BytesIO()
        Image.new('RGB', size).save(data, image_format)
        data.seek(0)
        return data

    @patch("juloserver.new_crm.tasks.upload_image")
    def test_upload_images(self, mock_upload_image):
        image = self.create_image()
        image_file = SimpleUploadedFile('test.png', image.getvalue())
        post_data = {
            'attachments': [image_file],
            'image_type_1': 'ktp_self',
        }
        mock_upload_image.assert_not_called()
        response = self.client.post(
            '/new_crm/v1/app_multi_image_upload/{}'.format(self.application.id), post_data
        )
        self.assertEqual(response.status_code, 200)
        image_model = ImageModel.objects.filter(image_source=self.application.id).last()
        self.assertEqual(image_model.image_type, 'ktp_self_ops')

    def test_app_status_get_app_history(self):
        app_history = ApplicationHistoryFactory()
        app_history.application_id = self.application.id
        app_history.save()
        response = self.client.get(
            '/new_crm/v1/app_status/app_history/{}'.format(self.application.id),
        )
        self.assertEqual(response.status_code, 200)
        count_app_history = ApplicationHistory.objects.count()
        self.assertEqual(count_app_history, 1)

    def test_permission(self):
        self.user.groups.remove(self.group)
        response = self.client.get(f'/new_crm/v1/app_status/{self.application.id}')
        self.assertEqual(response.status_code, 403)

    @patch("juloserver.new_crm.views.application_views.filter_app_statuses_crm")
    def test_get_app_status_change(self, mock_filter):
        code = 123
        desc = "I'm testing over here! I'm testing!"
        change_reasons = ['reason1', 'reason2']
        status = [{
            'code': code,
            'desc': desc,
            'change_reasons': change_reasons,
        }]
        mock_filter.return_value = (status, None)
        response = self.client.get(f'/new_crm/v1/app_status/status_change/{self.application.id}')
        self.assertEqual(response.status_code, 200)
        json_response = response.json()
        expected_response = [
            {
            'status': code,
            'description': desc,
            'change_reasons': change_reasons,
            },
        ]
        self.assertEqual(json_response['data'], expected_response)

    def test_post_app_status_change(self):
        bogus_status_lookup = StatusLookupFactory(status_code='666666')
        bogus_status = bogus_status_lookup.status_code
        WorkflowStatusPathFactory(
            status_previous=self.application.status,
            status_next=bogus_status,
            type='happy',
            is_active=True,
            workflow=self.application.workflow,
        )
        self.application.application_status = bogus_status_lookup
        data = {
            'status': bogus_status,
            'change_reason': "sweet home alabama",
        }
        response = self.client.post(
            f'/new_crm/v1/app_status/status_change/{self.application.id}',
            data=data,
            format='json',
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.application.status, bogus_status)

    def test_post_app_status_change_bad_params(self):
        data = {
            'status': "bollocks_string", # not valid, should be int
            'change_reason': "no erasion",
        }
        response = self.client.post(
            f'/new_crm/v1/app_status/status_change/{self.application.id}',
            data=data,
            format='json',
        )
        self.assertEqual(response.status_code, 400)

    def test_post_app_note(self):
        data = {
            'note_text': 'Testing application notes'
        }
        response = self.client.post(
            f'/new_crm/v1/app_status/app_note/{self.application.id}',
            data=data,
            format='json',
        )
        app_note = ApplicationNote.objects.last()
        self.assertEqual(response.status_code, 200)
        self.assertNotEqual(app_note, None)

    def test_post_app_note_app_not_found(self):
        data = {
            'note_text': 'Testing application notes'
        }
        response = self.client.post(
            f'/new_crm/v1/app_status/app_note/{self.application.id + 100}',
            data=data,
            format='json',
        )
        self.assertEqual(response.status_code, 404)

    def test_post_app_note_bad_params(self):
        data = {}
        response = self.client.post(
            f'/new_crm/v1/app_status/app_note/{self.application.id}',
            data=data,
            format='json',
        )
        self.assertEqual(response.status_code, 400)

    def test_app_status_and_history(self):
        ApplicationHistoryFactory(application_id=self.application.id)
        ApplicationNote.objects.create(application_id=self.application.id, note_text='Testing')
        AccountStatusHistory.objects.create(
            account=self.account, status_old=self.terminated_status_code,
            status_new=self.active_status_code, change_reason='Testing')
        AccountNote.objects.create(account=self.account, note_text='Testing')
        response = self.client.get(
            f'/new_crm/v1/app_status/app_history/{self.application.id}')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data.get('data')), 4)

    def test_app_status_image_list(self):
        response = self.client.get(f'/new_crm/v1/app_status/image_list/{self.application.id}')
        self.assertEqual(response.status_code, 200)
        data = response.json()['data']

        self.assertEqual(
            data[0].get('img_type'),
            self.image.image_type,
        )

    def test_app_detail_update_history_view(self):
        ApplicationFieldChangeFactory(application=self.application, agent=self.user)
        response = self.client.get(
            f'/new_crm/v1/app_status/app_update_history/{self.application.id}')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data.get('data')), 1)

    def test_app_status_skiptrace_history(self):
        response = self.client.get(f'/new_crm/v1/app_status/skiptrace_history/{self.application.id}')
        self.assertEqual(response.status_code, 200)
        skip_trace_history_data = response.json()['data']
        self.assertEqual(
            skip_trace_history_data[0].get('agent_name'), self.skiptrace_history.agent_name
        )
        self.assertEqual(
            skip_trace_history_data[0].get('call_result_name'),
            self.skiptrace_result_choice.name
        )
        self.assertEqual(
            skip_trace_history_data[0].get('contact_source'),
            self.skiptrace.contact_source
        )


class TestAppScrapeDataView(APITestCase):
    def setUp(self):
        self.user = AuthUserFactory()
        self.user = AuthUserFactory()
        self.user.groups.add(GroupFactory(name=JuloUserRoles.BO_SD_VERIFIER))
        self.client.force_login(self.user)
        self.application = ApplicationJ1Factory()

    def test_get_no_data(self):
        response = self.client.get(f'/new_crm/v1/app_status/scrape_data/{self.application.id}')
        self.assertEqual(200, response.status_code)

        data = response.json()['data']
        self.assertEqual([], data)

    def test_get_no_application(self):
        application_id = self.application.id
        self.application.delete()
        response = self.client.get(f'/new_crm/v1/app_status/scrape_data/{application_id}')
        self.assertEqual(404, response.status_code)

        errors = response.json()['errors']
        self.assertEqual(['Application not found'], errors)


class TestAppFinanceView(APITestCase):
    def setUp(self):
        self.user = AuthUserFactory()
        self.user.groups.add(GroupFactory(name=JuloUserRoles.BO_SD_VERIFIER))
        self.client.force_login(self.user)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)
        self.application = ApplicationJ1Factory(
            product_line=ProductLineFactory(
                product_line_code=ProductLineCodes.J1,
                product_profile=ProductProfileFactory()
            ),
            monthly_housing_cost=1000000,
            monthly_income=1500000,
        )

    def test_get_finance_tab(self):
        from juloserver.new_crm.serializers import AppFinanceSerializer
        response = self.client.get(f'/new_crm/v1/app_status/finance/{self.application.id}')

        serialier = AppFinanceSerializer(self.application)
        print(serialier.data)
        self.assertEqual(response.status_code, 200)
        data = response.json()['data']

        self.assertEqual(
            set(data.keys()),
            {
                'id',
                'loan_amount_request',
                'loan_duration_request',
                'default_interest_rate',
                'basic_installment',
                'basic_installment_discount',
                'monthly_income',
                'monthly_housing_cost',
                'monthly_expenses',
                'total_current_debt',
                'basic_financial',
                'dti_multiplier',
                'dti_capacity',
                'is_dti_passed',
                'is_basic_financial_passed'
            }
        )


class TestBasicAppDetail(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.group = Group(name=JuloUserRoles.BO_SD_VERIFIER)
        self.group.save()
        self.user = AuthUserFactory()
        self.user.groups.add(self.group)
        self.client.force_login(self.user)
        self.customer = CustomerFactory(user=self.user)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)
        self.workflow = WorkflowFactory(name=WorkflowConst.JULO_ONE)
        self.product_line = ProductLineFactory(product_line_code=ProductLineCodes.J1)
        self.application = ApplicationFactory(
            customer=self.customer,
            workflow=self.workflow,
            product_line=self.product_line,
        )
        self.experimentsetting = ExperimentSettingFactory(
            code='ExperimentUwOverhaul',
            start_date=datetime.now(),
            end_date=datetime.now() + timedelta(days=50),
            is_active=False,
            is_permanent=False,
            criteria={'crm_tag': True, 'min_apk_version': '5.0.0'}
        )
        self.experiment = ExperimentFactory(
            code='ExperimentUwOverhaul',
            name='ExperimentUwOverhaul',
            description='Details can be found here: https://juloprojects.atlassian.net/browse/RUS1-264',
            status_old='0',
            status_new='0',
            date_start=datetime.now(),
            date_end=datetime.now() + timedelta(days=50),
            is_active=False,
            created_by='Djasen Tjendry'
        )
        ApplicationExperimentFactory(
            application=self.application,
            experiment=self.experiment
        )
        self.etl_job = EtlJobFactory(
            application_id=self.application.id,
            status='load_success')
        PdFraudDetectionFactory(
            etl_job_id=self.etl_job.id,
            customer_id=self.customer.id,
            application_id=self.application.id)
        PdIncomeVerificationFactory(
            etl_job_id=self.etl_job.id,
            customer_id=self.customer.id,
            application_id=self.application.id)

    def test_basic_app_detail_GET_permission_fail(self):
        self.user.groups.remove(self.group)
        response = self.client.get(f'/new_crm/v1/app_status/{self.application.id}')
        self.assertEqual(response.status_code, 403)

    def test_basic_app_detail_GET_success(self):
        response = self.client.get(f'/new_crm/v1/app_status/{self.application.id}')
        self.assertEqual(response.status_code, 200)
        data = response.json()['data']
        expected_result = {
            'status': self.application.status,
            'email': self.application.email,
            'phone': self.application.mobile_phone_1,
            'name': self.application.fullname,
            'account': self.application.account_id,
            'tags': ['alert', 'new flow'],
            'fraud_list': None,
            'is_highscore_full_bypass': False,
            'is_sonic_bypass': False,
            'app_tabs': {
                'dvc': True,
                'fin': True,
                'name_bank_validation': False,
                'sd': False,
                'security': False,
                'st': False
            }
        }
        self.assertEqual(data, expected_result)


class TestAppDetail(APITestCase):
    def setUp(self):
        self.api_fields = ['loan_purpose', 'credit_score', 'credit_score_message', 'imei',
                           'dob', 'product_line', 'marital_status', 'payday', 'job_start',
                           'address', 'gender', 'occupied_since', 'dialect',
                           'close_kin_relationship', 'kin_gender', 'kin_relationship',
                           'facebook_fullname', 'facebook_email', 'facebook_gender',
                           'facebook_birth_date', 'facebook_id', 'facebook_friend_count',
                           'has_whatsapp_1', 'has_whatsapp_2', 'vehicle_ownership_1',
                           'loan_amount_request', 'loan_duration_request', 'loan_purpose_desc',
                           'marketing_source', 'referral_code', 'is_own_phone', 'fullname',
                           'birth_place', 'ktp', 'home_status', 'mobile_phone_1', 'mobile_phone_2',
                           'email', 'twitter_username', 'instagram_username', 'dependent',
                           'spouse_name', 'spouse_dob', 'spouse_mobile_phone',
                           'spouse_has_whatsapp', 'kin_name', 'kin_mobile_phone', 'close_kin_name',
                           'close_kin_mobile_phone', 'job_type', 'job_industry', 'job_description',
                           'company_name', 'company_phone_number', 'work_kodepos', 'monthly_income',
                           'income_1', 'income_2', 'income_3', 'last_education', 'college',
                           'major', 'graduation_year', 'gpa', 'has_other_income',
                           'other_income_amount', 'other_income_source', 'monthly_housing_cost',
                           'monthly_expenses', 'total_current_debt', 'vehicle_type_1', 'bank_name',
                           'bank_branch', 'bank_account_number', 'name_in_bank', 'app_version',
                           'hrd_name', 'company_address', 'number_of_employees',
                           'position_employees', 'employment_status', 'billing_office', 'mutation',
                           'customer', 'dob_in_nik', 'area_in_nik', 'fraud_report', 'karakter',
                           'selfie', 'signature', 'voice_recording', 'facebook_open_date',
                           'kin_dob', 'verified_income']

        self.client = APIClient()
        self.user = AuthUserFactory()
        self.group = Group(name=JuloUserRoles.BO_SD_VERIFIER)
        self.group.save()
        self.user = AuthUserFactory()
        self.user.groups.add(self.group)
        self.client.force_login(self.user)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)
        self.customer = CustomerFactory(user=self.user)
        self.application = ApplicationFactory(customer=self.customer)

    def test_app_detail_GET_success(self):
        response = self.client.get(f'/new_crm/v1/app_status/detail/{self.application.id}')
        json_response = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertCountEqual(set(json_response['data'].keys()), set(self.api_fields))

    def test_app_detail_GET_application_not_found(self):
        response = self.client.get(f'/new_crm/v1/app_status/detail/{self.application.id + 99}')
        expected_response = {
            'success': False,
            'data': None,
            'errors': ['Application not found']
        }

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.data, expected_response)

    def test_app_detail_GET_value_has_meta_is_type_detailed(self):
        response = self.client.get(f'/new_crm/v1/app_status/detail/{self.application.id}')
        json_response = response.json()

        self.assertIn('_meta', json_response['data']['dob']['value'].keys())
        self.assertIn('_meta', json_response['data']['payday']['value'].keys())
        self.assertIn('_meta', json_response['data']['job_start']['value'].keys())
        self.assertIn('_meta', json_response['data']['occupied_since']['value'].keys())

    def test_app_detail_GET_checklist_sd_enabled_for_bo_sd_verifier(self):
        response = self.client.get(f'/new_crm/v1/app_status/detail/{self.application.id}')
        response_data = response.data['data']

        for key, application_checklist in application_checklist_update.items():
            if application_checklist['sd'] is True:
                self.assertEqual(response_data[key]['checklist_groups']['sd']['is_disabled'], False)

    def test_app_detail_POST_success_saving_valid_field(self):
        update_data = {
            'payday': 13
        }
        response = self.client.post(
            f'/new_crm/v1/app_status/detail/{self.application.id}',
            data=update_data,
            format='json'
        )

        self.application.refresh_from_db()
        self.assertEqual(self.application.payday, update_data['payday'])
        self.assertEqual(response.status_code, 200)

    def test_app_detail_POST_application_not_found(self):
        update_data = {
            'payday': 13
        }
        response = self.client.post(
            f'/new_crm/v1/app_status/detail/{self.application.id + 99}',
            data=update_data,
            format='json'
        )
        expected_response = {
            'success': False,
            'data': None,
            'errors': ['Application not found']
        }

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.data, expected_response)

    def test_app_detail_POST_validation_error(self):
        update_data = {
            'dialect': 'Dragonian'
        }
        response = self.client.post(
            f'/new_crm/v1/app_status/detail/{self.application.id}',
            data=update_data,
            format='json'
        )
        expected_response = {
            'success': False,
            'data': {'dialect': [
                '"Dragonian" is not a valid choice.'
            ]},
            'errors': ['Bad Parameter(s)']
        }

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data, expected_response)

    def test_app_detail_POST_readonly_field_update_error(self):
        update_data = {
            'gpa': 4
        }
        response = self.client.post(
            f'/new_crm/v1/app_status/detail/{self.application.id}',
            data=update_data,
            format='json'
        )
        expected_response = {
            'success': False,
            'data': {
                'gpa': ['this field can not be updated']
            },
            'errors': ['Bad Parameter(s)']
        }

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data, expected_response)

    def test_app_detail_POST_checklist_with_wrong_role(self):
        update_data = {
            'checklist': {
                'dob': {
                    'group': 'pve',
                    'value': True
                }
            }
        }

        response = self.client.post(
            f'/new_crm/v1/app_status/detail/{self.application.id}',
            data=update_data,
            format='json'
        )
        expected_response = {
            'success': False,
            'data': {
                'checklist': [
                    'This user is not allowed to add/update pve checklist.'
                ]
            },
            'errors': ['Bad Parameter(s)']
        }

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data, expected_response)

    def test_app_detail_POST_comments_with_wrong_role(self):
        update_data = {
            'comments': {
                'dob': {
                    'group': 'pve',
                    'value': "This is the first pve comment for dob field."
                }
            }
        }

        response = self.client.post(
            f'/new_crm/v1/app_status/detail/{self.application.id}',
            data=update_data,
            format='json'
        )
        expected_response = {
            'success': False,
            'data': {
                'comments': [
                    'This user is not allowed to add/update pve comments.'
                ]
            },
            'errors': ['Bad Parameter(s)']
        }

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data, expected_response)


class TestAppSkiptrace(APITestCase):
    def setUp(self):
        self.user = AuthUserFactory()
        self.group = Group(name=JuloUserRoles.BO_SD_VERIFIER)
        self.group.save()
        self.user = AuthUserFactory()
        self.user.groups.add(self.group)
        self.client.force_login(self.user)

    def test_get_app_skiptrace(self):
        application = ApplicationJ1Factory()
        skiptrace = SkiptraceFactory(phone_number='+628123456789', customer=application.customer)
        skiptrace_result = SkiptraceResultChoiceFactory(name=SkiptraceResultChoiceConst.RPC)

        response = self.client.get(
            '/new_crm/v1/app_status/skiptrace/{}'.format(application.id)
        )

        self.assertEqual(200, response.status_code)

        response_body = response.json()
        self.assertEqual(
            {'skiptrace', 'wa_template', 'skiptrace_result_option'},
            set(response_body['data'].keys())
        )
        self.assertEqual('+628123456789', response_body['data']['skiptrace'][0]['phone_number'])
        self.assertEqual('RPC', response_body['data']['skiptrace_result_option'][0]['name'])
