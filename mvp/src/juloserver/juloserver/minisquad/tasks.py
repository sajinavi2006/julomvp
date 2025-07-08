import io
import os
import csv
import base64
import logging
import tempfile

from builtins import str

from itertools import chain

import requests
from cacheops import invalidate_obj
from dateutil.relativedelta import relativedelta
from datetime import timedelta, datetime

from django.utils import timezone
from django.db.models import F, Q, Count, Case, When, IntegerField, Min, Max
from celery import task

from typing import List

from juloserver.minisquad.services import (
    get_payment_details_for_calling,
    upload_payment_details,
    upload_ptp_agent_level_data,
    unassign_bucket2_payment,
    unassign_bucket3_payment,
    unassign_bucket4_payment,
    exclude_payment_from_daily_upload,
    record_centerix_log,
    send_slack_message_centrix_failure,
    get_caller_experiment_setting,
    filter_loan_id_based_on_experiment_settings,
    record_vendor_experiment_data,
    insert_col_history_data_based_on_call_result,
    is_eligible_for_in_app_callback,
)
from .models import (
    CollectionHistory,
    SentToCenterixLog,
    CallbackPromiseApp,
    BucketRecoveryDistribution,
)
from juloserver.portal.object.dashboard.constants import JuloUserRoles
from juloserver.julo.services import (
    sort_payments_by_collection_model,
    cem_b2_3_4_experiment,
    ptp_create,
)
from juloserver.julo.statuses import (
    PaymentStatusCodes,
    LoanStatusCodes,
    JuloOneCodes,
    ApplicationStatusCodes,
)
from juloserver.julo.clients import (
    get_julo_centerix_client,
    get_julo_email_client,
    get_julo_pn_client,
    get_julo_sentry_client,
)
from juloserver.julo.models import (
    SkiptraceHistory,
    ProductivityCenterixSummary,
    Loan,
    PaymentNote,
    SkiptraceResultChoice,
    Skiptrace,
    PTP,
    Payment,
    FeatureSetting,
    PaybackTransaction,
    SkiptraceStats,
)
from juloserver.julo.exceptions import JuloException
from django.contrib.auth.models import User, Group

from .utils import (
    validate_activate_experiment,
    batch_pk_query_with_cursor,
    get_feature_setting_parameters,
)
from ..account.models import Account
from juloserver.ana_api.models import (
    B2ExcludeFieldCollection,
    B3ExcludeFieldCollection,
    CollectionB5,
)
from ..fdc.files import TempDir
from juloserver.julo.product_lines import ProductLineCodes
from ..julo.utils import format_e164_indo_phone_number, have_pn_device
from juloserver.julo.constants import ExperimentConst, FeatureNameConst
from juloserver.minisquad.constants import (
    DialerVendor,
    Threshold,
    IntelixResultChoiceMapping,
    ErrorMessageProcessDownloadManualUploadIntelix,
    DialerSystemConst,
)

from juloserver.account_payment.models import AccountPayment
from juloserver.minisquad.constants import DialerTaskStatus
from juloserver.minisquad.models import DialerTask
from django.db import connection
from juloserver.collection_vendor.celery_progress import ProgressRecorder
from juloserver.minisquad.services2.metabase import query_download_manual_upload_intelix
from juloserver.minisquad.services2.phone_number_related import (
    RemovePhoneNumberParamDTO,
    remove_phone_number,
)
from django.conf import settings
from juloserver.minisquad.constants import (
    ExperimentConst as MinisquadExperimentConst,
    FeatureNameConst as MinisquadFeatureNameConst,
)
from ..moengage.constants import UNSENT_MOENGAGE_EXPERIMENT
from ..moengage.services.use_cases import send_user_attributes_to_moengage_for_cashback_new_scheme_exp
from ..monitors.notifications import slack_notify_and_send_csv_files
from ..streamlined_communication.constant import CommunicationPlatform
from ..streamlined_communication.models import StreamlinedCommunication
from juloserver.minisquad.services2.growthbook import (
    store_from_growthbook,
    get_experiment_setting_data_on_growthbook
)

logger = logging.getLogger(__name__)


# @task(name='upload_julo_t0_data_to_centerix')
# def upload_julo_t0_data_to_centerix():
#     payments = get_payment_details_for_calling('JULO_T0')
#     if len(payments) == 0:
#         logger.error({
#             "action": "upload_julo_t0_data_to_centerix",
#             "error": "error upload t0 data to centerix because payment list not exist"
#         })
#         return
#
#     payments_collection = sort_payments_by_collection_model(payments, '0')
#     response = upload_payment_details(payments_collection, 'JULO_T0')
#     logger.info({
#         "action": "upload_julo_t0_data_to_centerix",
#         "response": response
#     })

# @task(name='upload_julo_tminus1_data_to_centerix')
# def upload_julo_tminus1_data_to_centerix():
#     payments = get_payment_details_for_calling('JULO_T-1')
#     if len(payments) == 0:
#         logger.error({
#             "action": "upload_julo_tminus1_data_to_centerix",
#             "error": "error upload tminus1 data to centerix because payment list not exist"
#         })
#         return
#
#     payments_collection = sort_payments_by_collection_model(payments, '-1')
#     response = upload_payment_details(payments_collection, 'JULO_T-1')
#     logger.info({
#         "action": "upload_julo_tminus1_data_to_centerix",
#         "response": response
#     })


