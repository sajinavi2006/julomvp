from builtins import str
from builtins import range
import logging
import random
import string
import os
import tempfile

from datetime import datetime, timedelta, date

from dateutil.relativedelta import relativedelta
from django.template.loader import render_to_string

from juloserver.api_token.authentication import ExpiryTokenAuthentication
from rest_framework import authentication
from rest_framework.views import APIView
from rest_framework import exceptions
from django.contrib.auth.models import User
from django.db import transaction
from django.db.models import F, Sum
from django.utils import timezone
from django.core.files.uploadedfile import InMemoryUploadedFile
from juloserver.paylater.constants import StatementEventConst
from juloserver.apiv2.tasks import generate_address_from_geolocation_async
from juloserver.apiv2.services import get_latest_app_version
from juloserver.julo.utils import redirect_post_to_anaserver
from juloserver.julo.models import (Customer,
                                    AddressGeolocation,
                                    StatusLookup,
                                    Partner,
                                    Application,
                                    Workflow
                                    )
from juloserver.julo.statuses import (LoanStatusCodes,
                                      PaymentStatusCodes,
                                      ApplicationStatusCodes,
                                      JuloOneCodes)
from juloserver.julo.services import process_application_status_change, update_customer_data
from juloserver.julo.services2.customer import CustomerFieldChangeRecorded
from juloserver.paylater.utils import get_late_fee_rules

from .constants import (LineTransactionType,
                        PaylaterConst)
from .models import (Invoice,
                     InvoiceDetail,
                     Statement,
                     StatementEvent,
                     TransactionOne,
                     CustomerCreditLimit,
                     TransactionPaymentDetail,
                     BukalapakCustomerData,
                     AccountCreditLimit)
from .serializers import (ActivationSerializer,
                          InvoiceSerializer,
                          InvoiceDetailSerializer,
                          ValidateSerializer,
                          RepaymentSerializer,
                          RefundSerializer,
                          StatementSerializer,
                          TransactionHistory,
                          TransactionSerializer,
                          InquirySerializer,
                          ScrapSerializer,
                          UpdateInvoiceDetailSerializer,
                          )
from .utils import (success_response,
                    server_error_response,
                    generate_customer_xid,
                    general_error_response,
                    html_response,
                    )
from .services import (generate_loan_one_and_payment,
                       update_loan_one_and_payment,
                       generate_accountcredit_history,
                       generate_new_statement,
                       activate_paylater,
                       process_rules_delete_latefee
                       )

from rest_framework.renderers import TemplateHTMLRenderer, StaticHTMLRenderer
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.standardized_api_response.mixin import StandardizedExceptionHandlerMixin

# Create your views here.
logger = logging.getLogger(__name__)
julo_sentry_client = get_julo_sentry_client()


class CustomAuthentication(ExpiryTokenAuthentication):
    def authenticate(self, request):
        if super(CustomAuthentication, self).authenticate(request):
            user, auth = super(CustomAuthentication, self).authenticate(request)
            if not hasattr(user, 'partner'):
                raise exceptions.AuthenticationFailed('Forbidden request, invalid user')
            else:
                if user.partner.name != PaylaterConst.PARTNER_NAME:
                    raise exceptions.AuthenticationFailed('Forbidden request, invalid partner')
            return (user, auth)
        else:
            raise exceptions.AuthenticationFailed('Forbidden request, invalid partner')


class PaylaterAPIView(StandardizedExceptionHandlerMixin, APIView):
    authentication_classes = (CustomAuthentication,)

    def validate_data(self, serializer_class, data):
        serializer = serializer_class(data=data)
        serializer.is_valid(raise_exception=True)
        return serializer.validated_data


