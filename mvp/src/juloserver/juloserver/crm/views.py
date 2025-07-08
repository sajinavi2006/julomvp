from __future__ import print_function

import datetime
import json
import logging
from builtins import str

from app_status.functions import (
    MAX_COUNT_LOCK_APP,
    check_lock_app,
    get_lock_status,
    get_user_lock_count,
    lock_by_user,
    role_allowed,
    unlocked_app,
)
from app_status.models import ApplicationLocked, ApplicationLockedMaster, CannedResponse
from app_status.services import dump_application_values_to_excel
from app_status.utils import canned_filter
from cuser.middleware import CuserMiddleware
from django.conf import settings
from django.core import serializers
from django.db import transaction
from django.utils import timezone
from rest_framework import generics
from rest_framework.response import Response
from rest_framework.status import (
    HTTP_200_OK,
    HTTP_201_CREATED,
    HTTP_400_BAD_REQUEST,
    HTTP_404_NOT_FOUND,
    HTTP_500_INTERNAL_SERVER_ERROR,
)
from rest_framework.views import APIView

from juloserver.apiv1.data.loan_purposes import (
    get_loan_purpose_dropdown_by_product_line,
)
from juloserver.crm.constants import (
    CA_CALCULATION_STATUSES,
    DISBURSEMENT_STATUSES,
    EMAIL_STATUSES,
    SKIPTRACE_STATUSES,
)
from juloserver.crm.permissions import IsAuthenticatedAgent
from juloserver.crm.serializers import (
    ApplicationNoteSerializer,
    ApplicationSerializer,
    CannedResponseSerializer,
)
from juloserver.crm.services import (
    get_serialized_app_update_history,
    get_serialized_skiptrace_history,
    get_serialized_sms_email_history,
    get_serialized_status_notes_history,
)
from juloserver.julo.banks import BankManager
from juloserver.julo.clients import get_julo_sentry_client, get_julo_xendit_client
from juloserver.julo.exceptions import EmailNotSent
from juloserver.julo.formulas.underwriting import compute_affordable_payment
from juloserver.julo.models import (
    AddressGeolocation,
    Agent,
    Application,
    ApplicationStatusCodes,
    Bank,
    Disbursement,
    FacebookData,
    Image,
    Loan,
    ProductLine,
    Skiptrace,
    VoiceRecord,
)
from juloserver.julo.services import (
    get_allowed_application_statuses_for_ops,
    get_data_application_checklist_collection,
    get_offer_recommendations,
    process_application_status_change,
    send_email_application,
)
from juloserver.julo.utils import check_email

from .utils import ExtJsonSerializer

logger = logging.getLogger(__name__)
sentry_client = get_julo_sentry_client()


class ApplicationDetailHistoryView(APIView):
    permission_classes = (IsAuthenticatedAgent,)

    def get(self, request, application_id):
        application = Application.objects.get_or_none(id=application_id)
        if not application:
            return Response(status=HTTP_404_NOT_FOUND,
                            data={'not_found': application_id})

        status_notes_history = get_serialized_status_notes_history(application)
        sms_email_history = get_serialized_sms_email_history(application)
        skiptrace_history = get_serialized_skiptrace_history(application)
        application_update_history = get_serialized_app_update_history(application)

        data = {
            'status_notes_history': status_notes_history,
            'sms_email_history': sms_email_history,
            'skiptrace_history': skiptrace_history,
            'application_update_history': application_update_history
        }
        return Response(status=HTTP_200_OK, data=data)


class ApplicationNotesView(APIView):
    permission_classes = (IsAuthenticatedAgent, )

    def post(self, request):
        # override cuserMiddleware class to accept user from request
        CuserMiddleware.set_user(request.user)

        application_id = int(self.request.data['application'])
        application = Application.objects.get_or_none(pk=application_id)
        if not application:
            return Response(status=HTTP_404_NOT_FOUND,
                            data={'not_found_application': application_id})

        data = request.data.copy()
        data['application_id'] = application.id
        serializer = ApplicationNoteSerializer(data=data)

        if serializer.is_valid():
            serializer.save()
            return Response(status=HTTP_201_CREATED, data=data)

        return Response(status=HTTP_400_BAD_REQUEST, data=serializer.errors)


