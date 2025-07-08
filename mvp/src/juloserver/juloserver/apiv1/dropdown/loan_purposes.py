from __future__ import unicode_literals

import json

from ...julo.models import ProductLine
from .base import DropDownBase


class LoanPurposeDropDown(DropDownBase, object):
    dropdown = "loan_purposes"
    version = 2
    file_name = "loan_purposes.json"

    def __init__(self, product_line_code):
        product = ProductLine.objects.get_or_none(pk=product_line_code)
        loan_purposes = product.loan_purposes.all()
        self.version = int("".join(loan_purposes.last().version.split(".")))
        super(LoanPurposeDropDown, self).__init__()

    def _get_data(self, product_line_code):
        product = ProductLine.objects.get_or_none(pk=product_line_code)
        if product:
            loan_purposes = product.loan_purposes.all().order_by('id')
            purposes = list([x.purpose for x in loan_purposes])
            data = {
                'version': self.version,
                'data': purposes,
            }
            return json.dumps(data)
        else:
            return {}
