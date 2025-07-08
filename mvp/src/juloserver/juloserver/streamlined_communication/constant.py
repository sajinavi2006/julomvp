from builtins import object
from argparse import Namespace

from django.conf import settings

from django.conf import settings

from juloserver.julo.constants import (
    FeatureNameConst,
    VendorConst,
)
from juloserver.payment_point.constants import TransactionMethodCode


class CommunicationPlatform(object):
    EMAIL = 'EMAIL'
    WA = 'WA'
    PN = 'PN'
    SMS = 'SMS'
    IAN = 'IAN'
    ROBOCALL = 'ROBOCALL'
    INFO_CARD = 'INFO_CARD'
    SLIK_NOTIFICATION = 'SLIK_NOTIFICATION'
    CHOICES = (
        (EMAIL, 'Email'),
        (WA, 'Whatsapp'),
        (PN, 'Push Notification'),
        (SMS, 'SMS'),
        (IAN, 'In App Notification'),
        (ROBOCALL, 'Robocall'),
        (INFO_CARD, 'Info Home Card'),
        (SLIK_NOTIFICATION, 'Tagihan banner')
    )
    PAYMENT_WIDGET = 'PAYMENT_WIDGET'


class Product(object):

    class SMS:
        J1 = 'j1'
        JTURBO = 'jturbo'
        MTL = 'mtl'
        STL = 'stl'
        PEDE_MTL = 'pedemtl'
        PEDE_STL = 'pedestl'
        BUKALAPAK = 'bukalapak'
        LAKU6 = 'laku6'
        GRAB= 'grab'

    class EMAIL:
        J1 = 'j1'
        MTL = 'mtl'
        STL = 'stl'
        INTERNAL_PRODUCT = 'internal_product'
        JTURBO = 'jturbo'
        GRAB = 'grab'

    ROBOCALL_PRODUCTS = {
        'nexmo_mtl': 'Nexmo MTL',
        'nexmo_stl': 'Nexmo STL',
        'nexmo_j1': 'Nexmo J1',
        'nexmo_pedemtl': 'Nexmo Pede MTL',
        'nexmo_pedestl': 'Nexmo Pede STL',
        'nexmo_grab': 'Nexmo Grab',
        'nexmo_dana': 'Nexmo Dana',
        'nexmo_turbo': 'Nexmo JTurbo',
    }
    SMS_PRODUCTS = {
        SMS.J1: 'J1',
        SMS.JTURBO: 'JTURBO',
        SMS.MTL: 'MTL',
        SMS.STL: 'STL',
        SMS.PEDE_MTL: 'Pede MTL',
        SMS.PEDE_STL: 'Pede STL',
        SMS.BUKALAPAK: 'Bukalapak Bayarnanti',
        SMS.LAKU6: 'LAKU6',
        SMS.GRAB: 'GRAB'
    }
    PN_PRODUCTS = {
        'j1': 'J1',
        'jturbo': 'JTURBO',
        'mtl': 'mtl',
        'stl': 'stl',
        'laku6': 'laku6',
        'icare': 'icare',
        'axiata': 'axiata',
        'pedemtl': 'pedemtl',
        'pedestl': 'pedestl',
        'bukalapak': 'bukalapak',
    }
    EMAIL_PRODUCTS = {
        EMAIL.J1: 'J1',
        EMAIL.JTURBO: 'JTurbo',
        EMAIL.MTL: 'MTL',
        EMAIL.STL: 'STL',
        EMAIL.INTERNAL_PRODUCT: 'MTL & STL',
        EMAIL.GRAB: 'GRAB',
    }
    STREAMLINED_PRODUCT = Namespace(**{
        'j1': None,
        'jstarter': 'jstarter'
    }
    )

    @classmethod
    def sms_non_account_products(cls):
        """
        All products that doesn't have `ops.account` in the `ops.application.
        In the `ops.loan` it is bind to `ops.application` instead of `ops.account`.

        These product are old products before J1 era.
        """
        return (
            cls.SMS.MTL,
            cls.SMS.STL,
            cls.SMS.PEDE_STL,
            cls.SMS.PEDE_MTL,
            cls.SMS.BUKALAPAK,
            cls.SMS.LAKU6,
        )


