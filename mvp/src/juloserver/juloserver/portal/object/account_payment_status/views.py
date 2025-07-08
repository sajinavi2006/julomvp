from __future__ import print_function

import time
from builtins import zip
from future import standard_library

from juloserver.account.services.account_related import (
    get_loan_amount_dict_by_account_ids,
    get_latest_loan_dict_by_account_ids,
    get_latest_application_dict_by_account_ids,
    get_experiment_group_data,
)
from juloserver.autodebet.services.account_services import get_autodebet_bank_name
from juloserver.dana.models import DanaSkiptraceHistory
from juloserver.minisquad.services2.dialer_related import get_uninstall_indicator_from_moengage_by_customer_id

standard_library.install_aliases()
from builtins import str
import json
import operator
import re
import math
import csv
import io
from babel.numbers import format_decimal, parse_number
from itertools import chain

from dateutil import tz
from dateutil.parser import parse
import logging

from juloserver.autodebet.models import (
    AutodebetAccount
)
from datetime import date, datetime
from datetime import timedelta
from dateutil.relativedelta import relativedelta
from django.contrib import messages
from django.views.decorators.csrf import csrf_protect
from django.conf import settings
from django.core.validators import validate_email
from django.core.validators import ValidationError

from django.utils import timezone
from django.http import HttpResponse
from django.http import HttpResponseBadRequest
from django.http import HttpResponseNotAllowed
from django.http import HttpResponseNotFound
from django.http import JsonResponse
from django.template import RequestContext
from django.shortcuts import render_to_response, render
from django.shortcuts import get_object_or_404, redirect
from django.core.urlresolvers import reverse
from django.contrib.auth.models import User, Group
from django.http import Http404
from django.db.models import (
    Q,
    Case,
    When,
    Sum, Prefetch,
)
from django.views.generic import ListView
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.core import serializers
from django.db import transaction
from wsgiref.util import FileWrapper
from django.core.exceptions import ObjectDoesNotExist, MultipleObjectsReturned

from juloserver.account_payment.services.manual_transaction import process_account_manual_payment
from juloserver.collection_vendor.constant import CollectionVendorAssignmentConstant
from juloserver.collection_vendor.models import CollectionVendorAssignment, AgentAssignment
from juloserver.collection_vendor.services import display_account_movement_history, get_current_sub_bucket
from juloserver.julo.utils import check_email, format_e164_indo_phone_number, display_rupiah

# set decorator for login required
from object import julo_login_required, julo_login_required_exclude
from object import julo_login_req_group_class, julo_login_required_multigroup

from juloserver.julo.clients import get_julo_sentry_client
from juloserver.julo.clients import get_julo_autodialer_client
from juloserver.julo.constants import (AgentAssignmentTypeConst,
                                       FeatureNameConst,
                                       PaymentConst,
                                       BucketConst,
                                       PTPStatus, WorkflowConst)
from juloserver.julo.exceptions import (SmsNotSent,
                                        EmailNotSent,
                                        LateFeeException)

from juloserver.julo.partners import PartnerConstant
from juloserver.julo.models import (
    Application,
    AutoDialerRecord,
    ApplicationNote,
    BankLookup,
    CollectionAgentAssignment,
    CustomerWalletHistory,
    CustomerWalletNote,
    EmailHistory,
    FacebookData,
    FeatureSetting,
    Image,
    Loan,
    Partner,
    Payment,
    PaymentEvent,
    PaymentMethod,
    PaymentNote,
    RepaymentTransaction,
    RobocallTemplate,
    Skiptrace,
    SkiptraceHistory,
    SkiptraceResultChoice,
    SmsHistory,
    StatusLookup,
    VoiceRecord,
    PTP,
    CootekRobocall,
    ProductLine,
    Bank,
    ExperimentSetting,
    FDCRiskyHistory,
    Customer,
)
from juloserver.account_payment.models import (AccountPayment,
                                               AccountPaymentNote,
                                               AccountPaymentStatusHistory)
from juloserver.julo.payment_methods import PaymentMethodCodes
from juloserver.julo.product_lines import ProductLineCodes
from juloserver.julo.services import process_payment_status_change
from juloserver.julo.services import get_data_application_checklist_collection
from juloserver.julo.services2.agent import convert_usergroup_to_agentassignment_type
from juloserver.julo.services2.payment_event import PaymentEventServices
from juloserver.julo.services2 import get_agent_service
from juloserver.julo.statuses import (JuloOneCodes, PaymentStatusCodes)
from loan_app.forms import ImageUploadForm

from juloserver.portal.object.loan_app.constants import ImageUploadType
from payment_status.services import check_change_due_date_active
from payment_status.services import check_first_installment_btn_active
from payment_status.utils import (get_list_history,
                    get_app_list_history,
                    get_wallet_list_note,
                    payment_parse_pass_due,
                    get_list_email_sms,
                    payment_filter_search_field)
from payment_status.forms import StatusChangesForm
from payment_status.forms import PaymentForm
from loan_status.forms import NewPaymentInstallmentForm

from dashboard.constants import JuloUserRoles

from app_status.forms import ApplicationForm
from app_status.forms import ApplicationSelectFieldForm
from app_status.utils import ExtJsonSerializer
from payment_status.functions import get_act_pmt_lock_status, get_account_payment_lock_count
from payment_status.models import PaymentLocked, PaymentLockedMaster
from payment_status.constants import PAYMENT_EVENT_CONST

from juloserver.collectionbucket.services import get_agent_service_for_bucket
from juloserver.minisquad.services import (
    check_customer_bucket_type_account_payment,
    get_oldest_unpaid_account_payment_ids,
    get_call_summary_mjolnir_data,
    get_fdc_details_for_customer
)

from payment_status.utils import get_acc_pmt_list_history
from juloserver.payback.models import WaiverTemp
from juloserver.payback.services.waiver import (get_remaining_late_fee,
                                                get_remaining_interest,
                                                get_remaining_principal)
from juloserver.loan_refinancing.models import LoanRefinancing, LoanRefinancingRequest
from juloserver.loan_refinancing.constants import LoanRefinancingStatus
from juloserver.loan_refinancing.services.customer_related import get_refinancing_status_display
from payment_status.forms import ApplicationPhoneForm, SendEmailForm
from .services import (
    check_account_payment_first_installment_btn_active,
    find_phone_number_from_application_table,
)

from juloserver.account_payment.services.account_payment_related import (
    get_account_payment_events_transaction_level,
    is_crm_sms_email_locking_active,
    get_cashback_earned_dict_by_account_payment_ids,
    get_potential_and_total_cashback,
    check_lender_eligible_for_paydate_change,
)

from juloserver.account_payment.services.reversal import (
    process_late_fee_reversal,
    process_customer_payment_reversal
)
from juloserver.apiv3.models import ProvinceLookup

from juloserver.account.models import (
    AccountTransaction,
    Account,
    ExperimentGroup,
)
from juloserver.julo.services import (send_custom_sms_account_payment_reminder,
                                      send_custom_email_account_payment_reminder,
                                      get_wa_message_is_5_days_unreachable,
                                      get_wa_message_is_broken_ptp_plus_1)


from juloserver.julo.exceptions import JuloException
from account_payment_status.constants import SearchCategory, SpecialConditions
from juloserver.minisquad.models import CollectionHistory
from payment_status.utils import get_ptp_max_due_date, get_ptp_max_due_date_for_j1
from payment_status.serializers import SkiptraceSerializer, SkiptraceHistorySerializer, \
    GrabSkiptraceHistorySerializer, DanaSkiptraceHistorySerializer
from juloserver.julo.services import update_skiptrace_score, ptp_create_v2
from juloserver.minisquad.tasks import trigger_insert_col_history
from juloserver.minisquad.tasks2 import delete_paid_payment_from_intelix_if_exists_async_for_j1
from juloserver.collection_vendor.task import assign_agent_for_julo_one_bucket_5
from juloserver.whatsapp.services import get_j1_whatsapp_collection_text
from juloserver.account_payment.services.account_payment_related import (
    change_due_dates, update_payment_installment
)
from juloserver.julo.statuses import LoanStatusCodes, ApplicationStatusCodes
from django.db.models import Value, CharField
from juloserver.grab.models import GrabSkiptraceHistory

from juloserver.autodebet.constants import AutodebetVendorConst
from juloserver.autodebet.services.task_services import (
    determine_best_deduction_day
)
from juloserver.autodebet.constants import ExperimentConst
from juloserver.minisquad.constants import (
    FeatureNameConst as FeatureNameConstMiniSquad,
    DEFAULT_DB,
    REPAYMENT_ASYNC_REPLICA_DB,
)
from juloserver.minisquad.constants import ExperimentConst as MinisquadExperimentConstants
from juloserver.loan_refinancing.services.offer_related import \
        is_account_can_offered_refinancing
from juloserver.account_payment.constants import FeatureNameConst as AccountPaymentFeatureNameConst
from babel.dates import format_date
from juloserver.urlshortener.services import get_payment_detail_shortened_url

logger = logging.getLogger(__name__)