class AppLockedView(APIView):
    permission_classes = (IsAuthenticatedAgent, )

    def get(self, request, application_id):
        user = request.user
        max_agents_lock_app = MAX_COUNT_LOCK_APP
        response_data = {}

        application = Application.objects.get_or_none(pk=application_id)
        if not application:
            return Response(status=HTTP_404_NOT_FOUND,
                            data={'not_found_application': application_id})

        # check max agents locking app
        agent_locked_count = get_user_lock_count(user)
        lock_app = check_lock_app(application, user)
        if lock_app[0] == 1:
                response_data['code'] = '01'
                response_data['result'] = 'successful!'
                response_data['reason'] = 'application is allowed for user %s' % (user.first_name)

        elif(agent_locked_count >= max_agents_lock_app):
            response_data['code'] = '09'
            response_data['result'] = 'failed!'
            response_data['reason'] = 'aplikasi lock oleh agent <code>%s</code> \
            telah lebih dari %d!' % (user.first_name, max_agents_lock_app)

        elif lock_app[0] == 2:
            app_locked_obj = lock_app[1]
            response_data['code'] = '02'
            response_data['result'] = 'failed!'
            response_data['reason'] = (
                'application is locked for this',
                lock_by_user(app_locked_obj),
                app_locked_obj.first().status_code_locked,
                datetime.datetime.strftime(
                    app_locked_obj.first().ts_locked,
                    "%d %b %Y %H:%M:%S"
                ),
            )
        else:
            response_data['code'] = '03'
            response_data['result'] = 'successful!'
            response_data['reason'] = 'application is free and still not locked'

        return Response(
            status=HTTP_200_OK,
            data=response_data
        )

    def post(self, request):
        max_agents_lock_app = MAX_COUNT_LOCK_APP
        user = request.user
        response_data = {}

        # check max agents locking app
        agent_locked_count = get_user_lock_count(user)
        # print "agent_locked_count: ", agent_locked_count

        if(agent_locked_count >= max_agents_lock_app):
            response_data['result'] = 'failed!'
            response_data['reason'] = 'aplikasi lock by agent %s \
            telah lebih dari %d!' % (user, max_agents_lock_app)
            return Response(
                status=HTTP_200_OK,
                data=response_data,
                content_type="application/json"
            )

        application_id = int(request.data['application_id'])
        app_obj = Application.objects.get_or_none(pk=application_id)

        if app_obj and user:
            ret_master = ApplicationLockedMaster.create(
                user=user, application=app_obj, locked=True)
            if ret_master:
                ApplicationLocked.create(
                    application=app_obj, user=user,
                    status_code_locked=app_obj.application_status.status_code)
                response_data['result'] = 'successful!'
                response_data['reason'] = 'application is locked'
            else:
                ret_master_obj = ApplicationLockedMaster.objects.get_or_none(
                    application=app_obj)
                response_data['result'] = 'failed!'
                if ret_master_obj:
                    response_data['reason'] = 'Aplikasi telah di lock oleh %s dengan TS: \
                    %s' % (ret_master_obj.user_lock, ret_master_obj.ts_locked)
                else:
                    response_data['reason'] = 'Aplikasi telah di lock'
        else:
            response_data['result'] = 'failed!'
            response_data['reason'] = 'user not login or application not exist'
            return Response(
                status=HTTP_404_NOT_FOUND,
                data=response_data,
                content_type="application/json"
            )

        return Response(
            status=HTTP_200_OK,
            data=response_data,
            content_type="application/json"
        )


class GetLockStatusView(APIView):
    permission_classes = (IsAuthenticatedAgent, )

    def get(self, request, application_id):
        user = request.user
        response_data = {}

        # application_id = int(self.request.data['application_id'])
        application = Application.objects.get_or_none(pk=application_id)
        if not application:
            return Response(status=HTTP_404_NOT_FOUND,
                            data={'not_found_application': application_id})

        lock_status, lock_by = get_lock_status(application, user)
        response_data['lock_status'] = lock_status
        response_data['lock_by'] = lock_by

        return Response(
            status=HTTP_200_OK,
            data=response_data
        )


