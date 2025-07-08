import operator
import logging
from itertools import chain
from django.conf import settings
from django.db.models import F, Value, CharField

from django.utils import timezone
from django.db.models import Q
from django.views.generic import ListView, DetailView

#set decorator for login required
from object import julo_login_required, julo_login_required_exclude
from object import julo_login_req_group_class, julo_login_required_multigroup
from juloserver.julo.models import Payment, StatusLookup
from functools import reduce


logger = logging.getLogger(__name__)


PROJECT_URL = getattr(settings, 'PROJECT_URL', 'http://api.julofinance.com')


@julo_login_required
@julo_login_required_exclude(['bo_credit_analyst'])
class PartialPaymentListView(ListView):
    model = Payment
    paginate_by = 50
    template_name = 'object/payment/list_partial_payment.html'

    def get_queryset(self):
        # print "get_queryset"
        qs = super(PartialPaymentListView, self).get_queryset()
        qs = qs.order_by('loan', '-payment_number', '-cdate')

        self.q = self.request.GET.get('q', '').strip()
        # Fetching information for display
        if isinstance(self.q, str) and self.q:
            qs = qs.filter(reduce(operator.or_,
                [
                    Q(**{('%s__icontains' % 'loan__application__fullname'): self.q}),
                    Q(**{('%s__icontains' % 'loan__application__ktp'): self.q}),
                    Q(**{('%s__icontains' % 'loan__application__mobile_phone_1'): self.q}),
                    Q(**{('%s__icontains' % 'id'): self.q}),
                    Q(**{('%s__icontains' % 'payment_status__status_code'): self.q}),
                    Q(**{('%s__icontains' % 'loan__application__email'): self.q})
                ]))

        return qs

    def get_context_data(self, **kwargs):
        # print "get_context_data"
        # print "self.kwargs['status']: ", self.kwargs['status']
        context = super(PartialPaymentListView, self).get_context_data(**kwargs)
        self.q = self.request.GET.get('q', '').strip()
        context['extra_context'] = {'q': self.q},
        context['q_value'] = self.q,
        context['results_per_page'] = self.paginate_by
        context['PROJECT_URL'] = settings.PROJECT_URL
        get_copy = self.request.GET.copy()
        parameters = get_copy.pop('page', True) and get_copy.urlencode()
        # print "parameters: ", parameters
        context['parameters'] = parameters
        return context


@julo_login_required
@julo_login_required_multigroup(['admin_full'])
class PartialPaymenDetailView(DetailView):
    model = Payment
    template_name='object/payment/detail_partial_payment.html'

    def get_context_data(self, **kwargs):
        self.object = self.get_object()
        payment_event = self.object.paymentevent_set.all().annotate(
            type_data=Value('Event', output_field=CharField()))
        payment_note = self.object.paymentnote_set.all().annotate(
            type_data=Value('Notes', output_field=CharField()))
        # result_list = list(chain(app_histories, app_notes))

        event_note_list = sorted(
            chain(payment_event, payment_note),
            key=lambda instance: instance.cdate, reverse=True)

        context = super(PartialPaymenDetailView, self).get_context_data(**kwargs)
        context['now'] = timezone.now()
        context['event_note_list'] = event_note_list
        return context