class CardProperty(object):
    APP_DEEPLINK = 'app_deeplink'
    WEBPAGE = 'webpage'
    REDIRECT = 'redirect'
    EXTRA_220_LIMIT_THRESHOLD = 500000
    RELOAD = 'reload'

    CARD_ACTION_CHOICES = (
        (APP_DEEPLINK, 'App Deeplink'),
        (WEBPAGE, 'Webpage'),
        (REDIRECT, 'Redirect'),
    )
    CARD_TYPE_CHOICES = (
        ('1', '1. L.Image, R.Title, R.Content, R.Button'),
        ('2', '2. M.Title, M.Content, M.Button'),
        ('3A', '3A. M.Title, M.Content, L.Button, R.Button'),
        ('3B', '3B. M.Title, M.Content, M.Button'),
    )
    IMAGE_TYPE = Namespace(**{
        'card_background_image': 'CARD_BACKGROUND_IMAGE',
        'card_optional_image': 'CARD_OPTIONAL_IMAGE',
        'button_background_image': 'BUTTON_IMAGE',
        'l_button_background_image': 'L_BUTTON_IMAGE',
        'm_button_background_image': 'M_BUTTON_IMAGE',
        'r_button_background_image': 'R_BUTTON_IMAGE',
    })

    LIMIT_GTE_500 = 'LIMIT_GTE_500'
    AUTODEBET_BENEFITS = {
        'cashback': 'AUTODEBET_CASHBACK_BENEFIT',
        'waive': 'AUTODEBET_WAIVE_BENEFIT',
    }
    LATE_FEE_EARLIER_EXPERIMENT = 'LATE_FEE_EARLIER_EXPERIMENT'
    CASHBACK_NEW_SCHEME_EXPERIMENT = 'CASHBACK_NEW_SCHEME_EXPERIMENT'
    SMS_AFTER_ROBOCALL_EXPERIMENT = 'SMS_AFTER_ROBOCALL_EXPERIMENT'
    EXTRA_CONDITION = (
        ('CUSTOMER_HAVE_HIGH_SCORE', 'only for people with high score'),
        ('CUSTOMER_HAVE_MEDIUM_SCORE', 'customer who have medium score'),
        ('CUSTOMER_HAVE_HIGH_C_SCORE', 'customer who have high C score'),
        ('CUSTOMER_HAVE_LOW_SCORE_OR_C', 'customer with low score / C'),
        ('ALL_106_EXPECT_PREVIOUS_EXPIRY_REASON',
         'all 106 except previous expiry reason = negative payment history'),
        ('MOVE_TO_106_WITH_REASON_NEGATIVE_PAYMENT_HISTORY',
         'move to 106 with reason = negative payment history'),
        ('ALREADY_ELIGIBLE_TO_REAPPLY', 'Already eligible to reapply'),
        ('HAS_NOT_SIGN_MASTER_AGREEMENT', 'has not sign master agreement'),
        ('MSG_TO_STAY_UNTIL_1ST_TRANSACTION', 'msg to stay until 1st transaction'),
        ('MTL_MIGRATION_CAN_REAPPLY', 'mtl customer can reapply to julo1'),
        ('MTL_MIGRATION_CAN_NOT_REAPPLY', 'mtl customer can not reapply to julo1'),
        ('REUPLOAD_KTP_ONLY_INFOCARD', 'Privy reupload - KTP'),
        ('REUPLOAD_SELFIE_ONLY_INFOCARD', 'Privy reupload - Selfie'),
        ('REUPLOAD_SELFIE_WITH_KTP_INFOCARD', 'Privy reupload - Selfie with KTP'),
        ('REUPLOAD_SIM_ONLY_INFOCARD', 'Privy reupload - SIM'),
        ('REUPLOAD_KK_ONLY_INFOCARD', 'Privy reupload - KK'),
        ('REUPLOAD_EKTP_ONLY_INFOCARD', 'Privy reupload - E-KTP'),
        ('REUPLOAD_KTP_SELFIE_INFOCARD', 'Privy reupload - KTP and Selfie'),
        ('REUPLOAD_KTP_KK_INFOCARD', 'Privy reupload - KTP and KK'),
        ('REUPLOAD_KTP_SIM_INFOCARD', 'Privy reupload - KTP and SIM'),
        ('REUPLOAD_SIM_SELFIE_INFOCARD', 'Privy reupload - SIM and Selfie'),
        ('REUPLOAD_SIM_KK_INFOCARD', 'Privy reupload - KK and SIM'),
        ('REUPLOAD_SELFIE_KK_INFOCARD', 'Privy reupload - KK and Selfie'),
        ('REUPLOAD_PASSPORT_ONLY_INFOCARD', 'Privy reupload - Passport'),
        ('REUPLOAD_SELFIE_WITH_PASSPORT_INFOCARD',
         'Privy reupload - Selfie with Passport and Passport'),
        ('REUPLOAD_SELFIE_PASSPORT_INFOCARD', 'Privy reupload - Passport and Selfie'),
        (LIMIT_GTE_500, 'limit greater than equal Rp500.000'),
        ('GRAB_INFO_CARD', 'Grab Info Card'),
        ('GRAB_INFO_CARD_BAD_HISTORY', 'Grab - Bad History'),
        ('GRAB_INFO_CARD_REAPPLY', 'Grab - Can Reapply'),
        ('GRAB_INFO_CARD_JULO_CUSTOMER', 'Grab - Reapply Julo Customer'),
        ('GRAB_INFO_CARD_JULO_CUSTOMER_FAILED', 'Grab - Reapply Julo Customer'),
        ('GRAB_ROBOCALL_HIGH_SCORE', 'Grab - Robocall High C score'),
        ('GRAB_ROBOCALL_MEDIUM_SCORE', 'Grab - Robocall Medium C score'),
        ('GRAB_ROBOCALL_LOW_SCORE', 'Grab - Robocall Low C score'),
        ('INAPP_PTP_BEFORE_SET', 'In App PTP - Before Set PTP'),
        ('INAPP_PTP_AFTER_SET', 'In App PTP - After Set PTP'),
        ('ELIGIBLE_FOR_INAPP_CALLBACK', 'Eligible for In App Callback'),
        ('INAPP_CALLBACK_ALREADY_FILLED', 'In App callback already filled'),
        (AUTODEBET_BENEFITS['cashback'], 'Autodebet - Cashback Benefit'),
        (AUTODEBET_BENEFITS['waive'], 'Autodebet - Waiver Benefit'),
        ('PARTNERSHIP_WEBVIEW_INFO_CARDS', 'Partnership Webview - Info Cards'),
        ('PARTNERSHIP_WEBVIEW_INFO_CARDS_BAD_HISTORY', 'Partnership Webview - Bad History'),
        ('PARTNERSHIP_WEBVIEW_INFO_CUSTOMER_HAVE_HIGH_SCORE',
         'Partnership Webview - only for people with high score'),
        ('PARTNERSHIP_WEBVIEW_INFO_CUSTOMER_HAVE_MEDIUM_SCORE',
         'Partnership Webview - customer who have medium score'),
        ('PARTNERSHIP_WEBVIEW_INFO_CUSTOMER_HAVE_HIGH_C_SCORE',
         'Partnership Webview - customer who have high C score'),
        ('PARTNERSHIP_WEBVIEW_INFO_CUSTOMER_HAVE_LOW_SCORE_OR_C',
         'Partnership Webview - customer with low score / C'),
        ('PARTNERSHIP_WEBVIEW_INFO_ALREADY_ELIGIBLE_TO_REAPPLY',
         'Partnership Webview - Already eligible to reapply'),
        ('PARTNERSHIP_WEBVIEW_INFO_MSG_TO_STAY_UNTIL_1ST_TRANSACTION',
         'Partnership Webview - Message Until First Transaction'),
        ('PARTNERSHIP_WEBVIEW_INFO_MOVE_TO_106_WITH_REASON_NEGATIVE_PAYMENT_HISTORY',
         'Partnership Webview - 106 Negative Payment History'),
        ('PARTNERSHIP_WEBVIEW_INFO_ALL_106_EXPECT_PREVIOUS_EXPIRY_REASON',
         'Partnership Webview - 106 expect previous expiry reason'),
        ('PARTNERSHIP_WEBVIEW_INFO_CHECK_LIMIT_AND_CONCURRENCY',
         'Partnership Webview - Check Limit and Concurrency'),
        ('PARTNERSHIP_WEBVIEW_INFO_CUSTOMER_HAVE_LOW_SCORE_OR_C_WITH_DELAY',
         'Partnership Webview - Customer low C with Delay'),
        ('PARTNERSHIP_WEBVIEW_INFO_CUSTOMER_WAITING_SCORE',
         'Partnership Webview - Customer waiting score'),
        ('PARTNERSHIP_WEBVIEW_INFO_CARD_BUTTON_FOR_LINKAJA',
         'Partnership Webview - button for linkaja'),
        ('CREDIT_CARD_TRANSACTION_CHOOSE_TENOR', 'credit card - Transaction choose tenor'),
        ('J1_ACTIVE_REFERRAL_CODE_EXIST', 'Referral - J1'),
        ('J1_NEXMO_ROBOCALL_COLLECTION_TAILORED', 'J1 nexmo - Robocall collection tailored'),
        ('AUTODEBET_NOT_ACTIVE', 'Autodebet Not Active'),
        ('JULO_TURBO_OFFER_TO_REGULAR', 'Julo Turbo Offer to Regular / J1'),
        ('ACTIVATION_CALL_JTURBO_UPGRADE', 'Activation Call JTurbo Upgrade'),
        ('SUCCESS_JTURBO_UPGRADE', 'Success JTurbo Upgrade'),
        ('REJECTION_JTURBO_UPGRADE', 'Rejection JTurbo Upgrade'),
        ('J1_LIMIT_LESS_THAN_TURBO', 'J1 Limit'),
        ('JULO_STARTER_WAIT_VERIFICATION', 'Julo Starter wait for verification'),
        ('JULO_TURBO_OFFER_J1_CAN_REAPPLY', 'Julo Turbo Offer J1 Can Reapply'),
        ('JULO_TURBO_OFFER_J1_CANNOT_REAPPLY', 'Julo Turbo Offer J1 Cannot Reapply'),
        ('AUTODEBET_NOT_ACTIVE_JTURBO', 'Autodebet Not Active - JTurbo'),
        ('TYPO_CALLS_UNSUCCESSFUL', 'Typo Calls Unsuccessful'),
        (LATE_FEE_EARLIER_EXPERIMENT, LATE_FEE_EARLIER_EXPERIMENT),
        (CASHBACK_NEW_SCHEME_EXPERIMENT, CASHBACK_NEW_SCHEME_EXPERIMENT),
        (SMS_AFTER_ROBOCALL_EXPERIMENT, SMS_AFTER_ROBOCALL_EXPERIMENT),
        ('unsent moengage experiment', 'unsent moengage experiment'),
        ('GRAB_BANK_ACCOUNT_REJECTED', 'Grab - Bank Account Rejected'),
        ('GRAB_INFO_CARD_AUTH_PENDING', 'Grab - Waiting for Auth'),
        ('GRAB_INFO_CARD_AUTH_SUCCESS', 'Grab - Auth Success'),
        ('GRAB_INFO_CARD_AUTH_FAILED', 'Grab - Auth Failed'),
        ('GRAB_INFO_CARD_AUTH_FAILED_4002', 'Grab - Auth Error 4002'),
        (FeatureNameConst.MARKETING_LOAN_PRIZE_CHANCE, 'Marketing Loan Prize Chance'),
        ('GRAB_PHONE_NUMBER_CHECK_FAILED', 'Grab - phone number check failed'),
        ('GRAB_FAILED_3MAX_CREDITORS_CHECK', 'Grab - Failed 3 max creditors check'),
        ('GRAB_FAILED_3MAX_CREDITORS_BOTTOM_SHEET', 'Grab - Failed 3 max creditors bottom sheet'),
        ('GRAB_PHONE_NUMBER_CHECK_FAILED', 'Grab - phone number check failed'),
        ('GRAB_AJUKAN_PINJAMAN_LAGI', 'Grab - ajukan pinjaman lagi'),
        ('GRAB_BELUM_BISA_MELANJUTKAN_APLIKASI', 'Grab - Belum bisa melanjutkan aplikasi'),
    )
    CARD_TYPE = {
        '1': '1. L.Image, R.Title, R.Content, R.Button',
        '2': '2. M.Title, M.Content, M.Button',
        '3A': '3A. M.Title, M.Content, L.Button, R.Button',
        '3B': '3B. M.Title, M.Content, M.Button',
        '9': '4. youtube'
    }
    CARD_TYPE_CHOICES_FOR_FORM = (
        ('1', '1. L.Image, R.Title, R.Content, R.Button'),
        ('2', '2. M.Title, M.Content, M.Button'),
        ('3', '3. M.Title, M.Content, L/M.Button, R.Button'),
        ('9', '4. Youtube'),
    )
    CARD_PRODUCT_CHOICES_FOR_FORM = (
        ('J1', 'J1'),
        ('jstarter', 'JStarter'),
    )
    APP_DEEPLINK_CHOICES = (
        ('home', 'Home Page'),
        ('appl_forms', 'Application Long Forms'),
        ('j1_appl_docs', 'Documents Application J1'),
        ('appl_docs', 'Documents Application'),
        ('appl_main', 'Main Application'),
        ('agunan', 'Agunan'),
        ('aktivitaspinjaman', 'Aktivitas Pinjaman'),
        ('syaratdanketentuan', 'Syarat dan ketentuan'),
        ('howtopay', 'Cara Membayar'),
        ('productselection', 'Product Selection'),
        ('loan_activity', 'Loan'),
        ('faq', 'FAQ'),
        ('contactus', 'Hubungi kami'),
        ('profile', 'Profile'),
        ('rating-playstore', 'Rating Playstore'),
        ('mtl', 'mtl'),
        ('stl', 'stl'),
        ('homescreen', 'HOME SCREEN'),
        ('product', 'product'),
        ('product_stl', 'product_stl'),
        ('got_offers', 'got_offers'),
        ('tnc', 'tnc'),
        ('referral', 'referral'),
        ('rating_in_apps', 'rating_in_apps'),
        ('about', 'about'),
        ('appl_forms_loandetails', 'appl_forms_loandetails'),
        ('appl_forms_personaldata', 'appl_forms_personaldata'),
        ('appl_forms_familyinfo', 'appl_forms_familyinfo'),
        ('appl_forms_workedu', 'appl_forms_workedu'),
        ('appl_forms_financial', 'appl_forms_financial'),
        ('appl_docs_kk_ktp', 'appl_docs_kk_ktp'),
        ('appl_docs_financial', 'appl_docs_financial'),
        ('appl_docs_selfie', 'appl_docs_selfie'),
        ('reapply', 'reapply'),
        ('cashback', 'Cashback'),
        ('reapply_j1', 'Reapply J1 Flow'),
        ('in_app_ptp', 'In App PTP'),
        ('product_transfer_self', 'Tarik Dana'),
        ('in_app_callback', 'In App Callback'),
        ('to_master_agreement', 'Master Agreement'),
        ('reapply_jstarter', 'Reapply Julo Starter'),
        ('to_upgrade_form', 'Julo Starter to J1 Form'),
        ('to_additional_form', 'Additional Form Julo Starter'),
        ('autodebet_activation_drawer', 'Autodebet Activation Drawer'),
        ('app_notif_setting', 'JULO App Notification Settings'),
        ('dana_link', 'Dana Linking'),
        ('gopay_linking', 'Gopay Linking'),
        ('gopay_autodebet', 'Gopay Autodebet'),
        ('autodebet_idfy', 'Autodebet IDFy'),
        ('dana_autodebet', 'DANA Autodebet'),
        ('bca_autodebet', 'BCA Autodebet'),
        ('bri_autodebet', 'BRI Autodebet'),
        ('mandiri_autodebet', 'Mandiri Autodebet'),
        ('bni_autodebet', 'BNI Autodebet'),
        ('ovo_autodebet', 'OVO Autodebet'),
    )
    ALREADY_ELIGIBLE_TO_REAPPLY = 'ALREADY_ELIGIBLE_TO_REAPPLY'
    CUSTOMER_WAITING_SCORE = 'CUSTOMER_WAITING_SCORE'
    CUSTOMER_HAVE_HIGH_SCORE = 'CUSTOMER_HAVE_HIGH_SCORE'
    CUSTOMER_HAVE_MEDIUM_SCORE = 'CUSTOMER_HAVE_MEDIUM_SCORE'
    CUSTOMER_HAVE_HIGH_C_SCORE = 'CUSTOMER_HAVE_HIGH_C_SCORE'
    CUSTOMER_HAVE_LOW_SCORE_OR_C = 'CUSTOMER_HAVE_LOW_SCORE_OR_C'
    CUSTOMER_HAVE_LOW_SCORE_OR_C_WITH_DElAY = 'CUSTOMER_HAVE_LOW_SCORE_OR_C_WITH_DElAY'
    ALL_106_EXPECT_PREVIOUS_EXPIRY_REASON = 'ALL_106_EXPECT_PREVIOUS_EXPIRY_REASON'
    MOVE_TO_106_WITH_REASON_NEGATIVE_PAYMENT_HISTORY =\
        'MOVE_TO_106_WITH_REASON_NEGATIVE_PAYMENT_HISTORY'
    HAS_NOT_SIGN_MASTER_AGREEMENT = 'HAS_NOT_SIGN_MASTER_AGREEMENT'
    HAS_NOT_SUBMIT_EXTRA_FORM = 'HAS_NOT_SUBMIT_EXTRA_FORM'
    MSG_TO_STAY_UNTIL_1ST_TRANSACTION = 'MSG_TO_STAY_UNTIL_1ST_TRANSACTION'
    MTL_MIGRATION_CAN_REAPPLY = 'MTL_MIGRATION_CAN_REAPPLY'
    MTL_MIGRATION_CAN_NOT_REAPPLY = 'MTL_MIGRATION_CAN_NOT_REAPPLY'
    INAPP_PTP_BEFORE_SET = 'INAPP_PTP_BEFORE_SET'
    INAPP_PTP_BEFORE_SET_V2 = 'INAPP_PTP_BEFORE_SET_V2'
    INAPP_PTP_AFTER_SET = 'INAPP_PTP_AFTER_SET'
    ELIGIBLE_FOR_INAPP_CALLBACK = 'ELIGIBLE_FOR_INAPP_CALLBACK'
    INAPP_CALLBACK_ALREADY_FILLED = 'INAPP_CALLBACK_ALREADY_FILLED'
    CREDIT_CARD_TRANSACTION_CHOOSE_TENOR = 'CREDIT_CARD_TRANSACTION_CHOOSE_TENOR'
    CREDIT_CARD_RESUBMIT_SELFIE = 'CREDIT_CARD_RESUBMIT_SELFIE'
    JULO_CARD_WRONG_PIN_EXCEED = 'JULO_CARD_WRONG_PIN_EXCEED'
    JULO_STARTER_OFFER_TO_REGULAR = 'JULO_STARTER_OFFER_TO_REGULAR'
    JULO_STARTER_WAIT_VERIFICATION = 'JULO_STARTER_WAIT_VERIFICATION'
    JULO_STARTER_135_190 = 'JULO_STARTER_ALLOWED_x135_x190'
    JULO_STARTER_133_TO_190 = 'JULO_STARTER_FROM_x133_TO_x190'

    REUPLOAD_KTP_ONLY_INFOCARD = 'REUPLOAD_KTP_ONLY_INFOCARD'
    REUPLOAD_SELFIE_ONLY_INFOCARD = 'REUPLOAD_SELFIE_ONLY_INFOCARD'
    REUPLOAD_SELFIE_WITH_KTP_INFOCARD = 'REUPLOAD_SELFIE_WITH_KTP_INFOCARD'
    REUPLOAD_SIM_ONLY_INFOCARD = 'REUPLOAD_SIM_ONLY_INFOCARD'
    REUPLOAD_KK_ONLY_INFOCARD = 'REUPLOAD_KK_ONLY_INFOCARD'
    REUPLOAD_EKTP_ONLY_INFOCARD = 'REUPLOAD_EKTP_ONLY_INFOCARD'
    REUPLOAD_KTP_SELFIE_INFOCARD = 'REUPLOAD_KTP_SELFIE_INFOCARD'
    REUPLOAD_KTP_KK_INFOCARD = 'REUPLOAD_KTP_KK_INFOCARD'
    REUPLOAD_KTP_SIM_INFOCARD = 'REUPLOAD_KTP_SIM_INFOCARD'
    REUPLOAD_SIM_SELFIE_INFOCARD = 'REUPLOAD_SIM_SELFIE_INFOCARD'
    REUPLOAD_SIM_KK_INFOCARD = 'REUPLOAD_SIM_KK_INFOCARD'
    REUPLOAD_SELFIE_KK_INFOCARD = 'REUPLOAD_SELFIE_KK_INFOCARD'
    REUPLOAD_PASSPORT_ONLY_INFOCARD = 'REUPLOAD_PASSPORT_ONLY_INFOCARD'
    REUPLOAD_SELFIE_WITH_PASSPORT_INFOCARD = 'REUPLOAD_SELFIE_WITH_PASSPORT_INFOCARD'
    REUPLOAD_SELFIE_PASSPORT_INFOCARD = 'REUPLOAD_SELFIE_PASSPORT_INFOCARD'
    J1_ACTIVE_REFERRAL_CODE_EXIST = 'J1_ACTIVE_REFERRAL_CODE_EXIST'
    J1_NEXMO_ROBOCALL_COLLECTION_TAILORED = 'J1_NEXMO_ROBOCALL_COLLECTION_TAILORED'
    GRAB_INFO_CARD = 'GRAB_INFO_CARD'
    GRAB_INFO_CARD_BAD_HISTORY = 'GRAB_INFO_CARD_BAD_HISTORY'
    GRAB_INFO_CARD_REAPPLY = 'GRAB_INFO_CARD_REAPPLY'
    GRAB_INFO_CARD_JULO_CUSTOMER = 'GRAB_INFO_CARD_JULO_CUSTOMER'
    GRAB_INFO_CARD_JULO_CUSTOMER_FAILED = 'GRAB_INFO_CARD_JULO_CUSTOMER_FAILED'
    PAID_FIRST_INSTALLMENT_AND_NOT_REFER = 'PAID_FIRST_INSTALLMENT_AND_NOT_REFER'
    PARTNERSHIP_WEBVIEW_INFO_CARDS = 'PARTNERSHIP_WEBVIEW_INFO_CARDS'
    PARTNERSHIP_WEBVIEW_INFO_CARDS_BAD_HISTORY = 'PARTNERSHIP_WEBVIEW_INFO_CARDS_BAD_HISTORY'
    PARTNERSHIP_WEBVIEW_INFO_ALREADY_ELIGIBLE_TO_REAPPLY = \
        'PARTNERSHIP_WEBVIEW_INFO_ALREADY_ELIGIBLE_TO_REAPPLY'
    PARTNERSHIP_WEBVIEW_INFO_CUSTOMER_HAVE_LOW_SCORE_OR_C = \
        'PARTNERSHIP_WEBVIEW_INFO_CUSTOMER_HAVE_LOW_SCORE_OR_C'
    PARTNERSHIP_WEBVIEW_INFO_CUSTOMER_HAVE_HIGH_C_SCORE = \
        'PARTNERSHIP_WEBVIEW_INFO_CUSTOMER_HAVE_HIGH_C_SCORE'
    PARTNERSHIP_WEBVIEW_INFO_CUSTOMER_HAVE_MEDIUM_SCORE = \
        'PARTNERSHIP_WEBVIEW_INFO_CUSTOMER_HAVE_MEDIUM_SCORE'
    PARTNERSHIP_WEBVIEW_INFO_CUSTOMER_HAVE_HIGH_SCORE = \
        'PARTNERSHIP_WEBVIEW_INFO_CUSTOMER_HAVE_HIGH_SCORE'
    PARTNERSHIP_WEBVIEW_INFO_MSG_TO_STAY_UNTIL_1ST_TRANSACTION = \
        'PARTNERSHIP_WEBVIEW_INFO_MSG_TO_STAY_UNTIL_1ST_TRANSACTION'
    PARTNERSHIP_WEBVIEW_INFO_MOVE_TO_106_WITH_REASON_NEGATIVE_PAYMENT_HISTORY = \
        'PARTNERSHIP_WEBVIEW_INFO_MOVE_TO_106_WITH_REASON_NEGATIVE_PAYMENT_HISTORY'
    PARTNERSHIP_WEBVIEW_INFO_ALL_106_EXPECT_PREVIOUS_EXPIRY_REASON = \
        'PARTNERSHIP_WEBVIEW_INFO_ALL_106_EXPECT_PREVIOUS_EXPIRY_REASON'
    PARTNERSHIP_WEBVIEW_INFO_CHECK_LIMIT_AND_CONCURRENCY = \
        'PARTNERSHIP_WEBVIEW_INFO_CHECK_LIMIT_AND_CONCURRENCY'
    PARTNERSHIP_WEBVIEW_INFO_CUSTOMER_HAVE_LOW_SCORE_OR_C_WITH_DELAY = \
        'PARTNERSHIP_WEBVIEW_INFO_CUSTOMER_HAVE_LOW_SCORE_OR_C_WITH_DELAY'
    PARTNERSHIP_WEBVIEW_INFO_CUSTOMER_WAITING_SCORE = \
        'PARTNERSHIP_WEBVIEW_INFO_CUSTOMER_WAITING_SCORE'
    PARTNERSHIP_WEBVIEW_INFO_CARD_BUTTON_FOR_LINKAJA = \
        'PARTNERSHIP_WEBVIEW_INFO_CARD_BUTTON_FOR_LINKAJA'
    AUTODEBET_NOT_ACTIVE = 'AUTODEBET_NOT_ACTIVE'
    JULO_TURBO_OFFER_TO_REGULAR = 'JULO_TURBO_OFFER_TO_REGULAR'
    ACTIVATION_CALL_JTURBO_UPGRADE = 'ACTIVATION_CALL_JTURBO_UPGRADE'
    SUCCESS_JTURBO_UPGRADE = 'SUCCESS_JTURBO_UPGRADE'
    REJECTION_JTURBO_UPGRADE = 'REJECTION_JTURBO_UPGRADE'
    J1_LIMIT_LESS_THAN_TURBO = 'J1_LIMIT_LESS_THAN_TURBO'
    JULO_TURBO_OFFER_J1_CAN_REAPPLY = 'JULO_TURBO_OFFER_J1_CAN_REAPPLY'
    JULO_TURBO_OFFER_J1_CANNOT_REAPPLY = 'JULO_TURBO_OFFER_J1_CANNOT_REAPPLY'
    AUTODEBET_NOT_ACTIVE_JTURBO = 'AUTODEBET_NOT_ACTIVE_JTURBO'
    TYPO_CALLS_UNSUCCESSFUL = 'TYPO_CALLS_UNSUCCESSFUL'
    GRAB_ROBOCALL_HIGH_C_SCORE = 'GRAB_ROBOCALL_HIGH_SCORE'
    GRAB_ROBOCALL_MEDIUM_C_SCORE = 'GRAB_ROBOCALL_MEDIUM_SCORE'
    GRAB_ROBOCALL_LOW_C_SCORE = 'GRAB_ROBOCALL_LOW_SCORE'
    GRAB_INFO_CARD_AUTH_PENDING = 'GRAB_INFO_CARD_AUTH_PENDING'
    GRAB_INFO_CARD_AUTH_SUCCESS = 'GRAB_INFO_CARD_AUTH_SUCCESS'
    GRAB_INFO_CARD_AUTH_FAILED = 'GRAB_INFO_CARD_AUTH_FAILED'
    GRAB_INFO_CARD_AUTH_FAILED_4002 = 'GRAB_INFO_CARD_AUTH_FAILED_4002'
    GRAB_BANK_ACCOUNT_REJECTED = 'GRAB_BANK_ACCOUNT_REJECTED'
    GRAB_PHONE_NUMBER_CHECK_FAILED = 'GRAB_PHONE_NUMBER_CHECK_FAILED'
    GRAB_FAILED_3MAX_CREDITORS_CHECK = 'GRAB_FAILED_3MAX_CREDITORS_CHECK'
    GRAB_FAILED_3MAX_CREDITORS_BOTTOM_SHEET = 'GRAB_FAILED_3MAX_CREDITORS_BOTTOM_SHEET'
    GRAB_AJUKAN_PINJAMAN_LAGI = 'GRAB_AJUKAN_PINJAMAN_LAGI'
    GRAB_BELUM_BISA_MELANJUTKAN_APLIKASI = 'GRAB_BELUM_BISA_MELANJUTKAN_APLIKASI'
    CASHBACK_CLAIM = 'CASHBACK_CLAIM'

