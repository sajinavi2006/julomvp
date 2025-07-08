from __future__ import print_function
from future import standard_library
standard_library.install_aliases()
from builtins import str
from channels import Group
import threading
import time
from .models import NexmoUser, NexmoConversation
import urllib.parse
from datetime import datetime
from django.utils import timezone
import os
import calendar
import requests
from base64 import urlsafe_b64encode
from jose import jwt
from django.conf import settings
from django.core.urlresolvers import reverse
import logging, sys
from django.db import connections

logger = logging.getLogger(__name__)
logger.addHandler(logging.StreamHandler(sys.stdout))


def make_outbound_call(phone_number, user_id):
    """
    initiate call with nexmo
    """
    answer_url = reverse('nexmo-answer-url', kwargs={'userid': user_id})
    answer_url_endpoint = settings.BASE_URL + answer_url
    params = {
        "to": [{
            "type": "phone",
            "number": phone_number
        }],
        "from": {
            "type": "phone",
            "number": "6285574670087"
        },
        "answer_url": [
            answer_url_endpoint
        ],
        "event_url":[
            settings.BASE_URL + "/nexmo_poc/beta/call_status/"
        ]
    }

    url = "https://api-sg-1.nexmo.com/v1/calls"
    headers = get_headers()
    response = requests.post(url, headers=headers, json=params)
    return response.json()

def get_headers():
    d = datetime.utcnow()
    voice_application_id = "562d1229-3acd-4bbf-a4c6-5b18eb3d1ff8"

    token_payload = {
        "iat": calendar.timegm(d.utctimetuple()),  # issued at
        "application_id": voice_application_id,  # application id
        "jti": urlsafe_b64encode(os.urandom(64)).decode('utf-8')
    }

    headers = {'User-Agent': 'nexmo-python/2.0.0/2.7.12+'}

    token = jwt.encode(claims=token_payload, key=settings.NEXMO_PRIVATE_KEY_POC, algorithm='RS256')

    return dict(headers, Authorization='Bearer ' + token)


def is_user_available(nexmo_id):
    user = NexmoUser.objects.get(nexmo_id=nexmo_id)
    if user.is_oncall:
        return False
    url =  "https://api-sg-1.nexmo.com/beta/users/%s/conversations" % nexmo_id
    headers = get_headers()
    response = requests.get(url, headers=headers)
    logger.info({
        'log_from': "POC nexmo",
        'type': "================response=====================",
        'response': response.json()
    })
    if len(response.json()) == 0:
        return True
    else:
        return False

t = False
def periodic():
    global t
    # conversations = NexmoConversation.objects.filter(is_executed=False)
    conn = connections['default']
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM nexmo_conversation WHERE is_executed=%s' % False)
    conversations = cursor.fetchall()

    if conversations:
        logger.info({
            'log_from': "POC nexmo",
            'type': "================conversations found=====================",
        })
        for conversation in conversations:
            logger.info({
                'log_from': "POC nexmo",
                'type': "================conversations loop=====================",
            })
            con_ts = timezone.now()
            Group('stocks').send({'text': 'ping'})
            time.sleep(5)
            # users = NexmoUser.objects.filter(last_seen__gt=con_ts)
            cursor.execute("SELECT * FROM nexmo_user WHERE last_seen > '%s'" % con_ts)
            users = cursor.fetchall()
            for user in users:
                logger.info({
                    'log_from': "POC nexmo",
                    'type': "================user loop=====================",
                })
                if is_user_available(user[3]):
                    logger.info({
                        'log_from': "POC nexmo",
                        'type': "================available user found=====================",
                    })
                    response = make_outbound_call(conversation[4], user[2])
                    logger.info({
                        'log_from': "================response from nexmo=====================",
                        'type': response,
                    })

                    if response["status"] == "started":
                        update_user = "UPDATE nexmo_user SET is_oncall=%s WHERE nexmo_user_id=%s" % (True, user[2])
                        cursor.execute(update_user)
                        conn.commit()
                        # user.is_oncall = True
                        # user.save()
                        update_conversation = ("UPDATE nexmo_conversation SET uuid='%s', nexmo_user_id=%s, is_executed=%s "
                                              "WHERE nexmo_conversation_id=%s") % (response["conversation_uuid"],
                                                                                   user[2],
                                                                                   True,
                                                                                   conversation[2])
                        cursor.execute(update_conversation)
                        conn.commit()
                        # conversation.uuid =response["conversation_uuid"]
                        # conversation.agent = user
                        # conversation.is_executed = True
                        # conversation.save()
                        break
                else:
                    continue
    cursor.close()
    connections.close_all()
    threading.Timer(10, periodic).start()
    while not t:
        time.sleep(1)
    print('done')


def ws_message(message):
    message = message.content['text']
    splited_message = message.split("|")
    logger.info({
        'log_from': "POC nexmo",
        'type': "================message received=====================",
    })
    if splited_message[0] == '[ping]':
        logger.info({
            'log_from': "POC nexmo",
            'type': "================user ping message saved=====================",
        })
        user = NexmoUser.objects.get(pk=splited_message[1])
        user.last_seen = timezone.now()
        user.save()

def ws_connect(message):
    params = urllib.parse.parse_qs(message.content['query_string'])
    userid = params.get('userid',('Not Supplied',))[0]
    Group('stocks').add(message.reply_channel)
    # Group('stocks').send({'text': 'connected'})

    user = NexmoUser.objects.get(pk=userid)
    user.is_online = True
    user.save()
    Group('stocks').send({'text': str(user.id) + '|' + user.name + ' (status online)'})
    periodic()


def ws_disconnect(message):
    # Group('stocks').send({'text':  'disconnected'})
    Group('stocks').discard(message.reply_channel)
