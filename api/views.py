import json
import random
import urllib.request

from posthog import capture, new_context
import jwt
from django.conf import settings
from django.core.cache import cache
from elasticsearch_dsl import Q
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token
from jwt.algorithms import RSAAlgorithm
from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from .documents import BookDocument
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from .models import Book, Bookshelf, ContactUs, Highlight, User, UserBook
from .serializers import (
    BookDetailSerializer,
    BookshelfSerializer,
    BookSummarySerializer,
    ContactUsSerializer,
    HighlightSerializer,
    UserBookSerializer,
)

FEATURED_CACHE_KEY = "home_featured"
FEATURED_CACHE_TTL = 60 * 60 * 24  # 1 day
FEATURED_COUNT = 10
POPULAR_COUNT = 10


def _get_or_create_token(user):
    token, _ = Token.objects.get_or_create(user=user)
    return token.key


class GoogleSignInView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        id_token = request.data.get("id_token")
        if not id_token:
            return Response(
                {"error": "id_token is required"}, status=status.HTTP_400_BAD_REQUEST
            )

        try:
            info = google_id_token.verify_oauth2_token(
                id_token,
                google_requests.Request(),
                settings.GOOGLE_CLIENT_ID_IOS,
            )
        except ValueError as exc:
            return Response(
                {"error": f"Invalid Google token: {exc}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        google_id = info.get("sub")
        email = info.get("email")

        if not email:
            return Response(
                {"error": "Email not available from Google token"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user = User.objects.filter(google_id=google_id).first()

        is_new_user = False
        if user is None:
            user = User.objects.filter(email=email).first()
            if user is None:
                user = User.objects.create_user(
                    email=email,
                    first_name=info.get("given_name", ""),
                    last_name=info.get("family_name", ""),
                    google_id=google_id,
                )
                is_new_user = True
            else:
                if not user.google_id:
                    user.google_id = google_id
                    user.save(update_fields=["google_id"])

        with new_context():
            if is_new_user:
                capture("user_signed_up", properties={
                    "sign_up_method": "google",
                })
            else:
                capture("user_signed_in", properties={
                    "sign_in_method": "google",
                })

        return Response(
            {"token": _get_or_create_token(user)}, status=status.HTTP_200_OK
        )


APPLE_JWKS_URL = "https://appleid.apple.com/auth/keys"
APPLE_ISSUER = "https://appleid.apple.com"
APPLE_JWKS_CACHE_KEY = "apple_jwks"
APPLE_JWKS_CACHE_TTL = 60 * 60 * 24  # 1 day


def _fetch_apple_public_key(kid):
    jwks = cache.get(APPLE_JWKS_CACHE_KEY)
    if jwks is None:
        with urllib.request.urlopen(APPLE_JWKS_URL) as response:  # noqa: S310
            jwks = json.loads(response.read())
        cache.set(APPLE_JWKS_CACHE_KEY, jwks, APPLE_JWKS_CACHE_TTL)
    key_data = next((k for k in jwks["keys"] if k["kid"] == kid), None)
    if key_data is None:
        # kid not found — keys may have rotated; bust cache and retry once
        with urllib.request.urlopen(APPLE_JWKS_URL) as response:  # noqa: S310
            jwks = json.loads(response.read())
        cache.set(APPLE_JWKS_CACHE_KEY, jwks, APPLE_JWKS_CACHE_TTL)
        key_data = next((k for k in jwks["keys"] if k["kid"] == kid), None)
    if key_data is None:
        raise ValueError(f"No Apple public key found for kid={kid}")
    return RSAAlgorithm.from_jwk(json.dumps(key_data))


class AppleSignInView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        id_token = request.data.get("identity_token")
        if not id_token:
            return Response(
                {"error": "identity_token is required"}, status=status.HTTP_400_BAD_REQUEST
            )

        try:
            header = jwt.get_unverified_header(id_token)
            public_key = _fetch_apple_public_key(header["kid"])
            payload = jwt.decode(
                id_token,
                public_key,
                algorithms=["RS256"],
                audience=settings.APPLE_CLIENT_ID,
                issuer=APPLE_ISSUER,
            )
        except Exception as exc:
            return Response(
                {"error": f"Invalid Apple token: {exc}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        apple_id = payload.get("sub")
        email = payload.get("email")

        if not apple_id:
            return Response(
                {"error": "Subject (sub) missing from Apple token"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user = User.objects.filter(apple_id=apple_id).first()

        is_new_user = False
        if user is None:
            if email:
                user = User.objects.filter(email=email).first()
            if user is None:
                if not email:
                    return Response(
                        {"error": "Email is required for new Apple sign-up"},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
                user = User.objects.create_user(email=email, apple_id=apple_id)
                is_new_user = True
            else:
                if not user.apple_id:
                    user.apple_id = apple_id
                    user.save(update_fields=["apple_id"])

        with new_context():
            if is_new_user:
                capture("user_signed_up", properties={
                    "sign_up_method": "apple",
                })
            else:
                capture("user_signed_in", properties={
                    "sign_in_method": "apple",
                })

        return Response(
            {"token": _get_or_create_token(user)}, status=status.HTTP_200_OK
        )


_HIGHLIGHT_REQUIRED_FIELDS = [
    "book_id", "start_xpath", "start_offset", "end_xpath", "end_offset",
    "selected_text", "color",
]


class HighlightListView(APIView):

    def post(self, request):
        missing = [f for f in _HIGHLIGHT_REQUIRED_FIELDS if request.data.get(f) is None]
        if missing:
            return Response(
                {"error": f"Missing required fields: {', '.join(missing)}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            book = Book.objects.get(pk=request.data["book_id"])
        except (Book.DoesNotExist, ValueError, TypeError):
            return Response({"error": "Book not found"}, status=status.HTTP_404_NOT_FOUND)

        raw_created_at = request.data.get("created_at")
        if raw_created_at:
            created_at = parse_datetime(raw_created_at)
            if created_at is None:
                return Response(
                    {"error": "Invalid created_at format, expected ISO 8601"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        else:
            created_at = timezone.now()

        try:
            start_offset = int(request.data["start_offset"])
            end_offset = int(request.data["end_offset"])
        except (ValueError, TypeError):
            return Response(
                {"error": "start_offset and end_offset must be integers"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        highlight = Highlight.objects.create(
            user=request.user,
            book=book,
            start_xpath=request.data["start_xpath"],
            start_offset=start_offset,
            end_xpath=request.data["end_xpath"],
            end_offset=end_offset,
            selected_text=request.data["selected_text"],
            note=request.data.get("note"),
            color=request.data["color"],
            section_title=request.data.get("section_title"),
            created_at=created_at,
        )
        return Response(HighlightSerializer(highlight).data, status=status.HTTP_201_CREATED)


class HighlightDetailView(APIView):

    def _get_highlight(self, request, pk):
        try:
            return Highlight.objects.select_related("book").get(pk=pk, user=request.user)
        except Highlight.DoesNotExist:
            return None

    def patch(self, request, pk):
        highlight = self._get_highlight(request, pk)
        if highlight is None:
            return Response({"error": "Not found"}, status=status.HTTP_404_NOT_FOUND)

        update_fields = []
        if "note" in request.data:
            highlight.note = request.data["note"]
            update_fields.append("note")
        if "color" in request.data:
            highlight.color = request.data["color"]
            update_fields.append("color")

        if update_fields:
            highlight.save(update_fields=update_fields)

        return Response(HighlightSerializer(highlight).data)

    def delete(self, request, pk):
        deleted, _ = Highlight.objects.filter(pk=pk, user=request.user).delete()
        if not deleted:
            return Response({"error": "Not found"}, status=status.HTTP_404_NOT_FOUND)
        return Response(status=status.HTTP_204_NO_CONTENT)


class ContactUsView(APIView):
    def post(self, request):
        serializer = ContactUsSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        instance = serializer.save(user=request.user)
        with new_context():
            capture("contact_submitted", properties={
                "category": instance.category,
                "message_length": len(instance.message),
            })
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class DeleteAccountView(APIView):
    def delete(self, request):
        user = request.user
        with new_context():
            capture("account_deleted")
        Token.objects.filter(user=user).delete()
        user.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class BookshelvesView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        shelves = Bookshelf.objects.filter(is_primary=True, parent__isnull=True).prefetch_related(
            "sub_bookshelves"
        )
        return Response(BookshelfSerializer(shelves, many=True).data)


class BookSearchView(APIView):
    def _build_search_query(self, query):
        return Q(
            "bool",
            should=[
                Q(
                    "match_phrase_prefix",
                    title={"query": query, "boost": 10, "max_expansions": 20},
                ),
                Q(
                    "match",
                    **{
                        "title.autocomplete": {
                            "query": query,
                            "boost": 8,
                            "operator": "and",
                        }
                    },
                ),
                Q(
                    "nested",
                    path="authors",
                    query=Q(
                        "bool",
                        should=[
                            Q(
                                "match_phrase_prefix",
                                **{
                                    "authors.name": {
                                        "query": query,
                                        "boost": 7,
                                        "max_expansions": 20,
                                    }
                                },
                            ),
                            Q(
                                "match",
                                **{
                                    "authors.name.autocomplete": {
                                        "query": query,
                                        "boost": 6,
                                        "operator": "and",
                                    }
                                },
                            ),
                            Q(
                                "match",
                                **{
                                    "authors.name": {
                                        "query": query,
                                        "boost": 3,
                                        "fuzziness": "AUTO",
                                    }
                                },
                            ),
                        ],
                        minimum_should_match=1,
                    ),
                ),
                Q(
                    "multi_match",
                    query=query,
                    fields=[
                        "title^3",
                        "summary",
                        "subjects",
                        "description",
                    ],
                    fuzziness="AUTO",
                ),
            ],
            minimum_should_match=1,
        )

    def get(self, request):
        q = request.query_params.get("q", "").strip()
        language = request.query_params.get("language", "").strip()
        bookshelf_id = request.query_params.get("bookshelf_id", "").strip()
        reading_ease_level = request.query_params.get("reading_ease_level", "").strip()

        valid_ease_levels = {choice[0] for choice in Book.READING_EASE_LEVEL_CHOICES}
        if reading_ease_level and reading_ease_level not in valid_ease_levels:
            return Response(
                {"error": f"Invalid reading_ease_level. Valid values: {', '.join(sorted(valid_ease_levels))}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            page = max(1, int(request.query_params.get("page", 1)))
            page_size = min(100, max(1, int(request.query_params.get("page_size", 20))))
        except ValueError:
            return Response(
                {"error": "Invalid pagination parameters"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        search = BookDocument.search()

        if q:
            search = search.query(self._build_search_query(q))
        else:
            search = search.sort("-downloads")

        if language:
            search = search.filter("term", language=language)

        if bookshelf_id:
            try:
                shelf = Bookshelf.objects.prefetch_related("sub_bookshelves").get(
                    pk=bookshelf_id
                )
            except (Bookshelf.DoesNotExist, ValueError):
                return Response(
                    {"error": "Invalid bookshelf ID"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            shelf_names = [shelf.name] + [
                child.name for child in shelf.sub_bookshelves.all()
            ]
            search = search.filter("terms", **{"bookshelves__keyword": shelf_names})

        if reading_ease_level:
            search = search.filter("term", reading_ease_level=reading_ease_level)

        offset = (page - 1) * page_size
        search = search[offset : offset + page_size]

        es_response = search.execute()

        results = [
            {
                "id": int(hit.meta.id),
                "title": hit.title,
                "language": hit.language,
                "downloads": hit.downloads,
                "issued_date": hit.issued_date,
                "cover_url": hit.cover_url,
                "authors": [
                    {
                        "name": a.name,
                        "birth_year": a.birth_year,
                        "death_year": a.death_year,
                    }
                    for a in (hit.authors or [])
                ],
                "bookshelves": list(hit.bookshelves or []),
                "summary": (hit.summary or "")[:300],
            }
            for hit in es_response
        ]

        with new_context():
            capture("book_searched", properties={
                "query_length": len(q),
                "has_query": bool(q),
                "has_language_filter": bool(language),
                "has_bookshelf_filter": bool(bookshelf_id),
                "has_reading_ease_filter": bool(reading_ease_level),
                "reading_ease_level": reading_ease_level or None,
                "result_count": es_response.hits.total.value,
                "page": page,
            })

        return Response(
            {
                "total": es_response.hits.total.value,
                "page": page,
                "page_size": page_size,
                "results": results,
            }
        )


class BookDetailView(APIView):

    def get(self, request, pk):
        try:
            book = Book.objects.prefetch_related(
                "authors", "subjects", "bookshelves", "formats"
            ).get(pk=pk)
        except Book.DoesNotExist:
            return Response({"error": "Not found"}, status=status.HTTP_404_NOT_FOUND)

        with new_context():
            capture("book_detail_viewed", properties={
                "book_id": book.id,
                "language": book.language,
            })

        return Response(BookDetailSerializer(book).data)


class HomeView(APIView):

    def get(self, request):
        return Response(
            {
                "featured": self._featured(),
                "popular": self._popular(),
                "current_readings": self._current_readings(request),
            }
        )

    def _featured(self):
        cached = cache.get(FEATURED_CACHE_KEY)
        if cached is not None:
            return cached

        top_ids = list(
            Book.objects.order_by("-downloads").values_list("id", flat=True)[:500]
        )
        sample_ids = random.sample(top_ids, min(FEATURED_COUNT, len(top_ids)))
        books = Book.objects.filter(id__in=sample_ids).prefetch_related(
            "authors", "bookshelves"
        )
        data = BookSummarySerializer(books, many=True).data
        cache.set(FEATURED_CACHE_KEY, data, FEATURED_CACHE_TTL)
        return data

    def _popular(self):
        books = Book.objects.order_by("-downloads").prefetch_related(
            "authors", "bookshelves"
        )[:POPULAR_COUNT]
        return BookSummarySerializer(books, many=True).data

    def _current_readings(self, request):
        if not request.user.is_authenticated:
            return []
        user_books = (
            UserBook.objects.filter(user=request.user, status=UserBook.READING)
            .select_related("book")
            .prefetch_related("book__authors", "book__bookshelves")
            .order_by("-updated_at")
        )
        return UserBookSerializer(user_books, many=True).data


class UserBooksListView(APIView):

    VALID_STATUSES = {UserBook.READING, UserBook.COMPLETED, UserBook.WANT_TO_READ}

    def get(self, request):
        requested_status = request.query_params.get("status", UserBook.READING)
        if requested_status not in self.VALID_STATUSES:
            return Response(
                {
                    "error": f"status must be one of: {', '.join(sorted(self.VALID_STATUSES))}"
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            page = max(1, int(request.query_params.get("page", 1)))
            page_size = min(100, max(1, int(request.query_params.get("page_size", 20))))
        except ValueError:
            return Response(
                {"error": "Invalid pagination parameters"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user_books = (
            UserBook.objects.filter(user=request.user, status=requested_status)
            .select_related("book")
            .prefetch_related("book__authors", "book__bookshelves")
            .order_by("-updated_at")
        )

        total = user_books.count()
        offset = (page - 1) * page_size
        page_qs = user_books[offset : offset + page_size]

        return Response(
            {
                "total": total,
                "page": page,
                "page_size": page_size,
                "results": UserBookSerializer(page_qs, many=True).data,
            }
        )


class UserBookView(APIView):

    def post(self, request, book_id):
        progress = request.data.get("progress")
        if progress is None:
            return Response(
                {"error": "progress is required"}, status=status.HTTP_400_BAD_REQUEST
            )
        try:
            progress = float(progress)
            if not (0 <= progress <= 100):
                raise ValueError
        except (TypeError, ValueError):
            return Response(
                {"error": "progress must be a number between 0 and 100"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        requested_status = request.data.get("status", UserBook.READING)
        if requested_status not in (UserBook.READING, UserBook.COMPLETED):
            return Response(
                {
                    "error": f"status must be '{UserBook.READING}' or '{UserBook.COMPLETED}'"
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            book = Book.objects.get(pk=book_id)
        except Book.DoesNotExist:
            return Response(
                {"error": "Book not found"}, status=status.HTTP_404_NOT_FOUND
            )

        now = timezone.now()
        user_book, created = UserBook.objects.get_or_create(
            user=request.user,
            book=book,
            defaults={
                "started_at": now,
                "status": requested_status,
                "progress": progress,
                "last_read_at": now,
            },
        )

        if not created:
            user_book.status = requested_status
            user_book.progress = progress
            user_book.last_read_at = now
            if user_book.started_at is None:
                user_book.started_at = now
            user_book.save(
                update_fields=["status", "progress", "last_read_at", "started_at"]
            )

        user_book.book = book
        with new_context():
            if created:
                capture("book_added_to_library", properties={
                    "book_id": book.id,
                    "status": requested_status,
                    "language": book.language,
                })
            else:
                if requested_status == UserBook.COMPLETED:
                    capture("book_completed", properties={
                        "book_id": book.id,
                        "language": book.language,
                    })
                else:
                    capture("book_reading_progress_updated", properties={
                        "book_id": book.id,
                        "progress": progress,
                        "status": requested_status,
                    })

        return Response(
            UserBookSerializer(user_book).data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )

    def delete(self, request, book_id):
        deleted, _ = UserBook.objects.filter(
            user=request.user, book_id=book_id
        ).delete()
        if not deleted:
            return Response(
                {"error": "Book not found in your library"},
                status=status.HTTP_404_NOT_FOUND,
            )
        with new_context():
            capture("book_removed_from_library", properties={
                "book_id": book_id,
            })
        return Response(status=status.HTTP_204_NO_CONTENT)
