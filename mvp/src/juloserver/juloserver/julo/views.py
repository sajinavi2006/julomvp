from builtins import str
from builtins import object
import os


from django.http import HttpResponse, HttpResponseRedirect, JsonResponse
from django.template import RequestContext, loader
from juloserver.julo.models import (
    Workflow,
    Image,
    NotificationTemplate,
    Customer,
)
from django.http import HttpResponseRedirect
from django.shortcuts import render_to_response,redirect
from django.shortcuts import render
from django.template import RequestContext
from django.contrib.auth import authenticate, login, logout
from juloserver.julo.utils import construct_remote_filepath, upload_file_to_oss
from django.conf import settings
from django import forms
from .clients.pn import JuloPNClient
from ..portal.core import functions
from django.contrib import messages
from juloserver.julo.clients import get_julo_pn_client


def workflow_diagram(request):
    workflow_id = request.GET.get('workflow_id')
    workflow = Workflow.objects.get_or_none(pk=workflow_id)
    template = loader.get_template('custom_admin/flowchart.html')
    last_diagrams = []
    diagrams =[]
    if workflow:
        status_paths = workflow.workflowstatuspath_set.all().order_by('status_previous')
        unique_previous_statuses = list(set(list([z.status_previous for z in status_paths])))
        unique_previous_statuses.sort()
        for counter, path in enumerate(status_paths):
            arrow = "-->" if path.type == "correctional" else "->"
            dest_diagram = diagrams
            # diag_position = "normal"
            if counter > 0:
                position = unique_previous_statuses.index(path.status_previous)
                if position < len(unique_previous_statuses)-1:
                    next_hop =  position + 1
                    if path.status_next > unique_previous_statuses[next_hop]:
                        dest_diagram = last_diagrams
                        # diag_position = "last"
            item = {'counter': path.status_previous, 'text': "%s%s%s: %s\\n" %(path.status_previous, arrow, path.status_next, path.type)}
            # if diag_position == "normal":
            #     if last_diagrams:
            #         if item['counter'] > min(last_diagrams)['counter']:
            #             dest_diagram.append(last_diagrams.pop(last_diagrams.index(min(last_diagrams))))
            dest_diagram.append(item)
    context = RequestContext(request, {
        "diagrams": diagrams + last_diagrams,
        "workflow_name" : workflow.name,
    })
    return HttpResponse(template.render(context))

def login_user(request, template_name='auth/login_theme.html'):
    logout(request)
    username = password = ''
    if request.POST:
        username = request.POST['username']
        password = request.POST['password']
        user = authenticate(username=username, password=password)
        if user is None:
            # Return an 'invalid login' error message.
            return render(request, template_name, {'errors': 'invalid login'})

        if not user.is_active:
            # Return a 'disabled account' error message
            return render(request, template_name, {'next': 'disabled account'})

        login(request, user)
        # Redirect to a success page.
        return HttpResponseRedirect('/')

    return render_to_response(template_name, context_instance=RequestContext(request))

class NotificationTemplateForm(forms.ModelForm):
    class Meta(object):
        model = NotificationTemplate
        fields = [
            'title',
            'body',
            'destination_page',
        ]


class NotificationTemplateSendForm(forms.Form):
    customer_recipients = forms.EmailField(required=True, widget=forms.TextInput(
        attrs={
            'class': 'basicAutoComplete form-control',
            'data-url': "/xgdfat82892ddn/email_autocomplete/",
            'autocomplete': "off"
        }))


def email_autocomplete(request):
    if request.GET.get('q'):
        q = request.GET['q']
        data = Customer.objects.filter(email__startswith=q).values('email')
        json = list(data)
        return JsonResponse(json, safe=False)
    else:
        HttpResponse("No cookies")

def upload_image_notification(image):
    local_path = "image_upload/notifications"
    suffix = 'notif-%s' %(image.image_source)
    uploaded_local = functions.upload_handle_media(image.image, local_path, suffix)

    subfolder = 'notif_' + str(image.image_source)
    _, file_extension = os.path.splitext(image.image.name)
    filename = "%s_%s_%s%s" % (image.image_type, str(image.id), 'ops', file_extension)

    dest_name = '/'.join(['notifications_templates', subfolder, filename])
    upload_file_to_oss(
        settings.OSS_MEDIA_BUCKET,
        settings.MEDIA_ROOT + '/' + local_path + '/' + suffix +'_'+ image.image.name,
        dest_name)
    return dest_name