# @task(name='upload_julo_tplus1_to_4_data_centerix')
# def upload_julo_tplus1_to_4_data_centerix():
#     payments = get_payment_details_for_calling('JULO_T1-T4')
#
#     if len(payments) == 0:
#         logger.error({
#             "action": "upload_julo_tplus1_to_4_data_to_centerix",
#             "error": "error upload tplus1_to_4 data to centerix because payment list not exist"
#         })
#         return
#
#     caller_experiment_setting = get_caller_experiment_setting(
#         ExperimentConst.COLLECTION_NEW_DIALER_V1)
#
#     if caller_experiment_setting:
#         centerix_payments, intelix_payments = filter_loan_id_based_on_experiment_settings(
#             caller_experiment_setting, payments)
#         experiment_dict = {
#             'bucket_type': 'B1',
#             'experiment_group': DialerVendor.CENTERIX,
#             'experiment_setting': caller_experiment_setting
#         }
#
#         centerix_collection = sort_payments_by_collection_model(
#             centerix_payments, ['1', '2', '3', '4'])
#         intelix_collection = sort_payments_by_collection_model(
#             intelix_payments, ['1', '2', '3', '4'])
#     else:
#         centerix_payments = payments
#         experiment_dict = {}
#         centerix_collection = sort_payments_by_collection_model(payments, ['1', '2', '3', '4'])
#         intelix_collection = []
#
#     response = upload_payment_details(centerix_collection, 'JULO_T1-T4')
#     record_centerix_log(centerix_collection, 'JULO_T1-T4', experiment_dict)
#     record_vendor_experiment_data(intelix_collection, experiment_dict)
#     logger.info({
#         "action": "upload_julo_tplus1_to_4_data_centerix",
#         "response": response
#     })
#
#
# @task(name='upload_julo_tplus5_to_10_data_centerix')
# def upload_julo_tplus5_to_10_data_centerix():
#     payments = get_payment_details_for_calling('JULO_T5-T10')
#
#     if len(payments) == 0:
#         logger.error({
#             "action": "upload_julo_tplus5_to_10_data_centerix",
#             "error": "error upload tplus5_to_10 data to centerix because payment list not exist"
#         })
#         return
#
#     caller_experiment_setting = get_caller_experiment_setting(
#         ExperimentConst.COLLECTION_NEW_DIALER_V1)
#
#     if caller_experiment_setting:
#         centerix_payments, intelix_payments = filter_loan_id_based_on_experiment_settings(
#             caller_experiment_setting, payments)
#         experiment_dict = {
#             'bucket_type': 'B1',
#             'experiment_group': DialerVendor.CENTERIX,
#             'experiment_setting': caller_experiment_setting
#         }
#
#         centerix_collection = sort_payments_by_collection_model(
#             centerix_payments, ['5', '6', '7', '8', '9', '10'])
#         intelix_collection = sort_payments_by_collection_model(
#             intelix_payments, ['5', '6', '7', '8', '9', '10'])
#     else:
#         centerix_payments = payments
#         experiment_dict = {}
#         centerix_collection = sort_payments_by_collection_model(
#             payments, ['5', '6', '7', '8', '9', '10'])
#         intelix_collection = []
#
#     response = upload_payment_details(centerix_collection, 'JULO_T5-T10')
#     record_centerix_log(centerix_collection, 'JULO_T5-T10', experiment_dict)
#     record_vendor_experiment_data(intelix_collection, experiment_dict)
#
#     logger.info({
#         "action": "upload_julo_tplus5_to_10_data_centerix",
#         "response": response
#     })
#
#
# @task(name='upload_julo_b2_data_centerix')
# def upload_julo_b2_data_centerix():
#     caller_experiment_setting = get_caller_experiment_setting(
#         ExperimentConst.COLLECTION_NEW_DIALER_V1)
#     payments = get_payment_details_for_calling('JULO_B2', caller_experiment_setting)
#
#     if len(payments) == 0:
#         logger.error({
#             "action": "upload_julo_b2_data_centerix",
#             "error": "error upload bucket 2 data to centerix because payment list not exist"
#         })
#
#         return
#
#     if caller_experiment_setting:
#         centerix_payments, intelix_payments = filter_loan_id_based_on_experiment_settings(
#             caller_experiment_setting, payments)
#         centerix_payments = cem_b2_3_4_experiment(centerix_payments, 'JULO_B2')
#         intelix_payments = cem_b2_3_4_experiment(intelix_payments, 'JULO_B2')
#         experiment_dict = {
#             'bucket_type': 'B2',
#             'experiment_group': DialerVendor.CENTERIX,
#             'experiment_setting': caller_experiment_setting
#         }
#     else:
#         experiment_dict = {}
#         centerix_payments = payments
#         intelix_payments = []
#
#     response = upload_payment_details(centerix_payments, 'JULO_B2')
#     record_centerix_log(centerix_payments, 'JULO_B2', experiment_dict)
#     record_vendor_experiment_data(intelix_payments, experiment_dict)
#     logger.info({
#         "action": "upload_julo_b2_data_centerix",
#         "response": response
#     })
#
#
# @task(name='upload_julo_b2_s1_data_centerix')
# def upload_julo_b2_s1_data_centerix():
#     caller_experiment_setting = get_caller_experiment_setting(
#         ExperimentConst.COLLECTION_NEW_DIALER_V1)
#     payments = get_payment_details_for_calling('JULO_B2.S1', caller_experiment_setting)
#
#     if len(payments) == 0:
#         logger.error({
#             "action": "upload_julo_b2_s1_data_centerix",
#             "error": "error upload bucket 2 squad 1 data to centerix because payment list not exist"
#         })
#         return
#
#     if caller_experiment_setting:
#         centerix_payments, _ = filter_loan_id_based_on_experiment_settings(
#             caller_experiment_setting, payments)
#         centerix_payments = cem_b2_3_4_experiment(
#             centerix_payments, 'JULO_B2.S1', is_object_payment=False)
#         experiment_dict = {
#             'bucket_type': 'B2',
#             'experiment_group': DialerVendor.CENTERIX,
#             'experiment_setting': caller_experiment_setting
#         }
#     else:
#         experiment_dict = {}
#         centerix_payments = payments
#
#     response = upload_payment_details(centerix_payments, 'JULO_B2.S1')
#     record_centerix_log(centerix_payments, 'JULO_B2.S1', experiment_dict)
#     logger.info({
#         "action": "upload_julo_b2_s1_data_centerix",
#         "response": response
#     })
#
# @task(name='upload_julo_b2_s2_data_centerix')
# def upload_julo_b2_s2_data_centerix():
#     caller_experiment_setting = get_caller_experiment_setting(
#         ExperimentConst.COLLECTION_NEW_DIALER_V1)
#     payments = get_payment_details_for_calling('JULO_B2.S2', caller_experiment_setting)
#
#     if len(payments) == 0:
#         logger.error({
#             "action": "upload_julo_b2_s2_data_centerix",
#             "error": "error upload bucket 2 squad 2 data to centerix because payment list not exist"
#         })
#         return
#
#     if caller_experiment_setting:
#         centerix_payments, _ = filter_loan_id_based_on_experiment_settings(
#             caller_experiment_setting, payments)
#         centerix_payments = cem_b2_3_4_experiment(
#             centerix_payments, 'JULO_B2.S2', is_object_payment=False)
#         experiment_dict = {
#             'bucket_type': 'B2',
#             'experiment_group': DialerVendor.CENTERIX,
#             'experiment_setting': caller_experiment_setting
#         }
#     else:
#         experiment_dict = {}
#         centerix_payments = payments
#
#     response = upload_payment_details(centerix_payments, 'JULO_B2.S2')
#     record_centerix_log(centerix_payments, 'JULO_B2.S2', experiment_dict)
#     logger.info({
#         "action": "upload_julo_b2_s2_data_centerix",
#         "response": response
#     })
#
#
# @task(name='upload_julo_b3_data_centerix')
# def upload_julo_b3_data_centerix():
#     caller_experiment_setting = get_caller_experiment_setting(
#         ExperimentConst.COLLECTION_NEW_DIALER_V1)
#     payments = get_payment_details_for_calling('JULO_B3', caller_experiment_setting)
#
#     if len(payments) == 0:
#         logger.error({
#             "action": "upload_julo_b3_data_centerix",
#             "error": "error upload bucket 3 data to centerix because payment list not exist"
#         })
#         return
#
#     if caller_experiment_setting:
#         centerix_payments, intelix_payments = filter_loan_id_based_on_experiment_settings(
#             caller_experiment_setting, payments)
#         centerix_payments = cem_b2_3_4_experiment(centerix_payments, 'JULO_B3')
#         experiment_dict = {
#             'bucket_type': 'B3',
#             'experiment_group': DialerVendor.CENTERIX,
#             'experiment_setting': caller_experiment_setting
#         }
#     else:
#         experiment_dict = {}
#         centerix_payments = payments
#         intelix_payments = []
#
#     response = upload_payment_details(centerix_payments, 'JULO_B3')
#     record_centerix_log(centerix_payments, 'JULO_B3', experiment_dict)
#     record_vendor_experiment_data(intelix_payments, experiment_dict)
#     logger.info({
#         "action": "upload_julo_b3_data_centerix",
#         "response": response
#     })
#
#
# @task(name='upload_julo_b3_s1_data_centerix')
# def upload_julo_b3_s1_data_centerix():
#     caller_experiment_setting = get_caller_experiment_setting(
#         ExperimentConst.COLLECTION_NEW_DIALER_V1)
#     payments = get_payment_details_for_calling('JULO_B3.S1', caller_experiment_setting)
#
#     if len(payments) == 0:
#         logger.error({
#             "action": "upload_julo_b3_s1_data_centerix",
#             "error": "error upload bucket 3 squad 1 data to centerix because payment list not exist"
#         })
#         return
#
#     if caller_experiment_setting:
#         centerix_payments, _ = filter_loan_id_based_on_experiment_settings(
#             caller_experiment_setting, payments)
#         centerix_payments = cem_b2_3_4_experiment(
#             centerix_payments, 'JULO_B3.S1', is_object_payment=False)
#         experiment_dict = {
#             'bucket_type': 'B3',
#             'experiment_group': DialerVendor.CENTERIX,
#             'experiment_setting': caller_experiment_setting
#         }
#     else:
#         experiment_dict = {}
#         centerix_payments = payments
#
#     response = upload_payment_details(centerix_payments, 'JULO_B3.S1')
#     record_centerix_log(centerix_payments, 'JULO_B3.S1', experiment_dict)
#     logger.info({
#         "action": "upload_julo_b3_s1_data_centerix",
#         "response": response
#     })
#
#
# @task(name='upload_julo_b3_s2_data_centerix')
# def upload_julo_b3_s2_data_centerix():
#     caller_experiment_setting = get_caller_experiment_setting(
#         ExperimentConst.COLLECTION_NEW_DIALER_V1)
#     payments = get_payment_details_for_calling('JULO_B3.S2', caller_experiment_setting)
#
#     if len(payments) == 0:
#         logger.error({
#             "action": "upload_julo_b3_s2_data_centerix",
#             "error": "error upload bucket 3 squad 2 data to centerix because payment list not exist"
#         })
#         return
#
#     if caller_experiment_setting:
#         centerix_payments, _ = filter_loan_id_based_on_experiment_settings(
#             caller_experiment_setting, payments)
#         centerix_payments = cem_b2_3_4_experiment(
#             centerix_payments, 'JULO_B3.S2', is_object_payment=False)
#         experiment_dict = {
#             'bucket_type': 'B3',
#             'experiment_group': DialerVendor.CENTERIX,
#             'experiment_setting': caller_experiment_setting
#         }
#     else:
#         experiment_dict = {}
#         centerix_payments = payments
#
#     response = upload_payment_details(centerix_payments, 'JULO_B3.S2')
#     record_centerix_log(centerix_payments, 'JULO_B3.S2', experiment_dict)
#     logger.info({
#         "action": "upload_julo_b3_s2_data_centerix",
#         "response": response
#     })
#
#
# @task(name='upload_julo_b3_s3_data_centerix')
# def upload_julo_b3_s3_data_centerix():
#     caller_experiment_setting = get_caller_experiment_setting(
#         ExperimentConst.COLLECTION_NEW_DIALER_V1)
#     payments = get_payment_details_for_calling('JULO_B3.S3', caller_experiment_setting)
#
#     if len(payments) == 0:
#         logger.error({
#             "action": "upload_julo_b3_s3_data_centerix",
#             "error": "error upload bucket 3 squad 3 data to centerix because payment list not exist"
#         })
#         return
#
#     if caller_experiment_setting:
#         centerix_payments, _ = filter_loan_id_based_on_experiment_settings(
#             caller_experiment_setting, payments)
#         centerix_payments = cem_b2_3_4_experiment(
#             centerix_payments, 'JULO_B3.S3', is_object_payment=False)
#         experiment_dict = {
#             'bucket_type': 'B3',
#             'experiment_group': DialerVendor.CENTERIX,
#             'experiment_setting': caller_experiment_setting
#         }
#     else:
#         experiment_dict = {}
#         centerix_payments = payments
#
#     response = upload_payment_details(centerix_payments, 'JULO_B3.S3')
#     record_centerix_log(centerix_payments, 'JULO_B3.S3', experiment_dict)
#     logger.info({
#         "action": "upload_julo_b3_s3_data_centerix",
#         "response": response
#     })
#
#
# @task(name='upload_julo_b4_data_centerix')
# def upload_julo_b4_data_centerix():
#     caller_experiment_setting = get_caller_experiment_setting(
#         ExperimentConst.COLLECTION_NEW_DIALER_V1)
#     payments = get_payment_details_for_calling('JULO_B4', caller_experiment_setting)
#
#     if len(payments) == 0:
#         logger.error({
#             "action": "upload_julo_b4_data_centerix",
#             "error": "error upload bucket 4 data to centerix because payment list not exist"
#         })
#         return
#
#     if caller_experiment_setting:
#         centerix_payments, intelix_payments = filter_loan_id_based_on_experiment_settings(
#             caller_experiment_setting, payments)
#         centerix_payments = cem_b2_3_4_experiment(centerix_payments, 'JULO_B4')
#         intelix_payments = cem_b2_3_4_experiment(intelix_payments, 'JULO_B4')
#         experiment_dict = {
#             'bucket_type': 'B4',
#             'experiment_group': DialerVendor.CENTERIX,
#             'experiment_setting': caller_experiment_setting
#         }
#     else:
#         experiment_dict = {}
#         centerix_payments = payments
#         intelix_payments = []
#
#     response = upload_payment_details(centerix_payments, 'JULO_B4')
#     record_centerix_log(centerix_payments, 'JULO_B4', experiment_dict)
#     record_vendor_experiment_data(intelix_payments, experiment_dict)
#     logger.info({
#         "action": "upload_julo_b4_data_centerix",
#         "response": response
#     })
#
#
# @task(name='upload_julo_b4_s1_data_centerix')
# def upload_julo_b4_s1_data_centerix():
#     caller_experiment_setting = get_caller_experiment_setting(
#         ExperimentConst.COLLECTION_NEW_DIALER_V1)
#     payments = get_payment_details_for_calling('JULO_B4.S1', caller_experiment_setting)
#
#     if len(payments) == 0:
#         logger.error({
#             "action": "upload_julo_b4_s1_data_centerix",
#             "error": "error upload bucket 4 squad 1 data to centerix because payment list not exist"
#         })
#         return
#
#     if caller_experiment_setting:
#         centerix_payments, _ = filter_loan_id_based_on_experiment_settings(
#             caller_experiment_setting, payments)
#         centerix_payments = cem_b2_3_4_experiment(
#             centerix_payments, 'JULO_B4.S1', is_object_payment=False)
#         experiment_dict = {
#             'bucket_type': 'B4',
#             'experiment_group': DialerVendor.CENTERIX,
#             'experiment_setting': caller_experiment_setting
#         }
#     else:
#         experiment_dict = {}
#         centerix_payments = payments
#
#     response = upload_payment_details(centerix_payments, 'JULO_B4.S1')
#     record_centerix_log(centerix_payments, 'JULO_B4.S1', experiment_dict)
#     logger.info({
#         "action": "upload_julo_b4_s1_data_centerix",
#         "response": response
#     })

