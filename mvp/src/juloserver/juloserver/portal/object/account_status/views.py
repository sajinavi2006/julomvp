from __future__ import print_function

import json
import logging
import re
from builtins import str
from datetime import date, datetime, timedelta

from account_payment_status.constants import SearchCategory
from account_status.forms import StatusChangesForm
from app_status.forms import ApplicationForm, ApplicationSelectFieldForm
from app_status.utils import ExtJsonSerializer, get_list_sms_email_history_fc
from dashboard.constants import JuloUserRoles
from dateutil.parser import parse
from django.contrib import messages
from django.contrib.auth.models import User
from django.core.urlresolvers import reverse
from django.db.models import Case, When
from django.http import (
    HttpResponse,
    HttpResponseBadRequest,
    HttpResponseNotAllowed,
    HttpResponseNotFound,
    JsonResponse,
)
from django.shortcuts import redirect, render
from django.template.loader import render_to_string
from django.utils import timezone
from django.views.decorators.csrf import csrf_protect
from future import standard_library
from loan_app.utils import get_list_history_all

# set decorator for login required
from object import julo_login_required, julo_login_required_exclude
from payment_status.constants import PAYMENT_EVENT_CONST
from payment_status.forms import ApplicationPhoneForm, SendEmailForm
from payment_status.serializers import (
    SkiptraceHistorySerializer,
    SkiptraceSerializer,
    GrabSkiptraceHistorySerializer,
)
from payment_status.utils import get_ptp_max_due_date_for_j1, get_wallet_list_note
from rest_framework.views import APIView

from juloserver.account.constants import AccountConstant
from juloserver.account.models import Account, AccountNote
from juloserver.apiv3.models import ProvinceLookup
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.julo.constants import EmailDeliveryAddress, FeatureNameConst
from juloserver.julo.exceptions import EmailNotSent, SmsNotSent
from juloserver.julo.models import (
    Application,
    ApplicationNote,
    BankLookup,
    CustomerWalletHistory,
    FeatureSetting,
    Image,
    Loan,
    PaymentMethod,
    RobocallTemplate,
    Skiptrace,
    SkiptraceHistory,
    SkiptraceResultChoice,
    StatusLookup,
    VoiceRecord,
)
from juloserver.julo.services import (
    get_data_application_checklist_collection,
    send_custom_sms_account,
    send_email_application,
    update_skiptrace_score,
)
from juloserver.julo.services2 import get_agent_service
from juloserver.julo.services2.agent import convert_usergroup_to_agentassignment_type
from juloserver.julo.statuses import JuloOneCodes, PaymentStatusCodes
from juloserver.julo.utils import check_email
from juloserver.loan.models import PaidLetterNote
from juloserver.loan.services.sphp import (
    generate_paid_off_letters,
    write_download_paid_letter_history,
)
from juloserver.otp.constants import EmailOTP
from juloserver.payback.models import WaiverTemp
from juloserver.portal.object.account_status.serializers import (
    LoanPaidOffLetterGeneratorSerializer,
)
from juloserver.portal.object.loan_app.constants import ImageUploadType
from juloserver.standardized_api_response.mixin import StandardizedExceptionHandlerMixin
from juloserver.standardized_api_response.utils import (
    general_error_response,
    success_response,
)

from .services import find_phone_number_from_application_table
from juloserver.grab.models import GrabSkiptraceHistory
from juloserver.portal.object import user_has_collection_blacklisted_role

standard_library.install_aliases()

logger = logging.getLogger(__name__)
client = get_julo_sentry_client()


