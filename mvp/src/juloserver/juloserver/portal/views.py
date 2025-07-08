from __future__ import absolute_import

import sys

from django import forms
from django.contrib.auth import logout
from django.contrib.auth.forms import AuthenticationForm
from django.forms.widgets import PasswordInput, TextInput
from django.shortcuts import render, render_to_response
from django.template import RequestContext

from .object.dashboard.views import index as dashboard_index


def custom_500(request):
    exception_type, exception_value, tb = sys.exc_info()
    return render(
        request,
        'custom_500.html',
        {
            "exception_type": exception_type.__name__,
            "exception_value": exception_value,
        },
        status=500,
    )


def contactus(request):
    return render(request, 'main/contact_us.html')


def about_us(request):
    return render(request, 'main/about_us.html')


def promotions(request):
    return render(request, 'main/promotions.html')


def faq(request):
    return render(request, 'main/faq.html')


def welcome(request):
    return dashboard_index(request)


class RFPAuthForm(AuthenticationForm):
    username = forms.CharField(
        widget=TextInput(attrs={'class': 'form-control input-lg', 'placeholder': 'Username'})
    )
    password = forms.CharField(
        widget=PasswordInput(attrs={'class': 'form-control input-lg', 'placeholder': 'Password'})
    )


def login_view(request):
    form = RFPAuthForm(request)
    return render_to_response(
        "auth/login.html", {'form': form}, context_instance=RequestContext(request)
    )


def logout_view(request):
    logout(request)
    # Redirect to a success page.
    return welcome(request)


def empty(request):
    return render_to_response('main/102.html', context_instance=RequestContext(request))
