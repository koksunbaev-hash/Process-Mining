from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import UserProfile
from apps.bakery.models import (
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
)
from apps.bakery.services import confirm_order, move_batch
from apps.nonconformities.models import DefectType, Nonconformity, NonconformityCause
from apps.quality.models import ControlPost, ControlType, Department, QualityObject


class Command(BaseCommand):
    help = "Создаёт демонстрационные данные хлебозавода."

    def add_arguments(self, parser):
        parser.add_argument("--reset-passwords", action="store_true")

    @transaction.atomic
    def handle(self, *args, **options):
        users = self.create_users(reset_passwords=options["reset_passwords"])
        self.create_stages()
        products = self.create_products()
        ingredients = self.create_ingredients()
        village_recipe = self.create_recipes(products, ingredients, users["technologist"])
        customers = self.create_customers()
        self.create_orders(customers, products, village_recipe, users)
        self.cleanup_non_bakery_demo_problem()
        self.create_demo_problem(users)
        self.create_demo_stock(users["warehouse"])
        self.stdout.write(self.style.SUCCESS("Данные хлебозавода созданы."))
        self.stdout.write("Логины:")
        for username, password in self.login_pairs:
            self.stdout.write(f"  {username} / {password}")

    @property
    def login_pairs(self):
        return [
            ("admin", "Admin123!"),
            ("dispatcher", "Dispatch123!"),
            ("technologist", "Tech123!"),
            ("mixing", "Mix123!"),
            ("forming", "Form123!"),
            ("proofing", "Proof123!"),
            ("oven", "Oven123!"),
            ("warehouse", "Stock123!"),
            ("manager", "Manager123!"),
            ("auditor", "Auditor123!"),
        ]

    def create_users(self, reset_passwords=False):
        User = get_user_model()
        dept, _ = Department.objects.get_or_create(code="BAKERY", defaults={"name": "Хлебозавод"})
        specs = [
            ("admin", "Admin123!", UserProfile.Role.ADMIN, True, True),
            ("dispatcher", "Dispatch123!", UserProfile.Role.PRODUCTION_DISPATCHER, False, True),
            ("technologist", "Tech123!", UserProfile.Role.TECHNOLOGIST, False, True),
            ("mixing", "Mix123!", UserProfile.Role.MIXING_OPERATOR, False, False),
            ("forming", "Form123!", UserProfile.Role.FORMING_OPERATOR, False, False),
            ("proofing", "Proof123!", UserProfile.Role.PROOFING_OPERATOR, False, False),
            ("oven", "Oven123!", UserProfile.Role.OVEN_OPERATOR, False, False),
            ("warehouse", "Stock123!", UserProfile.Role.WAREHOUSE_WORKER, False, False),
            ("manager", "Manager123!", UserProfile.Role.MANAGER, False, True),
            ("auditor", "Auditor123!", UserProfile.Role.AUDITOR, False, False),
        ]
        users = {}
        for username, password, role, is_superuser, is_staff in specs:
            group, _ = Group.objects.get_or_create(name=dict(UserProfile.Role.choices).get(role, role))
            user, created = User.objects.get_or_create(username=username, defaults={"is_superuser": is_superuser, "is_staff": is_staff})
            if created or reset_passwords:
                user.set_password(password)
                user.save()
            user.groups.add(group)
            user.profile.role = role
            user.profile.department = dept
            user.profile.save()
            users[username] = user
        return users

    def create_stages(self):
        for seq, (code, name) in enumerate([
            ("queue", "Очередь"),
            ("mixing", "Замес"),
            ("forming", "Формовка"),
            ("proofing", "Расстойка"),
            ("oven", "Печь"),
            ("warehouse", "Склад"),
            ("done", "Готово"),
        ], start=1):
            ProductionStage.objects.update_or_create(code=code, defaults={"name": name, "sequence": seq, "is_active": True})

    def create_products(self):
        specs = [
            ("ZHAILY", "Хлеб Жайлы", "bread", "0.520", 36, 220, 34, 55, 16),
            ("RYE-SANDWICH", "Сэндвич Ржаной", "sandwich", "0.420", 48, 210, 28, 45, 14),
            ("PARTY", "Хлеб «Партийный»", "bread", "0.500", 36, 220, 32, 50, 15),
            ("BURGER-BUN", "Булочка для гамбургера", "bun", "0.085", 36, 200, 12, 40, 12),
            ("FORM", "Хлеб «Формовой»", "bread", "0.450", 36, 220, 32, 50, 15),
            ("MALT-SEED", "Хлеб «Солодовый» с семечками нарезанный", "bread", "0.430", 48, 215, 30, 52, 15),
            ("MINI", "Хлеб «Мини»", "bread", "0.250", 36, 220, 24, 42, 12),
            ("VERNENSKY", "Батон «Верненский»", "loaf", "0.380", 36, 210, 25, 45, 13),
            ("FAMILY", "Хлеб «Семейный»", "bread", "0.550", 36, 220, 35, 55, 16),
            ("TOAST", "Тостовый хлеб нарезанный", "toast", "0.500", 72, 200, 35, 60, 18),
            ("PANINI", "Сэндвич Панини", "sandwich", "0.120", 48, 205, 15, 42, 12),
            ("DIET", "Хлеб «Диетический»", "bread", "0.400", 48, 210, 30, 50, 14),
            ("BRAN-TOAST", "Тостовый хлеб отрубной нарезанный", "toast", "0.500", 72, 200, 35, 60, 18),
            ("SPORT", "Хлеб «Спорт Актив»", "bread", "0.430", 48, 215, 30, 52, 15),
            ("BAGUETTE", "Багет «Новый»", "baguette", "0.280", 24, 230, 22, 35, 12),
            ("VILLAGE", "Хлеб «Деревенский»", "bread", "0.450", 36, 220, 32, 50, 15),
            ("SLAVYANSKY", "Хлеб «Славянский»", "bread", "0.720", 36, 220, 34, 50, 15),
        ]
        products = {}
        for code, name, category, weight, shelf_life, temperature, baking, proofing, mixing in specs:
            product, _ = Product.objects.update_or_create(
                code=code,
                defaults={
                    "name": name,
                    "description": "Хлебобулочное изделие основного ассортимента хлебозавода.",
                    "category": category,
                    "unit": "шт",
                    "weight_per_item": Decimal(weight),
                    "shelf_life_hours": shelf_life,
                    "baking_temperature": temperature,
                    "baking_duration_minutes": baking,
                    "proofing_duration_minutes": proofing,
                    "mixing_duration_minutes": mixing,
                    "is_active": True,
                },
            )
            products[code] = product
        return products

    def create_ingredients(self):
        specs = [
            ("FLOUR-W1", "Мука пшеничная 1 сорт", "кг", "800", "200"),
            ("FLOUR-HG", "Мука пшеничная высший сорт", "кг", "650", "150"),
            ("FLOUR-RYE", "Мука ржаная", "кг", "420", "120"),
            ("BRAN", "Отруби пшеничные", "кг", "80", "20"),
            ("MALT", "Солод", "кг", "60", "20"),
            ("SUNFLOWER", "Семечки подсолнечные", "кг", "70", "20"),
            ("YEAST", "Дрожжи", "кг", "45", "15"),
            ("SALT", "Соль", "кг", "80", "20"),
            ("GLUTEN", "Глютен", "кг", "30", "10"),
            ("WATER", "Вода", "л", "5000", "1000"),
            ("ICE", "Лёд", "кг", "200", "50"),
            ("IMPROVER", "Улучшитель", "кг", "12", "5"),
            ("KAZENZYM", "KAZENZYM 260097", "кг", "10", "2"),
            ("SORBIC", "Сорбиновая кислота", "кг", "5", "2"),
            ("VINEGAR", "Уксус", "л", "18", "5"),
            ("EMUL", "Эмульгатор", "кг", "7", "2"),
            ("EMCEPROP", "EMCEprop G", "кг", "8", "2"),
            ("MARGARINE", "Маргарин", "кг", "90", "20"),
            ("SUGAR", "Сахар", "кг", "120", "30"),
        ]
        ingredients = {}
        for code, name, unit, stock, minimum in specs:
            ingredient, _ = Ingredient.objects.update_or_create(
                code=code,
                defaults={
                    "name": name,
                    "unit": unit,
                    "current_stock": Decimal(stock),
                    "minimum_stock": Decimal(minimum),
                    "supplier": "Основной поставщик",
                    "is_active": True,
                },
            )
            ingredients[code] = ingredient
        return ingredients

    def create_recipes(self, products, ingredients, technologist):
        def upsert_recipe(product_code, title, rows):
            recipe, _ = Recipe.objects.update_or_create(
                product=products[product_code],
                version="1.0",
                defaults={
                    "name": title,
                    "output_quantity": Decimal("100"),
                    "output_unit": "шт",
                    "is_active": True,
                    "approved_by": technologist,
                    "approved_at": timezone.now(),
                },
            )
            for seq, (ingredient_code, quantity) in enumerate(rows, start=1):
                RecipeItem.objects.update_or_create(
                    recipe=recipe,
                    ingredient=ingredients[ingredient_code],
                    defaults={"quantity_for_batch": Decimal(quantity), "sequence": seq},
                )
            return recipe

        village = upsert_recipe("VILLAGE", "Рецептура хлеба «Деревенский»", [
            ("FLOUR-W1", "25.287"), ("FLOUR-RYE", "22.643"), ("MALT", "0.919"), ("YEAST", "0.919"),
            ("SALT", "0.574"), ("GLUTEN", "0.195"), ("WATER", "16.091"), ("ICE", "5.747"),
            ("IMPROVER", "0.014"), ("SORBIC", "0.022"), ("VINEGAR", "0.045"), ("EMUL", "0.047"),
        ])
        recipes = {
            "SLAVYANSKY": [("FLOUR-W1", "44.600"), ("YEAST", "0.900"), ("SALT", "0.720"), ("KAZENZYM", "0.013"), ("WATER", "20.000"), ("ICE", "5.900"), ("MARGARINE", "0.500"), ("SUGAR", "0.420"), ("SORBIC", "0.023"), ("VINEGAR", "0.046"), ("EMCEPROP", "0.044")],
            "ZHAILY": [("FLOUR-W1", "38.000"), ("YEAST", "0.820"), ("SALT", "0.650"), ("WATER", "18.500"), ("ICE", "4.800"), ("IMPROVER", "0.050")],
            "RYE-SANDWICH": [("FLOUR-W1", "24.000"), ("FLOUR-RYE", "18.000"), ("YEAST", "0.850"), ("SALT", "0.620"), ("WATER", "19.000"), ("MARGARINE", "0.800"), ("SUGAR", "0.900")],
            "PARTY": [("FLOUR-W1", "40.000"), ("YEAST", "0.850"), ("SALT", "0.680"), ("WATER", "19.500"), ("ICE", "4.500"), ("IMPROVER", "0.040")],
            "BURGER-BUN": [("FLOUR-HG", "9.000"), ("YEAST", "0.350"), ("SALT", "0.160"), ("WATER", "4.000"), ("MARGARINE", "0.700"), ("SUGAR", "0.900")],
            "FORM": [("FLOUR-W1", "36.000"), ("YEAST", "0.800"), ("SALT", "0.650"), ("WATER", "18.000"), ("ICE", "4.000"), ("IMPROVER", "0.040")],
            "MALT-SEED": [("FLOUR-W1", "30.000"), ("FLOUR-RYE", "10.000"), ("MALT", "1.200"), ("SUNFLOWER", "3.000"), ("YEAST", "0.850"), ("SALT", "0.650"), ("WATER", "19.000")],
            "MINI": [("FLOUR-W1", "22.000"), ("YEAST", "0.520"), ("SALT", "0.380"), ("WATER", "11.000"), ("ICE", "2.200"), ("IMPROVER", "0.025")],
            "VERNENSKY": [("FLOUR-HG", "34.000"), ("YEAST", "0.750"), ("SALT", "0.600"), ("WATER", "16.500"), ("MARGARINE", "0.900"), ("SUGAR", "1.200")],
            "FAMILY": [("FLOUR-W1", "42.000"), ("YEAST", "0.900"), ("SALT", "0.720"), ("WATER", "21.000"), ("ICE", "5.000"), ("IMPROVER", "0.050")],
            "TOAST": [("FLOUR-HG", "36.000"), ("YEAST", "0.900"), ("SALT", "0.620"), ("WATER", "17.000"), ("MARGARINE", "1.100"), ("SUGAR", "1.400"), ("EMUL", "0.050")],
            "PANINI": [("FLOUR-HG", "12.000"), ("YEAST", "0.400"), ("SALT", "0.220"), ("WATER", "5.600"), ("MARGARINE", "0.500"), ("SUGAR", "0.350")],
            "DIET": [("FLOUR-W1", "25.000"), ("BRAN", "8.000"), ("YEAST", "0.700"), ("SALT", "0.520"), ("WATER", "17.000"), ("GLUTEN", "0.250")],
            "BRAN-TOAST": [("FLOUR-HG", "30.000"), ("BRAN", "6.000"), ("YEAST", "0.850"), ("SALT", "0.620"), ("WATER", "17.500"), ("MARGARINE", "0.900"), ("EMUL", "0.050")],
            "SPORT": [("FLOUR-W1", "27.000"), ("BRAN", "5.000"), ("SUNFLOWER", "4.000"), ("GLUTEN", "0.400"), ("YEAST", "0.820"), ("SALT", "0.600"), ("WATER", "18.000")],
            "BAGUETTE": [("FLOUR-HG", "24.000"), ("YEAST", "0.620"), ("SALT", "0.450"), ("WATER", "12.800"), ("IMPROVER", "0.030")],
        }
        for product_code, rows in recipes.items():
            upsert_recipe(product_code, f"Рецептура: {products[product_code].name}", rows)
        return village

    def create_customers(self):
        customers = []
        for name, phone in [
            ("ТОО Магазин У дома", "+7 700 100 10 10"),
            ("Сеть Маркет Fresh", "+7 700 200 20 20"),
            ("Кафе Центральное", "+7 700 300 30 30"),
        ]:
            customer, _ = Customer.objects.get_or_create(name=name, defaults={"phone": phone, "address": "Кызылорда", "is_active": True})
            customers.append(customer)
        return customers

    def create_orders(self, customers, products, recipe, users):
        for idx, customer in enumerate(customers, start=1):
            order, _ = ProductionOrder.objects.get_or_create(
                order_number=f"6{idx}",
                defaults={
                    "customer": customer,
                    "required_date": timezone.now() + timedelta(hours=idx * 4),
                    "priority": "urgent" if idx == 1 else "normal",
                    "status": "draft",
                    "created_by": users["dispatcher"],
                },
            )
            ProductionOrderItem.objects.get_or_create(order=order, product=products["VILLAGE"], defaults={"quantity": Decimal("500"), "unit": "шт", "recipe": recipe})
            batches = list(ProductionBatch.objects.filter(order_item__order=order).order_by("id"))
            if order.status == ProductionOrder.Status.DRAFT or not batches:
                batches = confirm_order(order, user=users["dispatcher"], assignee=users["mixing"])
            if idx == 2 and batches:
                self.move_batch_if_before(batches[0], "mixing", users["dispatcher"], "Старт замеса")
            if idx == 3 and batches:
                self.move_batch_if_before(batches[0], "mixing", users["dispatcher"], "Старт")
                self.move_batch_if_before(batches[0], "forming", users["dispatcher"], "Передано на формовку")

    def move_batch_if_before(self, batch, stage_code, user, comment):
        target_stage = ProductionStage.objects.get(code=stage_code)
        if batch.current_stage.sequence < target_stage.sequence:
            move_batch(batch, target_stage, user, comment)

    def create_demo_problem(self, users):
        dept, _ = Department.objects.get_or_create(code="BAKERY", defaults={"name": "Хлебозавод"})
        control_type, _ = ControlType.objects.get_or_create(code="bakery-problem", defaults={"name": "Производственная проблема"})
        post, _ = ControlPost.objects.get_or_create(
            code="BAKERY-NC",
            defaults={"name": "Контроль хлебозавода", "department": dept, "control_type": control_type, "sequence": 1},
        )
        defect, _ = DefectType.objects.get_or_create(code="DOUGH-CONSISTENCY", defaults={"name": "неправильная консистенция теста", "category": "хлебозавод", "criticality": "critical", "object_block_required": True})
        NonconformityCause.objects.get_or_create(name="Нарушение рецептуры", category="хлебозавод")
        qobj, _ = QualityObject.objects.get_or_create(unique_number="BAKERY-DEMO", defaults={"object_type": "finished_product", "product_name": "Хлеб «Деревенский»", "quantity": 1, "department": dept, "created_by": users["dispatcher"]})
        batch = ProductionBatch.objects.first()
        if batch:
            _, created = Nonconformity.objects.get_or_create(
                quality_object=qobj,
                defect_type=defect,
                bakery_batch=batch,
                defaults={
                    "control_post": post,
                    "detected_by": users["mixing"],
                    "description": "Тесто плотнее нормы, партия остановлена до решения технолога.",
                    "criticality": "critical",
                    "affected_quantity": 1,
                    "responsible_department": dept,
                    "responsible_user": users["technologist"],
                    "bakery_order": batch.order_item.order,
                    "bakery_product": batch.product,
                    "bakery_stage": batch.current_stage,
                },
            )
            if created:
                batch.status = "problem"
                batch.save(update_fields=["status", "updated_at"])

    def cleanup_non_bakery_demo_problem(self):
        self.stdout.write("Очистка старых несоответствий пропущена: связанные данные сохраняются.")

    def create_demo_stock(self, warehouse_user):
        warehouse_batch = ProductionBatch.objects.exclude(status="problem").last()
        if warehouse_batch:
            FinishedGoodsStock.objects.get_or_create(
                batch=warehouse_batch,
                defaults={
                    "product": warehouse_batch.product,
                    "quantity": warehouse_batch.planned_quantity,
                    "unit": warehouse_batch.unit,
                    "expiration_date": timezone.now() + timedelta(hours=36),
                    "warehouse_location": "A-01",
                    "received_by": warehouse_user,
                },
            )