class SetUnlockApp(APIView):
    permission_classes = (IsAuthenticatedAgent, )

    def post(self, request):
        print(request)
        user = request.user
        response_data = {}

        application_id = int(self.request.data['application_id'])
        application = Application.objects.get_or_none(pk=application_id)
        if not application:
            return Response(status=HTTP_404_NOT_FOUND,
                            data={'not_found_application': application_id})

        app_locked_master = ApplicationLockedMaster.objects.get_or_none(application=application)

        if app_locked_master:
            app_locked = ApplicationLocked.objects.filter(
                application=application, user_lock=user, locked=True)

            if app_locked.count() > 0:
                with transaction.atomic():
                    unlocked_app(app_locked[0], user)
                    # delete master locked
                    app_locked_master.delete()

                response_data['result'] = 'successful'
                response_data['reason'] = 'Application <code>%s</code> \
                Succesfully Un-Locked' % application.id

            else:
                flag_admin = False
                # check if admin, so it can be unlocked
                if role_allowed(user, ['admin_unlocker']):
                    app_locked_here = ApplicationLocked.objects.filter(
                        application=application, locked=True)
                    if app_locked_here.count() > 0:
                        with transaction.atomic():
                            unlocked_app(
                                app_locked_here[0], user,
                                application.application_status.status_code
                            )
                            # delete master locked
                            app_locked_master.delete()

                        flag_admin = True
                        response_data['result'] = 'successful'
                        response_data['reason'] = 'Application <code>%s</code> \
                        Succesfully Un-Locked by Admin' % application.id

                if (not flag_admin):
                    response_data['result'] = 'failed'
                    response_data['reason'] = 'application is lock by %s, \
                    you are not allowed to unlock!' % (app_locked_master.user_lock)

        return Response(
            status=HTTP_200_OK,
            data=response_data
        )


