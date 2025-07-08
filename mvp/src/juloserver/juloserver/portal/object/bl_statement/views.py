from __future__ import print_function
from builtins import str
import json
import phonenumbers
import logging

from dateutil.parser import parse
from django.shortcuts import render, redirect
from django.views.decorators.csrf import csrf_protect
from django.db import transaction
from django.db.models import Q
from django.http.response import (HttpResponseNotAllowed,
                                  JsonResponse,
                                  HttpResponse,
                                  HttpResponseNotFound,
                                  HttpResponseBadRequest)
from object import julo_login_required, julo_login_required_exclude

from juloserver.paylater.constants import StatementEventConst
from juloserver.julo.models import (Customer,
                                    Skiptrace,
                                    PaymentMethod,
                                    SmsHistory)
from juloserver.paylater.models import (Statement,
                                        StatementLock,
                                        StatementNote,
                                        StatementPtp,
                                        SkipTraceHistoryBl,
                                        TransactionOne,
                                        InvoiceDetail)
from juloserver.julo.utils import format_e164_indo_phone_number
from juloserver.paylater.services import StatementEventServices

from .utils import statement_parse_pass_due, unlock_statement, lock_statement
from .serializers import SkiptraceHistoryBlSerializer
from juloserver.paylater.constants import LineTransactionType
from juloserver.julo.payment_methods import PaymentMethodCodes
from juloserver.julo.banks import BankCodes
from juloserver.paylater.tasks import send_sms_bukalapak_notify_va_created

logger = logging.getLogger(__name__)

@julo_login_required
@julo_login_required_exclude(['bo_credit_analyst'])
def statement_list_view(request, status_code):
    template_name = 'object/bl_statement/list.html'
    status_title, bucket_title = statement_parse_pass_due(str(status_code))

    return render(
        request,
        template_name,
        {
            'status_code': status_code,
            'bucket_title': bucket_title
        }
    )


@csrf_protect
def ajax_create_statement_note(request):
    if request.method != 'POST':
        return HttpResponseNotAllowed(["POST"])

    note = str(request.POST.get('note', ''))
    statement_id = int(request.POST.get('statement_id'))
    statement = Statement.objects.get_or_none(pk=statement_id)
    if not statement:
        return JsonResponse({
            'status': 'failed',
            'message': 'statement {} not found'.format(statement_id)
        })

    if note:
        StatementNote.objects.create(
            note_text=note,
            statement=statement,
            added_by=request.user
        )

    return JsonResponse({
        'status': 'success'
    })


@csrf_protect
def ajax_lock_statement(request):
    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])

    user = request.user
    statement_id = str(request.POST.get('statement_id', ''))
    statement_to_lock = Statement.objects.get(id=statement_id)
    is_statement_lock = lock_statement(user, statement_to_lock)

    if is_statement_lock:
        return JsonResponse({
            'result': 'success',
            'msg': 'Sucess lock statement'
        })
    else:
        return JsonResponse({
            'result': 'failed',
            'msg': 'Failed to lock statement'
        })


@csrf_protect
def ajax_unlock_statement(request):
    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])

    user = request.user
    statement_id = str(request.POST.get('statement_id', ''))
    statement_to_unlock = Statement.objects.get(id=statement_id)

    if not statement_to_unlock:
        return JsonResponse({
            'result': 'failed',
            'msg': 'Statement already unlocked'
        })
    else:
        is_statement_unlock = unlock_statement(user, statement_to_unlock)

    if is_statement_unlock:
        return JsonResponse({
            'result': 'success',
            'msg': 'Statement unlocked'
        })
    else:
        return JsonResponse({
            'result': 'failed',
            'msg': 'Failed to unlock statement'
        })


