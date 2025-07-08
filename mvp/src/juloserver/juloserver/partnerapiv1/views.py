import logging
from builtins import str
from datetime import datetime

import pytz
from django.contrib.auth import authenticate
from django.contrib.auth.models import Group, User
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from rest_framework import generics
from rest_framework.generics import CreateAPIView, UpdateAPIView
from rest_framework.parsers import JSONParser
from rest_framework.permissions import IsAdminUser
from rest_framework.renderers import JSONRenderer
from rest_framework.response import Response
from rest_framework.status import (
    HTTP_200_OK,
    HTTP_201_CREATED,
    HTTP_400_BAD_REQUEST,
    HTTP_401_UNAUTHORIZED,
)
from rest_framework.views import APIView

from juloserver.api_token.models import ExpiryToken as Token
from juloserver.julo.models import Application, Partner, PartnerLoan, PartnerReferral
from juloserver.julo.services import (
    process_application_status_change,
    process_lender_deposit,
    process_lender_withdraw,
)
from juloserver.julo.statuses import ApplicationStatusCodes

from .constants import PARTNER_GROUP_NAME
from .permissions import IsAuthenticatedPartner, MerchantPartnerSellerAppPermission
from .serializers import (
    ApplicationUpdateSerializer,
    LoginSerializer,
    PartnerLoanSerializer,
    PartnerReferralSerializer,
    PartnerTransactionSerializer,
    RegistrationSerializer,
)

logger = logging.getLogger(__name__)


class ReferralCreateView(CreateAPIView):

    permission_classes = (IsAuthenticatedPartner,)
    parser_classes = (JSONParser,)
    renderer_classes = (JSONRenderer,)
    serializer_class = PartnerReferralSerializer
    model_class = PartnerReferral

    def perform_create(self, serializer):
        user = self.request.user
        serializer.save(partner=user.partner)


class RegistrationView(APIView):

    permission_classes = (IsAdminUser,)
    serializer_class = RegistrationSerializer

    def post(self, request, *args, **kwargs):

        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)

        username = serializer.validated_data['username']
        password = serializer.validated_data['password']
        email = serializer.validated_data['email']
        phone = serializer.validated_data['phone']

        logger.info(
            {'status': 'inputs_value', 'username': username, 'email': email, 'phone': phone}
        )

        with transaction.atomic():

            user = User.objects.create_user(username=username, password=password, email=email)
            logger.info({'status': 'user_created', 'user': user})

            group = Group.objects.get(name=PARTNER_GROUP_NAME)
            user.groups.add(group)
            logger.info({'status': 'user_added_to_group', 'group': group.name})

            partner = Partner.objects.create(user=user, name=username, email=email, phone=phone)
            logger.info({'status': 'partner_created', 'partner': partner})

        return Response(
            status=HTTP_201_CREATED, data={'username': username, 'email': email, 'phone': phone}
        )


class LoginView(APIView):

    permission_classes = ()
    serializer_class = LoginSerializer

    def post(self, request, *args, **kwargs):

        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)

        username = serializer.validated_data['username']
        password = serializer.validated_data['password']

        user = authenticate(username=username, password=password)

        if not user:
            logger.error({'status': 'authentication_failed', 'username': username})
            return Response(
                data={'message': 'Either password or email is incorrect'},
                status=HTTP_401_UNAUTHORIZED,
            )

        if PARTNER_GROUP_NAME not in user.groups.values_list('name', flat=True):
            logger.error({'status': 'user_not_partner', 'username': username})
            return Response(data={'message': "You're not authorized"}, status=HTTP_401_UNAUTHORIZED)

        if Partner.objects.get_or_none(user=user) is None:
            logger.error({'status': 'user_not_partner', 'username': username})
            return Response(data={'message': "You're not authorized"}, status=HTTP_401_UNAUTHORIZED)

        token, created = Token.objects.get_or_create(user=user)
        return Response({'token': token.key})


