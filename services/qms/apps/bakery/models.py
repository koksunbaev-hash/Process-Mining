import os
import re
import uuid
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.utils import timezone


class TimestampedModel(models.Model):
    created_at = models.DateTimeField("создано", auto_now_add=True)
    updated_at = models.DateTimeField("обновлено", auto_now=True)

    class Meta:
        abstract = True


class Unit(models.TextChoices):
    KG = "кг", "кг"
    G = "г", "г"
    L = "л", "л"
    ML = "мл", "мл"
    PCS = "шт", "шт"


class Product(TimestampedModel):
    class Category(models.TextChoices):
        BREAD = "bread", "хлеб"
        LOAF = "loaf", "батон"
        BAGUETTE = "baguette", "багет"
        TOAST = "toast", "тостовый хлеб"
        SANDWICH = "sandwich", "сэндвичный хлеб"
        BUN = "bun", "булочка"
        OTHER = "other", "другое"

    code = models.CharField("код", max_length=50, unique=True)
    name = models.CharField("название", max_length=220)
    description = models.TextField("описание", blank=True)
    category = models.CharField("категория", max_length=32, choices=Category.choices, default=Category.BREAD)
    unit = models.CharField("единица", max_length=12, default=Unit.PCS, choices=Unit.choices)
    weight_per_item = models.DecimalField("вес 1 шт.", max_digits=10, decimal_places=3, null=True, blank=True)
    shelf_life_hours = models.PositiveIntegerField("срок годности, часов", default=24)
    baking_temperature = models.PositiveIntegerField("температура выпечки", null=True, blank=True)
    baking_duration_minutes = models.PositiveIntegerField("выпечка, мин", null=True, blank=True)
    proofing_duration_minutes = models.PositiveIntegerField("расстойка, мин", null=True, blank=True)
    mixing_duration_minutes = models.PositiveIntegerField("замес, мин", null=True, blank=True)
    image = models.ImageField("изображение", upload_to="products/", blank=True)
    is_active = models.BooleanField("активен", default=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "продукт"
        verbose_name_plural = "продукты"

    def __str__(self):
        return self.name


class Ingredient(TimestampedModel):
    code = models.CharField("код", max_length=50, unique=True)
    name = models.CharField("название", max_length=220)
    unit = models.CharField("единица", max_length=12, choices=Unit.choices, default=Unit.KG)
    current_stock = models.DecimalField("остаток", max_digits=12, decimal_places=3, default=0)
    minimum_stock = models.DecimalField("минимум", max_digits=12, decimal_places=3, default=0)
    supplier = models.CharField("поставщик", max_length=180, blank=True)
    cost_per_unit = models.DecimalField("цена за ед.", max_digits=12, decimal_places=2, null=True, blank=True)
    is_active = models.BooleanField("активен", default=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "ингредиент"
        verbose_name_plural = "ингредиенты"

    def __str__(self):
        return self.name

    @property
    def is_low_stock(self):
        return self.current_stock < self.minimum_stock


class Recipe(TimestampedModel):
    product = models.ForeignKey(Product, verbose_name="продукт", on_delete=models.CASCADE, related_name="recipes")
    name = models.CharField("название", max_length=220)
    version = models.CharField("версия", max_length=40, default="1.0")
    output_quantity = models.DecimalField("выход", max_digits=12, decimal_places=3)
    output_unit = models.CharField("единица выхода", max_length=12, choices=Unit.choices, default=Unit.PCS)
    is_active = models.BooleanField("активна", default=True)
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="утвердил", on_delete=models.SET_NULL, null=True, blank=True)
    approved_at = models.DateTimeField("утверждено", null=True, blank=True)
    notes = models.TextField("примечания", blank=True)

    class Meta:
        ordering = ["product__name", "-is_active", "-created_at"]
        unique_together = ("product", "version")
        verbose_name = "рецептура"
        verbose_name_plural = "рецептуры"

    def __str__(self):
        return f"{self.product} v{self.version}"

    def calculate_requirements(self, quantity):
        quantity = Decimal(str(quantity))
        if not self.output_quantity:
            return []
        factor = quantity / self.output_quantity
        return [
            {
                "ingredient": item.ingredient,
                "quantity": (item.quantity_for_batch * factor).quantize(Decimal("0.001")),
                "unit": item.ingredient.unit,
            }
            for item in self.items.select_related("ingredient").all()
        ]


class RecipeItem(models.Model):
    recipe = models.ForeignKey(Recipe, verbose_name="рецептура", on_delete=models.CASCADE, related_name="items")
    ingredient = models.ForeignKey(Ingredient, verbose_name="ингредиент", on_delete=models.PROTECT, related_name="recipe_items")
    # Технологические карты содержат микродобавки до миллионных долей кг.
    # Три знака после запятой превращали такие количества в ноль.
    quantity_for_batch = models.DecimalField("на партию", max_digits=15, decimal_places=6)
    quantity_per_item = models.DecimalField("на 1 шт.", max_digits=12, decimal_places=6, default=0)
    sequence = models.PositiveIntegerField("порядок", default=1)
    notes = models.TextField("примечание", blank=True)

    class Meta:
        ordering = ["sequence", "ingredient__name"]
        unique_together = ("recipe", "ingredient")
        verbose_name = "строка рецептуры"
        verbose_name_plural = "строки рецептуры"

    def save(self, *args, **kwargs):
        if self.recipe_id and self.recipe.output_quantity:
            self.quantity_per_item = (self.quantity_for_batch / self.recipe.output_quantity).quantize(Decimal("0.000001"))
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.ingredient} - {self.quantity_for_batch} {self.ingredient.unit}"