#
# @task(name='unassign_payments_from_squad')
# def unassign_payments_from_squad():
#     """
#     Unassign payments from the collection history table when the
#     maximum interval of payment staying in bucket already passed
#     """
#     collection_histories = CollectionHistory.objects\
#         .filter(
#             last_current_status=True,
#             payment__payment_status_id__lt=PaymentStatusCodes.PAID_ON_TIME,
#             payment_id__isnull=False)
#     today = timezone.localtime(timezone.now()).date()
#     role_dict = {
#         JuloUserRoles.COLLECTION_BUCKET_1: 10,
#         JuloUserRoles.COLLECTION_BUCKET_2: 40,
#         JuloUserRoles.COLLECTION_BUCKET_3: 70,
#         JuloUserRoles.COLLECTION_BUCKET_4: 100,
#     }
#
#     for collection_history in collection_histories:
#         bucket_type = collection_history.squad.group.name
#         max_date_in_bucket = collection_history.payment.due_date + timedelta(
#                                                         days=role_dict[bucket_type])
#
#         if today > max_date_in_bucket:
#             collection_history.update_safely(last_current_status=False,
#                                              agent=None,
#                                              squad=None,
#                                              excluded_from_bucket=False)

# @task(name="unassign_ptp_payments_from_agent")
# def unassign_ptp_payments_from_agent():
#     """Agent-Payment relationship on ptp payments that already passed the ptp date
#        and not fully paid will be removed on ptp_date + 1
#     """
#     today_minus1 = timezone.localtime(timezone.now()).date() - timedelta(days=1)
#     CollectionHistory.objects.filter(last_current_status=True,
#                                      payment__ptp_date=today_minus1,
#                                      payment__payment_status_id__lt=PaymentStatusCodes.PAID_ON_TIME,
#                                      excluded_from_bucket=False)\
#                              .update(agent=None,
#                                      is_ptp=False)


# @task(name="upload_ptp_agent_level_data_centerix")
# def upload_ptp_agent_level_data_centerix():
#     """
#     Task to upload ptp with ptp date today and today - 1
#     for agent level data to centerix
#     """
#     payments = get_payment_details_for_calling('PTP')
#     if len(payments) == 0:
#         logger.error({
#             "action": "upload_ptp_agent_level_data_centerix",
#             "error": "error upload ptp agent level data to centerix because payment list not exist"
#         })
#         return
#
#     caller_experiment_setting = get_caller_experiment_setting(
#         ExperimentConst.COLLECTION_NEW_DIALER_V1)
#
#     if caller_experiment_setting:
#         centerix_payments, _ = filter_loan_id_based_on_experiment_settings(
#             caller_experiment_setting, payments)
#         experiment_dict = {
#             'experiment_group': DialerVendor.CENTERIX,
#             'experiment_setting': caller_experiment_setting
#         }
#
#         centerix_bucket_payments, intelix_payments = get_payment_details_for_calling(
#             'BUCKET_PTP', caller_experiment_setting)
#         centerix_bucket_payments = centerix_bucket_payments.list_bucket_1_group_ptp_only()
#     else:
#         experiment_dict = {}
#         centerix_payments = payments
#         intelix_payments = []
#         centerix_bucket_payments = []
#
#     centerix_payment_groups = dict()
#
#     for obj in centerix_payments:
#         centerix_payment_groups.setdefault(obj.squad.squad_name, []).append(obj)
#
#     upload_ptp_agent_level_data(centerix_payment_groups, experiment_dict)
#     record_vendor_experiment_data(intelix_payments, experiment_dict, True)
#     record_vendor_experiment_data(
#         centerix_bucket_payments, experiment_dict, True, DialerVendor.CENTERIX)


# @task(name='run_get_call_status_details_from_centerix')
# def run_get_call_status_details_from_centerix():
#     """
#     Task to fetch call status details like abandon by user, abandon by system ,
#     null etc. to skiptrace tables and centrix log table based on each day
#     """
#     try:
#         centerix_client = get_julo_centerix_client()
#         date = timezone.localtime(timezone.now()).date()
#         start_date = date
#         end_date = date
#         centerix_client.get_call_status_details_from_centerix(start_date, end_date)
#     except Exception as e:
#         if run_get_call_status_details_from_centerix.request.retries == \
#                 run_get_call_status_details_from_centerix.max_retries:
#
#             sentry_client = get_julo_sentry_client()
#             sentry_client.captureException()
#             send_slack_message_centrix_failure(str(e))
#
#         raise run_get_call_status_details_from_centerix.retry(
#             countdown=600,  exc=e, max_retries=1
#         )


# @task(name='call_system_call_result_every_day')
# def call_system_call_result_every_day():
#     """
#     Task is to call the system result for each day
#     """
#     try:
#         centerix_client = get_julo_centerix_client()
#         centerix_client.get_all_system_call_result_from_centerix()
#     except Exception as e:
#         if call_system_call_result_every_day.request.retries >= \
#                 call_system_call_result_every_day.max_retries:
#
#             sentry_client = get_julo_sentry_client()
#             sentry_client.captureException()
#             send_slack_message_centrix_failure(str(e))
#
#         raise call_system_call_result_every_day.retry(
#             countdown=600,  exc=e, max_retries=1
#         )


# @task(name='run_get_all_system_call_result_from_centerix')
# def run_get_all_system_call_result_from_centerix():
#     """
#     Task to fetch call status details  and store it in table
#     """
#     call_system_call_result_every_day.apply_async(queue='low')


# @task(name="unassign_bucket_level_excluded_payment")
# def unassign_bucket_level_excluded_payment():
#     """Task to unassign excluded payments when switch buckets
#     """
#     unassign_bucket2_payment()
#     unassign_bucket3_payment()
#     unassign_bucket4_payment()


@task(queue="collection_normal")
def exclude_abandoned_payments_calls_from_daily_upload():
    """Task to move bucket level payments to NC bucket if
        5 consecutive of Abandoned calls
    """
    today = timezone.localtime(timezone.now()).date()
    # 22:15 is chosen as hour  and minutes since the cron to exclude because
    # the cron to insert abandoned data is at 22:10
    today_localtime = datetime(
        today.year,
        today.month,
        today.day,
        22,
        00
    )

    payment_level_abandoned_histories = SkiptraceHistory.objects.filter(
        cdate__gt=today_localtime,
        payment_id__isnull=False
    ).order_by('payment', '-id').distinct('payment')

    account_payment_level_abandoned_histories = SkiptraceHistory.objects.filter(
        cdate__gt=today_localtime,
        payment_id__isnull=True
    ).order_by('account_payment', '-id').distinct('account_payment')

    for call_history in payment_level_abandoned_histories:
        exclude_payment_from_daily_upload(call_history)

    for call_history in account_payment_level_abandoned_histories:
        exclude_payment_from_daily_upload(call_history, True)


