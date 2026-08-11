from datetime import timedelta
from decimal import Decimal
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.db.models.deletion import ProtectedError
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import UserProfile

from apps.bakery.models import (
    BatchStageHistory,
    Customer,
    FinishedGoodsStock,
    Ingredient,
    ProductionBatch,
    ProductionOrder,
    ProductionOrderItem,
    ProductionStage,
    Product,
    Recipe,
    RecipeItem,
    VoiceMessage,
)
from apps.bakery.services import confirm_order, move_batch


class BakeryFixtureMixin:
    def setUp(self):
        User = get_user_model()
        self.dispatcher = User.objects.create_user("dispatcher", password="x")
        self.dispatcher.profile.role = UserProfile.Role.MANAGER
        self.dispatcher.profile.save()
        self.auditor = User.objects.create_user("auditor", password="x")
        self.auditor.profile.role = UserProfile.Role.USER
        self.auditor.profile.save()
        self.operator = User.objects.create_user("mixing", password="x")
        self.operator.profile.role = UserProfile.Role.USER
        self.operator.profile.save()
        for seq, (code, name) in enumerate([
            ("queue", "Очередь"), ("mixing", "Замес"), ("forming", "Формовка"),
            ("proofing", "Расстойка"), ("oven", "Печь"), ("warehouse", "Склад"), ("done", "Готово"),
        ], start=1):
            ProductionStage.objects.create(code=code, name=name, sequence=seq)
        self.product = Product.objects.create(code="VILLAGE", name="Хлеб «Деревенский»", category="bread", unit="шт", shelf_life_hours=36)
        self.flour = Ingredient.objects.create(code="FLOUR", name="Мука пшеничная", unit="кг", current_stock=100, minimum_stock=20)
        self.yeast = Ingredient.objects.create(code="YEAST", name="Дрожжи", unit="кг", current_stock=10, minimum_stock=3)
        self.recipe = Recipe.objects.create(product=self.product, name="Основная", version="1.0", output_quantity=100, output_unit="шт")
        RecipeItem.objects.create(recipe=self.recipe, ingredient=self.flour, quantity_for_batch=Decimal("25.000"), sequence=1)
        RecipeItem.objects.create(recipe=self.recipe, ingredient=self.yeast, quantity_for_batch=Decimal("1.000"), sequence=2)
        self.customer = Customer.objects.create(name="Клиент")
        self.order = ProductionOrder.objects.create(customer=self.customer, required_date=timezone.now() + timedelta(hours=6), created_by=self.dispatcher)
        self.line = ProductionOrderItem.objects.create(order=self.order, product=self.product, quantity=500, unit="шт", recipe=self.recipe)


