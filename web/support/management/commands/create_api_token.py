from django.core.management.base import BaseCommand, CommandError

from support.models import ApiToken, User


class Command(BaseCommand):
    help = "Issue a personal API token for a user (#42). The token is printed once, not stored."

    def add_arguments(self, parser):
        account = parser.add_mutually_exclusive_group(required=True)
        account.add_argument("username", nargs="?", help="The user's login name")
        account.add_argument("--email", help="The user's email address")
        parser.add_argument("--name", default="script", help="What the token is for")

    def handle(self, *args, username: str | None, email: str | None, name: str, **options):
        if email is not None:
            email = email.strip()
            if not email:
                raise CommandError("email must not be empty")
        lookup = {"email__iexact": email} if email is not None else {"username": username}
        try:
            user = User.objects.get(is_active=True, **lookup)
        except User.DoesNotExist as e:
            raise CommandError(f"no active user {(email or username)!r}") from e
        _, key = ApiToken.issue(user, name)
        self.stdout.write(key)
        self.stderr.write("Save it now: only its hash is kept. Revoke it in the admin.")