@julo_login_required
def change_account_payment_status(request, pk):
    user = request.user
    user_groups = user.groups.values_list('name', flat=True).all()
    today = timezone.localtime(timezone.now()).date()

    payment_obj = AccountPayment.objects.select_related(
                  'account',
                  'status').prefetch_related('payment_set').filter(id=pk).last()

    if not payment_obj:
        return redirect(
            '/account_payment_status/all/list?message=account_payment_id: %s tidak ditemukan' % pk)

    status_current = payment_obj.status
    account = payment_obj.account
    all_account_payments = account.accountpayment_set.all().normal().order_by('-due_date')
    sum_of_paid_amount = account.sum_of_all_account_payment_paid_amount()
    oldest_unpaid_account_payment = account.get_oldest_unpaid_account_payment()
    paid_account_payment = account.accountpayment_set.normal().paid().order_by('due_date')
    if oldest_unpaid_account_payment:
        paid_account_payment = paid_account_payment.filter(
            due_date__lte=oldest_unpaid_account_payment.due_date
        ).order_by('due_date').first()
    else:
        paid_account_payment = paid_account_payment.first()
    paid_account_payment_date = datetime.strftime(paid_account_payment.due_date,
                                                  "%Y-%m-%d") if paid_account_payment else ''
    template_name = 'object/payment_status/account_payment_change_status.html'
    message_out_ubah_status = None
    message_out_simpan_note = None
    ubah_status_active = 0
    simpan_note_active = 0

    application = account.last_application
    application.refresh_from_db()
    loan_obj = account.loan_set.all().last()
    sum_of_all_loan_amounts = account.sum_of_all_active_loan_amount()
    sum_of_all_installment_amounts = account.sum_of_all_active_installment_amount()
    payments_after_restructured = Payment.objects.select_related(
        'loan',
        'loan__lender'
    ).filter(account_payment=payment_obj).normal()
    sum_of_cashback_earned = payment_obj.total_cashback_earned()
    sum_of_cashback_redeemed = payment_obj.total_redeemed_cashback()
    application_id = application.id
    application_product_line = application.product_line
    customer = account.customer
    app_list = get_app_list_history(application)
    wallet_notes = get_wallet_list_note(customer)
    app_phone = [
        (application.mobile_phone_1, 'mobile_phone_1'),
        (application.mobile_phone_2, 'mobile_phone_2'),
        (application.spouse_mobile_phone, 'spouse_mobile_phone'),
        (application.kin_mobile_phone, 'kin_mobile_phone'),
        ('0', 'custom')
    ]

    robocall_templates = RobocallTemplate.objects.filter(is_active=True)
    robo_templates_map = {}
    for robocall_template in robocall_templates:
        robo_templates_map[str(robocall_template.id)] = robocall_template.text
    app_email = application.email

    # web_url
    # available_parameters = generate_wl_web_url(account)
    available_parameters = '#'   # temporary fix for high traffic in CRM

    autodebet_obj = AutodebetAccount.objects.filter(
        account=account, vendor=AutodebetVendorConst.BCA)

    # For the new additional fields on Crm-ADBCA agent menu
    autodebet_account_last = autodebet_obj.filter(
        is_use_autodebet=True,
        deduction_cycle_day__isnull=False).last()
    is_group_experiment = 'Tidak'
    deduction_cycle_day = None
    if autodebet_account_last:
        deduction_cycle_day = autodebet_account_last.deduction_cycle_day
    elif account:
        deduction_cycle_day = determine_best_deduction_day(account, raise_error=False)

    if deduction_cycle_day:
        experiment_setting = ExperimentSetting.objects.filter(
            code=ExperimentConst.BEST_DEDUCTION_TIME_ADBCA_EXPERIMENT_CODE).last()
        experiment_group = ExperimentGroup.objects.filter(
            experiment_setting=experiment_setting,
            account_id=account.id).last()
        if experiment_group and experiment_group.group == 'experiment':
            is_group_experiment = 'Ya'

    if request.method == 'POST':
        form = StatusChangesForm(status_current, request.POST)
        form_app_phone = ApplicationPhoneForm(app_phone, request.POST)
        form_email = SendEmailForm()
        if form.is_valid():
            if 'ubah_status' in request.POST:
                print("ubah_status-> valid here")

            status_to = form.cleaned_data['status_to']
            reason = form.cleaned_data['reason']
            notes = form.cleaned_data['notes']

            reason_arr = [item_reason.reason for item_reason in reason]
            reason = ", ".join(reason_arr)

            logger.info({
                'status_to': status_to,
                'reason': reason,
                'notes': notes
            })

            # TODO: call change_status_backend mapping
            ret_status = process_payment_status_change(
                payment_obj.id, status_to.status_code, reason, note=notes)
            print("ret_status: ", ret_status)
            if (ret_status):
                # form is sukses
                url = reverse('payment_status:change_status', kwargs={'pk': payment_obj.id})
                return redirect(url)
            else:
                # there is an error
                err_msg = """
                    Ada Kesalahan di Backend Server!!!, Harap hubungi Administrator
                """
                logger.info({
                    'app_id': payment_obj.id,
                    'error': "Ada Kesalahan di Backend Server with process_payment_status_change!!."
                })
                messages.error(request, err_msg)
                message_out_ubah_status = err_msg
                ubah_status_active = 1

        else:
            print("for is invalid and check notes")
            if 'simpan_note_to' in request.POST:
                try:
                    text_notes = form.cleaned_data['notes_only']
                    data = request.POST

                    if text_notes:
                        if data['simpan_note_to'] == 'application':
                            notes = ApplicationNote.objects.create(
                                note_text=text_notes,
                                application_id=application.id,
                                added_by_id=user.id,
                            )
                        else:
                            notes = AccountPaymentNote.objects.create(
                                note_text=text_notes,
                                account_payment=payment_obj)

                        logger.info({
                            'action': 'save_note',
                            'notes': notes,
                        })

                        url = reverse(
                            'account_payment_status:change_status',
                            kwargs={'pk': payment_obj.id}
                        )
                        return redirect(url)
                    else:
                        err_msg = """
                            Note/Catatan Tidak Boleh Kosong !!!
                        """
                        messages.error(request, err_msg)
                        message_out_simpan_note = err_msg
                        simpan_note_active = 1

                except Exception as e:
                    err_msg = """
                        Catatan Tidak Boleh Kosong !!!
                    """
                    messages.error(request, err_msg)
                    message_out_simpan_note = err_msg
                    simpan_note_active = 1
            elif 'autodebit_notes' in request.POST:
                try:
                    notes = form.cleaned_data['autodebit_notes']

                    if notes:
                        current_autodebet_obj = autodebet_obj.last()
                        current_autodebet_obj.notes = notes
                        current_autodebet_obj.save()

                        url = reverse('account_payment_status:change_status', kwargs={'pk': payment_obj.id})
                        return redirect(url)

                except Exception as e:
                    err_msg = """
                        Catatan Tidak Boleh Kosong !!!
                    """
                    message_out_simpan_note = err_msg
                    simpan_note_active = 1
            else:
                # form is not valid
                err_msg = """
                    Ubah Status atau Alasan harus dipilih dahulu !!!
                """
                messages.error(request, err_msg)
                message_out_ubah_status = err_msg
                ubah_status_active = 1

    else:
        form = StatusChangesForm(status_current)
        form_app_phone = ApplicationPhoneForm(app_phone)
        form_email = SendEmailForm()
        account.refresh_from_db()
        excluded_image_dict = dict()
        ojk_hide_document_feature_setting = FeatureSetting.objects.filter(
            feature_name=FeatureNameConstMiniSquad.HIDE_KTP_SELFIE_IMAGE_J1_ALL_300,
            is_active=True).last()
        if ojk_hide_document_feature_setting:
            parameters = ojk_hide_document_feature_setting.parameters
            excluded_image_dict = dict(
                image_type__in=parameters.get('excluded_image_type_list')
            )
        image_list = Image.objects.filter(
            image_source=application_id,
            image_status__in=[Image.CURRENT, Image.RESUBMISSION_REQ]
        ).exclude(**excluded_image_dict)
        image_list_paystub = Image.objects.filter(
            image_source=payment_obj.id,
            image_status__in=[Image.CURRENT, Image.RESUBMISSION_REQ]
        ).last()
        if image_list_paystub:
            image_list = (image_list | Image.objects.filter(pk=image_list_paystub.id)).distinct()
        results_json = ExtJsonSerializer().serialize(
            image_list,
            props=['image_url', 'image_ext'],
            fields=('image_type',)
        )

        image_list_1 = Image.objects.filter(
            image_source=application_id,
            image_status=Image.DELETED).exclude(**excluded_image_dict)
        image_list_1_paystub = Image.objects.filter(image_source=payment_obj.id,
                                                    image_status=Image.DELETED)
        image_list_1 = (image_list_1 | image_list_1_paystub).distinct()
        results_json_1 = ExtJsonSerializer().serialize(
            image_list_1,
            props=['image_url', 'image_ext'],
            fields=('image_type',)
        )
        voice_list = VoiceRecord.objects.filter(
            application=application_id,
            status__in=[VoiceRecord.CURRENT, VoiceRecord.RESUBMISSION_REQ]
        )
        results_json_2 = ExtJsonSerializer().serialize(
            voice_list,
            props=['presigned_url'],
            fields=('status')
        )

        voice_list_1 = VoiceRecord.objects.filter(
            application=application_id,
            status=VoiceRecord.DELETED
        )
        results_json_3 = ExtJsonSerializer().serialize(
            voice_list_1,
            props=['presigned_url'],
            fields=('status')
        )
        # *history_note_list move to lazy load
        skiptrace_list = (
            Skiptrace.objects.select_related('skiptracestats')
            .filter(customer_id=customer.id)
            .exclude(contact_source='kin_mobile_phone')
            .order_by('id')
        )
        skiptrace_history_model = SkiptraceHistory
        skiptrace_field_list = [
            'id', 'account_payment_id', 'account_id', 'application_id',
            'call_result_id', 'cdate', 'agent_name', 'call_result__name', 'callback_time',
            'skiptrace__phone_number', 'skiptrace__contact_source', 'spoke_with',
            'loan_id', 'payment_id', 'start_ts', 'end_ts', 'non_payment_reason',
        ]
        if account.is_grab_account():
            skiptrace_history_model = GrabSkiptraceHistory
        elif account.is_dana:
            skiptrace_history_model = DanaSkiptraceHistory
            skiptrace_field_list.remove('loan_id')
            skiptrace_field_list.remove('payment_id')

        skiptrace_history_list = skiptrace_history_model.objects.select_related(
            'skiptrace',
            'call_result',).only(*tuple(skiptrace_field_list)).filter(
            application_id=application_id).order_by('-cdate')[:2]
        cootek_payment = CootekRobocall.objects.filter(account_payment_id=payment_obj.id). \
                         order_by('-cdate')
        status_skiptrace = True
        # call_result = SkiptraceResultChoice.objects.all()

        # get fb data
        fb_obj = getattr(application, 'facebook_data', None)
        # get loan data and order by offer_number
        offer_set_objects = application.offer_set.all().order_by("offer_number")
        app_data = get_data_application_checklist_collection(application)
        deprecated_list = ['address_kodepos','address_kecamatan','address_kabupaten','bank_scrape',
                           'address_kelurahan','address_provinsi','bidang_usaha']
        form_payment = PaymentForm(instance=payment_obj, prefix='form2')
        form_app = ApplicationForm(instance=application, prefix='form2')
        form_app_select = ApplicationSelectFieldForm( application, prefix='form2')
        lock_status, lock_by = 0, None
        if application.product_line_code not in ProductLineCodes.grab():
            lock_status, lock_by = get_act_pmt_lock_status(payment_obj, user)

        wallets = CustomerWalletHistory.objects.select_related(
            'customer').prefetch_related(
            'customer__account_set').filter(
            customer=customer).order_by('-id')
        wallets = wallets.exclude(change_reason__contains='_old').order_by('-cdate')

        payment_event_detail = get_account_payment_events_transaction_level(payment_obj,
                                                                        user, user_groups)
        # change_due_date_active = check_change_due_date_active(
        # payment_obj, loan_obj, status_current)
        waiver_temps = WaiverTemp.objects.filter(account=account)
        loan_refinancing_status = None
        first_installment_btn_active = None
        if payment_obj:
            first_installment_btn_active = False
            if (not payment_obj.is_paid and
                    oldest_unpaid_account_payment and
                    oldest_unpaid_account_payment.status_id in [
                        PaymentStatusCodes.PAYMENT_NOT_DUE,
                        PaymentStatusCodes.PAYMENT_DUE_IN_3_DAYS,
                        PaymentStatusCodes.PAYMENT_DUE_TODAY,
                        PaymentStatusCodes.PAYMENT_DUE_IN_1_DAYS]):
                first_installment_btn_active = True

        if loan_obj:
            loan_refinancing = LoanRefinancing.objects.filter(loan=loan_obj).last()
            if loan_refinancing:
                if loan_refinancing.status == LoanRefinancingStatus.REQUEST:
                    loan_refinancing_status = 'Restructure Pending'
                elif loan_refinancing.status == LoanRefinancingStatus.ACTIVE:
                    loan_refinancing_status = 'Restructured'

        payment_methods = PaymentMethod.objects.filter(
            customer=customer).filter(
                Q(is_shown=True) | Q(payment_method_name__in=['Autodebet BCA', 'Autodebet BRI'])
            ).order_by('-is_primary','sequence')

        loan_refinancing_request = LoanRefinancingRequest.objects.filter(account=account).last()
        if loan_refinancing_request:
            loan_refinancing_status = get_refinancing_status_display(loan_refinancing_request)

        list_whatsapp_phone = skiptrace_list.filter(
                                contact_source__in=['mobile phone 1','mobile_phone1','mobile_phone 1','mobile_phone_1','Mobile phone 1'
                                                    'Mobile_phone_1','Mobile_Phone_1','mobile_phone1_1','mobile phone 2','mobile_phone2'
                                                    'mobile_phone 2','mobile_phone_2','Mobile phone 2','Mobile_phone2','Mobile_phone_2'
                                                    'MOBILE_PHONE_2']).order_by('contact_source')
        ptp_robocall_mobile_qs = skiptrace_list.filter(
            contact_source__in=['mobile_phone_1', 'mobile_phone_2']).values(
            'contact_source', 'phone_number')
        ptp_robocall_mobile_list = list(ptp_robocall_mobile_qs)
        if len(ptp_robocall_mobile_list) == 0:
            ptp_robocall_mobile_list.append(
                {'contact_source': 'mobile_phone_1', 'phone_number': application.mobile_phone_1})
            ptp_robocall_mobile_list.append(
                {'contact_source': 'mobile_phone_2', 'phone_number': application.mobile_phone_2})
        installment_form = NewPaymentInstallmentForm(request.POST)
        collection_agent_service = get_agent_service_for_bucket()
        agent_details = collection_agent_service.get_agent_account_payment([{'id': payment_obj.id}])

        # iso collection setting hide tab and button
        is_iso_inactive = True
        iso_st_source = ['mobile_phone_1',
                        'mobile_phone_2',
                        'kin_mobile_phone',
                        'close_kin_mobile_phone',
                        'company_phone_number',
                        'spouse_mobile_phone']
        iso_collection_setting = FeatureSetting.objects.filter(
            feature_name=FeatureNameConst.ISO_COLLECTION,
            category='collection', is_active=True).last()
        if iso_collection_setting:
            param = iso_collection_setting.parameters
            start_date = parse(param.get('start')).date()
            end_date = parse(param.get('end')).date()
            if start_date <= today <= end_date:
                is_iso_inactive = False
            elif today > end_date:
                iso_collection_setting.is_active = False
                iso_collection_setting.save()
                is_iso_inactive = True

        if not is_iso_inactive:
            image_list = image_list.filter(image_type__icontains='RECEIPT')

        is_for_ojk = False
        if user.crmsetting.role_select in JuloUserRoles.collection_bucket_roles():
            is_for_ojk = True
            image_list = image_list.filter(image_type__in=(
                ImageUploadType.PAYSTUB, 'crop_selfie', ImageUploadType.LATEST_PAYMENT_PROOF)
            )

        is_hidden_menu = FeatureSetting.objects.filter(
            feature_name=FeatureNameConst.CRM_HIDE_MENU,
            is_active=True).last()

        hide_tabs = []
        if is_hidden_menu and user.crmsetting.role_select in is_hidden_menu.parameters['roles']:
            hide_tabs = is_hidden_menu.parameters['menu']

        # only show current payment during transition to new integrated waiver
        # last_payment = AccountPayment.objects.filter(account=account).not_paid_active().order_by(
        #     '-cdate').last()
        # last_payment_number = payment_obj.payment_number
        # if last_payment:
        #     last_payment_number = last_payment.payment_number
        # total_max_waive_interest = get_remaining_interest(
        #     payment_obj, is_unpaid=False, max_payment_number=last_payment_number)
        # total_max_waive_late_fee = get_remaining_late_fee(
        #     payment_obj, is_unpaid=False, max_payment_number=last_payment_number)
        # total_max_waive_principal = get_remaining_principal(
        #     payment_obj, is_unpaid=False, max_payment_number=last_payment_number)

        provinces = ProvinceLookup.objects.filter(
            is_active=True
        ).order_by('province').values_list('province', flat=True)
        total_unpaid_due_amount = account.get_total_outstanding_due_amount()
        whatsapp_text = get_j1_whatsapp_collection_text(application, payment_obj,
                                                        loan_obj, payment_methods)
        no_contact_whatsapp_text = get_wa_message_is_5_days_unreachable(application)
        wa_contact_mobile_data = skiptrace_list.filter(
            contact_source__in=['mobile_phone_1', 'mobile_phone_2',
                                'kin_mobile_phone', 'close_kin_mobile_phone', 'spouse_mobile_phone']). \
            values('contact_source', 'phone_number')
        wa_contact_mobile_list = list(wa_contact_mobile_data)

        # check if is_5_days_uncontacted, is_broken_ptp_plus_1
        is_5_days_unreachable = False
        is_broken_ptp_plus_1 = False
        broken_ptp_whatsapp_text = ""

        if  oldest_unpaid_account_payment and (oldest_unpaid_account_payment.id == payment_obj.id):
            is_5_days_unreachable = account.is_5_days_unreachable
            is_broken_ptp_plus_1 = account.is_broken_ptp_plus_1
            if is_broken_ptp_plus_1:
                broken_ptp_whatsapp_text = get_wa_message_is_broken_ptp_plus_1(oldest_unpaid_account_payment, application)

        is_multiple_factors = False
        if is_broken_ptp_plus_1 and is_5_days_unreachable:
            is_multiple_factors = True

        # Generate PTP details.

        skiptrace_result_choice = SkiptraceResultChoice.objects.filter(
            name='RPC - PTP'
        ).first()

        ptp_st_map = {}
        
        account_payment = AccountPayment.objects.get_or_none(pk=pk)
        application = account_payment.account.last_application
        workflow = application.workflow
        
        if workflow.name == WorkflowConst.DANA:
            ptp_st_history_list = DanaSkiptraceHistory.objects.filter(
                Q(account_payment_id=pk) &
                Q(call_result_id=skiptrace_result_choice.id)
            ).only('skiptrace', 'cdate', 'account_payment_status').prefetch_related(
                Prefetch('skiptrace', queryset=Skiptrace.objects.only('contact_source', 'phone_number'))
            )
        elif workflow.name == WorkflowConst.GRAB:
            ptp_st_history_list = GrabSkiptraceHistory.objects.filter(
                Q(account_id=account_payment.account.id) &
                Q(call_result_id=skiptrace_result_choice.id)
            ).only('skiptrace', 'cdate', 'account_payment_status').prefetch_related(
                Prefetch('skiptrace', queryset=Skiptrace.objects.only('contact_source', 'phone_number'))
            )
        else:
            ptp_st_history_list = SkiptraceHistory.objects.filter(
                Q(account_payment_id=pk) &
                Q(call_result_id=skiptrace_result_choice.id)
            ).only('skiptrace', 'cdate', 'account_payment_status').prefetch_related(
                Prefetch('skiptrace', queryset=Skiptrace.objects.only('contact_source', 'phone_number'))
            )
        
        for e in ptp_st_history_list:
            st = e.skiptrace
            curr_st_history_key = str(e.cdate.date())
            if curr_st_history_key not in ptp_st_map:
                ptp_st_map[curr_st_history_key] = {
                    'source': st.contact_source,
                    'phone_number': st.phone_number,
                    'account_payment_status': e.account_payment_status,
                    'cdate': e.cdate,
                }
                continue
            
            curr_ptp_skiptrace = ptp_st_map[curr_st_history_key]
            if e.cdate > curr_ptp_skiptrace['cdate']:
                curr_ptp_skiptrace = {
                    'source': st.contact_source,
                    'phone_number': st.phone_number,
                    'account_payment_status': e.account_payment_status,
                    'cdate': e.cdate,
                }
        
        ptp_ids = set()
        ptp_details = []
        ptp_list = PTP.objects.filter(account_payment_id=pk).order_by('-cdate')
        for ptp in ptp_list:
            ptp_parent = ptp.ptp_parent
            if ptp_parent:
                ptp = ptp_parent
            
            # Make sure no double ptp is listed.
            ptp_id = ptp.id
            if ptp_id in ptp_ids:
                continue

            ptp_ids.add(ptp_id)
            
            ptp_agent = ''
            if ptp.agent_assigned:
                ptp_agent = ptp.agent_assigned.username
            
            source, phone_number, account_payment_status = '', '', ''

            curr_st_history_key = str(ptp.cdate.date())            
            if curr_st_history_key in ptp_st_map:
                curr_val = ptp_st_map[curr_st_history_key]
                source = curr_val['source']
                phone_number = curr_val['phone_number']
                account_payment_status = curr_val['account_payment_status']    
            
            ptp_details.append({
                'ptp_created': ptp.cdate,
                'event_date': ptp.udate,
                'status': ptp.ptp_status,
                'amount': ptp.ptp_amount,
                'ptp_date': ptp.ptp_date,
                'agent': ptp_agent,
                'phone_number': phone_number,
                'source': source,
                'account_payment_status': account_payment_status,
            })

        is_ojk_audit_active = FeatureSetting.objects.filter(
            feature_name=FeatureNameConst.OJK_AUDIT_FEATURE,
            is_active=True).exists()
        experiment_info = None
        _, experiment_data = get_experiment_group_data(
            MinisquadExperimentConstants.LATE_FEE_EARLIER_EXPERIMENT,
            payment_obj.account_id)
        if experiment_data:
            experiment_info = 'Late fee dpd 1, {}'.format(
                'No' if experiment_data.group == 'control' else 'Yes')
        is_can_refinancing = is_account_can_offered_refinancing(payment_obj.account)
        # TODO adjust unit test

        uninstall_indicator = get_uninstall_indicator_from_moengage_by_customer_id(customer.id)

        fdc_risky = None
        fdc_risky_udate = '-'
        fdc_risky_history = FDCRiskyHistory.objects.filter(application_id=application.id).last()
        if fdc_risky_history:
            fdc_risky = fdc_risky_history.is_fdc_risky
            fdc_risky_udate = format_date(fdc_risky_history.udate, "d MMM yyyy", locale="id_ID")

        cashback_counter = account.cashback_counter or 0
        potensi_cashback, total_cashback_earned = get_potential_and_total_cashback(payment_obj, cashback_counter, customer.id)

        is_superuser = user.is_superuser
        if is_superuser:
            restrict_data_for_sales_ops_role = False
        else:
            restrict_data_for_sales_ops_role = user.groups.filter(name=JuloUserRoles.SALES_OPS).exists()

        return render(
            request,
            template_name,
            {
                'form': form,
                'payment_obj': payment_obj,
                'restrict_data_for_sales_ops_role': restrict_data_for_sales_ops_role,
                'max_cashback_earned': payment_obj.max_cashback_earned(),
                'application': application,
                'customer': customer,
                'application_product_line': application_product_line,
                'fb_obj': fb_obj,
                'status_current': status_current,
                'image_list': image_list,
                'json_image_list': results_json,
                'image_list_1': image_list_1,
                'json_image_list_1': results_json_1,
                'voice_list': voice_list,
                'json_voice_list': results_json_2,
                'voice_list_1': voice_list_1,
                'json_voice_list_1': results_json_3,
                'datetime_now': timezone.now(),
                'image_per_row0': [1, 7, 13, 19, 25],
                'image_per_row': [7, 13, 19, 25],
                'message_out_simpan_note': message_out_simpan_note,
                'message_out_ubah_status': message_out_ubah_status,
                'ubah_status_active': ubah_status_active,
                'simpan_note_active': simpan_note_active,
                'form_app_phone': form_app_phone,
                'form_send_email': form_email,
                'app_email': app_email,
                'app_list': app_list,
                'offer_set_objects': offer_set_objects,
                'loan_obj': loan_obj,
                'skiptrace_list': skiptrace_list,
                'skiptrace_history_list': skiptrace_history_list,
                'cootek_payment' : cootek_payment,
                'status_skiptrace': status_skiptrace,
                'application_id': application_id,
                'customer_id': customer.id,
                'payment_id': pk,
                'app_data':app_data,
                'deprecatform_apped_list':deprecated_list,
                'deprecated_list': deprecated_list,
                'form_app':form_app,
                'form_app_select':form_app_select,
                'form_payment':form_payment,
                'payment_methods' : payment_methods,
                'button_lock' : get_account_payment_lock_count(payment_obj),
                'lock_status': lock_status,
                'lock_by': lock_by,
                'is_payment_called' : 0,
                'bank_name_list':json.dumps(list(BankLookup.objects.all(). \
                                 values_list('bank_name', flat=True))),
                'wallets': wallets,
                'wallet_notes': wallet_notes,
                'wallet_balance_available': customer.wallet_balance_available,
                'payment_event_detail': payment_event_detail,
                # 'change_due_date_active': change_due_date_active,
                'first_installment_btn_active': first_installment_btn_active,
                'list_whatsapp_phone':list_whatsapp_phone,
                'robocall_templates': robocall_templates,
                'robo_templates_map': json.dumps(robo_templates_map),
                'ptp_robocall_mobile_list': ptp_robocall_mobile_list,
                'installment_form': installment_form,
                'agent_details': agent_details[0],
                'is_iso_inactive': is_iso_inactive,
                'iso_st_source': iso_st_source,
                'is_for_ojk': is_for_ojk,
                'hide_tabs': hide_tabs,
                'is_ojk_audit_active': is_ojk_audit_active,
                # only show current payment during transition to new integrated waiver
                'payment_number_list': sorted((payment_obj.id, ), reverse=True),
                'waiver_temps': waiver_temps,
                # 'total_max_waive_interest' : total_max_waive_interest,
                # 'total_max_waive_late_fee' : total_max_waive_late_fee,
                # 'total_max_waive_principal': total_max_waive_principal,
                # 'total_max_waive_principal_input': total_max_waive_principal - 1,
                # 'total_max_waive_principal_paid': payment_obj.installment_principal - payment_obj.paid_principal,
                # 'total_max_waive_interest_paid': payment_obj.installment_interest - payment_obj.paid_interest,
                # 'total_max_waive_late_fee_paid': payment_obj.late_fee_amount - payment_obj.paid_late_fee,
                'loan_refinancing_status': loan_refinancing_status,
                'payment_event_reversal_reason' : PAYMENT_EVENT_CONST.REVERSAL_REASONS,
                'reversal_reason_show_move_payment': PAYMENT_EVENT_CONST.REVERSAL_REASON_WRONG_PAYMENT,
                'payments': payments_after_restructured,
                'all_account_payments': all_account_payments,
                'sum_of_paid_amount': sum_of_paid_amount,
                'sum_of_cashback_earned':sum_of_cashback_earned,
                'sum_of_cashback_redeemed':sum_of_cashback_redeemed,
                'sum_of_all_loan_amounts':sum_of_all_loan_amounts,
                'sum_of_all_installment_amounts': sum_of_all_installment_amounts,
                'customer_bucket_type': check_customer_bucket_type_account_payment(payment_obj),
                'provinces': provinces,
                'user': user,
                'available_parameters': available_parameters,
                'whatsapp_text': whatsapp_text,
                'paid_status_codes': PaymentStatusCodes.paid_status_codes_without_sell_off,
                'paid_account_payment_date': paid_account_payment_date,
                'total_unpaid_due_amount': total_unpaid_due_amount or 0,
                'no_contact_whatsapp_text': no_contact_whatsapp_text,
                'wa_contact_mobile_list': wa_contact_mobile_list,
                'is_5_days_unreachable':is_5_days_unreachable,
                'is_broken_ptp_plus_1': is_broken_ptp_plus_1,
                'broken_ptp_whatsapp_text': broken_ptp_whatsapp_text,
                'is_multiple_factors': is_multiple_factors,
                'autodebet_bank_name': get_autodebet_bank_name(account),
                'is_sms_email_button_unlocked': not is_crm_sms_email_locking_active(),
                'account': account,
                'ptp_details': ptp_details,
                'autodebet_obj': autodebet_obj.order_by('-registration_ts'),
                'deduction_cycle_day': deduction_cycle_day,
                'is_group_experiment': is_group_experiment,
                'agent_id': user.id,
                'experiment': experiment_info,
                'is_can_refinancing': 'Ya' if is_can_refinancing else 'Tidak',
                'uninstall_indicator': uninstall_indicator,
                'fdc_risky': fdc_risky,
                'fdc_risky_udate': fdc_risky_udate,
                'potential_cashback': potensi_cashback,
                'total_cashback_earned': total_cashback_earned,
                'new_j1_enhancement': FeatureSetting.objects.filter(
                    feature_name=AccountPaymentFeatureNameConst.CRM_CUSTOMER_DETAIL_TAB,
                    is_active=True,
                ).exists(),
                'is_julo_one_or_starter': application.is_julo_one_or_starter,
                'payment_detail_url': None,
                # 'payment_detail_url': (
                #     get_payment_detail_shortened_url(payment_obj)
                #     if account_payment
                #     and 300 <= account_payment.status_id < 400
                #     and application.is_julo_one_or_starter
                #     else None
                # ),
            }
        )