class ActivationView(PaylaterAPIView):
    http_method_names = ['post']
    serializer_class = ActivationSerializer

    def post(self, request):
        data = self.validate_data(self.serializer_class, request.data)
        new_customer = True
        email = data['email'].strip().lower()

        customer_exist = Customer.objects.get_or_none(nik=data['ktp'])
        # check for old user which has no nik on customer table
        if not customer_exist:
            user_exist = User.objects.filter(username=data['ktp']).last()
            if user_exist:
                customer_exist = user_exist.customer
            else:
                customer_exist = Customer.objects.get_or_none(email__iexact=email)

        if customer_exist:
            if hasattr(customer_exist, 'customercreditlimit'):
                return general_error_response(
                    "customer has activated before", {"customer_xid": customer_exist.customer_xid} )
            new_customer = False
            customer = customer_exist
            user = customer.user
            customer_dict = dict(customer.__dict__)
        else:
            password = ''.join(random.choice(
                string.ascii_lowercase + string.digits) for _ in range(12))
            user = User(username=data['ktp'])
            user.set_password(password)

            customer = Customer(
                email=email,
                nik=data['ktp'],
                phone=data['phone_number'],
                fullname=data['fullname'],
                dob=data['dob'],
                gender=data['gender'],
            )
        try:
            with transaction.atomic():
                user.save()
                customer.user = user
                customer.save()
                customer.customer_xid = generate_customer_xid(customer.id)
                customer.save()

                activated_customer = hasattr(customer, 'line')
                if not activated_customer:
                    customer_credit_limit = CustomerCreditLimit.objects.create(
                        customer=customer,
                        customer_credit_status=StatusLookup.objects.get(pk=LoanStatusCodes.INACTIVE)
                    )
                    workflow = Workflow.objects.get_or_none(name='SubmittingFormWorkflow')
                    application = Application.objects.create(
                        partner=Partner.objects.get(name=PaylaterConst.PARTNER_NAME), #populate partner_id
                        customer=customer, ktp=data['ktp'], fullname=customer.fullname,
                        app_version=get_latest_app_version(), mobile_phone_1=data['phone_number'],
                        email=email, customer_credit_limit=customer_credit_limit,
                        dob=data['dob'], gender=data['gender'], birth_place=data['birthplace'],
                        workflow=workflow
                    )
                    update_customer_data(application)
                    account_credit = AccountCreditLimit.objects.create(
                        customer_credit_limit=customer_credit_limit,
                        partner=Partner.objects.get(name=PaylaterConst.PARTNER_NAME),
                        account_credit_status=StatusLookup.objects.get(pk=JuloOneCodes.INACTIVE),
                        agreement_accepted_ts=timezone.localtime(timezone.now()),
                        callback_url=data['callback_url']
                    )

                    BukalapakCustomerData.objects.create(
                        application=application,
                        customer=customer,
                        email=email,
                        nik=data['ktp'],
                        confirmed_phone=data['phone_number'],
                        fullname=data['fullname'],
                        birthday=data['dob'],
                        gender=data['gender'],
                        account_opening_date=data['account_opening_date'],
                        birthplace=data['birthplace'],
                        seller_flag=data['seller_flag'],
                        identity_type=data['identity_type'],
                        job=data['job'],
                        marital_status=data['marital_status'],
                        reference_date=data['reference_date'])

                    if new_customer and data.get('latitude') and data.get('longitude'):
                        # create AddressGeolocation
                        address_geolocation = AddressGeolocation.objects.create(
                            application=application,
                            customer=customer,
                            latitude=data['latitude'],
                            longitude=data['longitude'])

                        generate_address_from_geolocation_async.delay(address_geolocation.id)

                    if not new_customer:
                        with CustomerFieldChangeRecorded(customer, application.id, request.user, customer_dict):
                            customer.update_safely(
                                email=email,
                                phone=data['phone_number'],
                                dob=data['dob'],
                                gender=data['gender'],
                                fullname=data['fullname']
                            )
                            #for old user
                            if not customer.nik:
                                customer.update_safely(nik=data['ktp'])

                    # generate account credit history
                    generate_accountcredit_history(account_credit, JuloOneCodes.INACTIVE, "created_by_API")
                    # process_application_status_change(application.id, ApplicationStatusCodes.FORM_CREATED,
                    #                                   change_reason='partner_triggered')

        except Exception as e:
            logger.error({
                'action_view': 'ActivationView',
                'data': data,
                'errors': str(e)
            })
            julo_sentry_client.captureException()
            return server_error_response()
        customer.refresh_from_db()
        res_data = {
            'customer_xid': customer.customer_xid,
            'ktp': customer.nik,
            'phone_number': customer.phone,
            'fullname': customer.fullname,
            'email': customer.email,
            'dob': customer.dob,
            'gender': customer.gender
        }

        return success_response(res_data)


