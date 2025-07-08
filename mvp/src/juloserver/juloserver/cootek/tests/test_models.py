import mock
from mock import patch, MagicMock, ANY
from django.db.models import F

from django.test.testcases import TestCase

from ..models import CootekConfiguration
from juloserver.cootek.constants import DpdConditionChoices
from django.utils import timezone
from datetime import timedelta


class TestCootekModels(TestCase):

    def test_get_loan_id_filter_case_1(self):
        cootek_config = CootekConfiguration(loan_ids=['1', '2'])
        result = cootek_config.get_loan_id_filter()
        assert result['annotate'] == {'1_last_digit': ANY}
        assert result['filter'] == {'1_last_digit__in': [1, 2]}

    def test_get_loan_id_filter_case_2(self):
        cootek_config = CootekConfiguration(loan_ids=['11-15'])
        result = cootek_config.get_loan_id_filter()
        assert result['annotate'] == {'2_last_digit': ANY}

    def test_get_loan_id_filter_case_3(self):
        cootek_config = CootekConfiguration(loan_ids=[])
        result = cootek_config.get_loan_id_filter()
        assert result is None

    def test_get_loan_id_filter_case_4(self):
        cootek_config = CootekConfiguration(loan_ids=['67-99'])
        result = cootek_config.get_loan_id_filter()
        assert result['filter'] == {'2_last_digit__range': (67, 99)}

    def test_get_payment_filter_case_1(self):
        cootek_config = CootekConfiguration(
            dpd_condition=DpdConditionChoices.RANGE,
            called_at=-2,
            called_to=0
        )
        result = cootek_config.get_payment_filter(dpd_limit_list=None)
        assert list(result.keys()) == ['due_date__in']

    def test_get_payment_filter_case_2(self):
        cootek_config = CootekConfiguration(
            dpd_condition=DpdConditionChoices.LESS,
            called_at=-2,
            called_to=0
        )
        result = cootek_config.get_payment_filter(dpd_limit_list=None)
        assert list(result.keys()) == ['due_date__gt']