@julo_login_required
@julo_login_required_exclude(['bo_credit_analyst'])
def account_payment_list_view(request, status_code):
    # check if there is statuslookup which matches the statuslookup (if not then display 404)
    template_name = 'object/account_payment_status/list.html'
    #get parameters url
    search_q = request.GET.get('search_q', '')
    message = request.GET.get('message', '')
    filter_category = request.GET.get('filter_category', '')
    filter_special_condition = request.GET.get('filter_special_condition', '')
    status_app = request.GET.get('status_app', '')
    #init variabel
    list_show_filter_agent = ['Collection supervisor T+1, T+4', 'Collection supervisor T+5, T+15', 'Collection supervisor T+16, T+29',
                              'Collection supervisor T+30, T+44', 'Collection supervisor T+45, T+59', 'Collection supervisor T+60, T+74',
                              'Collection supervisor T+60, T+74', 'Collection supervisor T+75, T+89', 'Collection supervisor T+90, T+119',
                              'Collection supervisor T+120, T+179', 'Collection supervisor T+179++',
                              'Collection supervisor PTP', 'Collection supervisor ignore called', 'Collection supervisor whatsapp', 'all',
                              'Collection Supervisor bucket T+1, T+4', 'Collection Supervisor bucket T+5, T+10',
                              'Collection Supervisor bucket T+11, T+25', 'Collection Supervisor bucket T+26, T+40',
                              'Collection Supervisor bucket T+41, T+55', 'Collection Supervisor bucket T+56, T+70',
                              'Collection Supervisor bucket T+71, T+85', 'Collection Supervisor bucket T+86, T+100',
                              'Collection supervisor T+101 >> ++', 'Collection Supervisor bucket 1 PTP',
                              'Collection Supervisor bucket 2 PTP', 'Collection Supervisor bucket 3 PTP',
                              'Collection Supervisor bucket 4 PTP', 'Collection Supervisor bucket 5 PTP',
                              'Collection Supervisor bucket 1 WA', 'Collection Supervisor bucket 2 WA',
                              'Collection Supervisor bucket 3 WA', 'Collection Supervisor bucket 4 WA',
                              'Collection Supervisor bucket 5 WA', 'Collection Supervisor Bucket 3 Ignore Called',
                              'Collection Supervisor Bucket 4 Ignore Called', 'Collection Supervisor Bucket 5 Ignore Called']
    try:
        title_status = payment_parse_pass_due(status_code)
        if title_status:
            title_status = title_status[1]
        else:
            if status_app:
                title_status = str(status_app)
            else:
                title_status = 'all'
        if status_code == 'all':
            status_show = status_code
        else:
            status_show = 'with_status'
    except:
        status_code = 'all'
        status_show = 'with_status'

    return render(
        request,
        template_name,
        {
            'status_code': status_code,
            'status_show': status_show,
            'status_title': title_status,
            'status_app': status_app,
            'search_q': search_q,
            'filter_category': filter_category,
            'filter_special_condition': filter_special_condition,
            'list_show_filter_agent': list_show_filter_agent,
            'redirect_message': message
        }
    )


