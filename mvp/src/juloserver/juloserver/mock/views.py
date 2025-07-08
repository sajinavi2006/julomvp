import logging
import uuid

from django.http import JsonResponse
from rest_framework.permissions import AllowAny
from rest_framework.parsers import JSONParser
from rest_framework.renderers import JSONRenderer
from rest_framework.views import APIView
from juloserver.julo.models import KycRequest
from datetime import datetime

logger = logging.getLogger(__name__)
