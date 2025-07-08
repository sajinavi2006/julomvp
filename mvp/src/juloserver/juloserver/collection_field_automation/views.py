import json
import os
from django.conf import settings
from django.views.decorators.cache import never_cache
import xlwt
from django.contrib.auth.models import User
from django.db.models import (
    Q,
    Count,
)
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
from django.views.static import serve
# Create your views here.
from juloserver.account.models import Account, AccountLookup
from juloserver.account_payment.models import AccountPayment
from juloserver.application_flow.clients import get_here_maps_client
from juloserver.collection_field_automation.constant import VisitResultCodes
from juloserver.collection_field_automation.models import FieldAssignment, FieldAttendance
from juloserver.collection_field_automation.serializers import (
    CollectionFieldSerializer,
    CollectionFieldAgentFilterSerializer,
    CollectionFieldReportSerializer,
)
from juloserver.collection_field_automation.services import (
    format_field_assignment_data,
    update_report_agent_field_visit_data,
)
from juloserver.collection_vendor.celery_progress import Progress
from juloserver.julo.constants import WorkflowConst
from juloserver.julo.models import (
    PaymentMethod,
    Application,
    Image,
    AddressGeolocation,
)
from juloserver.julo.services2 import get_redis_client
from juloserver.julo.statuses import PaymentStatusCodes, ApplicationStatusCodes
from juloserver.julo.utils import (
    display_rupiah,
)
from juloserver.minisquad.constants import DialerTaskType, RedisKey
from juloserver.minisquad.models import DialerTask, SentToDialer
from datetime import datetime, timedelta
from django.utils import timezone
from django.utils.encoding import smart_str
from juloserver.minisquad.services import get_oldest_unpaid_account_payment_ids
from juloserver.portal.core.templatetags.unit import format_rupiahs
from juloserver.portal.object import julo_login_required_group, julo_login_required
from juloserver.portal.object.dashboard.constants import JuloUserRoles
from django.core.paginator import Paginator, PageNotAnInteger, EmptyPage
from django.db import transaction
from juloserver.sdk.services import xls_to_dict
from juloserver.collection_field_automation.task import bulk_assign_account_to_agent_field, \
    bulk_change_agent_field_ownership, do_delete_excel, process_download_excel_files, process_upload_excel_files

import logging
logger = logging.getLogger("collection field log")