@csrf_protect
def ajax_statement_list_view(request):
    if request.method != 'GET':
        return HttpResponseNotAllowed(['GET'])

    statement_manager = Statement.objects
    status_code = request.GET.get('status_code')
    here_title_status = None

    try:
        current_page = int(request.GET.get('current_page'))
        max_per_page = int(request.GET.get('max_per_page'))
    except:
        page = 1
        max_per_page = 50

    status_title, bucket_title = statement_parse_pass_due(status_code)
    if status_title == 0:
        qs = statement_manager.bucket_list_t0()
    elif status_title == 15:
        qs = statement_manager.bucket_list_t1_to_t5()
    elif status_title == 614:
        qs = statement_manager.bucket_list_t6_to_t14()
    elif status_title == 1529:
        qs = statement_manager.bucket_list_t15_to_t29()
    elif status_title == 3044:
        qs = statement_manager.bucket_list_t30_to_t44()
    elif status_title == 4559:
        qs = statement_manager.bucket_list_t45_to_t59()
    elif status_title == 6089:
        qs = statement_manager.bucket_list_t60_to_t89()
    elif status_title == 9000:
        qs = statement_manager.bucket_list_t90plus()
    elif status_title == 200:
        qs = statement_manager

    search_q = request.GET.get('search_q').strip()
    statements = qs.values('id', 'statement_due_date',
                            'statement_due_amount',
                            'statement_status__status_code',
                            'account_credit_limit__account_credit_limit',
                            'account_credit_limit__available_credit_limit',
                            'customer_credit_limit__customer__fullname')
    statements_count =  statements.count()

    statement_lock_list = list(StatementLock.objects.all().values('statement'))
    statement_lock_list_statement_id_only = []

    # to get value without the column name and stored in arr
    for statement_lock in statement_lock_list:
        statement_lock_list_statement_id_only.append(statement_lock['statement'])

    if search_q and status_title == 200:
        if search_q.isnumeric():
            statements = statements.filter(Q(id=search_q) | Q(customer_credit_limit__customer__phone=search_q) \
                | Q(customer_credit_limit__customer__customer_xid=search_q))

        else:
            statements = statements.filter(Q(customer_credit_limit__customer__fullname__icontains=search_q) \
                | Q(customer_credit_limit__customer__email=search_q))

        return JsonResponse({
            'status': 'success',
            'statements': list(statements),
            'statements_count': statements_count,
            'max_per_page': max_per_page,
            'current_page': current_page,
            'statement_lock_list': statement_lock_list_statement_id_only
        }, safe=False)

    elif search_q:
        if search_q.isnumeric():
            statement_id = int(search_q)
            statements = statements.filter(id=statement_id)

        else:
            fullname_to_match = str(search_q)
            statements = statements.filter(customer_credit_limit__customer__fullname__icontains=fullname_to_match)

        return JsonResponse({
            'status': 'success',
            'statements': list(statements),
            'statements_count': statements_count,
            'max_per_page': max_per_page,
            'current_page': current_page,
            'statement_lock_list': statement_lock_list_statement_id_only
        }, safe=False)

    #pagination
    first_offset_page = (current_page - 1) * max_per_page
    last_offset_page =  current_page * max_per_page
    statements = statements[first_offset_page : last_offset_page]

    return JsonResponse({
        'status': 'success',
        'statements': list(statements),
        'statements_count': statements_count,
        'max_per_page': max_per_page,
        'current_page': current_page,
        'statement_lock_list': statement_lock_list_statement_id_only
    }, safe=False)


@julo_login_required
@julo_login_required_exclude(['bo_credit_analyst'])
def statement_detail(request, pk):
    user = request.user
    user_groups = user.groups.values_list('name', flat=True).all()
    template_name = 'object/bl_statement/detail.html'
    statement_obj = Statement.objects.get(id=pk)

    customer_obj = statement_obj.customer_credit_limit.customer
    is_hide_transaction = LineTransactionType.is_hide()
    is_hide_transaction.remove("payment")
    transactionsone_obj = list(TransactionOne.objects.filter(statement=pk).exclude(
        transaction_description__in=is_hide_transaction))
    statement_ptp = StatementPtp.objects.filter(statement=statement_obj)\
                                        .order_by('cdate')\
                                        .last()
    transactions_obj = []
    for transactionone_obj in transactionsone_obj:
        #fetch invoice details
        if transactionone_obj.invoice is not None:
            transactionone_obj.invoice_details = transactionone_obj.invoice.transactions.all()
        transactions_obj.append(transactionone_obj)

    statement_lock = StatementLock.objects.get_or_none(statement=statement_obj, agent=request.user)
    show_unlock_button = False
    lock_status = 1
    lock_by = '-'
    is_set_called = 0

    if statement_lock:
        show_unlock_button = True
        lock_status = 0
        lock_by = statement_lock.agent.username

    if statement_obj.is_collection_called:
        is_set_called = 1

    skiptrace_list = Skiptrace.objects.filter(customer=customer_obj).order_by('id')
    skiptrace_history_list = list(SkipTraceHistoryBl.objects.filter(statement=pk)
                                  .order_by('-cdate'))[:100]
    statement_notes = statement_obj.statementnote_set.all().order_by('-cdate')
    statement_event_service = StatementEventServices()
    statement_events_details = statement_event_service.get_dropdown_event(user_groups)
    sms_history_list = list(
        SmsHistory.objects.filter(customer=customer_obj).order_by('-cdate'))

    result_dict = {
        'statement_obj': statement_obj,
        'transactions_obj': transactions_obj,
        'customer_obj': customer_obj,
        'show_unlock_button': show_unlock_button,
        'lock_status': lock_status,
        'lock_by': lock_by,
        'skiptrace_list': skiptrace_list,
        'skiptrace_history_list': skiptrace_history_list,
        'statement_notes': statement_notes,
        'statement_ptp': statement_ptp,
        'is_set_called': is_set_called,
        'statement_events_details': statement_events_details,
        'sms_history_list': sms_history_list
    }

    # get virtual account for direct payment if requested
    payment_method = PaymentMethod.objects.filter(
        customer_credit_limit=statement_obj.customer_credit_limit
    ).last()

    if payment_method:
        result_dict.update({
            'virtual_account': payment_method.virtual_account
        })

    return render(
        request,
        template_name,
        result_dict
    )


