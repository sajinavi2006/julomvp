import csv
import json
import random
import string
import time
from builtins import range, str
from collections import OrderedDict

import requests
from dateutil.relativedelta import relativedelta
from django.conf import settings
from django.contrib.auth import authenticate
from django.contrib.auth.models import User
from django.core.exceptions import ObjectDoesNotExist
from django.db import transaction
from oauth2client import client
from rest_framework.generics import RetrieveAPIView
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import AllowAny, IsAdminUser
from rest_framework.response import Response
from rest_framework.status import HTTP_400_BAD_REQUEST
from rest_framework.views import APIView

from juloserver.api_token.models import ExpiryToken as Token
from juloserver.disbursement.constants import DisbursementStatus, XfersDisbursementStep
from juloserver.disbursement.models import Disbursement
from juloserver.disbursement.services import create_disbursement_new_flow_history
from juloserver.followthemoney.models import LenderTransactionMapping
from juloserver.followthemoney.services import (
    update_lender_balance_current_for_disbursement,
)
from juloserver.julo.exceptions import JuloException
from juloserver.julo.statuses import ApplicationStatusCodes
from juloserver.standardized_api_response.utils import (
    general_error_response,
    not_found_response,
    success_response,
)

from ..apiv2.services import get_product_selections
from ..disbursement.clients import get_bca_client
from ..julo import tasks
from ..julo.clients import get_julo_pn_client
from ..julo.models import (
    Application,
    ApplicationHistory,
    CreditScore,
    Customer,
    Loan,
    Payment,
    PaymentEvent,
    ProductLine,
)
from ..julo.services import (
    create_application_checklist,
    process_application_status_change,
)
from ..julo.tasks import (
    send_accept_offer_reminder_am,
    send_accept_offer_reminder_pm,
    send_phone_verification_reminder_am,
    send_phone_verification_reminder_pm,
    send_resubmission_request_reminder_am,
    send_resubmission_request_reminder_pm,
    send_sign_sphp_reminder_am,
    send_sign_sphp_reminder_pm,
    send_submit_document_reminder_am,
    send_submit_document_reminder_pm,
    update_payment_status,
)
from ..julo.utils import generate_hex_sha256, generate_sha1_md5
from ..julo.workflows import WorkflowAction
from ..line_of_credit.tasks import execute_loc_notification
from .serializers import (
    METHOD_CHOICES,
    ApplicationHistorySerializers,
    BugChampionActivateLoanManualDisburseSerializer,
    BugChampionApplicationIdsSerializer,
    BugChampionForceChangeStatusSerializer,
    BugChampionKtpNameSerializer,
    BugChampionLoginSerializer,
    BugChampionPaymentEventSerializer,
    BugChampionPaymentRestructureSerializer,
    BugChampionRescrapeActionSerializer,
    BugChampionUpdateLoanStatusSerializer,
    CustomerSerializers,
    DeviceSerializers,
    ManualDisburseFakeCallBackSerializer,
    PaymentSerializer,
    ProductLineSerializer,
    UnlockSerializer,
)
from .services import (
    bulk_activate_loan_manual_disburse,
    coll_reassign_agent,
    customer_rescrape_action,
    force_change_status,
    payment_restructure,
    process_change_name_ktp,
    process_payment_discount,
    unlocked_app,
    unlocked_payment,
    waive_refinancing,
)
from juloserver.integapiv1.utils import generate_signature_hmac_sha512

class RunUpdatePayment(APIView):
    """
    endpoint to run update_payment_status from celery tasks
    """

    permission_classes = (IsAdminUser,)

    def get(self, request, format=None):
        update_payment_status()
        return Response("updated_payment_status")


class ChangeAppHistoryCdate(APIView):
    """
    endpoint to change application history cdate by application_id get the latest change
    """

    permission_classes = (IsAdminUser,)
    model_class = ApplicationHistory
    serializer_class = ApplicationHistorySerializers

    def put(self, request, format=None):
        application_id = request.data['application_id']
        cdate_key = request.data['cdate_key']
        times = int(request.data['times'])
        application = Application.objects.get_or_none(id=application_id)
        application_history = ApplicationHistory.objects.filter(
            application=application, status_new=application.status
        ).latest('cdate')
        if cdate_key in ('hour', 'Hour', 'h', 'H'):
            changed_cdate = application_history.cdate - relativedelta(hours=times)
        elif cdate_key in ('day', 'Day', 'D', 'd'):
            changed_cdate = application_history.cdate - relativedelta(days=times)

        application_history.cdate = changed_cdate
        application_history.save()

        return Response(
            {'application_history_id': application_history.id, 'cdate': application_history.cdate}
        )


