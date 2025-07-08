from __future__ import print_function
import logging
import sys
from pyexcel_xls import get_data

from django.core.management.base import BaseCommand
from juloserver.julo.models import Loan, Application
from juloserver.julo.statuses import LoanStatusCodes
logger = logging.getLogger(__name__)
logger.addHandler(logging.StreamHandler(sys.stdout))

class Command(BaseCommand):

    def add_arguments(self, parser):
        parser.add_argument('-f', '--file', type=str, help='Define file name')

    def handle(self, **options):
        path = options['file']
        try:
            extension = path.split('.')[-1]
            if extension in ['xls', 'xlsx']:
                count = 0
                excel_datas = get_data(path)
                for idx_sheet, sheet in enumerate(excel_datas):
                    for row, col in enumerate(excel_datas[sheet]):
                        if row > 10 and row < 17061:
                            try:
                                application_xid = col[1]
                                if application_xid:
                                    Loan.objects.filter(application__application_xid=application_xid).\
                                                    update(loan_status=LoanStatusCodes.SELL_OFF)
                            except Exception as e:
                                count = count + 1
                                if count == 1:
                                    print("Following datas were not updated")
                                print("{} == {}".format(row + 1, application_xid))
                                continue
                print("Loan status updated successfully")

            else:
                logger.error("could not open given file " + path)
                return

        except Exception as e:
            print(e)
