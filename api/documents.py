from django_elasticsearch_dsl import Document, fields
from django_elasticsearch_dsl.registries import registry
from elasticsearch_dsl import analyzer, token_filter

from .models import Author, Book, Bookshelf, Subject


autocomplete_filter = token_filter(
    "book_autocomplete_filter",
    "edge_ngram",
    min_gram=1,
    max_gram=20,
)

autocomplete_analyzer = analyzer(
    "book_autocomplete",
    tokenizer="standard",
    filter=["lowercase", "asciifolding", autocomplete_filter],
)

autocomplete_search_analyzer = analyzer(
    "book_autocomplete_search",
    tokenizer="standard",
    filter=["lowercase", "asciifolding"],
)


@registry.register_document
class BookDocument(Document):
    title = fields.TextField(
        analyzer="standard",
        fields={
            "keyword": fields.KeywordField(),
            "autocomplete": fields.TextField(
                analyzer=autocomplete_analyzer,
                search_analyzer=autocomplete_search_analyzer,
            ),
        },
    )
    authors = fields.NestedField(
        properties={
            "name": fields.TextField(
                analyzer="standard",
                fields={
                    "autocomplete": fields.TextField(
                        analyzer=autocomplete_analyzer,
                        search_analyzer=autocomplete_search_analyzer,
                    )
                },
            ),
            "birth_year": fields.IntegerField(),
            "death_year": fields.IntegerField(),
            "aliases": fields.TextField(analyzer="standard", multi=True),
        }
    )
    subjects = fields.TextField(
        analyzer="standard",
        multi=True,
        fields={"keyword": fields.KeywordField()},
    )
    bookshelves = fields.TextField(
        analyzer="standard",
        multi=True,
        fields={"keyword": fields.KeywordField()},
    )
    reading_ease_level = fields.KeywordField()

    class Index:
        name = "gutenberg_books"
        settings = {
            "number_of_shards": 1,
            "number_of_replicas": 0,
        }

    class Django:
        model = Book
        queryset_pagination = 1000
        fields = [
            "id",
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
        ]
        related_models = [Author, Subject, Bookshelf]

    def get_queryset(self):
        return (
            super()
            .get_queryset()
            .prefetch_related("authors", "subjects", "bookshelves")
        )

    def get_instances_from_related(self, related_instance):
        if isinstance(related_instance, Author):
            return related_instance.books.all()
        if isinstance(related_instance, Subject):
            return related_instance.books.all()
        if isinstance(related_instance, Bookshelf):
            return related_instance.books.all()

    def prepare_authors(self, instance):
        return [
            {
                "name": a.name,
                "birth_year": a.birth_year,
                "death_year": a.death_year,
                "aliases": a.aliases,
            }
            for a in instance.authors.all()
        ]

    def prepare_subjects(self, instance):
        return [s.name for s in instance.subjects.all()]

    def prepare_bookshelves(self, instance):
        return [b.name for b in instance.bookshelves.all()]
