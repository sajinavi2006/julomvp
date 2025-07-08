import json

from django.utils import six
from rest_framework.exceptions import ParseError
from rest_framework.parsers import JSONParser


class JSONParserRemoveNonUTF8Char(JSONParser):

    '''
    we remove the non-UTF-8 Charaters to handle JSON parse error
    '''

    def parse(self, stream, media_type=None, parser_context=None):
        parser_context = parser_context or {}

        try:
            data = stream.read().decode('utf-8', 'ignore').encode("utf-8")
            return json.loads(data)
        except ValueError as exc:
            raise ParseError('JSON parse error - %s' % six.text_type(exc))