class ApplicationDetailView(APIView):
    permission_classes = (IsAuthenticatedAgent, )

    def get(self, request, application_id):
        user = request.user
        application = Application.objects.get(pk=application_id)

        if not application:
            return Response(status=HTTP_404_NOT_FOUND,
                            data={'not_found_application': application_id})
        data = {}

        # AGENT AND GROUPS ROLE
        agent_data = None
        agent_obj = Agent.objects.get(user=user)
        if agent_obj:
            agent_data = serializers.serialize('json', [agent_obj, ])
            agent_data = json.loads(agent_data)[0]
        user_groups = user.groups.values_list('name', flat=True)

        # APPLICATION CHECKLIST
        application_checklist = get_data_application_checklist_collection(application)

        # CA CALCULATION
        sum_undisclosed_expense = 0
        calculation_results = None
        product_rate = None
        if 'total_current_debt' in application_checklist:
            for expense in application_checklist['total_current_debt']['undisclosed_expenses']:
                sum_undisclosed_expense += expense['amount']
        if application.application_status.status_code in CA_CALCULATION_STATUSES:
            input_params = {
                'product_line_code': application.product_line.product_line_code,
                'job_start_date': application.job_start,
                'job_end_date': timezone.localtime(application.cdate).date(),
                'job_type': application.job_type,
                'monthly_income': application.monthly_income,
                'monthly_expense': application.monthly_expenses,
                'dependent_count': application.dependent,
                'undisclosed_expense': sum_undisclosed_expense,
                'monthly_housing_cost': application.monthly_housing_cost,
                'application_id': application_id,
                'application_xid': application.application_xid,
            }
            calculation_results = compute_affordable_payment(**input_params)
            calculation_results['undisclosed_expense'] = sum_undisclosed_expense
            offer_recommendations_output = get_offer_recommendations(
                application.product_line.product_line_code,
                application.loan_amount_request,
                application.loan_duration_request,
                calculation_results['affordable_payment'],
                application.payday,
                application.ktp,
                application.id,
                application.partner
                )
            product_rate = offer_recommendations_output['product_rate']

        # SD
        sd_obj_list = application.devicescrapeddata_set.all()
        sd_data_list = serializers.serialize('json', sd_obj_list)

        # ADDRESS GEOLOCATION
        address_geo_obj = AddressGeolocation.objects.get_or_none(application=application)
        address_geolocation = serializers.serialize('json', [address_geo_obj, ])
        address_geolocation = json.loads(address_geolocation)[0]
        gmap_url = application.gmap_url

        # FACEBOOK
        fb_data = None
        try:
            fb_obj = application.facebook_data
            fb_data = serializers.serialize('json', [fb_obj, ])
            fb_data = json.loads(fb_data)[0]
        except FacebookData.DoesNotExist:
            fb_obj = None

        # APPLICATION DUMP VALUE
        app_data_fields, app_data_values = dump_application_values_to_excel(application)

        # BANK LIST
        bank_list = BankManager.get_bank_names()
        bank_list_name = bank_list

        # PARTNER
        partner_referral = None
        partner_account_id = None
        account_doku_julo = None
        if application.partner:
            if application.partner.name == 'doku':
                partner_referral = application.customer.partnerreferral_set.filter(
                    pre_exist=False).last()
                partner_account_id = partner_referral.partner_account_id
                account_doku_julo = settings.DOKU_ACCOUNT_ID

        product_line_code = application.product_line.product_line_code
        serializer = ApplicationSerializer(application)
        status_path = get_allowed_application_statuses_for_ops(application.status, application)

        # SKIPTRACE
        skiptrace_list = Skiptrace.objects.filter(customer=application.customer).order_by('id')

        # EMAIL
        canned_responses = CannedResponse.objects.all()
        email_app_params = {
            'FULL_NAME': application.fullname_with_title,
            'LOAN_AMOUNT': application.loan_amount_request,
            'LOAN_DURATION': application.loan_duration_request,
            'LOAN_PURPOSE': application.loan_purpose,
            'AGENT_NAME': user.username,
        }

        # PRODUCT_LINE, LOAN_PURPOSE, MIN_INCOME
        product_line_list = ProductLine.objects.all()
        loan_purpose_list = get_loan_purpose_dropdown_by_product_line(product_line_code)
        min_income_due = 413000

        # OFFERS
        offers = application.offer_set.all().order_by("offer_number")

        # IMAGE
        image_list = Image.objects.filter(
            image_source=application.id,
            image_status__in=[Image.CURRENT, Image.RESUBMISSION_REQ]
        )
        image_list_json = ExtJsonSerializer().serialize(
            image_list,
            props=['image_url', 'image_ext'],
            fields=('id', 'image_type',)
        )
        image_list_hide = Image.objects.filter(
            image_source=application.id,
            image_status=Image.DELETED)
        image_list_hide_json = ExtJsonSerializer().serialize(
            image_list_hide,
            props=['image_url', 'image_ext'],
            fields=('id', 'image_type',)
        )

        # VOICE
        voice_list = VoiceRecord.objects.filter(
            application=application.id,
            status__in=[VoiceRecord.CURRENT, VoiceRecord.RESUBMISSION_REQ]
        )
        voice_list_json = ExtJsonSerializer().serialize(
            voice_list,
            props=['presigned_url'],
            fields=('id', 'status')
        )

        voice_list_hide = VoiceRecord.objects.filter(
            application=application.id,
            status=VoiceRecord.DELETED
        )
        voice_list_hide_json = ExtJsonSerializer().serialize(
            voice_list_hide,
            props=['presigned_url'],
            fields=('id', 'status')
        )

        # DISBURSEMENT
        disbursement = None
        bank_number_validate = None
        name_validate = None
        if application.application_status_id >= ApplicationStatusCodes.OFFER_ACCEPTED_BY_CUSTOMER:
            loan = Loan.objects.get_or_none(application=application)
            if loan is not None:
                bank_number_validate = 'NOT INITIATED'
                name_validate = 'NOT INITIATED'
                disbursement = Disbursement.objects.get_or_none(loan=loan)
                if disbursement is not None:
                    if disbursement.bank_number is None:
                        bank_number_validate = 'PENDING'
                    else:
                        bank_number_validate = 'VALID'

                    if disbursement.validated_name is None:
                        name_validate = 'PENDING'
                    elif str(disbursement.validated_name).lower() != str(application.name_in_bank).lower():
                        name_validate = 'INVALID'
                    else:
                        name_validate = 'VALID'

        # FIN
        fin = {}
        fin['basic_financial'] = application.basic_financial
        fin['basic_installment'] = application.basic_installment
        fin['basic_installment_discount'] = application.basic_installment_discount
        fin['default_insterest'] = application.default_interest_rate
        fin['determine_kind_of_installment'] = application.determine_kind_of_installment
        fin['dti_multiplier'] = application.dti_multiplier
        fin['dti_capacity'] = application.dti_capacity

        data['agent'] = agent_data
        data['user_groups'] = user_groups
        data['application'] = serializer.data
        data['sd_data_list'] = sd_data_list
        data['fb_data'] = fb_data
        data['address_geolocation'] = address_geolocation
        data['gmap_url'] = gmap_url
        data['bank_list'] = bank_list
        data['bank_list_name'] = bank_list_name
        data['partner_referral'] = partner_referral
        data['partner_account_id'] = partner_account_id
        data['account_doku_julo'] = account_doku_julo
        data['application_checklist'] = application_checklist
        data['app_data_values'] = app_data_values
        data['app_data_fields'] = app_data_fields
        data['fin'] = fin
        data['calculation_results'] = calculation_results
        data['min_income_due'] = min_income_due
        data['product_rate'] = product_rate
        data['offers'] = serializers.serialize('json', offers)
        data['disbursement'] = disbursement
        data['bank_number_validate'] = bank_number_validate
        data['name_validate'] = name_validate
        data['skiptrace_list'] = serializers.serialize('json', skiptrace_list)
        data['status_path'] = status_path
        data['email_statuses'] = EMAIL_STATUSES
        data['skiptrace_statuses'] = SKIPTRACE_STATUSES
        data['ca_calculation_statuses'] = CA_CALCULATION_STATUSES
        data['canned_responses'] = canned_filter(canned_responses)
        data['email_app_params'] = json.dumps(email_app_params)
        data['product_line_list'] = serializers.serialize('json', product_line_list)
        data['loan_purpose_list'] = loan_purpose_list
        data['image'] = image_list_json
        data['image_hide'] = image_list_hide_json
        data['voice'] = voice_list_json
        data['voice_hide'] = voice_list_hide_json

        return Response(status=HTTP_200_OK, data=data)


