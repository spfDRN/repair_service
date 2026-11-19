from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Устанавливает демонстрационный пароль всем пользователям (после загрузки фикстуры)."

    def add_arguments(self, parser):
        parser.add_argument("--password", default="demo12345")

    def handle(self, *args, **options):
        users = get_user_model().objects.all()
        for user in users:
            user.set_password(options["password"])
            user.save(update_fields=["password"])
        self.stdout.write(self.style.SUCCESS(f"Пароль обновлён у {users.count()} пользователей."))