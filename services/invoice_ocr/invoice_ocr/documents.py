from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
import re

import fitz
from PIL import Image, ImageOps, UnidentifiedImageError

SUPPORTED_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png"}
MAGIC = {
    ".pdf": (b"%PDF-",),
    ".jpg": (b"\xff\xd8\xff",),
    ".jpeg": (b"\xff\xd8\xff",),
    ".png": (b"\x89PNG\r\n\x1a\n",),
}


class DocumentError(ValueError):
    pass


@dataclass(frozen=True)
class PreparedDocument:
    source_path: Path
    source_sha256: str
    page_images: tuple[Path, ...]
    embedded_text: str
    use_embedded_text: bool


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_source(path: Path, max_bytes: int = 10 * 1024 * 1024) -> None:
    if not path.is_file():
        raise DocumentError("source is not a readable file")
    suffix = path.suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        raise DocumentError("unsupported extension")
    size = path.stat().st_size
    if size <= 0:
        raise DocumentError("source is empty")
    if size > max_bytes:
        raise DocumentError("source exceeds size limit")
    header = path.read_bytes()[:8]
    if not any(header.startswith(prefix) for prefix in MAGIC[suffix]):
        raise DocumentError("file header does not match extension")
    if suffix != ".pdf":
        try:
            with Image.open(path) as image:
                image.verify()
        except (UnidentifiedImageError, OSError) as exc:
            raise DocumentError("image cannot be decoded") from exc


def embedded_text_is_reliable(text: str) -> bool:
    compact = re.sub(r"\s+", "", text)
    meaningful = re.findall(r"[0-9A-Za-z\u3400-\u9fff]", compact)
    if len(meaningful) < 20:
        return False
    replacement_ratio = compact.count("\ufffd") / max(len(compact), 1)
    return replacement_ratio < 0.02


def _render_pdf(path: Path, output_dir: Path, digest: str, max_pages: int) -> tuple[list[Path], str]:
    images: list[Path] = []
    texts: list[str] = []
    try:
        document = fitz.open(path)
    except Exception as exc:
        raise DocumentError("PDF cannot be opened") from exc
    try:
        if document.page_count < 1:
            raise DocumentError("PDF has no pages")
        if document.page_count > max_pages:
            raise DocumentError("PDF exceeds page limit")
        for index, page in enumerate(document):
            texts.append(page.get_text("text"))
            pixmap = page.get_pixmap(matrix=fitz.Matrix(2.0, 2.0), alpha=False)
            rendered = output_dir / f"{digest[:16]}-p{index + 1}.png"
            pixmap.save(rendered)
            images.append(rendered)
    finally:
        document.close()
    return images, "\n".join(texts).strip()


def _normalize_image(path: Path, output_dir: Path, digest: str) -> list[Path]:
    try:
        with Image.open(path) as source:
            image = ImageOps.exif_transpose(source).convert("RGB")
            rendered = output_dir / f"{digest[:16]}-p1.png"
            image.save(rendered, format="PNG", optimize=True)
    except (UnidentifiedImageError, OSError) as exc:
        raise DocumentError("image cannot be normalized") from exc
    return [rendered]


def prepare_document(path: Path, output_dir: Path, max_pages: int = 5) -> PreparedDocument:
    validate_source(path)
    output_dir.mkdir(parents=True, exist_ok=True)
    digest = file_sha256(path)
    if path.suffix.lower() == ".pdf":
        images, embedded_text = _render_pdf(path, output_dir, digest, max_pages)
    else:
        images = _normalize_image(path, output_dir, digest)
        embedded_text = ""
    return PreparedDocument(
        source_path=path,
        source_sha256=digest,
        page_images=tuple(images),
        embedded_text=embedded_text,
        use_embedded_text=embedded_text_is_reliable(embedded_text),
    )
