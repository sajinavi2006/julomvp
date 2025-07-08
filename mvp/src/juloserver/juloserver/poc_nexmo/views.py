from __future__ import print_function
from builtins import str
from django.shortcuts import render

# Create your views here.
from django.views.generic import TemplateView
import time
import os
import calendar

from base64 import urlsafe_b64encode
from datetime import datetime
from jose import jwt
from django.conf import settings
from .models import NexmoUser, NexmoConversation
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.status import HTTP_201_CREATED, HTTP_200_OK
from rest_framework.permissions import AllowAny


# Create your views here.
class HomePageView(TemplateView):
    def get(self, request, username):
        user = NexmoUser.objects.get(name=username)
        d = datetime.utcnow()
        token_payload = {
            "iat": calendar.timegm(d.utctimetuple()),
            "jti": urlsafe_b64encode(os.urandom(64)).decode('utf-8'),
            "sub": user.name,
            "exp": str(int(time.time())+86400),
            "acl": {
                "paths": {
                    "/v1/users/**": {},
                    "/v1/conversations/**": {},
                    "/v1/sessions/**": {},
                    "/v1/devices/**": {},
                    "/v1/image/**": {},
                    "/v3/media/**": {},
                    "/v1/applications/**": {},
                    "/v1/push/**": {},
                    "/v1/knocking/**": {}
                }
            },
            "application_id": "562d1229-3acd-4bbf-a4c6-5b18eb3d1ff8"
        }
        token = jwt.encode(claims=token_payload, key=settings.NEXMO_PRIVATE_KEY_POC, algorithm='RS256')

        context = {"username": user.name, "userid": user.id, "user_token": token}

        return render(request, 'index2.html', context)

class AnswerUrlView(APIView):
    permission_classes = (AllowAny,)
    def get(self, request, userid):
        user = NexmoUser.objects.get(pk=userid)

        response_data = [
            {
                "action":"talk",
                "voiceName":"Damayanti",
                "text":"Angsuran Anda ke 6 sebesar 1000000 rupiah"
            },
            {
                "action": "connect",
                "from": "6285574670087",
                "endpoint": [
                    {
                        "type": "app",
                        "user": user.name
                    }
                ]
            }
        ]
        return Response(data=response_data)


class CallQueueView(APIView):

    permission_classes = (AllowAny,)

    def post(self, request):
        data = request.data.copy()
        phonenumbers = data['phone_numbers']
        for phonenumber in phonenumbers:
            NexmoConversation.objects.create(to_number=phonenumber)
        return Response(status=HTTP_201_CREATED, data={"success":True})


class CallStatusView(APIView):
    permission_classes = (AllowAny,)

    def post(self, request):
        failed_statuses = ("unanswered", "timeout", "rejected", "busy")
        data = request.data.copy()
        conversation_uuid = data["conversation_uuid"]
        status = data["status"]
        conversation = NexmoConversation.objects.get_or_none(uuid=conversation_uuid)
        if conversation:
            conversation.result = status
            conversation.save()
            if status == "completed" or status in failed_statuses:
                user = conversation.agent
                user.is_oncall = False
                user.save()
        print("=========================================================")
        print(data)
        print("=========================================================")
        return Response(status=HTTP_200_OK)