class PartnerLoanUpdateView(UpdateAPIView):

    permission_classes = (IsAuthenticatedPartner,)
    parser_classes = (JSONParser,)
    renderer_classes = (JSONRenderer,)
    serializer_class = PartnerLoanSerializer
    model_class = PartnerLoan

    def put(self, request, *args, **kwargs):

        wib = timezone.get_current_timezone_name()
        application_xid = request.data['submission_id']
        try:
            application_xid = int(application_xid)
        except ValueError:
            return Response(
                data={'message': "invalid submission_id: %s" % application_xid},
                status=HTTP_400_BAD_REQUEST,
            )

        application = (
            Application.objects.values("id", "application_status_id", "partner_id")
            .filter(application_xid=application_xid)
            .first()
        )
        if application is None:
            return Response(
                data={'message': "application with submission_id %s not found" % application_xid},
                status=HTTP_400_BAD_REQUEST,
            )

        application_id = application['id']
        partner_id = application['partner_id']
        if partner_id is None:
            return Response(
                data={
                    'message': "application with submission_id %s is not application partner"
                    % application_xid
                },
                status=HTTP_400_BAD_REQUEST,
            )

        approval_date = datetime.strptime(request.data['approval_date'], '%Y-%m-%d %H:%M:%S')

        partner_loan = PartnerLoan.objects.filter(application_id=application_id).first()
        if partner_loan is None:
            return Response(
                data={'message': "partner_loan with submission_id %s not found" % application_xid},
                status=HTTP_400_BAD_REQUEST,
            )

        assignment_status = request.data['StatusAssignment'].upper()
        survey_status = request.data['StatusSurvey']
        approval_status = request.data['approval_status']
        disbursement_status = request.data['StatusDisbursement']

        CANCEL = assignment_status == 'UNCONNECTED'
        REJECT_1 = assignment_status == 'UNPROSPECT'
        REJECT_2 = assignment_status == 'PROSPECT' and survey_status == 'Info Negatif'

        approval_statuses = ['Approved', 'Reject', 'Cancel']

        if approval_status not in approval_statuses:
            if CANCEL:
                final_status = 'Cancel'

            elif REJECT_1 or REJECT_2:
                final_status = 'Reject'

            else:
                final_status = 'On Process'

        else:
            if approval_status == 'Approved':
                if disbursement_status == 'Disburse':
                    final_status = 'Approved'
                else:
                    final_status = 'On Process'
            else:
                final_status = approval_status

        partner_loan.agreement_number = request.data['agreement_number']
        approval_date = pytz.timezone(wib).localize(approval_date)
        partner_loan.approval_date = approval_date
        partner_loan.approval_status = final_status
        partner_loan.loan_amount = request.data['loan_amount']

        try:
            partner_loan.full_clean()
        except ValidationError:
            return Response(data={'message': "invalid data"}, status=HTTP_400_BAD_REQUEST)

        partner_loan.update_safely(
            agreement_number=request.data['agreement_number'],
            approval_date=approval_date,
            approval_status=final_status,
            loan_amount=request.data['loan_amount'],
        )

        new_application_status_code = None
        if partner_loan.approval_status == 'Approved':
            new_application_status_code = ApplicationStatusCodes.PARTNER_APPROVED
        elif partner_loan.approval_status == 'Reject':
            new_application_status_code = ApplicationStatusCodes.APPLICATION_DENIED
        elif partner_loan.approval_status == 'Cancel':
            new_application_status_code = ApplicationStatusCodes.APPLICATION_CANCELED_BY_CUSTOMER

        if (
            new_application_status_code is not None
            and new_application_status_code != application['application_status_id']
        ):
            process_application_status_change(
                application_id, new_application_status_code, change_reason='partner_triggered'
            )
        else:
            return Response(data={'message': "Already updated"}, status=HTTP_400_BAD_REQUEST)

        return Response(data={'message': "success"}, status=HTTP_200_OK)


class PartnerTransactionView(APIView):

    permission_classes = (IsAuthenticatedPartner,)
    parser_classes = (JSONParser,)
    renderer_classes = (JSONRenderer,)
    serializer_class = PartnerTransactionSerializer

    def post(self, request, *args, **kwargs):

        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        amount = request.data['amount']
        type_transaction = request.data['type_transaction']
        partner = self.request.user.partner
        if partner.type != 'lender':
            return Response(data={'message': 'Partner not Lender'}, status=HTTP_401_UNAUTHORIZED)
        try:
            if type_transaction == 'deposit':
                process_lender_deposit(partner, amount)
            else:
                process_lender_withdraw(partner, amount)
            lender_balance_event = partner.lenderbalance.lenderbalanceevent_set.all().last()
        except Exception as e:
            return Response(
                data={'message': "process lender failed.", 'error_message': str(e)},
                status=HTTP_400_BAD_REQUEST,
            )
        return Response(
            status=HTTP_200_OK,
            data={
                'message': 'success',
                'transaction_id': lender_balance_event.id,
                'amount': lender_balance_event.amount,
                'before_balance': lender_balance_event.before_amount,
                'after_balance': lender_balance_event.after_amount,
            },
        )


class MerchantApplicationView(generics.RetrieveUpdateAPIView):
    serializer_class = ApplicationUpdateSerializer
    lookup_url_kwarg = 'application_id'
    permission_classes = (MerchantPartnerSellerAppPermission,)

    def get_queryset(self):
        return Application.objects.filter(pk=self.kwargs['application_id'])

    def perform_update(self, serializer):
        serializer.save()