# @task(name='agent_productiviy_details_from_centerix')
# def agent_productiviy_details_from_centerix(result):
#     agent_name = result['agent_name']
#     event_date = result['event_date']
#     event_date = datetime.strptime(event_date, '%m/%d/%Y %I:%M:%S %p')
#     leader_name = result['leader_name']
#     acw_time_duration = result['outbond_acw_time_duration']
#     outbond_acw_time_duration = datetime.strptime(acw_time_duration,
#                                                   '%H:%M:%S:%f').time().replace(microsecond=0)
#     aux_in_time_duration = result['outbond_aux_in_time_duration']
#     outbond_aux_in_time_duration = datetime.strptime(aux_in_time_duration,
#                                                      '%H:%M:%S:%f').time().replace(microsecond=0)
#
#     available_in_time_duration = result['outbond_available_in_time_duration']
#     outbond_available_in_time_duration = datetime.strptime(available_in_time_duration,
#                                                            '%H:%M:%S:%f').time().replace(microsecond=0)
#     busy_in_time_duration = result['outbond_busy_in_time_duration']
#     outbond_busy_in_time_duration = datetime.strptime(busy_in_time_duration,
#                                                       '%H:%M:%S:%f').time().replace(microsecond=0)
#     outbond_calls_connected = result['outbond_calls_connected']
#     outbond_calls_initiated = result['outbond_calls_initiated']
#     outbond_calls_not_connected = result['outbond_calls_not_connected']
#     handling_time_duration = result['outbond_handling_time_duration']
#     outbond_handling_time_duration = datetime.strptime(handling_time_duration,
#                                                        '%H:%M:%S:%f').time().replace(microsecond=0)
#     logged_in_time_duration = result['outbond_logged_in_time_duration']
#     outbond_logged_in_time_duration = datetime.strptime(logged_in_time_duration,
#                                                         '%H:%M:%S:%f').time().replace(microsecond=0)
#     talk_time_duration = result['outbond_talk_time_duration']
#     outbond_talk_time_duration = datetime.strptime(talk_time_duration,
#                                                    '%H:%M:%S:%f').time().replace(microsecond=0)
#     filter_ = dict(agent_name=agent_name,
#                   event_date=event_date,
#                   leader_name=leader_name,
#                   outbond_acw_time_duration=outbond_acw_time_duration,
#                   outbond_aux_in_time_duration=outbond_aux_in_time_duration,
#                   outbond_available_in_time_duration=outbond_available_in_time_duration,
#                   outbond_busy_in_time_duration=outbond_busy_in_time_duration,
#                   outbond_calls_connected=outbond_calls_connected,
#                   outbond_calls_initiated=outbond_calls_initiated,
#                   outbond_calls_not_connected=outbond_calls_not_connected,
#                   outbond_handling_time_duration=outbond_handling_time_duration,
#                   outbond_logged_in_time_duration=outbond_logged_in_time_duration,
#                   outbond_talk_time_duration=outbond_talk_time_duration)
#     productivity_centerix_summary_count = ProductivityCenterixSummary.objects.filter(**filter_).count()
#     if productivity_centerix_summary_count > 0:
#         return
#     ProductivityCenterixSummary.objects.create(**filter_)
#

# @task(name='run_get_agent_productiviy_details_from_centerix')
# def run_get_agent_productiviy_details_from_centerix():
#     """
#     Task to fetch agent productivity details based on each day
#     """
#     centerix_client = get_julo_centerix_client()
#     date = timezone.localtime(timezone.now()).date()
#     start_date = date
#     end_date = date
#     try:
#         results = centerix_client.get_agent_productiviy_details_from_centerix(start_date, end_date)
#         for result in results:
#             agent_productiviy_details_from_centerix(result)
#
#     except Exception as e:
#         response = 'Failed to retrieve data from centerix for agent productivity'
#         error_msg = 'Something went wrong -{}'.format(str(e))
#         logger.error({
#             'status': response,
#             'reason': error_msg
#         })
#         raise e


# @task(name='remove_centerix_log_more_than_30days')
# def remove_centerix_log_more_than_30days():
#     """
#     Task to remove all unused ceneterix log that more than 30days
#     """
#     end_date = timezone.localtime(timezone.now()) - relativedelta(days=30)
#     data = SentToCenterixLog.objects.filter(cdate__lte=end_date).last()
#     if data:
#         SentToCenterixLog.objects.filter(id__lte=data.id).delete()


# @task(name='run_get_agent_hourly_data_from_centerix')
# def run_get_agent_hourly_data_from_centerix():
#     """
#     Task is to get the agent hourly availability data from centerix
#     and store it in table
#     """
#     centerix_client = get_julo_centerix_client()
#     centerix_client.get_agent_hourly_data_from_centerix()


# @task(name='upload_julo_b2_non_contacted_data_centerix')
# def upload_julo_b2_non_contacted_data_centerix():
#     nc_squad, nc_bucket = get_payment_details_for_calling('JULO_B2_NON_CONTACTED')
#     caller_experiment_setting = get_caller_experiment_setting(
#         ExperimentConst.COLLECTION_NEW_DIALER_V1)
#
#     if caller_experiment_setting:
#         nc_squad_centerix, nc_squad_intelix = filter_loan_id_based_on_experiment_settings(
#             caller_experiment_setting, nc_squad)
#         nc_bucket_centerix, nc_bucket_intelix = filter_loan_id_based_on_experiment_settings(
#             caller_experiment_setting, nc_bucket)
#         experiment_dict = {
#             'bucket_type': 'NON_CONTACT_B2',
#             'experiment_group': DialerVendor.CENTERIX,
#             'experiment_setting': caller_experiment_setting
#         }
#
#         centerix_payments = list(chain(nc_squad_centerix, nc_bucket_centerix))
#         intelix_payments = list(chain(nc_squad_intelix, nc_bucket_intelix))
#     else:
#         experiment_dict = {}
#         centerix_payments = list(chain(nc_squad, nc_bucket))
#         intelix_payments = []
#
#     response = upload_payment_details(centerix_payments, 'JULO_B2_NON_CONTACTED')
#     record_centerix_log(centerix_payments, 'JULO_B2_NON_CONTACTED', experiment_dict)
#     record_vendor_experiment_data(intelix_payments, experiment_dict)
#     logger.info({
#         "action": "upload_julo_b2_non_contacted_data_centerix",
#         "response": response
#     })


# @task(name='upload_julo_b3_non_contacted_data_centerix')
# def upload_julo_b3_non_contacted_data_centerix():
#     nc_squad, nc_bucket = get_payment_details_for_calling('JULO_B3_NON_CONTACTED')
#     caller_experiment_setting = get_caller_experiment_setting(
#         ExperimentConst.COLLECTION_NEW_DIALER_V1)
#
#     if caller_experiment_setting:
#         nc_squad_centerix, nc_squad_intelix = filter_loan_id_based_on_experiment_settings(
#             caller_experiment_setting, nc_squad)
#         nc_bucket_centerix, nc_bucket_intelix = filter_loan_id_based_on_experiment_settings(
#             caller_experiment_setting, nc_bucket)
#         experiment_dict = {
#             'bucket_type': 'NON_CONTACT_B3',
#             'experiment_group': DialerVendor.CENTERIX,
#             'experiment_setting': caller_experiment_setting
#         }
#
#         centerix_payments = list(chain(nc_squad_centerix, nc_bucket_centerix))
#         intelix_payments = list(chain(nc_squad_intelix, nc_bucket_intelix))
#     else:
#         experiment_dict = {}
#         centerix_payments = list(chain(nc_squad, nc_bucket))
#         intelix_payments = []
#
#     response = upload_payment_details(centerix_payments, 'JULO_B3_NON_CONTACTED')
#     record_centerix_log(centerix_payments, 'JULO_B3_NON_CONTACTED', experiment_dict)
#     record_vendor_experiment_data(intelix_payments, experiment_dict)
#     logger.info({
#         "action": "upload_julo_b3_non_contacted_data_centerix",
#         "response": response
#     })


# @task(name='upload_julo_b4_non_contacted_data_centerix')
# def upload_julo_b4_non_contacted_data_centerix():
#     nc_squad, nc_bucket = get_payment_details_for_calling('JULO_B4_NON_CONTACTED')
#     caller_experiment_setting = get_caller_experiment_setting(
#         ExperimentConst.COLLECTION_NEW_DIALER_V1)
#
#     if caller_experiment_setting:
#         nc_squad_centerix, nc_squad_intelix = filter_loan_id_based_on_experiment_settings(
#             caller_experiment_setting, nc_squad)
#         nc_bucket_centerix, nc_bucket_intelix = filter_loan_id_based_on_experiment_settings(
#             caller_experiment_setting, nc_bucket)
#         experiment_dict = {
#             'bucket_type': 'NON_CONTACT_B4',
#             'experiment_group': DialerVendor.CENTERIX,
#             'experiment_setting': caller_experiment_setting
#         }
#
#         centerix_payments = list(chain(nc_squad_centerix, nc_bucket_centerix))
#         intelix_payments = list(chain(nc_squad_intelix, nc_bucket_intelix))
#     else:
#         experiment_dict = {}
#         centerix_payments = list(chain(nc_squad, nc_bucket))
#         intelix_payments = []
#
#     response = upload_payment_details(centerix_payments, 'JULO_B4_NON_CONTACTED')
#     record_centerix_log(centerix_payments, 'JULO_B4_NON_CONTACTED', experiment_dict)
#     record_vendor_experiment_data(intelix_payments, experiment_dict)
#     logger.info({
#         "action": "upload_julo_b4_non_contacted_data_centerix",
#         "response": response
#     })