class TemplateCode(object):
    CASHBACK_EXPIRED_1 = 'CASHBACK_EXPIRED_1'
    CASHBACK_EXPIRED_2 = 'CASHBACK_EXPIRED_2'
    CASHBACK_EXPIRED_3 = 'CASHBACK_EXPIRED_3'
    CASHBACK_EXPIRED_4 = 'CASHBACK_EXPIRED_4'
    CARD_REFERRAL_SERBUCUANKITA = 'card_referral_serbucuankita'
    FRAUD_SOFT_REJECT = 'gotham_soft_reject'
    FRAUD_ATO_DEVICE_CHANGE_BLOCK = 'fraud_ato_device_change_block'
    IDFY_AUTODEBET_NOT_ACTIVE = 'idfy_autodebet_not_active'

    @classmethod
    def all_cashback_expired(cls):
        return [
            cls.CASHBACK_EXPIRED_1,
            cls.CASHBACK_EXPIRED_2,
            cls.CASHBACK_EXPIRED_3,
            cls.CASHBACK_EXPIRED_4,
        ]


class CommunicationTypeConst:
    INFORMATION = 'Information'
    PAYMENT_REMINDER = 'Payment Reminder'
    PARTNER_COMMUNICATION = 'Partner Communication'


INAPP_RATING_POPUP_DAYS = 3


