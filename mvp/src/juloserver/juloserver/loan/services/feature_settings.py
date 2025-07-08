from typing import Dict
from juloserver.julo.services2.feature_setting import FeatureSettingHelper
from juloserver.loan.constants import CampaignConst, LoanFeatureNameConst
from juloserver.julo.constants import FeatureNameConst


class AnaTransactionModelSetting:
    """
    Feature Setting for ana loan transaction model
    """

    DEFAULT_COOLDOWN_TIME = 60 * 10
    DEFAULT_REQUEST_TIMEOUT = 5
    DEFAULT_IS_HITTING_ANA = False
    MINIMUM_LIMIT_TO_HIT_ANA = 1

    def __init__(self):
        self.setting = FeatureSettingHelper(LoanFeatureNameConst.ANA_TRANSACTION_MODEL)

    @property
    def is_active(self) -> bool:
        return self.setting.is_active

    @property
    def cooldown_time(self) -> int:
        return self.setting.get('cooldown_time_in_seconds', self.DEFAULT_COOLDOWN_TIME)

    @property
    def request_timeout(self) -> int:
        return self.setting.get('request_to_ana_timeout_in_seconds', self.DEFAULT_REQUEST_TIMEOUT)

    @property
    def is_hitting_ana(self) -> int:
        return self.setting.get('is_hitting_ana', self.DEFAULT_IS_HITTING_ANA)

    @property
    def minimum_limit(self) -> int:
        return self.setting.get('minimum_limit_to_hit_ana', self.MINIMUM_LIMIT_TO_HIT_ANA)

    def is_customer_eligible(self, customer_id: int) -> bool:
        """
        Check if customer eligible for ana transaction model, for testing/whitelist purposes
        """

        def ends_with_digit(n: int, digits: list):
            return (n % 10) in digits

        whitelist_settings = self.setting.get('whitelist_settings', dict())
        # whitelist off, accept all customers
        if not whitelist_settings.get('is_whitelist_active', False):
            return True

        whitelisted_customer_ids = whitelist_settings.get('whitelist_by_customer_id', [])
        whitelisted_last_digits = whitelist_settings.get('whitelist_by_last_digit', [])

        if customer_id in whitelisted_customer_ids:
            return True

        if ends_with_digit(customer_id, digits=whitelisted_last_digits):
            return True

        return False


class ThorTenorInterventionModelSetting:
    """
    Feature setting for THOR Intervention,
    Delay Intervention is for bottom sheet to trigger again after a given amount of time,
    Tenure Options is the choices of tenure to show in intervention bottom sheet.
    """
    DEFAULT_DELAY_INTERVENTION = 0
    DEFAULT_TENURE_OPTIONS = []

    def __init__(self):
        self.setting = FeatureSettingHelper(FeatureNameConst.THOR_TENOR_INTERVENTION)

    @property
    def is_active(self) -> bool:
        return self.setting.is_active

    @property
    def delay_intervention(self) -> int:
        return self.setting.get('delay_intervention', self.DEFAULT_DELAY_INTERVENTION)

    @property
    def duration_intervention(self) -> list:
        return self.setting.get('tenor_option', self.DEFAULT_TENURE_OPTIONS)


class AppendQrisTransactionMethodSetting:
    """
    Appending QRIS_1 method to front page (temporary)
    """

    def __init__(self):
        self.setting = FeatureSettingHelper(
            feature_name=LoanFeatureNameConst.APPENDING_QRIS_TRANSACTION_METHOD_HOME_PAGE
        )

    @property
    def is_active(self) -> bool:
        return self.setting.is_active


class CrossSellingConfigMethodSetting:
    """
    Feature setting for Cross-selling
    """
    DEFAULT_NUMBER_OF_PRODUCTS = 0

    def __init__(self):
        self.setting = FeatureSettingHelper(FeatureNameConst.CROSS_SELLING_CONFIG)

    @property
    def is_active(self) -> bool:
        return self.setting.is_active

    @property
    def get_info_param(self) -> dict:
        return self.setting.get('info', {})

    @property
    def get_products(self) -> list:
        return self.setting.get('products', [])

    @property
    def get_cross_selling_message(self) -> str:
        return self.setting.get("cross_selling_message", "")

    @property
    def get_available_limit_image(self) -> str:
        return self.setting.get("available_limit_image", "")

    @property
    def get_number_of_products(self) -> int:
        return self.setting.get("number_of_products", self.DEFAULT_NUMBER_OF_PRODUCTS)


