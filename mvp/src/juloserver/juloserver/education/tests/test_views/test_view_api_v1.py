import copy
import json
from unittest.mock import patch

from django.test.testcases import TestCase
from fakeredis import FakeServer, FakeStrictRedis
from rest_framework import status
from rest_framework.test import APIClient

from juloserver.account.tests.factories import AccountFactory
from juloserver.customer_module.constants import BankAccountCategoryConst
from juloserver.customer_module.tests.factories import BankAccountCategoryFactory
from juloserver.disbursement.constants import NameBankValidationVendors, NameBankValidationStatus
from juloserver.disbursement.tests.factories import BankNameValidationLogFactory
from juloserver.education.constants import FeatureNameConst
from juloserver.education.models import (
    School,
    StudentRegister,
    StudentRegisterHistory,
)
from juloserver.education.tests.factories import (
    SchoolFactory,
    StudentRegisterFactory,
    LoanStudentRegisterFactory,
)
from juloserver.julo.statuses import ApplicationStatusCodes, JuloOneCodes
from juloserver.julo.tests.factories import (
    ApplicationFactory,
    AuthUserFactory,
    BankFactory,
    CustomerFactory,
    FeatureSettingFactory,
    StatusLookupFactory,
    LoanFactory,
)


class TestSchoolListView(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.client.force_login(self.user)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)
        self.customer = CustomerFactory(user=self.user)
        self.account = AccountFactory(
            customer=self.customer, status=StatusLookupFactory(status_code=JuloOneCodes.ACTIVE)
        )
        self.application = ApplicationFactory(customer=self.account.customer, account=self.account)
        self.application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.LOC_APPROVED
        )
        self.application.save()

        self.school = SchoolFactory()

    @patch('juloserver.julocore.redis_completion_py3.RedisEnginePy3.get_client')
    @patch('juloserver.education.services.views_related.is_search_school_with_redis')
    def test_get_school_list_and_adding_school_feature(
        self, mock_is_search_school_with_redis, mock_get_client
    ):
        # FILTER SCHOOL IN DATABASE
        mock_is_search_school_with_redis.return_value = False

        # enable allow_add_new_school
        allow_add_new_school_fs = FeatureSettingFactory(
            is_active=True,
            feature_name=FeatureNameConst.ALLOW_ADD_NEW_SCHOOL,
        )
        response = self.client.get('/api/education/v1/school')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.data['data']
        self.assertEqual(data['list'][0]['id'], self.school.id)
        self.assertEqual(data['list'][0]['name'], self.school.name)
        self.assertEqual(data['adding_enable'], True)

        # disable allow_add_new_school
        allow_add_new_school_fs.is_active = False
        allow_add_new_school_fs.save()
        response = self.client.get('/api/education/v1/school')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['data']['adding_enable'], False)

        # FILTER SCHOOL IN REDIS
        mock_is_search_school_with_redis.return_value = True
        school_data = {'id': 1, 'name': 'School test 1', 'City': 'city test 1'}
        fake_redis_client = FakeStrictRedis(server=FakeServer())
        fake_redis_client.hset('school_ac:d', '1', json.dumps(school_data))
        mock_get_client.return_value = fake_redis_client

        # test search by some letters
        response = self.client.get('/api/education/v1/school?query=N')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.data['data']
        self.assertEqual(data['list'], [])

        # test not search anything -> get school data in hash table
        response = self.client.get('/api/education/v1/school?query=')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.data['data']
        self.assertEqual(len(data['list']), 1)
        self.assertEqual(data['list'][0]['id'], school_data['id'])
        self.assertEqual(data['list'][0]['name'], school_data['name'])