########################################## AJAX SKIPTRACE ACTIONS #########################################
@csrf_protect
def add_skiptrace(request):
    if request.method != 'POST':
        return HttpResponseNotAllowed(["POST"])

    data = request.POST.dict()
    customer = Customer.objects.get_or_none(pk=data['customer'])
    if not customer:
        return HttpResponseNotFound("customer id %s not found" % data['customer'])
    try:
        phone_number = phonenumbers.parse(data['phone_number'], "ID")
    except Exception as e:
        return HttpResponseBadRequest("invalid data!! - {}".format(e))

    skiptrace = Skiptrace.objects.create(customer=customer,
                                         phone_number=phone_number,
                                         contact_name=data['contact_name'],
                                         contact_source=data['contact_source'])
    skiptrace.save()
    data['id'] = skiptrace.id
    data['phone_operator'] = skiptrace.phone_operator
    data['effectiveness'] = skiptrace.effectiveness
    data['recency'] = skiptrace.recency
    data['frequency'] = skiptrace.frequency
    return JsonResponse({
        "messages": "save success",
        "data": data
    })


@csrf_protect
def update_skiptrace(request):
    if request.method != 'POST':
        return HttpResponseNotAllowed(["POST"])

    data = request.POST.dict()
    customer = Customer.objects.get_or_none(pk=data['customer'])
    if not customer:
        return HttpResponseNotFound("customer id %s not found" % data['customer'])

    try:
        phone_number = phonenumbers.parse(data['phone_number'], "ID")
    except Exception as e:
        return HttpResponseBadRequest("invalid data!! - {}".format(e))

    skiptrace = Skiptrace.objects.get_or_none(pk=data['skiptrace_id'])
    if not skiptrace:
        return HttpResponseNotFound("skiptrace id %s not found" % data['skiptrace_id'])

    skiptrace.phone_number = phone_number
    skiptrace.contact_source = data['contact_source']
    skiptrace.contact_name = data['contact_name']
    skiptrace.save()
    data['id'] = skiptrace.id
    data['phone_operator'] = skiptrace.phone_operator
    data['effectiveness'] = skiptrace.effectiveness
    data['recency'] = skiptrace.recency
    data['frequency'] = skiptrace.frequency

    return JsonResponse({
        "messages": "save success",
        "data": data
    })


@csrf_protect
def create_skiptrace_history(request):
    if request.method != 'POST':
        return HttpResponseNotAllowed(["POST"])

    data = request.POST.dict()
    statement = Statement.objects.get_or_none(pk=int(data['statement']))

    if not statement:
        return HttpResponseNotFound("statement id %s not found" % data['statement'])

    data['agent'] = request.user.id
    agent_name = request.user.username
    data['source'] = 'CRM'
    skiptrace_history_serializer = SkiptraceHistoryBlSerializer(data=data)

    if not skiptrace_history_serializer.is_valid():
        logger.warn({
            'skiptrace_id': data['skiptrace'],
            'agent_name': agent_name,
            'error_msg': skiptrace_history_serializer.errors
        })

        return HttpResponseBadRequest("data invalid")

    skiptrace_history_serializer.save()

    return JsonResponse({
        "messages": "save success"
    })