class AvailableLimitInfoSetting:
    """
    Feature setting for Available Limit Extra Information
    """

    # section info name for FE
    SECTION_AVAILABLE_CASHLOAN_LIMIT = "available_cash_loan_limit"
    SECTION_NORMAL_AVAILABLE_LIMIT = "normal_available_limit"

    # Default Image Link
    BASE_IMAGE_URL = "https://statics.julo.co.id/loan/available_limit_info_page"
    DEFAULT_ICON = ""  # empty
    MONEY_BAG_ICON = f"{BASE_IMAGE_URL}/red_money_bag.png"
    EXCLAMATION_ICON = f"{BASE_IMAGE_URL}/icon_exclamation_circle.png"
    SPARKLES_ICON = f"{BASE_IMAGE_URL}/icon_sparkles.png"
    WEB_PERKS_ICON = f"{BASE_IMAGE_URL}/web_perks.png"

    def __init__(self):
        self.setting = FeatureSettingHelper(LoanFeatureNameConst.AVAILABLE_LIMIT_INFO)

    @property
    def is_active(self) -> bool:
        return self.setting.is_active

    @property
    def displayed_sections(self) -> bool:
        return self.setting.get('displayed_sections', [])

    def get_section_title(self, section):
        sections = self.setting.get('sections', {})
        section = sections.get(section, {})
        return section['title']

    def get_section_icon(self, section):
        sections = self.setting.get('sections', {})
        section = sections.get(section, {})
        return section['icon']

    def get_section_items(self, section):
        sections = self.setting.get('sections', {})
        section = sections.get(section, {})
        return section['items']


class LockedProductPageSetting:
    """
    Setting for Lock Product Page
    """

    # settings
    MERCURY_LOCKED_SETTING = CampaignConst.PRODUCT_LOCK_PAGE_FOR_MERCURY

    # messages
    DEFAULT_LOCKED_MESSAGE = (
        "Transaksi ini bisa kamu gunakan lagi setelah kamu lunasi tagihan produk ini."
        "<br>Tapi tenang, kamu tetap bisa gunakan limitmu di transaksi lainnya, kok!"
    )
    MERCURY_LOCKED_MESSAGE = (
        "Tarik Dana bisa kamu gunakan lagi setelah kamu "
        "<b>lunasi tagihan Tarik Danamu</b>."
        "<br>Tapi tenang, kamu tetap bisa gunakan limitmu di transaksi lainnya, kok!"
    )

    # images
    DEFAULT_HEADER_IMAGE_URL = (
        "https://statics.julo.co.id/loan/locked_product_page/banner_locked_product.png"
    )

    def __init__(self):
        self.setting = FeatureSettingHelper(
            feature_name=LoanFeatureNameConst.LOCK_PRODUCT_PAGE,
        )

    @property
    def is_active(self) -> bool:
        return self.setting.is_active

    @property
    def locked_settings(self) -> Dict:
        return self.setting.get('locked_settings', {})

    @property
    def default_header_image_url(self) -> Dict:
        return self.setting.get('default_banner_image_url', self.DEFAULT_HEADER_IMAGE_URL)

    @property
    def default_locked_message(self) -> Dict:
        return self.setting.get('default_locked_message', self.DEFAULT_LOCKED_MESSAGE)

    def get_header_image_url(self, setting: str):
        setting = self.locked_settings.get(setting, {})
        return setting.get("header_image_url", self.default_header_image_url)

    def get_locked_message(self, setting: str):
        setting = self.locked_settings.get(setting, {})
        return setting.get("locked_message", self.default_locked_message)


class AutoAdjustDueDateSetting:
    """
    Feature setting for Auto Adjust Due Date
    """

    def __init__(self):
        self.setting = FeatureSettingHelper(LoanFeatureNameConst.AUTO_ADJUST_DUE_DATE)

    @property
    def is_active(self) -> bool:
        return self.setting.is_active

    def get_auto_adjust_due_date_mapping(self) -> dict:
        return self.setting.get("auto_adjust_due_date_mapping", {})

    def get_whitelist(self) -> dict:
        return self.setting.get("whitelist", {})