class NexmoVoiceAction:
    TALK = 'talk'
    INPUT = 'input'
    RECORD = 'record'


class NexmoVoice:
    INDO = 'id-ID'
    MALE_STYLE = [2, 3]
    FEMALE_STYLE = [0, 1, 4]

    @classmethod
    def all_voice_styles(cls):
        return cls.MALE_STYLE + cls.FEMALE_STYLE


nexmo_voice_map = {
    NexmoVoice.INDO: {
        'male': NexmoVoice.FEMALE_STYLE,
        'female': NexmoVoice.MALE_STYLE
    }
}

id_to_en_gender_map = {
    'Wanita': 'female',
    'Pria': 'male'
}

autodebet_pn_dpds = (-5, -4, -3, -2, -1, 0)
autodebet_sms_dpds = (-7, -3, -1)


class PageType:
    """
    The available page that can be used for Push Notification.
    """
    CFS = "cfs"
    REFERRAL = "referral"
    AUTODEBET_BCA_WELCOME = "autodebet_bca_welcome"
    AUTODEBET_BRI_WELCOME = "autodebet_bri_welcome"
    JULO_SHOP = "julo_shop"
    OVO_TAGIHAN_PAGE = "ovo_tagihan_page"
    TARIK_DANA = "TarikDana"
    TARIK_DANA_NEW = "tarik_dana"
    KIRIM_DANA = "kirim_dana"
    PULSA_DATA = "pulsa_data"
    LISTRIK_PLN = "listrik_pln"
    BPJS_KESEHATAN = "bpjs_kesehatan"
    KARTU_PASCA_BAYAR = "kartu_pasca_bayar"
    PRODUCT_TRANSFER_SELF = "product_transfer_self"
    NAV_INAPP_PRODUCT_TRANSFER_OTHER = "nav_inapp_product_transfer_other"
    JULO_CARD_HOME_PAGE = "julo_card_home_page"
    CASHBACK = 'cashback'
    PDAM_HOME_PAGE = "pdam_home_page"
    JULO_CARD_TRANSACTION_COMPLETED = 'julo_card_transaction_completed'
    JULO_CARD_CHOOSE_TENOR = 'julo_card_choose_tenor'
    TRAIN_TICKET = 'train_ticket'
    EDUCATION = "education_spp"
    DANA_LINK = "dana_link"
    GOPAY_AUTODEBET = "gopay_autodebet"
    GOPAY_LINKING = 'gopay_linking'
    GOPAY_PAYMENT = 'gopay_payment'
    HOME = 'Home'
    E_WALLET = 'e-wallet'
    E_COMMERCE = 'e-commerce'
    IN_APP_PTP = 'in_app_ptp'
    TAGIHAN = 'tagihan'
    PROFILE = 'profile'
    HEALTHCARE_MAIN_PAGE = 'healthcare_main_page'
    TRANSACTION_STATUS = 'transaction_status'
    CHANGE_DATA_PRIVACY = 'change_data_privacy'
    CHECKOUT = 'checkout'
    CHANGE_PHONE_NUMBER = 'change_phone_number'
    JULO_FINANCING = 'julo_financing'
    QRIS_MAIN_PAGE = 'qris_main_page'
    BCA_AUTODEBET = 'bca_autodebet'
    BRI_AUTODEBET = 'bri_autodebet'
    BNI_AUTODEBET = 'bni_autodebet'
    MANDIRI_AUTODEBET = 'mandiri_autodebet'
    OVO_AUTODEBET = 'ovo_autodebet'
    REPAYMENT_CASBACK = 'repayment_cashback'

    # Loan Page
    LOAN = 'loan_activity'
    LOAN_1 = 'Loan'
    LOAN_2 = 'activity_loan'

    # Julo Turbo Related
    TURBO_ELIGIBILITY_OK = "julo_starter_eligbility_ok"
    TURBO_ELIGIBILITY_J1_OFFER = "julo_starter_eligbility_j1_offer"
    TURBO_STARTER_ELIGIBILITY_REJECTED = "julo_starter_eligbility_rejected"
    TURBO_SECOND_CHECK_OK = "julo_starter_second_check_ok"
    TURBO_SECOND_CHECK_REJECTED = "julo_starter_second_check_rejected"
    TURBO_SECOND_CHECK_FULL_DV = "julo_starter_second_check_ok_full_dv"
    TURBO_SECOND_CHECK_J1_OFFER = "julo_starter_second_check_j1_offer"
    TURBO_FULL_LIMIT = "julo_starter_full_limit"
    TURBO_DEEPLINK_UPGRADE_FORM = "deeplink_upgrade_form"
    TURBO_ADDITIONAL_FORM = "to_additional_form"

    # promo
    PROMO_ENTRY_PAGE = "promo_entry_page"
    UPLOAD_SALARY_SLIP = 'upload_salary_slip'
    UPLOAD_BANK_STATEMENT = 'upload_bank_statement'

    VIDEO_WEBVIEW = 'video_webview'
    AUTODEBET_ACTIVATION_DRAWER = 'autodebet_activation_drawer'
    AUTODEBET_IDFY = 'autodebet_idfy'

    # sell off related
    PROFILE = 'profile'

    LOYALTY_HOMEPAGE = 'loyalty_homepage'
    DANA_AUTODEBET = 'dana_autodebet'

    @classmethod
    def all_pages(cls):
        return {
            value
            for field_name, value in vars(cls).items()
            if (
                not field_name.startswith('_')
                and not callable(value)
                and isinstance(value, str)
            )
        }

    @classmethod
    def sell_off_white_list_pages(cls):
        return {cls.LOAN_1.lower(), cls.HOME.lower(), cls.PROFILE.lower()}


