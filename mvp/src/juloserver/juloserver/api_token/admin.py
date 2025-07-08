from django.contrib import admin

from .models import ExpiryToken


class ExpiryTokenAdmin(admin.ModelAdmin):
    list_display = ('key', 'user', 'generated_time', 'is_active')
    fields = ('user',)
    ordering = ('-generated_time',)


admin.site.register(ExpiryToken, ExpiryTokenAdmin)
