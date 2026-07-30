from django import forms

from .models import ControlRoute, QualityObject


class QualityObjectForm(forms.ModelForm):
    class Meta:
        model = QualityObject
        fields = [
            "unique_number", "object_type", "product_name", "product_code", "batch_number", "serial_number",
            "quantity", "unit", "supplier", "manufacturer", "department", "route",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["route"].queryset = ControlRoute.objects.filter(is_active=True)
