from builtins import object, range

from juloserver.email_delivery.constants import EmailStatusMapping

MAX_EVENT = 40
RETRY_SECONDS = 3600 * 3  # 3 hours
MAX_RETRY_COUNT = 3
DELAY_FOR_MOENGAGE_EVENTS = 30
MAX_LIMIT = 2000
MAX_RETRY = 3
MAX_RETRY_FOR_TIMEOUT = 5


DAYS_ON_STATUS = {
    100: [1,2,3,12],
    105: [1],
    131: [1],
    147: [1,2,3],
    190: [1,2,3],
}

ACCOUNT_PAYMENT_STATUS_CHANGE_EVENTS = [list(range(320,328)), list(range(310,314))]


class MoengageEventType(object):
    IS_CHURN_EXPERIMENT = 'is_churn_experiment'
    LOAN_STATUS_CHANGE = 'loan_status_reminder'
    APPLICATION_STATUS_CHANGE = 'application_status_reminder'
    ACCOUNT_STATUS_CHANGE = 'account_status_change'
    LOAN_PAYMENT_REMINDER = 'loan_payment_reminder'
    PAYMENT_REMINDER = 'payment_reminder'
    HI_SEASON_LOTTERY_REMINDER = 'hi_season_lottery_reminder'
    REALTIME_BASIS = 'realtime_basis'
    BE_PAYMENT_RECEIVED = 'BE_PAYMENT_RECEIVED'
    CUSTOMER_DAILY_UPDATE = 'customer_daily_update'
    PROMO_CODE_USAGE = 'promo_code_usage'
    IS_SALES_OPS_RPC = 'is_sales_ops_rpc'
    BALANCE_CONSOLIDATION = 'balance_consolidation'
    BALANCE_CONSOLIDATION_SUBMIT_FORM = 'balance_consolidation_submit_form_'
    CFS_AGENT_CHANGE_MISSION = 'cfs_agent_change_mission'
    JULO_STARTER_LIMIT_APPROVED = 'julo_starter_limit_approved'
    EARLY_LIMIT_RELEASE = 'early_limit_release'
    TYPO_CALLS_UNSUCCESSFUL = 'typo_calls_unsuccessful'
    IDFY_VERIFICATION_SUCCESS = 'idfy_verification_success'
    IDFY_COMPLETED_DATA = 'idfy_completed_data'
    CUSTOMER_REMINDER_VKYC = 'customer_reminder_vkyc'
    GRADUATION = 'is_graduated'
    DOWNGRADE = 'is_downgraded'
    REFERRAL_CASHBACK = 'get_referral_cashback'
    CUSTOMER_SUSPENDED = 'is_suspended'
    EMERGENCY_CONSENT_RECEIVED = 'emergency_consent_received'
    CUSTOMER_SEGMENTATION = 'customer_segmentation'
    ELIGIBLE_GOLDFISH = 'eligible_goldfish'
    LOYALTY_MISSION = 'loyalty_mission'
    LOYALTY_TOTAL_POINT = 'loyalty_total_point'
    JULO_FINANCING = 'julo_financing'
    QRIS_READ_SIGN_MASTER_AGREEMENT = 'qris_read_sign_master_agreement'

    # generating
    BEx190_NOT_YET_REFER = 'BEx190_not_yet_refer'
    BEx190_NOT_YET_REFER_JULOVER = 'BEx190_not_yet_refer_julover'
    BEx220_GET_REFERRER = 'BEx220_get_referrer'
    BEX220_GET_REFEREE = 'BEx220_get_referee'
    AUTODEBET_REQUEST_OTP_TRANSACTION = 'autodebet_request_otp_transaction'
    ATTRIBUTE_FOR_COLLECTION_TAILOR = 'attribute_for_collection_tailor'
    AUTODEBIT_FAILED_DEDUCTION = 'BE_AUTODEBET_FAILED_DEDUCTION'
    FRAUD_ATO_DEVICE_CHANGE = 'fraud_ato_device_change_block'
    BEx220_CHANNELING_LOAN = 'BEx220_channeling_loan'
    USERS_ATTRIBUTE_FOR_LATE_FEE_EXPERIMENT = 'users_attribute_for_late_fee_experiment'
    USERS_ATTRIBUTE_FOR_CASHBACK_NEW_SCHEME_EXPERIMENT = (
        'users_attribute_for_cashback_new_scheme_experiment'
    )
    AUTODEBET_DISABLE_TURNED_ON = 'autodebet_disable_turned_on'
    AUTODEBET_DISABLE_TURNED_OFF = 'autodebet_disable_turned_off'
    BEx220_ACTIVE_JULO_CARE = 'BEx220_active_julo_care'
    ACTIVATED_AUTODEBET = 'be_autodebet_activated'
    ACTIVE_PLATFORMS = 'active_platforms'
    GTL_INSIDE = 'gtl_inside'
    MAYBE_GTL_INSIDE = 'maybe_gtl_inside'
    GTL_OUTSIDE = 'gtl_outside'
    BE_ADBRI_EXP = 'be_adbri_exp'
    LOAN_TRANSACTION_STATUS = 'loan_transaction_status'
    CASHBACK_INJECTION_FOR_PROMO = 'cashback_injection_for_promo_'
    IS_SALES_OPS_RPC_PDS = 'is_sales_ops_rpc_pds'
    JFINANCING_TRANSACTION = 'j_financing_transaction'
    JFINANCING_DELIVERY = 'j_financing_delivery'
    JFINANCING_COMPLETED = 'j_financing_completed'
    IS_AGENT_ASSISTED_SUBMISSION = 'is_agent_assisted_submission'
    IS_BALANCE_CONSOLIDATION_PUNISHMENT = 'is_balance_consolidation_punishment'
    BEx220_CASHBACK_DELAY_DISBURSEMENT = 'BEx220_cashback_delay_disbursement'
    QRIS_AMAR_REGISTRATION_STATUS = 'qris_amar_registration_status'
    ACTIVATED_ONEKLIK = 'be_activated_oneklik'
    QRIS_LINKAGE_STATUS = 'qris_linkage_status'
    SKRTP_REGENERATION = 'skrtp_regeneration'
    RISK_SEGMENT_ATTRIBUTE_UPDATE = 'risk_segment_attribute_update'


