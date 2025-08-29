from django.contrib import admin
from coag.models import Coag

# Register your models here.
class CoagAdmin(admin.ModelAdmin):
    pass

admin.site.register(Coag, CoagAdmin)