@task(queue="collection_normal")
def store_intelix_call_result(valid_data, uploader_email):
    now_tasks = timezone.now()
    logger.info({
        "action": "store_intelix_call_result_start",
        "time": timezone.localtime(now_tasks).strftime('%m/%d/%Y %I:%M:%S %p'),
        "data_count": len(valid_data)
    })
    failed_store = []
    for data in valid_data:
        now = timezone.now()
        try:
            loan = Loan.objects.get_or_none(pk=data['LOAN_ID'])
            if not loan:
                failed_store.append(
                    dict(
                        loan_id=data['LOAN_ID'],
                        payment_id='',
                        error_msg='loan id : {} is not found on database'.format(data['LOAN_ID'])
                    )
                )
                continue

            application = loan.application
            customer = application.customer
            phone = application.mobile_phone_1
            payment = loan.payment_set.get_or_none(id=data['PAYMENT_ID'])
            if not payment:
                failed_store.append(
                    dict(
                        loan_id=loan.id,
                        payment_id=data['PAYMENT_ID'],
                        error_msg='payment id : {} is not found on database with loan id : {}'
                            .format(data['PAYMENT_ID'], loan.id)
                    )
                )
                continue

            agent_user = User.objects.filter(username=data['AGENT_NAME'].lower()).last()
            agent_name = None
            if agent_user:
                agent_name = agent_user.username

            start_ts = datetime.strptime(data['START_TS'], '%Y-%m-%d %H:%M:%S')
            end_ts = datetime.strptime(data['END_TS'], '%Y-%m-%d %H:%M:%S')
            call_status = data['CALL_STATUS']
            notes = data['NOTES']

            if 'PTP_AMOUNT' in data and 'PTP_DATE' in data:
                ptp_amount = data['PTP_AMOUNT']
                ptp_date = data['PTP_DATE']

                if ptp_amount and ptp_date:
                    if agent_user:
                        ptp = PTP.objects.filter(payment=payment).last()
                        paid_ptp_status = ['Paid', 'Paid after ptp date']

                        if payment.payment_status_id in PaymentStatusCodes.paid_status_codes():
                            raise JuloException("Can not add PTP, this payment {} already paid \
                                    off".format(payment.id))

                        if ptp:
                            if ptp.ptp_status and ptp.ptp_status in paid_ptp_status:
                                raise JuloException("Can not create PTP, this payment {} already paid \
                                    off".format(payment.id))

                        ptp_create(payment, ptp_date, ptp_amount, agent_user)
                        ptp_notes = "Promise to Pay %s -- %s " % (ptp_amount, ptp_date)

                        payment.update_safely(ptp_date=ptp_date,
                                              ptp_amount=ptp_amount)

                        PaymentNote.objects.create(
                            note_text=ptp_notes,
                            payment=payment)

                    else:
                        failed_store.append(
                            dict(
                                loan_id=loan.id,
                                payment_id=payment.id,
                                error_msg='invalid because not found agent name {} for this PTP'
                                    .format(data['AGENT_NAME'])
                            )
                        )
                        continue

            skip_result_choice = SkiptraceResultChoice.objects.filter(name__iexact=call_status).last()
            if not skip_result_choice:
                mapping_key = call_status.lower()
                julo_skiptrace_result_choice = None if mapping_key not in IntelixResultChoiceMapping.MAPPING_STATUS \
                    else IntelixResultChoiceMapping.MAPPING_STATUS[mapping_key]

                skip_result_choice = SkiptraceResultChoice.objects.filter(name__iexact=julo_skiptrace_result_choice).last()
                if not skip_result_choice:
                    failed_store.append(
                        dict(
                            loan_id=loan.id,
                            payment_id=payment.id,
                            error_msg='Invalid skip_result_choice with value {}'
                                .format(call_status)
                        )
                    )
                    continue

            skiptrace_result_id = skip_result_choice.id
            skip_history = SkiptraceHistory.objects.filter(
                payment_id=payment.id,
                loan_id=payment.loan.id,
                application_id=payment.loan.application.id,
                start_ts=start_ts,
                call_result_id=skiptrace_result_id).last()
            if skip_history:
                continue

            skiptrace_obj = Skiptrace.objects.filter(
                phone_number=format_e164_indo_phone_number(phone),
                customer_id=customer.id).last()
            if not skiptrace_obj:
                skiptrace = Skiptrace.objects.create(
                    contact_source='mobile_phone_1',
                    phone_number=format_e164_indo_phone_number(phone),
                    customer_id=customer.id)
                skiptrace_ids = skiptrace.id
            else:
                skiptrace_ids = skiptrace_obj.id

            if not skiptrace_ids:
                failed_store.append(
                    dict(
                        loan_id=loan.id,
                        payment_id=payment.id,
                        error_msg='Invalid Skiptrace ID'
                    )
                )
                continue

            SkiptraceHistory.objects.create(
                start_ts=start_ts,
                end_ts=end_ts,
                application_id=payment.loan.application.id,
                loan_id=payment.loan.id,
                agent_name=agent_name,
                agent=agent_user,
                call_result_id=skiptrace_result_id,
                skiptrace_id=skiptrace_ids,
                payment_id=payment.id,
                notes=notes,
                loan_status=payment.loan.loan_status.status_code,
                payment_status=payment.payment_status.status_code,
                application_status=payment.loan.application.status,
                spoke_with=data['SPOKE_WITH'],
                non_payment_reason=data['NON_PAYMENT_REASON'],
                source='Intelix'
            )

            if agent_user:
                trigger_insert_col_history(
                    payment.id, agent_user.id, skip_result_choice.id)

            logger.info({
                "action": "store_intelix_call_result_success",
                "time": timezone.localtime(timezone.now()).strftime('%m/%d/%Y %I:%M:%S %p'),
                "spent_time": "{}s".format((timezone.now() - now).seconds)
            })
        except Exception as error_message:
            # report error to sentry because if not sentry will not catch the error
            sentry_client = get_julo_sentry_client()
            sentry_client.captureException()
            failed_store.append(
                dict(
                    loan_id=data['LOAN_ID'],
                    payment_id=data['PAYMENT_ID'],
                    error_msg=str(error_message)
                )
            )
            logger.info({
                "action": "store_intelix_call_result_failed",
                "time": timezone.localtime(timezone.now()).strftime('%m/%d/%Y %I:%M:%S %p'),
                "spent_time": "{}s".format((timezone.now() - now).seconds)
            })
            continue

    logger.info({
        "action": "store_intelix_call_result_finished",
        "time": timezone.localtime(timezone.now()).strftime('%m/%d/%Y %I:%M:%S %p'),
        "spent_time": "{}s".format((timezone.now() - now_tasks).seconds),
        "data_count": len(valid_data)
    })

    if failed_store:
        julo_email_client = get_julo_email_client()
        julo_email_client.email_intelix_error_report(failed_store, uploader_email)


@task(queue="collection_high")
def exclude_non_contacted_payment_for_intelix(days=1):
    experiment_settings = get_caller_experiment_setting(ExperimentConst.COLLECTION_NEW_DIALER_V1)

    if not experiment_settings:
        return

    today = timezone.localtime(timezone.now()).date()
    date_to_compare = today - timedelta(days)
    intelix_range_loan_ids = experiment_settings.criteria[DialerVendor.INTELIX]
    skiptrace_history_results = SkiptraceHistory.objects.annotate(
        last_two_digit_loan_id=F('loan_id') % 100).filter(
        last_two_digit_loan_id__range=intelix_range_loan_ids,
        cdate__date=date_to_compare
    ).order_by('payment', '-start_ts').distinct('payment')

    for skiptrace_history in skiptrace_history_results:
        failed_calls = exclude_payment_from_daily_upload(skiptrace_history)

        if failed_calls >= Threshold.FAILED_CALLED:
            skiptrace_history.update_safely(excluded_from_bucket=True)



# @task(name='unassign_account_payments_from_squad')
# def unassign_account_payments_from_squad():
#     """
#     Unassign account payments from the collection history table when the
#     maximum interval of account payment staying in bucket already passed
#     """
#     collection_histories = CollectionHistory.objects\
#         .filter(
#             last_current_status=True,
#             account_payment__status_id__lt=PaymentStatusCodes.PAID_ON_TIME,
#             payment_id__isnull=True)
#     today = timezone.localtime(timezone.now()).date()
#     role_dict = {
#         JuloUserRoles.COLLECTION_BUCKET_1: 10,
#         JuloUserRoles.COLLECTION_BUCKET_2: 40,
#         JuloUserRoles.COLLECTION_BUCKET_3: 70,
#         JuloUserRoles.COLLECTION_BUCKET_4: 100,
#     }
#
#     for collection_history in collection_histories:
#         bucket_type = collection_history.squad.group.name
#         max_date_in_bucket = collection_history.account_payment.due_date + timedelta(
#             days=role_dict[bucket_type])
#
#         if today > max_date_in_bucket:
#             collection_history.update_safely(last_current_status=False,
#                                              agent=None,
#                                              squad=None,
#                                              excluded_from_bucket=False)


# @task(name="unassign_ptp_account_payments_from_agent")
# def unassign_ptp_account_payments_from_agent():
#     """Agent-Payment relationship on ptp payments that already passed the ptp date
#        and not fully paid will be removed on ptp_date + 1
#     """
#     today_minus1 = timezone.localtime(timezone.now()).date() - timedelta(days=1)
#     CollectionHistory.objects.filter(last_current_status=True,
#                                      account_payment__ptp_date=today_minus1,
#                                      account_payment__status_id__lt=PaymentStatusCodes.PAID_ON_TIME,
#                                      excluded_from_bucket=False)\
#                              .update(agent=None,
#                                      is_ptp=False)


@task(queue="collection_low")
def trigger_insert_col_history(
        payment_id, user_id, call_result_id, is_julo_one=False, is_grab=False, is_dana=False):

    if is_julo_one or is_grab:
        payment = AccountPayment.objects.get(pk=payment_id)
    else:
        payment = Payment.objects.get(pk=payment_id)

    if not user_id:
        return

    user = User.objects.get(pk=user_id)

    call_result = SkiptraceResultChoice.objects.get(pk=call_result_id)

    insert_col_history_data_based_on_call_result(
        payment,
        user,
        call_result,
        is_julo_one,
        is_dana=is_dana
    )


@task(queue="collection_low")
def trigger_in_app_ptp_broken():
    feature_setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.IN_APP_PTP_SETTING,
        is_active=True).last()
    if not feature_setting:
        return
    today = datetime.now().date()
    yesterday = today - timedelta(days=1)
    ptp_data = PTP.objects.filter(
        ptp_date=yesterday,
        ptp_status='Not Paid'
    )
    for ptp in ptp_data:
        account = ptp.account
        if account:
            send_notification_in_app_ptp_broken(account.id)
            logger.info({
                'action': 'trigger_in_app_ptp_broken',
                'ptp_id': ptp.id,
                'message': 'success run'
            })
            ptp.update_safely(ptp_status='Not Paid')


@task(queue="collection_low")
def send_notification_in_app_ptp_broken(account_id):
    account = Account.objects.get_or_none(pk=account_id)
    if not account:
        return
    application = account.application_set.last()
    device = application.device
    if not have_pn_device(device):
        logger.info({
            'action': 'send_notification_in_app_ptp_broken',
            'application_id': application.id,
            'meessage': 'did not have pn device'
        })
    gcm_reg_id = device.gcm_reg_id
    julo_pn_client = get_julo_pn_client()
    message = 'Tanggal janji bayar telah kembali seperti semula, mohon lakukan pembayaran sesuai dengan tanggal jatuh tempo.'
    julo_pn_client.in_app_ptp_broken('Janji Bayar Kamu Sudah Tidak Berlaku', message, gcm_reg_id)


