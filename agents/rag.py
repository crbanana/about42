"""RAG layer using LangChain PGVector + Neon Postgres."""

import os
from pathlib import Path
from typing import List

from langchain_core.documents import Document
from langchain_openai import OpenAIEmbeddings
from langchain_postgres import PGVector
from langchain_text_splitters import RecursiveCharacterTextSplitter

NEON_DATABASE_URL = os.environ.get("NEON_DATABASE_URL", "")
COLLECTION_NAME = "hyperise_wiki"
EMBEDDING_MODEL = "text-embedding-3-small"

# LangChain PGVector requires postgresql+psycopg:// format
_connection = NEON_DATABASE_URL.replace("postgresql://", "postgresql+psycopg://")
if not _connection.startswith("postgresql+psycopg://"):
    _connection = "postgresql+psycopg://" + _connection.replace("postgresql://", "", 1)

_embeddings = OpenAIEmbeddings(model=EMBEDDING_MODEL)


def _get_vectorstore() -> PGVector:
    return PGVector(
        embeddings=_embeddings,
        collection_name=COLLECTION_NAME,
        connection=_connection,
        use_jsonb=True,
    )


def chunk_wiki_document(source: str, text: str) -> List[Document]:
    """Split a wiki document into LangChain Documents."""
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=1000,
        chunk_overlap=200,
        separators=["\n## ", "\n### ", "\n\n", "\n", " ", ""],
    )
    return splitter.create_documents([text], metadatas=[{"source": source}])


def index_wiki_chunks(docs: List[Document]) -> None:
    """Embed and store wiki chunks in Neon via PGVector."""
    if not docs:
        return
    vectorstore = _get_vectorstore()
    vectorstore.add_documents(docs)
    print(f"[RAG] Indexed {len(docs)} chunks into '{COLLECTION_NAME}'")


def query_rag(query: str, k: int = 5) -> List[Document]:
    """Retrieve top-k relevant chunks for a query."""
    vectorstore = _get_vectorstore()
    retriever = vectorstore.as_retriever(search_kwargs={"k": k})
    return retriever.invoke(query)