######################## END OF AJAX Skiptrace ##################################
def ajax_update_ptp(request):
    if request.method != 'POST':
        return HttpResponseNotAllowed(["POST"])

    data = request.POST.dict()
    statement_id = data['statement_id']
    ptp_amount = int(data['ptp_amount'])
    try:
        ptp_date = parse(data['ptp_date']).date()
    except Exception:
        return JsonResponse({
            'status': 'failed',
            'message': 'invalid format ptp date {}'.format(data['ptp_date'])
        })

    statement = Statement.objects.get_or_none(pk=statement_id)
    if not statement:
        return JsonResponse({
            'status': 'failed',
            'message': 'statement {} not found'.format(statement_id)
        })

    if hasattr(statement, 'statementptp'):
        statement_ptp = statement.statementptp
        statement_ptp.update_safely(ptp_date=ptp_date,
                                    ptp_amount=ptp_amount,
                                    updated_by=request.user)
    else:
        StatementPtp.objects.create(statement=statement,
                                    ptp_date=ptp_date,
                                    ptp_amount=ptp_amount,
                                    updated_by=request.user)

    #create statement note ptpt
    note_text = "Promise to Pay : %s  - Rp.%s" % (ptp_date, ptp_amount)
    StatementNote.objects.create(statement=statement,
                                 note_text=note_text)

    return JsonResponse({
        'status': 'success',
        'message': 'update ptp success',
        'data': data
    })


def ajax_statement_set_called(request):
    if request.method != 'POST':
        return HttpResponseNotAllowed(["POST"])

    data = request.POST.dict()
    statement = Statement.objects.get_or_none(pk=int(data['statement_id']))
    if not statement:
        return JsonResponse({
            'status': 'failed',
            'message': 'statement {} not found'.format(data['statement_id'])
        })

    with transaction.atomic():
        statement.is_collection_called = True
        statement.save()
        if data['note_text']:
            StatementNote.objects.create(statement=statement,
                                         note_text=data['note_text'],
                                         added_by=request.user)
        unlock_statement(request.user, statement)

    return JsonResponse({
        'status': 'success',
        'message': 'set called success',
        'data': data
    })


@csrf_protect
def ajax_create_va_and_send_sms(request):
    if request.method != 'POST':
        return HttpResponseNotAllowed(["POST"])

    data = request.POST.dict()
    statement_id = data['statement_id']
    statement = Statement.objects.get_or_none(pk=statement_id)

    if not statement:
        return JsonResponse({
            'status': 'failed',
            'message': 'statement not found',
        })

    payment_method = PaymentMethod.objects.filter(
        customer_credit_limit=statement.customer_credit_limit
    ).last()

    if not payment_method:
        virtual_account = "".join(
            [PaymentMethodCodes.PERMATA1, str(statement.customer_credit_limit.customer_id)])
        PaymentMethod.objects.create(
            payment_method_code=PaymentMethodCodes.PERMATA1,
            payment_method_name='PERMATA Bank',
            bank_code=BankCodes.PERMATA,
            customer_credit_limit=statement.customer_credit_limit,
            is_shown=True,
            is_primary=True,
            virtual_account=virtual_account,
            sequence=1
        )

    send_sms_bukalapak_notify_va_created.delay(statement_id)

    return JsonResponse({
        'status': 'success',
        'message': 'Va generate and kirim sms berhasil'
    })

########################################## AJAX STATEMENT EVENT ACTIONS #########################################
@csrf_protect
def ajax_add_statement_event(request):
    if request.method != 'POST':
        return HttpResponseNotAllowed(["POST"])

    data = request.POST.dict()
    statement = Statement.objects.get_or_none(pk=int(data['statement']))

    if not statement:
        return HttpResponseBadRequest("statement not found")

    statement_event_service = StatementEventServices()
    agent = request.user
    result = False

    if data['statement_event'] == StatementEventConst.WAIVE_LATE_FEE:
        result = statement_event_service.process_waive_late_fee(statement, data, agent)

    if not result:
        return HttpResponseBadRequest('Please check statement data again!')
    else:
        return JsonResponse({
            'status': 'success',
            'message': 'success create new statement event'
        })
########################################## END AJAX STATEMENT EVENT ACTIONS #########################################