@task(queue="collection_low")
def trigger_in_app_callback_notification_before_call():
    feature_setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.IN_APP_CALLBACK_SETTING,
        is_active=True).last()
    if not feature_setting:
        return

    parameter = feature_setting.parameters
    yesterday = timezone.localtime(timezone.now() - timedelta(days=1)).date()
    callback_promises = CallbackPromiseApp.objects.filter(
        selected_time_slot_start__isnull=False,
        account_payment__status_id__lt=PaymentStatusCodes.PAID_ON_TIME,
        bucket__in=parameter['eligible_buckets'],
        cdate__date=yesterday
    ).order_by('account_payment', '-cdate').distinct('account_payment')
    for callback_promise in callback_promises:
        account = callback_promise.account
        selected_time = callback_promise.selected_time_slot_start
        is_eligible, is_set_selected_time = is_eligible_for_in_app_callback(account)
        if not is_eligible or not is_set_selected_time:
            continue

        now = timezone.localtime(timezone.now())
        time_sent = selected_time.split(':')
        hours = int(time_sent[0]) - 1
        minute = int(time_sent[1])
        later = timezone.localtime(timezone.now()).replace(
            hour=hours, minute=minute, second=0, microsecond=0)
        if now < later:
            send_notification_in_app_callback_promise.apply_async(
                (callback_promise.account.id,), eta=later)
            logger.info({
                'action': 'trigger_in_app_callback_notification_before_call',
                'callback_promise': callback_promise.id,
                'message': 'success run'
            })
        else:
            logger.info({
                'action': 'trigger_in_app_callback_notification_before_call',
                'streamlined_comm': callback_promise.id,
                'message': 'run failed because time had passed'
            })


@task(queue="collection_low")
def send_notification_in_app_callback_promise(account_id):
    account = Account.objects.get_or_none(pk=account_id)
    if not account:
        return

    application = account.application_set.last()
    device = application.device
    if not have_pn_device(device):
        return

    gcm_reg_id = device.gcm_reg_id
    julo_pn_client = get_julo_pn_client()
    message = "1 jam lagi tim JULO akan menelepon kamu nih 😉"
    julo_pn_client.in_app_callback_reminder(
        "Siap-siap ya! ", message, gcm_reg_id)


@task(queue='collection_dialer_normal')
def process_download_manual_upload_intelix_csv_files(dialer_task_id, query_bucket):
    processed_count=0
    progress_recorder = ProgressRecorder(
        task_id=process_download_manual_upload_intelix_csv_files.request.id
    )
    
    try:
        query=query_download_manual_upload_intelix(query_bucket=query_bucket)

        cursor = connection.cursor()
        cursor.execute(query)
        row = cursor.fetchall()
    except:
        progress_recorder.set_progress(
            0, 0, ErrorMessageProcessDownloadManualUploadIntelix.FAILED_RUN_QUERY
        )
        return

    dialer_task = DialerTask.objects.get(pk=dialer_task_id)
    dialer_task.update_safely(
        status=DialerTaskStatus.PROCESSED,
    )
    fpath = settings.MEDIA_ROOT
    if not os.path.isdir(fpath):
        os.mkdir(fpath)

    filename = query_bucket.lower().replace(" ", "_", -1) + "_" +timezone.localtime(timezone.now()).strftime("%Y%m%d%H%M%S") + ".csv"

    header = ('loan_id', 'payment_id', 'account_id', 'account_payment_id', 'is_j1', 'customer_id',
              'application_id', 'nama_customer', 'mobile_phone_1', 'mobile_phone_2', 'nama_perusahaan',
              'posisi_karyawan', 'telp_perusahaan', 'dpd', 'angsuran_per_bulan', 'denda', 'outstanding',
              'tanggal_jatuh_tempo', 'nama_pasangan', 'no_telp_pasangan', 'nama_kerabat', 'no_telp_kerabat',
              'hubungan_kerabat', 'alamat', 'kota', 'jenis_kelamin', 'tgl_lahir', 'tgl_gajian', 'tujuan_pinjaman',
              'tgl_upload', 'va_bca', 'va_permata', 'va_maybank', 'va_alfamart', 'va_indomaret', 'campaign',
              'tipe_produk', 'jumlah_pinjaman', 'last_pay_date', 'last_pay_amount', 'status_tagihan_1',
              'status_tagihan_2', 'status_tagihan_3', 'status_tagihan_4', 'status_tagihan_5', 'status_tagihan_6',
              'status_tagihan_7', 'status_tagihan_8', 'status_tagihan_9', 'status_tagihan_10', 'status_tagihan_11',
              'status_tagihan_12', 'status_tagihan_13', 'status_tagihan_14', 'status_tagihan_15', 'partner_name',
              'last_agent', 'last_call_status', 'refinancing_status', 'activation_amount', 'program_expiry_date',
              'customer_bucket_type', 'promo_untuk_customer', 'zipcode', 'team')

    f =  open(fpath + filename,'w')
    writer = csv.writer(f)
    writer.writerow(header)

    if len(row) > 0:
        total_process = len(row)
        for i in row:
            writer.writerow(i)
            processed_count += 1
            progress_recorder.set_progress(processed_count, total_process)

        progress_recorder.set_progress(processed_count, total_process,
                                        str(filename).replace('.csv',''))
    else:
        total_process = 1
        processed_count += 1
        progress_recorder.set_progress(processed_count, total_process,
                                        str(filename).replace('.csv',''))

    f.close()
    

@task(queue='collection_dialer_low')
def do_delete_download_manual_upload_intelix_csv(csv_file_name):
    filename =  str(csv_file_name) + ".csv"
    csv_filepath = os.path.join(settings.BASE_DIR + '/media/',filename)
    if os.path.isfile(csv_filepath):
        os.remove(csv_filepath)

