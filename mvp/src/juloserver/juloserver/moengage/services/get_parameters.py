import logging
import time
from datetime import datetime, timedelta
from django.db import transaction
from celery import task
from juloserver.application_flow.services import JuloOneService
from juloserver.julo.models import CreditScore
from juloserver.julo.services2.high_score import feature_high_score_full_bypass


def get_credit_score_type(application):
    credit_score = CreditScore.objects.filter(application_id=application.id).last()
    if not credit_score:
        return ""
    high_score = feature_high_score_full_bypass(application)
    if high_score:
        return "High"
    elif JuloOneService.is_c_score(application):
        return "Low C"
    elif JuloOneService.is_high_c_score(application):
        return "High C"
    else:
        return "Medium"


def get_application_history_cdate(application, status_new=None):
    if status_new:
        application_history = application.applicationhistory_set.filter(status_new=status_new)
        if application_history:
            return (application_history.last().cdate).strftime("%d/%m/%Y %H:%M:%S")
    else:
        application_history = application.applicationhistory_set.filter(
            status_new=application.status)

        if application_history:
            return (application_history.last().cdate).strftime("%Y-%m-%d %H:%M:%S")

    return None
