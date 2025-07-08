from __future__ import print_function
from __future__ import absolute_import
from builtins import str
from builtins import range
import json
import operator
import hashlib, random

import datetime
import logging
from babel.numbers import parse_number, format_decimal
from dateutil.relativedelta import relativedelta

from django.contrib import messages
from django.views.decorators.csrf import csrf_protect
from django.conf import settings
from django.template.loader import render_to_string
from django.utils.html import strip_tags
from django.core import serializers

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

# from juloserver.julo.models import Payment
from juloserver.julo.exceptions import JuloException
from juloserver.julo.models import Application, StatusLookup, Offer, Payment
from juloserver.julo.models import FacebookData, ApplicationNote, ProductLookup
from juloserver.julo.formulas import compute_adjusted_payment_installment
from juloserver.julo.formulas import get_available_due_dates_by_payday
from juloserver.julo.formulas import get_available_due_dates_by_payday_monthly
from juloserver.julo.formulas import round_rupiah
from juloserver.julo.formulas import compute_payment_installment
from juloserver.julo.statuses import ApplicationStatusCodes

from loan_app.utils import get_list_history
from .forms import OfferSearchForm, NoteForm, OfferForm
from functools import reduce


logger = logging.getLogger(__name__)


PROJECT_URL = getattr(settings, 'PROJECT_URL', 'http://api.julofinance.com')


# ----------------------------- Payment data Start ---------------------------------------


@julo_login_required
@julo_login_required_multigroup(['admin_full', 'bo_data_verifier', 'bo_sd_verifier',
    'document_verifier', 'bo_credit_analyst'])
class OfferListView(ListView):
    model = Offer
    paginate_by = 50 #get_conf("PAGINATION_ROW")
    template_name = 'object/offer/list.html'

    def http_method_not_allowed(self, request, *args, **kwargs):
        # print "http_method_not_allowed"
        return ListView.http_method_not_allowed(self, request, *args, **kwargs)

    def get_template_names(self):
        # print "get_template_names"
        return ListView.get_template_names(self)

    def get_queryset(self):
        self.qs = super(OfferListView, self).get_queryset()
        self.qs = self.qs.order_by('application', 'offer_number','-udate')

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

            if isinstance(self.search_q, str) and self.search_q:
                self.qs = self.qs.filter(reduce(operator.or_,
                    [
                        Q(**{('%s__icontains' % 'application__id'): self.search_q}),
                        Q(**{('%s__icontains' % 'application__fullname'): self.search_q}),
                        Q(**{('%s__icontains' % 'application__ktp'): self.search_q}),
                        Q(**{('%s__icontains' % 'application__mobile_phone_1'): self.search_q}),
                        Q(**{('%s__icontains' % 'id'): self.search_q}),
                        Q(**{('%s__icontains' % 'product__product_name'): self.search_q}),
                        Q(**{('%s__icontains' % 'application__email'): self.search_q})
                    ]))

            if(self.status_app):
                self.qs = self.qs.filter(application__application_status__status_code=self.status_app)

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
        return ListView.get_context_object_name(self, object_list)

    def get_context_data(self, **kwargs):
        context = super(OfferListView, self).get_context_data(**kwargs)
        if self.request.method == 'GET':
            context['form_search'] = OfferSearchForm(self.request.GET.copy())
        else:
            context['form_search'] = OfferSearchForm()
        context['results_per_page'] = self.paginate_by
        context['obj_search'] = None
        context['status_show'] = self.status_app
        context['err_msg'] = self.err_message_here
        context['PROJECT_URL'] = settings.PROJECT_URL
        get_copy = self.request.GET.copy()
        parameters = get_copy.pop('page', True) and get_copy.urlencode()
        context['parameters'] = parameters
        return context

    def get(self, request, *args, **kwargs):
        return ListView.get(self, request, *args, **kwargs)

    def render_to_response(self, context, **response_kwargs):
        rend_here = super(OfferListView, self).render_to_response(context, **response_kwargs)
        return rend_here


def re_configure_req_post(request_post):
    if 'form2-loan_amount_offer' in request_post:
        request_post['form2-loan_amount_offer'] = parse_number(request_post['form2-loan_amount_offer'], locale='id_ID')
    if 'form2-loan_duration_offer' in request_post:
        request_post['form2-loan_duration_offer'] = parse_number(request_post['form2-loan_duration_offer'], locale='id_ID')
    if 'form2-installment_amount_offer' in request_post:
        request_post['form2-installment_amount_offer'] = parse_number(request_post['form2-installment_amount_offer'], locale='id_ID')
    return request_post


