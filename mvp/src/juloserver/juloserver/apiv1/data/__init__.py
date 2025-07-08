from builtins import object

from juloserver.julo.banks import BANKS_VERSION, BankManager
from juloserver.julo.models import Bank

from .addresses import get_addresses_dropdown_by_product_line
from .colleges import COLLEGE_LIST, COLLEGE_VERSION
from .companies import COMPANY_LIST, COMPANY_VERSION
from .jobs import JOBS_LIST, JOBS_VERSION
from .loan_purposes import get_loan_purpose_dropdown_by_product_line
from .majors import MAJORS_LIST, MAJORS_VERSION
from .marketing_source import MARKETING_SOURCE_LIST, MARKETING_SOURCE_VERSION


class DropDownDataType(object):
    COLLEGE = 1
    JOB = 2
    BANK = 3
    MAJOR = 4
    ADDRESS = 5
    MARKETING_SOURCE = 6
    COMPANY = 7


class DropDownData(DropDownDataType):
    """
    class for JSON object response data
    """

    def __init__(self, data_type):
        self.data_type = data_type
        self.response = None

    def select_data(self):
        return self._select_data()

    def _select_data(self):
        list_selected = None
        if self.data_type == self.COLLEGE:
            list_selected = COLLEGE_LIST
        elif self.data_type == self.JOB:
            list_selected = JOBS_LIST
        elif self.data_type == self.BANK:
            list_selected = list(Bank.objects.regular_bank().values_list('bank_name', flat=True))
        elif self.data_type == self.MAJOR:
            list_selected = MAJORS_LIST
        elif self.data_type == self.MARKETING_SOURCE:
            list_selected = MARKETING_SOURCE_LIST
        elif self.data_type == self.COMPANY:
            list_selected = COMPANY_LIST
        return list_selected

    def _select_version(self):
        version_selected = None
        if self.data_type == self.COLLEGE:
            version_selected = COLLEGE_VERSION
        elif self.data_type == self.JOB:
            version_selected = JOBS_VERSION
        elif self.data_type == self.BANK:
            version_selected = BANKS_VERSION
        elif self.data_type == self.MAJOR:
            version_selected = MAJORS_VERSION
        elif self.data_type == self.MARKETING_SOURCE:
            version_selected = MARKETING_SOURCE_VERSION
        elif self.data_type == self.COMPANY:
            version_selected = COMPANY_VERSION
        return version_selected

    def get_data_dict(self):
        """
        get json data from specific list base on data_type
        """
        data_selected = self._select_data()
        self.response = {
            "count": len(data_selected) if data_selected else 0,
            "next": None,
            "previous": None,
            "results": data_selected,
        }
        return self.response

    def get_version(self):
        return self._select_version()

    def get_version_json(self):
        return {'version': self.get_version()}

    def count(self):
        return self.get_data_dict()['count']


def get_all_versions():
    data = {
        'colleges': {
            'version': COLLEGE_VERSION,
            'count': len(COLLEGE_LIST) if COLLEGE_LIST else 0,
        },
        'jobs': {
            'version': JOBS_VERSION,
            'count': len(JOBS_LIST) if JOBS_LIST else 0,
        },
        'banks': {
            'version': BANKS_VERSION,
            'count': len(BankManager.get_bank_names()) if BankManager.get_bank_names() else 0,
        },
        'majors': {
            'version': MAJORS_VERSION,
            'count': len(MAJORS_LIST) if MAJORS_LIST else 0,
        },
        'marketingsources': {
            'version': MARKETING_SOURCE_VERSION,
            'count': len(MARKETING_SOURCE_LIST) if MARKETING_SOURCE_LIST else 0,
        },
        'companies': {
            'version': COMPANY_VERSION,
            'count': len(COMPANY_LIST) if COMPANY_LIST else 0,
        },
    }
    return data


def get_dropdown_versions_by_product_line(product_line_code):
    data = get_all_versions()
    loan_purpose_dropdown = get_loan_purpose_dropdown_by_product_line(product_line_code)
    data['loan_purposes'] = {
        'version': loan_purpose_dropdown['version'],
        'count': len(loan_purpose_dropdown['results']),
    }
    addresses_dropdown = get_addresses_dropdown_by_product_line(product_line_code)
    data['addresses'] = {
        'version': addresses_dropdown['version'],
        'count': len(addresses_dropdown['results']),
    }
    return data
