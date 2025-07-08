from builtins import object

from core.classes import ChoiceConstantBase


class JuloUserRoles(ChoiceConstantBase):
    ADMIN_FULL = 'admin_full'
    ADMIN_READ_ONLY = 'admin_read_only'
    BO_FULL = 'bo_full'
    BO_READ_ONLY = 'bo_read_only'
    BO_DATA_VERIFIER = 'bo_data_verifier'
    BO_CREDIT_ANALYST = 'bo_credit_analyst'
    BO_OUTBOUND_CALLER = 'bo_outbound_caller'
    BO_OUTBOUND_CALLER_3rd_PARTY = 'bo_outbond_caller_3rd_party'
    BO_FINANCE = 'bo_finance'
    BO_GENERAL_CS = 'bo_general_cs'
    PARTNER_FULL = 'partner_full'
    PARTNER_READ_ONLY = 'partner_read_only'
    DOCUMENT_VERIFIER = 'document_verifier'
    BO_SD_VERIFIER = 'bo_sd_verifier'
    COLLECTION_AGENT_1 = 'collection_agent_1'
    COLLECTION_AGENT_2 = 'collection_agent_2'
    COLLECTION_AGENT_2A = 'collection_agent_2a'
    COLLECTION_AGENT_2B = 'collection_agent_2b'
    COLLECTION_AGENT_3 = 'collection_agent_3'
    COLLECTION_AGENT_3A = 'collection_agent_3a'
    COLLECTION_AGENT_3B = 'collection_agent_3b'
    COLLECTION_AGENT_4 = 'collection_agent_4'
    COLLECTION_AGENT_5 = 'collection_agent_5'
    COLLECTION_AGENT_PARTNERSHIP_BL_2A = 'collection_agent_partnership_bl_2a'
    COLLECTION_AGENT_PARTNERSHIP_BL_2B = 'collection_agent_partnership_bl_2b'
    COLLECTION_AGENT_PARTNERSHIP_BL_3A = 'collection_agent_partnership_bl_3a'
    COLLECTION_AGENT_PARTNERSHIP_BL_3B = 'collection_agent_partnership_bl_3b'
    COLLECTION_AGENT_PARTNERSHIP_BL_4 = 'collection_agent_partnership_bl_4'
    COLLECTION_AGENT_PARTNERSHIP_BL_5 = 'collection_agent_partnership_bl_5'

    # Roles for new collection buckets
    COLLECTION_BUCKET_1 = 'collection_bucket_1'
    COLLECTION_BUCKET_2 = 'collection_bucket_2'
    COLLECTION_BUCKET_3 = 'collection_bucket_3'
    COLLECTION_BUCKET_4 = 'collection_bucket_4'
    COLLECTION_BUCKET_5 = 'collection_bucket_5'

    COLLECTION_SUPERVISOR = 'collection_supervisor'
    JULO_PARTNERS = 'julo_partners'
    ACTIVITY_DIALER = 'activity_dialer_upload'
    OPS_TEAM_LEADER = 'ops_team_leader'
    CHANGE_OF_REPAYMENT_CHANNEL = 'change_of_repayment_channel'
    CHANGE_OF_PAYMENT_VISIBILITY = 'change_of_payment_visibility'
    BUSINESS_DEVELOPMENT = 'business_development'
    PRODUCT_MANAGER = 'product_manager'
    CS_TEAM_LEADER = 'cs_team_leader'
    FRAUD_OPS = 'fraudops'
    FRAUD_COLLS = 'fraudcolls'
    OPS_REPAYMENT = 'ops_repayment'
    CCS_AGENT = 'ccs_agent'
    CS_ADMIN = "cs_admin"
    PHONE_DELETE_NUMBER_FEATURE_USER = "phone_delete_number_feature_user"
    AGENT_RETROFIX_HIGH_RISK_USER = "agent_retrofix_high_risk_user"
    COLLECTION_COURTESY_CALL = "collection_courtesy_call"
    IT_TEAM = 'it_team'
    SALES_OPS = 'sales_ops'
    JFinancingAdmin = 'j_financing_admin'
    J1_AGENT_ASSISTED_100 = 'j1_agent_assisted_100'

    # Collection Field
    COLLECTION_FIELD_AGENT = 'field_agent'

    # CRM Revamp
    CRM_REVAMP_TESTER = 'crm_revamp_tester'
    # cohort campaign automation
    COHORT_CAMPAIGN_EDITOR = 'cohort_campaign_editor'
    # New Collection Team
    COLLECTION_TEAM_LEADER = 'collection_team_leader'
    COLLECTION_AREA_COORDINATOR = 'collection_area_coordinator'

    @classmethod
    def ordering(cls, values):
        last_value = 'PARTNER_READ_ONLY'
        ordered_values = sorted(values)
        if last_value in ordered_values:
            ordered_values.remove(last_value)
            ordered_values.append(last_value)
        return ordered_values

    @classmethod
    def collection_roles(cls):
        return [
            cls.COLLECTION_AGENT_1,
            cls.COLLECTION_AGENT_2,
            cls.COLLECTION_AGENT_2A,
            cls.COLLECTION_AGENT_2B,
            cls.COLLECTION_AGENT_3,
            cls.COLLECTION_AGENT_3A,
            cls.COLLECTION_AGENT_3B,
            cls.COLLECTION_AGENT_4,
            cls.COLLECTION_AGENT_5,
        ]

    @classmethod
    def collection_bucket_roles(cls):
        return [
            cls.COLLECTION_BUCKET_1,
            cls.COLLECTION_BUCKET_2,
            cls.COLLECTION_BUCKET_3,
            cls.COLLECTION_BUCKET_4,
            cls.COLLECTION_BUCKET_5,
            cls.COLLECTION_COURTESY_CALL,
        ]