@julo_login_required
@julo_login_required_multigroup(['admin_full', 'bo_data_verifier', 'bo_sd_verifier',
    'document_verifier', 'bo_credit_analyst'])
def details(request, pk):
    # check if there is statuslookup which matches the statuslookup (if not then display 404)
    offer_obj = get_object_or_404(Offer, id=pk)
    status_current = offer_obj.application.application_status.status_code
    payday = offer_obj.application.payday
    offerday = datetime.date.today()
    product_type = offer_obj.application.product_line.product_line_type

    template_name ='object/offer/details.html'

    if request.method == 'POST':
        form = NoteForm(request.POST)
        #re-configure request.POST for loan
        request_POST = re_configure_req_post(request.POST.copy())
        form_offer = OfferForm(request_POST, instance=offer_obj,
                            prefix='form2')
        if 'simpan_note' in request.POST:
            flag_notes = True
            if form.is_valid():
                notes = form.cleaned_data['notes']
                if notes:
                    user_id = request.user.id if request.user else None
                    app_note = ApplicationNote.objects.create(
                        note_text=notes,
                        application_id=offer_obj.application.id,
                        added_by_id=user_id,
                    )
                    logger.info(
                        {
                            'offers:details': notes,
                            'app_note': app_note,
                        }
                    )

                    url = reverse('offers:details', kwargs={'pk': offer_obj.id })
                    return redirect(url)
                else:
                    flag_notes = False
            else:
                flag_notes = False

            if not flag_notes:
                #there is an error
                err_msg = """
                    Catatan Tidak Boleh dikosongkan!!!
                """
                logger.info({
                    'offer_id': offer_obj.id,
                    'error': err_msg
                })
                messages.error(request, err_msg)

        if 'ubah_offer' in request.POST:
            first_payment_date_obj = request_POST['form2-first_payment_date']
            first_payment_datetime = datetime.datetime.strptime(first_payment_date_obj.strip(),"%d-%m-%Y")
            first_installment_amount = request_POST['form2-first_installment_amount'].replace('.','')
            request_POST['form2-first_payment_date'] = first_payment_datetime.date()
            request_POST['form2-first_installment_amount'] = first_installment_amount
            if status_current >= ApplicationStatusCodes.OFFER_ACCEPTED_BY_CUSTOMER:
                err_msg = """
                    Tidak dapat merubah offer karena sudah ada loan.
                """
                messages.error(request, err_msg)
            if status_current < ApplicationStatusCodes.OFFER_ACCEPTED_BY_CUSTOMER:
                if form_offer.is_valid():
                    print("form_offer.is_valid")
                    form_offer.save()
                    offer_obj.is_approved = True
                    offer_obj.save()

                    url = reverse('offers:details', kwargs={'pk': offer_obj.id })
                    return redirect(url)
                else:
                    #there is an error
                    err_msg = """
                        Masih terdapat kesalahan input, mohon diperbaiki dahulu!!!
                    """

                    for field in form_offer:
                        if field.errors:
                            # print dir(form_offer.fields[field.name]), field.name
                            if form_offer.fields[field.name].error_messages['required']:
                                err_field = form_offer.fields[field.name].error_messages['required']
                            elif form_offer.fields[field.name].error_messages['invalid']:
                                err_field = form_offer.fields[field.name].error_messages['invalid']
                            else:
                                "unknown error!"
                            err_msg += ": %s - err_msg: %s" % (
                                field.name, err_field)

                    logger.info({
                        'app_id': offer_obj.application.id,
                        'error': err_msg
                    })
                    messages.error(request, err_msg)

    else:
        form = NoteForm()
        form_offer = OfferForm(instance=offer_obj, prefix='form2')

    history_note_list = get_list_history(offer_obj.application)
    #edit offer status check
    flag_edit_offer = False
    if 130 <= status_current < 170:
        flag_edit_offer = True

    # #get fb data
    try:
        fb_obj = offer_obj.application.facebook_data
    except FacebookData.DoesNotExist:
        fb_obj = None
    #get loan data and order by offer_number
    offer_set_objects = offer_obj.application.offer_set.all().order_by("offer_number")

    return render(
        request,
        template_name,
        {
            'form': form,
            'form_offer': form_offer,
            'offer_obj': offer_obj,
            'fb_obj': fb_obj,
            'status_current': status_current,
            'history_note_list': history_note_list,
            'flag_edit_offer': flag_edit_offer,
            'datetime_now': timezone.now(),
            'offer_set_objects': offer_set_objects,
            'payday': payday,
            'offerday': offerday,
            'product_type': product_type,
        }
    )

