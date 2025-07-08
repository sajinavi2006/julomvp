from builtins import str
import json

from django.core.paginator import Paginator, EmptyPage
from django.http import HttpResponseNotAllowed
from django.http import HttpResponse
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_protect

# set decorator for login required
from object import julo_login_required, julo_login_required_exclude

from juloserver.julo.models import Application
from juloserver.julo.models import Note
from juloserver.julo.models import Skiptrace
from juloserver.line_of_credit.models import LineOfCreditStatement
from juloserver.line_of_credit.services import LineOfCreditService
from juloserver.line_of_credit.services import LineOfCreditStatementService
from juloserver.line_of_credit.services import LocCollectionService
from juloserver.line_of_credit.services import LineOfCreditNoteService

from .utils import custom_serializer
# Create your views here.


@julo_login_required
@julo_login_required_exclude(['bo_credit_analyst'])
def loc_collection_list(request, bucket):
    # check if there is statuslookup which matches the statuslookup (if not then display 404)
    template_name = 'object/loc_collection/list.html'
    # get parameters url
    search_q = request.GET.get('search_q', '')
    status_app = request.GET.get('status_app', '')
    # init variabel
    list_show_filter_agent = ['T-1', 'T0', 'T+1 to T+30', 'T > 30', 'all']
    bucket_key_map = {
        'Tmin1': 'T-1',
        'T0': 'T0',
        'T1to30': 'T+1 to T+30',
        'Tplus30': 'T > 30',
        'all': 'All'
    }

    if bucket:
        title_status = bucket_key_map[bucket]
    else:
        title_status = 'All'

    return render(
        request,
        template_name,
        {
            'bucket': bucket,
            'status_title': title_status,
            'status_app': status_app,
            'search_q': search_q,
            'list_show_filter_agent': list_show_filter_agent
        }
    )


@csrf_protect
def ajax_loc_collection_list(request):
    if request.method != 'GET':
        return HttpResponseNotAllowed(["GET"])

    bucket = request.GET.get('bucket')
    max_per_page = int(request.GET.get('max_per_page'))

    qs = LocCollectionService().get_loc_coll_list_by_bucket(bucket)

    try:
        page = int(request.GET.get('page'))
    except:
        page = 1

    paginator = Paginator(qs, max_per_page)

    try:
        loc_collections = paginator.page(page)
    except(EmptyPage):
        return HttpResponse(
            json.dumps({
                "status": "failed",
                "message": "invalid page"
            }),
            content_type="application/json"
        )

    return JsonResponse({
        'status': 'success',
        'data': list(loc_collections),
        'count_page': paginator.num_pages,
        'current_page': page,
    }, safe=False)


@julo_login_required
@julo_login_required_exclude(['bo_credit_analyst'])
def loc_collection_detail(request, loc_id):
    template_name = 'object/loc_collection/detail.html'

    loc = LineOfCreditService().get_by_id(int(loc_id))
    application = loc.application_set.all().last()
    customer = application.customer
    skiptrace_list = Skiptrace.objects.filter(customer=customer).order_by('id')

    return render(
        request,
        template_name,
        {
            'loc': loc,
            'application': application,
            'customer': customer,
            'skiptrace_list': skiptrace_list,
        })


@csrf_protect
def get_last_statement(request):
    if request.method != 'GET':
        return HttpResponseNotAllowed(["GET"])

    loc_id = int(request.GET.get('loc_id'))
    last_statement = LineOfCreditStatementService().get_last_statement(loc_id)
    last_statement_data = {
        'id': last_statement.id,
        'cdate': last_statement.cdate,
        'last_billing_amount': last_statement.last_billing_amount,
        'last_minimum_payment': last_statement.last_minimum_payment,
        'last_payment_due_date': last_statement.last_payment_due_date,
        'payment_amount': last_statement.payment_amount,
        'late_fee_amount': last_statement.late_fee_amount,
        'interest_amount': last_statement.interest_amount,
        'purchase_amount': last_statement.purchase_amount,
        'billing_amount': last_statement.billing_amount,
        'minimum_payment': last_statement.minimum_payment,
        'payment_due_date': last_statement.payment_due_date,
        'statement_code': last_statement.statement_code
    }
    return JsonResponse({
        'status': 'success',
        'data': last_statement_data,
    }, safe=False)


@csrf_protect
def get_statement_summaries(request):
    if request.method != 'GET':
        return HttpResponseNotAllowed(["GET"])

    loc_id = int(request.GET.get('loc_id'))
    statement_summaries = LocCollectionService().get_statement_summaries(loc_id)
    data = json.dumps(list(statement_summaries), default=custom_serializer)
    return JsonResponse({
        'status': 'success',
        'data': data
    }, safe=False)


@csrf_protect
def get_va_list(request):
    if request.method != 'GET':
        return HttpResponseNotAllowed(["GET"])

    loc_id = int(request.GET.get('loc_id'))
    va_list = LineOfCreditService().get_virtual_accounts(loc_id)
    data = json.dumps(list(va_list), default=custom_serializer)
    return JsonResponse({
        'status': 'success',
        'data': data
    }, safe=False)


@csrf_protect
def get_transaction_list(request):
    if request.method != 'GET':
        return HttpResponseNotAllowed(["GET"])

    statement_id = int(request.GET.get('statement_id'))
    statement_trans = LineOfCreditStatementService().get_statement_by_id(statement_id)
    data = json.dumps(statement_trans, default=custom_serializer)
    return JsonResponse({
        'status': 'success',
        'data': data
    }, safe=False)


@csrf_protect
def change_status(request):
    if request.method != 'GET':
        return HttpResponseNotAllowed(["GET"])

    loc_id = int(request.GET.get('loc_id'))
    status = request.GET.get('status')
    freeze_reason = request.GET.get('freeze_reason')

    try:
        LocCollectionService().change_loc_status(loc_id, status, freeze_reason)
    except Exception as e:
        return JsonResponse({
            'status': 'failed',
            'message': str(e)
        }, safe=False)

    return JsonResponse({
        'status': 'success',
        'message': 'update status success'
    }, safe=False)


@csrf_protect
def add_notes(request):
    if request.method != 'GET':
        return HttpResponseNotAllowed(["GET"])

    loc_id = int(request.GET.get('loc_id'))
    statement_id = request.GET.get('statement_id')
    note_text = request.GET.get('note_text')

    loc = LineOfCreditService().get_by_id(loc_id)
    loc_statement = None
    if statement_id:
        loc_statement = LineOfCreditStatement.objects.get_or_none(pk=int(statement_id))

    try:
        LineOfCreditNoteService().create(note_text, loc, loc_statement)

    except Exception as e:
        return JsonResponse({
            'status': 'failed',
            'message': str(e)
        }, safe=False)

    return JsonResponse({
        'status': 'success',
        'message': 'update status success'
    }, safe=False)


@csrf_protect
def get_loc_notes(request):
    if request.method != 'GET':
        return HttpResponseNotAllowed(['GET'])

    loc_id = int(request.GET.get('loc_id'))
    loc_note_list = LineOfCreditNoteService().get_list_by_loc_id(loc_id)

    return JsonResponse({
        'status': 'success',
        'data': list(loc_note_list)
    }, safe=False)
