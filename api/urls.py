from django.urls import path

from . import views

urlpatterns = [
    path("auth/google/", views.GoogleSignInView.as_view(), name="google-signin"),
    path("auth/apple/", views.AppleSignInView.as_view(), name="apple-signin"),
    path("auth/account/", views.DeleteAccountView.as_view(), name="delete-account"),
    path("contact-us/", views.ContactUsView.as_view(), name="contact-us"),
    path("home/", views.HomeView.as_view(), name="home"),
    path("bookshelves/", views.BookshelvesView.as_view(), name="bookshelves"),
    path("books/", views.BookSearchView.as_view(), name="book-search"),
    path("books/<int:pk>/", views.BookDetailView.as_view(), name="book-detail"),
    path("user-books/", views.UserBooksListView.as_view(), name="user-books-list"),
    path("user-books/<int:book_id>/", views.UserBookView.as_view(), name="user-book"),
    path("highlights/", views.HighlightListView.as_view(), name="highlight-list"),
    path("highlights/<uuid:pk>/", views.HighlightDetailView.as_view(), name="highlight-detail"),
]
