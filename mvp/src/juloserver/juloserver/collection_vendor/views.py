from __future__ import print_function
from builtins import map
from builtins import str
from builtins import range
import logging


import xlwt
import re

from django.contrib.auth.models import User
from django.db import transaction
from django.shortcuts import render, get_object_or_404
from django.conf import settings
from django.http.response import StreamingHttpResponse

# Create your views here.
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from babel.dates import format_date
from datetime import timedelta
from juloserver.julo.utils import get_oss_presigned_url
from juloserver.collection_vendor.models import (
    CollectionVendor, CollectionVendorFieldChange, CollectionVendorRatio,
    CollectionVendorRatioFieldChange, CollectionVendorAssignmentTransfer,
    CollectionVendorAssignment, AgentAssignment,
    CollectionVendorAssignmentExtension, CollectionVendorAssigmentTransferType,
    UploadVendorReport, VendorReportErrorInformation)
from juloserver.collection_vendor.constant import (
    CollectionAssignmentConstant)
from juloserver.collection_vendor.services import (
    validate_collection_vendor_name,
    delete_collection_vendors,
    generate_collection_vendor_ratio,
    format_assigment_transfer_from,
    get_current_sub_bucket,
    validate_data_calling_result,
    store_error_information_calling_vendor_result,
    determine_input_is_account_id_or_loan_id,
    format_agent_assignment_list_for_removal_agent_menu,
    bulk_create_assignment_movement_history_base_on_agent_assignment,
    move_agent_assignment_to_new_agent,
    remove_active_ptp_after_agent_removal,
    generate_filter_for_recording_detail,
    assign_new_vendor,
    manual_transfer_assignment,
)
from juloserver.portal.object import (
    julo_login_required, julo_login_required_group,
    julo_login_required_multigroup)
from juloserver.julo.models import Application, Loan, Payment
from django.http import HttpResponse, JsonResponse
from django.template import RequestContext, loader

from .celery_progress import Progress
from .serializers import (
    CollectionVendorAssignmentExtensionSerializer,
    CollectionVendorManualTransferSerializer,
    VendorBulkTransferSerializer,
)
from django.utils import timezone, dateformat
from django.core.paginator import Paginator, PageNotAnInteger, EmptyPage
from ..account.models import Account
from ..account_payment.models import AccountPayment
from juloserver.sdk.services import xls_to_dict
from juloserver.collection_vendor.task import (
    store_related_data_calling_vendor_result_task,
    process_bulk_download_recording_files,
    bulk_transfer_vendor_async,
)
from ..julo.services2 import get_redis_client
from ..julo.utils import get_file_from_oss
from ..minisquad.models import VendorRecordingDetail, BulkVendorRecordingFileCache, DialerTask
import json
from dateutil.relativedelta import relativedelta
from datetime import date
from juloserver.minisquad.constants import (
    DialerTaskType,
    REPAYMENT_ASYNC_REPLICA_DB,
)


logger = logging.getLogger(__name__)


@julo_login_required
def collection_vendor_data(request):
    template = 'collection_vendor/vendor_data.html'
    context = {
        'collection_vendor_list': CollectionVendor.objects.normal().order_by('-cdate')
    }
    return render(
        request,
        template,
        context
    )


@julo_login_required
def collection_vendor_form(request):
    template = 'collection_vendor/vendor_form.html'
    context = {
        'form_title': 'ADD COLLECTIONS VENDOR DATA',
        'current_vendor_name': '',
        'current_vendor_is_active': False,
        'current_vendor_type': '',
        'current_vendor_id': '',
        'current_vendor_is_final': False,
        'current_vendor_is_general': False,
        'current_vendor_is_special': False,
        'current_vendor_is_b4': False,
        'save_type': '',
        'vendor_name_error': '',
        'success_save': False,
    }
    collection_vendor_id = request.GET.get('vendor_id')
    if collection_vendor_id:
        context['form_title'] = 'CHANGE COLLECTIONS VENDOR DATA'
        current_collection_vendor = CollectionVendor.objects.get(pk=collection_vendor_id)
        context['current_vendor_name'] = current_collection_vendor.vendor_name
        context['current_vendor_is_active'] = current_collection_vendor.is_active
        context['current_current_vendor_type'] = current_collection_vendor.vendor_types
        context['current_vendor_id'] = current_collection_vendor.id
        context['current_vendor_is_general'] = current_collection_vendor.is_general
        context['current_vendor_is_special'] = current_collection_vendor.is_special
        context['current_vendor_is_final'] = current_collection_vendor.is_final
        context['current_vendor_is_b4'] = current_collection_vendor.is_b4

    if request.POST:
        user = request.user
        collection_vendor_id = request.POST.get('vendor_id')
        submit_type = 'add' if collection_vendor_id is None else 'edit'
        save_type = request.POST.get('save_type')
        vendor_name = request.POST.get('vendor_name')
        is_active = bool(request.POST.get('is_active'))
        is_special = True if request.POST.get('is_special') == 'on' else False
        is_general = True if request.POST.get('is_general') == 'on' else False
        is_final = True if request.POST.get('is_final') == 'on' else False
        is_b4 = True if request.POST.get('is_b4') == 'on' else False
        is_success_save = True
        is_vendor_name_exists = False
        data = dict(
            vendor_name=vendor_name,
            is_active=is_active,
            is_special=is_special,
            is_general=is_general,
            is_final=is_final,
            is_b4=is_b4,
        )
        new_collection_vendor = None
        if submit_type == 'add':
            data['created_by'] = user
            if validate_collection_vendor_name(vendor_name):
                new_collection_vendor = CollectionVendor.objects.create(**data)
                generate_collection_vendor_ratio(new_collection_vendor, user)
                context['submit_message'] = 'Collection Vendor berhasil ditambah'
            else:
                is_success_save = False
                is_vendor_name_exists = True
                new_collection_vendor = CollectionVendor(**data)
        else:
            data['last_updated_by'] = user
            changed_fields = []
            current_collection_vendor = CollectionVendor.objects.get(pk=collection_vendor_id)
            for key, new_value in list(data.items()):
                old_value = eval('current_collection_vendor.{}'.format(key))
                if not old_value:
                    old_value = ''

                if old_value != new_value:
                    if key == 'vendor_name':
                        if not validate_collection_vendor_name(new_value):
                            is_vendor_name_exists = True
                            break

                    changed_fields.append(
                        CollectionVendorFieldChange(
                            collection_vendor=current_collection_vendor,
                            action_type='Change',
                            field_name=key,
                            old_value=old_value,
                            new_value=new_value,
                            modified_by=user
                        )
                    )
            if not is_vendor_name_exists:
                current_collection_vendor.update_safely(
                    **data
                )
                generate_collection_vendor_ratio(current_collection_vendor, user)
                CollectionVendorFieldChange.objects.bulk_create(changed_fields)
                context['submit_message'] = 'Collection Vendor berhasil diubah'

            new_collection_vendor = current_collection_vendor

        context['current_vendor_name'] = new_collection_vendor.vendor_name
        context['current_vendor_is_active'] = new_collection_vendor.is_active
        context['current_current_vendor_type'] = new_collection_vendor.vendor_types
        context['current_vendor_id'] = new_collection_vendor.id
        context['current_vendor_is_general'] = new_collection_vendor.is_general
        context['current_vendor_is_special'] = new_collection_vendor.is_special
        context['current_vendor_is_final'] = new_collection_vendor.is_final
        context['current_vendor_is_b4'] = new_collection_vendor.is_b4
        context['save_type'] = save_type
        context['success_save'] = is_success_save
        if is_vendor_name_exists:
            context['vendor_name_error'] = 'Nama Vendor tidak boleh sama dengan yang sudah ada'

    return render(
        request,
        template,
        context
    )