@julo_login_required
def account_details(request, account_id):
    user = request.user
    if not user.is_authenticated or user_has_collection_blacklisted_role(user):
        return render(request, 'covid_refinancing/404.html')

    # user_groups = user.groups.values_list('name', flat=True).all()
    today = timezone.localtime(timezone.now()).date()

    account = Account.objects.get_or_none(pk=account_id)
    if not account:
        return redirect("/account_status/all/list")

    application = account.last_application
    application.refresh_from_db()
    loan_objects = account.loan_set.all()
    loan_obj = application.account.loan_set.last()
    account_payments = account.accountpayment_set.all().order_by('-due_date')
    status_current = account.status

    template_name = 'object/account_status/account_details.html'
    message_out_ubah_status = None
    message_out_simpan_note = None
    ubah_status_active = 0
    simpan_note_active = 0

    application_id = application.id
    application_product_line = application.product_line
    customer = account.customer
    app_list = get_list_history_all(application)
    wallet_notes = get_wallet_list_note(customer)
    app_phone = [
        (application.mobile_phone_1, 'mobile_phone_1'),
        (application.mobile_phone_2, 'mobile_phone_2'),
        (application.spouse_mobile_phone, 'spouse_mobile_phone'),
        (application.kin_mobile_phone, 'kin_mobile_phone'),
        ('0', 'custom'),
    ]
    robocall_templates = RobocallTemplate.objects.filter(is_active=True)
    robo_templates_map = {}
    for robocall_template in robocall_templates:
        robo_templates_map[str(robocall_template.id)] = robocall_template.text
    app_email = application.email

    if request.method == 'POST':
        form = StatusChangesForm(status_current, request.POST)
        form_app_phone = ApplicationPhoneForm(app_phone, request.POST)
        if 'notes_only' in request.POST:
            try:
                text_notes = form.data['notes_only']
                # data = request.POST

                if text_notes:
                    notes = AccountNote.objects.create(note_text=text_notes, account=account)
                    logger.info(
                        {
                            'action': 'save_note',
                            'notes': notes,
                        }
                    )

                    url = reverse(
                        'account_status:account_details', kwargs={'account_id': account.id}
                    )
                    return redirect(url)
                else:
                    err_msg = """
                        Note/Catatan Tidak Boleh Kosong !!!
                    """
                    messages.error(request, err_msg)
                    message_out_simpan_note = err_msg
                    simpan_note_active = 1

            except Exception:
                err_msg = """
                    Catatan Tidak Boleh Kosong !!!
                """
                messages.error(request, err_msg)
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

        image_list = Image.objects.filter(
            image_source=application_id, image_status__in=[Image.CURRENT, Image.RESUBMISSION_REQ]
        )
        results_json = ExtJsonSerializer().serialize(
            image_list, props=['image_url', 'image_ext'], fields=('image_type',)
        )

        image_list_1 = Image.objects.filter(image_source=application_id, image_status=Image.DELETED)
        results_json_1 = ExtJsonSerializer().serialize(
            image_list_1, props=['image_url', 'image_ext'], fields=('image_type',)
        )
        voice_list = VoiceRecord.objects.filter(
            application=application_id,
            status__in=[VoiceRecord.CURRENT, VoiceRecord.RESUBMISSION_REQ],
        )
        results_json_2 = ExtJsonSerializer().serialize(
            voice_list, props=['presigned_url'], fields=('status')
        )

        voice_list_1 = VoiceRecord.objects.filter(
            application=application_id, status=VoiceRecord.DELETED
        )
        results_json_3 = ExtJsonSerializer().serialize(
            voice_list_1, props=['presigned_url'], fields=('status')
        )
        history_note_list = get_list_history_all(application)
        email_sms_list = get_list_sms_email_history_fc(application)
        skiptrace_list = Skiptrace.objects.filter(customer_id=customer.id).order_by('id')
        if account.is_grab_account():
            skiptrace_history_list = GrabSkiptraceHistory.objects.filter(
                application_id=application_id
            ).order_by('-cdate')[:100]
        else:
            skiptrace_history_list = SkiptraceHistory.objects.filter(
                application_id=application_id
            ).order_by('-cdate')[:100]
        status_skiptrace = False
        status_fraud_collection = True

        # get fb data
        fb_obj = getattr(application, 'facebook_data', None)
        # get loan data and order by offer_number
        offer_set_objects = application.offer_set.all().order_by("offer_number")
        app_data = get_data_application_checklist_collection(application)
        deprecated_list = [
            'address_kodepos',
            'address_kecamatan',
            'address_kabupaten',
            'bank_scrape',
            'address_kelurahan',
            'address_provinsi',
            'bidang_usaha',
        ]
        form_app = ApplicationForm(instance=application, prefix='form2')
        form_app_select = ApplicationSelectFieldForm(application, prefix='form2')
        lock_status, lock_by = 0, None
        wallets = (
            CustomerWalletHistory.objects.filter(customer=customer)
            .select_related('customer')
            .prefetch_related('customer__account_set')
            .filter(customer=customer)
            .order_by('-id')
        )
        wallets = wallets.exclude(change_reason__contains='_old').order_by('-id')

        waiver_temps = WaiverTemp.objects.filter(account=account)
        payment_methods = PaymentMethod.objects.filter(
            is_shown=True, customer=account.customer
        ).order_by('-is_primary', 'sequence')

        list_whatsapp_phone = skiptrace_list.filter(
            contact_source__in=[
                'mobile phone 1',
                'mobile_phone1',
                'mobile_phone 1',
                'mobile_phone_1',
                'Mobile phone 1' 'Mobile_phone_1',
                'Mobile_Phone_1',
                'mobile_phone1_1',
                'mobile phone 2',
                'mobile_phone2' 'mobile_phone 2',
                'mobile_phone_2',
                'Mobile phone 2',
                'Mobile_phone2',
                'Mobile_phone_2' 'MOBILE_PHONE_2',
            ]
        ).order_by('contact_source')
        ptp_robocall_mobile_qs = skiptrace_list.filter(
            contact_source__in=['mobile_phone_1', 'mobile_phone_2']
        ).values('contact_source', 'phone_number')
        ptp_robocall_mobile_list = list(ptp_robocall_mobile_qs)
        if len(ptp_robocall_mobile_list) == 0:
            ptp_robocall_mobile_list.append(
                {'contact_source': 'mobile_phone_1', 'phone_number': application.mobile_phone_1}
            )
            ptp_robocall_mobile_list.append(
                {'contact_source': 'mobile_phone_2', 'phone_number': application.mobile_phone_2}
            )

        # iso collection setting hide tab and button
        is_iso_inactive = True
        iso_st_source = [
            'mobile_phone_1',
            'mobile_phone_2',
            'kin_mobile_phone',
            'close_kin_mobile_phone',
            'company_phone_number',
            'spouse_mobile_phone',
        ]
        iso_collection_setting = FeatureSetting.objects.filter(
            feature_name=FeatureNameConst.ISO_COLLECTION, category='collection', is_active=True
        ).last()
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
            image_list = image_list.filter(image_type__in=(ImageUploadType.PAYSTUB, 'crop_selfie'))

        is_hidden_menu = FeatureSetting.objects.filter(
            feature_name=FeatureNameConst.CRM_HIDE_MENU, is_active=True
        ).last()

        hide_tabs = []
        if is_hidden_menu and user.crmsetting.role_select in is_hidden_menu.parameters['roles']:
            hide_tabs = is_hidden_menu.parameters['menu']

        provinces = (
            ProvinceLookup.objects.filter(is_active=True)
            .order_by('province')
            .values_list('province', flat=True)
        )
        total_unpaid_due_amount = account.get_total_outstanding_due_amount()

        wa_contact_mobile_data = skiptrace_list.filter(
            contact_source__in=[
                'mobile_phone_1',
                'mobile_phone_2',
                'kin_mobile_phone',
                'close_kin_mobile_phone',
                'spouse_mobile_phone',
            ]
        ).values('contact_source', 'phone_number')
        wa_contact_mobile_list = list(wa_contact_mobile_data)

        # CUSTOM EMAIL AND SMS TEMPLATES
        available_context = {
            'fullname': application.full_name_only,
            'banner_url': EmailOTP.BANNER_URL,
            'footer_url': EmailOTP.FOOTER_URL,
        }
        custom_email_template_content = render_to_string(
            'fraud/crm_fraud_colls_customer_email.html', available_context
        )

        sms_template = 'fraud/fraud_colls_customer_sms.txt'
        custom_sms_content = render_to_string(sms_template)

        show_reverification = False
        if account.status_id in AccountConstant.REVERIFICATION_TAB_STATUSES:
            show_reverification = True

        return render(
            request,
            template_name,
            {
                'custom_email_template_content': custom_email_template_content,
                'custom_sms_content': custom_sms_content,
                'loan_obj': loan_obj,
                'account': account,
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
                'history_note_list': history_note_list,
                'email_sms_list': email_sms_list,
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
                'loan_objects': loan_objects,
                'skiptrace_list': skiptrace_list,
                'skiptrace_history_list': skiptrace_history_list,
                'status_skiptrace': status_skiptrace,
                'status_fraud_collection': status_fraud_collection,
                'application_id': application_id,
                'app_data': app_data,
                'deprecatform_apped_list': deprecated_list,
                'deprecated_list': deprecated_list,
                'form_app': form_app,
                'form_app_select': form_app_select,
                'payment_methods': payment_methods,
                'lock_status': lock_status,
                'lock_by': lock_by,
                'is_payment_called': 0,
                'bank_name_list': json.dumps(
                    list(BankLookup.objects.all().values_list('bank_name', flat=True))
                ),
                'wallets': wallets,
                'wallet_notes': wallet_notes,
                'list_whatsapp_phone': list_whatsapp_phone,
                'robocall_templates': robocall_templates,
                'robo_templates_map': json.dumps(robo_templates_map),
                'ptp_robocall_mobile_list': ptp_robocall_mobile_list,
                'is_iso_inactive': is_iso_inactive,
                'iso_st_source': iso_st_source,
                'is_for_ojk': is_for_ojk,
                'hide_tabs': hide_tabs,
                'waiver_temps': waiver_temps,
                'payment_event_reversal_reason': PAYMENT_EVENT_CONST.REVERSAL_REASONS,
                'reversal_reason_show_move_payment': (
                    PAYMENT_EVENT_CONST.REVERSAL_REASON_WRONG_PAYMENT
                ),
                'all_account_payments': account_payments,
                'provinces': provinces,
                'user': user,
                # 'whatsapp_text': whatsapp_text,
                'paid_status_codes': PaymentStatusCodes.paid_status_codes_without_sell_off,
                'total_unpaid_due_amount': total_unpaid_due_amount or 0,
                'wa_contact_mobile_list': wa_contact_mobile_list,
                'is_show_download_paid_off_letter': user.groups.filter(
                    name__in=(
                        JuloUserRoles.COLLECTION_SUPERVISOR,
                        JuloUserRoles.OPS_REPAYMENT,
                        JuloUserRoles.OPS_TEAM_LEADER,
                    )
                ).exists(),
                'token': request.user.auth_expiry_token.key,
                'show_reverification': show_reverification,
                'form': form,
            },
        )


