from builtins import object


class GaDownloadBatchStatus(object):
    PENDING = 'pending'
    RETRIEVED = 'retrieved'
    PARSED = 'parsed'
    STORED = 'stored'
    FAILED = 'failed'


class GAEvent:
    APPLICATION_BYPASS = 'application_bypass'
    APPLICATION_MD = 'application_md'
    REFERRAL_CODE_USED = 'referral_code_used'
    X120 = 'x120'
    X190 = 'x190'

    CFS_MULAI_CONNECT_BANK = 'mulai_connect_bank'
    CFS_REFUSE_CONNECT_BANK = 'refuse_connect_bank'
    CFS_KLAIM_CONNECT_BANK = 'klaim_connect_bank'

    CFS_MULAI_CONNECT_BPJS = 'mulai_connect_bpjs'
    CFS_REFUSE_CONNECT_BPJS = 'refuse_connect_bpjs'
    CFS_KLAIM_CONNECT_BPJS = 'klaim_connect_bpjs'

    CFS_MULAI_BUKTI_TAGIHAN = 'mulai_bukti_tagihan'
    CFS_APPROVE_BUKTI_TAGIHAN = 'approve_bukti_tagihan'
    CFS_REFUSE_BUKTI_TAGIHAN = 'refuse_bukti_tagihan'
    CFS_KLAIM_BUKTI_TAGIHAN = 'klaim_bukti_tagihan'

    CFS_MULAI_BUKTI_GAJI = 'mulai_bukti_gaji'
    CFS_APPROVE_BUKTI_GAJI = 'approve_bukti_gaji'
    CFS_REFUSE_BUKTI_GAJI = 'refuse_bukti_gaji'
    CFS_KLAIM_BUKTI_GAJI = 'klaim_bukti_gaji'

    CFS_MULAI_BUKTI_MUTASI = 'mulai_bukti_mutasi'
    CFS_APPROVE_BUKTI_MUTASI = 'approve_bukti_mutasi'
    CFS_REFUSE_BUKTI_MUTASI = 'refuse_bukti_mutasi'
    CFS_KLAIM_BUKTI_MUTASI = 'klaim_bukti_mutasi'

    CFS_MULAI_PHONE_VERIFICATION = 'mulai_phone_verification'
    CFS_REFUSE_PHONE_VERIFICATION = 'refuse_phone_verification'
    CFS_KLAIM_PHONE_VERIFICATION = 'klaim_phone_verification'

    CFS_MULAI_OTHER_PHONE = 'mulai_other_phone'
    CFS_REFUSE_OTHER_PHONE = 'refuse_other_phone'
    CFS_KLAIM_OTHER_PHONE_VERIFICATION = 'klaim_other_phone_verification'

    CFS_MULAI_FAMILY_NUMBER = 'mulai_family_number'
    CFS_APPROVE_FAMILY_NUMBER = 'approve_family_number'
    CFS_REFUSE_FAMILY_NUMBER = 'refuse_family_number'
    CFS_KLAIM_FAMILY_NUMBER = 'klaim_family_number'

    CFS_MULAI_COMPANY_NUMBER = 'mulai_company_number'
    CFS_APPROVE_COMPANY_NUMBER = 'approve_company_number'
    CFS_REFUSE_COMPANY_NUMBER = 'refuse_company_number'
    CFS_KLAIM_COMPANY_NUMBER = 'klaim_company_number'

    CFS_MULAI_ADDRESS_VERIFICATION = "mulai_address_verification"
    CFS_REFUSE_ADDRESS_VERIFICATION = 'refuse_address_verification'
    CFS_KLAIM_ADDRESS_VERIFICATION = 'klaim_address_verification'

    CFS_MULAI_SHARE_SOCIAL_MEDIA = "mulai_share_social_media"
    CFS_REFUSE_SHARE_SOCIAL_MEDIA = 'refuse_share_social_media'
    CFS_KLAIM_SHARE_SOCIAL_MEDIA = 'klaim_share_social_media'

    CFS_MULAI_BCA_AUTODEBET = "mulai_bca_autodebet"

    X220 = 'x_220_backend'
    X250 = 'x_250_backend'

    X420 = 'x_420_backend'
    X421 = 'x_421_backend'
    X430 = 'x_430_backend'

    # for application with certain pgood
    APPLICATION_X105_PCT70 = 'x_105_pct70'
    APPLICATION_X105_PCT80 = 'x_105_pct80'
    APPLICATION_X105_PCT90 = 'x_105_pct90'
    APPLICATION_X190_PCT70 = 'x_190_pct70'
    APPLICATION_X190_PCT80 = 'x_190_pct80'
    APPLICATION_X190_PCT90 = 'x_190_pct90'
    APPLICATION_X100_DEVICE = 'x_100_device'
    APPLICATION_X105_BANK = 'x_105_bank'

    APPLICATION_X105_PCT80_MYCROFT_90 = '105_p80_mycroft90'
    APPLICATION_X105_PCT90_MYCROFT_90 = '105_p90_mycroft90'
    APPLICATION_X190_PCT80_MYCROFT_90 = '190_p80_mycroft90'
    APPLICATION_X190_PCT90_MYCROFT_90 = '190_p90_mycroft90'