class SubmitDocReminderAm(APIView):
    '''
    endpoint to run send_submit_document_reminder_am from celery tasks
    '''

    permission_classes = (IsAdminUser,)

    def get(self, request, format=None):
        send_submit_document_reminder_am()
        return Response("send_submit_document_reminder_am")


class SubmitDocReminderPm(APIView):
    '''
    endpoint to run send_submit_document_reminder_pm from celery tasks
    '''

    permission_classes = (IsAdminUser,)

    def get(self, request, format=None):
        send_submit_document_reminder_pm()
        return Response("send_submit_document_reminder_pm")


class ResubmitDocReminderAm(APIView):
    '''
    endpoint to run send_resubmission_request_reminder_am from celery tasks
    '''

    permission_classes = (IsAdminUser,)

    def get(self, request, format=None):
        send_resubmission_request_reminder_am()
        return Response("send_resubmission_request_reminder_am")


class ResubmitDocReminderPm(APIView):
    '''
    endpoint to run send_resubmission_request_reminder_pm from celery tasks
    '''

    permission_classes = (IsAdminUser,)

    def get(self, request, format=None):
        send_resubmission_request_reminder_pm()
        return Response("send_resubmission_request_reminder_pm")


class PhoneVerificationReminderAm(APIView):
    '''
    endpoint to run send_phone_verification_reminder_am from celery tasks
    '''

    permission_classes = (IsAdminUser,)

    def get(self, request, format=None):
        send_phone_verification_reminder_am()
        return Response("send_phone_verification_reminder_am")


class PhoneVerificationReminderPm(APIView):
    '''
    endpoint to run send_phone_verification_reminder_pm from celery tasks
    '''

    permission_classes = (IsAdminUser,)

    def get(self, request, format=None):
        send_phone_verification_reminder_pm()
        return Response("send_phone_verification_reminder_pm")


class AcceptOfferReminderAm(APIView):
    '''
    endpoint to run send_accept_offer_reminder_am from celery tasks
    '''

    permission_classes = (IsAdminUser,)

    def get(self, request, format=None):
        send_accept_offer_reminder_am()
        return Response("send_accept_offer_reminder_am")


class AcceptOfferReminderPm(APIView):
    '''
    endpoint to run send_accept_offer_reminder_pm from celery tasks
    '''

    permission_classes = (IsAdminUser,)

    def get(self, request, format=None):
        send_accept_offer_reminder_pm()
        return Response("send_accept_offer_reminder_pm")


class SignSphpReminderAm(APIView):
    '''
    endpoint to run send_sign_sphp_reminder_am from celery tasks
    '''

    permission_classes = (IsAdminUser,)

    def get(self, request, format=None):
        send_sign_sphp_reminder_am()
        return Response("send_sign_sphp_reminder_am")


class SignSphpReminderPm(APIView):
    '''
    endpoint to run send_sign_sphp_reminder_pm from celery tasks
    '''

    permission_classes = (IsAdminUser,)

    def get(self, request, format=None):
        send_sign_sphp_reminder_pm()
        return Response("send_sign_sphp_reminder_pm")


class SendGcm(APIView):
    def get(self, request, format=None):
        gcm_reg_id = self.request.query_params.get('gcm_reg_id', None)

        if not gcm_reg_id:
            return Response("gcm_reg_id is None")

        julo_pn_client = get_julo_pn_client()
        julo_pn_client.trigger_location(gcm_reg_id)

        return Response("gcm send to gcm_reg_id " + gcm_reg_id)


class ScheduledTaskTriggerView(RetrieveAPIView):
    """Internal way to trigger scheduled tasks (very hacky)"""

    def get(self, request, *args, **kwargs):
        scheduled_task_name = kwargs['scheduled_task']
        scheduled_task = getattr(tasks, scheduled_task_name)
        scheduled_task()
        return Response(data={'scheduled_task': scheduled_task_name})


