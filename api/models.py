import uuid

from django.contrib.auth.models import (
    AbstractBaseUser,
    BaseUserManager,
    PermissionsMixin,
)
from django.db import models


class Author(models.Model):
    id = models.IntegerField(primary_key=True)
    name = models.CharField(max_length=500)
    birth_year = models.IntegerField(null=True, blank=True)
    death_year = models.IntegerField(null=True, blank=True)
    aliases = models.JSONField(default=list, blank=True)
    wikipedia_url = models.URLField(max_length=500, blank=True)

    class Meta:
        db_table = "authors"

    def __str__(self):
        return self.name


class Subject(models.Model):
    name = models.CharField(max_length=1000, unique=True)

    class Meta:
        db_table = "subjects"

    def __str__(self):
        return self.name


class Bookshelf(models.Model):
    name = models.CharField(max_length=500, unique=True)
    parent = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        related_name="sub_bookshelves",
        on_delete=models.CASCADE,
    )

    is_primary = models.BooleanField(default=False)

    class Meta:
        db_table = "bookshelves"

    def __str__(self):
        return self.name


class Book(models.Model):
    id = models.IntegerField(primary_key=True)
    title = models.CharField(max_length=2000)
    language = models.CharField(max_length=20, db_index=True)
    downloads = models.IntegerField(default=0)
    issued_date = models.DateField(null=True, blank=True)
    rights = models.CharField(max_length=200, blank=True)
    content_type = models.CharField(
        max_length=50, blank=True
    )  # DCMIType: Text, Sound, Image, etc.
    description = models.TextField(blank=True)  # joined dcterms:description values
    summary = models.TextField(blank=True)  # marc520 auto-generated summary
    transcribers = models.TextField(blank=True)  # marc508
    reading_ease = models.CharField(max_length=300, blank=True)  # marc908
    cover_url = models.URLField(max_length=500, blank=True)
    authors = models.ManyToManyField(Author, related_name="books", blank=True)
    subjects = models.ManyToManyField(Subject, related_name="books", blank=True)
    bookshelves = models.ManyToManyField(Bookshelf, related_name="books", blank=True)

    class Meta:
        db_table = "books"

    def __str__(self):
        return self.title


class BookFormat(models.Model):
    book = models.ForeignKey(Book, related_name="formats", on_delete=models.CASCADE)
    url = models.URLField(max_length=500)
    mime_type = models.CharField(max_length=100, db_index=True)
    size = models.IntegerField(null=True, blank=True)  # bytes
    modified = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "book_formats"


class UserBook(models.Model):
    READING = "reading"
    COMPLETED = "completed"
    WANT_TO_READ = "want_to_read"

    STATUS_CHOICES = [
        (READING, "Reading"),
        (COMPLETED, "Completed"),
        (WANT_TO_READ, "Want to Read"),
    ]

    user = models.ForeignKey(
        "User", on_delete=models.CASCADE, related_name="user_books"
    )
    book = models.ForeignKey(Book, on_delete=models.CASCADE, related_name="user_books")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES)
    progress = models.FloatField(null=True, blank=True)  # percentage of book read
    last_read_at = models.DateTimeField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "user_books"
        unique_together = [("user", "book")]


class UserManager(BaseUserManager):
    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError("Email is required")
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        return self.create_user(email, password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin):
    email = models.EmailField(unique=True)
    first_name = models.CharField(max_length=150, blank=True)
    last_name = models.CharField(max_length=150, blank=True)
    google_id = models.CharField(max_length=255, unique=True, null=True, blank=True)
    apple_id = models.CharField(max_length=255, unique=True, null=True, blank=True)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    date_joined = models.DateTimeField(auto_now_add=True)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    objects = UserManager()

    class Meta:
        db_table = "users"

    def __str__(self):
        return self.email


class ContactUs(models.Model):
    CATEGORY_CHOICES = [
        ("bug", "Bug"),
        ("feature_request", "Feature Request"),
        ("general", "General"),
        ("other", "Other"),
    ]

    reference = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="contact_us_submissions"
    )
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES)
    message = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "contact_us"

    def __str__(self):
        return f"{self.user.email} - {self.category} ({self.created_at.date()})"