J1_PRODUCT_DEEP_LINK_MAPPING_TRANSACTION_METHOD = {
    PageType.TARIK_DANA_NEW: TransactionMethodCode.SELF,
    PageType.KIRIM_DANA: TransactionMethodCode.OTHER,
    PageType.PULSA_DATA: TransactionMethodCode.PULSA_N_PAKET_DATA,
    PageType.KARTU_PASCA_BAYAR: TransactionMethodCode.PASCA_BAYAR,
    PageType.E_WALLET: TransactionMethodCode.DOMPET_DIGITAL,
    PageType.LISTRIK_PLN: TransactionMethodCode.LISTRIK_PLN,
    PageType.BPJS_KESEHATAN: TransactionMethodCode.BPJS_KESEHATAN,
    PageType.E_COMMERCE: TransactionMethodCode.E_COMMERCE,
    PageType.TRAIN_TICKET: TransactionMethodCode.TRAIN_TICKET,
    PageType.PDAM_HOME_PAGE: TransactionMethodCode.PDAM,
    PageType.EDUCATION: TransactionMethodCode.EDUCATION,
    PageType.HEALTHCARE_MAIN_PAGE: TransactionMethodCode.HEALTHCARE,
    PageType.QRIS_MAIN_PAGE: TransactionMethodCode.QRIS_1,
}


