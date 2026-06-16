"""Chunking rules for build-time recipe documents."""

from __future__ import annotations

from typing import Iterable, List, Tuple

from ...text_document import TextDocument


class RecipeDocumentChunker:
    """Split recipe documents into retrieval-oriented chunks."""

    def chunk(
        self,
        documents: Iterable[TextDocument],
        *,
        chunk_size: int = 500,
        chunk_overlap: int = 50,
    ) -> List[TextDocument]:
        chunks: List[TextDocument] = []
        next_chunk_id = 0
        for document in documents:
            document_chunks, next_chunk_id = self._chunk_document(
                document=document,
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap,
                next_chunk_id=next_chunk_id,
            )
            chunks.extend(document_chunks)
        return chunks

    def _chunk_document(
        self,
        *,
        document: TextDocument,
        chunk_size: int,
        chunk_overlap: int,
        next_chunk_id: int,
    ) -> Tuple[List[TextDocument], int]:
        content = document.page_content or ""
        if len(content) <= chunk_size:
            return [self._build_chunk(document, content, next_chunk_id, 0, 1)], next_chunk_id + 1

        sections = content.split("\n## ")
        if len(sections) > 1:
            return self._chunk_by_sections(document, sections, next_chunk_id)
        return self._chunk_by_window(
            document=document,
            content=content,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            next_chunk_id=next_chunk_id,
        )

    def _chunk_by_sections(
        self,
        document: TextDocument,
        sections: List[str],
        next_chunk_id: int,
    ) -> Tuple[List[TextDocument], int]:
        chunks: List[TextDocument] = []
        total_chunks = len(sections)
        chunk_id = next_chunk_id
        for index, section in enumerate(sections):
            chunk_content = section if index == 0 else f"## {section}"
            chunks.append(
                self._build_chunk(
                    document,
                    chunk_content,
                    chunk_id,
                    index,
                    total_chunks,
                    section_title=section.split("\n")[0] if index > 0 else "main_title",
                )
            )
            chunk_id += 1
        return chunks, chunk_id

    def _chunk_by_window(
        self,
        *,
        document: TextDocument,
        content: str,
        chunk_size: int,
        chunk_overlap: int,
        next_chunk_id: int,
    ) -> Tuple[List[TextDocument], int]:
        stride = max(1, chunk_size - chunk_overlap)
        total_chunks = (len(content) - 1) // stride + 1
        chunks: List[TextDocument] = []
        chunk_id = next_chunk_id
        for index in range(total_chunks):
            start = index * stride
            end = min(start + chunk_size, len(content))
            chunk_content = content[start:end]
            chunks.append(
                self._build_chunk(
                    document,
                    chunk_content,
                    chunk_id,
                    index,
                    total_chunks,
                )
            )
            chunk_id += 1
        return chunks, chunk_id

    @staticmethod
    def _build_chunk(
        document: TextDocument,
        chunk_content: str,
        chunk_id: int,
        chunk_index: int,
        total_chunks: int,
        *,
        section_title: str | None = None,
    ) -> TextDocument:
        parent_id = str(
            document.metadata.get("node_id")
            or document.metadata.get("parent_id")
            or "unknown"
        )
        metadata = {
            **document.metadata,
            "chunk_id": f"{parent_id}_chunk_{chunk_id}",
            "parent_id": parent_id,
            "chunk_index": chunk_index,
            "total_chunks": total_chunks,
            "chunk_size": len(chunk_content),
            "doc_type": "chunk",
        }
        if section_title is not None:
            metadata["section_title"] = section_title
        return TextDocument(
            content=chunk_content,
            metadata=metadata,
        )