class ValidateView(PaylaterAPIView):
    http_method_names = ['post']
    serializer_class = ValidateSerializer

    def post(self, request):
        data = self.validate_data(self.serializer_class, request.data)
        customer = Customer.objects.get(customer_xid=data['customer_xid'])

        if not hasattr(customer, 'customercreditlimit'):
            return general_error_response(
                "customer_xid %s not activated yet" % data['customer_xid'])
        line = customer.customercreditlimit

        if hasattr(line, 'accountcreditlimit'):
            return general_error_response(
                "customer_xid %s not activated yet" % data['customer_xid'])

        if line.credit_score.score == 'C':
            return general_error_response(
                "customer_xid %s has no good credit score" % data['customer_xid'])

        subscription_exist = line.accountcreditlimit_set.filter(
            partner__name=PaylaterConst.PARTNER_NAME).last()

        if subscription_exist.account_credit_status.status_code != JuloOneCodes.INACTIVE:
            res_data = {
                'customer_xid': customer.customer_xid,
                'limit': subscription_exist.available_credit_limit,
                'type': data.get('type')
            }
            return general_error_response("customer has already validated before", res_data)

        if int(data['limit']) > line.customer_credit_limit:
            return general_error_response("limit not valid", {"max_limit": line.customer_credit_limit})

        # generate account credit history
        generate_accountcredit_history(subscription_exist, JuloOneCodes.ACTIVE, "updated_by_API")
        subscription_exist.account_credit_limit=data['limit']
        subscription_exist.available_credit_limit=data['limit']
        subscription_exist.account_credit_status=StatusLookup.objects.get(pk=JuloOneCodes.ACTIVE)
        subscription_exist.account_credit_active_date=timezone.now()
        subscription_exist.save(update_fields=['account_credit_limit',
                                               'available_credit_limit',
                                               'account_credit_status',
                                               'account_credit_active_date'])
        subscription_exist.refresh_from_db()
        res_data = {
            'customer_xid': customer.customer_xid,
            'limit': subscription_exist.available_credit_limit,
            'type': data.get('type')
        }
        return success_response(res_data)


class ScrapView(PaylaterAPIView):
    http_method_names = ['post']
    serializer_class = ScrapSerializer

    def post(self, request):
        data = self.validate_data(self.serializer_class, request.data)
        if request.FILES['upload'].content_type not in ('application/zip'):
            return general_error_response(
                "validation failed", data={'upload': "file type must be .zip"})

        customer = Customer.objects.get_or_none(customer_xid=data['customer_xid'])
        if not hasattr(customer, 'customercreditlimit'):
            return general_error_response("customer has not activated")
        line = customer.customercreditlimit
        if line.credit_score:
            return general_error_response(
                "customer_xid %s data has been processed before" % data['customer_xid'])
        line_sub = line.accountcreditlimit_set.filter(
            partner__name=PaylaterConst.PARTNER_NAME).last()
        if line_sub.scrap_data_uploaded:
                return general_error_response(
                    "data for customer_xid %s still in process" % data['customer_xid'])

        app = line.application_set.last()
        req_data = {'application_id': app.id}
        files = {'upload': request.data['upload']}
        redirect_post_to_anaserver(
            '/api/amp/v1/paylater-scraped-data/', data=req_data, files=files)

        line_sub.scrap_data_uploaded = True
        line_sub.save(update_fields=['scrap_data_uploaded'])

        res_data = {'customer_xid': data['customer_xid']}
        return success_response(res_data)


