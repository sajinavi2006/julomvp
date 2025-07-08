from juloserver.settings.base import STATIC_URL


def get_invalid_product_image():
    """
    In case no JFinancing product image found or havent uploaded yet,
    return special image
    """
    return STATIC_URL + 'images/ecommerce/juloshop/invalid_product_image.png'