class GmailAuthRedirectionView(RetrieveAPIView):
    def get(self, request, *args, **kwargs):
        """
        When called from the browser, it will redirect to authenticate with
        Google
        """
        flow = client.flow_from_clientsecrets(
            settings.GOOGLE_CLIENT_SECRET,
            scope='',
            redirect_uri=settings.BASE_URL + '/api/qa/v1/google/auth/callback',
        )
        flow.params['access_type'] = 'offline'
        auth_url = flow.step1_get_authorize_url()
        return Response(data={'redirect_url': auth_url})


class GmailAuthCallbackView(RetrieveAPIView):

    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request, *args, **kwargs):
        code = request.query_params.get('code', None)
        application = Application.objects.filter(email__endswith='julofinance.com').last()
        token, created = Token.objects.get_or_create(user=application.customer.user)
        response = requests.post(
            settings.GOOGLE_AUTH_CALLBACK,
            data={'auth_code': code, 'application_id': application.id},
            headers={'Authorization': 'Token %s' % token},
        )
        assert response.status_code == 200, response.content

        return Response(data={'code': code})


class SetEmailVerified(APIView):
    """
    endpoint to change application history cdate by application_id get the latest change
    """

    permission_classes = (IsAdminUser,)
    model_class = Customer
    serializer_class = CustomerSerializers

    def put(self, request, format=None):
        email = request.data['email']
        customer = Customer.objects.get_or_none(email=email)
        customer.is_email_verified = True
        customer.save()
        return Response([customer.id])


class ChangeCustomerCdate(APIView):
    """
    endpoint to change application history cdate by application_id get the latest change
    """

    permission_classes = (IsAdminUser,)
    model_class = Customer
    serializer_class = CustomerSerializers

    def put(self, request, format=None):
        customer_id = request.data['customer_id']
        cdate_key = request.data['cdate_key']
        times = int(request.data['times'])
        customer = Customer.objects.get_or_none(id=customer_id)
        if customer:
            if cdate_key in ('hour', 'Hour', 'h', 'H'):
                changed_cdate = customer.cdate - relativedelta(hours=times)
            elif cdate_key in ('day', 'Day', 'D', 'd'):
                changed_cdate = customer.cdate - relativedelta(days=times)

            customer.cdate = changed_cdate
            customer.save()

            return Response({'customer_id': customer_id, 'cdate': customer.cdate})
        else:
            return Response({'message': 'customer with id %s not found' % customer_id})


class AccountChanger(APIView):

    permission_classes = (AllowAny,)

    def post(self, request, *args, **kwargs):
        """
        This is a special QA endpoint to randomize your email so you can register
        with the same email multiple times.

        It also randomizes device IMEI and android id so same device can be used
        multiple times without being marked as fraud. Optionally phone numbers
        for all applications too.
        """

        email = request.data['email']
        password = request.data['password']

        customer = Customer.objects.get_or_none(email=email)
        if not customer:
            return Response(status=404, data={"message": "email %s not found" % email})
        user = authenticate(username=customer.user.username, password=password)
        if not user:
            return Response(status=404, data={"message": "authentication failed"})
        time_now = str(int(time.time()))
        handle, domain = email.split('@')
        new_email = ''.join([handle, '+', time_now, '@', domain])

        with transaction.atomic():

            for application in customer.application_set.all():
                application.email = new_email
                phonefields = request.data.get('phonefields', None)
                if phonefields:
                    phone_types = phonefields.split(',')
                    for phone_type in phone_types:
                        setattr(
                            application,
                            phone_type,
                            '08'
                            + time_now
                            + ''.join(random.choice(string.digits) for _ in range(5)),
                        )
                application.save()

            customer.email = new_email
            customer.save()

            for device in customer.device_set.all():
                device.imei = ''.join(
                    random.choice(string.ascii_lowercase + string.digits) for _ in range(20)
                )
                device.android_id = ''.join(
                    [time_now, ''.join(random.choice(string.digits) for _ in range(10))]
                )
                device.save()
        return Response(status=201, data={"new_email": new_email})


class ExecuteLocNotificationTask(RetrieveAPIView):
    """Internal way to trigger scheduled tasks (very hacky)"""

    permission_classes = (IsAdminUser,)

    def get(self, request, *args, **kwargs):
        execute_loc_notification()
        return Response("execute_loc_notification")


