from __future__ import print_function
# !/usr/local/bin/python
# coding: latin-1
from builtins import str
import logging
import sys
from pyexcel_xls import get_data
import re
import xml.dom.minidom

from django.core.management.base import BaseCommand
from juloserver.julo.models import BlacklistCustomer
from juloserver.julo.utils import trim_name
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
                        if row > 1:
                            english_name = re.compile(u'[a-zA-Z-()#/@;:<>{}+=~|.!?,-??\u2018-\u2019\u201a-\u201e\u0027]')
                            if english_name.match(col[1].strip()):
                                fullname = col[1]
                                fullname_trim = trim_name(fullname)
                                source = col[0]
                                try:
                                    dob = col[2]
                                except Exception:
                                    dob = None
                                try:
                                    citizenship = col[3]
                                except Exception:
                                    citizenship = None
                                filter_ = dict(fullname_trim=fullname_trim.strip(),
                                               source=source,
                                               name=fullname.strip(),
                                               dob=dob,
                                               citizenship=citizenship)
                                blacklist_customer_count = BlacklistCustomer.objects.filter(**filter_).count()
                                if blacklist_customer_count > 0:
                                    continue
                                BlacklistCustomer.objects.create(**filter_)
                            else:
                                count = count + 1
                                if count == 1:
                                    print("Following datas were not inserted in db")
                                print (str(row) + '=' +col[1])
                print("Data uploading finished successfully")
            elif extension == 'xml':
                doc = xml.dom.minidom.parse(path)
                individuals = doc.getElementsByTagName("INDIVIDUAL")
                source = 'UN'
                for individual in individuals:

                    first_name = (individual.getElementsByTagName("FIRST_NAME")[0]).childNodes[0].data
                    second_name = (individual.getElementsByTagName("SECOND_NAME")[0]).childNodes[0].data
                    dob = individual.getElementsByTagName("INDIVIDUAL_DATE_OF_BIRTH")
                    place_of_birth = individual.getElementsByTagName("INDIVIDUAL_PLACE_OF_BIRTH")
                    citizenship = None
                    year_of_birth = None
                    for year in dob:
                        if year.getElementsByTagName("YEAR"):
                            year_of_birth = (year.getElementsByTagName("YEAR")[0]).childNodes[0].data

                    for country in place_of_birth:
                        if country.getElementsByTagName("COUNTRY"):
                            citizenship = (country.getElementsByTagName("COUNTRY")[0]).childNodes[0].data

                    name = first_name + " " + second_name
                    fullname_trim = trim_name(name)
                    filter_ = dict(fullname_trim=fullname_trim.strip(),
                                   source=source,
                                   name=name.strip(),
                                   dob=year_of_birth,
                                   citizenship=citizenship)
                    blacklist_customer_count = BlacklistCustomer.objects.filter(**filter_).count()
                    if blacklist_customer_count > 0:
                        continue
                    BlacklistCustomer.objects.create(**filter_)

                print("Data uploading finished successfully")

            else:
                logger.error("could not open given file " + path)
                return

        except Exception as e:
            print(e)