@csrf_protect
def collection_vendor_delete(request):
    collection_vendor_ids = request.POST.get('collections_vendor_ids').split(',')
    delete_collection_vendors(collection_vendor_ids)
    return JsonResponse({
        'status': 'success',
        'messages': 'Collection Vendor berhasil dihapus'
    })


def collection_vendor_ratio_edit(request, vendor_types):
    template = loader.get_template('custom_admin/collection_vendor_ratio_template_form.html')
    queryset = CollectionVendorRatio.objects.normal().filter(vendor_types=vendor_types)
    context = {
        "form_status": "update",
        "vendor_types": vendor_types,
        "data": queryset,
        "violent_validation": False,
        "success_update": False,
    }
    if request.POST:
        user = request.user
        vendor_ratio_ids = request.POST.getlist('vendor_ratio_ids')
        account_distribution_ratios = request.POST.getlist('account_distribution_ratios')
        total_distribution_ratio = sum(map(float, account_distribution_ratios))
        if float("{:.2f}".format(total_distribution_ratio)) != float(1):
            context['violent_validation'] = True
        else:
            collection_vendor_ratio_field_change_list = []
            for index in range(0, len(vendor_ratio_ids)):
                current_collection_vendor_ratio = CollectionVendorRatio.objects.get(
                    pk=vendor_ratio_ids[index])
                new_account_distribution_ratio = float(account_distribution_ratios[index])
                if current_collection_vendor_ratio.account_distribution_ratio \
                        != new_account_distribution_ratio:
                    collection_vendor_ratio_field_change_list.append(
                        CollectionVendorRatioFieldChange(
                            collection_vendor_ratio=current_collection_vendor_ratio,
                            old_value=current_collection_vendor_ratio.account_distribution_ratio,
                            new_value=new_account_distribution_ratio,
                            modified_by=user
                        )
                    )
                    current_collection_vendor_ratio.update_safely(
                        account_distribution_ratio=float(account_distribution_ratios[index]),
                        last_updated_by=user
                    )

            CollectionVendorRatioFieldChange.objects.bulk_create(
                collection_vendor_ratio_field_change_list)
            context['success_update'] = True

    context = RequestContext(request, context)
    return HttpResponse(template.render(context))


