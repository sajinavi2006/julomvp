from builtins import zip
import logging
import datetime
import base64

from django.contrib.auth.models import Group
from django.contrib.auth.models import User
from django.core.files.base import ContentFile
from django.db import transaction, connection
from django.db.utils import IntegrityError
from rest_framework import status, viewsets
from rest_framework.response import Response
from rest_framework.views import APIView

from juloserver.julo.models import Agent, DashboardBuckets, Customer, EmailAttachments, EmailHistory
from juloserver.core.renderers import JuloJSONRenderer
from juloserver.julo.utils import check_email
from .authserver.api import save_user
from .permissions import AgentSupervisor, AgentPermission
from .raw_sql import Sqls
from .serializers import AgentSerializer, GroupSerializer, BucketSerializer, CustomerSerializer, EmailSerializer

logger = logging.getLogger(__name__)


class AgentViewSet(viewsets.ModelViewSet):
    """
    Agents
    """

    serializer_class = AgentSerializer
    permission_classes = (AgentSupervisor,)
    renderer_classes = (JuloJSONRenderer,)

    def post(self, request, format=None):
        self.serializer_class().custome_validation(request.data)
        email = request.data['user'].strip().lower()
        if not check_email(email):
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data={"Email is not valid."})
        username = email
        name = request.data['name']
        password = request.data['password']
        role = request.data['role']

        with transaction.atomic():

            try:
                user = User.objects.create_user(first_name=name, username=username, password=password, email=email)
            except IntegrityError:
                logger.warn("Registration failed, email=%s already exists")
                return Response(
                    status=status.HTTP_400_BAD_REQUEST,
                    data={"Email already exists. Please use another email."})
            logger.info("Sucessfully created user=%s" % user)
            group = Group.objects.filter(pk=role, name__in=['agent1', 'agent2', 'agent3'])[0]

            user.groups.add(group)

            data = {
                "username": username,
                "password": password,
                "first_name": name,
                "last_name": "",
                "email": email,
                "mvp_user_id": user.pk,
                "role": group.name
            }
            result = save_user(data)
            if not result:
                raise ValueError('could not create user in auth server')

            agent = Agent()
            agent.user = user
            agent.created_by = request.user
            agent.save()
            logger.info("Agent with id=%d registered" % agent.id)
            return Response({"message": "created"})

    def get_queryset(self):
        queryset = Agent.objects.all()
        date_from = self.request.query_params.get('date-from', None)
        date_to = self.request.query_params.get('date-to', None)
        role_id = self.request.query_params.get('role', None)
        name = self.request.query_params.get('query', None)
        if date_from is not None:
            queryset = queryset.filter(cdate__gte=date_from)
        if date_to is not None:
            queryset = queryset.filter(cdate__lte=date_to)
        if role_id is not None:
            queryset = queryset.filter(user__groups__id=role_id)
        if name is not None:
            queryset = queryset.filter(user__username__contains=name)
        return queryset


class GroupViewSet(viewsets.ModelViewSet):
    """
    Agents
    """
    queryset = Group.objects.filter(name__in=['agent1', 'agent2', 'agent3'])
    serializer_class = GroupSerializer
    permission_classes = (AgentSupervisor,)
    renderer_classes = (JuloJSONRenderer,)


class BucketViewSet(viewsets.ModelViewSet):
    """
    Agents
    """
    queryset = DashboardBuckets.objects.all()
    serializer_class = BucketSerializer
    permission_classes = (AgentSupervisor,)
    renderer_classes = (JuloJSONRenderer,)


