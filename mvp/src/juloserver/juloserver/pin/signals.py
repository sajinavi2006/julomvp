from django.dispatch import Signal

from juloserver.fraud_security.signals import ato_change_device_on_login_success_handler

login_success = Signal()
login_success.connect(ato_change_device_on_login_success_handler)
