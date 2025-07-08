import ipaddress

from django.utils.text import slugify


def create_slug(name, model):
    slug = clean_slug = slugify(name)
    exists = True
    i = 1
    while exists:
        if i > 1:
            slug = clean_slug + "-" + str(i)
        queryset = model.objects.filter(slug=slug)
        exists = queryset.exists()
        i += 1

    return slug


def get_ip(request):
    """
    Get the client's IP address from the request.

    Args:
        request (HttpRequest): The HTTP request object.

    Returns:
        str: The client's IP address.

    """
    ip = None
    ip_headers = [
        'HTTP_CF_CONNECTING_IP',
        'HTTP_TRUE_CLIENT_IP',
        'HTTP_X_FORWARDED_FOR',
        'HTTP_X_REAL_IP',
        'REMOTE_ADDR',
    ]

    for ip_header_name in ip_headers:
        if ip_header_name not in request.META:
            continue

        ip_address = request.META[ip_header_name]
        if ip_header_name == 'HTTP_X_FORWARDED_FOR' and ',' in ip_address:
            ip_address = [x for x in [x.strip() for x in ip_address.split(',')] if x][0]

        try:
            ip = ipaddress.ip_address(ip_address)
        except ValueError:
            continue

        return str(ip), ip_header_name
