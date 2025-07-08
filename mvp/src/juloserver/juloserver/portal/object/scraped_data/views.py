from __future__ import print_function
import json
import operator
import hashlib, random
 
import datetime
import logging
from itertools import chain
from operator import attrgetter

from django.contrib import messages 
from django.views.decorators.csrf import csrf_protect
from django.conf import settings
from django.db.models import F, Value, CharField
from django.template.loader import render_to_string
from django.utils.html import strip_tags
 
from django.utils import timezone
from django.http import HttpResponseRedirect, HttpResponse
from django.core.exceptions import ObjectDoesNotExist
from django.template import RequestContext
from django.shortcuts import render_to_response, render
from django.shortcuts import get_object_or_404, redirect
from django.core.urlresolvers import reverse
from django.contrib.auth.models import User, Group
from django.http import Http404  
from django.db.models import Q
from django.views.generic import ListView, DetailView

#set decorator for login required
from object import julo_login_required, julo_login_required_exclude
from object import julo_login_req_group_class, julo_login_required_multigroup

from juloserver.julo.models import ApplicationHistory, ApplicationNote
from juloserver.julo.models import Application, StatusLookup

from .forms import ApplicationSearchForm
from functools import reduce

logger = logging.getLogger(__name__)


PROJECT_URL = getattr(settings, 'PROJECT_URL', 'http://api.julofinance.com')


@julo_login_required
@julo_login_required_multigroup(['admin_full', 'bo_sd_verifier'])
class ScrapedDataListView(ListView):
    model = Application
    paginate_by = 10
    template_name = 'object/scraped_data/list_for_excel.html'


    def http_method_not_allowed(self, request, *args, **kwargs):
        # print "http_method_not_allowed"
        return ListView.http_method_not_allowed(self, request, *args, **kwargs)

    def get_template_names(self):
        # print "get_template_names"
        return ListView.get_template_names(self)

    def get_queryset(self):
        # print "get_queryset"
        self.qs = super(ScrapedDataListView, self).get_queryset()
        self.qs = self.qs.order_by('-cdate')

        self.err_message_here = None
        self.tgl_range = None
        self.tgl_start = None
        self.tgl_end = None
        self.status_app = None
        self.search_q = None
        self.status_now = None

        # print "self.request.GET: ", self.request.GET
        if self.request.method == 'GET':
            self.tgl_range = self.request.GET.get('datetime_range', None)
            self.status_app = self.request.GET.get('status_app', None)
            self.search_q = self.request.GET.get('search_q', '').strip()
            self.status_now = self.request.GET.get('status_now', None)

            # print "self.form: ", self.tgl_range
            # print "self.form: ", self.status_app
            # print "self.form: ", self.search_q, self.status_now

            if isinstance(self.search_q, str) and self.search_q:
                self.qs = self.qs.filter(reduce(operator.or_,
                    [
                        Q(**{('%s__icontains' % 'fullname'): self.search_q}),
                        Q(**{('%s__icontains' % 'ktp'): self.search_q}),
                        Q(**{('%s__icontains' % 'mobile_phone_1'): self.search_q}),
                        Q(**{('%s__icontains' % 'id'): self.search_q}),
                        Q(**{('%s__icontains' % 'email'): self.search_q})
                    ]))

            if(self.status_app):
                self.qs = self.qs.filter(application_status__status_code=self.status_app)

            if(self.status_now):
                # print "OKAY STATUS NOW : ", self.status_now
                if(self.status_now=='True'):
                    # print "HARI INI"
                    startdate = datetime.datetime.today()
                    startdate = startdate.replace(hour=0, minute=0, second=0)
                    enddate = startdate + datetime.timedelta(days=1)
                    enddate = enddate - datetime.timedelta(seconds=1)
                    self.qs = self.qs.filter(cdate__range=[startdate, enddate])
                else:
                    _date_range = self.tgl_range.split('-')
                    if(_date_range[0].strip()!= 'Invalid date'):
                        _tgl_mulai = datetime.datetime.strptime(_date_range[0].strip(),"%d/%m/%Y %H:%M")
                        _tgl_end = datetime.datetime.strptime(_date_range[1].strip(), "%d/%m/%Y %H:%M")
                        # print "BEBAS"
                        if(_tgl_end > _tgl_mulai):
                            self.qs = self.qs.filter(cdate__range=[_tgl_mulai, _tgl_end])
                        else:
                            self.err_message_here = "Tgl Sampai Harus Lebih besar dari Tgl Dari"
                    else:
                        self.err_message_here = "Format Tanggal tidak valid"
        else:
            print("else request GET")

        return self.qs

    def get_context_object_name(self, object_list):
        # print "get_context_object_name"
        return ListView.get_context_object_name(self, object_list)

    def get_context_data(self, **kwargs):
        # print "get_context_data"
        context = super(ScrapedDataListView, self).get_context_data(**kwargs)
        if self.request.method == 'GET':
            context['form_search'] = ApplicationSearchForm(self.request.GET.copy()) 
        else:
            context['form_search'] = ApplicationSearchForm()
        context['results_per_page'] = self.paginate_by
        context['obj_search'] = None
#         print "self.kwargs['status_order']: ", self.kwargs['status_order']
        try:
            context['STATUS_ORDER'] = showStatusOrder(self.kwargs['status_order'])
        except:
            context['STATUS_ORDER'] = "Seluruh Data"
        context['err_msg'] = self.err_message_here
        context['PROJECT_URL'] = settings.PROJECT_URL
        get_copy = self.request.GET.copy()
        parameters = get_copy.pop('page', True) and get_copy.urlencode()
        # print "parameters: ", parameters
        context['parameters'] = parameters
        return context

    def get(self, request, *args, **kwargs):
        return ListView.get(self, request, *args, **kwargs)

    def render_to_response(self, context, **response_kwargs):
        # print "render_to_response"
        rend_here = super(ScrapedDataListView, self).render_to_response(context, **response_kwargs)
        return rend_here


@julo_login_required
@julo_login_required_multigroup(['admin_full', 'bo_sd_verifier'])
class ApplicationDetailView(DetailView):
    model = Application
    template_name='object/scraped_data/detail_app_xls.html'

    def get_context_data(self, **kwargs):
        context = super(ApplicationDetailView, self).get_context_data(**kwargs)
        context['now'] = timezone.now()
        return context