@csrf_protect
def add_account_transaction(request):

    if request.method == 'POST':
        user = request.user
        data = request.POST.dict()
        account_payment = AccountPayment.objects.get(pk=data['account_payment_id'])
        if not account_payment:
            return HttpResponse(
                json.dumps({
                    "messages": "account_payment id not found : %s " % (data['account_payment_id']),
                    "result": "failed"}),
                content_type="application/json")
        messages_response = "payment event not success"
        result = 'failed'

        if data['event_type'] == 'payment':
            account = account_payment.account
            application = account.application_set.last()
            partial_payment = parse_number(data['partial_payment'], locale='id_ID')
            if partial_payment <= 0:
                return HttpResponse(
                    json.dumps({"messages": "Can not input negative value", "result": "failed"}),
                    content_type="application/json"
                )

            total_outstanding_amount = account.get_total_outstanding_amount()
            if application.is_julover() and partial_payment > total_outstanding_amount:
                status = False
                messages_response = 'payment cannot be overpaid'
            else:
                status, messages_response = process_account_manual_payment(user, account_payment, data)
        if status:
            messages_response = "payment event success"
            result = 'success'
        return HttpResponse(
            json.dumps({
                "messages": messages_response,
                "result": result}),
            content_type="application/json")


@csrf_protect
def ajax_reversal_account_payment_event(request):
    """
    """
    current_user = request.user
    response_data = {}

    if request.method != 'POST':
        return HttpResponseNotAllowed(["POST"])

    data = request.POST.dict()
    account_transaction_object = AccountTransaction.objects.get(pk=data['event_id'])

    if not account_transaction_object:
        return HttpResponse(json.dumps({
            "result": "failed",
            "message": "payment event not found"
        }), content_type="application/json")

    event_type = account_transaction_object.transaction_type
    if event_type not in ['payment', 'late_fee', 'customer_wallet']:
        return HttpResponse(json.dumps({
            "result": "failed",
            "message": "payment event not initiate process"
        }), content_type="application/json")

    try:
        if event_type in ['payment', 'customer_wallet']:
            account_destination_obj = None
            if data['reason'] == PAYMENT_EVENT_CONST.REVERSAL_REASON_WRONG_PAYMENT and data['account_dest_id']:
                account_destination_obj = Account.objects.get_or_none(pk=data['account_dest_id'])
            process_customer_payment_reversal(account_transaction_object, account_destination_obj,  data['note'])
        elif event_type == "late_fee":
            process_late_fee_reversal(account_transaction_object, data['note'])
        messages = "reverse payment event success"
        result = 'success'
        return HttpResponse(
            json.dumps({
                "messages": messages,
                "result": result}),
            content_type="application/json")
    except LateFeeException:
        messages = 'Tidak dapat void, karena terdapat 2 account payment atau lebih yang memiliki late fee'
        result = 'failed'
        return HttpResponse(
            json.dumps({
                "messages": messages,
                "result": result,
                "multiple_account_payment_flag":True}),
            content_type="application/json")
    except JuloException:
        messages = "reverse payment event not success"
        result = 'failed'
        return HttpResponse(
            json.dumps({
                "messages": messages,
                "result": result,
                "multiple_account_payment_flag":False}),
            content_type="application/json")