class RobocallType(object):
    NEXMO_J1 = 'nexmo_j1'
    COOTEK_J1 = 'cootek_j1'
    COOTEK_JTURBO = 'cootek_jturbo'


class RedisKey(object):
    EXCELLENT_CUSTOMER_ACCOUNT_IDS_TEST_GROUP = \
        'streamlined_communication:excellent_customer_{}_account_ids_test_group'
    EXCELLENT_CUSTOMER_ACCOUNT_IDS_CONTROL_GROUP = \
        'streamlined_communication:excellent_customer_{}_account_ids_control_group'

    INFOBIP_VOICE_LIST = 'infobip:voice_list'
    STREAMLINE_LATE_FEE_EXPERIMENT = 'STREAMLINE_LATE_FEE_EXPERIMENT_{}_{}'
    STREAMLINE_CASHBACK_NEW_SCHEME_EXPERIMENT = 'STREAMLINE_CASHBACK_NEW_SCHEME_EXPERIMENT_{}_{}'
    STREAMLINE_SMS_AFTER_ROBOCALL_EXPERIMENT = 'STREAMLINE_SMS_AFTER_ROBOCALL_EXPERIMENT_{}_{}'

    EMAIL_UNSENT_MOENGAGE = 'EMAIL_UNSENT_MOENGAGE_STREAMLINED_ID_{}'


