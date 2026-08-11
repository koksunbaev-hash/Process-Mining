from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import UserProfile
from apps.equipment.models import MeasuringEquipment
from apps.inspections.services import start_task
from apps.nonconformities.models import DefectType, NonconformityCause
from apps.nonconformities.services import register_nonconformity
from apps.quality.models import (
    ControlParameter,
    ControlPost,
    ControlRoute,
    ControlRouteStep,
    ControlType,
    Department,
    InspectionTemplate,
    InspectionTemplateParameter,
    QualityObject,
)
from apps.quality.services import create_quality_object_with_route


class Command(BaseCommand):
    help = "Создаёт демонстрационные данные QMS."

    @transaction.atomic
    def handle(self, *args, **options):
        User = get_user_model()
        # Группы Django остались названы должностями: они описывают, чем человек
        # занят, и по ним удобно рассылать. Права из них не берутся - их
        # определяет роль профиля, а ролей теперь три.
        for name in [
            "Администратор QMS",
            "Руководитель службы качества",
            "Инженер по качеству",
            "Контролёр ОТК",
            "Производственный мастер",
            "Ответственный исполнитель",
            "Руководитель предприятия",
            "Аудитор",
        ]:
            Group.objects.get_or_create(name=name)

        dept_quality, _ = Department.objects.get_or_create(code="QCD", defaults={"name": "Служба качества"})
        dept_prod, _ = Department.objects.get_or_create(code="PRD", defaults={"name": "Производство"})

        users = [
            ("admin", "Admin123!", UserProfile.Role.ADMIN, True, True, dept_quality),
            ("quality_manager", "Quality123!", UserProfile.Role.MANAGER, False, False, dept_quality),
            ("inspector", "Inspector123!", UserProfile.Role.USER, False, False, dept_quality),
            ("master", "Master123!", UserProfile.Role.USER, False, False, dept_prod),
            ("auditor", "Auditor123!", UserProfile.Role.USER, False, False, dept_quality),
        ]
        created_users = {}
        for username, password, role, is_superuser, is_staff, department in users:
            user, created = User.objects.get_or_create(username=username, defaults={"is_staff": is_staff, "is_superuser": is_superuser})
            if created:
                user.set_password(password)
                user.save()
            user.profile.role = role
            user.profile.department = department
            user.profile.save()
            created_users[username] = user

        control_types = [
            ("incoming", "входной"), ("operational", "операционный"), ("visual", "визуальный"),
            ("measuring", "измерительный"), ("welding", "сварочный"), ("hydraulic", "гидравлический"),
            ("pneumatic", "пневматический"), ("coating", "контроль покрытия"), ("assembly", "контроль сборки"),
            ("final", "финальный"), ("sample", "выборочный"), ("full", "сплошной"), ("lab", "лабораторный"),
            ("document", "документарный"),
        ]
        types = {}
        for code, name in control_types:
            types[code], _ = ControlType.objects.get_or_create(code=code, defaults={"name": name})

        post_specs = [
            ("P01", "Входной контроль материалов и комплектующих", "incoming"),
            ("P02", "Контроль после механической обработки", "measuring"),
            ("P03", "Контроль качества сварки", "welding"),
            ("P04", "Гидравлические испытания", "hydraulic"),
            ("P05", "Контроль после дробеструйной обработки", "visual"),
            ("P06", "Контроль после покраски", "coating"),
            ("P07", "Контроль сборки изделия или модуля", "assembly"),
            ("P08", "Пневматические испытания", "pneumatic"),
            ("P09", "Контроль после заправки модуля", "operational"),
            ("P10", "Финальный контроль и упаковка", "final"),
        ]
        posts = []
        for index, (code, name, type_code) in enumerate(post_specs, start=1):
            post, _ = ControlPost.objects.get_or_create(
                code=code,
                defaults={
                    "name": name,
                    "department": dept_quality,
                    "responsible_user": created_users["inspector"],
                    "control_type": types[type_code],
                    "sequence": index,
                    "normative_duration_minutes": 120,
                    "escalation_minutes": 240,
                },
            )
            posts.append(post)

        param_specs = {
            "P01": [("CERT", "наличие сертификата", "conformity", ""), ("QTY", "количество", "number", "шт"), ("VISD", "визуальные повреждения", "conformity", ""), ("SIZE", "геометрический размер", "number", "мм")],
            "P03": [("WLOOK", "внешний вид шва", "conformity", ""), ("WLEN", "длина шва", "number", "мм"), ("WWID", "ширина шва", "number", "мм"), ("CRACK", "наличие трещин", "conformity", ""), ("PORE", "наличие пор", "conformity", "")],
            "P04": [("TPRESS", "испытательное давление", "number", "МПа"), ("SPRESS", "начальное давление", "number", "МПа"), ("EPRESS", "конечное давление", "number", "МПа"), ("DUR", "продолжительность", "number", "мин"), ("TEMP", "температура", "number", "C"), ("LEAK", "наличие течи", "conformity", "")],
            "P06": [("THICK", "толщина покрытия", "number", "мкм"), ("UNIF", "равномерность", "conformity", ""), ("COLOR", "цвет", "text", ""), ("ADH", "адгезия", "conformity", ""), ("RUNS", "наличие подтёков", "conformity", "")],
            "P10": [("COMP", "комплектность", "conformity", ""), ("MARK", "маркировка", "conformity", ""), ("DOCS", "документация", "conformity", ""), ("PACK", "упаковка", "conformity", ""), ("MASS", "масса", "number", "кг"), ("SHIP", "разрешение на отгрузку", "conclusion", "")],
        }
        default_params = [("VISUAL", "визуальный осмотр", "conformity", ""), ("DIM", "контрольный размер", "number", "мм")]
        templates = {}
        for post in posts:
            template, _ = InspectionTemplate.objects.get_or_create(
                code=f"TPL-{post.code}",
                defaults={"name": f"Карта: {post.name}", "control_post": post, "control_type": post.control_type, "product_type": "MVP", "approved_by": created_users["quality_manager"], "approved_at": timezone.now()},
            )
            templates[post.code] = template
            for seq, (suffix, name, value_type, unit) in enumerate(param_specs.get(post.code, default_params), start=1):
                criticality = "critical" if suffix in {"CRACK", "LEAK", "SHIP"} else "medium"
                parameter, _ = ControlParameter.objects.get_or_create(
                    code=f"{post.code}-{suffix}",
                    defaults={
                        "name": name,
                        "unit": unit,
                        "value_type": value_type,
                        "lower_limit": 10 if value_type == "number" else None,
                        "upper_limit": 100 if value_type == "number" else None,
                        "nominal_value": 50 if value_type == "number" else None,
                        "criticality": criticality,
                        "requires_photo": suffix in {"VISD", "CRACK", "LEAK"},
                    },
                )
                InspectionTemplateParameter.objects.get_or_create(template=template, parameter=parameter, defaults={"sequence": seq})

        route, _ = ControlRoute.objects.get_or_create(code="ROUTE-MODULE", defaults={"name": "Маршрут модуля", "product_type": "module"})
        route2, _ = ControlRoute.objects.get_or_create(code="ROUTE-INCOMING", defaults={"name": "Маршрут входного контроля", "product_type": "material"})
        for seq, post in enumerate(posts, start=1):
            ControlRouteStep.objects.get_or_create(route=route, sequence=seq, defaults={"control_post": post, "inspection_template": templates[post.code], "normative_duration_minutes": 120})
        ControlRouteStep.objects.get_or_create(route=route2, sequence=1, defaults={"control_post": posts[0], "inspection_template": templates["P01"], "normative_duration_minutes": 60})

        MeasuringEquipment.objects.get_or_create(
            serial_number="MI-001",
            defaults={"name": "Штангенциркуль", "equipment_type": "измерительный инструмент", "department": dept_quality, "responsible_user": created_users["inspector"], "next_verification_date": timezone.localdate() + timedelta(days=180), "status": "available"},
        )
        MeasuringEquipment.objects.get_or_create(
            serial_number="MI-019",
            defaults={"name": "Манометр", "equipment_type": "манометр", "department": dept_quality, "responsible_user": created_users["inspector"], "next_verification_date": timezone.localdate() - timedelta(days=3), "status": "available"},
        )

        for code, name, criticality, block in [
            ("WELD-CRACK", "Трещина сварного шва", "critical", True),
            ("PAINT-LOW", "Толщина покрытия ниже допуска", "high", False),
            ("DOC-MISS", "Отсутствует документ", "medium", False),
        ]:
            DefectType.objects.get_or_create(code=code, defaults={"name": name, "category": "производство", "criticality": criticality, "object_block_required": block, "manager_notification_required": block})
        for category in [
            "дефект материала", "ошибка поставщика", "нарушение технологии", "ошибка оператора", "неисправность оборудования",
            "неправильная настройка", "нарушение инструкции", "нарушение хранения", "неисправность средства измерения",
            "повреждение при транспортировке", "ошибка документации", "причина не установлена",
        ]:
            NonconformityCause.objects.get_or_create(name=category, category=category)

        obj1, _ = QualityObject.objects.get_or_create(
            unique_number="MOD-3321",
            defaults={"object_type": "module", "product_name": "Модуль гидравлический", "serial_number": "SN-008184", "quantity": 1, "department": dept_prod, "route": route, "created_by": created_users["admin"]},
        )
        if not obj1.tasks.exists():
            create_quality_object_with_route(
                user=created_users["admin"],
                unique_number="MAT-2026-041",
                object_type="material_batch",
                product_name="Партия комплектующих",
                batch_number="MAT-2026-041",
                quantity=24,
                department=dept_prod,
                route=route2,
                supplier="Demo Supplier",
            )
        if not obj1.current_route_step:
            first = route.steps.first()
            obj1.current_route_step = first
            obj1.current_control_post = first.control_post
            obj1.quality_status = "awaiting_control"
            obj1.save()
            from apps.quality.services import create_inspection_task_for_step

            create_inspection_task_for_step(obj1, first, user=created_users["admin"])

        first_task = obj1.tasks.first()
        if first_task and not hasattr(first_task, "card"):
            start_task(first_task, created_users["inspector"])

        if not obj1.nonconformities.exists():
            register_nonconformity(
                user=created_users["inspector"],
                quality_object=obj1,
                inspection_card=getattr(first_task, "card", None),
                control_post=first_task.control_post,
                defect_type=DefectType.objects.get(code="WELD-CRACK"),
                description="Демонстрационное критическое несоответствие.",
                criticality="critical",
                affected_quantity=1,
                responsible_department=dept_prod,
                responsible_user=created_users["master"],
            )

        self.stdout.write(self.style.SUCCESS("Демо-данные QMS созданы."))
        self.stdout.write("Логины:")
        for username, password, *_ in users:
            self.stdout.write(f"  {username} / {password}")