class RandomizeImeiAndAndroidId(APIView):
    permission_classes = (IsAdminUser,)

    def get(self, request, *args, **kwargs):
        email = request.query_params.get('email', None)
        if email:
            customer = Customer.objects.get_or_none(email=email)
            if customer:
                devices = customer.device_set.all()
                for device in devices:
                    device.android_id = (
                        "andro"
                        + (
                            str(int((time.time() + 0.5) * 1000))
                            + str(int((time.time() + 0.5) * 1000))
                        )[-17:]
                    )
                    device.imei = str(int((time.time() + 0.5) * 1000)) + str(
                        int((time.time() + 0.5) * 1000)
                    )
                    device.save()
                devices._result_cache = None
                return Response(
                    {'success': True, 'content': DeviceSerializers(devices, many=True).data}
                )
            else:
                return Response({'success': False, 'message': 'No customer found'})
        else:
            return Response({'success': False, 'message': 'email is required'})


class ModifyCreditScore(APIView):
    permission_classes = (IsAdminUser,)

    def post(self, request, *args, **kwargs):
        application_id = request.data['application_id']
        demanded_score = request.data['score']
        if application_id and demanded_score:
            application = Application.objects.get_or_none(pk=application_id)
            if application:
                products = get_product_selections(application, demanded_score)
                if hasattr(application, 'creditscore'):
                    credit_score = application.creditscore
                    credit_score.score = demanded_score
                    credit_score.products_str = json.dumps(products)
                    credit_score.save()
                else:
                    CreditScore.objects.create(
                        application_id=application.id,
                        score=demanded_score,
                        products_str=json.dumps(products),
                        message="manual edit via QA API",
                    )
                product_lines = ProductLine.objects.filter(product_line_code__in=products)
                return Response(
                    {
                        'success': True,
                        'content': ProductLineSerializer(product_lines, many=True).data,
                    }
                )
            else:
                return Response({'success': False, 'message': 'No application found'})
        else:
            return Response({'success': False, 'message': 'application_id and score is required'})


class GenerateBcaSignature(APIView):
    permission_classes = (IsAdminUser,)

    def post(self, request):
        access_token = request.META.get('HTTP_BCA_ACCESS_TOKEN')
        content_type = request.META.get('CONTENT_TYPE')
        origin = request.META.get('HTTP_ORIGIN')
        x_bca_key = request.META.get('HTTP_X_BCA_KEY')
        x_bca_timestamp = request.META.get('HTTP_X_BCA_TIMESTAMP')
        headers = dict(
            access_token=access_token,
            content_type=content_type,
            origin=origin,
            x_bca_key=x_bca_key,
            x_bca_timestamp=x_bca_timestamp,
        )
        data = json.loads(request.body, object_pairs_hook=OrderedDict)
        relative_url = data.pop('relative_url')
        body = json.dumps(data).replace(' ', '')
        encrypted_data = generate_hex_sha256(body)
        access_token = headers.get('access_token').split(' ')[-1]
        bca_client = get_bca_client()
        signature = bca_client.generate_signature(
            'POST', relative_url, access_token, encrypted_data, headers.get('x_bca_timestamp')
        )
        return Response(signature)


# API TO BUGFIX (BUG CHAMPION HELPER) #
class BugChampionLoginView(APIView):
    permission_classes = (AllowAny,)
    serializer_class = BugChampionLoginSerializer

    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)

        data = serializer.validated_data
        username = data.get('username')
        password = data.get('password')

        user = User.objects.filter(username=username).last()
        is_password_correct = user.check_password(password)
        if not is_password_correct:
            return Response(status=HTTP_400_BAD_REQUEST, data={'errors': ["Incorrect Password"]})
        if not user:
            return Response(
                status=HTTP_400_BAD_REQUEST,
                data={'message': 'Either password or username is incorrect'},
            )

        if not user.is_active:
            return Response(
                status=HTTP_400_BAD_REQUEST,
                data={'message': 'The account is valid but has been disabled!'},
            )

        if not user.is_staff:
            return Response(
                status=HTTP_400_BAD_REQUEST,
                data={'message': 'The account is valid but unauthorized!'},
            )

        token, created = Token.objects.get_or_create(user=user)
        return Response({'token': token.key})


