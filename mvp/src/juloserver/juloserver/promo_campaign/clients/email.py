from builtins import object
from django.template.loader import render_to_string
from ..utils import (save_email_history)


class PromoEmailClient(object):
    @save_email_history
    def send_ramadan_email_promo(self, cust_info, payment_info, template_info):
        title = 'Bapak/Ibu'
        customer = cust_info['customer']
        gender = customer.gender

        if gender == 'Pria':
            title = 'Bapak'
        elif gender == 'Wanita':
            title = 'Ibu'

        context = {
            'fullname_with_title': title + ' ' + customer.fullname,
            'due_date': payment_info['due_date'],
            'payment_link': payment_info['payment_link'],
            'terms_link': payment_info['terms_link'],
            'payments': payment_info['payments'] if 'payments' in payment_info else []
        }

        template = template_info['template']
        msg = render_to_string(template, context)
        subject = template_info['subject']
        email_to = customer.email
        email_from = 'promotion@julo.co.id '
        name_from = 'JULO'
        reply_to = 'promotion@julo.co.id'

        status, body, headers = self.send_email(subject,
                                                msg,
                                                email_to,
                                                email_from=email_from,
                                                email_cc=None,
                                                name_from=name_from,
                                                reply_to=reply_to)

        return dict(
            status=status,
            headers=headers,
            subject=subject,
            msg=msg,
            email=email_to,
            template_code=template_info['template_code'],
            customer=customer,
            application=cust_info['application']
        )
