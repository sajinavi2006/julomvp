from django.utils import timezone
from django.db.models import Q

from juloserver.apiv1.services import construct_card

from .models import AndroidCard


def get_android_card_from_database(cards):
    today = timezone.localtime(timezone.now()).date()
    androidcards = AndroidCard.objects.filter(is_active=True).filter(
        (Q(start_date__lte=today) & Q(end_date__gte=today)) |
        Q(is_permanent=True)).order_by('display_order')

    for androidcard in androidcards:
        card = construct_card(
            androidcard.message, androidcard.title, '',
            androidcard.action_url, None, androidcard.button_text)
        cards.append(card)

    return cards