class BakeryModelTests(BakeryFixtureMixin, TestCase):
    def test_create_product_ingredient_recipe(self):
        self.assertEqual(Product.objects.count(), 1)
        self.assertEqual(Ingredient.objects.count(), 2)
        self.assertEqual(self.recipe.items.count(), 2)

    def test_calculate_ingredients_for_order(self):
        requirements = {row["ingredient"].code: row["quantity"] for row in self.line.requirements()}
        self.assertEqual(requirements["FLOUR"], Decimal("125.000"))
        self.assertEqual(requirements["YEAST"], Decimal("5.000"))

    def test_confirm_order_creates_queued_batch(self):
        batches = confirm_order(self.order, user=self.dispatcher, assignee=self.operator)
        self.assertEqual(len(batches), 1)
        self.assertEqual(batches[0].current_stage.code, "queue")
        self.assertEqual(batches[0].status, ProductionBatch.Status.QUEUED)

    def test_move_batch_saves_history(self):
        batch = confirm_order(self.order, user=self.dispatcher)[0]
        move_batch(batch, ProductionStage.objects.get(code="mixing"), self.dispatcher, "Старт")
        batch.refresh_from_db()
        self.assertEqual(batch.current_stage.code, "mixing")
        self.assertEqual(BatchStageHistory.objects.filter(batch=batch).count(), 2)

    def test_move_without_permission_forbidden(self):
        # Роли без права двигать партии не осталось - все три могут. Отказ
        # приходит тому, у кого роли нет вовсе: такой профиль заведён в обход
        # приложения, и прав ему не полагается.
        self.auditor.profile.role = ""
        self.auditor.profile.save(update_fields=["role"])
        batch = confirm_order(self.order, user=self.dispatcher)[0]
        with self.assertRaises(PermissionDenied):
            move_batch(batch, ProductionStage.objects.get(code="mixing"), self.auditor)

    def test_problem_batch_blocks_forward_move(self):
        batch = confirm_order(self.order, user=self.dispatcher)[0]
        batch.status = ProductionBatch.Status.PROBLEM
        batch.save()
        batch.nonconformities.create(
            quality_object=self._quality_object(),
            control_post=self._control_post(),
            defect_type=self._defect_type(),
            description="Критическая проблема",
            criticality="critical",
            affected_quantity=1,
        )
        with self.assertRaises(ValidationError):
            move_batch(batch, ProductionStage.objects.get(code="mixing"), self.dispatcher)

    def test_stock_created_on_warehouse_stage(self):
        batch = confirm_order(self.order, user=self.dispatcher)[0]
        for code in ["mixing", "forming", "proofing", "oven", "warehouse"]:
            move_batch(batch, ProductionStage.objects.get(code=code), self.dispatcher)
            batch.refresh_from_db()
        self.assertTrue(FinishedGoodsStock.objects.filter(batch=batch).exists())

    def test_kanban_filter(self):
        confirm_order(self.order, user=self.dispatcher)
        self.client.force_login(self.dispatcher)
        response = self.client.get(reverse("bakery:kanban"), {"q": "Деревенский"})
        self.assertContains(response, "Деревенский", status_code=200)

    def test_reports_page(self):
        confirm_order(self.order, user=self.dispatcher)
        self.client.force_login(self.dispatcher)
        self.assertEqual(self.client.get(reverse("bakery:reports")).status_code, 200)

    def _quality_object(self):
        from apps.quality.models import Department, QualityObject
        dept, _ = Department.objects.get_or_create(code="T", defaults={"name": "Test"})
        return QualityObject.objects.create(unique_number="BTEST", object_type="finished_product", product_name="Bread", quantity=1, department=dept)

    def _control_post(self):
        from apps.quality.models import ControlPost, ControlType, Department
        dept, _ = Department.objects.get_or_create(code="T", defaults={"name": "Test"})
        ct, _ = ControlType.objects.get_or_create(code="T", defaults={"name": "Test"})
        return ControlPost.objects.create(code="BT", name="Bakery test", department=dept, control_type=ct)

    def _defect_type(self):
        from apps.nonconformities.models import DefectType
        return DefectType.objects.create(code="BT", name="Проблема", criticality="critical")


@override_settings(
    STORAGES={
        "default": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    }
)
class VoiceMessageTests(BakeryFixtureMixin, TestCase):

    @override_settings(MAX_VOICE_MESSAGE_SIZE_MB=1)
    def test_voice_upload_and_logical_delete(self):
        self.client.force_login(self.dispatcher)
        file = SimpleUploadedFile("note.webm", b"audio", content_type="audio/webm")
        response = self.client.post(reverse("bakery:voice_upload"), {"audio_file": file, "comment": "Комментарий"})
        self.assertEqual(response.status_code, 302)
        msg = VoiceMessage.objects.get()
        self.client.post(reverse("bakery:voice_delete", args=[msg.pk]))
        msg.refresh_from_db()
        self.assertTrue(msg.is_deleted)

    def test_voice_rejects_unsupported_file(self):
        msg = VoiceMessage(original_filename="bad.exe", mime_type="application/x-msdownload", file_size=10)
        with self.assertRaises(ValidationError):
            msg.clean()

    @override_settings(MAX_VOICE_MESSAGE_SIZE_MB=1)
    def test_voice_rejects_large_file(self):
        msg = VoiceMessage(original_filename="big.webm", mime_type="audio/webm", file_size=2 * 1024 * 1024)
        with self.assertRaises(ValidationError):
            msg.clean()

    def test_voice_file_access_forbidden_for_unrelated_user(self):
        other = get_user_model().objects.create_user("other", password="x")
        other.profile.role = UserProfile.Role.USER
        other.profile.save()
        file = SimpleUploadedFile("note.webm", b"audio", content_type="audio/webm")
        msg = VoiceMessage.objects.create(audio_file=file, original_filename="note.webm", mime_type="audio/webm", file_size=5, created_by=self.dispatcher)
        self.client.force_login(other)
        self.assertEqual(self.client.get(reverse("bakery:voice_audio", args=[msg.pk])).status_code, 403)