class CommonVariables(object):
    DEFAULT_COLOURS = [
        {'color': '#FDFF02', 'color_name': 'Yellow', 'content_color': '#FFFFFF'},
        {'color': '#FA9901', 'color_name': 'Orange-Yellow', 'content_color': '#FFFFFF'},
        {'color': '#F93D02', 'color_name': 'Orange', 'content_color': '#FFFFFF'},
        {'color': '#F93300', 'color_name': 'Red-Orange', 'content_color': '#FFFFFF'},
        {'color': '#CC0300', 'color_name': 'Red', 'content_color': '#FFFFFF'},
        {'color': '#9933CC', 'color_name': 'Violet-Red', 'content_color': '#FFFFFF'},
        {'color': '#663299', 'color_name': 'Violet', 'content_color': '#FFFFFF'},
        {'color': '#6600CC', 'color_name': 'Blue-Violet', 'content_color': '#FFFFFF'},
        {'color': '#153398', 'color_name': 'Blue', 'content_color': '#FFFFFF'},
        {'color': '#249999', 'color_name': 'Blue-Green', 'content_color': '#FFFFFF'},
        {'color': '#0F6600', 'color_name': 'Green', 'content_color': '#FFFFFF'},
        {'color': '#28CC00', 'color_name': 'Yellow-Green', 'content_color': '#FFFFFF'},
    ]


class BucketType(object):
    BUCKET_1 = 'bucket_1'
    BUCKET_2 = 'bucket_2'
    BUCKET_3 = 'bucket_3'
    BUCKET_4 = 'bucket_4'
    BUCKET_5 = 'bucket_5'


class RepaymentChannel(object):
    BCA = 'BCA'
    PERMATA = 'Permata'
    BRI = 'BRI'


class BucketCode(object):
    CASHBACK_REQUEST = '999'
    CASHBACK_PENDING = '998'
    CASHBACK_FAILED = '997'
    VERIFYING_OVERPAID = '996'

    @classmethod
    def cashback_crm_buckets(cls):
        return [
            cls.CASHBACK_REQUEST,
            cls.CASHBACK_PENDING,
            cls.CASHBACK_FAILED,
        ]