class DummyView(APIView):
    authentication_classes = (authentication.BasicAuthentication,)

    def post(self, request):
        logger.info({
            'action_view': 'Dummy_callback',
            'data': request.data,
        })
        res_data = {"dummy_data":True}
        return success_response(res_data)


class TransactionsView(PaylaterAPIView):
    http_method_names = ['get', 'post']
    serializer_class = InvoiceSerializer

    def get(self, request):
        return success_response({"yes": "TransactionsView"})

    def post(self, request):
        data = request.data
        if 'transactions' not in data:
            return general_error_response('transactions is required')
        trans_datas = data.pop('transactions')
        if not isinstance(trans_datas, list):
            return general_error_response('transactions should be array')
        if len(trans_datas) == 0:
            return general_error_response('transactions could not be empty!')

        # validate invoice data
        invoice_data = self.validate_data(self.serializer_class, data)
        customer = Customer.objects.get(customer_xid=invoice_data.get('customer_xid'))
        if not hasattr(customer, 'customercreditlimit'):
            return general_error_response("customer has not activated")

        status_active = StatusLookup.objects.get(pk=LoanStatusCodes.CURRENT)
        account_status_active = StatusLookup.objects.get(pk=JuloOneCodes.ACTIVE)
        credit_limit = customer.customercreditlimit
        if credit_limit.customer_credit_status != status_active:
            return general_error_response("customer has not activated")

        account_credit_limit = credit_limit.accountcreditlimit_set.filter(
            partner__name=PaylaterConst.PARTNER_NAME,
            account_credit_status=account_status_active).last()
        invoice_amount = invoice_data.get('invoice_amount')
        invoice_total_amount = invoice_data.get('invoice_amount')

        if not account_credit_limit:
            return general_error_response("customer has not activated")

        # check duplicate invoice number
        old_invoices = Invoice.objects.filter(invoice_number=invoice_data.get('invoice_number'))
        if old_invoices:
            return general_error_response("invoice number has exist")

        # comment it temporary
        # last_transaction_date = date(2019, 7, 28)
        #
        # if invoice_data['invoice_date'].date()>= last_transaction_date:
        #     if invoice_amount < 100000:
        #         return general_error_response("minimum transaction is 100000")


        # line_sattement checking
        last_debt = 0
        last_statement = account_credit_limit.statement_set.exclude(
            statement_status_id__gte=PaymentStatusCodes.PAID_ON_TIME).order_by('id').last()
        if last_statement:
            if last_statement.statement_due_date <= invoice_data['invoice_date'].date():
                return general_error_response("paylater not available")

            last_debt = account_credit_limit.used_credit_limit

        available_limit = account_credit_limit.account_credit_limit - last_debt
        if available_limit < invoice_total_amount:
            return general_error_response("customer has not enough limit")

        try:
            with transaction.atomic():
                # create invoice
                invoice_data['customer_credit_limit'] = credit_limit
                invoice_data['account_credit_limit'] = account_credit_limit
                invoice_data['invoice_status'] = "Paid"
                invoice = Invoice(**invoice_data)
                invoice.save()

                # create invoice details
                inv_details = []
                for detail in trans_datas:
                    inv_detail_data = self.validate_data(InvoiceDetailSerializer, detail)
                    # check duplicate partner transaction id
                    old_invoice_detail = InvoiceDetail.objects.filter(
                        partner_transaction_id=inv_detail_data.get('partner_transaction_id'))
                    if old_invoice_detail:
                        return general_error_response("partner transaction id has exist")

                    inv_detail_data['invoice'] = invoice
                    inv_details.append(InvoiceDetail(**inv_detail_data))
                invoice_details = InvoiceDetail.objects.bulk_create(inv_details)

                # create new statement if theres no active statement
                total_amount = invoice.invoice_amount
                disbursement_amount = invoice.invoice_amount - invoice.transaction_fee_amount
                if not last_statement:
                    last_statement = generate_new_statement(invoice)

                # create transaction
                transaction_obj = TransactionOne.objects.create(
                    customer_credit_limit=credit_limit,
                    account_credit_limit=account_credit_limit,
                    invoice=invoice,
                    statement=last_statement,
                    transaction_type='debit',
                    transaction_date=invoice.invoice_date,
                    transaction_amount=total_amount,
                    disbursement_amount=disbursement_amount,
                    transaction_description=LineTransactionType.TYPE_INVOICE['name'],
                    transaction_status='paid'
                )
                # execute signal after save transaction

            # prepare response data
            detail_ids = [obj.partner_transaction_id for obj in invoice_details]
            invoice_data.pop('customer_credit_limit')
            invoice_data.pop('account_credit_limit')
            # change due_date response with julo due_date
            invoice_data['invoice_due_date'] = last_statement.statement_due_date
            response_data = invoice_data
            response_data['transactions'] = [{'transaction_id': id} for id in detail_ids]
            return success_response(response_data)
        except Exception as e:
            logger.error({
                'action_view': 'TransactionsView',
                'data': data,
                'errors': str(e)
            })
            julo_sentry_client.captureException()
            return server_error_response()