@julo_login_required
def transfer_account_list(request):
    template = 'collection_vendor/transfer_account_list.html'
    collection_vendor_assignment_transfer_list = \
        CollectionVendorAssignmentTransfer.objects.all().order_by('-cdate')
    paginator = Paginator(
        collection_vendor_assignment_transfer_list, 100)
    page_number = request.GET.get('page_number')
    if not page_number:
        page_number = 1

    try:
        result_data = paginator.page(page_number)
    except PageNotAnInteger:
        result_data = paginator.page(1)
        page_number = 1
    except EmptyPage:
        result_data = paginator.page(paginator.num_pages)

    table_list = []
    for transfer_account in result_data:
        transfer_from = 'Inhouse' if not transfer_account.transfer_from\
            else transfer_account.transfer_from
        transfer_to = 'Inhouse' if not transfer_account.transfer_to\
            else transfer_account.transfer_to
        account_payment = transfer_account.account_payment
        account_id = '-'
        account_payment_id = '-'
        if not account_payment:
            payment = transfer_account.payment
            payment_id = payment.id
            loan = payment.loan
            loan_id = loan.id
            application = loan.application
            dpd_today = payment.due_late_days
            sub_bucket_today = get_current_sub_bucket(payment)
        else:
            account = account_payment.account
            account_id = account.id
            account_payment_id = account_payment.id
            application = account.application_set.last()
            payment_id = '-'
            loan_id = '-'
            dpd_today = account_payment.dpd
            sub_bucket_today = get_current_sub_bucket(
                account_payment, is_julo_one=True)
        if not application:
            continue
        customer = application.customer
        assign_time = '-'
        dpd_assign_time = '-'
        sub_bucket_assign_time = '-'
        if sub_bucket_today:
            sub_bucket_today = sub_bucket_today.sub_bucket_label
        else:
            sub_bucket_today = '-'

        if transfer_account.transfer_from:
            if type(transfer_from) is User:
                transfer_from_object = AgentAssignment.objects.filter(
                    agent=transfer_from, collection_vendor_assigment_transfer=transfer_account,
                    is_transferred_to_other=True
                ).last()
            else:
                transfer_from_object = CollectionVendorAssignment.objects.filter(
                    vendor=transfer_from, collection_vendor_assigment_transfer=transfer_account,
                    is_transferred_to_other=True
                ).last()
            if transfer_from_object:
                assign_time = transfer_from_object.assign_time.date()
                dpd_assign_time = transfer_from_object.dpd_assign_time
                sub_bucket_assign_time = transfer_from_object.\
                    sub_bucket_assign_time.sub_bucket_label

        transfer_from = 'Agent ({})'.format(transfer_from) if type(transfer_from) is User\
            else transfer_from
        transfer_to = 'Agent ({})'.format(transfer_to) if type(transfer_to) is User\
            else transfer_to
        table_list.append(
            dict(
                id=transfer_account.id,
                transfer_date=transfer_account.cdate.date(),
                application_xid=application.application_xid,
                application_id=application.id,
                assign_time=assign_time,
                dpd_assign_time=dpd_assign_time,
                dpd_today=dpd_today,
                sub_bucket_assign_time=sub_bucket_assign_time,
                sub_bucket_today=sub_bucket_today,
                loan_id=loan_id,
                payment_id=payment_id,
                customer_name=customer.fullname,
                customer_email=customer.email,
                transfer_from=transfer_from,
                transfer_to=transfer_to,
                transfer_reason=transfer_account.transfer_reason,
                account_id=account_id,
                account_payment_id=account_payment_id,
            )
        )
    context = {
        'collection_transfer_list': table_list,
        'num_pages': list(range(paginator.num_pages)),
        'current_page': int(page_number)
    }
    return render(
        request,
        template,
        context
    )


@julo_login_required
def add_new_transfer_account(request):
    template = 'collection_vendor/transfer_account_form.html'
    context = {
        'vendors': CollectionVendor.objects.normal().exclude(is_active=False).order_by('-cdate'),
        'is_show': False,
        'save_type': '',
        'vendor_name_error': '',
        'success_save': False,
        'error_message': '',
        'transfer_type_count': CollectionVendorAssigmentTransferType.objects.all().count(),
        'available_products': (('j1', 'J1'), ('grab', 'Grab'), ('mtl', 'Pre-j1 Product'))
    }
    application_xid = request.GET.get('application_xid')
    try:
        if application_xid:
            int(application_xid)
    except ValueError as e:
        return JsonResponse(
            status=400,
            data={
                "status": "failed",
                "message": "application_xid has wrong format",
                "error": str(e)
            })

    account_id = request.GET.get('account_id')
    selected_available_product = request.GET.get('product_type')
    if application_xid or account_id:
        context['application_xid'] = application_xid
        context['account_id'] = account_id
        context['selected_available_product'] = selected_available_product
        context['transfer_from_labels'] = 'inhouse'
        is_julo_one = True if account_id else False
        context['is_julo_one'] = is_julo_one
        if is_julo_one:
            filter_assigned_from = dict(
                is_active_assignment=True,
                account_payment__account_id=account_id
            )
        else:
            filter_assigned_from = dict(
                is_active_assignment=True,
                payment__loan__application__application_xid=application_xid
            )
        assigned_from = CollectionVendorAssignment.objects.filter(
            **filter_assigned_from).last()
        context['transfer_from_labels'] = 'vendor'
        if not assigned_from:
            assigned_from = AgentAssignment.objects.filter(**filter_assigned_from).last()
            context['transfer_from_labels'] = 'agent'

        if assigned_from:
            formated_assigned_from = format_assigment_transfer_from(
                assigned_from, is_julo_one=is_julo_one)
            context.update(formated_assigned_from)
        else:
            context['transfer_from_labels'] = 'inhouse'
            loan = None
            account = None
            if not is_julo_one:
                loan = Loan.objects.get_or_none(
                    application__application_xid=application_xid,
                    ever_entered_B5=True)
            else:
                account = Account.objects.get_or_none(
                    id=account_id, ever_entered_B5=True)
            if loan and loan.get_oldest_unpaid_payment():
                payment = loan.get_oldest_unpaid_payment()
                application = loan.application
                customer = application.customer
                context['application_id'] = application.id
                context['assign_time'] = '-'
                context['dpd_assign_time'] = '-'
                context['dpd_today'] = payment.due_late_days
                context['sub_bucket_assign_time'] = '-'
                sub_bucket_today = get_current_sub_bucket(payment)
                context['sub_bucket_today'] = '-'
                if sub_bucket_today:
                    context['sub_bucket_today'] = sub_bucket_today.sub_bucket_label

                context['loan_id'] = payment.loan.id
                context['payment_id'] = payment.id
                context['customer_name'] = customer.fullname
                context['customer_email'] = customer.email
                context['transfer_from'] = 'inhouse'
                context['transfer_from_id'] = 'inhouse'
            elif account and account.get_oldest_unpaid_account_payment():
                account_payment = account.get_oldest_unpaid_account_payment()
                application = account.application_set.last()
                customer = application.customer
                context['application_id'] = application.id
                context['assign_time'] = '-'
                context['dpd_assign_time'] = '-'
                context['dpd_today'] = account_payment.dpd
                context['sub_bucket_assign_time'] = '-'
                sub_bucket_today = get_current_sub_bucket(account_payment, is_julo_one=True)
                context['sub_bucket_today'] = '-'
                if sub_bucket_today:
                    context['sub_bucket_today'] = sub_bucket_today.sub_bucket_label

                context['account_payment_id'] = account_payment.id
                context['customer_name'] = customer.fullname
                context['customer_email'] = customer.email
                context['transfer_from'] = 'inhouse'
                context['transfer_from_id'] = 'inhouse'
                context['payment_id'] = ''

        context['is_show'] = True

    if request.POST:
        user = request.user
        serializer = CollectionVendorManualTransferSerializer(
            data=request.POST)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        context = manual_transfer_assignment(data, user, context)

    return render(
        request,
        template,
        context
    )


