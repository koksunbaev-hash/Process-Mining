from django.contrib import admin

from .models import CorrectiveAction, DefectType, Nonconformity, NonconformityAttachment, NonconformityCause


admin.site.register(DefectType)
admin.site.register(NonconformityCause)
admin.site.register(Nonconformity)
admin.site.register(NonconformityAttachment)
admin.site.register(CorrectiveAction)
