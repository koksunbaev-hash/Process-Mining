"""Кто может двигать партии.

Раньше здесь проверялось разделение по этапам: оператор замеса брал партию на
замес, но не мог закрыть формовку, а аудитор не двигал ничего. Ролей оператора
замеса и аудитора больше нет - остались администратор, менеджер и сотрудник, -
и вместе с ними ушло разделение по этапам. Тесты ниже держат то, что осталось:
двигать может любая из трёх ролей, и ни одна не может обойти правила самого
перехода.

Кто именно перевёл партию, по-прежнему записано - `BatchStageHistory` хранит
пользователя, и из этой записи строится карта процесса.
"""

from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase

from apps.accounts.models import UserProfile

from .factories import create_user
from .helpers import WORKFLOW, assert_move_rejected, create_batch_at_stage, move_batch


class BatchPermissionTests(TestCase):
    def test_admin_can_move_any_batch(self):
        user = create_user("admin-flow", UserProfile.Role.ADMIN, is_superuser=True, is_staff=True)
        batch = create_batch_at_stage("oven", user)
        move_batch(batch, "warehouse", user, "ok")
        batch.refresh_from_db()
        self.assertEqual(batch.current_stage.code, "warehouse")

    def test_manager_can_move_batch(self):
        user = create_user("manager-flow", UserProfile.Role.MANAGER)
        batch = create_batch_at_stage("queue", user)
        move_batch(batch, "mixing", user, "ok")
        batch.refresh_from_db()
        self.assertEqual(batch.current_stage.code, "mixing")

    def test_employee_moves_a_batch_through_the_whole_chain(self):
        """Один сотрудник ведёт партию от очереди до готовности.

        Пять почти одинаковых тестов - «оператор замеса берёт замес», «оператор
        печи берёт печь» - описывали разделение, которого не осталось. Здесь то
        же самое одной проверкой и без вымышленных должностей.
        """
        manager = create_user("manager-chain", UserProfile.Role.MANAGER)
        worker = create_user("worker-chain", UserProfile.Role.USER)
        batch = create_batch_at_stage("queue", manager)
        for code in WORKFLOW[1:]:
            move_batch(batch, code, worker, "дальше")
            batch.refresh_from_db()
            self.assertEqual(batch.current_stage.code, code)

    def test_user_without_a_role_cannot_move(self):
        """Единственная проверка прав, которая пережила сведение ролей.

        Пустая роль - это профиль, заведённый в обход приложения. Права он не
        даёт: три роли перечислены явно, и ничего кроме них не подходит.
        """
        stranger = create_user("no-role", UserProfile.Role.USER)
        stranger.profile.role = ""
        stranger.profile.save(update_fields=["role"])
        assert_move_rejected(
            self, create_batch_at_stage("queue", create_user()), "mixing", stranger, PermissionDenied
        )

    def test_backend_blocks_hidden_button_bypass(self):
        """Скрытой кнопки мало - отказ должен приходить с сервера.

        Раньше здесь брали роль, которой перенос не полагался. Теперь роль
        подходит любая, а сервер всё равно отказывает: через этап не шагают,
        сколько бы прав ни было.
        """
        worker = create_user("worker-bypass", UserProfile.Role.USER)
        assert_move_rejected(
            self, create_batch_at_stage("queue", create_user()), "forming", worker, ValidationError, "хочу быстрее"
        )
