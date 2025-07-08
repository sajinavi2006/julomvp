from juloserver.portal.object.dashboard.constants import JuloUserRoles

ELEMENTS_IN_TOKEN = 3
TOKEN_EXPIRED_HOURS = 168  # 7 days
JFINANCING_LOAN_PURPOSE = "julo-ecom"
JFINANCING_VENDOR_NAME = "SMF"  # subject to change
JFINACNING_FE_PRODUCT_CATEGORY = "Kredit HP"


class JFinancingStatus:
    INITIAL = "initial"  # before user signs signature
    ON_REVIEW = 'on_review'
    CONFIRMED = 'confirmed'
    ON_DELIVERY = 'on_delivery'
    COMPLETED = 'completed'
    CANCELED = 'canceled'

    @classmethod
    def change_to_status(cls, status: str) -> list:
        list_status = {
            cls.ON_REVIEW: {cls.CANCELED, cls.CONFIRMED},
            cls.CONFIRMED: {cls.ON_DELIVERY},
            cls.ON_DELIVERY: {cls.COMPLETED},
            cls.COMPLETED: set(),
            cls.CANCELED: set(),
        }
        return list_status[status]


class JFinancingEntryPointType:
    LANDING_PAGE = 'landing_page'
    PRODUCT_DETAIL = 'product_detail'

    @classmethod
    def list_entry_point_types(cls):
        return [cls.LANDING_PAGE, cls.PRODUCT_DETAIL]


class RedisKey:
    J_FINANCING_CUSTOMER_TOKEN = 'j_financing_customer_token:customer_id_{}'


REQUIRED_GROUPS = [
    JuloUserRoles.JFinancingAdmin,
]


class JFinancingResponseMessage:
    INVALID_INPUT = 'Invalid input, please correct!'
    VERIFICATION_NOT_FOUND = 'Smartphone financing verification not found.'
    VERIFICATION_LOCKED = 'Smartphone financing verification is locked.'
    PRODUCT_NOT_AVAILABLE = 'Produk Sedang Tidak Tersedia'
    PRODUCT_OUT_OF_STOCK = 'Stok Produk Habis'


class JFinancingProductListConst:
    MIN_PRODUCT_QUANTITY = 2


class JFinancingProductImageType:
    PRIMARY = 'j_financing_product_primary'
    DETAIL = 'j_financing_product_detail'

    @classmethod
    def list_image_types(cls):
        return [cls.PRIMARY, cls.DETAIL]


class JFinancingFeatureNameConst:
    JULO_FINANCING_PRODUCT_CONFIGURATION = 'julo_financing_product_configuration'
    JULO_FINANCING_PROVINCE_SHIPPING_FEE = 'julo_financing_province_shipping_fee'


class JFinancingErrorMessage:
    JFINANCING_NOT_AVAILABLE = (
        "Maaf, JULO Ponsel+ belum tersedia untukmu. Harap tunggu hingga produk tersedia, ya!"
    )
    SYSTEM_ISSUE = "Maaf, ada masalah pada sistem. Silakan coba beberapa saat lagi, ya!"
    STOCK_NOT_AVAILABLE = (
        "Harap tunggu stok produk tersedia lagi atau kamu juga bisa cek HP lainnya, ya!"
    )
    SIGNATURE_ISSUE = (
        "Maaf, terjadi masalah saat tanda tangan elektronik. Harap ulangi tanda tanganmu, ya!"
    )
    PRODUCT_NOT_AVAILABLE = (
        "Maaf, produk ini tidak dapat ditemukan. Tapi tenang, masih ada pilihan HP lainnya, kok!"
    )
    LIMIT_NOT_ENOUGH = (
        "Maaf, limit tersedia kamu belum mencukupi. Kamu bisa cek pilihan HP lainnya, ya!"
    )
