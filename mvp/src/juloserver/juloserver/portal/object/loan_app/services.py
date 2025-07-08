from builtins import object
import collections 
import logging

from django.db import transaction

from juloserver.julo.models import ApplicationDataCheck, ApplicationField
from .statuses import Checker


logger = logging.getLogger(__name__)


def create_data_verification_checks(application, last_index = None):

    if last_index:
        data_checks = Checker[last_index:]
    else:
        data_checks = Checker

    with transaction.atomic():
        for check in data_checks:
            # data_checks_arg = check_item.__dict__.copy()
            # data_checks_arg['application'] = application
            # data_checks_arg['application_field'] = ApplicationField.objects.get_or_none(
            #                     pk=data_checks_arg['app_field_id'])
            # logger.debug(data_checks_arg)

            # data_check = ApplicationDataCheck.objects.create(**data_checks_arg)

            _application_field = ApplicationField.objects.filter(
                                pk=check.app_field_id)
            if _application_field.count()>0:
                _application_field = _application_field[0]
            else:
                _application_field = None
            data_check = ApplicationDataCheck.objects.create(
                application_id=application.id,
                automation=check.automation,
                prioritize=check.prioritize,
                sequence=check.sequence,
                data_to_check=check.data_to_check,
                description=check.description,
                check_type=check.check_type,
                application_field_id=_application_field.id if _application_field else None,
            )
            logger.info(
                {
                    'data_check': data_check.data_to_check,
                    'application': application,
                    'status': 'created',
                }
            )


class ImageListIndex(object):
    def __init__(self, arr_input):
        self.arr_input = arr_input
        self.dup = self.check_duplicate()

    def output(self):
        return self.refactor_list()

    def check_duplicate(self):
        x=set(self.arr_input)
        _dup=[]
        for c in x:
            if(self.arr_input.count(c)>1 and c!=''):
                _dup.append([c, 0])
        # print(_dup)
        return _dup

    def upd_index(self, key, index):
        y = self.dup
        loop_index = 0
        for x in self.dup:
            if x[0] == key:
                y[loop_index][1] = index
                break
            loop_index =+1
        return y

    def get_index(self, key):
        ret_index = 0
        for x in self.dup:
            if x[0] == key:
                ret_index = x[1]
                break
        return ret_index            

    def refactor_list(self):
        arr_output = []
        dup_str = [d[0] for d in self.dup]
        # print dup_str
        if (dup_str):
            for x in self.arr_input:
                # print x
                if x in dup_str:
                    type_index = self.get_index(x)
                    y = "%s_%d" % (x, type_index)
                    #update index
                    self.upd_index(x, (type_index+1))
                    arr_output.append(y)
                else:
                    arr_output.append(x)
        else:
            arr_output = self.arr_input
        return arr_output