@csrf_protect
def reversal_payment_event_check_account_destination(request):
    current_user = request.user
    response_data = {}

    if request.method != 'POST':
        return HttpResponseNotAllowed(["POST"])
    account_id = int(request.POST.get('account_id'))
    account_obj = Account.objects.get_or_none(pk=account_id)
    if account_obj:
        if not account_obj.get_unpaid_account_payment_ids():
            response_data['result'] = 'failed'
            response_data['message'] = 'Account ID %s sudah lunas silahkan cek kembali' % account_id
        else:
            application = account_obj.application_set.last()
            response_data['result'] = 'success'
            response_data['message'] = '%s (%s)' % (application.fullname, application.id)
    else:
        response_data['result'] = 'failed'
        response_data['message'] = 'Account ID %s tidak ditemukan silahkan cek kembali' % account_id

    return HttpResponse(
        json.dumps(response_data),
        content_type="application/json"
    )


@csrf_protect
def send_sms(request):
    from juloserver.warning_letter.services import (generate_wl_web_url)
    if request.method == 'GET':

        account_payment_id = request.GET.get('account_payment_id')
        account_payment = AccountPayment.objects.get_or_none(id=account_payment_id)
        if account_payment is None:
            return HttpResponse(
                json.dumps({
                    'result': 'nok',
                    'error_message': "Account Payment=%s not found" % account_payment_id
                }),
                content_type="application/json")

        if not account_payment.account.customer.can_notify:
            return HttpResponse(
                json.dumps({
                    'result': 'nok',
                    'error_message': "Can not notify to this customer"
                }),
                content_type="application/json")

        sms_message = request.GET.get('sms_message').strip()

        to_number = request.GET.get('to_number')
        phone_type = request.GET.get('phone_type')
        category = request.GET.get('category')
        template_code = request.GET.get('template_code')
        if sms_message == '':
            return HttpResponse(
                json.dumps({
                    'result': 'nok',
                    'error_message': "Message is empty"
                }),
                content_type="application/json")

        try:
            send_custom_sms_account_payment_reminder(
                account_payment, to_number,
                phone_type, category, sms_message, template_code)

        except SmsNotSent as sns:
            return HttpResponse(
                json.dumps({
                    'result': 'nok',
                    'error_message': str(sns)
                }),
                content_type="application/json")

        return HttpResponse(
            json.dumps({
                'result': 'successful!',
            }),
            content_type="application/json")


@csrf_protect
def send_email(request):
    if request.method == 'GET':
        account_payment_id = request.GET.get('account_payment_id')
        account_payment = AccountPayment.objects.get_or_none(id=account_payment_id)
        if account_payment is None:
            return HttpResponse(
                json.dumps({
                    'result': 'nok',
                    'error_message': "Account Payment=%s not found" % account_payment_id
                }),
                content_type="application/json")

        if not account_payment.account.customer.can_notify:
            return HttpResponse(
                json.dumps({
                    'result': 'nok',
                    'error_message': "Can not notify to this customer"
                }),
                content_type="application/json")

        email_content = request.GET.get('content')

        to_email = request.GET.get('to_email')
        subject = request.GET.get('subject')
        category = request.GET.get('category')
        template_code = request.GET.get('template_code')
        pre_header = request.GET.get('pre_header')
        valid_email = check_email(to_email)

        if not valid_email:
            return HttpResponse(
                json.dumps({
                    'result': 'nok',
                    'error_message': "Invalid Email Address"
                }),
                content_type="application/json")

        if email_content == '':
            return HttpResponse(
                json.dumps({
                    'result': 'nok',
                    'error_message': "Message is empty"
                }),
                content_type="application/json")

        try:
            send_custom_email_account_payment_reminder(
                account_payment, to_email, subject, email_content, category, pre_header, template_code)

        except EmailNotSent as ens:
            return HttpResponse(
                json.dumps({
                    'result': 'nok',
                    'error_message': str(ens)
                }),
                content_type="application/json")

        return HttpResponse(
            json.dumps({
                'result': 'successful!',
            }),
            content_type="application/json")


@csrf_protect
def ajax_account_payment_list_view(request):
    if request.method != 'GET':
        return HttpResponseNotAllowed(["GET"])

    if not getattr(request.user, 'agent', None):
        return HttpResponse(
            json.dumps({
                "status": "failed",
                "message": "Session Login Expired, Silahkan Login Kembali"
            }),
            content_type="application/json"
        )

    search_category = request.GET.get('filter_category')
    status_code = request.GET.get('status_code')
    max_per_page = int(request.GET.get('max_per_page'))
    here_title_status = None
    user = request.user
    agent_service = get_agent_service()
    squad = getattr(request.user.agent, 'squad', None)

    sort_partner = request.GET.get('sort_partner')

    try:
        page = int(request.GET.get('page'))
    except:
        page = 1

    if status_code != 'None':
        pass
        # alter query deep
    else:
        status_code = "all"

    list_status = StatusLookup.objects.filter(
        status_code__in=PaymentStatusCodes.account_payment_status_codes() + JuloOneCodes.all())\
        .values('status_code', 'status')

    list_agent_type = []
    agent_roles = JuloUserRoles.collection_bucket_roles()
    for role in agent_roles:
        list_agent_type.append(
            dict(value=role,
                 label='{} - {}'.format(
                     role, convert_usergroup_to_agentassignment_type(role))
                 )
        )

    list_agent = User.objects.filter(groups__name__in=agent_roles,
                                     is_active=True) \
        .order_by('id') \
        .values('id', 'username', 'groups__name')
    sort_q = request.GET.get('sort_q', None)
    sort_agent = request.GET.get('sort_agent', None)
    status_payment = request.GET.get('status_app', None)

    qs = AccountPayment.objects.exclude(is_restructured=True).select_related('status', 'account')
    if status_payment and status_code in ['all', 'partner']:
        if str(status_payment)[0] == '4':
            qs = qs.filter(account__status__status_code=status_payment)
        else:
            qs = qs.filter(status__status_code=status_payment)

    search_q = request.GET.get('search_q', None).strip()
    today_checked = request.GET.get('today_checked', None)
    freeday_checked = request.GET.get('freeday_checked', None)
    range_date = request.GET.get('range_date', None)
    autodialer_result = AutoDialerRecord.objects.all() \
        .order_by('payment_id') \
        .values('payment_id', 'call_status')

    # searching
    special_condition = request.GET.get('filter_special_condition')
    if special_condition:
        oldest_unpaid_account_payment_ids = get_oldest_unpaid_account_payment_ids()
        spacial_condition_filter_ = {
            'account__' + special_condition: True,
            'id__in': oldest_unpaid_account_payment_ids
        }
        if spacial_condition_filter_:
            qs = qs.filter(**spacial_condition_filter_)


    if isinstance(search_q, str) and search_q:
        qs = account_payment_filter_search_field(qs, search_category, search_q)

    # product line filter
    filter_pline_category = request.GET.get('filter_pline_category', '')
    if filter_pline_category.isdigit():
        # sanitize parameter
        filter_pline_category = int(filter_pline_category)
        # get latest application id
        latest_application_ids = Application.objects.filter(account__in=qs.values_list('account_id', flat=True)).distinct('account_id').order_by('account_id', '-cdate').values_list('id', flat=True)
        # filter by latest application with product line id
        qs = qs.filter(account__application__product_line_id=filter_pline_category, account__application__in=latest_application_ids)

    # datefilters
    if today_checked != 'false' or freeday_checked != 'false' and range_date != '':
        if today_checked == 'true':
            startdate = datetime.today()
            startdate = startdate.replace(hour=0, minute=0, second=0)
            enddate = startdate + timedelta(days=1)
            enddate = enddate - timedelta(seconds=1)
            qs = qs.filter(cdate__range=[startdate, enddate])

        elif freeday_checked == 'true':
            _date_range = range_date.split('-')
            if (_date_range[0].strip() != 'Invalid date'):
                _tgl_mulai = datetime.strptime(_date_range[0].strip(), "%d/%m/%Y %H:%M")
                _tgl_end = datetime.strptime(_date_range[1].strip(), "%d/%m/%Y %H:%M")
                if (_tgl_end > _tgl_mulai):
                    qs = qs.filter(cdate__range=[_tgl_mulai, _tgl_end])
                else:
                    return HttpResponse(
                        json.dumps({
                            "status": "failed",
                            "message": "Tgl Sampai Harus Lebih besar dari Tgl Dari"
                        }),
                        content_type="application/json"
                    )
            else:
                return HttpResponse(
                    json.dumps({
                        "status": "failed",
                        "message": "Format Tanggal tidak valid"
                    }),
                    content_type="application/json"
                )

    if sort_q:
        qs = qs.order_by(sort_q)

    if sort_agent:
        if sort_agent != '':
            qs = agent_service.filter_account_payments_by_agent_id(qs, sort_agent)

    # for pagination
    if qs.model is Payment:
        collection_values = ['id', 'loan__application__product_line_id', \
                             'loan__application__email', 'loan__application__fullname', \
                             'is_robocall_active', 'payment_status_id', 'due_date',
                             'payment_number', \
                             'loan_id', 'loan__loan_status_id', 'udate', 'cdate',
                             'loan__application__partner__name', \
                             'loan__application_id', 'loan__application__customer_id', \
                             'due_amount', 'late_fee_amount', 'cashback_earned',
                             'loan__application__mobile_phone_1', \
                             'loan__application__ktp', 'loan__application__dob',
                             'loan__loan_amount', \
                             'loan__loan_duration', 'loan__application__id',
                             'payment_status__status_code', \
                             'loan__id', 'loan__application__email',
                             'loan__julo_bank_account_number', \
                             'ptp_date', 'reminder_call_date', 'paid_date']
    elif qs.model is CollectionHistory:
        collection_values = ['payment__id', 'loan__application__product_line_id', \
                             'loan__application__email', 'loan__application__fullname', \
                             'payment__is_robocall_active', 'payment__payment_status_id',
                             'payment__due_date', 'payment__payment_number', \
                             'loan_id', 'loan__loan_status_id', 'payment__udate', 'payment__cdate',
                             'loan__application__partner__name', \
                             'loan__application_id', 'loan__application__customer_id', \
                             'payment__due_amount', 'payment__late_fee_amount',
                             'payment__cashback_earned', 'loan__application__mobile_phone_1', \
                             'loan__application__ktp', 'loan__application__dob',
                             'loan__loan_amount', \
                             'loan__loan_duration', 'loan__application__id',
                             'payment__payment_status__status_code', \
                             'loan__id', 'loan__application__email',
                             'loan__julo_bank_account_number', \
                             'payment__ptp_date', 'payment__reminder_call_date',
                             'squad__squad_name', 'payment__paid_date']
    elif qs.model is SkiptraceHistory:
        collection_values = ['payment__id', 'loan__application__product_line_id',
                             'loan__application__email', 'loan__application__fullname',
                             'payment__is_robocall_active', 'payment__payment_status_id',
                             'payment__due_date', 'payment__payment_number',
                             'loan_id', 'loan__loan_status_id', 'payment__udate', 'payment__cdate',
                             'loan__application__partner__name', 'loan__application__customer_id',
                             'payment__due_amount',
                             'payment__late_fee_amount', 'payment__cashback_earned',
                             'loan__application__mobile_phone_1', 'loan__application__ktp',
                             'loan__application__dob',
                             'loan__loan_amount', 'loan__loan_duration',
                             'loan__application_id', 'payment__payment_status__status_code',
                             'loan__julo_bank_account_number', 'payment__ptp_date',
                             'payment__reminder_call_date', 'payment__paid_date']
    elif qs.model is GrabSkiptraceHistory:
        collection_values = ['payment__id', 'loan__application__product_line_id',
                             'loan__application__email', 'loan__application__fullname',
                             'payment__is_robocall_active', 'payment__payment_status_id',
                             'payment__due_date', 'payment__payment_number',
                             'loan_id', 'loan__loan_status_id', 'payment__udate', 'payment__cdate',
                             'loan__application__partner__name', 'loan__application__customer_id',
                             'payment__due_amount',
                             'payment__late_fee_amount', 'payment__cashback_earned',
                             'loan__application__mobile_phone_1', 'loan__application__ktp',
                             'loan__application__dob',
                             'loan__loan_amount', 'loan__loan_duration',
                             'loan__application_id', 'payment__payment_status__status_code',
                             'loan__julo_bank_account_number', 'payment__ptp_date',
                             'payment__reminder_call_date', 'payment__paid_date']

    elif qs.model is AccountPayment:
        collection_values = ['id', 'cdate', 'due_amount', 'due_date', 'account_id',
                             'account__customer__email',
                             'account__customer_id',
                             'account__customer__fullname', 'account__customer__nik',
                             'account__customer__dob', 'interest_amount', 'is_locked',
                             'late_fee_amount', 'late_fee_applied',
                             'locked_by_id', 'paid_amount', 'paid_date', 'paid_interest',
                             'paid_late_fee', 'paid_principal',
                             'principal_amount', 'account__status__status_code', 'status_id',
                             'udate']

    processed_model = qs.model
    primary_key = 'id'

    three_next_pages = max_per_page * (page + 2) + 1
    limit = max_per_page * page
    offset = limit - max_per_page

    result = qs.values_list(primary_key, flat=True)
    result = result[offset:three_next_pages]
    account_payment_ids = list(result)
    account_payment_ids_1page = account_payment_ids[:max_per_page]
    count_account_payment = len(account_payment_ids)
    count_page = page + (count_account_payment // max_per_page) + (
                count_account_payment % max_per_page > 0) - 1
    if count_account_payment == 0:
        count_page = page

    # this preserved is needed because random order by postgresql/django
    preserved = Case(*[When(pk=pk, then=pos) for pos, pk in enumerate(result)])

    account_payments = processed_model.objects\
        .filter(**{primary_key + '__in': account_payment_ids_1page})\
        .order_by(preserved)\
        .select_related('account')

    # Eager loading stuff
    account_payments_values = list(account_payments.values(*collection_values))
    account_ids = [apv['account_id'] for apv in account_payments_values]
    application_fields = [
        'id', 'fullname', 'mobile_phone_1', 'ktp', 'dob', 'customer_id', 'product_line_id'
    ]
    total_loan_amount_dict = get_loan_amount_dict_by_account_ids(account_ids)
    latest_loan_dict = get_latest_loan_dict_by_account_ids(account_ids, ['loan_duration'])
    total_cashback_dict = get_cashback_earned_dict_by_account_payment_ids(account_payment_ids_1page)
    latest_application_dict = get_latest_application_dict_by_account_ids(
        account_ids, fields=application_fields, select_related=['product_line'])

    for ap, apv in zip(account_payments, account_payments_values):
        application = latest_application_dict.get(ap.account_id)
        if application:
            application_details = {
                "application_" + key: getattr(application, key) for key in application_fields
            }
            apv.update(application_details)
            apv['application_product_line_type'] = application.product_line.product_line_type \
                if application.product_line else None
        extra_data = {
            'dpd': ap.dpd,
            'total_cashback_earned': total_cashback_dict.get(ap.id)
        }
        loan = latest_loan_dict.get(ap.account_id)
        if loan:
            extra_data['loan_duration'] = loan.loan_duration
            extra_data['total_loan_amount'] = total_loan_amount_dict.get(ap.account_id)
        apv.update(extra_data)

    list_partner = Partner.objects.all().values('id', 'name')
    pline_categories = ProductLine.objects.all().order_by('product_line_type').values('product_line_code', 'product_line_type')

    return JsonResponse({
        'status': 'success',
        'data': account_payments_values,
        'count_page': count_page,
        'current_page': page,
        'list_status': list(list_status),
        'list_agent': list(list_agent),
        'autodialer_result': list(autodialer_result),
        'list_agent_type': list_agent_type,
        'list_partner': list(list_partner),
        'payment_paid_status': PaymentStatusCodes.PAID_ON_TIME,
        'search_categories': SearchCategory.ALL,
        'special_conditions': SpecialConditions.ALL,
        'pline_categories': list(pline_categories)
    }, safe=False)


