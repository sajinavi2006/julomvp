from __future__ import print_function
import json
import operator
import hashlib, random
 
import datetime
import logging

from django.utils import timezone
from django.conf import settings
from django.http import HttpResponseRedirect
from django.core.exceptions import ObjectDoesNotExist
from django.core.urlresolvers import reverse
from django.shortcuts import render_to_response, render
from django.shortcuts import get_object_or_404, redirect
from django.views.generic import ListView, DetailView
from django.db.models import Q

#set decorator for login required
from object import julo_login_required
from object import julo_login_required_group, julo_login_required_multigroup

# from account.models import UserActivation
from juloserver.julo.models import StatusLookup
from julo_status.models import StatusAppSelection, ReasonStatusAppSelection

from .forms import StatusSelectionsForm, ReasonSelectionsForm
from functools import reduce

logger = logging.getLogger(__name__)


PROJECT_URL = getattr(settings, 'PROJECT_URL', 'http://api.julofinance.com')


"""
    Status Selections views START
"""
@julo_login_required
@julo_login_required_multigroup(['admin_full'])
class StatusSelectionsView(ListView):
    model = StatusLookup #StatusAppSelection
    paginate_by = 50 #get_conf("PAGINATION_ROW") #= 20

    def get_queryset(self):
        qs = super(StatusSelectionsView, self).get_queryset().order_by('status_code')

        self.q = self.request.GET.get('q', '').strip()
        # Fetching information for display
        if isinstance(self.q, str) and self.q:
            qs = qs.filter(reduce(operator.or_,
                [
                    Q(**{('%s__icontains' % 'status'): self.q}),
                    Q(**{('%s__icontains' % 'status_code'): self.q})
                ]))

        return qs

    def get_context_data(self, **kwargs):
        context = super(StatusSelectionsView, self).get_context_data(**kwargs)
        self.q = self.request.GET.get('q', '').strip()
        context['extra_context'] = {'q': self.q},
        context['q_value'] = self.q
        context['results_per_page'] = self.paginate_by
        return context


@julo_login_required
@julo_login_required_multigroup(['admin_full'])
def status_selections_update(request, status_code):
    # check if there is Application which matches the application_id (if not then display 404)
    status_obj = get_object_or_404(StatusLookup, status_code=status_code)
    status_selection_current = status_obj.statusapp_from.all()

    template_name ='object/julo_status/roles/update_status_selection.html'

    ignore_status = [] 
    ignore_status.append(status_obj.status_code)

    if request.method == 'POST':
        form = StatusSelectionsForm(ignore_status, 
            request.POST)
        if form.is_valid():
            status_to_all = form.cleaned_data['status_to_all']

            # delete all record before update
            if status_selection_current.count()>0:
                status_selection_current.delete()

            #insert new
            for item in status_to_all:
                StatusAppSelection.objects.create(status_from=status_obj,
                    status_to=item)

            url = reverse('julo_status:detail_status_selection', kwargs={'pk': status_obj.status_code })
            return redirect(url)
    else:
        form = StatusSelectionsForm(ignore_status)

    status_exists = [item.status_to.status_code for item in status_selection_current]
    return render(request, 
        template_name,
            { 
            'form':form ,
            'status_obj': status_obj ,
            'status_current': status_selection_current,
            'status_exists': status_exists
            }
        )


@julo_login_required
@julo_login_required_multigroup(['admin_full'])
class StatusSelectionDetailView(DetailView):
    model = StatusLookup
    template_name='object/julo_status/roles/detail_status_selection.html'
    allow_empty = True
    pk_field = 'status_code' # 'name' is field of Customer Model

    def get_context_data(self, **kwargs):
        self.object = self.get_object()
        context = super(StatusSelectionDetailView, self).get_context_data(**kwargs)
        context['now'] = timezone.now()
        return context

"""
    Status Selections views END
"""

"""
    Reason views START
"""

@julo_login_required
@julo_login_required_multigroup(['admin_full'])
class ReasonSelectionsView(ListView):
    model = StatusLookup #StatusAppSelection
    paginate_by = 50 #get_conf("PAGINATION_ROW") #= 20

    def get_queryset(self):
        qs = super(ReasonSelectionsView, self).get_queryset()

        self.q = self.request.GET.get('q', '').strip()
        # Fetching information for display
        if isinstance(self.q, str) and self.q:
            qs = qs.filter(reduce(operator.or_,
                [
                    Q(**{('%s__icontains' % 'status'): self.q}),
                    Q(**{('%s__icontains' % 'status_code'): self.q})
                ]))

        return qs

    def get_context_data(self, **kwargs):
        context = super(ReasonSelectionsView, self).get_context_data(**kwargs)
        self.q = self.request.GET.get('q', '').strip()
        context['extra_context'] = {'q': self.q}
        context['q_value'] = self.q
        context['results_per_page'] = self.paginate_by
        return context


@julo_login_required
@julo_login_required_multigroup(['admin_full'])
def reason_selections_update(request, status_code):
    # check if there is statuslookup which matches the statuslookup (if not then display 404)
    status_obj = get_object_or_404(StatusLookup, status_code=status_code)
    reason_selection_current = status_obj.reason_status_to.all()
    reason_exists = [item.reason for item in reason_selection_current]
    
    template_name ='object/julo_status/roles/update_reason_selection.html'

    if request.method == 'POST':
        form = ReasonSelectionsForm(reason_exists, request.POST)
        print(form.is_valid())
        if form.is_valid():
            reason_all = form.cleaned_data['reason_all']

            # delete all record before update
            if reason_selection_current.count()>0:
                reason_selection_current.delete()

            # #insert new
            list_reason = reason_all.split("\r\n")
            for item in list_reason:
                str_reason = item.strip()
                if(len(str_reason)>0):
                    ReasonStatusAppSelection.objects.create(status_to=status_obj,
                        reason=str_reason)

            url = reverse('julo_status:detail_reason_selection', kwargs={'pk': status_obj.status_code })
            return redirect(url)
    else:
        form = ReasonSelectionsForm(reason_exists)

    return render(request, 
        template_name,
            { 
            'form':form ,
            'status_obj': status_obj ,
            'reason_current': reason_selection_current,
            'reason_exists': reason_exists
            }
        )


@julo_login_required
@julo_login_required_multigroup(['admin_full'])
class ReasonSelectionDetailView(DetailView):
    model = StatusLookup
    template_name='object/julo_status/roles/detail_reason_selection.html'
    allow_empty = True
    pk_field = 'status_code' 

    def get_context_data(self, **kwargs):
        self.object = self.get_object()
        context = super(ReasonSelectionDetailView, self).get_context_data(**kwargs)
        context['now'] = timezone.now()
        return context

"""
    Reason views END
"""

