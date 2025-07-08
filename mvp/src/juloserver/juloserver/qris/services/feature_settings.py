from typing import Dict

from juloserver.julo.services2.feature_setting import FeatureSettingHelper
from juloserver.loan.constants import LoanFeatureNameConst
from juloserver.julo.constants import FeatureNameConst


class QrisLoanEligibilitySetting:
    DEFAULT_MAX_LOAN_AMOUNT = 3_000_000
    DEFAULT_MIN_LOAN_AMOUNT = 5_000

    def __init__(self):
        self.fs = FeatureSettingHelper(
            feature_name=LoanFeatureNameConst.QRIS_LOAN_ELIGIBILITY_SETTING
        )

    @property
    def is_active(self):
        return self.fs.is_active

    @property
    def max_requested_amount(self):
        """ "
        Max loan requested amount
        """
        return self.fs.get('max_requested_amount', self.DEFAULT_MAX_LOAN_AMOUNT)

    @property
    def min_requested_amount(self):
        """ "
        Min loan requested amount
        """
        return self.fs.get('min_requested_amount', self.DEFAULT_MIN_LOAN_AMOUNT)


class QrisBlacklistMerchantSetting:

    def __init__(self):
        self.fs = FeatureSettingHelper(
            feature_name=FeatureNameConst.QRIS_MERCHANT_BLACKLIST_NEW
        )

    @property
    def is_active(self):
        return self.fs.is_active

    @property
    def merchant_names(self):
        """
        list of blacklisted merchant names
        """
        return self.fs.get('merchant_names', [])

    @property
    def merchant_ids(self):
        """
        list of blacklisted merchant ids
        """
        return self.fs.get('merchant_ids', [])


class QrisWhitelistSetting:
    def __init__(self):
        self.fs = FeatureSettingHelper(
            feature_name=LoanFeatureNameConst.QRIS_WHITELIST_ELIGIBLE_USER,
        )

    @property
    def is_active(self):
        return self.fs.is_active

    @property
    def redis_customer_whitelist_active(self):
        return self.fs.get('redis_customer_whitelist_active', False)

    @property
    def customer_ids(self):
        return self.fs.get('customer_ids', [])

    @property
    def allowed_last_digits(self):
        return self.fs.get('allowed_last_digits', [])


class QrisFAQSetting:
    DEFAULT_AMAR_FAQ_LINK = "https://www.julo.co.id/faq"

    def __init__(self):
        self.setting = FeatureSettingHelper(LoanFeatureNameConst.QRIS_FAQ)

    @property
    def is_active(self) -> bool:
        return self.setting.is_active

    @property
    def amar(self) -> Dict:
        return self.setting.get('amar', {})

    @property
    def amar_faq_link(self) -> str:
        if self.amar:
            return self.amar.get('faq_link', self.DEFAULT_AMAR_FAQ_LINK)

        return self.DEFAULT_AMAR_FAQ_LINK


def get_qris_faq_fs() -> QrisFAQSetting:
    return QrisFAQSetting()


class QrisFAQSettingHandler:
    """
    Handler for QrisFAQSetting
    """

    def __init__(self):
        self.setting = get_qris_faq_fs()
        self.default_amar_faq = self.setting.DEFAULT_AMAR_FAQ_LINK

    def get_amar_faq_link(self) -> int:
        if not self.setting.is_active:
            return self.default_amar_faq

        return self.setting.amar_faq_link


class QrisTenureFromLoanAmountSetting:
    DEFAULT_TENURE = 1

    def __init__(self):
        self.setting = FeatureSettingHelper(LoanFeatureNameConst.QRIS_TENURE_FROM_LOAN_AMOUNT)

    @property
    def is_active(self):
        return self.setting.is_active

    @property
    def loan_amount_tenure_map(self) -> Dict:
        return self.setting.get('loan_amount_tenure_map', [])


def get_qris_tenure_from_loan_amount_fs():
    return QrisTenureFromLoanAmountSetting()


class QrisTenureFromLoanAmountHandler:
    """
    Handler for QrisTenureFromLoanAmountSetting
    """

    def __init__(self, amount: int):
        self.amount = amount
        self.setting = get_qris_tenure_from_loan_amount_fs()

    def get_tenure(self) -> int:
        """
        Get tenure from loan amount
        """
        if not self.setting.is_active:
            return self.setting.DEFAULT_TENURE

        for from_amount, to_amount, tenure in self.setting.loan_amount_tenure_map:
            if from_amount < self.amount <= to_amount:
                return tenure

        return self.setting.DEFAULT_TENURE

    @staticmethod
    def get_tenure_in_cm_range(loan_duration: int, max_tenure: int, min_tenure: int) -> int:
        if loan_duration > max_tenure:
            return max_tenure
        if loan_duration < min_tenure:
            return min_tenure

        return loan_duration


class QrisMultipleLenderSetting:
    def __init__(self):
        self.setting = FeatureSettingHelper(LoanFeatureNameConst.QRIS_MULTIPLE_LENDER)

    @property
    def is_active(self):
        return self.setting.is_active

    @property
    def lender_names_ordered_by_priority(self) -> Dict:
        return self.setting.get('lender_names_ordered_by_priority', [])

    @property
    def out_of_balance_threshold(self) -> Dict:
        return self.setting.get('out_of_balance_threshold', 0)

    def is_lender_name_set_up(self, lender_name) -> bool:
        return lender_name in self.lender_names_ordered_by_priority


class QrisErrorLogSetting:
    """
    Logging some known errors to Logging DB
    """

    def __init__(self):
        self.setting = FeatureSettingHelper(LoanFeatureNameConst.QRIS_ERROR_LOG)

    @property
    def is_active(self):
        return self.setting.is_active


class QrisProgressBarSetting:
    """
    Setting for Qris Progress Bar
    {
        "active_seconds_after_success": 86400,
        "progress_detail": {
            "default": {
                "percentage": "25",
                "messages": {
                    "title": "xxx",
                    "body": "xxx",
                    "footer": "xxx"
                }
            },
            "success": {
                "percentage": "100",
                "messages": {
                    "title": "xxx",
                    "body": "xxx",
                    "footer": "xxx"
                }
            },
        }
    }
    """

    STATUS_DEFAULT = 'default'
    DEFAULT_ACTIVE_SECONDS_AFTER_SUCCESS = 60 * 60 * 24  # one day

    def __init__(self):
        self.setting = FeatureSettingHelper(LoanFeatureNameConst.QRIS_PROGRESS_BAR)

    @property
    def is_active(self):
        return self.setting.is_active

    @property
    def active_seconds_after_success(self):
        return self._get_disappear_data().get(
            'active_seconds_after_success',
            self.DEFAULT_ACTIVE_SECONDS_AFTER_SUCCESS,
        )

    @property
    def is_disappear_active(self):
        return self._get_disappear_data().get('is_active', False)

    def _get_status_data(self, status: str):
        detail = self.setting.get('progress_detail')

        status_data = detail.get(status)
        if not status_data:
            status_data = detail.get(self.STATUS_DEFAULT)

        return status_data

    def _get_disappear_data(self):
        disappear_data = self.setting.get('disappear_after_success', {})

        return disappear_data

    def get_percentage(self, status: str):
        status_data = self._get_status_data(status=status)

        return status_data['percentage']

    def get_title(self, status: str):
        status_data = self._get_status_data(status=status)

        return status_data['messages']['title']

    def get_body(self, status: str):
        status_data = self._get_status_data(status=status)

        return status_data['messages']['body']

    def get_footer(self, status: str):
        status_data = self._get_status_data(status=status)

        return status_data['messages']['footer']