def account_payment_filter_search_field(qs, search_category, search_q):
    if not search_category:
        return qs
    if search_category in [SearchCategory.ACCOUNT_PAYMENT_ID, SearchCategory.ACCOUNT_ID, SearchCategory.APPLICATION_ID]:
        search_q = re.sub(r"\D", "", search_q)
        search_q = int(search_q) if search_q else 0
    if search_category == SearchCategory.ACCOUNT_PAYMENT_ID:
        qs = qs.filter(id=search_q)
    elif search_category == SearchCategory.ACCOUNT_ID:
        qs = qs.filter(account_id=search_q)
    elif search_category == SearchCategory.APPLICATION_ID:
        qs = qs.filter(account__application__id=search_q)
    elif search_category == SearchCategory.MOBILE_NUMBER:
        if search_q.startswith('+'):
            search_q = search_q[1:]
        qs = qs.filter(account__application__mobile_phone_1=search_q)
    elif search_category == SearchCategory.EMAIL:
        qs = qs.filter(account__customer__email=search_q)
    elif search_category == SearchCategory.FULLNAME:
        qs = qs.filter(account__application__fullname__iexact=search_q)
    elif search_category == SearchCategory.PRODUCT_LINE:
        qs = qs.filter(account__application__product_line_id__product_line_type__icontains=search_q)
    elif search_category == SearchCategory.CUSTOMER_DPD_STATUS:
        search_param = int(search_q)
        pay_account = qs.filter(due_amount__gt = 0)
        days = -abs(search_param) if search_param > 0 else abs(search_param)
        search_days = datetime.now() + timedelta(days=days)
        if days != 0:
            qs = pay_account
            qs = qs.filter(due_date = search_days.date())

        else:
            qs = qs.filter(Q(due_amount = 0 ) | Q(due_date = search_days.date()))

    elif search_category == SearchCategory.VA_NUMBER:
        customer_ids = PaymentMethod.objects.filter(
            virtual_account=search_q,
            is_shown=True
        ).values_list('customer_id', flat=True)
        qs = qs.filter(account__customer_id__in=customer_ids)
    elif search_category == SearchCategory.OTHER_PHONE_NUMBER:
        if search_q.startswith('+'):
            search_q = search_q[1:]
        qs = find_phone_number_from_application_table(qs, search_q)

    return qs


@csrf_protect
@julo_login_required
def skiptrace_history(request):
    if request.method != 'POST':
        return HttpResponseNotAllowed(["POST"])

    data = request.POST.dict()
    application = Application.objects.get_or_none(pk=int(data['application']))
    if not application:
        return HttpResponseNotFound("application id %s not found" % data['application'])

    ptp_date_str = data['skip_ptp_date'] if 'skip_ptp_date' in data else None
    ptp_date = None

    if ptp_date_str:
        ptp_date = datetime.strptime(ptp_date_str, '%d-%m-%Y').date()

    today = timezone.localtime(timezone.now()).date()

    if ptp_date is not None and ptp_date < today:
        return JsonResponse(status=400, data={
            "status": "failed",
            "message": "ptp_date is less than today!"
        })

    loan_id = data['loan_id'] if 'loan_id' in data else None
    ptp_due_date = None

    if loan_id is not None:
        loan = Loan.objects.get_or_none(pk=int(data['loan_id']))
        account = loan.account
        if not account:
            return HttpResponseNotFound("account id is not found for loan_id" % data['loan_id'])
        ptp_due_date = get_ptp_max_due_date_for_j1(account)

    if ptp_date is not None and ptp_due_date != date(2017, 1, 1) and \
        ptp_due_date is not None and \
        (ptp_due_date is None or ptp_date > ptp_due_date):
        return JsonResponse(status=400, data={
            "status": "failed",
            "message": "ptp_date is greater than max ptp bucket date"
        })

    data['application_status'] = application.status
    data['old_application_status'] = None

    status_new = application.application_status.status_code
    app_history = application.applicationhistory_set.filter(status_new=status_new).order_by('cdate').last()
    is_account_payment = 0
    if app_history:
        data['application_status'] = app_history.status_new
        data['old_application_status'] = app_history.status_old

    if 'account_payment' in data:
        account_payment = AccountPayment.objects.get_or_none(pk=int(data['account_payment']))
        if not account_payment:
            return HttpResponseNotFound("account payment id %s not found" % data['account_payment'])
        data['account_payment_status'] = account_payment.status_id
        data['account'] = account_payment.account_id
        is_account_payment = 1

    data['end_ts'] = parse(str(data['end_ts']))
    data['start_ts'] = parse(str(data['start_ts'])) if data['start_ts'] else data['end_ts']

    data['agent'] = request.user.id
    data['agent_name'] = request.user.username
    if 'level1' in data:
        data['notes'] = data['skip_note']
        if 'skip_time' in data:
            data['callback_time'] = data['skip_time']

        if ptp_date:
            # validation on going PTP
            ptp = PTP.objects.filter(account=data['account']).last()
            if ptp:
                ptp_status = ptp.ptp_status
                if ptp.ptp_date >= today and (not ptp_status or ptp_status == PTPStatus.PARTIAL):
                    return JsonResponse(status=400, data={
                        "status": "failed",
                        "message": "on going ptp"
                    })

    if application.is_grab():
        skiptrace_history_serializer = GrabSkiptraceHistorySerializer(data=data)
    elif application.is_dana_flow():
        skiptrace_history_serializer = DanaSkiptraceHistorySerializer(data=data)
    else:
        skiptrace_history_serializer = SkiptraceHistorySerializer(data=data)
    if not skiptrace_history_serializer.is_valid():
        logger.warn({
            'skiptrace_id': data['skiptrace'],
            'agent_name': data['agent_name'],
            'error_msg': skiptrace_history_serializer.errors
        })
        return HttpResponseBadRequest("data invalid")

    skiptrace_history_obj = skiptrace_history_serializer.save()
    skiptrace_history_obj = skiptrace_history_serializer.data

    call_result = SkiptraceResultChoice.objects.get(pk=data['call_result'])
    if call_result.name == 'Cancel':
        return JsonResponse({
            "messages": "save success",
            "data": ""
        })

    skiptrace = Skiptrace.objects.get_or_none(pk=data['skiptrace'])

    if not skiptrace:
        return HttpResponseNotFound("skiptrace id %s not found" % data['skiptrace'])
    skiptrace = update_skiptrace_score(skiptrace, data['start_ts'])

    call_note = {
        "contact_source": skiptrace.contact_source,
        "phone_number": str(skiptrace.phone_number),
        "call_result": call_result.name or '',
        "spoke_with": skiptrace_history_obj['spoke_with'],
        "non_payment_reason": skiptrace_history_obj.get('non_payment_reason') or ''
    }

    agent_assignment_message = ''
    skip_note = data.get('skip_note')

    if 'level1' in data:
        if account_payment and request.user and call_result:
            trigger_insert_col_history(
                account_payment.id, request.user.id, call_result.id, is_julo_one=True)

        # if response:
        if ptp_date:

            with transaction.atomic():  
                # Create PTP Entry
                ptp_amount = data['skip_ptp_amount']

                if account_payment.status_id in PaymentStatusCodes.paid_status_codes():
                    return JsonResponse(status=400, data={
                        "status": "failed",
                        "message": "Tidak dapat tambah PTP, account payment ini sudah lunas"
                    })

                ptp_create_v2(account_payment, ptp_date, ptp_amount, request.user, is_julo_one=True)

                notes = "Promise to Pay %s -- %s " % (ptp_amount, ptp_date)
                if skip_note:
                    notes = ", ".join([notes, skip_note])

                account_payment.update_safely(ptp_date=ptp_date, ptp_amount=ptp_amount)

                AccountPaymentNote.objects.create(
                    note_text=notes,
                    account_payment=account_payment,
                    extra_data={
                        'call_note': call_note
                    }
                )

        else:
            if skip_note:
                payment_note = {
                    'account_payment': account_payment,
                    'extra_data': {
                        'call_note': call_note
                    },
                    'note_text': skip_note
                }
                AccountPaymentNote.objects.create(**payment_note)

        # delete intelix queue
        if call_result.name in ('RPC - Regular', 'RPC - PTP'):
            delete_paid_payment_from_intelix_if_exists_async_for_j1.delay(account_payment.id)
        if call_result.name in \
                CollectionVendorAssignmentConstant.SKIPTRACE_CALL_STATUS_ASSIGNED_CRITERIA \
                and account_payment.bucket_number == 5:
            subbucket = get_current_sub_bucket(account_payment, is_julo_one=True)
            # check collection vendor assignment
            assigned_payment_to_vendor = CollectionVendorAssignment.objects.filter(
                is_active_assignment=True, is_transferred_to_other__isnull=True,
                account_payment=account_payment
            )
            assigned_payment_to_agent = AgentAssignment.objects.filter(
                is_active_assignment=True, account_payment=account_payment,
                sub_bucket_assign_time=subbucket
            )
            if assigned_payment_to_vendor:
                assigned_vendor = assigned_payment_to_vendor.last()
                agent_assignment_message += 'failed add agent assignment because payment ' \
                                            'assigned to vendor {}'.format(
                                                assigned_vendor.vendor.vendor_name)
            if assigned_payment_to_agent:
                agent_assignment_data = assigned_payment_to_agent.last()
                agent_assignment_message += 'failed add agent assignment because payment ' \
                                            'assigned to agent {}'.format(
                                                agent_assignment_data.agent.username)

            if not assigned_payment_to_vendor and not assigned_payment_to_agent:
                assign_agent_for_julo_one_bucket_5.delay(request.user.id, account_payment.id)
    return JsonResponse({
        "messages": "save success skiptrace history {}".format(agent_assignment_message),
        "data": SkiptraceSerializer(skiptrace).data
    })


