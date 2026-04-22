import os
import xml.etree.ElementTree as ET
from datetime import date, datetime, timezone

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction

from api.documents import BookDocument
from api.models import Author, Book, BookFormat, Bookshelf, Subject

NS = {
    "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
    "pgterms": "http://www.gutenberg.org/2009/pgterms/",
    "dcterms": "http://purl.org/dc/terms/",
    "dcam": "http://purl.org/dc/dcam/",
}

RDF_ABOUT = "{http://www.w3.org/1999/02/22-rdf-syntax-ns#}about"
RDF_RESOURCE = "{http://www.w3.org/1999/02/22-rdf-syntax-ns#}resource"

# These carry no useful information for users
SKIP_MIMES = {"application/rdf+xml", "application/octet-stream"}


def _text(el):
    return (el.text or "").strip() if el is not None else ""


def _parse_rdf(path):
    try:
        tree = ET.parse(path)
    except ET.ParseError:
        return None

    root = tree.getroot()
    ebook = root.find("pgterms:ebook", NS)
    if ebook is None:
        return None

    about = ebook.get(RDF_ABOUT, "")
    try:
        book_id = int(about.split("/")[-1])
    except (ValueError, IndexError):
        return None

    title = _text(ebook.find("dcterms:title", NS))

    lang_el = ebook.find(".//dcterms:language//rdf:value", NS)
    language = _text(lang_el)

    dl_el = ebook.find("pgterms:downloads", NS)
    downloads = int(dl_el.text) if dl_el is not None and dl_el.text else 0

    issued_el = ebook.find("dcterms:issued", NS)
    issued_date = None
    if issued_el is not None and issued_el.text:
        try:
            issued_date = date.fromisoformat(issued_el.text.strip())
        except ValueError:
            pass

    rights = _text(ebook.find("dcterms:rights", NS))

    type_el = ebook.find(".//dcterms:type//rdf:value", NS)
    content_type = _text(type_el)

    descriptions = [
        _text(el) for el in ebook.findall("dcterms:description", NS) if el.text
    ]
    description = "\n\n".join(descriptions)

    summary = _text(ebook.find("pgterms:marc520", NS))
    transcribers = _text(ebook.find("pgterms:marc508", NS))
    reading_ease = _text(ebook.find("pgterms:marc908", NS))

    authors = []
    for creator in ebook.findall("dcterms:creator", NS):
        agent = creator.find("pgterms:agent", NS)
        if agent is None:
            continue
        agent_about = agent.get(RDF_ABOUT, "")
        try:
            agent_id = int(agent_about.split("/")[-1])
        except (ValueError, IndexError):
            continue
        wiki_el = agent.find("pgterms:webpage", NS)
        aliases = [_text(el) for el in agent.findall("pgterms:alias", NS) if el.text]
        authors.append(
            {
                "id": agent_id,
                "name": _text(agent.find("pgterms:name", NS)),
                "birth_year": (
                    int(agent.find("pgterms:birthdate", NS).text)
                    if agent.find("pgterms:birthdate", NS) is not None
                    and agent.find("pgterms:birthdate", NS).text
                    else None
                ),
                "death_year": (
                    int(agent.find("pgterms:deathdate", NS).text)
                    if agent.find("pgterms:deathdate", NS) is not None
                    and agent.find("pgterms:deathdate", NS).text
                    else None
                ),
                "aliases": aliases,
                "wikipedia_url": (
                    wiki_el.get(RDF_RESOURCE, "") if wiki_el is not None else ""
                ),
            }
        )

    subjects = [
        _text(el)
        for subj in ebook.findall("dcterms:subject", NS)
        for el in [subj.find(".//rdf:value", NS)]
        if el is not None and el.text
    ]

    bookshelves = []
    for shelf in ebook.findall("pgterms:bookshelf", NS):
        val = shelf.find(".//rdf:value", NS)
        if val is not None and val.text:
            name = val.text.strip()
            if name.startswith("Category: "):
                name = name[len("Category: ") :]
            bookshelves.append(name)

    cover_url = ""
    formats = []
    for fmt in ebook.findall("dcterms:hasFormat", NS):
        file_el = fmt.find("pgterms:file", NS)
        if file_el is None:
            continue
        url = file_el.get(RDF_ABOUT, "")
        if not url:
            continue

        # Collect all mime types; a file entry can have multiple dcterms:format children
        mimes = [_text(el) for el in file_el.findall(".//rdf:value", NS) if el.text]
        # Pick first non-skipped mime
        mime = next((m for m in mimes if m not in SKIP_MIMES), None)
        if not mime:
            continue

        extent_el = file_el.find("dcterms:extent", NS)
        size = int(extent_el.text) if extent_el is not None and extent_el.text else None

        modified = None
        modified_el = file_el.find("dcterms:modified", NS)
        if modified_el is not None and modified_el.text:
            try:
                modified = datetime.fromisoformat(modified_el.text.strip()).replace(tzinfo=timezone.utc)
            except ValueError:
                pass

        if mime == "image/jpeg" and "cover.medium" in url:
            cover_url = url

        formats.append(
            {
                "url": url,
                "mime_type": mime,
                "size": size,
                "modified": modified,
            }
        )

    return {
        "id": book_id,
        "title": title,
        "language": language,
        "downloads": downloads,
        "issued_date": issued_date,
        "rights": rights,
        "content_type": content_type,
        "description": description,
        "summary": summary,
        "transcribers": transcribers,
        "reading_ease": reading_ease,
        "cover_url": cover_url,
        "authors": authors,
        "subjects": subjects,
        "bookshelves": bookshelves,
        "formats": formats,
    }