@task(queue="collection_normal")
def remove_phone_number_task(
    execute_time,
    data: List[RemovePhoneNumberParamDTO]
):
    # Remove phone number based on data.
    res_list = remove_phone_number(data)

    # Compose csv result file.

    csv_header = (
        "account_id", 
        "phone_number", 
        "status", 
        "reason", 
        "source_deleted_in_app", 
        "source_deleted_in_skiptrace",
    )
    csv_data = [
        [
            res.account_id, 
            res.phone_number, 
            res.status, 
            res.reason, 
            res.source_deleted_in_app, 
            res.source_deleted_in_skiptrace
        ] for res in res_list
    ]

    temp_dir = tempfile.gettempdir()

    file_name = 'phone_number_delete_result_{}.csv'.format(execute_time.strftime("%m%d%Y"))
    file_path = os.path.join(temp_dir, file_name)
    with open(file_path, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(csv_header)
        writer.writerows(csv_data)

    with open(file_path, 'rb') as f:
        data = f.read()

    encoded = base64.b64encode(data)

    if os.path.exists(file_path):
        os.remove(file_path)
    
    # Send email.

    action_time = execute_time.strftime("%m/%d/%Y, %H:%M:%S")
    subject = "Phone Number Delete Result {}".format(action_time)
    content = "Hi Team<br/><br/>Here is the result of Phone Number Delete Feature on {}<br/><br/>Thank you<br/>Best Regards".format(
        action_time
    )
    attachment_dict = {
        "content": encoded.decode(),
        "filename": file_name,
        "type": "text/csv"
    }

    feature_setting = FeatureSetting.objects.filter(
        feature_name=FeatureNameConst.PHONE_NUMBER_DELETE, 
        is_active=True,
    ).first()
    if not feature_setting:
        logger.error({
            "function_name": "remove_phone_number_task",
            "message": "failed fetch recipient email from feature setting",
        })
        
        return

    julo_email_client = get_julo_email_client()
    julo_email_client.send_email(
        subject=subject, 
        content=content, 
        attachment_dict=attachment_dict, 
        content_type="text/html",
        email_to=feature_setting.parameters['recipient_email'], 
        email_from="collections@julo.co.id",
        email_cc="", 
    )


@task(queue="collection_high")
@validate_activate_experiment(MinisquadExperimentConst.LATE_FEE_EARLIER_EXPERIMENT)
def update_is_automated_for_late_fee_experiment(*args, **kwargs):
    streamlined_comms = StreamlinedCommunication.objects.filter(
        template_code__in=('j1_email_dpd_+4', 'jturbo_email_dpd_+4'),
        communication_platform=CommunicationPlatform.EMAIL,
        extra_conditions=UNSENT_MOENGAGE_EXPERIMENT,)
    if not streamlined_comms:
        return
    streamlined_comms.update(is_automated=True)
    return


@task(queue="collection_dialer_high")
def populate_account_id_for_new_cashback_experiment(*args, **kwargs):
    fn_name = 'populate_account_id_for_new_cashback_experiment'
    logger.info({
        'action': fn_name,
        'message': 'task begin'
    })
    eligible_account_qs = Loan.objects.filter(
        account_id__isnull=False,
        loan_status_id__gte=LoanStatusCodes.CURRENT,
        loan_status_id__lt=LoanStatusCodes.RENEGOTIATED
    ).exclude(account__status=JuloOneCodes.SUSPENDED
    ).distinct('account_id').values_list('account_id', flat=True)
    split_threshold = 5000
    for batch_account_ids in batch_pk_query_with_cursor(
        eligible_account_qs, batch_size=split_threshold):
        store_cashback_new_scheme_by_account_ids.delay(
            batch_account_ids)
    logger.info({
        'action': fn_name,
        'message': 'all processed by async task'
    })


@task(queue="collection_high")
def store_cashback_new_scheme_by_account_ids(account_ids):
    fn_name = 'store_cashback_new_scheme_by_account_ids'
    logger.info({
        'action': fn_name,
        'message': 'task begin'
    })
    store_from_growthbook(MinisquadExperimentConst.CASHBACK_NEW_SCHEME, account_ids)
    send_user_attributes_to_moengage_for_cashback_new_scheme_exp.delay(account_ids)
    logger.info({
        'action': fn_name,
        'message': 'task finish'
    })


@task(queue="collection_high")
def populate_account_id_for_sms_after_robocall_experiment(*args, **kwargs):
    fn_name = 'populate_account_id_for_sms_after_robocall_experiment'
    logger.info({
        'action': fn_name,
        'message': 'task begin'
    })

    if not get_experiment_setting_data_on_growthbook(
            MinisquadExperimentConst.SMS_AFTER_ROBOCALL):
        logger.info({
            'action': fn_name,
            'message': 'Growthbook experiment setting active not found'
        })
        return

    dpd_setting = 6
    exclude_experiments = (
        MinisquadExperimentConst.CASHBACK_NEW_SCHEME,
        MinisquadExperimentConst.SMS_AFTER_ROBOCALL
    )
    dpd_date = timezone.localtime(timezone.now()).date() + timedelta(days=dpd_setting)
    eligible_account_qs = AccountPayment.objects.filter(
        due_date=dpd_date,
        due_amount__gt=0
    ).extra(
        where=["""NOT EXISTS(SELECT 1 FROM "account_payment" sub_ap
        WHERE "sub_ap"."account_id" = "account_payment"."account_id"
        AND "sub_ap"."due_date" < %s
        AND "sub_ap"."due_amount" > 0)"""],
        params=[dpd_date]
    ).extra(
        where=["""NOT EXISTS(SELECT 1 FROM "experiment_group"
        JOIN "experiment_setting" ON "experiment_group"."experiment_setting_id" = "experiment_setting"."experiment_setting_id"
        WHERE "experiment_group"."account_id" = "account_payment"."account_id"
        AND "experiment_setting"."code" IN %s)"""],
        params=[exclude_experiments]
    ).distinct('account').values_list('account_id', flat=True)
    split_threshold = 5000
    for batch_account_ids in batch_pk_query_with_cursor(
        eligible_account_qs, batch_size=split_threshold):
        store_sms_after_robocall_by_account_ids.delay(
            batch_account_ids)
    logger.info({
        'action': fn_name,
        'message': 'all processed by async task'
    })


@task(queue="collection_dialer_high")
def store_sms_after_robocall_by_account_ids(account_ids):
    fn_name = 'store_sms_after_robocall_by_account_ids'
    logger.info({
        'action': fn_name,
        'message': 'task begin'
    })
    store_from_growthbook(MinisquadExperimentConst.SMS_AFTER_ROBOCALL, account_ids)
    logger.info({
        'action': fn_name,
        'message': 'task finish'
    })


@task(queue="collection_high")
def bulk_change_users_role_async(csv_data, csv_file_name):
    logger.info({
        'action': 'bulk_change_users_role_async',
        'status': 'start {}'.format(csv_file_name)
    })
    csvfile = io.StringIO(csv_data)
    reader = csv.DictReader(csvfile)
    list_added_role = {}
    list_remove_role = {}
    failed_processed = []
    list_remove_all_roles = []
    new_email_list = {}
    logger.info({
        'action': 'bulk_change_users_role_async',
        'status': 'construct csv data'
    })
    for row in reader:
        username = row['username']
        user = User.objects.filter(username=username).last()
        if not user:
            failed_processed.append({
                'username': username,
                'reason': 'username cannot be found'
            })
            continue
        remove_roles = row['remove_roles']
        new_roles = row['new_roles']
        if not remove_roles and not new_roles:
            failed_processed.append({
                'username': username,
                'reason': 'remove roles and add roles is null'
            })
            continue

        if remove_roles and remove_roles != "*":
            for remove_role_name in remove_roles.split('|'):
                remove_role_user_list = list_remove_role.get(remove_role_name, [])
                remove_role_user_list.append(user.id)
                list_remove_role[remove_role_name] = remove_role_user_list
        elif remove_roles == "*":
            list_remove_all_roles.append(user.id)

        if new_roles:
            for new_role_name in new_roles.split('|'):
                new_role_user_list = list_added_role.get(new_role_name, [])
                new_role_user_list.append(user.id)
                list_added_role[new_role_name] = new_role_user_list
        new_email = row['new_email']
        if new_email:
            new_email_list[user.id] = {'user_obj': user, 'new_email': new_email}

    logger.info({
        'action': 'bulk_change_users_role_async',
        'status': 'processing'
    })
    # process remove all roles
    for user_id in list_remove_all_roles:
        user = User.objects.filter(pk=user_id).last()
        if not user:
            failed_processed.append({
                'username': str(user.id),
                'reason': 'username cannot be found'
            })
            continue
        user.groups.clear()
        # clear cacheops
        invalidate_obj(user)

    # process remove roles
    for role_name, list_users in list_remove_role.items():
        group_role = Group.objects.filter(name__iexact=role_name.upper()).last()
        if not group_role:
            username_list = list(User.objects.filter(
                pk__in=list_users).values_list('username', flat=True))
            failed_processed.append({
                'username': ','.join(str(user) for user in username_list),
                'reason': 'cannot remove group for {} since '
                          'cannot found in our system'.format(role_name)
            })
            continue
        users_to_remove = User.objects.filter(pk__in=list_users)
        group_role.user_set.remove(*users_to_remove)
        # clear cacheops
        invalidate_obj(group_role)

    # process add new roles
    UserGroups = User.groups.through
    for role_name, list_users in list_added_role.items():
        group_role = Group.objects.filter(name__iexact=role_name.upper()).last()
        if not group_role:
            failed_processed.append({
                'username': ','.join(str(user) for user in list_users),
                'reason': 'cannot add new role group for {} since'
                          ' cannot found in our system'.format(role_name)
            })
            continue
        existing_user_ids = UserGroups.objects.filter(
            group=group_role, user_id__in=list_users).values_list('user_id', flat=True)
        if existing_user_ids:
            username_list = list(User.objects.filter(
                pk__in=list_users).values_list('username', flat=True))
            failed_processed.append({
                'username': ','.join(str(user) for user in username_list),
                'reason': 'cannot add new role group {} because user '
                          'already have this role '.format(role_name)
            })
        user_ids_to_add = [user_id for user_id in list_users if user_id not in existing_user_ids]
        user_group_relations = [
            UserGroups(user_id=user_id, group_id=group_role.id) for user_id in user_ids_to_add]
        UserGroups.objects.bulk_create(user_group_relations)
        # clear cacheops
        invalidate_obj(group_role)
    # process change email
    for user_id, attribute in new_email_list.items():
        user = attribute['user_obj']
        try:
            user.email = attribute['new_email']
            user.save()
            invalidate_obj(user)
        except Exception as e:
            failed_processed.append({
                'username': user.username,
                'reason': str(e)
            })

    with TempDir() as tempdir:
        current_date_time = timezone.localtime(timezone.now())
        file_name = 'failed_processed_change_role_{}.csv'.format(
            str(current_date_time.strftime("%Y-%m-%d-%H:%M")))
        failed_processed_csv_file = os.path.join(tempdir.path, file_name)
        with open(failed_processed_csv_file, 'w', newline='') as file:
            writer = csv.writer(file)
            # Write the header row
            writer.writerow(
                ['username', 'reason'])
            for row in failed_processed:
                writer.writerow(row.values())
        message = "Success Bulk user role for this file {}".format(csv_file_name)
        message = message + ' with some failure please check'
        slack_notify_and_send_csv_files(
            message=message,
            csv_path=failed_processed_csv_file,
            channel="#IT-bulk-change-user-roles",
            file_name=file_name,
        )
    logger.info(
        {'action': 'bulk_change_users_role_async', 'status': 'finish {}'.format(csv_file_name)}
    )
    return True


@task(queue="collection_normal")
def sent_webhook_to_field_collection_service_by_category(**kwargs):
    category = kwargs.get('category', None)
    if not category:
        return

    fn = "sent_webhook_to_field_collection_service_by_category"
    logger.info(
        {
            'function_name': fn,
            'message': 'Start running',
            'category': category,
            'data': kwargs,
        }
    )

    timeout = kwargs.get('timeout', 60)
    retries = sent_webhook_to_field_collection_service_by_category.request.retries
    base_url = settings.FIELDCOLL_BASE_URL
    headers = {
        'Content-Type': 'application/json',
        'Authorization': 'Token {}'.format(settings.FIELDCOLL_TOKEN),
        'Run-Async': 'true',
    }
    payload = {}

    def get_account(param_account_xid):
        local_account = Account.objects.filter(
            id=param_account_xid,
            application__application_status_id__in=ApplicationStatusCodes.active_account(),
            application__partner_id__isnull=True,
            application__product_line_id__in=ProductLineCodes.julo_product(),
        ).last()
        if not local_account:
            logger.info(
                {'action': fn, 'message': 'non-product account j1', 'account_id': param_account_xid}
            )
        return local_account

    # Transaction category logic
    if category == 'transaction':
        account_xid = kwargs.get('account_xid', None)
        account = get_account(account_xid)
        if not account:
            return
        end_point_fc = 'transactions'
        oldest_unpaid = account.get_oldest_unpaid_account_payment()
        payload = {
            'outstanding_amount': account.get_total_outstanding_amount() or 0,
            'overdue_amount': account.get_total_overdue_amount() or 0,
            'due_date': oldest_unpaid.due_date.strftime('%Y-%m-%d') if oldest_unpaid else None,
        }
        url = '{}api/v1/debtor/webhook/{}/{}'.format(base_url, end_point_fc, account_xid)

    # Payment event category logic
    elif category == 'payment_event':
        payback_transaction_id = kwargs.get('payback_transaction_id', None)
        if not payback_transaction_id:
            return

        account_xid = kwargs.get('account_xid', None)
        account = get_account(account_xid)
        if not account:
            return

        end_point_fc = 'payment-event'
        payback_transaction_obj = PaybackTransaction.objects.get_or_none(pk=payback_transaction_id)
        if not payback_transaction_obj:
            logger.info(
                {
                    'action': fn,
                    'message': 'Payment event cannot found payback_transaction',
                    'account_id': account_xid,
                }
            )
            return
        transaction_datetime = (
            ''
            if not payback_transaction_obj.transaction_date
            else (payback_transaction_obj.transaction_date.strftime('%Y-%m-%d %H:%M:%S'))
        )

        payload = {
            'paid_amount': payback_transaction_obj.amount,
            'paid_date_time': transaction_datetime,
        }
        url = '{}api/v1/debtor/webhook/{}/{}'.format(base_url, end_point_fc, account_xid)

    # Population category logic
    elif category == 'population':
        bucket_type = kwargs.get('bucket_type', None)
        if not bucket_type:
            return

        current_date = timezone.localtime(timezone.now()).date()
        account_ids = None
        if bucket_type == 'b2':
            account_ids = B2ExcludeFieldCollection.objects.filter(
                assignment_date__gte=current_date
            ).values_list('account_id', flat=True)
        elif bucket_type == 'b3':
            account_ids = B3ExcludeFieldCollection.objects.filter(
                assignment_date__gte=current_date
            ).values_list('account_id', flat=True)
        elif bucket_type == 'b5':
            bucket_recover_is_running = get_feature_setting_parameters(
                MinisquadFeatureNameConst.BUCKET_RECOVERY_DISTRIBUTION, 'B5', 'is_running'
            )
            if bucket_recover_is_running:
                account_ids = BucketRecoveryDistribution.objects.filter(
                    bucket_name=DialerSystemConst.DIALER_BUCKET_5,
                    assignment_generated_date=current_date,
                    assigned_to="Field Collection - Inhouse",
                ).values_list('account_id', flat=True)
            else:
                account_ids = CollectionB5.objects.filter(
                    assignment_datetime__gte=current_date,
                    assigned_to="Field Collection - Inhouse",
                ).values_list('account_id', flat=True)
        elif bucket_type == 'fcb1':
            bucket_recover_is_running = get_feature_setting_parameters(
                MinisquadFeatureNameConst.BUCKET_RECOVERY_DISTRIBUTION, 'FCB1', 'is_running'
            )
            if bucket_recover_is_running:
                account_ids = BucketRecoveryDistribution.objects.filter(
                    bucket_name=DialerSystemConst.DIALER_BUCKET_FC_B1,
                    assignment_generated_date=current_date,
                    assigned_to="Field Collection - Inhouse",
                ).values_list('account_id', flat=True)
            else:
                return

        if not account_ids:
            logger.info(
                {
                    'function_name': fn,
                    'message': 'account_ids not found',
                    'category': category,
                    'bucket_type': bucket_type,
                }
            )
            return

        url = '{}{}'.format(base_url, 'api/v1/debtor/webhook/population')
        payload = {
            'bucket_type': bucket_type,
            'external_account_ids': list(account_ids),
        }

    elif category == 'exclude-pds':
        per_page = kwargs.get('per_page', 1000)
        page = kwargs.get('page', 1)
        bucket = kwargs.get('bucket', '')
        external_account_ids = kwargs.get('external_account_ids', [])
        url = '{}api/v1/debtor/webhook/exclude-pds/{}'.format(base_url, bucket)
        payload = {
            "current_page": page,
            "per_page": per_page,
            "external_account_ids": external_account_ids,
        }

    elif category == 'exclude-physical-wl':
        last_external_account_id = kwargs.get('last_external_account_id', 0)
        limit = kwargs.get('limit', 1000)
        end_point_fc = 'exclude-physical-wl'
        url = '{}api/v1/debtor/webhook/{}?_last_external_account_id={}&_limit={}'.format(
            base_url, end_point_fc, last_external_account_id, limit
        )

    # Handle invalid category
    else:
        logger.info(
            {
                'function_name': fn,
                'message': 'no category match',
                'category': category,
                'data': kwargs,
            }
        )
        return

    # Send the POST request
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=timeout)
        logger.info(
            {
                'function_name': fn,
                'message': 'success sent data to field collection service',
                'category': category,
                'data': kwargs,
                'response': response.text,
            }
        )
        return response
    except Exception as e:
        logger.error(
            {
                'function_name': fn,
                'message': 'failed to send data to field collection service',
                'category': category,
                'data': kwargs,
                'error': str(e),
            }
        )
        if retries >= sent_webhook_to_field_collection_service_by_category.max_retries:
            get_julo_sentry_client().captureException()
            return

        kwargs.update(
            {
                'timeout': timeout + (20 * retries),
            }
        )
        raise sent_webhook_to_field_collection_service_by_category.retry(
            countdown=300,
            exc=e,
            max_retries=3,
            kwargs=kwargs,
        )


