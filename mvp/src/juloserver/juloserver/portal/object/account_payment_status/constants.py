from builtins import object

class SearchCategory(object):
    APPLICATION_ID = 'Application ID'
    MOBILE_NUMBER = 'Nomor Handphone'
    FULLNAME = 'Nama Lengkap'
    EMAIL = 'Email'
    ACCOUNT_PAYMENT_ID = 'Account Payment ID'
    ACCOUNT_ID = 'Account ID'
    VA_NUMBER = 'VA Number'
    PRODUCT_LINE = 'Product Line'
    OTHER_PHONE_NUMBER = 'Other Phone Number'
    CUSTOMER_DPD_STATUS = 'Account Payment DPD'
    
    ALL = [APPLICATION_ID, MOBILE_NUMBER, FULLNAME, EMAIL,
           ACCOUNT_PAYMENT_ID, ACCOUNT_ID, VA_NUMBER, OTHER_PHONE_NUMBER,PRODUCT_LINE,CUSTOMER_DPD_STATUS]
    ACCOUNT_PAGE = [APPLICATION_ID, MOBILE_NUMBER, FULLNAME, EMAIL,
           ACCOUNT_ID, OTHER_PHONE_NUMBER]


class SpecialConditions(object):
    is_5_days_unreachable = {'flag': 'is_5_days_unreachable', 'name': '5 days in a row not answered'}
    is_broken_ptp_plus_1 = {'flag': 'is_broken_ptp_plus_1', 'name': 'Broken ptp+1'}
    ALL = [is_5_days_unreachable, is_broken_ptp_plus_1]