class Command(BaseCommand):
    help = "Index Project Gutenberg catalog from local per-book RDF files"

    def add_arguments(self, parser):
        parser.add_argument(
            "--epub-dir",
            default=str(settings.BASE_DIR / "epub"),
            help="Path to the epub/ directory containing per-book RDF files",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=500,
            help="Number of books to commit per DB transaction",
        )
        parser.add_argument(
            "--es-only",
            action="store_true",
            help="Skip DB phase and only re-index existing books to Elasticsearch",
        )

    def handle(self, *args, **options):
        epub_dir = options["epub_dir"]
        batch_size = options["batch_size"]
        es_only = options["es_only"]

        if es_only:
            self._index_to_es()
            return

        self._index_db(epub_dir, batch_size)
        self._index_to_es()

    def _index_db(self, epub_dir, batch_size):
        self.stdout.write("Loading existing IDs from database...")
        existing_ids = set(Book.objects.values_list("id", flat=True))
        self.stdout.write(f"  {len(existing_ids)} books already indexed, skipping.")

        self.stdout.write("Pre-loading author/subject/bookshelf caches...")
        author_cache = {a.id: a for a in Author.objects.all()}
        subject_cache = {s.name: s for s in Subject.objects.all()}
        bookshelf_cache = {b.name: b for b in Bookshelf.objects.all()}

        rdf_files = self._collect_rdf_files(epub_dir, existing_ids)
        total = len(rdf_files)
        self.stdout.write(f"Found {total} new RDF files to process.")

        processed = 0
        new_book_ids = []
        batch = []

        for rdf_path in rdf_files:
            data = _parse_rdf(rdf_path)
            if data is None:
                self.stderr.write(f"  Skipping unparseable file: {rdf_path}")
                continue
            batch.append(data)

            if len(batch) >= batch_size:
                ids = self._commit_batch(
                    batch, author_cache, subject_cache, bookshelf_cache
                )
                new_book_ids.extend(ids)
                processed += len(batch)
                self.stdout.write(f"  Committed {processed}/{total}")
                batch = []

        if batch:
            ids = self._commit_batch(
                batch, author_cache, subject_cache, bookshelf_cache
            )
            new_book_ids.extend(ids)
            processed += len(batch)
            self.stdout.write(f"  Committed {processed}/{total}")

        self.stdout.write(
            self.style.SUCCESS(f"DB phase complete. {len(new_book_ids)} books added.")
        )

    @transaction.atomic
    def _commit_batch(self, batch, author_cache, subject_cache, bookshelf_cache):
        book_ids = []
        for data in batch:
            book = Book.objects.create(
                id=data["id"],
                title=data["title"],
                language=data["language"],
                downloads=data["downloads"],
                issued_date=data["issued_date"],
                rights=data["rights"],
                content_type=data["content_type"],
                description=data["description"],
                summary=data["summary"],
                transcribers=data["transcribers"],
                reading_ease=data["reading_ease"],
                cover_url=data["cover_url"],
            )

            for a_data in data["authors"]:
                key = a_data["id"]
                if key not in author_cache:
                    author, _ = Author.objects.get_or_create(
                        id=key,
                        defaults={
                            "name": a_data["name"],
                            "birth_year": a_data["birth_year"],
                            "death_year": a_data["death_year"],
                            "aliases": a_data["aliases"],
                            "wikipedia_url": a_data["wikipedia_url"],
                        },
                    )
                    author_cache[key] = author
                book.authors.add(author_cache[key])

            for s_name in data["subjects"]:
                if s_name not in subject_cache:
                    subj, _ = Subject.objects.get_or_create(name=s_name)
                    subject_cache[s_name] = subj
                book.subjects.add(subject_cache[s_name])

            for b_name in data["bookshelves"]:
                if b_name not in bookshelf_cache:
                    shelf, _ = Bookshelf.objects.get_or_create(name=b_name)
                    bookshelf_cache[b_name] = shelf
                book.bookshelves.add(bookshelf_cache[b_name])

            BookFormat.objects.bulk_create(
                [BookFormat(book=book, **fmt) for fmt in data["formats"]]
            )

            book_ids.append(book.id)

        return book_ids

    def _collect_rdf_files(self, epub_dir, existing_ids):
        paths = []
        for entry in os.scandir(epub_dir):
            if not entry.is_dir():
                continue
            try:
                book_id = int(entry.name)
            except ValueError:
                continue
            if book_id in existing_ids:
                continue
            rdf_path = os.path.join(entry.path, f"pg{book_id}.rdf")
            if os.path.isfile(rdf_path):
                paths.append(rdf_path)
        return paths

    def _index_to_es(self):
        self.stdout.write("Indexing to Elasticsearch...")
        qs = Book.objects.prefetch_related("authors", "subjects", "bookshelves").all()
        BookDocument().update(qs)
        self.stdout.write(
            self.style.SUCCESS(
                f"Elasticsearch indexing complete. {qs.count()} books indexed."
            )
        )