class RefundView(PaylaterAPIView):
    http_method_names = ['get', 'post']
    serializer_class = RefundSerializer

    def get(self, request):
        data = request.query_params
        invoice_number = data.get('invoice_number')

        invoice = Invoice.objects.filter(invoice_number=invoice_number).last()
        if not invoice:
            return general_error_response('invoice %s not found' % (invoice_number))

        refund_transactions = invoice.transactionone_set.filter(
            transaction_description='refund').annotate(
                transaction_id=F('invoice_detail__partner_transaction_id'),
                refund_amount=F('transaction_amount')
            ).values('transaction_id', 'refund_amount')

        res_data = dict(
            invoice_number=invoice_number,
            refunds=refund_transactions
        )
        return success_response(res_data)

    def post(self, request):
        data = self.validate_data(self.serializer_class, request.data)
        invoice_number = data.get('invoice_number')
        invoice = Invoice.objects.filter(invoice_number=invoice_number).last()
        if not invoice:
            return general_error_response('invoice %s not found' % (invoice_number))

        transaction_id = data.get('partner_transaction_id')
        invoice_detail = invoice.transactions.filter(
            partner_transaction_id=transaction_id).last()
        if not invoice_detail:
            return general_error_response('transaction %s not found' % (transaction_id))

        invoice_trans = TransactionOne.objects.prefetch_related(
                        'loanone', 'loanone__paymentschedule_set',
                        'statement').filter(
                            invoice=invoice,
                            transaction_description='invoice').last()

        trans_type = LineTransactionType.TYPE_REFUND

        last_statement = invoice_trans.statement
        refund_amount = data.get('refund_amount')
        last_refund_amount = last_statement.total_refund_by_invoces(invoice)

        total_invoice_amount = invoice.invoice_amount - last_refund_amount
        if int(refund_amount) > int(total_invoice_amount):
            return general_error_response("refund amount can't be more than invoice amount")

        # refund after statement paid off
        if last_statement.statement_status.status_code in PaymentStatusCodes.paylater_paid_status_codes():
            trans_type = LineTransactionType.TYPE_REFUND_PAID

        today = timezone.now().date()
        try:
            with transaction.atomic():
                account_credit_limit = invoice.account_credit_limit
                refund_transaction = TransactionOne.objects.create(
                    customer_credit_limit=invoice.customer_credit_limit,
                    account_credit_limit=account_credit_limit,
                    invoice=invoice,
                    invoice_detail=invoice_detail,
                    statement=last_statement,
                    transaction_type=trans_type.get('type'),
                    transaction_date=today,
                    transaction_amount=refund_amount,
                    transaction_description=trans_type.get('name'),
                    transaction_status='paid',
                )
                # execute signal after save transaction

                # update loan_one and payment
                loan_one = invoice_trans.loanone
                loan_one.refund_amount = refund_amount + last_refund_amount
                loan_one.save(update_fields=['refund_amount'])

                refund_data = dict(
                    transaction_id=data.get('partner_transaction_id'),
                    refund_amount=data.get('refund_amount')
                )
                res_data = dict(
                    invoice_number=invoice_number,
                    refunds=[refund_data]
                )
                return success_response(res_data)
        except Exception as e:
            logger.error({
                'action_view': 'RefundView',
                'data': data,
                'errors': str(e)
            })
            julo_sentry_client.captureException()
            return server_error_response()

        return success_response({})


