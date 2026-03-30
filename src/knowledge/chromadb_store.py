"""ChromaDB vector store for krkn and OCP documentation search."""

import logging
from dataclasses import dataclass

import chromadb

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DocChunk:
    text: str
    component: str
    doc_type: str  # "scenario", "architecture", "upgrade", "release-notes"
    source: str  # "krkn-website", "krkn-hub", "openshift-docs"
    version: str = ""


class ChromaStore:
    """Vector store for semantic search over krkn and OCP documentation."""

    def __init__(self, persist_dir: str = "./chroma_data"):
        self._client = chromadb.PersistentClient(path=persist_dir)
        self._scenarios = self._client.get_or_create_collection(
            name="scenario_docs",
            metadata={"hnsw:space": "cosine"},
        )
        self._krkn_docs = self._client.get_or_create_collection(
            name="krkn_docs",
            metadata={"hnsw:space": "cosine"},
        )
        self._ocp_docs = self._client.get_or_create_collection(
            name="ocp_docs",
            metadata={"hnsw:space": "cosine"},
        )

    def add_scenario_docs(self, chunks: list[DocChunk]) -> None:
        """Add scenario documentation chunks."""
        self._add_chunks(self._scenarios, chunks, prefix="scenario")

    def add_krkn_docs(self, chunks: list[DocChunk]) -> None:
        """Add krkn documentation chunks."""
        self._add_chunks(self._krkn_docs, chunks, prefix="krkn")

    def add_ocp_docs(self, chunks: list[DocChunk]) -> None:
        """Add OpenShift documentation chunks."""
        self._add_chunks(self._ocp_docs, chunks, prefix="ocp")

    def search_scenarios(
        self, query: str, component: str | None = None, n_results: int = 5
    ) -> list[dict]:
        """Search scenario docs by semantic similarity."""
        where = {"component": component} if component else None
        return self._search(self._scenarios, query, where, n_results)

    def search_krkn_docs(
        self, query: str, component: str | None = None, n_results: int = 5
    ) -> list[dict]:
        """Search krkn documentation."""
        where = {"component": component} if component else None
        return self._search(self._krkn_docs, query, where, n_results)

    def search_all(self, query: str, n_results: int = 10) -> list[dict]:
        """Search across all collections."""
        results = []
        results.extend(self._search(self._scenarios, query, None, n_results))
        results.extend(self._search(self._krkn_docs, query, None, n_results))
        results.extend(self._search(self._ocp_docs, query, None, n_results))
        results.sort(key=lambda r: r.get("distance", 1.0))
        return results[:n_results]

    def _add_chunks(
        self, collection: chromadb.Collection, chunks: list[DocChunk], prefix: str
    ) -> None:
        if not chunks:
            return

        ids = [f"{prefix}_{i}" for i in range(len(chunks))]
        documents = [c.text for c in chunks]
        metadatas = [
            {
                "component": c.component,
                "doc_type": c.doc_type,
                "source": c.source,
                "version": c.version,
            }
            for c in chunks
        ]

        collection.upsert(ids=ids, documents=documents, metadatas=metadatas)
        logger.info("Added %d chunks to %s", len(chunks), collection.name)

    def _search(
        self,
        collection: chromadb.Collection,
        query: str,
        where: dict | None,
        n_results: int,
    ) -> list[dict]:
        try:
            count = collection.count()
            if count == 0:
                return []

            kwargs = {"query_texts": [query], "n_results": min(n_results, count)}
            if where:
                kwargs["where"] = where

            results = collection.query(**kwargs)
        except Exception as e:
            logger.error("ChromaDB search failed: %s", e)
            return []

        hits = []
        if results and results.get("documents"):
            for i, doc in enumerate(results["documents"][0]):
                hit = {
                    "text": doc,
                    "metadata": results["metadatas"][0][i] if results.get("metadatas") else {},
                    "distance": results["distances"][0][i] if results.get("distances") else 1.0,
                }
                hits.append(hit)
        return hits