class ChangeStatusUpdateView(APIView):
    permission_classes = (IsAuthenticatedAgent, )

    def post(self, request):
        user = request.user
        response_data = {}
        # override cuserMiddleware class to accept user from request
        CuserMiddleware.set_user(user)

        application_id = int(request.data['application_id'])
        application = Application.objects.get(pk=application_id)
        if not application:
            return Response(status=HTTP_404_NOT_FOUND,
                            data={'not_found_application': application_id})

        status_to = int(request.data['status_to'])
        reason = request.data['reason']
        notes = request.data['notes']

        logger.info({
            'status_to': status_to,
            'reason': reason,
            'notes': notes
        })

        try:
            with transaction.atomic():
                process_application_status_change(
                    application.id, status_to, reason, note=notes)

            response_data['result'] = 'successful'
            response_data['message'] = 'status updated Succesfully'

            return Response(status=HTTP_200_OK, data=response_data)

        except Exception as e:
                sentry_client.captureException()
                # there is an error
                err_msg = """
                    Ada Kesalahan di Backend Server!!!, Harap hubungi Administrator : %s
                """
                err_msg = err_msg % (e)
                logger.info({
                    'app_id': application.id,
                    'error': "Ada Kesalahan di Backend Server with \
                    process_application_status_change !!!."
                })

                response_data['result'] = 'failed'
                response_data['message'] = str(e)
                response_data['ubah_status_active'] = 1

                return Response(status=HTTP_400_BAD_REQUEST,
                                data=response_data)


class CannedResponseView(generics.RetrieveUpdateDestroyAPIView):

    permission_classes = (IsAuthenticatedAgent, )
    queryset = CannedResponse.objects.all()
    serializer_class = CannedResponseSerializer
    lookup_url_kwarg = 'canned_response_id'


class CannedResponseListCreateView(generics.ListCreateAPIView):
    permission_classes = (IsAuthenticatedAgent, )
    queryset = CannedResponse.objects.all()
    serializer_class = CannedResponseSerializer


class SendEmailView(APIView):
    permission_classes = (IsAuthenticatedAgent, )

    def post(self, request):
        application_id = int(request.data['application_id'])
        application = Application.objects.get_or_none(id=application_id)
        if not application:
            return Response(status=HTTP_404_NOT_FOUND,
                            data={'not_found_application': application_id})

        response_data = {}
        email_content = request.data['email_content']
        email_sender = request.data['email_sender']
        email_receiver = request.data['email_receiver'].replace(" ", "")
        email_cc = request.data['email_cc']
        subject = request.data['subject'] + '-' + application.email

        for email in [x for x in email_receiver.split(',') if x.strip() != '']:
            valid_email = check_email(email.strip())
            if not valid_email:
                response_data['result'] = 'failed'
                response_data['reason'] = "Invalid To Email Address = %s \
                                           cannot be found" % email
                return Response(status=HTTP_400_BAD_REQUEST,
                                data=response_data)
        if email_cc:
            email_cc = email_cc.strip()
            for email in [x for x in email_cc.split(',') if x.strip() != '']:
                valid_email = check_email(email.strip())
                if not valid_email:
                    response_data['result'] = 'failed'
                    response_data['reason'] = "Invalid To Email Address = %s \
                                               cannot be found" % email
                    return Response(status=HTTP_400_BAD_REQUEST,
                                    data=response_data)

        try:
            logger.info({
                'application': application,
                'email_sender': email_sender,
                'email_receiver': email_receiver,
                'email_cc': email_cc,
                'subject': subject,
                'email_content': email_content,
            })
            send_email_application(
                application, email_sender, email_receiver, subject, email_content, email_cc)

        except EmailNotSent:
            response_data['result'] = 'failed'
            response_data['reason'] = 'Send Email Failed!! Please Contact Administrator!!'
            return Response(status=HTTP_500_INTERNAL_SERVER_ERROR,
                            data=response_data)

        response_data['result'] = 'success'
        response_data['reason'] = 'success send email'
        return Response(status=HTTP_200_OK,
                        data=response_data)