class MoengageLoanStatusEventType(object):
    STATUS_210 = 'BEx210'
    STATUS_211 = 'BEx211'
    STATUS_212 = 'BEx212'
    STATUS_213 = 'BEx213'
    STATUS_216 = 'BEx216'
    STATUS_217 = 'BEx217'
    STATUS_218 = 'BEx218'
    STATUS_219 = 'BEx219'
    STATUS_220 = 'BEx220'
    STATUS_230 = 'BEx230'
    STATUS_231 = 'BEx231'
    STATUS_232 = 'BEx232'
    STATUS_233 = 'BEx233'
    STATUS_234 = 'BEx234'
    STATUS_235 = 'BEx235'
    STATUS_236 = 'BEx236'
    STATUS_237 = 'BEx237'
    STATUS_240 = 'BEx240'
    STATUS_250 = 'BEx250'
    STATUS_215 = 'BEx215'


class MoengageAccountStatusEventType(object):
    STATUS_420 = 'BEx420'
    STATUS_450 = 'BEx450'


class MoengageJuloCardStatusEventType(object):
    STATUS_510 = 'BEx510'
    STATUS_530 = 'BEx530'
    STATUS_540 = 'BEx540'
    STATUS_580 = 'BEx580'

class MoengageTaskStatus(object):
    PENDING = 'pending'
    SUCCESS = 'success'
    FAILURE = 'fail'


PnNotificationTypes = {
    'Notification Received Android': 'received',
    'Notification Clicked Android': 'clicked',
    'SMART_TRIGGER_CAMPAIGN_TYPE': 'SMART_TRIGGER'
}


EmailStatusType = {
    'Email Sent': 'sent',
    'Email Bounced': 'bounced',
    'Email Soft Bounced': 'bounced',
    'Email Opened': 'open',
    'Email Clicked': 'clicked',
    'Email Unsubscribed': 'unsubscribed'
}


SmsStatusType = {
    'SMS Sent': 'sent'
}


InAppStatusType = {
    'Mobile In-App Shown': 'shown',
    'Mobile In-App Clicked': 'clicked',
    'Mobile In-App Closed': 'closed'
}


PnNotificationStreams = {
    'NOTIFICATION_RECEIVED_MOE': 'received',
    'NOTIFICATION_CLICKED_MOE': 'clicked',
}


SmsStreamsStatus = {
    'SMS_SENT': 'sent'
}


InAppStreamsStatus = {
    'MOE_IN_APP_SHOWN': 'shown',
    'MOE_IN_APP_CLICKED': 'clicked',
    'MOE_IN_APP_DISMISSED': 'closed',
    'MOE_IN_APP_AUTO_DISMISS': 'auto_dismissed'
}


InstallStreamsStatus = {
    'INSTALL': 'install',
    'Device Uninstall': 'uninstall'
}

OnsiteMessagingStreamsStatus = {
    'MOE_ONSITE_MESSAGE_SHOWN': 'shown',
    'MOE_ONSITE_MESSAGE_CLICKED': 'clicked',
    'MOE_ONSITE_MESSAGE_DISMISSED': 'dismissed',
}

OnsiteMessagingStreamKeyMapping = {
    'USER_ATTRIBUTE_USER_FIRST_NAME': 'first_name',
    'USER_ATTRIBUTE_USER_EMAIL': 'email',
    'USER_ATTRIBUTE_USER_MOBILE': 'phone_number'
}

INHOUSE = 'inhouse'
UNSENT_MOENGAGE = 'unsent moengage'
UNSENT_MOENGAGE_EXPERIMENT = 'unsent moengage experiment'


class UpdateFields:
    CASHBACK = 'cashback'