class Customer(TimestampedModel):
    name = models.CharField("клиент", max_length=220)
    phone = models.CharField("телефон", max_length=80, blank=True)
    email = models.EmailField("email", blank=True)
    address = models.CharField("адрес", max_length=260, blank=True)
    notes = models.TextField("примечания", blank=True)
    is_active = models.BooleanField("активен", default=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "клиент"
        verbose_name_plural = "клиенты"

    def __str__(self):
        return self.name


class KanbanDemoRun(TimestampedModel):
    class Status(models.TextChoices):
        CREATED = "created", "создано"
        RUNNING = "running", "запущено"
        PAUSED = "paused", "пауза"
        COMPLETED = "completed", "завершено"
        STOPPED = "stopped", "остановлено"
        FAILED = "failed", "ошибка"

    class Mode(models.TextChoices):
        SEQUENTIAL = "sequential", "по очереди"
        WAVE = "wave", "группами"
        RANDOM = "random", "случайно"
        FAST = "fast", "быстро"

    name = models.CharField("название", max_length=160, default="Kanban demo")
    status = models.CharField("статус", max_length=24, choices=Status.choices, default=Status.CREATED, db_index=True)
    mode = models.CharField("режим", max_length=24, choices=Mode.choices, default=Mode.WAVE)
    total_batches = models.PositiveIntegerField("всего партий", default=100)
    completed_batches = models.PositiveIntegerField("готово партий", default=0)
    speed_seconds = models.DecimalField("скорость, секунд", max_digits=5, decimal_places=2, default=2)
    simulate_pauses = models.BooleanField("симулировать паузы", default=False)
    simulate_problems = models.BooleanField("симулировать проблемы", default=False)
    simulate_returns = models.BooleanField("симулировать возвраты", default=False)
    last_error = models.TextField("последняя ошибка", blank=True)
    client_request_id = models.CharField("ID запроса клиента", max_length=120, unique=True, null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="создал", on_delete=models.SET_NULL, null=True, blank=True, related_name="kanban_demo_runs")
    started_at = models.DateTimeField("старт", null=True, blank=True)
    paused_at = models.DateTimeField("пауза", null=True, blank=True)
    finished_at = models.DateTimeField("финиш", null=True, blank=True)
    is_active = models.BooleanField("активно", default=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "демо Kanban"
        verbose_name_plural = "демо Kanban"

    def __str__(self):
        return f"{self.name} #{self.pk or 'new'}"


class ProductionOrder(TimestampedModel):
    class Status(models.TextChoices):
        DRAFT = "draft", "черновик"
        CONFIRMED = "confirmed", "подтверждён"
        QUEUED = "queued", "в очереди"
        IN_PRODUCTION = "in_production", "в производстве"
        READY = "ready", "готов"
        SHIPPED = "shipped", "отгружен"
        CANCELLED = "cancelled", "отменён"

    class Priority(models.TextChoices):
        LOW = "low", "низкий"
        NORMAL = "normal", "обычный"
        HIGH = "high", "высокий"
        URGENT = "urgent", "срочный"

    order_number = models.CharField("номер заказа", max_length=50, unique=True, blank=True)
    customer = models.ForeignKey(Customer, verbose_name="клиент", on_delete=models.PROTECT, related_name="orders")
    order_date = models.DateTimeField("дата заказа", default=timezone.now)
    required_date = models.DateTimeField("плановый срок")
    priority = models.CharField("приоритет", max_length=16, choices=Priority.choices, default=Priority.NORMAL)
    status = models.CharField("статус", max_length=24, choices=Status.choices, default=Status.DRAFT, db_index=True)
    notes = models.TextField("примечания", blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="создал", on_delete=models.SET_NULL, null=True, blank=True)
    kanban_grouped = models.BooleanField(
        "единый блок на канбане",
        default=False,
        help_text="Показывать партии этого заказа одним блоком и перемещать их вместе.",
    )
    is_demo = models.BooleanField("демо", default=False, db_index=True)
    demo_run = models.ForeignKey(KanbanDemoRun, verbose_name="демо-запуск", on_delete=models.SET_NULL, null=True, blank=True, related_name="orders")

    class Meta:
        ordering = ["-order_date"]
        verbose_name = "заказ"
        verbose_name_plural = "заказы"

    def save(self, *args, **kwargs):
        if not self.order_number:
            last_id = ProductionOrder.objects.order_by("-id").values_list("id", flat=True).first() or 0
            self.order_number = f"{last_id + 1:04d}"
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Заказ №{self.order_number}"


class ProductionOrderItem(models.Model):
    order = models.ForeignKey(ProductionOrder, verbose_name="заказ", on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey(Product, verbose_name="продукт", on_delete=models.PROTECT, related_name="order_items")
    quantity = models.DecimalField("количество", max_digits=12, decimal_places=3)
    unit = models.CharField("единица", max_length=12, choices=Unit.choices, default=Unit.PCS)
    recipe = models.ForeignKey(Recipe, verbose_name="рецептура", on_delete=models.PROTECT, null=True, blank=True, related_name="order_items")
    notes = models.TextField("примечания", blank=True)
    is_demo = models.BooleanField("демо", default=False, db_index=True)
    demo_run = models.ForeignKey(KanbanDemoRun, verbose_name="демо-запуск", on_delete=models.SET_NULL, null=True, blank=True, related_name="order_items")

    class Meta:
        ordering = ["id"]
        verbose_name = "товар заказа"
        verbose_name_plural = "товары заказа"

    def __str__(self):
        return f"{self.product} x {self.quantity}"

    def requirements(self):
        recipe = self.recipe or self.product.recipes.filter(is_active=True).first()
        return recipe.calculate_requirements(self.quantity) if recipe else []


class ProductionPlan(TimestampedModel):
    """Сколько цех собирается испечь этого продукта в этот день.

    Отдельно от заказов покупателей, и это не педантизм. Заказ - то, что
    попросили; план - то, что решили печь. Они расходятся постоянно: пекут с
    запасом, округляют до противня, добавляют под витрину. Правка плана не
    должна менять чужой заказ, а правка заказа не должна молча переписывать то,
    что уже отдали в цех.

    Пусто - значит плана нет, и лист покажет сумму заказов как есть.
    """

    date = models.DateField("дата", db_index=True)
    product = models.ForeignKey(Product, verbose_name="продукт", on_delete=models.CASCADE, related_name="plans")
    quantity = models.DecimalField("количество", max_digits=12, decimal_places=3, default=0)
    note = models.CharField("примечание", max_length=200, blank=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="изменил", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="production_plans",
    )
    # created_at и updated_at приходят из TimestampedModel - объявить их здесь
    # ещё раз означало бы конфликт полей с базовым классом.

    class Meta:
        ordering = ["date", "product__name"]
        # Одна строка на продукт в дне: иначе "количество" перестаёт быть числом
        # и становится вопросом, какую из строк считать правдой.
        constraints = [
            models.UniqueConstraint(fields=["date", "product"], name="unique_plan_per_product_per_day"),
        ]
        verbose_name = "план производства"
        verbose_name_plural = "планы производства"

    def __str__(self):
        return f"{self.date} {self.product.name}: {self.quantity}"


class ProductionStage(models.Model):
    code = models.CharField("код", max_length=40, unique=True)
    name = models.CharField("название", max_length=80)
    sequence = models.PositiveIntegerField("порядок", unique=True)
    is_active = models.BooleanField("активен", default=True)

    class Meta:
        ordering = ["sequence"]
        verbose_name = "этап производства"
        verbose_name_plural = "этапы производства"

    def __str__(self):
        return self.name


class ProductionBatch(TimestampedModel):
    class Status(models.TextChoices):
        PLANNED = "planned", "запланирована"
        QUEUED = "queued", "в очереди"
        IN_PROGRESS = "in_progress", "в работе"
        PAUSED = "paused", "остановлена"
        PROBLEM = "problem", "проблема"
        COMPLETED = "completed", "завершена"
        CANCELLED = "cancelled", "отменена"

    batch_number = models.CharField("номер партии", max_length=60, unique=True, blank=True)
    order_item = models.ForeignKey(ProductionOrderItem, verbose_name="товар заказа", on_delete=models.PROTECT, related_name="batches")
    product = models.ForeignKey(Product, verbose_name="продукт", on_delete=models.PROTECT, related_name="batches")
    recipe = models.ForeignKey(Recipe, verbose_name="рецептура", on_delete=models.PROTECT, null=True, blank=True, related_name="batches")
    planned_quantity = models.DecimalField("план", max_digits=12, decimal_places=3)
    actual_quantity = models.DecimalField("факт", max_digits=12, decimal_places=3, null=True, blank=True)
    unit = models.CharField("единица", max_length=12, choices=Unit.choices, default=Unit.PCS)
    current_stage = models.ForeignKey(ProductionStage, verbose_name="этап", on_delete=models.PROTECT, related_name="batches")
    status = models.CharField("статус", max_length=24, choices=Status.choices, default=Status.PLANNED, db_index=True)
    assigned_to = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="ответственный", on_delete=models.SET_NULL, null=True, blank=True, related_name="bakery_batches")
    planned_start = models.DateTimeField("план старт", null=True, blank=True)
    actual_start = models.DateTimeField("факт старт", null=True, blank=True)
    planned_finish = models.DateTimeField("план финиш", null=True, blank=True)
    actual_finish = models.DateTimeField("факт финиш", null=True, blank=True)
    notes = models.TextField("примечания", blank=True)
    is_demo = models.BooleanField("демо", default=False, db_index=True)
    demo_run = models.ForeignKey(KanbanDemoRun, verbose_name="демо-запуск", on_delete=models.SET_NULL, null=True, blank=True, related_name="batches")

    class Meta:
        ordering = ["current_stage__sequence", "planned_finish", "id"]
        verbose_name = "производственная партия"
        verbose_name_plural = "производственные партии"

    @staticmethod
    def short_number_for(value):
        value = (value or "").strip().upper()

        if not value:
            return ""

        demo_match = re.fullmatch(r"DEMO-B-0*(\d+)", value)
        if demo_match:
            return f"D-{int(demo_match.group(1))}"

        old_match = re.fullmatch(r"B-\d{4}-\d+-0*(\d+)", value)
        if old_match:
            return str(int(old_match.group(1)))

        new_match = re.fullmatch(r"B-0*(\d+)", value)
        if new_match:
            return str(int(new_match.group(1)))

        return value

    @property
    def short_batch_number(self):
        return self.short_number_for(self.batch_number)

    def save(self, *args, **kwargs):
        if not self.batch_number:
            base = self.order_item_id or int(timezone.now().timestamp())
            candidate = f"B-{base}"
            suffix = 1
            while ProductionBatch.objects.filter(batch_number=candidate).exclude(pk=self.pk).exists():
                suffix += 1
                candidate = f"B-{base}-{suffix}"
            self.batch_number = candidate
        super().save(*args, **kwargs)

    def __str__(self):
        return self.batch_number

    def clean(self):
        if self.planned_quantity is not None and self.planned_quantity <= 0:
            raise ValidationError("Плановое количество партии должно быть больше нуля.")
        if self.actual_quantity is not None and self.actual_quantity < 0:
            raise ValidationError("Фактическое количество партии не может быть отрицательным.")

    @property
    def stage_duration(self):
        last = self.stage_history.order_by("-created_at").first()
        start = last.created_at if last else self.actual_start or self.created_at
        return timezone.now() - start

    @property
    def has_blocking_problem(self):
        return self.nonconformities.filter(criticality="critical").exclude(status__in=["closed", "rejected"]).exists()


class BatchStageHistory(models.Model):
    batch = models.ForeignKey(ProductionBatch, verbose_name="партия", on_delete=models.CASCADE, related_name="stage_history")
    from_stage = models.ForeignKey(ProductionStage, verbose_name="откуда", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    to_stage = models.ForeignKey(ProductionStage, verbose_name="куда", on_delete=models.PROTECT, related_name="+")
    started_at = models.DateTimeField("старт этапа", null=True, blank=True)
    finished_at = models.DateTimeField("завершение этапа", null=True, blank=True)
    changed_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="перевёл", on_delete=models.SET_NULL, null=True, blank=True)
    comment = models.TextField("комментарий", blank=True)
    created_at = models.DateTimeField("создано", auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "история этапа"
        verbose_name_plural = "история этапов"

    @property
    def duration_minutes(self):
        if self.started_at and self.finished_at:
            return round((self.finished_at - self.started_at).total_seconds() / 60, 1)
        return None


class FinishedGoodsStock(TimestampedModel):
    class Status(models.TextChoices):
        AVAILABLE = "available", "доступно"
        RESERVED = "reserved", "зарезервировано"
        SHIPPED = "shipped", "отгружено"
        EXPIRED = "expired", "просрочено"
        BLOCKED = "blocked", "заблокировано"

    product = models.ForeignKey(Product, verbose_name="продукт", on_delete=models.PROTECT, related_name="finished_stock")
    batch = models.OneToOneField(ProductionBatch, verbose_name="партия", on_delete=models.PROTECT, related_name="stock_record")
    quantity = models.DecimalField("количество", max_digits=12, decimal_places=3)
    unit = models.CharField("единица", max_length=12, choices=Unit.choices, default=Unit.PCS)
    received_at = models.DateTimeField("поступило", default=timezone.now)
    expiration_date = models.DateTimeField("срок годности")
    warehouse_location = models.CharField("место хранения", max_length=120, blank=True)
    status = models.CharField("статус", max_length=24, choices=Status.choices, default=Status.AVAILABLE)
    received_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="принял", on_delete=models.SET_NULL, null=True, blank=True)
    is_demo = models.BooleanField("демо", default=False, db_index=True)
    demo_run = models.ForeignKey(KanbanDemoRun, verbose_name="демо-запуск", on_delete=models.SET_NULL, null=True, blank=True, related_name="stock_items")

    class Meta:
        ordering = ["-received_at"]
        verbose_name = "готовая продукция"
        verbose_name_plural = "готовая продукция"


def voice_upload_to(instance, filename):
    ext = os.path.splitext(filename)[1].lower()
    return timezone.now().strftime(f"voice_messages/%Y/%m/{uuid.uuid4().hex}{ext}")


class VoiceMessage(TimestampedModel):
    class TranscriptionStatus(models.TextChoices):
        PENDING = "pending", "ожидает"
        UPLOADED = "uploaded", "загружено"
        SENT = "sent", "отправлено"
        PROCESSING = "processing", "обработка"
        COMPLETED = "completed", "завершено"
        FAILED = "failed", "ошибка"

    TRANSCRIPTION_PENDING = "pending"
    audio_file = models.FileField("аудио", upload_to=voice_upload_to)
    original_filename = models.CharField("исходное имя", max_length=240, blank=True)
    mime_type = models.CharField("MIME", max_length=120)
    file_size = models.PositiveIntegerField("размер")
    duration_seconds = models.PositiveIntegerField("длительность", null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="автор", on_delete=models.SET_NULL, null=True, blank=True, related_name="voice_messages")
    order = models.ForeignKey(ProductionOrder, verbose_name="заказ", on_delete=models.SET_NULL, null=True, blank=True, related_name="voice_messages")
    batch = models.ForeignKey(ProductionBatch, verbose_name="партия", on_delete=models.SET_NULL, null=True, blank=True, related_name="voice_messages")
    nonconformity = models.ForeignKey("nonconformities.Nonconformity", verbose_name="проблема", on_delete=models.SET_NULL, null=True, blank=True, related_name="voice_messages")
    product = models.ForeignKey(Product, verbose_name="продукт", on_delete=models.SET_NULL, null=True, blank=True, related_name="voice_messages")
    stage = models.ForeignKey(ProductionStage, verbose_name="этап", on_delete=models.SET_NULL, null=True, blank=True, related_name="voice_messages")
    comment = models.TextField("комментарий", blank=True)
    is_deleted = models.BooleanField("удалено", default=False)
    transcript = models.TextField("транскрипт", blank=True)
    transcription_status = models.CharField("статус транскрибации", max_length=32, choices=TranscriptionStatus.choices, default=TranscriptionStatus.UPLOADED)
    external_task_id = models.CharField("ID задачи Process Mining", max_length=120, blank=True, db_index=True)
    processing_error = models.TextField("ошибка обработки", blank=True)
    client_request_id = models.CharField("ID запроса клиента", max_length=120, unique=True, null=True, blank=True)
    processed_at = models.DateTimeField("обработано", null=True, blank=True)
    confidence = models.DecimalField("уверенность", max_digits=5, decimal_places=4, null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "голосовое сообщение"
        verbose_name_plural = "голосовые сообщения"

    def clean(self):
        allowed_ext = {".webm", ".ogg", ".mp3", ".wav", ".m4a"}
        allowed_mime = {"audio/webm", "audio/ogg", "audio/mpeg", "audio/wav", "audio/x-wav", "audio/mp4", "audio/m4a"}
        name = self.original_filename or getattr(self.audio_file, "name", "")
        ext = os.path.splitext(name)[1].lower()
        if ext not in allowed_ext:
            raise ValidationError("Неподдерживаемый формат аудио.")
        if self.mime_type and self.mime_type not in allowed_mime:
            raise ValidationError("Неподдерживаемый MIME-type аудио.")
        max_size = getattr(settings, "MAX_VOICE_MESSAGE_SIZE_MB", 20) * 1024 * 1024
        if self.file_size and self.file_size > max_size:
            raise ValidationError("Аудиофайл слишком большой.")


class VoiceCommand(TimestampedModel):
    class Intent(models.TextChoices):
        MOVE_BATCH = "move_batch", "передать партию"
        PAUSE_BATCH = "pause_batch", "остановить партию"
        RESUME_BATCH = "resume_batch", "возобновить партию"
        CREATE_PROBLEM = "create_problem", "создать проблему"
        ACCEPT_TO_WAREHOUSE = "accept_to_warehouse", "принять на склад"
        COMPLETE_BATCH = "complete_batch", "завершить партию"
        ADD_COMMENT = "add_comment", "добавить комментарий"

    class Status(models.TextChoices):
        DETECTED = "detected", "распознана"
        NEEDS_REVIEW = "needs_review", "требует проверки"
        CONFIRMED = "confirmed", "подтверждена"
        EXECUTED = "executed", "выполнена"
        REJECTED = "rejected", "отклонена"
        FAILED = "failed", "ошибка"

    voice_message = models.OneToOneField(VoiceMessage, verbose_name="голосовое сообщение", on_delete=models.CASCADE, related_name="command")
    intent = models.CharField("намерение", max_length=40, choices=Intent.choices)
    extracted_data = models.JSONField("извлечённые данные", default=dict)
    confidence = models.DecimalField("уверенность", max_digits=5, decimal_places=4, null=True, blank=True)
    status = models.CharField("статус", max_length=24, choices=Status.choices, default=Status.DETECTED)
    confirmed_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="подтвердил", on_delete=models.SET_NULL, null=True, blank=True, related_name="confirmed_voice_commands")
    executed_at = models.DateTimeField("выполнено", null=True, blank=True)
    error_message = models.TextField("ошибка", blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "голосовая команда"
        verbose_name_plural = "голосовые команды"

    def __str__(self):
        return f"{self.intent} / {self.status}"


class OrderEvent(models.Model):
    order = models.ForeignKey(ProductionOrder, verbose_name="заказ", on_delete=models.CASCADE, related_name="events")
    batch = models.ForeignKey(ProductionBatch, verbose_name="партия", on_delete=models.SET_NULL, null=True, blank=True, related_name="events")
    event_type = models.CharField("тип", max_length=60)
    message = models.TextField("сообщение")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="пользователь", on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField("создано", auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "событие заказа"
        verbose_name_plural = "история движения заказов"


def stock_expiration_for(batch):
    return timezone.now() + timedelta(hours=batch.product.shelf_life_hours or 24)