@julo_login_required
@julo_login_required_group(JuloUserRoles.COLLECTION_SUPERVISOR)
def field_supervisor_dashboard(request):
    template = 'collection_field_automation/supervisor_field_dashboard.html'
    page_number = 1
    j1_account_lookup = AccountLookup.objects.filter(name='JULO1').last()
    context = dict(
        current_page=page_number,
        is_search_filled=False,
        buckets=SentToDialer.objects.filter(
            account_payment__account__account_lookup_id=j1_account_lookup.id
        ).values_list('bucket', flat=True).distinct()
    )
    order_by_default_value = '-cdate'
    filter_data = dict()
    if request.POST:
        today = timezone.localtime(timezone.now()).date()
        data = request.POST
        page_number = 1 if not data.get('page_number') else data.get('page_number')
        search_account_id = data.get('search_account_id')
        search_area = data.get('search_area')
        search_dpd = data.get('search_dpd')
        search_agent = data.get('search_agent')
        search_date_assignment = data.get('search_date_assignment')
        search_expiry_date_assignment = data.get('search_expiry_date_assignment')
        context.update(
            search_account_id=search_account_id,
            search_area=search_area,
            search_dpd=search_dpd,
            search_agent=search_agent,
            search_date_assignment=search_date_assignment,
            search_expiry_date_assignment=search_expiry_date_assignment,
        )
        redisClient = get_redis_client()
        cached_oldest_account_payment_ids = redisClient.get_list(
            RedisKey.OLDEST_ACCOUNT_PAYMENT_IDS)
        if not cached_oldest_account_payment_ids:
            oldest_account_payment_ids = get_oldest_unpaid_account_payment_ids()
            if oldest_account_payment_ids:
                redisClient.set_list(
                    RedisKey.OLDEST_ACCOUNT_PAYMENT_IDS, oldest_account_payment_ids, timedelta(hours=4))
        else:
            oldest_account_payment_ids = list(map(int, cached_oldest_account_payment_ids))

        if search_account_id:
            filter_data.update(account_id=search_account_id)
        if search_agent:
            filter_data.update(agent__username=search_agent.lower())
        filter_account_ids = []
        if search_dpd:
            due_threshold = today - timedelta(days=int(search_dpd))
            account_ids = AccountPayment.objects.filter(
                id__in=oldest_account_payment_ids,
                due_date=due_threshold
            ).distinct('account').values_list('account_id', flat=True)
            filter_account_ids = list(account_ids)
        if search_area:
            filter_area = dict(
                workflow__name=WorkflowConst.JULO_ONE,
                application_status_id=ApplicationStatusCodes.LOC_APPROVED,
                address_kelurahan__iexact=search_area,
            )
            if filter_account_ids:
                filter_area.update(
                    account_id__in=filter_account_ids
                )
            account_ids = Application.objects.filter(
                **filter_area
            ).distinct('account').values_list('account_id', flat=True)
            filter_data.update(account_id__in=list(account_ids))
        else:
            if search_dpd:
                filter_data.update(account_id__in=list(filter_account_ids))

        if search_date_assignment:
            search_cdate_start = datetime.strptime(
                search_date_assignment, '%Y-%m-%d')
            filter_data.update(
                assign_date=search_cdate_start.date()
            )
        if search_expiry_date_assignment:
            search_expiry_date_assignment_conv = datetime.strptime(
                search_expiry_date_assignment, '%Y-%m-%d')
            filter_data.update(
                expiry_date=search_expiry_date_assignment_conv.date()
            )
    field_agent_assignments = FieldAssignment.objects.filter(
        **filter_data).order_by(order_by_default_value)
    paginator = Paginator(
        field_agent_assignments, 200)
    try:
        result_data = paginator.page(page_number)
    except PageNotAnInteger:
        result_data = paginator.page(1)
    except EmptyPage:
        result_data = paginator.page(paginator.num_pages)

    context.update(
        data_for_field_assignments=format_field_assignment_data(result_data),
        raw_data=result_data
    )
    return render(
        request,
        template,
        context
    )