class BugChampionForceChangeStatusView(APIView):
    permission_classes = (IsAdminUser,)
    serializer_class = BugChampionForceChangeStatusSerializer

    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        application_id = data.get('application_id')  # application_id: number,
        agent = data.get('agent')  # agent: string,
        notes = data.get('notes')  # notes: string,
        newstatus = data.get('newstatus')  # newstatus: number
        run_handler = data.get('run_handler')

        FORBIDDEN_STATUSES = [170, 180, 181]
        res_data = dict(status=False, message='')
        if newstatus in FORBIDDEN_STATUSES:
            res_data['status'] = False
            res_data['message'] = 'do not change to forbidden statuses {}'.format(
                FORBIDDEN_STATUSES
            )
            return Response(status=HTTP_400_BAD_REQUEST, data=res_data)

        if run_handler:
            changed, message = force_change_status(application_id, newstatus, notes, agent)
            res_data['status'] = changed
            res_data['message'] = message
        else:
            changed, message = force_change_status(application_id, newstatus, notes, agent)
            res_data['status'] = changed
            res_data['message'] = message

        return Response(data=data)


class BugChampionRescrapeActionView(APIView):
    permission_classes = (IsAdminUser,)
    serializer_class = BugChampionRescrapeActionSerializer

    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        application_id = data.get('application_id')
        application = Application.objects.get_or_none(pk=application_id)
        if not application:
            return Response(
                {'status': False, 'message': 'application id {} not found'.format(application_id)}
            )

        customer = application.customer
        action = 'rescrape'
        status, message = customer_rescrape_action(customer, action)

        return Response({'status': status, 'message': message})


class BugChampionActivateLoanManualDisburseView(APIView):
    permission_classes = (IsAdminUser,)
    serializer_class = BugChampionActivateLoanManualDisburseSerializer

    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        application_ids = data.get('application_ids')
        method = data.get('method')
        response_data = dict(status=False, message='', data={})
        try:
            result = bulk_activate_loan_manual_disburse(application_ids, method)
            response_data['status'] = True
            response_data['message'] = 'bulk activate loan manual disburse success'
            response_data['data'] = result
        except Exception as e:
            response_data['status'] = False
            response_data['message'] = e.__str__()

        return Response(response_data)


class BugChampionPaymentEventView(APIView):
    permission_classes = (IsAdminUser,)
    serializer_class = BugChampionPaymentEventSerializer

    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        payment_id = data.get('payment_id')
        amount = data.get('amount')

        payment_event = PaymentEvent.objects.filter(
            payment_id=payment_id, event_type='payment', event_payment=amount
        )

        if len(payment_event) < 2:
            return Response(data={'status': False, 'message': 'payment event has no duplicate'})

        last_payment_event = payment_event.last()
        last_payment_receipt = last_payment_event.payment_receipt
        last_payment_event.delete()
        return Response(
            data={
                'status': True,
                'message': 'delete payment event with payment receipt %s successfully'
                % last_payment_receipt,
            }
        )


class BugChampionDisbursementMethodView(APIView):
    """get list of payment method available"""

    permission_classes = (IsAdminUser,)

    def get(self, request):
        return Response(METHOD_CHOICES)


class BugChampionPaymentAgentReassignment(APIView):
    permission_classes = (IsAdminUser,)
    parser_classes = (FormParser, MultiPartParser)

    def post(self, request):
        file_obj = request.FILES.get('upload', None)
        if not file_obj or '.csv' not in file_obj.name:
            return Response(status=HTTP_400_BAD_REQUEST)
        datas = []
        # with open(file_obj, 'rb') as csvfile:
        r = csv.DictReader(file_obj.read().decode().splitlines(), delimiter=',')
        for row in r:
            data = {}
            data['loan_id'] = int(row['loan_id'])
            data['old_user_name'] = row['user_1']
            data['type'] = row['type']
            data['new_user_name'] = row['user_2']
            datas.append(data)

        success, failed_loan_assignment = coll_reassign_agent(datas)

        return Response(
            data={
                'status': True,
                'message': 'Success process reassignment agent',
                'failed': failed_loan_assignment,
            }
        )


class BugChampionValidateCustomerBank(APIView):
    permission_classes = (IsAdminUser,)
    serializer_class = BugChampionApplicationIdsSerializer

    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        application_ids = data.get('application_ids').split(",")
        failed_validate_bank_app = []
        status_to = "164"
        reason = "re-validate disburse"
        notes = "manual action from bug champion"

        for app_id in application_ids:
            application = Application.objects.get_or_none(pk=int(app_id))
            if not application:
                failed_validate_bank_app.append("%s - Application does not exist" % app_id)
                continue
            try:
                if application.status in [163, 175]:
                    process_application_status_change(application.id, status_to, reason, note=notes)
                elif application.status in [164]:
                    action = WorkflowAction(application, status_to, reason, notes)
                    action.process_name_bank_validate()
                else:
                    failed_validate_bank_app.append(
                        "%s - Application should be in 163, 164, 175 status code" % app_id
                    )
            except Exception as e:
                failed_validate_bank_app.append("%s - %s" % (app_id, e))

        return Response(
            data={
                'status': True,
                'message': 'Success process validate bank',
                'failed': failed_validate_bank_app,
            }
        )


