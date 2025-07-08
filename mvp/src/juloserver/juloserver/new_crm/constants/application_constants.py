from binhex import FInfo
from builtins import object

class CRMAppConstants(object):
    # Application Details Tabs
    DVC = 'dvc'
    SD = 'sd'
    FIN = 'fin'
    SECURITY = 'security'
    ST = 'st'
    NAME_BANK_VALIDATION = 'name_bank_validation'

    list_skiptrace_status = (121, 122, 1220, 123, 124, 1240,
                             125, 127, 130, 131, 132, 138,
                             1380, 141, 144, 172, 180)

    @classmethod
    def app_details_tabs(cls):
        return [
            cls.DVC,
            cls.SD,
            cls.FIN,
            cls.SECURITY,
            cls.ST,
            cls.NAME_BANK_VALIDATION
        ]