@julo_login_required
def collection_retain_data(request):
    template = 'collection_vendor/retain_data.html'
    collection_vendor_assignments = CollectionVendorAssignment.objects.filter(
        is_extension=True,
        vendor_assignment_extension__isnull=False
    ).order_by('-cdate')
    paginator = Paginator(
        collection_vendor_assignments, 100)
    page_number = request.GET.get('page_number')
    if not page_number:
        page_number = 1

    try:
        result_data = paginator.page(page_number)
    except PageNotAnInteger:
        result_data = paginator.page(1)
        page_number = 1
    except EmptyPage:
        result_data = paginator.page(paginator.num_pages)

    context = {
        'collection_assignment_extension_list': result_data,
        'current_page': int(page_number),
        'num_pages': list(range(paginator.num_pages))
    }
    return render(
        request,
        template,
        context
    )


def get_data_assignment(request, application_xid):
    application = Application.objects.get_or_none(application_xid=application_xid)
    account = Account.objects.get_or_none(id=application_xid)
    if not application and not account:
        return JsonResponse({
            'status': 'fail',
            'messages': 'application atau account tidak ditemukan'
        })
    is_julo_one = True if account else False
    collection_vendor_assignment_filter = dict(
        is_active_assignment=True,
    )
    if is_julo_one:
        application = account.application_set.last()
        oldest_payment = account.get_oldest_unpaid_account_payment()
        if not oldest_payment:
            return JsonResponse({
                'status': 'fail',
                'messages': 'account payment tidak ditemukan'
            })
        collection_vendor_assignment_filter['account_payment'] = oldest_payment
        data = dict(
            account_id=account.id,
            account_payment_id=oldest_payment.id,
        )
    else:
        loan = Loan.objects.get_or_none(application=application)
        if not loan:
            return JsonResponse({
                'status': 'fail',
                'messages': 'loan tidak ditemukan'
            })
        oldest_payment = loan.get_oldest_unpaid_payment()
        collection_vendor_assignment_filter['payment'] = oldest_payment
        data = dict(
            loan_id=loan.id,
            payment_id=oldest_payment.id,
        )
    collection_vendor_assignment = CollectionVendorAssignment.objects.filter(
        **collection_vendor_assignment_filter
    ).last()
    if not collection_vendor_assignment:
        return JsonResponse({
            'status': 'fail',
            'messages': 'Account tidak memiliki vendor assignment yang masih aktif'
        })

    subbucket = get_current_sub_bucket(oldest_payment, is_julo_one=is_julo_one)
    if collection_vendor_assignment.vendor_assignment_extension and \
            collection_vendor_assignment.vendor_assignment_extension.vendor.id == \
            collection_vendor_assignment.vendor.id and \
            collection_vendor_assignment.vendor_assignment_extension.sub_bucket_current.id == \
            subbucket.id:
        return JsonResponse({
            'status': 'fail',
            'messages': 'Account sudah pernah di-retain sebelumnya oleh Vendor'
                        ' ini pada periode Sub Bucket yang sama'
        })
    if (oldest_payment.due_late_days + 30) > 720:
        return JsonResponse({
            'status': 'fail',
            'messages': 'Account ini telah melewati DPD 720 pada saat'
                        'Retain Removal Date (1 bulan dari sekarang)'
        })
    extension_date = collection_vendor_assignment.get_expiration_assignment + timedelta(days=30)
    customer = application.customer
    data.update(
        application_id=application.id,
        assign_time=format_date(collection_vendor_assignment.assign_time.date(),
                                'd MMMM yyyy', locale='id_ID'),
        dpd=collection_vendor_assignment.dpd_assign_time,
        dpd_current=oldest_payment.due_late_days,
        subbucket='dpd{}_dpd{}'.format(
            collection_vendor_assignment.sub_bucket_assign_time.start_dpd,
            collection_vendor_assignment.sub_bucket_assign_time.end_dpd,
        ),
        subbucket_current='dpd{}_dpd{}'.format(
            subbucket.start_dpd,
            subbucket.end_dpd,
        ),
        customer_name=customer.fullname,
        customer_email=customer.email,
        vendor_id=collection_vendor_assignment.vendor.id,
        extension_date=format_date(extension_date, 'd MMMM yyyy', locale='id_ID'),
        is_julo_one=is_julo_one
    )

    return JsonResponse({
        'status': 'success',
        'data': data
    })


