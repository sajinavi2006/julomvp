from django.test.utils import override_settings
from rest_framework.test import APITestCase
from rest_framework import status


@override_settings(CELERY_ALWAYS_EAGER=True)
@override_settings(BROKER_BACKEND='memory')
@override_settings(CELERY_EAGER_PROPAGATES_EXCEPTIONS=True)
class TestEmailEventCallbackView(APITestCase):

    def test_store_email_delivery_status_successfully(self):
        data = [{
            "email": "example@test.com",
            "timestamp": 1513299569,
            "smtp-id": "<14c5d75ce93.dfd.64b469@ismtpd-555>",
            "event": "group_resubscribe",
            "category": "cat facts",
            "sg_event_id": "w_u0vJhLT-OFfprar5N93g==",
            "sg_message_id": "14c5d75ce93.dfd.64b469.filter0001.16648.5515E0B88.0",
            "useragent": "Mozilla/4.0 (compatible; MSIE 6.1; Windows XP; .NET CLR 1.1.4322; .NET CLR 2.0.50727)",
            "ip": "255.255.255.255",
            "url": "http://www.sendgrid.com/",
            "asm_group_id": 10
        }]
        response = self.client.post('/api/integration/v1/callbacks/email', data, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_with_bounce_data(self):
        """
        Issue: https://sentry.io/organizations/juloeng/issues/3222908702
        """
        data = [
            {
                "email": "random@email.com",
                "event": "delivered",
                "ip": "1.1.1.1",
                "response": "220 2.0.0 OK  1654299774 f2-20020adfdb42000000b023421fb801bsi18258208wrj.458 - gsmtp",
                "sg_event_id": "ZGVsaXZlcmVkLTAtMTgxODgzN4252laTNWUU5TSGlYZ09KTlF3SjVXUS0w",
                "sg_message_id": "niei3VQNSHi23423JNQwJ5WQ.filterd23cv-66679f88fc-52lcm-1-629F305C-11.0",
                "smtp-id": "<niei3VQNSHiXg32423@geopod-ismtpd-4-1>",
                "timestamp": 1654599775,
                "tls": 1
            },
            {
                "bounce_classification": "Mailbox Unavailable",
                "email": "random2@email.com",
                "event": "bounce",
                "reason": "Storage quota exceeded",
                "sg_event_id": "Ym91bmNlLTE4123123TYyZGI2ODEwLWU4MTFlYy04ZThiLWE4YmEzMTg0NGVhNg",
                "status": "5.0.0",
                "timestamp": 1654599776,
                "type": "blocked"
            },
        ]
        response = self.client.post('/api/integration/v1/callbacks/email', data, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