# ----------------------------- Payment Status END  ----------------------------


def set_unavailable_due_dates(payday, offerday, product_line_code):
    disable_days = []
    today_date = datetime.date.today()
    available_due_dates = get_available_due_dates_by_payday(payday, offerday, product_line_code)
    unavailable_due_dates = []

    for days in range(0, 60):
        date = today_date + relativedelta(days=days)
        if date not in available_due_dates:
            unavailable_due_dates.append(date)

    for due_date in unavailable_due_dates:
        day = due_date.day
        month = due_date.month
        year = due_date.year
        unavailable_date = str(day)+"-"+str(month)+"-"+str(year)
        disable_days.append(unavailable_date)
    return disable_days

def set_unavailable_due_dates_by_payment(payday, due_date, product_line_code):
    disable_days = []
    available_due_dates = get_available_due_dates_by_payday_monthly(payday, due_date, product_line_code)
    unavailable_due_dates = []

    for days in range(0, 120):
        date = due_date + relativedelta(days=days)
        if date not in available_due_dates:
            unavailable_due_dates.append(date)

    for due_date in unavailable_due_dates:
        day = due_date.day
        month = due_date.month
        year = due_date.year
        unavailable_date = str(day)+"-"+str(month)+"-"+str(year)
        disable_days.append(unavailable_date)
    return disable_days

# ----------------------------- AJAX Status START  -----------------------------


@csrf_protect
def ajax_compute_installment(request):
    """
    """
    response_data = {}

    if request.method == 'GET':

        product_id = parse_number(request.GET.get('product'), locale='id_ID')
        loan_amount = parse_number(request.GET.get('loan_amount'), locale='id_ID')
        loan_duration = parse_number(request.GET.get('loan_duration'), locale='id_ID')
        try:
            product_obj = ProductLookup.objects.get(pk=product_id)
        except ProductLookup.DoesNotExist:
            product_obj = None

        if product_obj and loan_amount and loan_duration:
            try:
                principal, interest, installment = compute_payment_installment(
                    loan_amount, loan_duration, product_obj.monthly_interest_rate)
                ret_installment = installment
                response_data['result'] = 'successful!'
                response_data['reason'] = "%s" % (format_decimal(ret_installment, locale='id_ID'))
            except Exception as e:
                response_data['result'] = 'failed!'
                response_data['reason'] = "ERR: %s " % e

        else:
            response_data['result'] = 'failed!'
            response_data['reason'] = 'Product object not exist'

        return HttpResponse(
            json.dumps(response_data),
            content_type="application/json"
        )
    else:
        return HttpResponse(
            json.dumps({"reason": "this isn't happening",
                'result': "nok"}),
            content_type="application/json"
        )

# ----------------------------- AJAX Status END  -------------------------------


def simulated_first_installment(request):
    if request.method == 'GET':
        product = ProductLookup.objects.get(pk=int(request.GET.get('product', '')))

        response_data = {}

        try:
            new_due_date = request.GET.get('new_due_date', '')
            new_due_date_obj = datetime.datetime.strptime(new_due_date,"%d-%m-%Y").date()
            loan_amount = request.GET.get('loan_amount', '').replace('.','')
            loan_duration = request.GET.get('loan_duration', '')

        except Exception as e:
            logger.warning({
                'status': 'ajax - simulated_first_installment',
                'new_due_date': new_due_date,
                'product': product
            })
            return HttpResponse(
                json.dumps({"reason": "exception on calculate days_extra",
                    'result': "nok"}),
                content_type="application/json"
            )

        # simulate recalculation for first payment installment
        try:
            _, _, new_first_payment_installment = compute_adjusted_payment_installment(
                int(loan_amount), int(loan_duration),
                product.monthly_interest_rate, datetime.date.today(), new_due_date_obj)
        except Exception as e:
            logger.warning({
                'status': 'ajax - simulate_adjusted_payment_installment',
                'exception': e,
                'product': product
            })
            return HttpResponse(
                json.dumps({"reason": "exception on simulate_adjusted_payment_installment",
                    'result': "nok"}),
                content_type="application/json"
            )

        response_data['result'] = 'successful!'
        response_data['output'] = "%s" % (format_decimal(new_first_payment_installment, locale='id_ID'))
        response_data['reason'] = "ALL OKE"

        return HttpResponse(
            json.dumps(response_data),
            content_type="application/json"
        )
    else:
        return HttpResponse(
            json.dumps({"reason": "this isn't happening",
                'result': "nok"}),
            content_type="application/json"
        )