@csrf_protect
def ajax_change_first_settlement(request):
    if request.method == 'POST':
        message = ""
        cycle_date_requested = request.POST.get('new_date')
        payday_requested = request.POST.get('payday')
        account_payment_id = request.POST.get('account_payment_id')
        account_payment = AccountPayment.objects.get_or_none(pk=account_payment_id)
        if not account_payment:
            return JsonResponse({
                "status": "failed",
                'message': "Account payment tidak ditemukan"
            })
        if not check_lender_eligible_for_paydate_change(account_payment):
            return JsonResponse(
                {"status": "failed", 'message': "Lender tidak diizinkan mengganti paydate"}
            )

        if not payday_requested or not cycle_date_requested:
            return JsonResponse({
                "status": "failed",
                'message': "field wajib diisi"
            })
        try:
            with transaction.atomic():
                if payday_requested:
                    app = account_payment.account.last_application
                    if int(payday_requested) != app.payday:
                        app.payday = payday_requested
                        app.save()
                        message += "new payday, "
                    if not account_payment.account.is_payday_changed:
                        account_payment.account.is_payday_changed = True
                        account_payment.account.save()
                if cycle_date_requested:
                    cycle_date_req_obj = datetime.strptime(cycle_date_requested.strip(),
                                                           "%d-%m-%Y").date()

                    # proceed cycle day change
                    change_due_dates(account_payment, cycle_date_req_obj)

                    # save first payment installment
                    update_payment_installment(account_payment, cycle_date_req_obj)
                    message += "new installment date "
        except Exception as je:
            err_msg = "Error from Backend Process:"
            err_msg = "%s %s" % (err_msg, str(je))
            logger.info({
                'ubah_cycle_day': 'edit_cycle_day_installment_date_julo_one',
                'account_payment_id': account_payment.id,
                'error': err_msg
            })
            return JsonResponse({
                "status": "failed",
                'message': err_msg
            })
        return JsonResponse({
            "status": "success",
            'message': message + "berhasil diupdate"
        })


@csrf_protect
def ajax_check_can_change_paydate(request):
    if request.method != 'POST':
        return JsonResponse({"status": "error", "message": "Invalid method"}, status=405)

    account_payment_id = request.POST.get('account_payment_id')
    if not account_payment_id:
        return JsonResponse(
            {"status": "error", "message": "Missing account_payment_id"}, status=400
        )

    account_payment = AccountPayment.objects.get_or_none(pk=account_payment_id)
    if not account_payment:
        return JsonResponse({"status": "success", "can_change_paydate": True})

    # Check eligibility
    can_change_paydate = check_lender_eligible_for_paydate_change(account_payment)

    logger.info(
        {
            'action': 'ajax_check_change_paydate',
            'account_payment_id': account_payment_id,
            'can_change_paydate': can_change_paydate,
        }
    )

    return JsonResponse(
        {
            "status": "success",
            "can_change_paydate": can_change_paydate,
        }
    )


@csrf_protect
def simulate_adjusted_installment(request):
    if request.method == 'GET':
        account_payment = AccountPayment.objects.get_or_none(
            pk=int(request.GET.get('account_payment_id', 0))
        )
        response_data = {}
        account_payment_id = request.GET.get('account_payment_id')
        # set int date object
        try:
            new_due_date = request.GET.get('new_due_date', '')
            new_due_date_obj = datetime.strptime(str(new_due_date), "%d-%m-%Y").date()
        except Exception as e:
            logger.warning({
                'status': 'ajax - simulate_adjusted_installment',
                'new_due_date': new_due_date,
                'account_payment_id': account_payment_id
            })
            return HttpResponse(
                json.dumps({
                    "reason": "exception on calculate days_extra",
                    "result": "nok"
                }),
                content_type="application/json"
            )

        # simulate recalculation for first payment installment
        new_first_payment_installment = None
        try:
            new_first_payment_installment = update_payment_installment(account_payment,
                                                                       new_due_date_obj,
                                                                       simulate=True)
        except Exception as e:
            logger.warning({
                'status': 'ajax - simulate_adjusted_payment_installment',
                'exception': e,
                'account_payment_id': account_payment_id
            })
            return HttpResponse(
                json.dumps({
                    "reason": "exception on simulate_adjusted_payment_installment",
                    "result": "nok",
                    "addd": e
                }),
                content_type="application/json"
            )

        response_data['result'] = 'successful!'
        response_data['output'] = "%s" % (format_decimal(
            new_first_payment_installment, locale='id_ID'
        )) if new_first_payment_installment else 'none'
        response_data['reason'] = "ALL OKE"

        return HttpResponse(
            json.dumps(response_data),
            content_type="application/json"
        )
    else:
        return HttpResponse(
            json.dumps({
                "reason": "this isn't happening",
                'result': "nok"
            }),
            content_type="application/json"
        )


@julo_login_required
def account_dashboard(request, pk):
    account_id = pk
    user = request.user
    user_groups = user.groups.values_list('name', flat=True).all()
    today = timezone.localtime(timezone.now()).date()

    account =  Account.objects.get_or_none(pk=account_id)
    if not account:
        return redirect("/account_payment_status/all/list")
    account_payments = account.accountpayment_set.all().order_by('-due_date')
    current_account_payment = account_payments.first()
    application = account.application_set.last()
    application_original = application.applicationoriginal_set.last()
    active_loans = account.loan_set.filter(loan_status__gte=LoanStatusCodes.CURRENT,
                                           loan_status__lt=LoanStatusCodes.PAID_OFF)
    account_limit = account.accountlimit_set.last()
    total_monthly_installment = account.loan_set.filter(loan_status__gte=LoanStatusCodes.CURRENT,
                                                        loan_status__lt=LoanStatusCodes.PAID_OFF).\
        aggregate(Sum('installment_amount'))['installment_amount__sum']

    total_outstanding_due_amount = account.get_total_outstanding_amount()
    total_overdue_amount = account.get_total_overdue_amount()
    oldest_unpaid_account_payment = account.get_oldest_unpaid_account_payment()

    active_account_payments = account_payments.not_paid_active()
    bucket_days_list = {
        "1": {'from': BucketConst.BUCKET_1_DPD['from'], 'to': BucketConst.BUCKET_1_DPD['to']},
        "2": {'from': BucketConst.BUCKET_2_DPD['from'], 'to': BucketConst.BUCKET_2_DPD['to']},
        "3": {'from': BucketConst.BUCKET_3_DPD['from'], 'to': BucketConst.BUCKET_3_DPD['to']},
        "4": {'from': BucketConst.BUCKET_4_DPD['from'], 'to': BucketConst.BUCKET_4_DPD['to']},
        "5": {'from': BucketConst.BUCKET_5_DPD, 'to': BucketConst.BUCKET_5_END_DPD},
        "6": {'from': BucketConst.BUCKET_6_1_DPD['from'], 'to': None},
    }

    over_due_bucket_data = {}
    for bucket_key, days_between in bucket_days_list.items():
        bucket_account_payment = None
        bucket_account_payment = active_account_payments.get_all_bucket_by_range(
            days_between['from'], days_between['to'])
        bucket_due_amount = bucket_account_payment.aggregate(Sum('due_amount'))['due_amount__sum'] \
            if bucket_account_payment else 0
        bucket_dpd = bucket_account_payment.last().dpd if bucket_account_payment else 0
        bucket_dpd_text =  " ‘{}’ DPD".format(bucket_dpd) if bucket_dpd != 0 else ""
        over_due_bucket_data[bucket_key] = {"overdue_amount": bucket_due_amount, "in_dpd": bucket_dpd_text}

    active_payments = Payment.objects.filter(
        loan__loan_status__gte=LoanStatusCodes.CURRENT,
        loan__loan_status__lt=LoanStatusCodes.PAID_OFF,
        loan__account=account, paid_amount__gt=0)
    sum_of_paid_amount = active_payments.aggregate(Sum('paid_amount'))['paid_amount__sum']
    last_paid_account_payment = active_payments.\
        filter(paid_date__isnull=False).order_by('paid_date').last()
    last_paid_date = last_paid_account_payment.paid_date if last_paid_account_payment else ''

    skiptrace_history_list = SkiptraceHistory.objects.filter(application_id=application.id). \
        order_by('-cdate')

    bucket_5_collection_assignment_movement_history = None
    history_note_list = []
    account_payment_ids = account_payments.values_list('id', flat=True)
    if account_payment_ids:
        if account.ever_entered_B5:
                bucket_5_collection_assignment_movement_history = display_account_movement_history(
                    account_payment_or_payment=current_account_payment, is_julo_one=True
                )
        act_pmt_histories = AccountPaymentStatusHistory.objects.filter(account_payment_id__in=account_payment_ids).\
            annotate(type_data = Value('Status Change', output_field=CharField())).order_by("-cdate")

        act_pmt_notes = AccountPaymentNote.objects.filter(account_payment_id__in=account_payment_ids).\
            annotate(type_data=Value('Notes', output_field=CharField())).order_by("-cdate")

        if bucket_5_collection_assignment_movement_history:
            history_note_list =  sorted(
                chain(act_pmt_histories, act_pmt_notes, bucket_5_collection_assignment_movement_history),
                key=lambda instance: instance.cdate, reverse=True)

        history_note_list =  sorted(
            chain(act_pmt_histories, act_pmt_notes),
            key=lambda instance: instance.cdate, reverse=True)

    template_name = 'object/account_payment_status/account_dashboard.html'

    return render(
        request,
        template_name,
        {
            'account': account,
            'application': application,
            'account_payments': account_payments,
            'current_account_payment': current_account_payment,
            'account_payment_ids': account_payments.values_list('id', flat=True),
            'active_loans_count' : active_loans.count(),
            'account_limit': account_limit,
            'sum_of_paid_amount': sum_of_paid_amount,
            'total_outstanding_due_amount': total_outstanding_due_amount,
            'total_overdue_amount': total_overdue_amount,
            'application_original':application_original,
            'skiptrace_history_list': skiptrace_history_list,
            'total_monthly_installment': total_monthly_installment,
            'history_note_list': history_note_list,
            'last_paid_date': last_paid_date,
            'over_due_bucket_data': over_due_bucket_data

        }
    )