class BakeryApiTests(BakeryFixtureMixin, TestCase):
    def test_api_requires_authentication(self):
        response = APIClient().get("/api/products/")
        self.assertEqual(response.status_code, 403)

    def test_api_authenticated(self):
        client = APIClient()
        client.force_authenticate(self.dispatcher)
        response = client.get("/api/products/")
        self.assertEqual(response.status_code, 200)


class SeedBakeryCommandTests(TestCase):
    def call_seed(self):
        call_command("seed_bakery", stdout=StringIO())

    def seeded_counts(self):
        from apps.nonconformities.models import Nonconformity

        return {
            "products": Product.objects.count(),
            "ingredients": Ingredient.objects.count(),
            "recipes": Recipe.objects.count(),
            "recipe_items": RecipeItem.objects.count(),
            "customers": Customer.objects.count(),
            "orders": ProductionOrder.objects.count(),
            "order_items": ProductionOrderItem.objects.count(),
            "batches": ProductionBatch.objects.count(),
            "stages": ProductionStage.objects.count(),
            "history": BatchStageHistory.objects.count(),
            "stock": FinishedGoodsStock.objects.count(),
            "problems": Nonconformity.objects.count(),
        }

    def test_seed_bakery_first_run_success(self):
        self.call_seed()
        self.assertGreaterEqual(Product.objects.count(), 10)
        self.assertGreaterEqual(Ingredient.objects.count(), 12)
        self.assertEqual(ProductionStage.objects.count(), 7)
        self.assertTrue(ProductionBatch.objects.filter(current_stage__code="queue").exists())

    def test_only_the_admin_gets_the_django_admin(self):
        """Менеджер правит справочники и этапы через /settings/, а не через админку.

        С is_staff ему открывались бы заодно пользователи и всё остальное -
        мимо разграничения по ролям.
        """
        self.call_seed()
        User = get_user_model()
        staff = set(User.objects.filter(is_staff=True).values_list("username", flat=True))
        self.assertEqual(staff, {"admin"})

    def test_seed_takes_the_staff_flag_back(self):
        # Ради этого правка и делалась: на стенде пользователи заведены прошлым
        # запуском, а `defaults` в get_or_create до существующих не доходит.
        self.call_seed()
        User = get_user_model()
        User.objects.filter(username="technologist").update(is_staff=True)
        self.call_seed()
        self.assertFalse(User.objects.get(username="technologist").is_staff)

    def test_seed_bakery_second_run_success_and_no_duplicates(self):
        self.call_seed()
        first_counts = self.seeded_counts()
        self.call_seed()
        self.assertEqual(self.seeded_counts(), first_counts)

    def test_seed_bakery_preserves_protected_legacy_nonconformity(self):
        from apps.inspections.models import InspectionCard, InspectionTask, Reinspection
        from apps.nonconformities.models import DefectType, Nonconformity
        from apps.quality.models import ControlPost, ControlType, Department, InspectionTemplate, QualityObject

        User = get_user_model()
        inspector = User.objects.create_user("legacy-inspector", password="x")
        dept = Department.objects.create(code="LEGACY", name="Legacy")
        control_type = ControlType.objects.create(code="LEGACY", name="Legacy")
        post = ControlPost.objects.create(code="LEGACY", name="Legacy post", department=dept, control_type=control_type)
        template = InspectionTemplate.objects.create(code="LEGACY", name="Legacy template", control_post=post, control_type=control_type)
        qobj = QualityObject.objects.create(
            unique_number="MOD-3321",
            object_type="finished_product",
            product_name="Legacy module",
            quantity=1,
            department=dept,
        )
        task = InspectionTask.objects.create(quality_object=qobj, control_post=post, inspection_template=template, assigned_to=inspector)
        card = InspectionCard.objects.create(task=task, quality_object=qobj, control_post=post, inspector=inspector)
        defect = DefectType.objects.create(code="WELD-CRACK", name="Трещина сварного шва", criticality="critical")
        nonconformity = Nonconformity.objects.create(
            quality_object=qobj,
            control_post=post,
            defect_type=defect,
            description="Legacy protected problem",
            criticality="critical",
            affected_quantity=1,
        )
        Reinspection.objects.create(
            nonconformity=nonconformity,
            quality_object=qobj,
            original_inspection_card=card,
            inspector=inspector,
        )

        try:
            self.call_seed()
        except ProtectedError as exc:
            self.fail(f"seed_bakery raised ProtectedError: {exc}")

        self.assertTrue(Nonconformity.objects.filter(pk=nonconformity.pk).exists())
        self.assertTrue(Reinspection.objects.filter(nonconformity=nonconformity).exists())