class TransactionDetailView(PaylaterAPIView):
    http_method_names = ['get', 'post']
    serializer_class = UpdateInvoiceDetailSerializer

    def get(self, request):
        data = request.query_params
        invoice_number = data.get('invoice_number')
        transaction_id = data.get('transaction_id')
        if not invoice_number or not transaction_id:
            return general_error_response('invoice_number and transaction_id are required')

        invoice = Invoice.objects.filter(invoice_number=invoice_number).last()
        if not invoice:
            return general_error_response('invoice %s not found' % (invoice_number))

        invoice_details = invoice.transactions.filter(partner_transaction_id=transaction_id)\
                                              .annotate(transaction_id=F('partner_transaction_id'),
                                                        status=F('partner_transaction_status'),
                                                        items=F('details'))\
                                              .values('transaction_id',
                                                      'status',
                                                      'shipping_address',
                                                      'items')
        if len(invoice_details) == 0:
            return general_error_response('transaction %s not found' % (transaction_id))

        res_data = dict(invoice_number=invoice_number,
                        transactions=invoice_details)
        return success_response(res_data)

    def post(self, request):
        data = self.validate_data(self.serializer_class, request.data)
        invoice_number = data.get('invoice_number')
        invoice = Invoice.objects.filter(invoice_number=invoice_number).last()
        if not invoice:
            return general_error_response('invoice %s not found' % (invoice_number))
        partner_transaction_id = data.get('partner_transaction_id')
        invoice_detail = InvoiceDetail.objects.filter(
            invoice_id=invoice.id, partner_transaction_id=partner_transaction_id).last()
        if not invoice_detail:
            return general_error_response('transaction %s not found' % (partner_transaction_id))
        partner_transaction_status = data.get('partner_transaction_status')
        invoice_detail.partner_transaction_status = partner_transaction_status
        invoice_detail.save(update_fields=['partner_transaction_status'])

        res_inv_detail = dict(transaction_id=partner_transaction_id,
                              status=partner_transaction_status)
        res_data = dict(
            invoice_number=invoice_number,
            transactions=[res_inv_detail]
        )
        return success_response(res_data)


