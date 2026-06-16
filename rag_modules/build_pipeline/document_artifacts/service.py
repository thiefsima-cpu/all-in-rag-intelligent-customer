"""Build orchestration for materialized documents and cache state."""

from __future__ import annotations

from ...artifacts import ARTIFACT_STAGE_DOCUMENTS_READY
from .cache import DocumentIndexCache
from ...runtime.artifact_ports import DocumentArtifactCachePort
from .models import DocumentArtifactResult
from .settings import DocumentArtifactSettings


class DocumentArtifactBuildService:
    """Orchestrate document build-vs-cache behavior for build runtime."""

    def __init__(
        self,
        config,
        *,
        settings: DocumentArtifactSettings | None = None,
        cache: DocumentArtifactCachePort | None = None,
    ) -> None:
        self.config = config
        self.settings = settings or DocumentArtifactSettings.from_config(config)
        self.cache = cache or DocumentIndexCache(config, settings=self.settings)

    def build_or_load(self, data_module) -> DocumentArtifactResult:
        cached = self.cache.load(data_module)
        if cached is not None:
            return cached

        data_module.build_recipe_documents()
        chunks = data_module.chunk_documents(
            chunk_size=self.settings.chunk_size,
            chunk_overlap=self.settings.chunk_overlap,
        )
        manifest = self.cache.save(
            data_module,
            stage=ARTIFACT_STAGE_DOCUMENTS_READY,
            cache_hit=False,
        )
        return DocumentArtifactResult(
            documents=getattr(data_module, "documents", []) or [],
            chunks=chunks,
            manifest=manifest,
            cache_hit=False,
        )


def build_or_load_documents(data_module, config) -> DocumentArtifactResult:
    return DocumentArtifactBuildService(config).build_or_load(data_module)