@julo_login_required
@julo_login_required_group(JuloUserRoles.COLLECTION_SUPERVISOR)
def download_eligible_account_for_assign(request, *args, **kwargs):
    today = timezone.localtime(timezone.now()).date()
    cdate_threshold = today - timedelta(days=90)
    redisClient = get_redis_client()
    cached_oldest_account_payment_ids = redisClient.get_list(
        RedisKey.OLDEST_ACCOUNT_PAYMENT_IDS)
    if not cached_oldest_account_payment_ids:
        oldest_account_payment_ids = get_oldest_unpaid_account_payment_ids()
        if oldest_account_payment_ids:
            redisClient.set_list(
                RedisKey.OLDEST_ACCOUNT_PAYMENT_IDS, oldest_account_payment_ids, timedelta(hours=4))
    else:
        oldest_account_payment_ids = list(map(int, cached_oldest_account_payment_ids))

    j1_account_lookup = AccountLookup.objects.filter(name='JULO1').last()
    base_query_filter = dict(
        account_payment__account__account_lookup_id=j1_account_lookup.id,
        account_payment_id__in=list(oldest_account_payment_ids),
        account_id__isnull=False,
        cdate__date__gte=cdate_threshold,
        account_payment__status_id__lt=PaymentStatusCodes.PAID_ON_TIME
    )
    base_account_payment_ids = SentToDialer.objects.filter(**base_query_filter).order_by(
        'account_payment', '-cdate').distinct('account_payment').values_list('account_payment', flat=True)
    filter_data = dict(
        account_payment_id__in=list(base_account_payment_ids),
    )
    if request.POST:
        data = request.POST
        if data.get('filter_bucket'):
            filter_data.update(
                bucket=data.get('filter_bucket'))
        if data.get('filter_account_ids'):
            filter_data.update(
                account_id__in=data.get('filter_account_ids').split(","))
        if data.get('filter_agent_username'):
            filter_data.update(
                last_agent__username__in=data.get('filter_agent_username').split(",")
            )
        filter_cdate_mode = data.get('filter_cdate_mode')
        if filter_cdate_mode:
            if filter_cdate_mode == 'today':
                today = timezone.localtime(timezone.now())
                filter_data.update(
                    cdate__date=today.date()
                )
            else:
                search_cdate_start = datetime.strptime(
                    data.get('filter_cdate_1'), '%Y-%m-%d')
                if filter_cdate_mode == 'between':
                    search_cdate_end = datetime.strptime(
                        data.get('filter_cdate_2'), '%Y-%m-%d')
                    filter_data.update(
                        cdate__date__range=(
                            search_cdate_start,
                            search_cdate_end
                        )
                    )
                elif filter_cdate_mode == 'after':
                    filter_data.update(
                        cdate__date__gte=search_cdate_start
                    )
                elif filter_cdate_mode == 'before':
                    filter_data.update(
                        cdate__date__lte=search_cdate_start
                    )
                elif filter_cdate_mode == 'exact':
                    filter_data.update(
                        cdate__date=search_cdate_start
                    )
    eligible_account_ids = SentToDialer.objects.filter(**filter_data).order_by(
        'account', '-cdate').distinct('account').values_list('account', flat=True)
    response = HttpResponse(
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    response['Content-Disposition'] = 'attachment; filename=field_collection_automation_{}.xls'.format(
        timezone.localtime(timezone.now()).strftime("%Y%m%d%H%M%S")
    )
    wb = xlwt.Workbook(style_compression=2)
    ws = wb.add_sheet("list_sent_to_dialer", cell_overwrite_ok=True)
    font_style = xlwt.XFStyle()
    font_style.font.bold = True
    row_num = 0
    columns = ('Account Id',
               'Agent Username',
               'Expiry Date',
               'Area',
               'Overdue Amount'
               )

    column_size = list(range(len(columns)))
    for col_num in column_size:
        ws.write(row_num, col_num, columns[col_num], font_style)

    for account_id in list(eligible_account_ids):
        row_num += 1
        account = Account.objects.get_or_none(pk=account_id)
        if not account:
            continue

        application = account.application_set.last()
        if not application:
            continue

        data = (
            account_id, '', '', application.address_kabupaten,
            account.get_total_overdue_amount() or 0
        )
        font_style = xlwt.XFStyle()

        data_size = list(range(len(data)))
        for data_slice in data_size:
            ws.write(row_num, data_slice, data[data_slice], font_style)

    wb.save(response)

    return response


@never_cache
def get_bulk_download_excel_progress(request, task_id):
    progress = Progress(task_id)
    response = progress.get_info()
    if progress.result.state == 'SUCCESS':
        response.update(download_cache_id=progress.result.description)

    return HttpResponse(json.dumps(response), content_type='application/json')


def do_download_excel_progress(request,excel_file_name):
    filename = str(excel_file_name) + ".xls"
    excel_filepath = os.path.join(settings.BASE_DIR + '/media/',filename)
    response = HttpResponse(
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    response['Content-Disposition'] = 'attachment; filename={}'.format(
        filename
    )
    response['X-Sendfile'] =smart_str(excel_filepath)
    do_delete_excel.delay(excel_file_name)
    return serve(request, os.path.basename(excel_filepath), os.path.dirname(excel_filepath))


def process_bulk_download_excel_trigger(request):
    today = timezone.localtime(timezone.now()).date()
    cdate_threshold = today - timedelta(days=90)
    redisClient = get_redis_client()
    cached_oldest_account_payment_ids = redisClient.get_list(
        RedisKey.OLDEST_ACCOUNT_PAYMENT_IDS)
    if not cached_oldest_account_payment_ids:
        oldest_account_payment_ids = get_oldest_unpaid_account_payment_ids()
        if oldest_account_payment_ids:
            redisClient.set_list(
                RedisKey.OLDEST_ACCOUNT_PAYMENT_IDS, oldest_account_payment_ids, timedelta(hours=4))
    else:
        oldest_account_payment_ids = list(map(int, cached_oldest_account_payment_ids))

    j1_account_lookup = AccountLookup.objects.filter(name='JULO1').last()
    base_query_filter = dict(
        account_payment__account__account_lookup_id=j1_account_lookup.id,
        account_payment_id__in=list(oldest_account_payment_ids),
        account_id__isnull=False,
        cdate__date__gte=cdate_threshold,
        account_payment__status_id__lt=PaymentStatusCodes.PAID_ON_TIME
    )
    base_account_payment_ids = SentToDialer.objects.filter(**base_query_filter).order_by(
        'account_payment', '-cdate').distinct('account_payment').values_list('account_payment', flat=True)
    filter_data = dict(
        account_payment_id__in=list(base_account_payment_ids),
    )
    if request.POST:
        serializer = CollectionFieldSerializer(data=request.POST)
        serializer.is_valid(raise_exception=True)
        data=serializer.validated_data
        
        if data.get('filter_bucket'):
            filter_data.update(
                bucket=data.get('filter_bucket'))
            
        if data.get('filter_account_ids'):
            filter_data.update(
                account_id__in=data.get('filter_account_ids').split(","))
            
        if data.get('filter_agent_username'):
            filter_data.update(
                last_agent__username__in=data.get('filter_agent_username').split(",")
            )
            
        filter_cdate_mode = data.get('filter_cdate_mode')
        if filter_cdate_mode:
            if filter_cdate_mode == 'today':
                today = timezone.localtime(timezone.now())
                filter_data.update(
                    cdate__date=today.date()
                )
            else:
                search_cdate_start = datetime.strptime(
                    data.get('filter_cdate_1'), '%Y-%m-%d')
                if filter_cdate_mode == 'between':
                    search_cdate_end = datetime.strptime(
                        data.get('filter_cdate_2'), '%Y-%m-%d')
                    filter_data.update(
                        cdate__date__range=(
                            search_cdate_start,
                            search_cdate_end
                        )
                    )
                elif filter_cdate_mode == 'after':
                    filter_data.update(
                        cdate__date__gte=search_cdate_start
                    )
                elif filter_cdate_mode == 'before':
                    filter_data.update(
                        cdate__date__lte=search_cdate_start
                    )
                elif filter_cdate_mode == 'exact':
                    filter_data.update(
                        cdate__date=search_cdate_start
                    )
    eligible_account_ids = SentToDialer.objects.filter(**filter_data).order_by(
        'account', '-cdate').distinct('account').values_list('account', flat=True)
    response = HttpResponse(
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    response['Content-Disposition'] = 'attachment; filename=field_collection_automation_{}.xlsx'.format(
        timezone.localtime(timezone.now()).strftime("%Y%m%d%H%M%S")
    )

    dialer_task = DialerTask.objects.create(
        type=DialerTaskType.BULK_DOWNLOAD_RECORDING_PROCESS_INTELIX,
        error=''
    )
    oldest_account_payment_ids = []

    process_download_async = process_download_excel_files.delay(
        dialer_task.id, eligible_account_ids)

    redisClient.set(
        process_download_async.task_id,
        {'state': 'PROGRESS', 'pending': True,
         'current': 0,
         'total': 0, 'percent': 0,
         'description': ''})

    return JsonResponse({
        'status': 'success',
        'download_cache_id': None,
        'task_id': process_download_async.task_id
    })

    
def process_bulk_upload_excel_trigger(request):
    field_agent_assignment_data = request.FILES['assignment_field_file']
    data_formated = xls_to_dict(field_agent_assignment_data)
    if 'list_sent_to_dialer' not in data_formated:
        return JsonResponse({
            'status': 'failure',
            'messages': 'Format xlsx tidak didapat dari sistem'
        })
    
    dialer_task = DialerTask.objects.create(
        type=DialerTaskType.BULK_DOWNLOAD_RECORDING_PROCESS_INTELIX,
        error=''
    )
    process_upload_async = bulk_assign_account_to_agent_field.delay(
        dialer_task.id, data_formated)
    redisClient = get_redis_client()        
    redisClient.set(
        process_upload_async.task_id,
        {'state': 'PROGRESS', 'pending': True,
         'current': 0,
         'total': 0, 'percent': 0,
         'description': ''})


    return JsonResponse({
        'download_cache_id': None,
        'task_id': process_upload_async.task_id,
        'messages': "message",
        'status': "success"
    })


@julo_login_required
@julo_login_required_group(JuloUserRoles.COLLECTION_SUPERVISOR)
def upload_agent_field_assignment(request):
    field_agent_assignment_data = request.FILES['assignment_field_file']
    data_formated = xls_to_dict(field_agent_assignment_data)
    if 'list_sent_to_dialer' not in data_formated:
        return JsonResponse({
            'status': 'failure',
            'messages': 'Format xlsx tidak didapat dari sistem'
        })

    data_xls = data_formated['list_sent_to_dialer']
    data_for_insert = []
    data_for_update = []
    invalid_data = []
    
    today = timezone.localtime(timezone.now()).date()
    for idx, row_data in enumerate(data_xls):
        index = idx + 1
        if 'agent username' not in row_data:
            continue

        agent_username = row_data['agent username']
        if not agent_username:
            continue

        agent_user = User.objects.filter(
            username=agent_username.lower()).last()
        if not agent_user:
            invalid_data.append(
                dict(
                    row_number=index,
                    account_id=row_data['account id'],
                    error_message='agent dengan username {} tidak ada di database'.format(
                        agent_username.lower()
                    )
                )
            )
            continue

        account = Account.objects.get_or_none(
            pk=row_data['account id'])
        if not account:
            continue

        expiry_date = None
        if 'expiry date' in row_data:
            try:
                expiry_date = datetime.strptime(
                    row_data['expiry date'], '%Y-%m-%d')
            except ValueError:
                invalid_data.append(
                    dict(
                        row_number=index,
                        account_id=row_data['account id'],
                        error_message='Format expiry date {} salah'.format(row_data['expiry date'])
                    )
                )
                continue

        check_existing_agent = FieldAssignment.objects.filter(
            Q(expiry_date__gte=today) | Q(expiry_date__isnull=True),
            account=account,
        ).last()
        if check_existing_agent:
            data_for_update.append(
                dict(
                    field_assignment_id=check_existing_agent.id,
                    assign_date=today,
                    new_agent_id=agent_user.id,
                    expiry_date=expiry_date
                )
            )
        else:
            data_for_insert.append(
                FieldAssignment(
                    agent=agent_user,
                    account=account,
                    expiry_date=expiry_date,
                    assign_date=today,
                )
            )

    status = 'failure'
    if len(invalid_data) > 0:
        return JsonResponse({
            'status': status,
            'messages': 'Upload gagal beberapa data tidak memenuhi validasi',
            'invalid_data': invalid_data
        })

    message = 'Assign account ke agent field berhasil, tunggu beberapa saat sampai data tersimpan'
    if len(data_for_insert) > 0:
        bulk_assign_account_to_agent_field.delay(data_for_insert)
        status = 'success'
    if len(data_for_update) > 0:
        bulk_change_agent_field_ownership.delay(data_for_update)
        status = 'success'
    if len(data_for_update) == 0 and len(data_for_insert) == 0:
        message = 'Assign account ke agent field gagal, mohon periksa kembali excelnya'

    return JsonResponse({
        'status': status,
        'messages': message,
    })


@julo_login_required
@julo_login_required_group(JuloUserRoles.COLLECTION_SUPERVISOR)
def field_agent_attendance_report(request):
    today = timezone.localtime(timezone.now()).date()
    cdate_threshold = today - timedelta(days=30)
    template = 'collection_field_automation/field_attendance_report.html'
    page_number = 1
    context = dict(
        current_page=page_number,
        is_search_filled=False,
    )
    order_by_default_value = '-cdate'
    filter_data = dict(
        cdate__gte=cdate_threshold
    )
    if request.POST:
        data = request.POST
        page_number = 1 if not data.get('page_number') else data.get('page_number')

    field_agent_attendance = FieldAttendance.objects.filter(
        **filter_data).order_by(order_by_default_value)
    paginator = Paginator(
        field_agent_attendance, 200)
    try:
        result_data = paginator.page(page_number)
    except PageNotAnInteger:
        result_data = paginator.page(1)
    except EmptyPage:
        result_data = paginator.page(paginator.num_pages)

    context.update(
        attendance_data=result_data
    )
    return render(
        request,
        template,
        context
    )


@julo_login_required
@julo_login_required_group(JuloUserRoles.COLLECTION_SUPERVISOR)
def download_report_attendance(request, *args, **kwargs):
    today = timezone.localtime(timezone.now()).date()
    cdate_threshold = today - timedelta(days=30)
    filter_data = dict(
        cdate__date__gte=cdate_threshold,
    )
    attendance_data = FieldAttendance.objects.filter(**filter_data).order_by('-cdate')
    if not attendance_data:
        return render(request, 'covid_refinancing/404.html')
    response = HttpResponse(
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    response['Content-Disposition'] = 'attachment; filename=field_attendance_report_{}.xlsx'.format(
        timezone.localtime(timezone.now()).strftime("%Y%m%d%H%M%S")
    )
    wb = xlwt.Workbook(style_compression=2)
    ws = wb.add_sheet("attendance_report", cell_overwrite_ok=True)
    font_style = xlwt.XFStyle()
    font_style.font.bold = True
    row_num = 0
    columns = ('Agent Username',
               'Area',
               'Login Time'
               )

    column_size = list(range(len(columns)))
    for col_num in column_size:
        ws.write(row_num, col_num, columns[col_num], font_style)

    for attendance in attendance_data:
        row_num = row_num + 1
        agent = attendance.agent
        last_login = ''
        if agent.last_login:
            last_login = timezone.localtime(
                agent.last_login
            ).strftime('%Y-%m-%d %H:%M')
        data = (
            agent.username, attendance.loc_geoloc, last_login
        )
        font_style = xlwt.XFStyle()

        data_size = list(range(len(data)))
        for data_slice in data_size:
            ws.write(row_num, data_slice, data[data_slice], font_style)

    wb.save(response)

    return response


@julo_login_required
@julo_login_required_group(JuloUserRoles.COLLECTION_FIELD_AGENT)
def agent_field_dashboard(request):
    template = 'collection_field_automation/field_agent_dashboard.html'
    page_number = 1
    context = dict(
        current_page=page_number,
        is_search_filled=False,
        ask_for_gps=True,
    )
    attendance_data = FieldAttendance.objects.filter(
        agent=request.user
    ).last()
    if attendance_data and attendance_data.loc_latitude and attendance_data.loc_longitude:
        context.update(ask_for_gps=False)
    context.update(field_agent_attendance_id=attendance_data.id)
    advance_filter_dict = dict()
    if request.POST:
        data = request.POST
        page_number = 1 if not data.get('page_number') else data.get('page_number')
        serializer = CollectionFieldAgentFilterSerializer(data=request.POST)
        if serializer.is_valid():
            data = serializer.validated_data
            if data.get('filter_account_id'):
                advance_filter_dict.update(account_id=data.get('filter_account_id'))
                context.update(filter_account_id=data.get('filter_account_id'))
            if data.get('filter_expiry_date'):
                advance_filter_dict.update(expiry_date=data.get('filter_expiry_date'))
                context.update(filter_expiry_date=request.POST.get('filter_expiry_date'))
            if data.get('filter_area'):
                advance_filter_dict.update(
                    account__application__address_kelurahan=data.get('filter_area'))
                context.update(filter_area=data.get('filter_area'))
    today = timezone.localtime(timezone.now()).date()
    field_assignments_qs = FieldAssignment.objects.filter(
        Q(expiry_date__gte=today) | Q(expiry_date__isnull=True),
        agent=request.user,
    )
    field_assignments = field_assignments_qs.filter(**advance_filter_dict).extra(
        select={'expired_in': "expiry_date - current_date"}).order_by('expired_in')
    area_list = field_assignments_qs.values_list(
        'account__application__address_kelurahan', flat=True).annotate(
        dcount=Count('account__application__address_kelurahan')
    ).order_by('account__application__address_kelurahan')
    context.update(area_list=area_list)
    paginator = Paginator(
        field_assignments, 50)
    try:
        result_data = paginator.page(page_number)
    except PageNotAnInteger:
        result_data = paginator.page(1)
    except EmptyPage:
        result_data = paginator.page(paginator.num_pages)
    context.update(attendance=attendance_data)
    context.update(field_assignments=format_field_assignment_data(result_data))
    context.update(raw_data=result_data)

    return render(
        request,
        template,
        context
    )


@julo_login_required
@julo_login_required_group(JuloUserRoles.COLLECTION_FIELD_AGENT)
def customer_identity(request, account_id):
    application = Application.objects.get_or_none(account_id=account_id)
    base_filter = dict(
        image_source=application.id,
        image_status=Image.CURRENT,
        image_type='ktp'
    )
    ktp = Image.objects.filter(**base_filter).last()
    if not ktp:
        base_filter.update(image_type='ktp_ocr')
        ktp = Image.objects.filter(**base_filter).last()
    if not ktp:
        base_filter.update(image_type='ktp_self')
        ktp = Image.objects.filter(**base_filter).last()

    base_filter.update(image_type='ktp_selfie')
    ktp_selfie = Image.objects.filter(**base_filter).last()
    if not ktp_selfie:
        base_filter.update(image_type='selfie')
        ktp_selfie = Image.objects.filter(**base_filter).last()
    ktp_url = None
    ktp_selfie_url = None
    if ktp:
        ktp_url = ktp.image_url
    if ktp_selfie:
        ktp_selfie_url = ktp_selfie.image_url
    template = 'collection_field_automation/customer_identity.html'
    page_number = 1
    context = dict(
        current_page=page_number,
        is_search_filled=False,
        ktp=ktp_url,
        ktp_selfie=ktp_selfie_url
    )
    return render(
        request,
        template,
        context
    )


@julo_login_required
@julo_login_required_group(JuloUserRoles.COLLECTION_FIELD_AGENT)
def assignment_field_list_for_agent(request):
    today = timezone.localtime(timezone.now()).date()
    data = FieldAssignment.objects.filter(
        Q(expiry_date__gte=today) | Q(expiry_date__isnull=True),
        agent=request.user,
    ).extra(select={'expired_in': "expiry_date - current_date"}).order_by('expired_in')
    return data


@julo_login_required
@julo_login_required_group(JuloUserRoles.COLLECTION_FIELD_AGENT)
def store_location_agent_attendance(request):
    data = request.POST
    field_agent_attendance_id = data.get('field_agent_attendance_id')
    latitude = data.get('latitude')
    longitude = data.get('longitude')
    attendance = FieldAttendance.objects.filter(
        pk=field_agent_attendance_id,
        loc_geoloc__isnull=True
    ).last()
    if not attendance:
        return JsonResponse({
            'status': 'failure',
            'messages': 'Not Found attendance'
        })
    with transaction.atomic():
        # commented after found third api for reverse geocode
        # here_maps = get_here_maps_client()
        # reverse_gecode = here_maps.get_reverse_geocode_by_coordinates(
        #     latitude, longitude
        # )
        # if not reverse_gecode:
        #     return JsonResponse({
        #         'status': 'failure',
        #         'messages': 'location not found'
        #     })

        # geocode_address = reverse_gecode['address']
        # geocode = '{}-{}'.format(
        #     geocode_address['district'],
        #     geocode_address['subdistrict'],
        # )
        attendance.update_safely(
            loc_latitude=latitude,
            loc_longitude=longitude,
        )
        return JsonResponse({
            'status': 'success',
            'messages': 'Success save location'
        })


@julo_login_required
@julo_login_required_group(JuloUserRoles.COLLECTION_FIELD_AGENT)
def agent_field_report_form(request, field_assignment_id):
    field_assignment = FieldAssignment.objects.filter(
        id=field_assignment_id,
        agent=request.user,
    ).last()
    attendance = FieldAttendance.objects.filter(
        agent=request.user,
    ).last()
    if not field_assignment or not attendance:
        return render(request, 'covid_refinancing/404.html')

    template = 'collection_field_automation/field_agent_report_form.html'
    account = Account.objects.get_or_none(
        pk=field_assignment.account.id)
    application = account.application_set.last()
    context = dict(
        loan_id=account.loan_set.last().id,
        mapping_code=VisitResultCodes.VISIT_RESULT_MAPPING_LIST,
        visit_location_list=VisitResultCodes.VISIT_LOCATION_LIST,
        visit_area=application.address_kelurahan,
        payment_channels=application.customer.paymentmethod_set.filter(
            is_shown=True).order_by('-is_primary').values('id', 'payment_method_name', 'is_primary'),
        refuse_pay_reasons=VisitResultCodes.REFUSE_PAY_REASONS,
        field_assignment_id=field_assignment_id,
        post_message='',
        post_status=''
    )
    if request.POST:
        data = request.POST
        field_assignment_id = data.get('field_assignment_id')
        today = timezone.localtime(timezone.now()).date()
        field_assignment = FieldAssignment.objects.get(
            Q(expiry_date__gte=today) | Q(expiry_date__isnull=True),
            pk=int(field_assignment_id)
        )
        serializer = CollectionFieldReportSerializer(data=data)
        if not serializer.is_valid():
            context.update(post_message=str(serializer.errors), post_status='failure')
            return render(
                request,
                template,
                context
            )
        data = serializer.data
        if not field_assignment:
            context.update(post_message='Assignment not found', post_status='failure')

        try:
            update_report_agent_field_visit_data(
                request.user, field_assignment, data, request.FILES)
            context.update(post_message='Simpan laporan berhasil', post_status='success')
        except Exception as e:
            context.update(
                post_message='Simpan laporan gagal mohon hubungi admin',
                post_status='failure'
            )

    return render(
        request,
        template,
        context
    )


@julo_login_required
@julo_login_required_group(JuloUserRoles.COLLECTION_FIELD_AGENT)
def get_field_assignment_detail(request):
    field_assignment_id = request.POST.get('field_assignment_id')
    field_assignment = FieldAssignment.objects.get(
        pk=field_assignment_id)
    if not field_assignment:
        return JsonResponse({
            'status': 'failure',
            'message': 'Field Assignment not found',
        })
    account = field_assignment.account
    account_payment = account.get_last_unpaid_account_payment()
    ptp_date = '-'
    ptp_amount = 0
    application = account.last_application
    if field_assignment.ptp:
        ptp_date = field_assignment.ptp.ptp_date
        ptp_amount = field_assignment.ptp.ptp_amount
    payment_method = PaymentMethod.objects.filter(
        customer=account.customer, is_primary=True).last()
    last_payment_date, last_payment_amount = account.get_last_payment_event_date_and_amount()
    if last_payment_date:
        last_payment_date = str(last_payment_date)
    geolocation = AddressGeolocation.objects.filter(
        application_id=application.id).last()
    gmaps_url = '-'
    if geolocation:
        gmaps_url = geolocation.gmap_address_and_latlon_url

    data = dict(
        bucket=account_payment.bucket_number_special_case,
        assignment_date=field_assignment.assign_date,
        overdue_amount=display_rupiah(account.get_total_overdue_amount() or 0),
        agent_username=field_assignment.agent.username,
        result=field_assignment.result,
        ptp_date=ptp_date,
        ptp_amount=display_rupiah(ptp_amount),
        payment_method=payment_method.payment_method_name,
        payment_method_number=payment_method.virtual_account,
        full_address=application.complete_addresses,
        company_name=application.company_name,
        last_payment_date=last_payment_date,
        last_payment_amount=display_rupiah(last_payment_amount),
        oldest_due_amount=format_rupiahs(account_payment.due_amount, 'no'),
        gmaps_url=gmaps_url,
        account_id=account.id,
        outstanding_amount=display_rupiah(account.get_total_outstanding_amount() or 0),
        result_foto=field_assignment.visit_proof_image_url,
        phone_number=application.mobile_phone_1
    )
    return JsonResponse({
        'status': 'success',
        'data': data,
    })
