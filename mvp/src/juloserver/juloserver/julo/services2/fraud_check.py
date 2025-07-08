import logging
from juloserver.julo.models import VPNDetection
from juloserver.julo.clients.ipinfo import get_ipinfo_client

from admin_honeypot.signals import honeypot
from django.template.loader import render_to_string
from django.core.urlresolvers import reverse
from django.conf import settings

from juloserver.julocore.utils import get_client_ip
from juloserver.monitors.notifications import get_slack_bot_client

logger = logging.getLogger(__name__)
ipinfo_client = get_ipinfo_client()


def get_client_ip_from_request(request, path=None):
    ip_address = get_client_ip(request)
    user = request.user

    if ip_address:
        logger.info({
            'action': 'get_client_ip_address',
            'path': path,
            'ip_address': ip_address,
            'user': user
        })
    return ip_address


def check_suspicious_ip(ip_address):
    vpn_detect = VPNDetection.objects.filter(ip_address=ip_address).last()
    if vpn_detect:
        return vpn_detect.is_vpn_detected is True

    is_vpn_detected = False
    ip_details = ipinfo_client.get_ip_info_detail(ip_address)
    for k, v in ip_details['privacy'].items():
        if v:
            is_vpn_detected = True

    VPNDetection.objects.create(
        ip_address=ip_address, extra_data=ip_details, is_vpn_detected=is_vpn_detected
    )

    return is_vpn_detected


def admin_honeypot_notify_slack(instance, request, **kwargs):
    path = reverse('admin:admin_honeypot_loginattempt_change', args=(instance.pk,))
    admin_detail_url = '{0}{1}'.format(settings.PROJECT_URL, path)

    # update ip_address as its not correct user IP
    ip_address = get_client_ip_from_request(request)
    if ip_address is None:
        if 'HTTP_X_FORWARDED_FOR' in request.META:
            ip_address = request.META['HTTP_X_FORWARDED_FOR'].split(",")[0].strip()
    if ip_address is not None:
            instance.ip_address = ip_address
            instance.save()

    context = {
        'request': request,
        'instance': instance,
        'admin_detail_url': admin_detail_url,
    }
    subject = render_to_string('admin_honeypot/email_subject.txt', context).strip()
    message = render_to_string('admin_honeypot/email_message.txt', context).strip()

    if 'honeypot' in subject:
        if settings.ENVIRONMENT != 'prod':
            return

        get_slack_bot_client().api_call("chat.postMessage",
                                        channel=settings.SLACK_SECURITY_ALERTS,
                                        text=message)
        logger.info({
            'action': 'admin_honeypot_notify_slack',
            'message': message
        })

if getattr(settings, 'ADMIN_HONEYPOT_SLACK_ALERT', True):
    honeypot.connect(admin_honeypot_notify_slack)
