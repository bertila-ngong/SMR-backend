from django.apps import AppConfig


class PaperlessConfig(AppConfig):
    name = "paperless"
    verbose_name = "UB Record Management"

    def ready(self) -> None:
        from django.contrib.auth.signals import user_login_failed

        from paperless.signals import handle_failed_login

        user_login_failed.connect(handle_failed_login)
        AppConfig.ready(self)
