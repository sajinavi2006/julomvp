from django.test import TestCase
import json

from juloserver.julo.tests.factories import FeatureSettingFactory
from juloserver.loan.admin import MarketingLoanPrizeChanceSettingForm, DelayDisbursementAdminForm
from juloserver.promo.constants import PromoCodeTypeConst
from juloserver.promo.tests.factories import PromoCodeFactory

from juloserver.loan.admin import DelayDisbursementSetting
from django.http import QueryDict
from juloserver.julo.tests.tests_service2.test_delay_disbursement import FeatureSettingDelayD

class TestMarketingLoanPrizeChanceSettingForm(TestCase):
    def setUp(self):
        self.promo_code = PromoCodeFactory(
            is_active=True,
            type=PromoCodeTypeConst.LOAN,
            start_date='2023-02-01 00:00:00',
            end_date='2023-03-02 23:59:59',
        )
        self.setting = FeatureSettingFactory(
            feature_name='marketing_loan_prize_chance',
            is_active=False,
            parameters={
                'minimum_amount': 100,
                'bonus_available_limit_threshold': 200,
                'start_time': '2023-01-01 00:00:00',
                'end_time': '2023-01-02 23:59:59',
                'chance_per_promo_code': 1,
                'campaign_start_date': '2023-10-13',
                'campaign_end_date': '2023-11-30',
                'campaign_period': 'November 2023'
            }
        )
        self.default_values = {
            'is_active': True,
            'description': 'Description',
            'category': 'category',
            'feature_name': self.setting.feature_name,
        }

    def test_save_complete(self):
        form = MarketingLoanPrizeChanceSettingForm(
            data={
                **self.default_values,
                'parameters': json.dumps(
                    {
                        'minimum_amount': 300,
                        'bonus_available_limit_threshold': 400,
                        'promo_code_id': self.promo_code.id,
                        'start_time': '2023-10-13 00:00:00',
                        'end_time': '2023-11-30 23:59:59',
                        'chance_per_promo_code': 1,
                        'campaign_start_date': '2023-10-13',
                        'campaign_end_date': '2023-11-30',
                        'campaign_period': 'November 2023'
                    }
                ),
            },
            instance=self.setting,
        )
        self.assertTrue(form.is_valid())
        form.save()
        self.setting.refresh_from_db()
        self.assertTrue(self.setting.is_active)
        self.assertEqual(
            self.setting.parameters,
            {
                'minimum_amount': 300,
                'bonus_available_limit_threshold': 400,
                'promo_code_id': self.promo_code.id,
                'start_time': '2023-02-01 00:00:00',
                'end_time': '2023-03-02 23:59:59',
                'chance_per_promo_code': 1,
                'campaign_start_date': '2023-10-13',
                'campaign_end_date': '2023-11-30',
                'campaign_period': 'November 2023'
            },
        )

    def test_invalid_date(self):
        form = MarketingLoanPrizeChanceSettingForm(
            data={
                **self.default_values,
                'parameters': json.dumps(
                    {
                        'minimum_amount': 300,
                        'bonus_available_limit_threshold': 400,
                        'start_time': '2023-11-30 23:59:59',
                        'end_time': '2023-10-13 00:00:00',
                        'chance_per_promo_code': 1,
                        'campaign_start_date': '2023-10-13',
                        'campaign_end_date': '2023-11-30',
                        'campaign_period': 'November 2023'
                    }
                ),
            },
            instance=self.setting,
        )
        self.assertFalse(form.is_valid())
        self.assertEqual(form.errors, {
            'parameters': ['end_time must be after start_time.']
        })

    def test_invalid_bonus_available_limit_threshold(self):
        form = MarketingLoanPrizeChanceSettingForm(
            data={
                **self.default_values,
                'parameters': json.dumps(
                    {
                        'minimum_amount': 300,
                        'bonus_available_limit_threshold': -1,
                        'start_time': '2023-10-13 00:00:00',
                        'end_time': '2023-11-30 23:59:59',
                        'chance_per_promo_code': 1,
                        'campaign_start_date': '2023-10-13',
                        'campaign_end_date': '2023-11-30',
                        'campaign_period': 'November 2023'
                    }
                ),
            },
            instance=self.setting,
        )
        self.assertEqual(form.errors, {
            'parameters': ['bonus_available_limit_threshold must be greater or equal than 0.']
        })

    def test_invalid__minimum_amount(self):
        form = MarketingLoanPrizeChanceSettingForm(
            data={
                **self.default_values,
                'parameters': json.dumps(
                    {
                        'minimum_amount': 0,
                        'bonus_available_limit_threshold': 400,
                        'start_time': '2023-10-13 00:00:00',
                        'end_time': '2023-11-30 23:59:59',
                        'chance_per_promo_code': 1,
                        'campaign_start_date': '2023-10-13',
                        'campaign_end_date': '2023-11-30',
                        'campaign_period': 'November 2023'
                    }
                ),
            },
            instance=self.setting,
        )
        self.assertFalse(form.is_valid())
        self.assertEqual(form.errors, {
            'parameters': ['minimum_amount must be greater than 0.']
        })

    def test_invalid_promo_code_id(self):
        form = MarketingLoanPrizeChanceSettingForm(
            data={
                **self.default_values,
                'parameters': json.dumps(
                    {
                        'minimum_amount': 300,
                        'bonus_available_limit_threshold': 400,
                        'start_time': '2023-10-13 00:00:00',
                        'end_time': '2023-11-30 23:59:59',
                        'promo_code_id': '1234',
                        'chance_per_promo_code': 1,
                        'campaign_start_date': '2023-10-13',
                        'campaign_end_date': '2023-11-30',
                        'campaign_period': 'November 2023'
                    }
                ),
            },
            instance=self.setting,
        )
        self.assertFalse(form.is_valid())
        self.assertEqual(form.errors, {
            'parameters': ['promo_code_id does not exist or is not active']
        })