@csrf_protect
def ajax_unavailable_due_dates(request):
    if request.method == 'GET':
        offer_obj = Offer.objects.get_or_none(pk=int(request.GET.get('offer_id',0)))
        payday = offer_obj.application.payday
        offerday = datetime.date.today()
        product_line_code = offer_obj.application.product_line.product_line_code
        start = str(offerday.day) + '-'+str(offerday.month) + '-' + str(offerday.year)

        response_data = {}

        try:
            unavailable_dates = set_unavailable_due_dates(payday, offerday, product_line_code)
        except Exception as e:
            logger.warning({
                'status': 'ajax - get available due_dates',
                'exception': e,
                'offer': offer_obj
            })
            return HttpResponse(
                json.dumps({"reason": "exception on get available due_dates",
                    'result': "nok"}),
                content_type="application/json"
            )

        response_data['result'] = 'successful!'
        response_data['output'] = unavailable_dates if unavailable_dates else 'none'
        response_data['start'] = start
        response_data['end'] = unavailable_dates[len(unavailable_dates)-1] if unavailable_dates else 'none'
        response_data['reason'] = "ALL OKE"

        return HttpResponse(
            json.dumps(response_data),
            content_type="application/json"
        )
    else:
        return HttpResponse(
            json.dumps({"reason": "this isn't happening",
                'result': "nok"}),
            content_type="application/json"
        )

@csrf_protect
def ajax_get_unavailable_due_dates_by_application(request):
    if request.method == 'GET':
        application = Application.objects.get_or_none(
            id=int(request.GET.get('application_id', 0)))
        payday = application.payday
        offerday = datetime.date.today()
        product_line_code = application.product_line.product_line_code

        start = str(offerday.day) + '-' + str(offerday.month) + '-' + str(
            offerday.year)

        response_data = {}

        try:
            unavailable_dates = set_unavailable_due_dates(
                payday, offerday, product_line_code)
        except Exception as e:
            logger.warning({
                'status': 'ajax - get available due_dates',
                'exception': e,
                'application': application
            })
            return HttpResponse(
                json.dumps({"reason": "exception on get available due_dates",
                            'result': "nok"}),
                content_type="application/json"
            )

        response_data['result'] = 'successful!'
        response_data[
            'output'] = unavailable_dates if unavailable_dates else 'none'
        response_data['start'] = start
        response_data['end'] = unavailable_dates[
            len(unavailable_dates) - 1] if unavailable_dates else 'none'
        response_data['reason'] = "ALL OKE"

        return HttpResponse(
            json.dumps(response_data),
            content_type="application/json"
        )
    else:
        return HttpResponse(
            json.dumps({"reason": "this isn't happening",
                        'result': "nok"}),
            content_type="application/json"
        )

@csrf_protect
def ajax_get_unavailable_due_dates_by_payment(request):
    if request.method == 'GET':
        payment = Payment.objects.get_or_none(
            id=int(request.GET.get('payment_id', 0)))
        if not payment:
            return HttpResponse(
                json.dumps({"reason": "payment not found",
                            'result': "nok"}),
                content_type="application/json"
            )
        payday = payment.loan.application.payday
        due_date = payment.due_date
        product_line_code = payment.loan.application.product_line.product_line_code

        start = str(due_date.day) + '-' + str(due_date.month) + '-' + str(
            due_date.year)
        response_data = {}

        try:
            unavailable_dates = set_unavailable_due_dates_by_payment(
                payday, due_date, product_line_code)
        except Exception as e:
            logger.warning({
                'status': 'ajax - get available due_dates',
                'exception': e,
                'application': payment
            })
            return HttpResponse(
                json.dumps({"reason": "exception on get available due_dates",
                            'result': "nok"}),
                content_type="application/json"
            )
        response_data['result'] = 'successful!'
        response_data[
            'output'] = unavailable_dates if unavailable_dates else 'none'
        response_data['start'] = start
        response_data['end'] = unavailable_dates[
            len(unavailable_dates) - 1] if unavailable_dates else 'none'
        response_data['reason'] = "ALL OKE"

        return HttpResponse(
            json.dumps(response_data),
            content_type="application/json"
        )
    else:
        return HttpResponse(
            json.dumps({"reason": "this isn't happening",
                        'result': "nok"}),
            content_type="application/json"
        )
