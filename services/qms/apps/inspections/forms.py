from django import forms

from .models import InspectionAttachment, InspectionResult


class InspectionResultForm(forms.ModelForm):
    class Meta:
        model = InspectionResult
        fields = [
            "numeric_value", "text_value", "boolean_value", "date_value", "choice_value",
            "conformity_value", "measuring_equipment", "comment", "is_manual_override", "override_reason",
        ]


class InspectionAttachmentForm(forms.ModelForm):
    class Meta:
        model = InspectionAttachment
        fields = ["file", "file_type", "title", "comment"]
