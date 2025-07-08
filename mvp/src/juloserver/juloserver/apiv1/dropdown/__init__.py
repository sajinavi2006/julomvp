from .addresses import AddressDropDown
from .banks import BankDropDown
from .birthplace import BirthplaceDropDown
from .colleges import CollegeDropDown
from .companies import CompanyDropDown
from .jobs import JobDropDown, JobDropDownV2
from .loan_purposes import LoanPurposeDropDown
from .majors import MajorDropDown
from .marketing_sources import MarketingSourceDropDown
from .uker_bri import UkerBriDropDown


def write_dropdowns_to_buffer(buf, dropdown_versions, product_line_code, api_version=None):
    sub_dropdowns = [
        AddressDropDown(),
        BankDropDown(),
        CollegeDropDown(),
        CompanyDropDown(),
        JobDropDownV2() if api_version == 'v2' else JobDropDown(),
        LoanPurposeDropDown(product_line_code),
        MajorDropDown(),
        MarketingSourceDropDown(),
        UkerBriDropDown(),
        BirthplaceDropDown(),
    ]
    for dropdown, version in list(dropdown_versions.items()):

        force_write = False
        if dropdown == JobDropDown().dropdown:
            force_write = True

        for sub_dropdown in sub_dropdowns:
            sub_dropdown.write(buf, dropdown, version, product_line_code, force_write)
