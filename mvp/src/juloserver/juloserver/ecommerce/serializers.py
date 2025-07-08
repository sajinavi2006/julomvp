from builtins import object
from rest_framework import serializers
from django.conf import settings

from juloserver.ecommerce.constants import EcommerceConstant
from juloserver.ecommerce.models import EcommerceConfiguration
from juloserver.julo.clients import get_julo_sentry_client
from juloserver.julo.models import Application

sentry_client = get_julo_sentry_client()


class EcommerceConfigurationSerializer(serializers.ModelSerializer):
    ecommerce_id = serializers.SerializerMethodField('get_ecommerce_name')
    ecommerce_name = serializers.SerializerMethodField()
    ecommerce_logo = serializers.SerializerMethodField('get_selection_logo')
    ecommerce_background = serializers.SerializerMethodField('get_background_logo')
    ecommerce_colour = serializers.SerializerMethodField('get_color_scheme')
    ecommerce_uri = serializers.SerializerMethodField('get_url')
    ecommerce_account_icon = serializers.SerializerMethodField('get_text_logo')
    ecommerce_web_view_uri = serializers.SerializerMethodField('get_web_view_url')

    class Meta(object):
        model = EcommerceConfiguration
        exclude = ("cdate", "udate", "selection_logo", "color_scheme", "url", "text_logo",
                   "background_logo", "is_active")

    def get_ecommerce_name(self, obj):
        return obj.ecommerce_name

    def get_selection_logo(self, obj):
        return obj.selection_logo

    def get_background_logo(self, obj):
        return obj.background_logo

    def get_color_scheme(self, obj):
        return obj.color_scheme

    def get_url(self, obj):
        return obj.url

    def get_text_logo(self, obj):
        return obj.text_logo

    def get_web_view_url(self, obj):
        return '{}?ecommerce_name=#{}'.format(settings.WEBVIEW_ECOMMERCE_URL, obj.ecommerce_name)


class InvoiceCallbackSerializer(serializers.Serializer):
    order_id = serializers.CharField(required=True)
    application_id = serializers.CharField(required=False)
    confirmation_status = serializers.CharField(required=True)

    field_mapping = (
        ('order_id', 'orderId'),
        ('application_id', 'applicationId'),
        ('confirmation_status', 'confirmationStatus'),
    )

    def __init__(self, instance=None, data=serializers.empty, **kwargs):
        # Prevent 'ValueError: too many values to unpack (expected 2)' if None is passed
        data = data if data else {}

        if isinstance(data, dict):
            data = {
                field: data[source]
                for field, source in self.field_mapping
                if source in data
            }

        super(InvoiceCallbackSerializer, self).__init__(instance, data, **kwargs)


class MarketPlaceSerializer(serializers.ModelSerializer):
    marketplace_id = serializers.SerializerMethodField('get_marketplace_name')
    marketplace_name = serializers.SerializerMethodField()
    marketplace_logo = serializers.SerializerMethodField('get_selection_logo')
    marketplace_background = serializers.SerializerMethodField('get_background_logo')
    marketplace_colour = serializers.SerializerMethodField('get_color_scheme')
    marketplace_uri = serializers.SerializerMethodField('get_url')
    marketplace_account_icon = serializers.SerializerMethodField('get_text_logo')
    marketplace_order_tracking_url = serializers.SerializerMethodField('get_order_tracking_url')

    class Meta(object):
        model = EcommerceConfiguration
        exclude = ("cdate", "udate", "selection_logo", "color_scheme", "url", "text_logo",
                   "background_logo", "ecommerce_name", "is_active")

    def get_marketplace_name(self, obj):
        return obj.ecommerce_name

    def get_selection_logo(self, obj):
        return obj.selection_logo

    def get_background_logo(self, obj):
        return obj.background_logo

    def get_color_scheme(self, obj):
        return obj.color_scheme

    def get_url(self, obj):
        return obj.url

    def get_text_logo(self, obj):
        return obj.text_logo

    def get_order_tracking_url(self, obj):
        if obj.ecommerce_name == EcommerceConstant.JULOSHOP:
            try:
                return obj.extra_config['urls']['order_tracking_url']
            except KeyError:
                sentry_client.captureException()
        return ''


class IpriceItemsSerializer(serializers.Serializer):
    id = serializers.CharField(required=True)
    imageUrl = serializers.CharField(required=True)
    url = serializers.CharField(required=True)
    name = serializers.CharField(required=True)
    price = serializers.FloatField(required=True)
    quantity = serializers.CharField(required=True)
    category = serializers.CharField(required=True)
    brandName = serializers.CharField(required=True)
    merchantName = serializers.CharField(required=True)


class IpriceCheckoutSerializer(serializers.Serializer):
    partnerUserId = serializers.IntegerField(required=True)
    paymentType = serializers.CharField(required=True)
    externalId = serializers.CharField(required=True)
    grandAmount = serializers.IntegerField(required=True)
    address = serializers.CharField(required=True)
    province = serializers.CharField(required=True)
    city = serializers.CharField(required=True)
    email = serializers.CharField(required=True)
    firstName = serializers.CharField(required=True)
    lastName = serializers.CharField(required=True)
    mobile = serializers.CharField(required=True)
    postcode = serializers.CharField(required=True)
    items = IpriceItemsSerializer(many=True, required=True)
    successRedirectUrl = serializers.CharField(required=True)
    failRedirectUrl = serializers.CharField(required=True)


class JuloShopShippingDetail(serializers.Serializer):
    province = serializers.CharField(required=True)
    city = serializers.CharField(required=True)
    area = serializers.CharField(required=True)
    postalCode = serializers.CharField(required=True)
    fullAddress = serializers.CharField(required=True)


class JuloShopItemRecipientDetail(serializers.Serializer):
    name = serializers.CharField(required=True)
    phoneNumber = serializers.CharField(required=True)


class JuloShopItemsSerializer(serializers.Serializer):
    productID = serializers.CharField(required=True)
    productName = serializers.CharField(required=True)
    price = serializers.FloatField(required=True)
    quantity = serializers.IntegerField(required=True)
    image = serializers.CharField(required=True)


class JuloShopCheckoutSerializer(serializers.Serializer):
    applicationXID = serializers.IntegerField(required=True)
    items = JuloShopItemsSerializer(many=True, required=True)
    sellerName = serializers.CharField(required=True)
    shippingDetail = JuloShopShippingDetail(required=True)
    recipientDetail = JuloShopItemRecipientDetail(required=True)
    totalProductAmount = serializers.IntegerField(required=True)
    shippingFee = serializers.IntegerField(required=True)
    insuranceFee = serializers.IntegerField(required=True)
    discount = serializers.IntegerField(required=True)
    finalAmount = serializers.IntegerField(required=True)

    def validate(self, data):
        items = data['items']
        if len(items) > EcommerceConstant.JULOSHOP_MAX_ITEMS_CHECKOUT:
            raise serializers.ValidationError("Items checkout max exceed")

        application = Application.objects.get_or_none(application_xid=data['applicationXID'])
        if not application:
            raise serializers.ValidationError("Invalid application")

        data['application'] = application
        return data


class JuloShopTransactionDetailsSerializer(serializers.Serializer):
    transaction_xid = serializers.UUIDField(required=True)