class BugChampionUpdateLoanStatus(APIView):
    permission_classes = (IsAdminUser,)
    serializer_class = BugChampionUpdateLoanStatusSerializer

    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        loan_ids = data.get('loan_ids').split(",")
        failed_update_loan = []
        for loan_id in loan_ids:
            try:
                loan = Loan.objects.get(pk=int(loan_id))
                loan.update_status()
                loan.save()
            except ObjectDoesNotExist as e:
                failed_update_loan.append("%s - %s" % (loan_id, e))

        return Response(
            data={'status': True, 'message': 'Success process loan', 'failed': failed_update_loan}
        )


class BugChampionUnlock(APIView):
    permission_classes = (IsAdminUser,)
    serializer_class = UnlockSerializer

    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        user = request.user

        ids = data.get('ids').split(",")
        unlock_type = data.get('type')
        failed_unlock = []

        if unlock_type == 'payment':
            for id in ids:
                status = unlocked_payment(id, user)
                if not status:
                    failed_unlock.append(id)

        if unlock_type == 'application':
            for id in ids:
                status = unlocked_app(id, user)
                if not status:
                    failed_unlock.append(id)

        return Response(
            data={'status': True, 'message': 'Success process unlock', 'failed': failed_unlock}
        )


class BugChampionWaiveRefinance(APIView):
    permission_classes = (IsAdminUser,)
    serializer_class = PaymentSerializer

    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        payment_id = data.get('payment_id')

        try:
            payment = Payment.objects.get(pk=int(payment_id))
            waive_refinancing(payment)
        except ObjectDoesNotExist:
            return Response(
                data={
                    'status': False,
                    'message': 'Failed process waive refinance',
                    'failed': payment_id,
                }
            )

        return Response(
            data={'status': True, 'message': 'Success process waive refinance', 'failed': []}
        )


class BugChampionCreateDVC(APIView):
    permission_classes = (IsAdminUser,)
    serializer_class = BugChampionApplicationIdsSerializer

    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        app_ids = data.get('application_ids').split(",")
        failed_update_app = []
        for app_id in app_ids:
            try:
                app = Application.objects.get(pk=int(app_id))
                create_application_checklist(app)
            except ObjectDoesNotExist as e:
                failed_update_app.append("%s - %s" % (app_id, e))

        return Response(
            data={
                'status': True,
                'message': 'Success process create dvc',
                'failed': failed_update_app,
            }
        )


class BugChampionPaymentDiscount(APIView):
    permission_classes = (IsAdminUser,)
    serializer_class = BugChampionPaymentEventSerializer

    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        payment_id = data.get('payment_id')
        amount = data.get('amount')

        result, message = process_payment_discount(amount, payment_id)

        return Response(
            data={'status': result, 'message': message, 'failed': payment_id if not result else []}
        )


class GenerateFaspaySignature(APIView):
    permission_classes = (AllowAny,)

    def get(self, request, va):
        new_va = request.GET.get('new_va', None)

        if new_va and new_va.lower() == 'true':
            faspay_user_id = settings.FASPAY_USER_ID_FOR_VA_PHONE_NUMBER
            faspay_password = settings.FASPAY_PASSWORD_FOR_VA_PHONE_NUMBER
        else:
            faspay_user_id = settings.FASPAY_USER_ID
            faspay_password = settings.FASPAY_PASSWORD

        signature_keystring = '{}{}{}'.format(faspay_user_id, faspay_password, va)
        julo_signature = generate_sha1_md5(signature_keystring)

        return Response(data={'signature': julo_signature})


