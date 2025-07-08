import json
import operator

from django.conf import settings
from django.core import serializers
from django.core.urlresolvers import reverse
from django.db import transaction
from django.db.models import Q
from django.http import HttpResponse, HttpResponseNotAllowed, HttpResponseBadRequest
from django.shortcuts import render
from django.shortcuts import get_object_or_404
from django.views.generic import ListView

# set decorator for login required
from object import julo_login_required, julo_login_required_exclude, julo_login_required_admin
from object import julo_login_req_group_class, julo_login_required_multigroup

from .forms import ProductProfileSearchForm

from juloserver.julo.models import Partner
from juloserver.julo.models import ProductCustomerCriteria
from juloserver.julo.models import ProductProfile
from juloserver.julo.models import ProductLookup
from juloserver.julo.models import ProductLine

from juloserver.julo.product_lines import ProductLineCodes

from .constants import CREDIT_SCORE_CHOICES
from .constants import JOB_TYPE_CHOICES
from .constants import JOB_FUNCTION_CHOICES
from .constants import JOB_INDUSTRY_CHOICES
from .constants import JOB_DESCRIPTION_CHOICES
from .constants import PAYMENT_FREQUENCY_CHOICES
from .services import get_cleaned_data
from .services import generate_product_lookup
from functools import reduce


@julo_login_required
class ProductProfileListView(ListView):
    model = ProductProfile
    paginate_by = 50
    template_name = 'object/product_profile/list.html'

    def http_method_not_allowed(self, request, *args, **kwargs):
        return ListView.http_method_not_allowed(self, request, *args, **kwargs)

    def get_template_names(self):
        return ListView.get_template_names(self)

    def get_queryset(self):
        self.qs = super(ProductProfileListView, self).get_queryset()
        self.err_message_here = None
        self.search_q = None
        self.sort_q = None
        self.sort_agent = None

        if self.request.method == 'GET':
            self.search_q = self.request.GET.get('search_q', '').strip()
            self.sort_q = self.request.GET.get('sort_q', None)

            if isinstance(self.search_q, str) and self.search_q:
                self.qs = self.qs.filter(reduce(operator.or_,
                    [Q(**{('%s__icontains' % 'id'): self.search_q}),
                     Q(**{('%s__icontains' % 'code'): self.search_q}),
                     Q(**{('%s__icontains' % 'name'): self.search_q}),
                    ]))

            if(self.sort_q):
                self.qs = self.qs.order_by(self.sort_q)

            return self.qs

    def get_context_object_name(self, object_list):
        return ListView.get_context_object_name(self, object_list)

    def get_context_data(self, **kwargs):
        context = super(ProductProfileListView, self).get_context_data(**kwargs)
        if self.request.method == 'GET':
            context['form_search'] = ProductProfileSearchForm(self.request.GET.copy())
        else:
            context['form_search'] = ProductProfileSearchForm()

        context['results_per_page'] = self.paginate_by
        context['obj_search'] = None
        context['err_msg'] = self.err_message_here
        context['PROJECT_URL'] = settings.PROJECT_URL
        get_copy = self.request.GET.copy()
        parameters = get_copy.pop('page', True) and get_copy.urlencode()
        context['parameters'] = parameters
        return context

    def render_to_response(self, context, **response_kwargs):
        rendered = super(ProductProfileListView, self).render_to_response(context, **response_kwargs)
        return rendered


@julo_login_required
def details(request, pk):
    product_profile = get_object_or_404(ProductProfile, id=pk)
    template_name = 'object/product_profile/detail.html'
    context_data = {}
    context_data['product_profile_id'] = product_profile.id
    context_data['product_line_grab'] = ProductLineCodes.grab()
    return render(
        request,
        template_name,
        context_data
    )


@julo_login_required
def add(request):
    template_name = 'object/product_profile/add.html'
    context_data = {}

    context_data['JOB_TYPE_CHOICES'] = JOB_TYPE_CHOICES
    context_data['JOB_INDUSTRY_CHOICES'] = JOB_INDUSTRY_CHOICES
    context_data['JOB_DESCRIPTION_CHOICES'] = JOB_DESCRIPTION_CHOICES
    context_data['CREDIT_SCORE_CHOICES'] = CREDIT_SCORE_CHOICES
    context_data['PAYMENT_FREQ_CHOICES'] = PAYMENT_FREQUENCY_CHOICES
    context_data['isError'] = False

    return render(
        request,
        template_name,
        context_data
    )