class CreditLimitView(PaylaterAPIView):
    http_method_names = ['post']
    serializer_class = InquirySerializer

    def post(self, request):
        data = request.data
        # validate request data
        inquiry_data = self.validate_data(self.serializer_class, data)

        customer = Customer.objects.get(customer_xid=inquiry_data.get('customer_xid'))
        if not hasattr(customer, 'customercreditlimit'):
            return general_error_response("customer has not activated")

        status_active = StatusLookup.objects.get(pk=LoanStatusCodes.CURRENT)
        account_status_active = StatusLookup.objects.get(pk=JuloOneCodes.ACTIVE)
        credit_limit = customer.customercreditlimit
        if credit_limit.customer_credit_status != status_active:
            return general_error_response("customer has not activated")

        try:
            account_credit_limit = credit_limit.accountcreditlimit_set.filter(
                partner__name=PaylaterConst.PARTNER_NAME).last()
            if account_credit_limit.account_credit_status != account_status_active:
                available_limit = 0
            else:
                available_limit = account_credit_limit.account_credit_limit

            # line_statement checking
            today = timezone.now().date()
            last_statement = credit_limit.statement_set.exclude(
                statement_status_id__gte=PaymentStatusCodes.PAID_ON_TIME).order_by('id').last()
            if last_statement:
                if last_statement.statement_due_date < today:
                    available_limit = 0
                else:
                    available_limit = account_credit_limit.account_credit_limit - account_credit_limit.used_credit_limit

            response_data = dict(
                customer_xid=customer.customer_xid,
                limit=account_credit_limit.account_credit_limit,
                available_limit=available_limit,
                account_credit_status_code=account_credit_limit.account_credit_status.status_code,
                statement_status_code=None
            )

            return success_response(response_data)
        except Exception as e:
            logger.error({
                'action_view': 'CreditLimitView',
                'data': data,
                'errors': str(e)
            })
            julo_sentry_client.captureException()
            return server_error_response()


class RepaymentView(PaylaterAPIView):
    http_method_names = ['post']
    serializer_class = RepaymentSerializer

    def post(self, request):
        data = request.data
        # validate request data
        repayment_data = self.validate_data(self.serializer_class, data)

        customer = Customer.objects.get(customer_xid=repayment_data.get('customer_xid'))
        if not hasattr(customer, 'customercreditlimit'):
            return general_error_response("customer has not activated")

        status_active = StatusLookup.objects.get(pk=LoanStatusCodes.CURRENT)
        account_status_exclude = StatusLookup.objects.get(pk=JuloOneCodes.INACTIVE)
        credit_limit = customer.customercreditlimit
        if credit_limit.customer_credit_status != status_active:
            return general_error_response("customer has not activated")

        account_credit_limit = credit_limit.accountcreditlimit_set.filter(
            partner__name=PaylaterConst.PARTNER_NAME,
            ).exclude(account_credit_status=account_status_exclude).last()
        if not account_credit_limit:
            return general_error_response("customer has not activated")

        statement = Statement.objects.get_or_none(
            id=repayment_data.get('statement_id'),
            customer_credit_limit=credit_limit,
            account_credit_limit=account_credit_limit
        )

        if not statement:
            return general_error_response("statement not found")

        if statement.statement_status.status_code in PaymentStatusCodes.paylater_paid_status_codes():
            return general_error_response("statement has paid off")

        first_transaction = statement.transactionone_set.order_by('cdate').first()
        paid_date = repayment_data.get('paid_date')
        paid_datetime = datetime(paid_date.year, paid_date.month, paid_date.day) + timedelta(days=1)
        if paid_datetime < first_transaction.transaction_date.replace(tzinfo=None):
            return general_error_response("Paid date can't be less than first transaction date")

        # check invoice_creation_time
        invoice_creation_date = repayment_data.get('invoice_creation_time').replace(tzinfo=None).date()
        process_rules_delete_latefee(statement, invoice_creation_date)
        statement.refresh_from_db()

        if repayment_data.get('amount') != statement.statement_total_due_amount:
            return general_error_response("amount is not valid, your due_amount is {}".format(
                statement.statement_total_due_amount
            ))
        try:
            with transaction.atomic():
                # create transaction
                transaction_obj = TransactionOne.objects.create(
                    customer_credit_limit=credit_limit,
                    account_credit_limit=account_credit_limit,
                    statement=statement,
                    transaction_type='credit',
                    transaction_date=repayment_data.get('paid_date'),
                    transaction_amount=repayment_data.get('amount'),
                    transaction_description=LineTransactionType.TYPE_PAYMENT['name'],
                    transaction_status='paid')

                # create payment detail
                TransactionPaymentDetail.objects.create(
                    transaction=transaction_obj,
                    payment_method_type=repayment_data.get('method_type'),
                    payment_method_name=repayment_data.get('method_name'),
                    payment_account_number=repayment_data.get('account_number'),
                    payment_amount=repayment_data.get('amount'),
                    payment_date=repayment_data.get('paid_date'),
                    payment_ref=repayment_data.get('payment_ref')
                )
                # execute signal after save transaction

                statement_transaction = TransactionOne.objects.filter(
                    statement=statement).exclude(transaction_description='payment')
                # update date loanone and paymentschedule
                for transaction_obj in statement_transaction:
                    update_loan_one_and_payment(transaction_obj, paid_date)

                response_data = StatementSerializer(statement).data
                response_data['transactions'] = TransactionSerializer(statement_transaction, many=True).data
                return success_response(response_data)
        except Exception as e:
            logger.error({
                'action_view': 'RepaymentView',
                'data': data,
                'errors': str(e)
            })
            julo_sentry_client.captureException()
            return server_error_response()


