from django.apps import AppConfig
from django.conf import settings
from django.db.models.signals import post_migrate


def seed(sender, **kwargs) -> None:
    """Give every configured zone a row.

    This runs after each migrate, which covers `serve`, `just manage migrate`,
    and the test database alike. It only adds. A name dropped from the settings
    keeps its row and its rules, and stops being served.
    """
    from dnsrules.rules.models import Group

    for name in settings.RPZ_ZONES:
        Group.objects.get_or_create(name=name)


class RulesConfig(AppConfig):
    name = "dnsrules.rules"

    def ready(self) -> None:
        post_migrate.connect(seed, sender=self)
