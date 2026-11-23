from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models
from django.db.models.functions import Lower


class UserManager(BaseUserManager):
    use_in_migrations = True

    def _create_user(self, email, password, **extra):
        if not email:
            raise ValueError("El email es obligatorio")
        email = self.normalize_email(email).lower()
        user = self.model(email=email, **extra)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra):
        extra.setdefault("is_staff", False)
        extra.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra)

    def create_superuser(self, email, password=None, **extra):
        extra.setdefault("is_staff", True)
        extra.setdefault("is_superuser", True)
        return self._create_user(email, password, **extra)


AVATAR_COLORS = [
    "#0052CC", "#00875A", "#FF5630", "#6554C0", "#FF991F",
    "#00B8D9", "#36B37E", "#DE350B", "#5243AA", "#172B4D",
]


class User(AbstractUser):
    username = None
    first_name = None
    last_name = None
    email = models.EmailField("email", unique=True)
    full_name = models.CharField(max_length=150, blank=True)
    avatar = models.ImageField(upload_to="avatars/", blank=True, null=True)
    job_title = models.CharField(max_length=120, blank=True)
    timezone = models.CharField(max_length=64, default="America/Lima")
    locale = models.CharField(max_length=10, default="es")
    external_id = models.CharField(
        max_length=255, blank=True, db_index=True,
        help_text="Id en el proveedor de identidad (SCIM)",
    )
    is_bot = models.BooleanField(
        default=False, help_text="Cuenta de sistema (automatización). No puede iniciar sesión."
    )

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS: list[str] = []

    objects = UserManager()

    class Meta:
        ordering = ["full_name", "email"]
        constraints = [models.UniqueConstraint(Lower("email"), name="user_email_ci_unique")]

    def __str__(self) -> str:
        return self.display_name

    @property
    def display_name(self) -> str:
        return self.full_name or self.email.split("@")[0]

    @property
    def initials(self) -> str:
        parts = self.display_name.replace(".", " ").split()
        return "".join(p[0] for p in parts[:2]).upper() or "?"

    @property
    def avatar_color(self) -> str:
        return AVATAR_COLORS[(self.pk or 0) % len(AVATAR_COLORS)]


class ApiToken(models.Model):
    """Machine credential (e.g. SCIM provisioning from Entra ID / Okta). Only the hash is
    stored; the clear token is shown once when created."""

    name = models.CharField(max_length=120)
    prefix = models.CharField(max_length=12, help_text="Primeros caracteres, para identificarlo")
    token_hash = models.CharField(max_length=64, unique=True)
    scopes = models.JSONField(default=list)
    created_by = models.ForeignKey("accounts.User", null=True, on_delete=models.SET_NULL,
                                   related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.name} ({self.prefix}…)"
