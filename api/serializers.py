from rest_framework import serializers

from .models import Author, Book, BookFormat, Bookshelf, ContactUs, UserBook


class ChildBookshelfSerializer(serializers.ModelSerializer):
    class Meta:
        model = Bookshelf
        fields = ["id", "name"]


class BookshelfSerializer(serializers.ModelSerializer):
    children = ChildBookshelfSerializer(many=True, read_only=True, source="sub_bookshelves")

    class Meta:
        model = Bookshelf
        fields = ["id", "name", "children"]


class AuthorSerializer(serializers.ModelSerializer):
    class Meta:
        model = Author
        fields = ["id", "name", "birth_year", "death_year", "aliases", "wikipedia_url"]


class BookFormatSerializer(serializers.ModelSerializer):
    class Meta:
        model = BookFormat
        fields = ["mime_type", "url", "size", "modified"]


class BookSummarySerializer(serializers.ModelSerializer):
    authors = serializers.SerializerMethodField()
    bookshelves = serializers.SlugRelatedField(
        many=True, read_only=True, slug_field="name"
    )

    class Meta:
        model = Book
        fields = [
            "id",
            "title",
            "language",
            "downloads",
            "issued_date",
            "cover_url",
            "authors",
            "bookshelves",
        ]

    def get_authors(self, obj):
        return [{"name": a.name} for a in obj.authors.all()]


class BookDetailSerializer(serializers.ModelSerializer):
    authors = AuthorSerializer(many=True)
    subjects = serializers.SlugRelatedField(
        many=True, read_only=True, slug_field="name"
    )
    bookshelves = serializers.SlugRelatedField(
        many=True, read_only=True, slug_field="name"
    )
    formats = BookFormatSerializer(many=True)

    class Meta:
        model = Book
        fields = [
            "id",
            "title",
            "language",
            "downloads",
            "issued_date",
            "rights",
            "content_type",
            "description",
            "summary",
            "transcribers",
            "reading_ease",
            "cover_url",
            "authors",
            "subjects",
            "bookshelves",
            "formats",
        ]


class UserBookSerializer(serializers.ModelSerializer):
    book = BookSummarySerializer()

    class Meta:
        model = UserBook
        fields = ["book", "status", "progress", "started_at", "last_read_at"]


class ContactUsSerializer(serializers.ModelSerializer):
    class Meta:
        model = ContactUs
        fields = ["reference", "category", "message", "created_at"]
        read_only_fields = ["reference", "created_at"]