class TestStudentRegisterView(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = AuthUserFactory()
        self.client.force_login(self.user)
        self.client.credentials(HTTP_AUTHORIZATION='Token ' + self.user.auth_expiry_token.key)
        self.customer = CustomerFactory(user=self.user)
        self.account = AccountFactory(
            customer=self.customer, status=StatusLookupFactory(status_code=JuloOneCodes.ACTIVE)
        )
        self.application = ApplicationFactory(customer=self.account.customer, account=self.account)
        self.application.application_status = StatusLookupFactory(
            status_code=ApplicationStatusCodes.LOC_APPROVED
        )
        self.application.save()

        BankAccountCategoryFactory(
            category=BankAccountCategoryConst.EDUCATION,
            parent_category_id=7,
        )
        self.school = SchoolFactory()
        self.bank = BankFactory(
            bank_code='012', bank_name='BCA', xfers_bank_code='BCA', swift_bank_code='01'
        )
        self.bank_name_validation_log = BankNameValidationLogFactory(
            validation_id='1234',
            validation_status=NameBankValidationStatus.SUCCESS,
            validated_name='ABCD',
            account_number='9876',
            method=NameBankValidationVendors.XFERS,
            application=self.application,
            reason='success',
        )

        self.allow_add_new_school_fs = FeatureSettingFactory(
            is_active=False,
            feature_name=FeatureNameConst.ALLOW_ADD_NEW_SCHOOL,
        )

    def test_get_student_registers_success(self):
        response = self.client.get('/api/education/v1/student')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['data']['student'], [])

    def test_create_student_register_success(self):
        data = {
            'school': {
                'id': self.school.id,
            },
            'bank': {
                'code': self.bank.xfers_bank_code,
                'validated_id': self.bank_name_validation_log.validation_id,
            },
            'name': 'Vo Van Duong',
            'note': '0352689431',
        }
        response = self.client.post('/api/education/v1/student', data=data, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        student_register = StudentRegister.objects.last()
        self.assertIsNotNone(student_register)
        self.assertEqual(student_register.school.id, data['school']['id'])
        self.assertEqual(student_register.student_fullname, data['name'])
        self.assertEqual(student_register.note, data['note'])

        bank_account_destination = student_register.bank_account_destination
        self.assertIsNotNone(bank_account_destination)
        self.assertEqual(bank_account_destination.bank.xfers_bank_code, data['bank']['code'])
        self.assertEqual(
            bank_account_destination.name_bank_validation.validation_id,
            data['bank']['validated_id'],
        )
        self.assertIsNotNone(bank_account_destination.name_bank_validation)

        # enable allow_add_new_school and new school
        self.allow_add_new_school_fs.is_active = True
        self.allow_add_new_school_fs.save()
        data['school'].pop('id')
        new_school_name = 'Test new school'
        data['school']['name'] = new_school_name
        response = self.client.post('/api/education/v1/student', data=data, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        student_register = StudentRegister.objects.last()
        self.assertIsNotNone(student_register)
        self.assertEqual(student_register.school.name, new_school_name)
        self.assertEqual(student_register.school.is_verified, False)
        new_school_id = student_register.school.id

        # new school (but already created by other users)
        response = self.client.post('/api/education/v1/student', data=data, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(StudentRegister.objects.last().school.id, new_school_id)

        # test strip note
        data['note'] = '    '
        response = self.client.post('/api/education/v1/student', data=data, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(StudentRegister.objects.last().note, '')

    def test_create_student_register_error(self):
        data = {
            'school': {
                'id': self.school.id,
            },
            'bank': {
                'code': self.bank.xfers_bank_code,
                'validated_id': self.bank_name_validation_log.validation_id,
            },
            'name': 'Vo Van Duong',
            'note': '0352689431',
        }

        # both school id and name
        error_data = copy.deepcopy(data)
        error_data['school']['name'] = 'Test both school id and name'
        response = self.client.post('/api/education/v1/student', data=error_data, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        # allow_add_new_school=False but only school name
        error_data = copy.deepcopy(data)
        error_data['school'].pop('id')
        error_data['school']['name'] = 'Test'
        response = self.client.post('/api/education/v1/student', data=error_data, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('school_id', response.data['errors'][0])

        # allow_add_new_school=False but wrong school_id
        error_data = copy.deepcopy(data)
        error_data['school']['id'] = 1234
        response = self.client.post('/api/education/v1/student', data=error_data, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('school_id', response.data['errors'][0])

        # allow_add_new_school=True but school name already in school list
        self.allow_add_new_school_fs.is_active = True
        self.allow_add_new_school_fs.save()
        error_data = copy.deepcopy(data)
        error_data['school'].pop('id')
        error_data['school']['name'] = self.school.name
        response = self.client.post('/api/education/v1/student', data=error_data, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('school_name', response.data['errors'][0])

        # disable allow_add_new_school to test below cases
        self.allow_add_new_school_fs.is_active = False
        self.allow_add_new_school_fs.save()

        error_data = copy.deepcopy(data)
        error_data['bank']['code'] = 56
        response = self.client.post('/api/education/v1/student', data=error_data, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('bank_code', response.data['errors'][0])

        error_data = copy.deepcopy(data)
        error_data['bank']['validated_id'] = 78
        response = self.client.post('/api/education/v1/student', data=error_data, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('bank_validated_id', response.data['errors'][0])

        error_data = copy.deepcopy(data)
        error_data['name'] = ''
        response = self.client.post('/api/education/v1/student', data=error_data, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('Name', response.data['errors'][0])

    def test_update_student_register_success(self):
        student_register = StudentRegisterFactory(account=self.account)
        student_register_id = student_register.id

        # TEST UPDATE STUDENT REGISTER WHICH DO NOT USE FOR CREATE LOAN BEFORE
        data = {
            'school': {
                'id': self.school.id,
            },
            'bank': {
                'code': self.bank.xfers_bank_code,
                'validated_id': self.bank_name_validation_log.validation_id,
            },
            'name': 'Vo Van Duong',
            'note': '   0352689431\t  ',
        }
        response = self.client.put(
            '/api/education/v1/student/{}'.format(student_register_id), data=data, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        updated_student_register = StudentRegister.objects.get(id=student_register_id)

        self.assertEqual(updated_student_register.school.id, data['school']['id'])
        log = StudentRegisterHistory.objects.filter(
            old_student_register=student_register_id,
            new_student_register=student_register_id,
            field_name='school_id',
        ).last()
        self.assertEqual(log.old_value, str(student_register.school_id))
        self.assertEqual(log.new_value, str(updated_student_register.school_id))

        self.assertEqual(
            updated_student_register.bank_account_destination.bank.xfers_bank_code,
            data['bank']['code'],
        )
        self.assertEqual(
            updated_student_register.bank_account_destination.name_bank_validation.validation_id,
            data['bank']['validated_id'],
        )
        log = StudentRegisterHistory.objects.filter(
            old_student_register=student_register_id,
            new_student_register=student_register_id,
            field_name='bank_account_destination_id',
        ).last()
        self.assertEqual(log.old_value, str(student_register.bank_account_destination_id))
        self.assertEqual(log.new_value, str(updated_student_register.bank_account_destination_id))

        self.assertEqual(updated_student_register.student_fullname, data['name'])
        log = StudentRegisterHistory.objects.filter(
            old_student_register=student_register_id,
            new_student_register=student_register_id,
            field_name='student_fullname',
        ).last()
        self.assertEqual(log.old_value, student_register.student_fullname)
        self.assertEqual(log.new_value, updated_student_register.student_fullname)

        self.assertEqual(updated_student_register.note, data['note'].strip())
        log = StudentRegisterHistory.objects.filter(
            old_student_register=student_register_id,
            new_student_register=student_register_id,
            field_name='note',
        ).last()
        self.assertEqual(log.old_value, student_register.note)
        self.assertEqual(log.new_value, updated_student_register.note)

        # test not update bank
        old_bank_account_destination_id = updated_student_register.bank_account_destination_id
        data.pop('bank')
        response = self.client.put(
            '/api/education/v1/student/{}'.format(student_register_id), data=data, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            old_bank_account_destination_id,
            StudentRegister.objects.get(id=student_register_id).bank_account_destination_id,
        )
        # not update this field -> log only have 1 line for previous update
        self.assertEqual(
            len(
                StudentRegisterHistory.objects.filter(
                    old_student_register=student_register_id,
                    new_student_register=student_register_id,
                    field_name='bank_account_destination_id',
                )
            ),
            1,
        )

        # test update 0 field
        current_count_log = StudentRegisterHistory.objects.filter(
            old_student_register=student_register_id,
            new_student_register=student_register_id,
        ).count()
        response = self.client.put(
            '/api/education/v1/student/{}'.format(student_register_id), data=data, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # no update any field -> no new log since previous update
        self.assertEqual(
            len(
                StudentRegisterHistory.objects.filter(
                    old_student_register=student_register_id,
                    new_student_register=student_register_id,
                )
            ),
            current_count_log,
        )

        # test update other fields with school input manually when creating
        School.objects.filter(id=data['school']['id']).update(is_verified=False)
        response = self.client.put(
            '/api/education/v1/student/{}'.format(student_register_id), data=data, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        School.objects.filter(id=data['school']['id']).update(is_verified=True)

        # TEST UPDATE STUDENT REGISTER WHICH DO USE FOR CREATE LOAN BEFORE
        # -> create new student register
        data = {
            'school': {
                'id': SchoolFactory().id,
            },
            'name': 'Vo Van Duong update FOR CREATE LOAN BEFORE',
            'note': '   0352689431  update FOR CREATE LOAN BEFORE\t  ',
        }
        LoanStudentRegisterFactory(loan=LoanFactory(), student_register=student_register)
        response = self.client.put(
            '/api/education/v1/student/{}'.format(student_register_id), data=data, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        new_student_register_id = response.data['data']['student_register_id']
        self.assertNotEqual(student_register.id, new_student_register_id)
        self.assertTrue(
            len(
                StudentRegisterHistory.objects.filter(
                    old_student_register=student_register_id,
                    new_student_register=new_student_register_id,
                )
            )
            > 0
        )

    def test_update_student_register_error(self):
        # do not have perm to update other student register because account is difference
        student_register = StudentRegisterFactory()
        data = {
            'school': {
                'id': self.school.id,
            },
            'bank': {
                'code': self.bank.xfers_bank_code,
                'validated_id': self.bank_name_validation_log.validation_id,
            },
            'name': 'Vo Van Duong',
            'note': '0352689431',
        }
        response = self.client.put(
            '/api/education/v1/student/{}'.format(student_register.id), data=data, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('student_register_id', response.data['errors'][0])

    def test_delete_student_register_success(self):
        student_register = StudentRegisterFactory(account=self.account)
        response = self.client.delete('/api/education/v1/student', data={'id': student_register.id})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['data']['message'], 'Data successfully deleted')

    def test_delete_student_register_error(self):
        # student of other user
        student_register = StudentRegisterFactory()
        response = self.client.delete('/api/education/v1/student', data={'id': student_register.id})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('not found', response.data['errors'][0])

        # not exists student id
        response = self.client.delete('/api/education/v1/student', data={'id': 1234})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('not found', response.data['errors'][0])
