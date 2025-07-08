from django.contrib import admin

from juloserver.channeling_loan.models import DBSChannelingApplicationJob


class DBSChannelingApplicationJobAdmin(admin.ModelAdmin):
    ordering = ('-id',)
    search_fields = ('id', 'job_industry', 'job_description')
    list_display = (
        'id',
        'job_industry',
        'job_description',
        'is_exclude',
        'aml_risk_rating',
        'job_code',
        'job_industry_code',
    )
    list_filter = ('job_industry', 'job_description')


admin.site.register(DBSChannelingApplicationJob, DBSChannelingApplicationJobAdmin)
