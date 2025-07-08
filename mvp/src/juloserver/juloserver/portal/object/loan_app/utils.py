#!/usr/bin/python
import os, shutil
from itertools import chain
from operator import attrgetter
from django.db.models import F, Value, CharField

from juloserver.loan.models import PaidLetterNote
from juloserver.julo.models import ApplicationNote


def remove_folder(path):
    # check if folder exists
    if os.path.exists(path):
        # remove if exists
        shutil.rmtree(path)
        return "Success"
    return "%s not successfully deleted" % path


def remove_file(path_file):
    ## if file exists, delete it ##
    if os.path.isfile(path_file):
        os.remove(path_file)
        return "Delete file success"
    else:    
        ## Show an error ##
        return "Error: %s file not found" % (path_file)


def get_list_history_all(app_object):
    app_histories = app_object.applicationhistory_set.all().annotate(
        type_data=Value('Status Change', output_field=CharField()))
    app_notes = ApplicationNote.objects.filter(application_id=app_object.id).annotate(
        type_data=Value('Notes', output_field=CharField()))
    account_histories = []
    paid_letter_histories = []
    account_notes = []
    if app_object.account:
        account = app_object.account
        account_histories = account.accountstatushistory_set.all().select_related('fraudnote').\
            annotate(type_data=Value('Status Change', output_field=CharField()))
        account_notes = account.accountnote_set.all().annotate(type_date=Value('Account Notes', output_field=CharField()))
        paid_loans = account.get_all_paid_off_loan()
        if paid_loans:
            paid_letter_histories = PaidLetterNote.objects.filter(loan__in=paid_loans).annotate(
                type_data=Value('paid_letter_history', output_field=CharField())
            )


    return sorted(
        chain(app_histories, app_notes, account_histories, account_notes, paid_letter_histories),
        key=lambda instance: instance.cdate, reverse=True)

def get_list_history(app_object):
    app_histories = app_object.applicationhistory_set.all().annotate(
        type_data=Value('Status Change', output_field=CharField()))
    app_notes = ApplicationNote.objects.filter(application_id=app_object.id).annotate(
        type_data=Value('Notes', output_field=CharField()))

    return sorted(
        chain(app_histories, app_notes),
        key=lambda instance: instance.cdate, reverse=True)

def get_app_detail_list_history(app_object):
    app_field_changes = app_object.applicationfieldchange_set.all().annotate(
        type_data=Value('App Detail Change', output_field=CharField()))

    return sorted(app_field_changes, key=lambda instance: instance.cdate, reverse=True)