@task(queue='collection_normal')
def update_skiptrace_stats_task():
    logger.info({"action": "update_skiptrace_stats_task", "message": "starting task"})
    feature_setting = FeatureSetting.objects.filter(
        is_active=True, feature_name=FeatureNameConst.SKIPTRACE_STATS_SCHEDULER
    ).last()
    if not feature_setting:
        logger.info(
            {"action": "update_skiptrace_stats_task", "message": "feature setting not active/found"}
        )
        return

    start_time = datetime.now().date() - timedelta(
        days=feature_setting.parameters.get('date_range', 30) + 1
    )
    end_time = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(
        microseconds=1
    )

    history_skiptrace_ids = (
        SkiptraceHistory.objects.distinct("skiptrace_id")
        .filter(cdate__range=(end_time.date(), end_time))
        .values_list('skiptrace_id', flat=True)
    )

    stats_skiptrace_ids = SkiptraceStats.objects.filter(
        calculation_start_date__lt=start_time, calculation_end_date__gte=F('calculation_start_date')
    ).values_list('skiptrace_id', flat=True)

    skiptrace_ids = list(set(list(history_skiptrace_ids) + list(stats_skiptrace_ids)))
    batch_size = feature_setting.parameters.get('task_batch_size', 10000)
    for i in range(0, len(skiptrace_ids), batch_size):
        update_skiptrace_stats_subtask.delay(skiptrace_ids[i : i + batch_size])

    logger.info({"action": "update_skiptrace_stats_task", "message": "task finished"})


@task(queue='collection_normal')
def update_skiptrace_stats_subtask(skiptrace_ids):
    logger.info(
        {
            "action": "update_skiptrace_stats_subtask",
            "message": "starting subtask",
            "skiptrace_ids": skiptrace_ids,
        }
    )
    feature_setting = FeatureSetting.objects.filter(
        is_active=True, feature_name=FeatureNameConst.SKIPTRACE_STATS_SCHEDULER
    ).last()
    if not feature_setting:
        logger.info(
            {
                "action": "update_skiptrace_stats_subtask",
                "message": "feature setting not active/found",
            }
        )
        return

    today_date = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    contact_call_results = [
        'RPC - Broken Promise',
        'RPC - Call Back',
        'RPC - HTP',
        'RPC - PTP',
        'RPC - Regular',
        'RPC - Already PTP',
        'RPC - Already Paid',
    ]

    start_time = today_date - timedelta(days=feature_setting.parameters.get('date_range', 30) + 1)
    end_time = today_date - timedelta(microseconds=1)

    skiptrace_histories = (
        SkiptraceHistory.objects.filter(
            skiptrace_id__in=skiptrace_ids,
            cdate__range=(start_time, end_time),
        )
        .values("skiptrace_id")
        .annotate(
            attempt_count=Count("id"),
            rpc_count=Count(
                Case(
                    When(call_result__name__in=contact_call_results, then=1),
                    output_field=IntegerField(),
                )
            ),
            min_date=Min("cdate"),
            max_date=Max("cdate"),
        )
    ).values_list('skiptrace_id', 'attempt_count', 'rpc_count', 'min_date', 'max_date')

    upserted_skiptrace_ids = []
    update_params = [
        'skiptrace_id',
        'attempt_count',
        'rpc_count',
        'calculation_start_date',
        'calculation_end_date',
        'rpc_rate',
    ]

    skiptrace_histories = [
        list(row) + [round(row[2] / row[1], 5) if row[2] > 0 else 0] for row in skiptrace_histories
    ]

    batch_size = feature_setting.parameters.get('insert_batch_size', 1000)
    for i in range(0, len(skiptrace_histories), batch_size):
        upserted_skiptrace_ids.extend(
            SkiptraceStats.objects.base_upsert(
                update_params, skiptrace_histories[i : i + batch_size]
            )
        )

    not_upseted_skiptraces_ids = list(set(skiptrace_ids) - set(upserted_skiptrace_ids))
    SkiptraceStats.objects.filter(skiptrace_id__in=not_upseted_skiptraces_ids,).update(
        attempt_count=0,
        rpc_count=0,
        rpc_rate=0,
        calculation_start_date=None,
        calculation_end_date=None,
    )

    rpc_start_time = today_date - timedelta(days=1)
    rpc_end_time = today_date - timedelta(microseconds=1)

    last_rpc_skiptrace_histories = (
        SkiptraceHistory.objects.distinct('skiptrace_id')
        .filter(
            skiptrace_id__in=skiptrace_ids,
            cdate__range=(rpc_start_time, rpc_end_time),
            call_result__name__in=contact_call_results,
        )
        .order_by('skiptrace_id', '-start_ts')
        .values_list('id', 'skiptrace_id', 'start_ts')
    )

    last_rpc_skiptrace_histories = [list(row) + [0, 0, 0] for row in last_rpc_skiptrace_histories]

    update_params = ['skiptrace_history_id', 'skiptrace_id', 'last_rpc_ts']
    insert_params = [
        'attempt_count',
        'rpc_count',
        'rpc_rate',
    ]
    for i in range(0, len(last_rpc_skiptrace_histories), batch_size):
        SkiptraceStats.objects.base_upsert(
            update_params + insert_params,
            last_rpc_skiptrace_histories[i : i + batch_size],
            update_params,
        )

    logger.info(
        {
            "action": "update_skiptrace_stats_subtask",
            "message": "subtask finished",
            "skiptrace_ids": skiptrace_ids,
        }
    )