def store_retain_data(request):
    data = request.POST.dict()
    user = request.user
    serializer = CollectionVendorAssignmentExtensionSerializer(data=data)
    serializer.is_valid(raise_exception=True)
    data = serializer.data
    account_payment = None
    payment = None
    if data['account_payment_id']:
        account_payment = AccountPayment.objects.get_or_none(
            pk=data['account_payment_id'])
    else:
        payment = Payment.objects.get_or_none(pk=data['payment_id'])

    is_julo_one = True if account_payment else False
    if not payment and not account_payment:
        return JsonResponse({
            'status': 'fail',
            'messages': 'Payment atau account payment tidak ditemukan'
        })
    vendor = CollectionVendor.objects.get_or_none(pk=data['vendor_id'])
    collection_vendor_assignment_filter = dict(is_active_assignment=True)
    if is_julo_one:
        sub_bucket = get_current_sub_bucket(account_payment, is_julo_one=True)
        collection_vendor_assignment_filter.update(
            account_payment=account_payment,
        )
        collection_vendor_assignment_extension_data = dict(
            account_payment=account_payment,
            dpd_current=account_payment.dpd,
        )
    else:
        sub_bucket = get_current_sub_bucket(payment)
        collection_vendor_assignment_filter.update(
            payment=payment,
        )
        collection_vendor_assignment_extension_data = dict(
            payment=payment,
            dpd_current=payment.due_late_days,
        )

    collection_vendor_assignment = CollectionVendorAssignment.objects.filter(
        **collection_vendor_assignment_filter
    ).last()
    if not collection_vendor_assignment:
        return JsonResponse({
            'status': 'fail',
            'messages': 'Payment ini belum diassign ke vendor'
        })
    extension_date = collection_vendor_assignment.get_expiration_assignment + timedelta(days=30)
    collection_vendor_assignment_extension_data.update(
        vendor=vendor,
        sub_bucket_current=sub_bucket,
        retain_reason=data['retain_reason'],
        retain_removal_date=extension_date,
        retain_inputted_by=user
    )
    collection_vendor_assignment_extension = CollectionVendorAssignmentExtension.objects.create(
        **collection_vendor_assignment_extension_data
    )

    collection_vendor_assignment.update_safely(
        is_extension=True,
        vendor_assignment_extension=collection_vendor_assignment_extension
    )

    return JsonResponse({
        'status': 'success',
        'messages': 'Account vendor berhasil di retain'
    })


@julo_login_required
def collection_retain_form(request):
    template = 'collection_vendor/retain_form.html'
    context = {
        'available_products': (
            ('j1', 'J1'), ('grab', 'Grab'), ('mtl', 'Pre-j1 Product')
        )
    }
    return render(
        request, template_name=template, context=context)


@julo_login_required
def list_report_vendor(request):
    template = 'collection_vendor/upload_report_vendor_list.html'
    context = {
        'upload_report_vendor_list': UploadVendorReport.objects.all().order_by('-id')[:20],
        'title': 'CHECK UPLOAD HISTORY (LAST 20 DATA)'
    }

    return render(request, template, context)


@julo_login_required
def upload_report_vendor(request):
    template = 'collection_vendor/upload_report_vendor_form.html'
    context = {
        'vendors': CollectionVendor.objects.filter(is_active=True).order_by('-id')
    }

    return render(request, template, context)


@julo_login_required
def submit_report_vendor(request):
    data = request.FILES.dict()
    template = 'collection_vendor/upload_report_vendor_list.html'
    file_uploads = []
    for vendor_name, file_name in list(data.items()):
        data_xls = xls_to_dict(file_name)['Sheet1']
        is_valid, errors = validate_data_calling_result(data_xls)
        collection_vendor = CollectionVendor.objects.filter(
            vendor_name=re.sub(r"\d+", "", vendor_name)
        ).last()
        with transaction.atomic():
            upload_vendor_report = UploadVendorReport.objects.create(
                file_name=file_name,
                vendor=collection_vendor,
                upload_status='success' if is_valid else 'failed',
            )

            if is_valid:
                store_related_data_calling_vendor_result_task.delay(data_xls)
            else:
                store_error_information_calling_vendor_result(errors, upload_vendor_report)
                url_path = '/collection_vendor/download_error_information/'
                url_download_error_info = settings.BASE_URL + url_path + str(
                    upload_vendor_report.id
                )
                upload_vendor_report.update_safely(error_details=url_download_error_info)
            file_uploads.append(upload_vendor_report)

    context = {
        'upload_report_vendor_list': file_uploads,
        'title': 'HASIL UPLOAD'
    }
    return render(request, template, context)


