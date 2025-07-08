from builtins import str
import logging

from django.views.decorators.csrf import csrf_protect
from django.http.response import (HttpResponseNotAllowed,
                                  JsonResponse,
                                  HttpResponse,
                                  HttpResponseNotFound,
                                  HttpResponseBadRequest)
from django.shortcuts import render
from django.db import transaction
from object import julo_login_required

from juloserver.followthemoney.models import (
    LenderCurrent,
    LenderBalanceCurrent,
    LenderTransaction,
    LenderTransactionType
)
from juloserver.followthemoney.constants import LenderTransactionTypeConst, SnapshotType
from juloserver.followthemoney.tasks import calculate_available_balance
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.julo.exceptions import JuloException

logger = logging.getLogger(__name__)

@julo_login_required
def form_view(request):
    is_bo_finance_role = request.user.groups.filter(name='bo_finance').last()
    if not is_bo_finance_role:
        return render(request, 'error/user_role_forbidden_to_access_page.html')

    template_name = 'object/julo_tool/form.html'
    lenders = LenderCurrent.objects.all().values('id', 'lender_name')

    return render(
        request,
        template_name,
        {
            'lenders': lenders
        }
    )

@csrf_protect
def ajax_form_topup_view(request):
    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])

    data = request.POST.dict()
    lender_id = data['lender']
    amount = data['amount']

    lender = LenderCurrent.objects.get_or_none(pk=lender_id)
    if lender is None:
        return JsonResponse({
            'status': 'failed',
            'error_message': 'Lender not exist',
        })

    try:
        with transaction.atomic():
            lender_balance = LenderBalanceCurrent.objects.select_for_update()\
                                                 .filter(lender_id=lender_id)\
                                                 .last()
            if lender_balance is None:
                return JsonResponse({
                    'status': 'failed',
                    'error_message': 'Lender balance not exist',
                })

            lender_transaction_type = LenderTransactionType.objects\
                .get_or_none(transaction_type=LenderTransactionTypeConst.DEPOSIT)

            if lender_transaction_type is None:
                return JsonResponse({
                    'status': 'failed',
                    'error_message': 'Lender transaction type not exist',
                })

            LenderTransaction.objects.create(
                lender=lender,
                lender_balance_current=lender_balance,
                transaction_type=lender_transaction_type,
                transaction_amount=amount
            )

            calculate_available_balance.delay(lender_balance.id, SnapshotType.TRANSACTION)
    except JuloException as error:
        sentry_client = get_julo_sentry_client()
        sentry_client.capture_exceptions()

        return JsonResponse({
            'status': 'failed',
            'error_message': str(error)
        })

    return JsonResponse({
        'status': 'success'
    })