class CustomerViewSet(viewsets.ModelViewSet):
    serializer_class = CustomerSerializer
    permission_classes = (AgentSupervisor,)
    renderer_classes = (JuloJSONRenderer,)

    def get_queryset(self):
        paid_status_codes = ["330", "331", "332"]
        due_date = datetime.datetime.now().date()
        bucket = self.request.query_params.get('bucket', '')
        status = self.request.query_params.get('status', '')
        queryset = Customer.objects.all()
        if bucket == 't0':
            queryset = queryset.filter(loan__payment__due_date=due_date)
        elif bucket == 't1':
            due_date = due_date + datetime.timedelta(1)
            queryset = queryset.filter(loan__payment__due_date=due_date)
        elif bucket == 't3':
            due_date = due_date + datetime.timedelta(3)
            queryset = queryset.filter(loan__payment__due_date=due_date)
        elif bucket == 't5':
            due_date = due_date + datetime.timedelta(5)
            queryset = queryset.filter(loan__payment__due_date=due_date)
        elif bucket == 't+1-t+4':
            dt_from = due_date + datetime.timedelta(-4)
            dt_to = due_date + datetime.timedelta(-1)
            queryset = queryset.filter(loan__payment__due_date__range=[dt_from, dt_to])
        elif bucket == 't+5-t+29':
            dt_from = due_date + datetime.timedelta(-30)
            dt_to = due_date + datetime.timedelta(-5)
            queryset = queryset.filter(loan__payment__due_date__range=[dt_from, dt_to])
        elif bucket == 't+30-t+44':
            dt_from = due_date + datetime.timedelta(-30)
            dt_to = due_date + datetime.timedelta(-59)
            queryset = queryset.filter(loan__payment__due_date__range=[dt_from, dt_to])
        elif bucket == 't+60-t+89':
            dt_from = due_date + datetime.timedelta(-60)
            dt_to = due_date + datetime.timedelta(-89)
            queryset = queryset.filter(loan__payment__due_date__range=[dt_from, dt_to])
        elif bucket == '>t+89':
            dt_to = due_date + datetime.timedelta(-89)
            queryset = queryset.filter(loan__payment__due_date__lte=dt_to)
        elif bucket == '>t+29':
            dt_to = due_date + datetime.timedelta(-29)
            queryset = queryset.filter(loan__payment__due_date__lte=dt_to)
        elif bucket == "wa":
            queryset = queryset.filter(loan__payment__is_whatsapp=True)
        elif bucket == "ptp":
            queryset = queryset.filter(loan__payment__ptp_date__isnull=False)
        elif status in paid_status_codes:
            queryset = queryset.filter(loan__payment__payment_status=status)
        elif status == "ban":
            queryset = queryset.filter(loan__is_ignore_calls=True)


        if not status:
            queryset = queryset.exclude(loan__payment__payment_status__in=paid_status_codes)

        return queryset


class PerformanceViewSet(APIView):
    permission_classes = (AgentSupervisor,)
    renderer_classes = (JuloJSONRenderer,)

    def dict_fetchall(self, cursor):
        desc = cursor.description
        return [
            dict(list(zip([col[0] for col in desc], row)))
            for row in cursor.fetchall()
        ]

    def get(self, request, format=None):
        today = datetime.date.today()
        first = today.replace(day=1)
        last_month = first - datetime.timedelta(days=1)
        year = last_month.strftime("%Y")
        month = last_month.strftime("%m")
        cursor = connection.cursor()
        cursor.execute(Sqls.monthly_collection(), [month, year])
        collections_rows = self.dict_fetchall(cursor)
        cursor.execute(Sqls.monthly_performance(), [month, year])
        performance_rows = self.dict_fetchall(cursor)
        cursor.execute(Sqls.monthly_performance_all(), [month, year])
        performance_rows_all = self.dict_fetchall(cursor)
        data = {
            "collection": collections_rows,
            "performance": performance_rows,
            "performance_all": performance_rows_all
        }
        return Response(data)


class EmailViewSet(viewsets.ModelViewSet):
    permission_classes = (AgentPermission,)
    renderer_classes = (JuloJSONRenderer,)
    queryset = EmailHistory.objects.all()
    serializer_class = EmailSerializer

    def post(self, request, format=None):
        serializer = EmailSerializer(data=request.data)
        if serializer.is_valid():
            email = serializer.save()
            attachments = request.data.getlist("attachments[]")
            if attachments:
                for attachment in attachments:
                    file_format, file_str = attachment.split(';base64,')
                    ext = file_format.split('/')[-1]
                    data = ContentFile(base64.b64decode(file_str), name='temp.' + ext)
                    EmailAttachments.objects.create(attachment=data, email=email)

            return Response({"message": "created"})
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