def download_error_information(request, *args, **kwargs):
    upload_vendor_report_id = kwargs['upload_vendor_report_id']
    upload_vendor_report = UploadVendorReport.objects.filter(pk=upload_vendor_report_id).last()
    if not upload_vendor_report:
        return render(request, 'covid_refinancing/404.html')
    date_upload = timezone.localtime(upload_vendor_report.cdate).date().strftime('%d%m%Y')
    response = HttpResponse(
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    response['Content-Disposition'] = 'attachment; filename=ErrorInfo_{}_{}_{}.xlsx'.format(
        date_upload,
        upload_vendor_report.vendor.vendor_name,
        upload_vendor_report.file_name
    )
    wb = xlwt.Workbook()
    ws = wb.add_sheet("List error call result vendor", cell_overwrite_ok=True)
    font_style = xlwt.XFStyle()
    font_style.font.bold = True
    row_num = 0
    columns = ('Error ID',
               'File Name',
               'Vendor Name',
               'Application XID',
               'Account ID',
               'Field',
               'Error Reason',
               'Value')

    column_size = list(range(len(columns)))
    for col_num in column_size:
        ws.write(row_num, col_num, columns[col_num], font_style)

    vendor_report_error_information = VendorReportErrorInformation.objects.filter(
        upload_vendor_report=upload_vendor_report
    )

    for error_data in vendor_report_error_information:
        row_num = row_num + 1
        data = (error_data.id,
                error_data.upload_vendor_report.file_name,
                error_data.upload_vendor_report.vendor.vendor_name,
                error_data.application_xid,
                error_data.account.id if error_data.account else None,
                error_data.field,
                error_data.error_reason,
                error_data.value)

        font_style = xlwt.XFStyle()

        data_size = list(range(len(data)))
        for data_slice in data_size:
            ws.write(row_num, data_slice, data[data_slice], font_style)

    wb.save(response)

    return response


@julo_login_required
@julo_login_required_group('collection_supervisor')
def agent_removal_page(request):
    template = 'collection_vendor/agent_removal_list.html'
    agent_username = request.POST.get('agent_username')
    loan_or_account_id = request.POST.get('loan_or_account_id')
    input_mode = request.POST.get('input_mode')
    agent_assignment_list = []
    if request.POST:
        agent_assignment_filter = dict(
            is_active_assignment=True
        )
        if input_mode == 'loan_or_account_mode':
            type_result = determine_input_is_account_id_or_loan_id(
                loan_or_account_id)
            agent_assignment_filter[type_result] = loan_or_account_id
        elif agent_username:
            user_obj = User.objects.filter(
                username=agent_username.lower()).last()
            if not user_obj:
                context = {
                    'agent_assignment_list': [],
                    'loan_or_account_id': loan_or_account_id,
                    'agent_username': agent_username,
                    'input_mode': input_mode,
                    'error_message': "agent dengan username {} tidak dapat ditemukan".format(
                        agent_username
                    )
                }
                return render(
                    request,
                    template,
                    context
                )
            agent_assignment_filter['agent_id'] = user_obj.id

        agent_assignment_list = AgentAssignment.objects.filter(
            **agent_assignment_filter).order_by('-cdate')
        agent_assignment_list = format_agent_assignment_list_for_removal_agent_menu(
            agent_assignment_list
        )

    context = {
        'agent_assignment_list': agent_assignment_list,
        'loan_or_account_id': loan_or_account_id,
        'agent_username': agent_username,
        'input_mode': input_mode
    }
    return render(
        request,
        template,
        context
    )


def process_agent_removal(request):
    data = request.POST.dict()
    agent_assignment_ids = data.get('agent_assignment_ids').split(',')
    agent_assignment_ids = list(map(int, agent_assignment_ids))
    today = timezone.localtime(timezone.now())
    agent_assignments = AgentAssignment.objects.filter(
        id__in=agent_assignment_ids, is_active_assignment=True
    )
    # record history new_assignment=None means return back into inhouse
    bulk_create_assignment_movement_history_base_on_agent_assignment(
        agent_assignments,
        CollectionAssignmentConstant.ASSIGNMENT_REASONS[
            'ACCOUNT_MANUALLY_TRANSFERRED_INHOUSE'],
        new_assignment=None
    )
    tomorrow = today.date() + timedelta(days=1)
    unassign_data = agent_assignments.update(
        is_active_assignment=False, unassign_time=tomorrow
    )
    if not unassign_data:
        return JsonResponse({
            'status': 'failed',
            'messages': 'Agent Berhasil di remove'
        })
    # delete PTP data
    agent_assignments = AgentAssignment.objects.filter(
        id__in=agent_assignment_ids
    )
    remove_active_ptp_after_agent_removal(agent_assignments)

    return JsonResponse({
        'status': 'success',
        'messages': 'Agent Berhasil di remove'
    })


def process_agent_transfer(request):
    data = request.POST.dict()
    agent_assignment_ids = data.get('agent_assignment_ids').split(',')
    agent_assignment_ids = list(map(int, agent_assignment_ids))
    today = timezone.localtime(timezone.now())
    new_agent_username = data.get('new_agent_username')
    new_agent_user = User.objects.filter(
        username=new_agent_username.lower()).last()
    if not new_agent_user:
        return JsonResponse({
            'status': 'failed',
            'messages': 'Agent dengan username {} tidak ada'.format(
                new_agent_username
            )
        })

    old_agent_assignments = AgentAssignment.objects.filter(
        id__in=agent_assignment_ids, is_active_assignment=True
    )
    tomorrow = today.date() + timedelta(days=1)
    unassign_old_agent_assignments = old_agent_assignments.update(
        is_active_assignment=False, unassign_time=tomorrow
    )
    if not unassign_old_agent_assignments:
        return JsonResponse({
            'status': 'failed',
            'messages': 'error saat unassign agent assignment'
        })

    old_agent_assignments = AgentAssignment.objects.filter(
        id__in=agent_assignment_ids,
    )
    success_create_new_agent_assignment = move_agent_assignment_to_new_agent(
        old_agent_assignments, new_agent_user, tomorrow
    )
    if not success_create_new_agent_assignment:
        return JsonResponse({
            'status': 'failed',
            'messages': 'error saat create new agent assignment'
        })

    # record history new_assignment=None means return back into inhouse
    bulk_create_assignment_movement_history_base_on_agent_assignment(
        old_agent_assignments,
        CollectionAssignmentConstant.ASSIGNMENT_REASONS[
            'ACCOUNT_MANUALLY_TRANSFERRED_AGENT'],
        new_assignment=new_agent_user
    )
    return JsonResponse({
        'status': 'success',
        'messages': 'Agent Berhasil di remove'
    })


@julo_login_required
@julo_login_required_multigroup(
    ['bo_data_verifier', 'collection_supervisor', 'waiver_b1_approver',
     'waiver_b2_approver', 'waiver_b3_approver', 'waiver_b4_approver',
     'waiver_b5_approver', 'admin_full', 'product_manager'])
def recording_detail_list(request):
    template = 'collection_vendor/recording_detail_list.html'
    page_number = 1
    context = dict(
        current_page=page_number,
        is_search_filled=False,
    )
    # faster query to filter only 1 week data
    week_before = date.today() - relativedelta(days=7)
    recording_detail_lists = (
        VendorRecordingDetail.objects.select_related('agent', 'skiptrace').filter(
            recording_url__isnull=False,
            cdate__date__gte=week_before,
        ).order_by('-call_start').only(
            'id', 'call_start', 'call_end', 'duration', 'account_payment__account_id',
            'account_payment__id', 'agent__username', 'bucket', 'call_to',
            'skiptrace__contact_source'
        )
    )
    if request.POST:
        # reset page number
        data = request.POST
        page_number = 1 if not data.get('page_number') else data.get('page_number')
        search_call_date_mode = data.get('search_call_date_mode')
        search_duration_mode = data.get('search_duration_mode')
        search_negative_score_mode = data.get('search_negative_score_mode')
        search_sop_score_mode = data.get('search_sop_score_mode')
        search_value_call_start = data.get('global_search_value_call_start')
        search_value_call_end = data.get('global_search_value_call_end')
        search_value_duration = data.get('global_search_value_duration')
        search_value_account_id = data.get('global_search_value_account_id')
        search_value_account_payment_id = data.get(
            'global_search_value_account_payment_id')
        search_value_agent = data.get('global_search_value_agent')
        search_value_bucket = data.get('global_search_value_bucket')
        search_value_call_to = data.get('global_search_value_call_to')
        search_value_negative_score = data.get('global_search_value_negative_score')
        search_value_sop_score = data.get('global_search_value_sop_score')
        search_value_id = data.get('global_search_value_id')
        search_value_source = data.get('global_search_value_source')
        context.update(
            search_call_date_mode=search_call_date_mode,
            search_call_date_start=data.get('search_call_date_1'),
            search_call_date_end=data.get('search_call_date_2'),
            search_duration_mode=search_duration_mode,
            search_duration_start=data.get('search_duration_filter_1'),
            search_duration_end=data.get('search_duration_filter_2'),
            search_value_call_start=search_value_call_start,
            search_value_call_end=search_value_call_end,
            search_value_duration=search_value_duration,
            search_value_account_id=search_value_account_id,
            search_value_account_payment_id=search_value_account_payment_id,
            search_value_agent=search_value_agent,
            search_value_bucket=search_value_bucket,
            search_value_call_to=search_value_call_to,
            page_number=page_number,
            search_negative_score_mode=search_negative_score_mode,
            search_negative_score_start=data.get('search_negative_score_filter_1'),
            search_negative_score_end=data.get('search_negative_score_filter_2'),
            search_sop_score_mode=search_sop_score_mode,
            search_sop_score_start=data.get('search_sop_score_filter_1'),
            search_sop_score_end=data.get('search_sop_score_filter_2'),
            search_value_negative_score=search_value_negative_score,
            search_value_sop_score=search_value_sop_score,
            search_value_id=search_value_id,
            search_value_source=search_value_source
        )
        filter_data = generate_filter_for_recording_detail(data)
        recording_detail_lists = recording_detail_lists.filter(
            **filter_data).order_by('-call_start')
        context.update(is_search_filled=True)

    paginator = Paginator(
        recording_detail_lists, 15)
    try:
        result_data = paginator.page(page_number)
    except PageNotAnInteger:
        result_data = paginator.page(1)
    except EmptyPage:
        result_data = paginator.page(paginator.num_pages)

    context.update(recording_detail_lists=result_data)
    return render(
        request,
        template,
        context
    )


@julo_login_required
def download_recording_detail_file(request, recording_detail_id):
    vendor_recording_detail = get_object_or_404(
        VendorRecordingDetail, id=recording_detail_id)
    recording_file_stream = get_file_from_oss(
        settings.OSS_JULO_COLLECTION_BUCKET, vendor_recording_detail.oss_recording_path)
    response = StreamingHttpResponse(
        streaming_content=recording_file_stream, content_type='application/wav')
    downloaded_file_name = 'filename="{}"'.format(
        vendor_recording_detail.downloaded_file_name
    )
    response['Content-Disposition'] = downloaded_file_name
    return response


@never_cache
def get_bulk_download_progress(request, task_id):
    progress = Progress(task_id)
    response = progress.get_info()
    if progress.result.state == 'SUCCESS':
        response.update(download_cache_id=progress.result.description)

    return HttpResponse(json.dumps(response), content_type='application/json')


def process_bulk_download_trigger(request):
    data = request.POST
    recording_detail_lists = (
        VendorRecordingDetail.objects.using(
            REPAYMENT_ASYNC_REPLICA_DB).select_related(
                'agent', 'skiptrace').filter(
                    recording_url__isnull=False).order_by(
                        '-call_start').only(
                            'id', 'call_start', 'call_end', 'duration',
                            'account_payment__account_id', 'account_payment__id',
                            'agent__username', 'bucket', 'call_to',
                            'skiptrace__contact_source'
        )
    )
    filter_data = generate_filter_for_recording_detail(data)
    vendor_recording_list_ids = recording_detail_lists.filter(
        **filter_data).order_by('id').values_list('id', flat=True)
    vendor_recording_list_ids_sorted = list(vendor_recording_list_ids)
    vendor_recording_list_ids_sorted = [
        str(vendor_recording_id) for vendor_recording_id in vendor_recording_list_ids_sorted
    ]
    download_cache = BulkVendorRecordingFileCache.objects.filter(
        expire_date__gte=timezone.localtime(timezone.now()),
        cache_vendor_recording_detail_ids=','.join(vendor_recording_list_ids_sorted)
    ).last()
    if download_cache and download_cache.total_data == vendor_recording_list_ids.count():
        # send existing link
        return JsonResponse({
            'status': 'success',
            'download_cache_id': download_cache.id,
            'task_id': None
        })

    dialer_task = DialerTask.objects.create(
        type=DialerTaskType.BULK_DOWNLOAD_RECORDING_PROCESS_INTELIX,
        error=''
    )
    process_download_async = process_bulk_download_recording_files.delay(
        list(vendor_recording_list_ids), dialer_task.id
    )
    redisClient = get_redis_client()
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


def do_bulk_download(request):
    data = request.POST
    download_cache_id = data.get('download_cache_id')
    now = timezone.localtime(timezone.now())
    bulk_recording_cache = BulkVendorRecordingFileCache.objects.filter(
        pk=download_cache_id, expire_date__gte=now
    ).last()
    if not bulk_recording_cache:
        return JsonResponse({
            'status': 'failed',
            'messages': "Waktu Penyimpanan telah habis, silahkan coba lagi"
        })
    zip_url = get_oss_presigned_url(
        settings.OSS_JULO_COLLECTION_BUCKET,
        bulk_recording_cache.zip_recording_file_url,
        expires_in_seconds=600
    )
    return JsonResponse({
        'status': 'success',
        'zip_url': zip_url
    })


def bulk_account_transfer_post(request):
    import csv
    import io
    try:
        reason = request.POST.get('reason')
        vendor_file = request.FILES['bulk_transfer']
        csv_file = vendor_file.read().decode('utf-8')
        response = HttpResponse(content_type='text/csv')
        today = timezone.localtime(timezone.now())
        formatted_date = dateformat.format(today, 'dmy-Hi')
        response['Content-Disposition'] = 'attachment; filename=\
            failed_B5_bulk_upload_list_{}.csv'.format(formatted_date)
        writer = csv.writer(response)
        writer.writerow(['application_xid', 'vendor_id', 'message'])
        not_processed = 0
        if csv_file:
            reader = csv.DictReader(io.StringIO(csv_file), delimiter=',')
            for line in reader:
                try:
                    application_xid = line['application_xid']
                    vendor_id = line['vendor_id']
                    if not application_xid:
                        continue
                    if not vendor_id:
                        continue
                    application = Application.objects.filter(
                        application_xid=application_xid).last()
                    if application:
                        new_vendor = CollectionVendor.objects.get(pk=vendor_id)
                        if not new_vendor:
                            not_processed += 1
                            message = 'vendor not found'
                            writer.writerow([application_xid, vendor_id, message])
                            continue
                        if not new_vendor.is_active:
                            not_processed += 1
                            message = 'vendor is not active'
                            writer.writerow([application_xid, vendor_id, message])
                            continue
                        account = application.account
                        if account:
                            is_julo_one = True
                            account_payment = account.get_last_unpaid_account_payment()
                            if account_payment:
                                CollectionVendorAssignment.objects.filter(
                                    is_active_assignment=True, account_payment=account_payment.id
                                ).update(is_active_assignment=False, unassign_time=today)
                                AgentAssignment.objects.filter(
                                    is_active_assignment=True, account_payment=account_payment.id
                                ).update(is_active_assignment=False)
                                is_processed, message = assign_new_vendor(
                                    account_payment, new_vendor, is_julo_one, reason
                                )
                                if not is_processed:
                                    not_processed += 1
                                    writer.writerow([application_xid, vendor_id, message])
                            else:
                                message = 'account payment is not found'
                                not_processed += 1
                                writer.writerow([application_xid, vendor_id, message])
                                continue
                        else:
                            is_julo_one = False
                            loan = Loan.objects.get_or_none(application=application)
                            if not loan:
                                message = 'loan is not found'
                                not_processed += 1
                                writer.writerow([application_xid, vendor_id, message])
                                continue
                            payment = loan.get_oldest_unpaid_payment()
                            AgentAssignment.objects.filter(
                                is_active_assignment=True, payment__loan_id=loan.id
                            ).update(is_active_assignment=False)
                            if payment:
                                CollectionVendorAssignment.objects.filter(
                                    is_active_assignment=True, payment=payment.id
                                ).update(is_active_assignment=False, unassign_time=today)
                                is_processed, message = assign_new_vendor(
                                    payment, new_vendor, is_julo_one, reason
                                )
                                if not is_processed:
                                    not_processed += 1
                                    writer.writerow([application_xid, vendor_id, message])
                            else:
                                message = 'payment is not found'
                                not_processed += 1
                                writer.writerow([application_xid, vendor_id, message])
                                continue
                    else:
                        not_processed += 1
                        writer.writerow([application_xid, vendor_id, 'application not found'])
                except Exception as e:
                    not_processed += 1
                    application_xid = line['application_xid']
                    vendor_id = line['vendor_id']
                    writer.writerow([application_xid, vendor_id, e])
        if not_processed > 0:
            return response
        template = 'collection_vendor/upload_bulk_account_transfer.html'
        context = {'load_message': 'success'}
        return render(request, template, context)
    except:
        template = 'collection_vendor/upload_bulk_account_transfer.html'
        context = {'load_message': 'failed'}
        return render(request, template, context)


@julo_login_required
def bulk_account_transfer(request):
    errors = ''
    message = ''
    if request.POST:
        uploaded_file = request.FILES['uploaded_file']
        form = VendorBulkTransferSerializer(request.POST, request.FILES)
        if form.is_valid():
            csv_data = form.cleaned_data.get('uploaded_file')
            bulk_transfer_vendor_async.delay(
                csv_data, uploaded_file.name, form.data.get('reason'))
            message = 'success'
        else:
            errors = form.errors.values()
            message = 'failed'

    template = 'collection_vendor/upload_bulk_account_transfer.html'
    context = {
        'load_message': message,
        'errors': errors
    }
    return render(request, template, context)
