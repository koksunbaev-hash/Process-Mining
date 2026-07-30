from django import forms

from .models import (
    Customer,
    Ingredient,
    ProductionBatch,
    ProductionOrder,
    ProductionOrderItem,
    Product,
    Recipe,
    RecipeItem,
    VoiceMessage,
)


class ProductForm(forms.ModelForm):
    class Meta:
        model = Product
        fields = [
            "code", "name", "description", "category", "unit", "weight_per_item", "shelf_life_hours",
            "baking_temperature", "baking_duration_minutes", "proofing_duration_minutes",
            "mixing_duration_minutes", "image", "is_active",
        ]


class IngredientForm(forms.ModelForm):
    class Meta:
        model = Ingredient
        fields = ["code", "name", "unit", "current_stock", "minimum_stock", "supplier", "cost_per_unit", "is_active"]


class RecipeForm(forms.ModelForm):
    class Meta:
        model = Recipe
        fields = ["product", "name", "version", "output_quantity", "output_unit", "is_active", "approved_by", "approved_at", "notes"]


class RecipeItemForm(forms.ModelForm):
    class Meta:
        model = RecipeItem
        fields = ["ingredient", "quantity_for_batch", "sequence", "notes"]


class CustomerForm(forms.ModelForm):
    class Meta:
        model = Customer
        fields = ["name", "phone", "email", "address", "notes", "is_active"]


class ProductionOrderForm(forms.ModelForm):
    class Meta:
        model = ProductionOrder
        fields = ["customer", "order_date", "required_date", "priority", "status", "notes"]
        widgets = {
            "order_date": forms.DateTimeInput(attrs={"type": "datetime-local"}),
            "required_date": forms.DateTimeInput(attrs={"type": "datetime-local"}),
        }


class ProductionOrderItemForm(forms.ModelForm):
    class Meta:
        model = ProductionOrderItem
        fields = ["product", "quantity", "unit", "recipe", "notes"]


class BatchAssignForm(forms.ModelForm):
    class Meta:
        model = ProductionBatch
        fields = ["assigned_to", "actual_quantity", "planned_start", "planned_finish", "notes"]
        widgets = {
            "planned_start": forms.DateTimeInput(attrs={"type": "datetime-local"}),
            "planned_finish": forms.DateTimeInput(attrs={"type": "datetime-local"}),
        }


class VoiceMessageForm(forms.ModelForm):
    class Meta:
        model = VoiceMessage
        fields = ["audio_file", "duration_seconds", "order", "batch", "nonconformity", "product", "stage", "comment"]

    def clean_audio_file(self):
        audio = self.cleaned_data["audio_file"]
        self.instance.original_filename = audio.name
        self.instance.mime_type = getattr(audio, "content_type", "") or ""
        self.instance.file_size = audio.size
        return audio
