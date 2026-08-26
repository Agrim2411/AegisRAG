import hashlib
import re
import uuid

from .domain import Chunk, Document, IngestRequest
from .embeddings import EmbeddingProvider

HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")


def content_digest(content: str) -> str:
    return "sha256:" + hashlib.sha256(content.encode("utf-8")).hexdigest()


def stable_id(prefix: str, *parts: str) -> str:
    raw = "|".join(parts).encode()
    return f"{prefix}_{uuid.uuid5(uuid.NAMESPACE_URL, raw.decode(errors='ignore')).hex[:20]}"


def _sections(markdown: str) -> list[tuple[str, str, int, int]]:
    lines = markdown.splitlines(keepends=True)
    sections: list[tuple[str, str, int, int]] = []
    current = "Overview"
    buffer: list[str] = []
    start = 0
    cursor = 0
    for line in lines:
        match = HEADING_RE.match(line.strip())
        if match:
            if " ".join(buffer).strip():
                text = "".join(buffer).strip()
                sections.append((current, text, start, cursor))
            current = match.group(2)
            buffer = []
            start = cursor + len(line)
        else:
            buffer.append(line)
        cursor += len(line)
    if " ".join(buffer).strip():
        sections.append((current, "".join(buffer).strip(), start, cursor))
    return sections


def chunk_document(
    request: IngestRequest, tenant_id: str, embedder: EmbeddingProvider, max_chars: int = 850
) -> Document:
    digest = content_digest(request.content)
    document_id = stable_id("doc", tenant_id, request.source_uri, digest)
    chunks: list[Chunk] = []
    ordinal = 0
    for section, text, section_start, _ in _sections(request.content):
        paragraphs = [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]
        current = ""
        current_start = section_start
        for paragraph in paragraphs:
            candidate = f"{current}\n\n{paragraph}" if current else paragraph
            if current and len(candidate) > max_chars:
                chunks.append(
                    _make_chunk(
                        document_id,
                        tenant_id,
                        digest,
                        ordinal,
                        section,
                        current,
                        current_start,
                        embedder,
                        request.metadata,
                    )
                )
                ordinal += 1
                current = paragraph
                current_start = request.content.find(paragraph, current_start)
            else:
                current = candidate
        if current:
            chunks.append(
                _make_chunk(
                    document_id,
                    tenant_id,
                    digest,
                    ordinal,
                    section,
                    current,
                    current_start,
                    embedder,
                    request.metadata,
                )
            )
            ordinal += 1
    return Document(
        id=document_id,
        tenant_id=tenant_id,
        title=request.title,
        source_uri=request.source_uri,
        content_type=request.content_type,
        content_hash=digest,
        metadata=request.metadata,
        chunks=chunks,
    )


def _make_chunk(
    document_id: str,
    tenant_id: str,
    digest: str,
    ordinal: int,
    section: str,
    text: str,
    start: int,
    embedder: EmbeddingProvider,
    metadata: dict[str, str],
) -> Chunk:
    return Chunk(
        id=stable_id("chunk", document_id, str(ordinal), text),
        document_id=document_id,
        tenant_id=tenant_id,
        ordinal=ordinal,
        section=section,
        text=text,
        content_hash=digest,
        start_char=max(start, 0),
        end_char=max(start, 0) + len(text),
        embedding=embedder.embed(text),
        metadata=metadata,
    )