def ajax_get_detail(request):
    response_data = {}
    if request.method != 'GET':
        return HttpResponseNotAllowed(
            json.dumps({
                "message": "method %s not allowed" % request.method,
            }),
            content_type="application/json"
        )

    product_profile_id = int(request.GET.get('product_profile_id'))
    product_profile = get_object_or_404(ProductProfile, id=product_profile_id)
    product_customer_criteria = ProductCustomerCriteria.objects.filter(
                                product_profile=product_profile).first()
    product_line = ProductLine.objects.filter(product_profile=product_profile).first()
    product_lookup = ProductLookup.objects.filter(product_profile=product_profile,
                                                  is_active=True)

    response_data['product_profile'] = json.loads(serializers.serialize('json', [product_profile]))[0]
    response_data['product_customer_criteria'] = json.loads(serializers.serialize(
                                                 'json', [product_customer_criteria]))[0]
    response_data['product_line'] = json.loads(serializers.serialize('json', [product_line]))[0]
    response_data['product_lookup_list'] = json.loads(serializers.serialize('json', product_lookup))
    response_data['JOB_TYPE_CHOICES'] = JOB_TYPE_CHOICES
    response_data['JOB_INDUSTRY_CHOICES'] = JOB_INDUSTRY_CHOICES
    response_data['JOB_DESCRIPTION_CHOICES'] = JOB_DESCRIPTION_CHOICES
    response_data['CREDIT_SCORE_CHOICES'] = CREDIT_SCORE_CHOICES
    response_data['PAYMENT_FREQ_CHOICES'] = PAYMENT_FREQUENCY_CHOICES

    return HttpResponse(
        json.dumps(response_data, indent=2),
        content_type="application/json"
    )


def ajax_update_detail(request):
    if request.method != 'POST':
        return HttpResponseNotAllowed(
            json.dumps({
                "message": "method %s not allowed" % request.method,
            }),
            content_type="application/json"
        )

    data = request.POST.dict()
    product_profile_data = get_cleaned_data(json.loads(data['product_profile']))
    customer_criteria_data = get_cleaned_data(json.loads(data['customer_criteria']))
    product_line_data = json.loads(data['product_line'])

    try:
        with transaction.atomic():
            product_profile = ProductProfile(**product_profile_data)
            product_profile.clean()
            product_profile.save()
            # assign product profile object to Product Customer Criteria
            customer_criteria_data['product_profile'] = product_profile
            product_line_data['product_profile'] = product_profile

            product_customer_criteria = ProductCustomerCriteria(**customer_criteria_data)
            product_customer_criteria.clean()
            product_customer_criteria.save()

            product_line = ProductLine(**product_line_data)
            product_line.save()

            # Matching Product Lookup old with new generated Product Lookup
            product_lookup_list_old = ProductLookup.objects.filter(
                product_profile=product_profile)
            product_lookup_list_new = generate_product_lookup(product_profile, product_line)
            pl_names_new = [pl_new['product_name'] for pl_new in product_lookup_list_new]
            matching_pl = {}

            for product_lookup_old in product_lookup_list_old:
                if product_lookup_old.product_name in pl_names_new:
                    matching_pl[product_lookup_old.product_name] = {
                        'product_code': product_lookup_old.product_code,
                        'cdate': product_lookup_old.cdate
                    }
                else:
                    product_lookup_old.is_active = False
                    product_lookup_old.save()

            for product_lookup_new in product_lookup_list_new:
                product_name_new = product_lookup_new['product_name']
                if product_name_new in matching_pl:
                    product_lookup_new['product_code'] = matching_pl[product_name_new]['product_code']
                    product_lookup_new['cdate'] = matching_pl[product_name_new]['cdate']
                    product_lookup_new['is_active'] = True
                product_lookup = ProductLookup(**product_lookup_new)
                product_lookup.save()

        url = reverse('product_profile:details', kwargs={'pk': product_profile.id})
        return HttpResponse(
            json.dumps({'url': url}),
            content_type="application/json")

    except Exception as e:
        return HttpResponseBadRequest(content=e)


def ajax_add(request):
    if request.method != 'POST':
        return HttpResponseNotAllowed(
            json.dumps({
                "message": "method %s not allowed" % request.method,
            }),
            content_type="application/json"
        )

    data = request.POST.dict()
    product_profile_data = get_cleaned_data(json.loads(data['product_profile']))
    customer_criteria_data = get_cleaned_data(json.loads(data['customer_criteria']))

    try:
        with transaction.atomic():
            product_profile = ProductProfile(**product_profile_data)
            product_profile.clean()
            product_profile.save()
            customer_criteria_data['product_profile'] = product_profile
            product_customer_criteria = ProductCustomerCriteria(**customer_criteria_data)
            product_customer_criteria.clean()
            product_customer_criteria.save()
            product_line = ProductLine.objects.create(
                product_line_code=product_profile.code,
                product_line_type=product_profile.name,
                min_amount=product_profile.min_amount,
                max_amount=product_profile.max_amount,
                min_duration=product_profile.min_duration,
                max_duration=product_profile.max_duration,
                min_interest_rate=product_profile.min_interest_rate,
                max_interest_rate=product_profile.max_interest_rate,
                payment_frequency=product_profile.payment_frequency,
                product_profile=product_profile
            )
            product_lookup_list = generate_product_lookup(product_profile, product_line)
            for product_lookup_data in product_lookup_list:
                product_lookup = ProductLookup(**product_lookup_data)
                product_lookup.save()

        url = reverse('product_profile:details', kwargs={'pk': product_profile.id})
        return HttpResponse(
            json.dumps({'url': url}),
            content_type="application/json"
        )

    except Exception as e:
        return HttpResponseBadRequest(content=e)
