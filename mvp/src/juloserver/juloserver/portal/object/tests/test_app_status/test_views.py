from future import standard_library
import json
from urllib.parse import urlencode
from mock import patch
from datetime import timedelta, datetime
from django.test import TestCase
from django.test import Client
from django.core.urlresolvers import reverse
from django.contrib.auth.models import User, Group, Permission
from django.test import override_settings

import juloserver.julo.models
from juloserver.julo.tests.factories import (
    FeatureSettingFactory,
    LoanFactory,
    CustomerFactory,
    PaymentMethodFactory,
    ApplicationFactory,
    ProductLine,
    StatusLookupFactory,
    ProductLineFactory,
)
from juloserver.julo.models import (
    LoanPurpose,
    ProductLineLoanPurpose,
    WorkflowConst,
    ProductLineCodes,
    ApplicationStatusCodes,
)
from juloserver.disbursement.tests.factories import (
    NameBankValidationFactory, BankNameValidationLogFactory)
from juloserver.disbursement.models import NameBankValidationStatus, BankNameValidationLog
from juloserver.julo.tests.factories import WorkflowFactory,\
    ExperimentSettingFactory, ExperimentFactory, ExperimentTestGroupFactory, AuthUserFactory
from juloserver.julovers.tests.factories import WorkflowStatusPathFactory

from juloserver.application_flow.tests import ApplicationPathTagStatusFactory
from juloserver.new_crm.tests.factories import ApplicationPathTagFactory
from juloserver.application_form.constants import IDFyApplicationTagConst

standard_library.install_aliases()

testing_middleware = [
    'django_cookies_samesite.middleware.CookiesSameSite',
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.auth.middleware.SessionAuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',

    # 3rd party middleware classes
    'juloserver.julo.middleware.DeviceIpMiddleware',
    'cuser.middleware.CuserMiddleware',
    'juloserver.julocore.restapi.middleware.ApiLoggingMiddleware',
    'juloserver.standardized_api_response.api_middleware.StandardizedApiURLMiddleware',
    'juloserver.routing.middleware.CustomReplicationMiddleware']


@override_settings(MIDDLEWARE=testing_middleware)
@override_settings(SUSPEND_SIGNALS_FOR_MOENGAGE=True)
class TestAjaxBankValidation(TestCase):
    def setUp(self):
        self.username = 'test'
        self.password = 'nha123'
        self.user = User.objects.create_superuser(
            self.username, 'test@example.com', self.password)
        self.client = Client()
        self.client.login(username=self.username, password=self.password)

    def test_method_not_allow(self):
        response = self.client.put('/app_status/ajax_bank_validation/', {'app_id': 999999})
        self.assertEqual(response.status_code, 405)

    def test_retrieve_validation_info_app_not_found(self):
        response = self.client.get('/app_status/ajax_bank_validation/?app_id=999999')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['status'], 'failed')

    def test_retrieve_validation_info_success(self):
        app = ApplicationFactory()
        name_bank_validation = NameBankValidationFactory(
            bank_code='BCA', account_number='123456',
            name_in_bank='Nha Ho', method='Xfers',
            mobile_phone='09999333933'
        )
        loan = LoanFactory(application=app, name_bank_validation_id=name_bank_validation.id)
        response = self.client.get('/app_status/ajax_bank_validation/?app_id=%s' % app.id)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['status'], 'success')
        self.assertEqual(response.json()['data']['bank_name'], 'BCA')
        self.assertEqual(response.json()['data']['bank_account_number'], '1234567890')
        self.assertEqual(response.json()['data']['validation_status'], 'INITIATED')

    def test_validate_bank_failed(self):
        bank_name = 'BANK CENTRAL ASIA, Tbk (BCA)'
        bank_account_number = '12342222'
        name_in_bank = 'Nha Ho'
        app = ApplicationFactory(bank_name=bank_name)
        loan = LoanFactory(application=app)
        name_bank_validation = NameBankValidationFactory(
            bank_code='BCA',
            account_number=bank_account_number,
            name_in_bank=name_in_bank,
            method='test method',
            validation_id='22222222',
            validation_status='PENDING'
        )
        app.name_bank_validation_id = name_bank_validation.id
        app.save()
        # bank name not found
        data = {
            'app_id': app.id,
            'name_bank_validation_id': name_bank_validation.id,
            'bank_name': 'invalid bank name',
            'bank_account_number': bank_account_number,
            'name_in_bank': name_in_bank,
            'validation_method': 'Xfers'
        }
        response = self.client.post('/app_status/ajax_bank_validation/', data=data)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['status'], 'failed')

    def test_validate_bank_success(self):
        bank_name = 'BANK CENTRAL ASIA, Tbk (BCA)'
        bank_account_number = '12342222'
        name_in_bank = 'nha ho'
        julo_one_workflow = WorkflowFactory(
            name='JuloOneWorkflow',
            handler='JuloOneWorkflowHandler'
        )
        name_bank_validation = NameBankValidationFactory(
            bank_code='BCA',
            account_number=bank_account_number,
            name_in_bank=name_in_bank,
            method='test method',
            validation_id='22222222',
            validation_status='PENDING'
        )
        app = ApplicationFactory(bank_name=bank_name)
        app.workflow = julo_one_workflow
        app.application_status_id = 124
        app.name_bank_validation_id = name_bank_validation.id
        app.save()

        BankNameValidationLogFactory(
            validation_id='22222222',
            account_number=bank_account_number,
            method='test method',
            application=app
        )
        # success
        data = {
            'app_id': app.id,
            'name_bank_validation_id': name_bank_validation.id,
            'bank_name': bank_name,
            'bank_account_number': bank_account_number,
            'name_in_bank': name_in_bank,
            'validation_method': 'Xfers'
        }
        loan = LoanFactory(application=app)
        response = self.client.post('/app_status/ajax_bank_validation/', data=data)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['status'], 'success')


