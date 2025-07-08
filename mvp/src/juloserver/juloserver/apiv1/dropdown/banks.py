from __future__ import unicode_literals

from juloserver.julo.banks import BankManager

from .base import DropDownBase


class BankDropDown(DropDownBase):
    dropdown = "banks"
    version = 3.0
    file_name = "banks.json"

    # Please Always Upgrade Version if there is changes on data, DEPRECATED?
    def __init__(self):
        self.DATA = BankManager.get_bank_names()