class DelayDisbursementAdminFormTest(TestCase):
    def setUp(self):
        parameters = {
            "content": {"tnc": ""},
            "condition": {
                "cut_off": "23:59",
                "cashback": 25000,
                "start_time": "09:00",
                "daily_limit": 0,
                "monthly_limit": 0,
                "min_loan_amount": 100000,
                "threshold_duration": 601,
                "list_transaction_method_code": [],
            },
            "whitelist_last_digit": 3,
        }
        # Mocking POST data as QueryDict
        self.valid_data = QueryDict(mutable=True)
        self.valid_data.update(
            {
                "feature_name": "delay_disburssement",
                "category": "feature setting",
                "description": "null",
                "is_active": "on",
                "parameters": json.dumps(parameters),
                "condition_start_time": "09:01",
                "condition_cut_off": "12:59",
                "condition_cashback": 25000,
                "condition_threshold_duration": 1,
            }
        )

        # Create an instance of FeatureSetting to pass to the form
        self.instance = FeatureSettingDelayD(parameters=parameters)

    def test_form_initialization(self):
        # Pass the instance to the form
        form = DelayDisbursementAdminForm(self.valid_data, instance=self.instance)
        self.assertIsNotNone(form)
        self.assertIn('condition_start_time', form.fields)
        self.assertIn('condition_cut_off', form.fields)

    def test_valid_form_submission(self):
        form = DelayDisbursementAdminForm(self.valid_data, instance=self.instance)
        self.assertTrue(form.is_valid())
        form.save()
        self.instance.refresh_from_db()
        self.assertEqual(form.cleaned_data['condition_cashback'], 25000)

    def test_empty_cashback(self):
        invalid_data = self.valid_data.copy()
        invalid_data['condition_cashback'] = 0  # Invalid value
        form = DelayDisbursementAdminForm(invalid_data, instance=self.instance)
        self.assertFalse(form.is_valid())

    def test_empty_threshold(self):
        invalid_data = self.valid_data.copy()
        invalid_data['condition_threshold_duration'] = 0  # Invalid value
        form = DelayDisbursementAdminForm(invalid_data, instance=self.instance)
        self.assertFalse(form.is_valid())


class DelayDisbursementAdminSettingTest(TestCase):
    def setUp(self):
        self.helper = DelayDisbursementSetting()

    def test_initialize_form(self):
        self.helper.initialize_form(DelayDisbursementAdminForm)
        self.assertIsNotNone(self.helper.form)
        self.assertIsNotNone(self.helper.change_form_template)
        self.assertIsNotNone(self.helper.fieldsets)
        self.assertIsNone(self.helper.cleaned_request)
        self.assertIsNone(self.helper.cleaned_data)

    def test_reconstruct_request(self):
        request_data = {
            "content": {"tnc": ""},
            "condition": {
                "cut_off": "23:59",
                "cashback": 25000,
                "start_time": "09:00",
                "daily_limit": 0,
                "monthly_limit": 0,
                "min_loan_amount": 100000,
                "threshold_duration": 601,
                "list_transaction_method_code": [],
            },
            "whitelist_last_digit": 3,
        }
        self.helper.cleaned_data = request_data
        self.helper.reconstruct_request(request_data)
        self.assertIsNone(self.helper.form)
        self.assertIsNone(self.helper.change_form_template)
        self.assertIsNone(self.helper.fieldsets)
        self.assertEqual(
            self.helper.cleaned_data['whitelist_last_digit'],
            self.helper.cleaned_request['whitelist_last_digit'],
        )
