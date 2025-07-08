from factory import (
    DjangoModelFactory,
    SubFactory,
)

from juloserver.pn_delivery.models import (
    PNDelivery,
    PNBlast,
    PNTracks,
)


class PNBlastFactory(DjangoModelFactory):
    class Meta(object):
        model = PNBlast

    title = 'default title'
    name = 'default name'
    status = 'default status'
    content = 'default content'
    redirect_page = 1


class PNDeliveryFactory(DjangoModelFactory):
    class Meta(object):
        model = PNDelivery

    fcm_id = 'default FCM'
    title = 'default title'
    body = 'default body'
    status = 'default status'
    pn_blast = SubFactory(PNBlastFactory)


class PNTracksFactory(DjangoModelFactory):
    class Meta(object):
        model = PNTracks

    pn_id = SubFactory(PNDeliveryFactory)
