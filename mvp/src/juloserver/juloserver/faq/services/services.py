from juloserver.faq.models import Faq


def get_faqs(feature_name):
    faqs = Faq.objects.order_by('order_priority').filter(feature_name=feature_name, is_active=True)
    faq_data = [{
        "id": faq.id,
        "question": faq.question,
        "answer": faq.answer,
        "order": faq.order_priority
    } for faq in faqs]
        
    return faq_data
