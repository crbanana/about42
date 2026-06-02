"""RAG utilities: chunking, embedding, vector search via Neon pgvector."""

import os
from typing import List

from langchain_core.documents import Document
from langchain_openai import OpenAIEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter

from agents.database import get_conn

EMBEDDING_MODEL = "text-embedding-3-small"
CHUNK_SIZE = 1000
CHUNK_OVERLAP = 200


_embeddings: OpenAIEmbeddings | None = None


def get_embeddings() -> OpenAIEmbeddings:
    global _embeddings
    if _embeddings is None:
        _embeddings = OpenAIEmbeddings(model=EMBEDDING_MODEL)
    return _embeddings


def chunk_wiki_document(source: str, text: str) -> List[Document]:
    """Split a wiki document into chunks."""
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        separators=["\n## ", "\n### ", "\n\n", "\n", " ", ""],
    )
    docs = splitter.create_documents([text], metadatas=[{"source": source}])
    return docs


def index_wiki_chunks(docs: List[Document]) -> None:
    """Embed and store wiki chunks in Neon."""
    if not docs:
        return
    embeddings = get_embeddings()
    texts = [doc.page_content for doc in docs]
    vectors = embeddings.embed_documents(texts)

    with get_conn() as conn:
        with conn.cursor() as cur:
            for doc, vector in zip(docs, vectors):
                cur.execute(
                    """
                    INSERT INTO wiki_chunks (content, embedding, source, metadata)
                    VALUES (%s, %s, %s, %s)
                    """,
                    (doc.page_content, str(vector), doc.metadata["source"], doc.metadata),
                )
        conn.commit()


def query_rag(query: str, k: int = 5) -> List[Document]:
    """Retrieve top-k relevant chunks for a query."""
    embeddings = get_embeddings()
    query_vector = embeddings.embed_query(query)

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT content, source, metadata, 1 - (embedding <=> %s::vector) AS score
                FROM wiki_chunks
                ORDER BY embedding <=> %s::vector
                LIMIT %s
                """,
                (str(query_vector), str(query_vector), k),
            )
            rows = cur.fetchall()

    docs: List[Document] = []
    for content, source, metadata, score in rows:
        docs.append(Document(
            page_content=content,
            metadata={"source": source, **(metadata or {}), "score": score},
        ))
    return docs
