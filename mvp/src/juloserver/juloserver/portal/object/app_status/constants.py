from builtins import object
from juloserver.julo.statuses import (ApplicationStatusCodes, JuloOneCodes)


class AgentUpdateAppSettings(object):
    RESTRICTED_STATUSES = [
        ApplicationStatusCodes.APPLICANT_CALLS_SUCCESSFUL, # 130
    ]


class FraudStatusMove(object):
    STATUS_420 = {
        JuloOneCodes.ACTIVE: "Account reactivated", 
        JuloOneCodes.FRAUD_REPORTED: "Pengaduan penipuan"
        }

    STATUS_440 = {
        JuloOneCodes.FRAUD_REPORTED: "Pengaduan penipuan",
        '': "Pengambilalihan Akun",
        JuloOneCodes.APPLICATION_OR_FRIENDLY_FRAUD: 'Application/friendly fraud',
        JuloOneCodes.SCAM_VICTIM: "Social engineering",
        JuloOneCodes.ACTIVE_IN_GRACE: "Account in grace period",
        JuloOneCodes.SUSPENDED: "Account suspended",
        JuloOneCodes.ACTIVE: "Account reactivated", 
        }

    STATUS_441 = {
        JuloOneCodes.APPLICATION_OR_FRIENDLY_FRAUD: 'Application/friendly fraud',
        JuloOneCodes.TERMINATED: "Account closed"
        }
    
    STATUS_442 = {
        JuloOneCodes.SCAM_VICTIM: "Social engineering",
        JuloOneCodes.ACTIVE: "Account reactivated", 
        JuloOneCodes.TERMINATED: "Account closed"
        }    
    STATUS_421 = {
        JuloOneCodes.ACTIVE_IN_GRACE: "Account in grace period", 
        JuloOneCodes.FRAUD_REPORTED: "Pengaduan penipuan"
        }
    STATUS_430 = {
        JuloOneCodes.SUSPENDED: "Account suspended", 
        JuloOneCodes.FRAUD_REPORTED: "Pengaduan penipuan"
        }


class AccountStatusMove(object):
    REASONS = {
        JuloOneCodes.ACTIVE: "Account reactivated",
        JuloOneCodes.TERMINATED: "Account closed",
        JuloOneCodes.FRAUD_REPORTED: "Reported fraud",
        JuloOneCodes.APPLICATION_OR_FRIENDLY_FRAUD: "Application/friendly fraud",
        JuloOneCodes.SCAM_VICTIM: "Social engineering",
        JuloOneCodes.ACTIVE_IN_GRACE: "Account in grace period",
        JuloOneCodes.SUSPENDED: "Account suspended",
        }

    MAX_SET_LIMIT = 500000


class JuloStarterFields:
    REQUIRE_FIELDS = [
        "fullname",
        "dob",
        "gender",
        "mobile_phone_1",
        "address_street_num",
        "address_provinsi",
        "address_kabupaten",
        "address_kecamatan",
        "address_kelurahan",
        "address_kodepos",
        "referral_code",
        "onboarding_id",
        "bank_name",
        "bank_account_number",
        "device",
    ]
    EXTRA_FIELDS = [
        "job_type",
        "job_industry",
        "job_description",
        "company_name",
        "payday",
        "marital_status",
        "spouse_name",
        "spouse_mobile_phone",
        "close_kin_name",
        "close_kin_mobile_phone",
        "kin_relationship",
        "kin_name",
        "kin_mobile_phone",
    ]
    ALL_FIELDS = REQUIRE_FIELDS + EXTRA_FIELDS