class ImageType(object):
    STREAMLINED_PN = 'streamlined_pn'
    STREAMLINED_PAYMENT_WIDGET_CONTENT = 'streamlined_payment_widget_content'
    STREAMLINED_PAYMENT_WIDGET_DESC = 'streamlined_payment_widget_desc'
    STREAMLINED_SLIK_NOTIFICATION_ICON = 'streamlined_slik_notification_icon'


class ExperimentConst(object):
    SMS_MINUS_7_TAKE_OUT_EXPERIMENT = 'sms_minus_7_take_out_experiment'


class SmsTspVendorConstants(object):
    TELKOMSEL = 'TELKOMSEL'
    XL = 'XL'
    AXIS = 'AXIS'
    INDOSAT_OOREDO = 'INDOSAT_OOREDO'
    HUTCHISON_TRI = 'HUTCHISON_TRI'
    SMARTFREN = 'SMARTFREN'
    OTHERS = 'OTHERS'

    CHOICES = (
        (TELKOMSEL, 'telkomsel'),
        (XL, 'xl'),
        (AXIS, 'axis'),
        (INDOSAT_OOREDO, 'indosat_ooredo'),
        (HUTCHISON_TRI, 'hutchison_tri'),
        (SMARTFREN, 'smartfren'),
        (OTHERS, 'others'),
    )

    NEXMO = '002'
    MONTY = '003'
    INFOBIP = '004'
    ALICLOUD = '005'

    NON_OTP_SMS_VENDOR_CHOICES = (
        (MONTY, 'monty'),
        (NEXMO, 'nexmo'),
        (ALICLOUD, 'alicloud'),
        (INFOBIP, 'infobip'),
    )

    VENDOR_MAP = {
        MONTY: 'send_sms_monty',
        NEXMO: 'send_sms_nexmo',
        ALICLOUD: 'send_sms_alicloud',
        INFOBIP: 'send_sms_infobip',
    }

    VENDOR_NAME_MAP = {
        MONTY: VendorConst.MONTY,
        NEXMO: VendorConst.NEXMO,
        ALICLOUD: VendorConst.ALICLOUD,
        INFOBIP: VendorConst.INFOBIP
    }