class GenerateFaspayPaymentNotificationSignature(APIView):
    permission_classes = (AllowAny,)

    def post(self, request):
        data = json.loads(request.body, object_pairs_hook=OrderedDict)

        if data.get('bill_no') is None or data.get('payment_status_code') is None:
            return Response({'error': 'bill_no and payment_status_code cannot be empty in body'})

        if data.get('new_va'):
            faspay_user_id = settings.FASPAY_USER_ID_FOR_VA_PHONE_NUMBER
            faspay_password = settings.FASPAY_PASSWORD_FOR_VA_PHONE_NUMBER
        elif data.get('bni_va'):
            faspay_user_id = settings.FASPAY_USER_ID_BNI_VA
            faspay_password = settings.FASPAY_PASSWORD_BNI_VA
        else:
            faspay_user_id = settings.FASPAY_USER_ID
            faspay_password = settings.FASPAY_PASSWORD

        signature_keystring = '{}{}{}{}'.format(
            faspay_user_id, faspay_password, data['bill_no'], data['payment_status_code']
        )
        julo_signature = generate_sha1_md5(signature_keystring)

        return Response(data={'signature': julo_signature})


class BugChampionChangeNameKtp(APIView):
    permission_classes = (IsAdminUser,)
    serializer_class = BugChampionKtpNameSerializer

    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        application_id = data.get('application_id')
        name = data.get('name')

        try:
            process_change_name_ktp(application_id, name)
        except JuloException as je:
            return not_found_response(str(je))

        return success_response({'name': name, 'application_id': application_id})


class BugChampionPaymentRestructure(APIView):
    permission_classes = (IsAdminUser,)
    serializer_class = BugChampionPaymentRestructureSerializer

    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        loan_id = data.get('loan_id')
        starting_payment_number = data.get('starting_payment_number')
        principal_amount = data.get('principal_amount')
        interest_amount = data.get('interest_amount')
        late_fee = data.get('late_fee')
        first_due_date = data.get('first_due_date')
        payment_count_to_restructure = data.get('payment_count_to_restructure')
        try:
            loan = payment_restructure(
                loan_id,
                starting_payment_number,
                principal_amount,
                interest_amount,
                late_fee,
                payment_count_to_restructure,
                first_due_date,
            )
        except JuloException as je:
            return not_found_response(str(je))

        return success_response(
            {
                'new_loan_duration': loan.loan_duration,
                'new_installment_amount': loan.installment_amount,
                'new_cycle_day': loan.cycle_day,
            }
        )


class ManualDisburseFakeCallBack(APIView):
    # permission_classes = (IsAdminUser,)
    serializer_class = ManualDisburseFakeCallBackSerializer

    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        application_id = data.get('application_id')
        bank_reference_id = data.get('bank_reference')
        application = Application.objects.get_or_none(pk=application_id)

        if not application:
            return not_found_response('Application not found')

        if application.application_status_id != ApplicationStatusCodes.FUND_DISBURSAL_SUCCESSFUL:
            return not_found_response('Application status is not 180')

        disbursement_id = application.loan.disbursement_id

        lender_transaction_mapping = LenderTransactionMapping.objects.get_or_none(
            disbursement_id=disbursement_id, lender_transaction__isnull=True
        )

        if not lender_transaction_mapping:
            return general_error_response('Application is already disbursed')

        disbursement = Disbursement.objects.get_or_none(pk=disbursement_id)

        if not disbursement.step:
            return general_error_response('Disburse is not new money flow')

        if disbursement.step != XfersDisbursementStep.SECOND_STEP:
            return general_error_response('Disbursement is not second step')

        loan = application.loan

        try:
            with transaction.atomic():
                update_fields = ['disburse_status', 'reason', 'reference_id']
                disbursement.disburse_status = DisbursementStatus.COMPLETED
                disbursement.reason = 'Manual Disburse'
                disbursement.reference_id = bank_reference_id
                disbursement.save(update_fields=update_fields)
                disbursement.create_history('update_status', update_fields)
                create_disbursement_new_flow_history(disbursement)
                update_lender_balance_current_for_disbursement(loan.id)

        except JuloException:
            return general_error_response('Process is failed! Please try again!')

        return success_response(
            {'status': 'success', 'message': 'successfully update disbursement data'}
        )


class ChangeApplicationStatus(APIView):
    def post(self, request, application_id):
        application = Application.objects.get_or_none(pk=application_id)
        if not application:
            return not_found_response('application not found')

        next_application_status = request.data['next_application_status']
        if not next_application_status:
            return general_error_response('next_application_status must be filled')

        process_application_status_change(
            application.id, next_application_status, change_reason="change status by API"
        )

        return success_response(
            {'status': 'success', 'message': 'successfully change application status'}
        )
