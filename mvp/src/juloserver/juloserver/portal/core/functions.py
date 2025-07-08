from __future__ import print_function

import hashlib
import json
import logging
import os
import random
import urllib.error
import urllib.parse

# import re
import urllib.request
from builtins import object, str, zip
from os.path import join

from django.conf import settings
from django.db import connections, transaction

# import re#, string
from future import standard_library

# from julo_config.models import JuloConfiguration
standard_library.install_aliases()
logger = logging.getLogger(__name__)
KNOWN_FILE_EXTENTIONS = ('csv', 'kml')
JULO_ALLCAPS_NAMES = getattr(settings, 'JULO_ALLCAPS_NAMES', ())

ALLCAPS_NAMES = tuple(set(JULO_ALLCAPS_NAMES).union(set(KNOWN_FILE_EXTENTIONS)))

FILE_UPLOAD_TEMP_DIR = getattr(settings, 'FILE_UPLOAD_TEMP_DIR', 'uploadfile/')


def display_name(name):
    SEPARATOR = ' '
    name = name.replace('_', ' ')
    return SEPARATOR.join(
        [
            word.upper() if word.lower() in ALLCAPS_NAMES else word.title()
            for word in name.split(SEPARATOR)
        ]
    )


def dictfetchall(cursor):
    "Returns all rows from a cursor as a dict"
    desc = cursor.description
    return [dict(list(zip([col[0] for col in desc], row))) for row in cursor.fetchall()]


def execute_sql(db_conn, sql_query):
    try:
        cursor = connections[db_conn].cursor()
        transaction.commit_unless_managed(using=db_conn)

        #        print sql_query
        cursor.execute(sql_query)
        return dictfetchall(cursor)
    except Exception as e:
        return "Error execute_sql : ", e


# def get_conf_value(conf_key):
#     ret_val = None
#     aa = JuloConfiguration.objects.filter(key=conf_key).exclude(status=0)
#     if aa.count()>0:
# #         print "get_conf_value key %s value %s: " % (conf_key, aa)
#         ret_val = aa[0].value
#     else:
#         print "get_conf_value key %s: Not Found"  % (conf_key)
#     return ret_val

# def max_size_conf():
#     max_size = 4
#     aa = JuloConfiguration.objects.filter(key='MAX_SIZE_FILE')
#     if aa.count()>0:
#         print "MAX_SIZE_FILE: " , aa
#         max_size = aa[0].value
#     else:
#         print "MAX_SIZE_FILE: Not Found"
#     return max_size


def make_random_password(
    length=10, allowed_chars='abcdefghjkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789'
):
    "Generates a random password with the given length and given allowed_chars"
    # Note that default value of allowed_chars does not have "I" or letters
    # that look like it -- just to avoid confusion.
    #         from random import choice
    #         return ''.join([choice(allowed_chars) for i in range(length)])
    return generate_hash(allowed_chars, length)


def generate_hash(string, length=10):
    salt = hashlib.sha224(str(random.random())).hexdigest()[:5]
    return hashlib.sha224(salt + string).hexdigest()[:length]


def upload_handle(f, generate_dir=FILE_UPLOAD_TEMP_DIR, suffix=False):
    if suffix:
        fileName = join(generate_dir, ('tmp_%s' % f.name))
    else:
        fileName = join(generate_dir, ('%s' % f.name))

    # create file from uploaded
    destination = open(fileName, 'wb+')
    for chunk in f.chunks():
        destination.write(chunk)
    destination.close()

    return fileName


CERT_ACTIVE = getattr(settings, 'CERT_ACTIVE', False)

CERT_PROTOCOL = getattr(settings, 'CERT_PROTOCOL', 'http')
CERT_HOST = getattr(settings, 'CERT_HOST', 'localhost')
CERT_PORT = getattr(settings, 'CERT_PORT', '9988')
CERT_RPC_PATH = getattr(settings, 'CERT_RPC_PATH', '/certificate/')


def certificate_urls():
    if CERT_ACTIVE:
        if CERT_PORT != '' and CERT_PORT is not None:
            return '%s://%s:%s%s' % (CERT_PROTOCOL, CERT_HOST, CERT_PORT, CERT_RPC_PATH)
        else:
            return '%s://%s%s' % (CERT_PROTOCOL, CERT_HOST, CERT_RPC_PATH)
    else:
        return 'http://localhost/certificate'


def media_urls():
    if CERT_ACTIVE:
        if CERT_PORT != '' and CERT_PORT is not None:
            return '%s://%s:%s/%s' % (CERT_PROTOCOL, CERT_HOST, CERT_PORT, settings.MEDIA_URL)
        else:
            return '%s://%s/%s' % (CERT_PROTOCOL, CERT_HOST, settings.MEDIA_URL)
    else:
        return 'http://localhost/media'


def upload_handle_media(f, upload_to, f_suffix=None):
    print("settings.MEDIA_ROOT:", settings.MEDIA_ROOT)
    generate_dir = join(settings.MEDIA_ROOT, upload_to)
    if f_suffix:
        f_out = '%s_%s' % (f_suffix, f.name)
    else:
        f_out = '%s' % f.name

    if not os.path.exists(generate_dir):
        os.makedirs(generate_dir)

    fileName = join(generate_dir, f_out)

    # create file from uploaded
    destination = open(fileName, 'wb+')
    for chunk in f.chunks():
        destination.write(chunk)
    destination.close()

    return dict(file_name=fileName, file_url="%s/%s/%s" % (media_urls(), upload_to, f_out))


class OrderList(object):
    def __init__(self):
        self.output_list = []

    def atoi(self, text):
        int_val = int(text) if text.isdigit() else text
        #         print 'int_val',int_val
        return int_val

    def __natural_keys(self, text):
        '''
        alist.sort(key=natural_keys) sorts in human order
        http://nedbatchelder.com/blog/200712/human_sorting.html
        (See Toothy's implementation in the comments)
        '''
        #         print 'text:', text
        return [self.atoi(text.split('_')[1])]

    def sort(self, list_input, prefix=None):
        # remove if not pass regex
        if prefix:
            for val in list_input:
                if not val.strip().startswith(prefix):
                    list_input.remove(val)
                    self.output_list.append(val)

        _sort_res = sorted(list_input, key=self.__natural_keys)
        return _sort_res + self.output_list


def get_from_post_rest(url, data_dict, username=None, password=None):
    logger.info("Data sent: %s" % data_dict)
    result = None
    if username and password:
        password_mgr = urllib.request.HTTPPasswordMgrWithDefaultRealm()
        password_mgr.add_password(None, url, username, password)
        handler = urllib.request.HTTPBasicAuthHandler(password_mgr)
        opener = urllib.request.build_opener(handler)
        urllib.request.install_opener(opener)

        if data_dict:
            data = data_dict
            result = urllib.parse.urlencode(data)
            req = urllib.request.Request(url, result)
        else:
            req = urllib.request.Request(url)

        response = urllib.request.urlopen(req)

        code = response.code
        try:
            result = json.loads(response.read())
        except Exception as e:
            logger.info("Err get_from_post_rest: %s" % e)
            logger.info(response.read())
            result = response.read()
    else:
        code = 1
        try:
            result = urllib.request.urlopen(url).read()
        except Exception as e:
            result = e

    return result, code
