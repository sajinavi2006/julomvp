from builtins import object


class SMFChannelingConst(object):
    PARTNER_CODE = "JTF"
    COMPANYID = "JTFSMF001"
    DATE_STRING_FORMAT = "%Y-%m-%d %H:%M:%S"
    LENDER_NAME = 'smf_channeling'

    NOT_OK_STATUS = "not ok"
    OK_STATUS = "ok"

    SUCCESS_STATUS_CODE = "00"
    DATA_FAILED_STATUS_CODE = "10"
    SCHEDULE_FAILED_STATUS_CODE = "20"
    BANK_FAILED_STATUS_CODE = "30"
    ONPROGRESS_STATUS_CODE = "40"
    UNDEFINED_STATUS_CODE = "99"
    FAILED_STATUS_CODES = (
        DATA_FAILED_STATUS_CODE,
        SCHEDULE_FAILED_STATUS_CODE,
        BANK_FAILED_STATUS_CODE,
    )

    EFFECTIVERATE = "33"

    SMF_CUSTOMER_DATA_KEY = {
        "zipcode": "custzip",
        "birthplace": "birthplace",
        "fullname": "fullname",
        "custname": "custname",
        "phoneno": "phoneno",
        "mobileno": "mobileno",
        "birthdate": "birthdate",
        "mothername": "mmn",
    }
    SMF_SANITIZE_DATA = [
        "fullname",
        "custname",
        "phoneno",
        "mobileno",
        "mothername",
        "birthplace",
    ]


class SMFMaritalStatusConst(object):
    LIST = {
        'Lajang': 1,
        'Menikah': 2,
        'Cerai': 3,
        'Janda / duda': 3,
    }


class SMFEducationConst(object):
    LIST = {
        "TK": "00",
        "SD": "00",
        "SLTP": "00",
        "SLTA": "00",
        "Diploma": "99",
        "S1": "04",
        "S2": "05",
        "S3": "06",
    }


class SMFDataField:
    @classmethod
    def customer_address(cls):
        return [
            "custaddress",
            "custkel",
            "custkec",
            "custcity",
            "custprov",
            "custzip",
            "custaddresshome",
            "custkelhome",
            "custkechome",
            "custcityhome",
            "custprovhome",
            "custziphome",
        ]


SMF_INVOICE_ICON_LINK = "https://statics.julo.co.id/smf/alterra-bills-01.png"