class StatementsView(PaylaterAPIView):
    http_method_names = ['get']
    serializer_class = TransactionHistory

    def get(self, request):
        data = request.data
        statement_data = self.validate_data(self.serializer_class, data)
        customer = Customer.objects.get(customer_xid=statement_data.get('customer_xid'))
        if not hasattr(customer, 'customercreditlimit'):
            return general_error_response("customer has not activated")

        status_active = StatusLookup.objects.get(pk=LoanStatusCodes.CURRENT)
        credit_limit = customer.customercreditlimit
        if credit_limit.customer_credit_status != status_active:
            return general_error_response("customer has not activated")

        account_credit_limit = credit_limit.accountcreditlimit_set.filter(
            partner__name=PaylaterConst.PARTNER_NAME).last()

        try:
            limit = data.get('limit', 10)
            order = data.get('order', 'desc')
            statement_id = data.get('statement_id')
            last_statement_id = data.get('last_statement_id')

            filter_ = dict(
                customer_credit_limit=credit_limit,
                account_credit_limit=account_credit_limit,
            )
            if statement_id:
                filter_['id'] = statement_id

            order_by = '-id'
            if order == "desc":
                if last_statement_id:
                    filter_['id__lt'] = last_statement_id
            elif order == "asc":
                order_by = 'id'
                if last_statement_id:
                    filter_['id__gt'] = last_statement_id

            statements = Statement.objects.filter(**filter_).order_by(order_by)[:limit]
            statement_datas = StatementSerializer(statements, many=True).data

            is_hide_transaction = LineTransactionType.is_hide()
            for statement in statement_datas:
                statement_transaction = TransactionOne.objects.filter(
                    statement=statement['id']).exclude(transaction_description__in=is_hide_transaction)
                statement['transactions'] = TransactionSerializer(statement_transaction, many=True).data

            return success_response(statement_datas)
        except Exception as e:
            logger.error({
                'action_view': 'StatementsView',
                'data': data,
                'errors': str(e)
            })
            julo_sentry_client.captureException()
            return server_error_response()


class ApprovalView(PaylaterAPIView):
    http_method_names = ['get']
    renderer_classes = [StaticHTMLRenderer]
    authentication_classes = []
    permission_classes = []

    def get(self, request, customer_xid):
        customer = Customer.objects.get_or_none(customer_xid=customer_xid)
        if not customer:
            return general_error_response("customer has not found")

        try:
            status_active = StatusLookup.objects.get(pk=LoanStatusCodes.CURRENT)
            credit_limit = customer.customercreditlimit
            if credit_limit.customer_credit_status == status_active:
                return general_error_response("customer has activated")

            activate_paylater(customer)

            data = dict(
                link="https://m.bukalapak.com/payment/payment_channels/webview/paylater?from=dope"
            )
            html = render_to_string('paylater-approval.html', data)

            return html_response(html)

        except Exception as e:
            logger.error({
                'action_view': 'ApprovalView',
                'data': {'customer_xid': customer_xid},
                'errors': str(e)
            })
            julo_sentry_client.captureException()
            return server_error_response()