@override_settings(MIDDLEWARE=testing_middleware)
@override_settings(SUSPEND_SIGNALS_FOR_MOENGAGE=True)
class TestChangeAppStatus(TestCase):
    def setUp(self):
        self.username = 'test'
        self.password = 'nha123'
        self.group = Group.objects.create(name='fake_group')
        self.user = User.objects.create_superuser(
            self.username, 'test@example.com', self.password)
        self.user.groups.add(self.group)

        self.client = Client()
        self.client.login(username=self.username, password=self.password)
        self.experimentsetting = ExperimentSettingFactory(
            code='ExperimentUwOverhaul',
            start_date=datetime.now(),
            end_date=datetime.now() + timedelta(days=50),
            is_active=False,
            is_permanent=False
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
    def test_julo_one_app_change_status(self):
        product_line = ProductLine.objects.get(product_line_code=10)
        product_line.payment_frequency = 'Monthly'
        product_line.save()
        julo_one_workflow = WorkflowFactory(
            name='JuloOneWorkflow',
            handler='JuloOneWorkflowHandler'
        )
        app = ApplicationFactory(product_line=product_line)
        app.workflow=julo_one_workflow
        app.application_status_id = 124
        app.save()
        NameBankValidationFactory(
            bank_code='BCA',
            account_number='11111111',
            name_in_bank='TEST user',
            method='test method',
            validation_id='22222222'
        )
        BankNameValidationLogFactory(
            validation_id='22222222',
            account_number='11111111',
            method='test method',
            application=app
        )
        loan_pp = LoanPurpose.objects.create(version='1.0.1', purpose='no purpose')
        ProductLineLoanPurpose.objects.create(product_line=app.product_line,
                                              loan_purpose=loan_pp)

        response = self.client.post('/app_status/change_status/%s' % app.id,
                                    {
                                        'reason_str': 'test reason',
                                        'status_to': '130',
                                        'reason': 'Credit approved',
                                        'notes': 'test'
                                    })
        self.assertEqual(response.status_code, 200)

    def test_julo_one_app_change_status_to_x127(self):

        j1_workflow = WorkflowFactory(name=WorkflowConst.JULO_ONE)
        WorkflowStatusPathFactory(
            status_previous=ApplicationStatusCodes.SCRAPED_DATA_VERIFIED,
            status_next=ApplicationStatusCodes.TYPO_CALLS_UNSUCCESSFUL,
            workflow=j1_workflow,
        )

        app = ApplicationFactory(
            product_line=ProductLineFactory(
                product_line_code=ProductLineCodes.J1,
            )
        )
        app.workflow = j1_workflow
        app.application_status_id = ApplicationStatusCodes.TYPO_CALLS_UNSUCCESSFUL
        app.save()
        response = self.client.post('/app_status/change_status/%s' % app.id,
                                    {
                                        'reason_str': 'test reason',
                                        'status_to': str(ApplicationStatusCodes.TYPO_CALLS_UNSUCCESSFUL),
                                        'reason': 'test',
                                        'notes': 'test'
                                    })
        app.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(app.application_status_id, ApplicationStatusCodes.TYPO_CALLS_UNSUCCESSFUL)

    def test_julo_detail_application(self):

        j1_workflow = WorkflowFactory(name=WorkflowConst.JULO_ONE)
        app = ApplicationFactory(
            product_line=ProductLineFactory(
                product_line_code=ProductLineCodes.J1,
            )
        )

        # create simulation condition data
        app.workflow = j1_workflow
        app.application_status_id = ApplicationStatusCodes.FORM_CREATED
        app.gender = 'Pria'
        app.fullname = None
        app.save()

        response = self.client.get('/app_status/change_status/%s' % app.id)
        self.assertEqual(response.status_code, 200)


@override_settings(MIDDLEWARE=testing_middleware)
@override_settings(SUSPEND_SIGNALS_FOR_MOENGAGE=True)
class TestAjaxUpdateNameBankValidation(TestCase):
    def setUp(self):
        self.username = 'test'
        self.password = 'nha123'
        self.user = User.objects.create_superuser(
            self.username, 'test@example.com', self.password)
        self.client = Client()
        self.client.login(username=self.username, password=self.password)

    def test_method_not_allow(self):
        response = self.client.put('/app_status/ajax_update_name_bank_validation/',
                                   {'app_id': 999999})
        self.assertEqual(response.status_code, 405)

    def test_julo_one_update(self):
        julo_one_workflow = WorkflowFactory(
            name='JuloOneWorkflow',
            handler='JuloOneWorkflowHandler'
        )
        application = ApplicationFactory()
        application.workflow = julo_one_workflow
        application.save()
        name_bank_validation = NameBankValidationFactory(
            bank_code='BCA',
            account_number='11111111',
            name_in_bank='TEST user',
            method='test method',
            validation_id='22222222'
        )
        # application not found

        response = self.client.post('/app_status/ajax_update_name_bank_validation/',
                                   {'name_bank_validation_id': name_bank_validation.id,
                                    'field': 'name_in_bank',
                                    'application_field': 'name_in_bank',
                                    'value': 'Test User',
                                    'application_id': 9999999999})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['status'], 'failed')

        response = self.client.post('/app_status/ajax_update_name_bank_validation/',
                                    {'name_bank_validation_id': name_bank_validation.id,
                                     'field': 'name_in_bank',
                                     'application_field': 'name_in_bank',
                                     'value': 'Test User',
                                     'application_id': application.id})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['status'], 'success')
        name_bank_validation.refresh_from_db()
        application.refresh_from_db()
        self.assertEqual(name_bank_validation.name_in_bank, 'Test User')
        self.assertEqual(application.name_in_bank, 'Test User')