@julo_login_required
def get_skiptrace_history(request, application_id):
    from .serializers import SkiptraceHistorySerializer
    if request.method == 'GET':
        if not application_id:
            return HttpResponse(
                json.dumps(
                    {"messages": "application_id is blank",
                    "result": "failed"
                     }
                ),
                content_type="application/json")
        skiptrace_field_list = [
            'id', 'account_payment_id', 'account_id', 'application_id',
            'call_result_id', 'cdate', 'agent_name', 'call_result__name', 'callback_time',
            'skiptrace__phone_number', 'skiptrace__contact_source', 'spoke_with',
            'loan_id', 'payment_id', 'start_ts', 'end_ts', 'non_payment_reason',
        ]
        # for handling on unittest, since can't using replica DB
        using = DEFAULT_DB if request.GET.get('unit_test') else REPAYMENT_ASYNC_REPLICA_DB
        skiptrace_history_model = SkiptraceHistory
        application = Application.objects.using(using).filter(
            pk=application_id).last()
        if application:
            if application.is_dana_flow():
                skiptrace_history_model = DanaSkiptraceHistory
                skiptrace_field_list.remove('loan_id')
                skiptrace_field_list.remove('payment_id')
            elif application.is_grab():
                skiptrace_history_model = GrabSkiptraceHistory

        skiptrace_history_list = skiptrace_history_model.objects.using(using)\
            .select_related('skiptrace', 'call_result')\
            .values(*tuple(skiptrace_field_list)).filter(application_id=application_id)\
            .order_by('-cdate')
        
        limit = 10
        pageNumber = request.GET.get('index')

        paginator = Paginator(skiptrace_history_list, limit)
        try:
            result_data = paginator.page(pageNumber)
        except PageNotAnInteger:
            result_data = paginator.page(1)
        except EmptyPage:
            result_data = None
        
        data = []
        if result_data:
            serializer_res = SkiptraceHistorySerializer(result_data, many=True)
            data = serializer_res.data
        
        return HttpResponse(
            json.dumps(
                {
                    "messages": "more skiptrace loaded",
                    "result": "success",
                    "data": data,
                }
            ),
            content_type="application/json",
        )
    
    return HttpResponse(
        json.dumps(
            {"messages": "no result",
             "result": "failed"
             }
        ),
        content_type="application/json")


@julo_login_required
def get_mjolnir_call_summary(request, application_id):
    if request.method != 'GET':
        return HttpResponse(
            json.dumps({"messages": "no result", "result": "failed"}),
            content_type="application/json",
        )

    if not application_id:
        return HttpResponse(
            json.dumps({"messages": "application_id is blank", "result": "failed"}),
            content_type="application/json",
        )

    # Get the last_id from the query parameters
    last_skiptrace_history_id = request.GET.get('last_skiptrace_history_id', None)
    sort_order = request.GET.get('sortOrder', 'desc')
    application = Application.objects.filter(pk=application_id).last()
    if last_skiptrace_history_id != None and last_skiptrace_history_id == 'null':
        last_skiptrace_history_id = None
    call_summary_data, new_last_id = get_call_summary_mjolnir_data(
        application, last_skiptrace_history_id=last_skiptrace_history_id, sort_order=sort_order
    )
    data = {"last_id": new_last_id, "call_summary_data": call_summary_data}
    return HttpResponse(
        json.dumps(
            {
                "messages": "more skiptrace loaded",
                "result": "success",
                "data": data,
            }
        ),
        content_type="application/json",
    )


@csrf_protect
def get_status_history(request, payment_id):
    from .serializers import StatusHistorySerializer
    if request.method == 'GET':
        if not payment_id:
            return HttpResponse(
                json.dumps(
                    {"messages": "payment_id is blank",
                    "result": "failed"
                     }
                ),
                content_type="application/json")

        payment_obj = AccountPayment.objects.select_related(
              'account',
              'status').prefetch_related('payment_set').filter(pk=payment_id).last()

        if not payment_obj:
            return HttpResponse(
                json.dumps(
                    {"messages": "payment_id is not found",
                    "result": "failed"
                     }
                ),
                content_type="application/json")
        account = payment_obj.account

        bucket_5_collection_assignment_movement_history = None
        if account.ever_entered_B5:
            bucket_5_collection_assignment_movement_history = display_account_movement_history(
                account_payment_or_payment=payment_obj, is_julo_one=True
            )

        try:
            history_note_list = get_acc_pmt_list_history(
                payment_obj,
                collection_assignment_movement_history=bucket_5_collection_assignment_movement_history)
        except Exception as e:
            logger.error(
                {
                    'action': 'get_status_history',
                    'account_id': account.id,
                    'errors': 'fail to get list history {} - {}'.format(account.customer, e),
                }
            )
            history_note_list = []

        limit = 10
        pageNumber = request.GET.get('index')

        paginator = Paginator(history_note_list, limit)
        try:
            result_data = paginator.page(pageNumber)
        except PageNotAnInteger:
            result_data = paginator.page(1)
        except EmptyPage:
            result_data = None

        data = []
        if result_data:
            try:
                serializer_res = StatusHistorySerializer(result_data, many=True)
                data = serializer_res.data
            except Exception as e:
                logger.error(
                    {
                        'action': 'get_status_history',
                        'account_id': account.id,
                        'errors': 'fail to serialize {} - {}'.format(account.customer, e),
                    }
                )
                return HttpResponse(
                    json.dumps(
                        {"messages": "fail to serialize",
                        "result": "failed"
                        }
                    ),
                    content_type="application/json")

        return HttpResponse(
            json.dumps(
                {
                    "messages": "more status history loaded",
                    "result": "success",
                    "data": data,
                }
            ),
            content_type="application/json",
        )

    return HttpResponse(
        json.dumps(
            {"messages": "no result",
             "result": "failed"
             }
        ),
        content_type="application/json")


@csrf_protect
def get_email_sms_history(request, payment_id):
    from .serializers import EmailSmsHistorySerializer
    if request.method == 'GET':
        if not payment_id:
            return HttpResponse(
                json.dumps(
                    {"messages": "payment_id is blank",
                    "result": "failed"
                     }
                ),
                content_type="application/json")

        payment_obj = AccountPayment.objects.select_related(
              'account',
              'status').prefetch_related('payment_set').filter(id=payment_id).last()

        if not payment_obj:
            return HttpResponse(
                json.dumps(
                    {"messages": "payment_id is not found",
                    "result": "failed"
                     }
                ),
                content_type="application/json")

        try:
            email_sms_list = get_list_email_sms(payment_obj)
        except Exception as e:
            account = payment_obj.account
            logger.error(
                {
                    'action': 'get_email_sms_history',
                    'accound_id': account.id,
                    'errors': 'fail to get list email sms {} - {}'.format(account.customer, e),
                }
            )
            email_sms_list = []

        limit = 10
        pageNumber = request.GET.get('index')

        paginator = Paginator(email_sms_list, limit)
        try:
            result_data = paginator.page(pageNumber)
        except PageNotAnInteger:
            result_data = paginator.page(1)
        except EmptyPage:
            result_data = None
        data = []
        if result_data:
            try:
                serializer_res = EmailSmsHistorySerializer(result_data, many=True)
                data = serializer_res.data
            except Exception as e:
                logger.error(
                    {
                        'action': 'get_email_sms_history',
                        'account_id': account.id,
                        'errors': 'fail to serialize {} - {}'.format(account.customer, e),
                    }
                )
                return HttpResponse(
                    json.dumps(
                        {"messages": "fail to serialize",
                        "result": "failed"
                        }
                    ),
                    content_type="application/json")

        return HttpResponse(
            json.dumps(
                {
                    "messages": "more email sms history loaded",
                    "result": "success",
                    "data": data,
                }
            ),
            content_type="application/json",
        )

    return HttpResponse(
        json.dumps(
            {"messages": "no result",
             "result": "failed"
             }
        ),
        content_type="application/json")


@julo_login_required
def get_fdc_details(request, customer_id):
    if request.method != 'GET':
        return HttpResponse(
            json.dumps({"messages": "no result", "result": "failed"}),
            content_type="application/json",
        )

    if not customer_id:
        return HttpResponse(
            json.dumps({"messages": "customer_id is blank", "result": "failed"}),
            content_type="application/json",
        )

    customer = Customer.objects.filter(pk=customer_id).last()
    if not customer:
        return HttpResponse(
            json.dumps({"messages": "no customer exists", "result": "failed"}),
            content_type="application/json",
        )
    last_fdc_id = request.GET.get('last_fdc_id', None)
    if last_fdc_id != None and last_fdc_id == 'null':
        last_fdc_id = None
    fdc_details, new_last_fdc_id = get_fdc_details_for_customer(customer, last_fdc_id)
    data = {"last_fdc_id": new_last_fdc_id, "fdc_details": fdc_details}
    return HttpResponse(
        json.dumps(
            {
                "messages": "more fdc details loaded",
                "result": "success",
                "data": data,
            }
        ),
        content_type="application/json",
    )