class InfobipVoice(object):
    """
    This class is to map infobip's text-to-speech voices due to VoiceCallRecord using voice_style_id
    to map voices. The property works as requirement for Nexmo vendor but doesn't work for Infobip
    without custom mapping since Infobip doesn't have ID for the voices.
    """
    voice_value_map = {
        20: {'name': 'Andika', 'gender': 'male'},
        21: {'name': 'Arif (beta)', 'gender': 'male'},
        22: {'name': 'Indah (beta)', 'gender': 'female'},
        23: {'name': 'Nurul (beta)', 'gender': 'female'},
        24: {'name': 'Reza (beta)', 'gender': 'male'},
    }
    default_voice = voice_value_map[20]

    voice_style_id_map = {
        'id': {
            'Pria': [20, 21, 24],
            'Wanita': [22, 23]
        }
    }


class NeoBannerConst:

    # destination when click "Lanjutkan isi formulir"
    # available in >= 8.15.0
    DESTINATION_FORM_OR_VIDEO = 'continue_form_or_video'
    TARGET_VERSION_FORM_OR_VIDEO = '8.15.0'


class NeoBannerStatusesConst:

    FORM_OR_VIDEO_CALL_STATUSES = '[100_CONTINUE_FILL_FORM]'


class PaymentWidgetTemplateCode:
    PG_minus1 = 'J1_due_date_widget_dpd_-1'
    PG_minus2 = 'J1_due_date_widget_dpd_-2'
    PG_minus3 = 'J1_due_date_widget_dpd_-3'
    PG_minus31 = 'J1_due_date_widget_dpd_-31'
    PG_2 = 'J1_due_date_widget_dpd_2'
    PG_3 = 'J1_due_date_widget_dpd_3'
    PG_4 = 'J1_due_date_widget_dpd_4'
    PG_5 = 'J1_due_date_widget_dpd_5'
    PG_6 = 'J1_due_date_widget_dpd_6'
    PG_7 = 'J1_due_date_widget_dpd_7'
    PG_8 = 'J1_due_date_widget_dpd_8'
    PG_9 = 'J1_due_date_widget_dpd_9'
    PG_10 = 'J1_due_date_widget_dpd_10'
    PG_11 = 'J1_due_date_widget_dpd_11-40'
    PG_41 = 'J1_due_date_widget_dpd_41-70'
    PG_71 = 'J1_due_date_widget_dpd_71-90'
    PG_91 = 'J1_due_date_widget_dpd_91'
    PG_1 = 'J1_due_date_widget_dpd_1'
    PG_0 = 'J1_due_date_widget_dpd_0'


class CeleryTaskLocker:
    STATUS = {
        'START': 'Start',
        'IN_PROGRESS': 'In Progress',
        'DONE': 'Done',
    }

    TIMEOUT = 1800


class StreamlinedCommCampaignConstants:
    class CampaignType:
        SMS = 'sms'

    class CampaignStatus:
        WAITING_FOR_APPROVAL = 'menunggu konfirmasi'
        ON_GOING = 'sedang berjalan'
        DONE = 'selesai'
        REJECTED = 'ditolak'
        FAILED = 'gagal'
        CANCELLED = 'dibatalkan'
        PARTIAL_SENT = 'terkirim sebagian'
        SENT = 'terkirim'

    status_mapping = {
        CampaignStatus.WAITING_FOR_APPROVAL: [CampaignStatus.WAITING_FOR_APPROVAL],
        CampaignStatus.ON_GOING: [CampaignStatus.ON_GOING],
        CampaignStatus.DONE: [
            CampaignStatus.REJECTED,
            CampaignStatus.FAILED,
            CampaignStatus.PARTIAL_SENT,
            CampaignStatus.DONE,
            CampaignStatus.CANCELLED,
            CampaignStatus.SENT,
        ],
    }

    class ScheduleMode:
        NOW = 'Sekarang'
        LATER = 'Nanti'
        REPEATED = 'Berulang'

    schedule_mode_mapping = {
        ScheduleMode.NOW: 'Now',
        ScheduleMode.LATER: 'Later',
        ScheduleMode.REPEATED: 'Repeated',
    }

    class TemplateCode:
        TEST_SMS = 'test_sms'

    class Action:
        REJECT = "reject"
        APPROVE = "approve"


class CommsUserSegmentConstants:
    class ChunkStatus:
        START = 0
        ON_GOING = 1
        FINISH = 2
        FAILED = 3

    class SegmentStatus:
        SUCCESS = 'success'
        FAILED = 'failed'
        PROCESSING = 'processing'


class SmsMapping:
    DEFAULT = 'sent_to_provider'

    STATUS = {
        'nexmo': {
            'DELIVERED': 'delivered',
        },
        'monty': {
            'DELIVERED': 'DELIVRD',
        },
        'infobip': {
            'DELIVERED': 'DELIVERED',
        },
        'alicloud': {
            'DELIVERED': 'DELIVERED',
            'FAILED': 'FAILED',
        },
    }


class NsqTopic:
    __VONAGE_OUTBOUND_CALL_DETAIL = 'communication_service_vonage_outbound_call_detail'
    __EMAIL_REACHABILITY = 'communication_service_email_reachability'
    __SMS_REACHABILITY = 'communication_service_sms_reachability'

    @classmethod
    def get_topic_name(cls, topic_name: str):
        """
        Add environment suffix to NSQ topic.
        Args:
            topic_name (str): topic name.
        """
        if settings.NSQ_ENVIRONMENT != 'production':
            renamed_topic_name = '{}_{}'.format(topic_name, settings.NSQ_ENVIRONMENT)
            return renamed_topic_name
        return topic_name

    @property
    def email_reachability_status(self):
        return self.get_topic_name(self.__EMAIL_REACHABILITY)

    @property
    def vonage_outbound_call_detail(self):
        return self.get_topic_name(self.__VONAGE_OUTBOUND_CALL_DETAIL)

    @property
    def sms_reachability_status(self):
        return self.get_topic_name(self.__SMS_REACHABILITY)

IMAGE_FOR_SLIK_NOTIFICATION = 'https://www.julo.co.id/sites/default/files/newsletter/ic-information-circle_0.png'


class StatusReapplyForIOS:

    # Need to replace buttont_action to reapply_form only for iOS
    STATUSES = ['106_REAPPLY', '136_REAPPLY']


class ListSpecificRuleStatus:
    """
    List status for Neo Banner for specific Status / Rule
    """

    STATUS_120_HSFBP = '[120_HSFBP]'