class TestChangeStatusTab(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = AuthUserFactory()
        self.group = Group(name='bo_data_verifier')
        self.group.save()
        self.user.groups.add(self.group)
        self.customer = CustomerFactory(user=self.user)
        self.application = ApplicationFactory(customer=self.customer)
        self.client.force_login(self.user)

    def test_skip_trace_tab(self):
        j1_workflow = WorkflowFactory(name=WorkflowConst.JULO_ONE)
        self.application = ApplicationFactory(
            product_line=ProductLineFactory(
                product_line_code=ProductLineCodes.J1,
            )
        )
        self.application.workflow = j1_workflow
        self.application.save()

        # skiptrace shouldnt show up
        ## x105
        self.application.application_status_id = ApplicationStatusCodes.FORM_PARTIAL
        self.application.save()
        response = self.client.post('/app_status/change_status/{}'.format(self.application.id))
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(b'<a href="#st" data-toggle="tab" aria-expanded="false" title="Skip Tracing">', response.content)

        # skip trace tab should show up
        ## x127
        self.application.application_status_id = ApplicationStatusCodes.TYPO_CALLS_UNSUCCESSFUL
        self.application.save()
        response = self.client.post('/app_status/change_status/{}'.format(self.application.id))
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'<a href="#st" data-toggle="tab" aria-expanded="false" title="Skip Tracing">', response.content)

    def test_registration_method_tag(self):
        j1_workflow = WorkflowFactory(name=WorkflowConst.JULO_ONE)
        self.application = ApplicationFactory(
            product_line=ProductLineFactory(
                product_line_code=ProductLineCodes.J1,
            ),
        )
        self.application.workflow = j1_workflow
        self.application.save()

        # case registration method should NOT show up
        self.application.application_status_id = ApplicationStatusCodes.FORM_CREATED
        self.application.save()

        response = self.client.post('/app_status/change_status/{}'.format(self.application.id))
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(b'<div class="col-xs-3 no-left"><strong>Metode Registrasi</strong></div>', response.content)

        # case registration method should show up & Registration Form
        self.application.application_status_id = ApplicationStatusCodes.FORM_PARTIAL
        self.application.save()

        response = self.client.post('/app_status/change_status/{}'.format(self.application.id))
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'<div class="col-xs-3 no-left"><strong>Metode Registrasi</strong></div>', response.content)
        self.assertIn(b'<span class="registration-method">Registration Form</span>', response.content)

        # case registration method should show up & Video Call
        self.application.application_status_id = ApplicationStatusCodes.FORM_PARTIAL
        self.application.save()

        self.application_path_tag_status = ApplicationPathTagStatusFactory(
            application_tag=IDFyApplicationTagConst.TAG_NAME,
        )
        self.application_path_tag = ApplicationPathTagFactory(
            application_id=self.application.id,
            application_path_tag_status=self.application_path_tag_status,
        )

        response = self.client.post('/app_status/change_status/{}'.format(self.application.id))
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'<div class="col-xs-3 no-left"><strong>Metode Registrasi</strong></div>', response.content)
        self.assertIn(b'Video Call', response.content)


