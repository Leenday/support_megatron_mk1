from django.core.management.base import BaseCommand, CommandError

from support.models import ApiToken, User


class Command(BaseCommand):
    help = "Issue a personal API token for a user (#42). The token is printed once, not stored."

    def add_arguments(self, parser):
        parser.add_argument("username")
        parser.add_argument("--name", default="script", help="What the token is for")

    def handle(self, *args, username: str, name: str, **options):
        try:
            user = User.objects.get(username=username, is_active=True)
        except User.DoesNotExist as e:
            raise CommandError(f"no active user {username!r}") from e
        _, key = ApiToken.issue(user, name)
        self.stdout.write(key)
        self.stderr.write("Save it now: only its hash is kept. Revoke it in the admin.")
