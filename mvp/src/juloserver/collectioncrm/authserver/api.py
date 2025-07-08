import requests
from django.conf import settings

def save_user(data):
	auth_url = settings.AUTH_SERVER_BASE_URL.strip("/")+"/api/v1/users"
	return requests.post(auth_url, data=data).ok