class TestAppStatusListTestCase(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = AuthUserFactory()
        self.group = Group(name='bo_data_verifier')
        self.group.save()

        self.user.groups.add(self.group)
        self.customer = CustomerFactory(user=self.user)
        self.client.force_login(self.user)

    @patch("juloserver.julo.models.Application.determine_kind_of_installment", return_value="bulan")
    def test_is_application_status_can_lock(self, mock_determine_kind_of_installment):
        j1_workflow = WorkflowFactory(name=WorkflowConst.JULO_ONE)
        self.product_line = ProductLineFactory(
            product_line_code=ProductLineCodes.J1,
            payment_frequency='Monthly'
        )

        self.application = ApplicationFactory(
            product_line=self.product_line,
            customer=self.customer,
        )
        self.application.workflow = j1_workflow

        # lock feature should not show up
        ## x105
        self.application.application_status_id = ApplicationStatusCodes.FORM_PARTIAL
        self.application.save()
        response = self.client.get('/app_status/list?status_app=105'.format(self.application.id))
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(b'<i class="fa fa-unlock"></i>', response.content)

        # lock feature should show up
        ## x127
        self.application.application_status_id = ApplicationStatusCodes.TYPO_CALLS_UNSUCCESSFUL
        self.application.save()
        response = self.client.get('/app_status/list?status_app=127'.format(self.application.id))
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'<i class="fa fa-unlock"></i>', response.content)

        ## x140
        self.application.application_status_id = ApplicationStatusCodes.OFFER_MADE_TO_CUSTOMER
        self.application.save()
        response = self.client.get('/app_status/list?status_app=140'.format(self.application.id))
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'<i class="fa fa-unlock"></i>', response.content)
