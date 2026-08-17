from django import forms
from django.core.exceptions import ValidationError
from django.forms import BaseFormSet, formset_factory

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
        fields = ["status", "notes"]


class ProductionOrderCreateItemForm(forms.ModelForm):
    class Meta:
        model = ProductionOrderItem
        fields = ["product", "quantity"]
        widgets = {
            "quantity": forms.NumberInput(attrs={"min": "0.001", "step": "0.001"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["product"].queryset = Product.objects.filter(is_active=True).order_by("name")
        self.fields["product"].empty_label = "Выберите продукт"


class BaseProductionOrderItemFormSet(BaseFormSet):
    def clean(self):
        super().clean()
        if any(self.errors):
            return

        products = []
        for form in self.forms:
            product = form.cleaned_data.get("product")
            quantity = form.cleaned_data.get("quantity")
            if product and quantity:
                products.append(product.pk)

        if not products:
            raise ValidationError("Добавьте хотя бы один продукт и укажите количество.")
        if len(products) != len(set(products)):
            raise ValidationError("Один продукт можно добавить только один раз.")


ProductionOrderCreateItemFormSet = formset_factory(
    ProductionOrderCreateItemForm,
    formset=BaseProductionOrderItemFormSet,
    extra=5,
    max_num=100,
    validate_max=True,
)


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
