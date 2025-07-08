import os, shutil
import logging
import re

from itertools import chain
from operator import attrgetter
from django.db import transaction
from django.db.models import Value, CharField
from django.db.utils import IntegrityError
from juloserver.paylater.models import StatementLock, StatementLockHistory
from app_status.functions import role_allowed

logger = logging.getLogger(__name__)


def statement_parse_pass_due(str_pass_due):
    """
        To determine which bucket to show bassed on request parameter
    """
    str_result = ''
    str_title = ''

    if str_pass_due == 'collection_supervisor_bl_duetoday' or \
            str_pass_due == 'collection_agent_bl_duetoday':
                str_result = 0
                str_title = 'T-0'
    elif str_pass_due == 'collection_supervisor_bl_1to5' or \
            str_pass_due == 'collection_agent_bl_1to5':
                str_result = 15
                str_title = 'T +1 to T +5'
    elif str_pass_due == 'collection_supervisor_bl_6to14'or \
            str_pass_due == 'collection_agent_bl_6to14':
                str_result = 614
                str_title = 'T +6 to T +14'
    elif str_pass_due == 'collection_supervisor_bl_15to29' or \
            str_pass_due == 'collection_agent_bl_15to29':
                str_result = 1529
                str_title = 'T +5 to T +29'
    elif str_pass_due == 'collection_supervisor_bl_30to44' or \
            str_pass_due == 'collection_agent_bl_30to44':
                str_result = 3044
                str_title = 'T +30 to T +44'
    elif str_pass_due == 'collection_supervisor_bl_45to59' or \
            str_pass_due == 'collection_agent_bl_45to59':
                str_result = 4559
                str_title = 'T +45 to T +59'
    elif str_pass_due == 'collection_supervisor_bl_60to89' or \
            str_pass_due == 'collection_agent_bl_60to89':
                str_result = 6089
                str_title = 'T +60 to T +89'
    elif str_pass_due == 'collection_supervisor_bl_90plus' or \
            str_pass_due == 'collection_agent_bl_90plus':
                str_result = 9000
                str_title = 'T-90+'
    elif str_pass_due == 'all':
        str_result = 200
        str_title = 'bl-all'

    try:
        pass_due_int = int(str_result)
    except Exception as e:
        logger.info({
                'statement_parse_pass_due': str_result,
                'error': 'converting into int',
                'e': e
                })

        return None

    return pass_due_int, str_title


def lock_statement(user, statement):
    with transaction.atomic():
        try:
            statement_lock = StatementLock.objects.create(statement=statement,
                                                          agent=user,
                                                          is_locked=True)
        except IntegrityError:
            return False

        if statement_lock:
            statement_lock_history = StatementLockHistory.objects.create(
                                        statement=statement,
                                        agent=user,
                                        is_locked=True
            )

            if statement_lock_history:
                return True
            else:
                return False
        else:
            return False


def unlock_statement(user, statement):
    statement_to_unlock = StatementLock.objects.get_or_none(statement=statement)
    if not statement_to_unlock:
        return True

    if statement_to_unlock.is_locked and (statement_to_unlock.agent == user or role_allowed(user, ['admin_unlocker'])):
        with transaction.atomic():
            try:
                StatementLock.objects.filter(statement=statement).delete()
            except IntegrityError:
                return False

        StatementLock.objects.filter(statement=statement).delete()
        StatementLockHistory.objects.create(
            statement=statement,
            agent=user,
            is_locked=False
        )

        return True
    else:
        return False