def notification_template_add(request):
    notif_form = NotificationTemplateForm(request.POST or None)
    template = loader.get_template('custom_admin/notification_template_form.html')
    if request.POST and notif_form.is_valid():
        if notif_form.is_valid():
            redirect_url = '/xgdfat82892ddn/julo/notificationtemplate/'
            try:
                notif_saved = notif_form.save()
                if request.FILES['image']:
                    image = Image()
                    image.image_source = notif_saved.pk
                    image.image_type = 'notification_image_ops'
                    image.save()
                    image.image = request.FILES['image']
                    uploaded_image = upload_image_notification(image)
                    if uploaded_image:
                        image.url = uploaded_image
                        image.save(update_fields=['url'])
                messages.success(request, 'Add Notification Template successfully saved.')
            except:
                messages.error(request, 'Add Notification Template failure saved.')
                redirect_url = '/xgdfat82892ddn/notification_template_add/'
            return redirect(redirect_url)

    context = RequestContext(request, {
        "notif_form": notif_form,
        "form_status": "create"
    })
    return HttpResponse(template.render(context))

def notification_template_update(request, notif_id):
    temp_data = NotificationTemplate.objects.get(pk=notif_id)
    current_image = Image.objects.get(image_source=temp_data.id, image_type='notification_image_ops')
    data = {
        'title': temp_data.title,
        'body': temp_data.body,
        'destination_page': "%s|%s"% (temp_data.click_action, temp_data.destination_page)
    }
    notif_form = NotificationTemplateForm(request.POST or None, initial=data, instance=temp_data)
    template = loader.get_template('custom_admin/notification_template_form.html')
    if request.POST:
        if notif_form.is_valid():
            redirect_url = '/xgdfat82892ddn/julo/notificationtemplate/'
            try:
                notif_form.save()
                if request.POST.get('is_change_image') == 'true':
                    current_image.image = request.FILES['image']
                    uploaded_image = upload_image_notification(current_image)
                    if uploaded_image:
                        current_image.url = uploaded_image
                        current_image.save(update_fields=["url"])
                        messages.success(request, 'Changes successfully saved.')
                else:
                    messages.success(request, 'Changes successfully saved.')
            except:
                messages.error(request, 'Changes Failed saved.')
                redirect_url = '/xgdfat82892ddn/notification_template_update/' + notif_id

            return redirect(redirect_url)

    context = RequestContext(request, {
        "form_status": "update",
        "notif_form" : notif_form,
        'image_url': current_image.image_url,
    })
    return HttpResponse(template.render(context))

def notification_template_send(request, notif_id):
    template = loader.get_template('custom_admin/notification_template_send.html')
    send_form = NotificationTemplateSendForm()
    message = None
    notif = NotificationTemplate.objects.get(pk=notif_id)
    current_image = Image.objects.get(image_source=notif.id, image_type='notification_image_ops')
    if request.POST:
        notif_template = {
            'title': notif.title,
            'body': notif.body,
            'click_action': notif.click_action,
            'destination_page': notif.destination_page,
            'image_url': current_image.notification_image_url,
        }
        email_customers = request.POST.get('customer_recipients').split(';')
        success_email = []
        failed_email = []
        pn = get_julo_pn_client()
        for email in email_customers:
            customer = Customer.objects.get(email=email)
            response = pn.notifications_enhancements_v1(customer, notif_template)
            if response.status_code < 400:
                success_email.append(email)
            else:
                failed_email.append(email)

        if len(success_email) > 0:
            messages.success(request, 'Notification successfully sended to %s' % ", ".join(success_email))
        if len(failed_email) > 0:
            messages.error(request, 'Notification failed sended to %s' % ", ".join(failed_email))
        return redirect('/xgdfat82892ddn/notification_template_send/' + notif_id)

    context = RequestContext(request, {
        "message": message,
        "success": True,
        "notif": notif,
        "image_url": current_image.notification_image_url,
        "send_form": send_form
    })
    return HttpResponse(template.render(context))
