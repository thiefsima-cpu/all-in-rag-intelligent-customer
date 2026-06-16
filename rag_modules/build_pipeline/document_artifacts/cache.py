"""JSON-backed cache store for materialized documents and chunks."""

from __future__ import annotations

import logging
import os
import hmac
from typing import Optional

from ...artifacts import (
    ARTIFACT_STAGE_DOCUMENTS_READY,
    ArtifactManifest,
    ArtifactManifestStore,
    compute_documents_digest,
    read_documents,
    write_documents,
)
from .manifest import DocumentArtifactManifestAssembler
from .models import DocumentArtifactResult
from .settings import DocumentArtifactSettings
from .signatures import DocumentArtifactSignatureCollector
from .statistics import DocumentArtifactStatsCollector

logger = logging.getLogger(__name__)


class DocumentIndexCache:
    """Stable JSON-backed cache for materialized documents and chunks."""

    def __init__(
        self,
        config,
        *,
        settings: DocumentArtifactSettings | None = None,
        manifest_store: ArtifactManifestStore | None = None,
        signature_collector: DocumentArtifactSignatureCollector | None = None,
        stats_collector: DocumentArtifactStatsCollector | None = None,
        manifest_assembler: DocumentArtifactManifestAssembler | None = None,
    ):
        self.config = config
        self.settings = settings or DocumentArtifactSettings.from_config(config)
        os.makedirs(self.settings.cache_dir, exist_ok=True)
        self.manifest_store = manifest_store or ArtifactManifestStore(config)
        self.signature_collector = signature_collector or DocumentArtifactSignatureCollector(self.settings)
        self.stats_collector = stats_collector or DocumentArtifactStatsCollector()
        self.manifest_assembler = manifest_assembler or DocumentArtifactManifestAssembler(
            settings=self.settings,
            manifest_store=self.manifest_store,
        )

    @property
    def documents_path(self) -> str:
        return self.settings.documents_path

    @property
    def chunks_path(self) -> str:
        return self.settings.chunks_path

    def load(self, data_module) -> Optional[DocumentArtifactResult]:
        if not self.settings.enable_index_cache:
            return None
        if not (os.path.exists(self.documents_path) and os.path.exists(self.chunks_path)):
            return None

        signatures = self.signature_collector.collect(data_module)
        manifests = []
        load_candidate = getattr(self.manifest_store, "load_candidate", None)
        if callable(load_candidate):
            candidate = load_candidate()
            if candidate is not None:
                manifests.append(candidate)
        manifests.append(self.manifest_store.load())
        manifest = next(
            (
                item
                for item in manifests
                if item.document_signature == signatures.document_signature
            ),
            None,
        )
        if manifest is None:
            logger.info("Document cache signature mismatch. Rebuilding document artifacts.")
            return None

        try:
            documents = read_documents(self.documents_path)
            chunks = read_documents(self.chunks_path)
        except Exception as exc:
            logger.warning("Failed to load document artifact cache. Rebuilding: %s", exc)
            return None
        expected_documents_digest = str(
            manifest.build_metadata.get("documents_sha256") or ""
        )
        expected_chunks_digest = str(
            manifest.build_metadata.get("chunks_sha256") or ""
        )
        actual_documents_digest = compute_documents_digest(documents)
        actual_chunks_digest = compute_documents_digest(chunks)
        if not (
            expected_documents_digest
            and expected_chunks_digest
            and hmac.compare_digest(expected_documents_digest, actual_documents_digest)
            and hmac.compare_digest(expected_chunks_digest, actual_chunks_digest)
        ):
            logger.warning("Document cache content digest mismatch. Rebuilding artifacts.")
            return None

        data_module.documents = documents
        data_module.chunks = chunks
        stats = self.stats_collector.collect(data_module)
        loaded_manifest = self.manifest_assembler.assemble(
            signatures=signatures,
            stats=stats,
            stage=ARTIFACT_STAGE_DOCUMENTS_READY,
            cache_hit=True,
            base_manifest=manifest,
            build_metadata={"document_cache_format": "json"},
        )
        logger.info(
            "Document artifacts loaded from cache: documents=%s chunks=%s",
            len(documents),
            len(chunks),
        )
        return DocumentArtifactResult(
            documents=documents,
            chunks=chunks,
            manifest=loaded_manifest,
            cache_hit=True,
        )

    def save(
        self,
        data_module,
        *,
        stage: str = ARTIFACT_STAGE_DOCUMENTS_READY,
        cache_hit: bool = False,
        base_manifest: ArtifactManifest | None = None,
        build_metadata: Optional[dict] = None,
    ) -> ArtifactManifest:
        documents = list(getattr(data_module, "documents", []) or [])
        chunks = list(getattr(data_module, "chunks", []) or [])
        if self.settings.enable_index_cache:
            write_documents(self.documents_path, documents)
            write_documents(self.chunks_path, chunks)

        signatures = self.signature_collector.collect(data_module)
        stats = self.stats_collector.collect(data_module)
        manifest = self.manifest_assembler.assemble(
            signatures=signatures,
            stats=stats,
            stage=stage,
            cache_hit=cache_hit,
            base_manifest=base_manifest,
            build_metadata={
                "document_cache_enabled": self.settings.enable_index_cache,
                "document_cache_format": "json",
                "documents_sha256": compute_documents_digest(documents),
                "chunks_sha256": compute_documents_digest(chunks),
                **(build_metadata or {}),
            },
        )
        save_candidate = getattr(self.manifest_store, "save_candidate", None)
        if callable(save_candidate):
            saved_manifest = save_candidate(manifest)
            logger.info(
                "Document artifact candidate manifest saved to %s",
                getattr(self.manifest_store, "candidate_path", self.manifest_store.manifest_path),
            )
        else:
            saved_manifest = self.manifest_store.save(manifest)
            logger.info("Document artifact manifest saved to %s", self.manifest_store.manifest_path)
        return saved_manifest