@julo_login_required
@julo_login_required_exclude(['bo_credit_analyst'])
def account_list_view(request, status_code):
    if not request.user.is_authenticated or user_has_collection_blacklisted_role(request.user):
        return render(request, 'covid_refinancing/404.html')

    # check if there is statuslookup which matches the statuslookup (if not then display 404)
    template_name = 'object/account_status/list.html'
    # get parameters url
    search_q = request.GET.get('search_q', '')
    filter_category = request.GET.get('filter_category', '')
    status_app = request.GET.get('status_app', '')

    try:
        if status_app:
            title_status = str(status_app)
        else:
            title_status = 'all'
        if status_code == 'all':
            status_show = status_code
        else:
            title_status = str(status_code)
            status_show = 'with_status'
    except Exception:
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
        },
    )


@csrf_protect
def ajax_account_status_list_view(request):
    if request.method != 'GET':
        return HttpResponseNotAllowed(["GET"])

    if not getattr(request.user, 'agent', None):
        return HttpResponse(
            json.dumps(
                {"status": "failed", "message": "Session Login Expired, Silahkan Login Kembali"}
            ),
            content_type="application/json",
        )

    search_category = request.GET.get('filter_category')
    status_code = request.GET.get('status_code')
    max_per_page = int(request.GET.get('max_per_page'))
    # here_title_status = None
    # user = request.user
    agent_service = get_agent_service()
    # squad = getattr(request.user.agent, 'squad', None)

    # sort_partner = request.GET.get('sort_partner')

    try:
        page = int(request.GET.get('page'))
    except Exception:
        page = 1

    if status_code != 'None':
        pass
        # alter query deep

    else:
        status_code = "all"

    list_status = (
        StatusLookup.objects.filter(status_code__in=JuloOneCodes.all())
        .order_by('status_code')
        .values('status_code', 'status')
    )

    list_agent_type = []
    agent_roles = JuloUserRoles.collection_bucket_roles()
    for role in agent_roles:
        list_agent_type.append(
            dict(
                value=role,
                label='{} - {}'.format(role, convert_usergroup_to_agentassignment_type(role)),
            )
        )

    list_agent = (
        User.objects.filter(groups__name__in=agent_roles, is_active=True)
        .order_by('id')
        .values('id', 'username', 'groups__name')
    )
    sort_q = request.GET.get('sort_q', None)
    sort_agent = request.GET.get('sort_agent', None)
    status_account = request.GET.get('status_app', None)

    qs = Application.objects.filter(account__loan__isnull=False).select_related(
        'application_status', 'account', 'customer', 'product_line'
    )
    if status_code not in ['all']:
        qs = qs.filter(account__status__status_code=status_code)
    if status_account and status_code in ['all']:
        qs = qs.filter(account__status__status_code=status_account)

    search_q = request.GET.get('search_q', None).strip()
    today_checked = request.GET.get('today_checked', None)
    freeday_checked = request.GET.get('freeday_checked', None)
    range_date = request.GET.get('range_date', None)

    if isinstance(search_q, str) and search_q:
        qs = account_status_filter_search_field(qs, search_category, search_q)

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
            if _date_range[0].strip() != 'Invalid date':
                _tgl_mulai = datetime.strptime(_date_range[0].strip(), "%d/%m/%Y %H:%M")
                _tgl_end = datetime.strptime(_date_range[1].strip(), "%d/%m/%Y %H:%M")
                if _tgl_end > _tgl_mulai:
                    qs = qs.filter(cdate__range=[_tgl_mulai, _tgl_end])
                else:
                    return HttpResponse(
                        json.dumps(
                            {
                                "status": "failed",
                                "message": "Tgl Sampai Harus Lebih besar dari Tgl Dari",
                            }
                        ),
                        content_type="application/json",
                    )
            else:
                return HttpResponse(
                    json.dumps({"status": "failed", "message": "Format Tanggal tidak valid"}),
                    content_type="application/json",
                )

    if sort_q:
        qs = qs.order_by(sort_q)

    if sort_agent:
        if sort_agent != '':
            qs = agent_service.filter_applications_by_agent_id(qs, sort_agent)

    # for pagination
    collection_values = [
        'id',
        'cdate',
        'account_id',
        'email',
        'customer_id',
        'mobile_phone_1',
        'fullname',
        'ktp',
        'product_line__product_line_type',
        'customer__dob',
        'account__status__status_code',
        'udate',
    ]

    processed_model = qs.model
    primary_key = 'id'

    three_next_pages = max_per_page * (page + 2) + 1
    limit = max_per_page * page
    offset = limit - max_per_page

    result = qs.values_list(primary_key, flat=True)
    if sort_q:
        sort_q = sort_q.replace('-', '')
        result = result.distinct(sort_q, primary_key)
    else:
        result = result.distinct(primary_key)
    result = result[offset:three_next_pages]
    app_ids = list(result)
    app_ids_1page = app_ids[:max_per_page]
    count_applications = len(app_ids)
    count_page = (
        page + (count_applications // max_per_page) + (count_applications % max_per_page > 0) - 1
    )
    if count_applications == 0:
        count_page = page

    # this preserved is needed because random order by postgresql/django
    preserved = Case(*[When(pk=pk, then=pos) for pos, pk in enumerate(result)])

    applications = processed_model.objects.filter(**{primary_key + '__in': app_ids_1page}).order_by(
        preserved
    )

    application_values = list(applications.values(*collection_values))

    return JsonResponse(
        {
            'status': 'success',
            'data': application_values,
            'count_page': count_page,
            'current_page': page,
            'list_status': list(list_status),
            'list_agent': list(list_agent),
            'list_agent_type': list_agent_type,
            'payment_paid_status': PaymentStatusCodes.PAID_ON_TIME,
            'search_categories': SearchCategory.ACCOUNT_PAGE,
        },
        safe=False,
    )


def account_status_filter_search_field(qs, search_category, search_q):
    if not search_category:
        return qs
    if search_category in [SearchCategory.ACCOUNT_ID, SearchCategory.APPLICATION_ID]:
        search_q = re.sub(r"\D", "", search_q)
        search_q = int(search_q) if search_q else 0
    if search_category == SearchCategory.ACCOUNT_ID:
        qs = qs.filter(account_id=search_q)
    elif search_category == SearchCategory.APPLICATION_ID:
        qs = qs.filter(id=search_q)
    elif search_category == SearchCategory.MOBILE_NUMBER:
        if search_q.startswith('+'):
            search_q = search_q[1:]
        qs = qs.filter(mobile_phone_1=search_q)
    elif search_category == SearchCategory.EMAIL:
        qs = qs.filter(email=search_q)
    elif search_category == SearchCategory.FULLNAME:
        qs = qs.filter(fullname__iexact=search_q)
    elif search_category == SearchCategory.OTHER_PHONE_NUMBER:
        if search_q.startswith('+'):
            search_q = search_q[1:]
        qs = find_phone_number_from_application_table(qs, search_q)

    return qs


@csrf_protect
def send_sms(request):

    if request.method == 'POST':

        account_id = request.POST.get('account_id')
        account = Account.objects.get_or_none(pk=account_id)

        if not account.customer.can_notify:
            return HttpResponse(
                json.dumps({'result': 'nok', 'error_message': "Can not notify to this customer"}),
                content_type="application/json",
            )

        sms_message = request.POST.get('sms_message').strip()

        to_number = request.POST.get('to_number')
        phone_type = request.POST.get('phone_type')
        category = request.POST.get('category')
        template_code = request.POST.get('template_code')
        template_code = "fraud_check_" + template_code
        if sms_message == '':
            return HttpResponse(
                json.dumps({'result': 'nok', 'error_message': "Message is empty"}),
                content_type="application/json",
            )
        try:
            send_custom_sms_account(
                account, to_number, phone_type, category, sms_message, template_code
            )

        except SmsNotSent as sns:
            return HttpResponse(
                json.dumps({'result': 'nok', 'error_message': str(sns)}),
                content_type="application/json",
            )

        return HttpResponse(
            json.dumps(
                {
                    'result': 'successful!',
                }
            ),
            content_type="application/json",
        )


@csrf_protect
def send_email(request):

    if request.method == 'POST':
        account_id = request.POST.get('account_id')
        account = Account.objects.get_or_none(pk=account_id)
        application = account.last_application
        if not account.customer.can_notify:
            return HttpResponse(
                json.dumps({'result': 'nok', 'error_message': "Can not notify to this customer"}),
                content_type="application/json",
            )

        email_content = request.POST.get('content')

        to_email = request.POST.get('to_email')
        subject = request.POST.get('subject')
        # category = request.POST.get('category')
        template_code = request.POST.get('template_code')
        # pre_header = request.POST.get('pre_header')
        valid_email = check_email(to_email)

        template_code = "fraud_check_" + template_code

        if not valid_email:
            return HttpResponse(
                json.dumps({'result': 'nok', 'error_message': "Invalid Email Address"}),
                content_type="application/json",
            )

        if email_content == '':
            return HttpResponse(
                json.dumps({'result': 'nok', 'error_message': "Message is empty"}),
                content_type="application/json",
            )

        try:
            email_sender = EmailDeliveryAddress.COLLECTIONS_JTF
            send_email_application(
                application,
                email_sender,
                to_email,
                subject,
                email_content,
                template_code=template_code,
            )

        except EmailNotSent as ens:
            return HttpResponse(
                json.dumps({'result': 'nok', 'error_message': str(ens)}),
                content_type="application/json",
            )

        return HttpResponse(
            json.dumps(
                {
                    'result': 'successful!',
                }
            ),
            content_type="application/json",
        )


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
        return JsonResponse(
            status=400, data={"status": "failed", "message": "ptp_date is less than today!"}
        )

    loan_id = data['loan_id'] if 'loan_id' in data else None
    ptp_due_date = None

    if loan_id is not None:
        loan = Loan.objects.get_or_none(pk=int(data['loan_id']))
        account = loan.account
        if not account:
            return HttpResponseNotFound("account id is not found for loan_id" % data['loan_id'])
        ptp_due_date = get_ptp_max_due_date_for_j1(account)

    if (
        ptp_date is not None
        and ptp_due_date != date(2017, 1, 1)
        and ptp_due_date is not None
        and (ptp_due_date is None or ptp_date > ptp_due_date)
    ):
        return JsonResponse(
            status=400,
            data={"status": "failed", "message": "ptp_date is greater than max ptp bucket date"},
        )

    data['application_status'] = application.status
    data['old_application_status'] = None

    status_new = application.application_status.status_code
    app_history = (
        application.applicationhistory_set.filter(status_new=status_new).order_by('cdate').last()
    )
    # is_account_payment = 0
    if app_history:
        data['application_status'] = app_history.status_new
        data['old_application_status'] = app_history.status_old

    if 'account' in data:
        data['account'] = application.account_id

    data['end_ts'] = parse(str(data['end_ts']))
    data['start_ts'] = parse(str(data['start_ts'])) if data['start_ts'] else data['end_ts']

    data['agent'] = request.user.id
    data['agent_name'] = request.user.username
    if 'level1' in data:
        data['notes'] = data['skip_note']
        if 'skip_time' in data:
            data['callback_time'] = data['skip_time']
    if application.is_grab():
        skiptrace_history_serializer = GrabSkiptraceHistorySerializer(data=data)
    else:
        skiptrace_history_serializer = SkiptraceHistorySerializer(data=data)
    if not skiptrace_history_serializer.is_valid():
        logger.warn(
            {
                'skiptrace_id': data['skiptrace'],
                'agent_name': data['agent_name'],
                'error_msg': skiptrace_history_serializer.errors,
            }
        )
        return HttpResponseBadRequest("data invalid")

    skiptrace_history_obj = skiptrace_history_serializer.save()
    fraud_colls_check = request.user.groups.filter(
        name__in=[JuloUserRoles.FRAUD_COLLS, JuloUserRoles.FRAUD_OPS]
    ).count()
    if fraud_colls_check > 0:
        skiptrace_history_obj.is_fraud_colls = True
        skiptrace_history_obj.save()
    skiptrace_history_obj = skiptrace_history_serializer.data

    call_result = SkiptraceResultChoice.objects.get(pk=data['call_result'])
    if call_result.name == 'Cancel':
        return JsonResponse({"messages": "save success", "data": ""})

    skiptrace = Skiptrace.objects.get_or_none(pk=data['skiptrace'])

    if not skiptrace:
        return HttpResponseNotFound("skiptrace id %s not found" % data['skiptrace'])
    skiptrace = update_skiptrace_score(skiptrace, data['start_ts'])

    call_note_dict = {
        "contact_source": skiptrace.contact_source,
        "phone_number": str(skiptrace.phone_number),
        "call_result": call_result.name or '',
        "spoke_with": skiptrace_history_obj['spoke_with'],
        "non_payment_reason": skiptrace_history_obj.get('non_payment_reason') or '',
    }
    call_note = (
        call_note_dict['contact_source']
        + "/"
        + call_note_dict['phone_number']
        + "/"
        + call_note_dict['call_result']
        + "/"
        + call_note_dict['spoke_with']
        + call_note_dict['non_payment_reason']
        + "\n"
    )

    agent_assignment_message = ''
    skip_note = data.get('skip_note')

    if skip_note:
        skip_note = call_note + skip_note
        ApplicationNote.objects.create(
            note_text=skip_note,
            application_id=application.id,
            added_by_id=request.user.id,
        )
    return JsonResponse(
        {
            "messages": "save success skiptrace history {}".format(agent_assignment_message),
            "data": SkiptraceSerializer(skiptrace).data,
        }
    )


class LoanEligiblePaidLetter(StandardizedExceptionHandlerMixin, APIView):
    serializer_class = LoanPaidOffLetterGeneratorSerializer

    def post(self, request):
        serializer = self.serializer_class(data=json.loads(request.data['json']))
        if not serializer.is_valid():
            message = serializer.errors
            return general_error_response(message=str(message))
        data = serializer.validated_data
        selected_loan_ids = data['selected_loan_ids']
        loans = Loan.objects.filter(id__in=selected_loan_ids)
        if not loans:
            return general_error_response(message="Loan tidak dapat ditemukan")

        # Generate paid off letters for the selected loans
        paid_letters_pdf_files = generate_paid_off_letters(loans)
        write_download_paid_letter_history(loans, request.user)
        filename, pdf_file = paid_letters_pdf_files[0]
        response = HttpResponse(pdf_file, content_type='application/force-download')
        response['Content-Disposition'] = 'attachment; filename="%s"' % filename
        return response

    def get(self, request):
        account_id = request.GET['account_id']
        account = Account.objects.filter(id=account_id).last()
        user = request.user
        if not account:
            return general_error_response(message="Account not found")
        eligible_loan_ids = []
        response = {'eligible_loan_ids': eligible_loan_ids}
        paid_off_loans_qs = account.get_all_paid_off_loan()
        if not paid_off_loans_qs:
            return success_response(response)

        if user.groups.filter(name=JuloUserRoles.OPS_REPAYMENT).exists():
            ops_repayment_user_ids = (
                User.objects.filter(groups__name=JuloUserRoles.OPS_REPAYMENT)
                .values_list('id', flat=True)
                .nocache()
            )
            downloaded_paid_letter_loan_ids = (
                PaidLetterNote.objects.filter(
                    loan_id__in=paid_off_loans_qs.values_list('id', flat=True),
                    added_by_id__in=ops_repayment_user_ids,
                )
                .distinct('loan')
                .values_list('loan', flat=True)
            )
            paid_off_loans_qs = paid_off_loans_qs.exclude(id__in=downloaded_paid_letter_loan_ids)
        eligible_loan_ids = paid_off_loans_qs.values('id', 'loan_xid')
        response['eligible_loan_ids'] = eligible_loan_ids
        return success_response(response)
