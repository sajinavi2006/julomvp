from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.status import HTTP_302_FOUND, HTTP_404_NOT_FOUND
from rest_framework.views import APIView

from juloserver.urlshortener.models import ShortenedUrl


# Create your views here.
class UrlShortenerView(APIView):

    permission_classes = (AllowAny,)

    def get(self, request, shorturl):

        shortened_url = ShortenedUrl.objects.get_or_none(short_url=shorturl)
        if shortened_url is not None:
            return Response(
                status=HTTP_302_FOUND,
                headers={'Location': shortened_url.full_url},
            )
        else:
            return Response(
                status=HTTP_404_NOT_FOUND,
            )
