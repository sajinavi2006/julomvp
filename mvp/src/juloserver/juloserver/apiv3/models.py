from __future__ import unicode_literals

from builtins import object

from django.db import models

from juloserver.julocore.data.models import (
    GetInstanceMixin,
    JuloModelManager,
    TimeStampedModel,
)


class ApiV3ModelManager(GetInstanceMixin, JuloModelManager):
    pass


class ApiV3Model(TimeStampedModel):
    class Meta(object):
        abstract = True

    objects = ApiV3ModelManager()


# Create your models here.
class ProvinceLookup(ApiV3Model):
    id = models.AutoField(db_column='province_lookup_id', primary_key=True)
    province = models.CharField(max_length=200)
    is_active = models.BooleanField(default=True)

    class Meta(object):
        db_table = 'province_lookup'
        index_together = [('province',)]

    def __str__(self):
        return self.province


class CityLookup(ApiV3Model):
    id = models.AutoField(db_column='city_lookup_id', primary_key=True)
    city = models.CharField(max_length=200)
    is_active = models.BooleanField(default=True)
    province = models.ForeignKey(
        'ProvinceLookup', on_delete=models.CASCADE, db_column='province_lookup_id'
    )

    class Meta(object):
        db_table = 'city_lookup'
        index_together = [('city',)]

    def __str__(self):
        return self.city


class DistrictLookup(ApiV3Model):
    id = models.AutoField(db_column='district_lookup_id', primary_key=True)
    district = models.CharField(max_length=200)
    is_active = models.BooleanField(default=True)
    city = models.ForeignKey('CityLookup', on_delete=models.CASCADE, db_column='city_lookup_id')

    class Meta(object):
        db_table = 'district_lookup'
        index_together = [('district',)]

    def __str__(self):
        return self.district


class SubDistrictLookup(ApiV3Model):
    id = models.AutoField(db_column='sub_district_lookup_id', primary_key=True)
    sub_district = models.CharField(max_length=200)
    zipcode = models.CharField(max_length=10, blank=True, null=True)
    is_active = models.BooleanField(default=True)
    district = models.ForeignKey(
        'DistrictLookup', on_delete=models.CASCADE, db_column='district_lookup_id'
    )

    class Meta(object):
        db_table = 'sub_district_lookup'
        index_together = [('sub_district', 'zipcode')]

    def __str__(self):
        return self.sub_district
