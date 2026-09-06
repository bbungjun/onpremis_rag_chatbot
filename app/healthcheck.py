from __future__ import annotations

from app.config import Settings


def main() -> None:
    settings = Settings.from_env()
    print("llmenhance rag-api healthcheck")
    print(f"LLM model: {settings.llm_model}")
    print(f"LLM think mode: {settings.llm_think}")
    print(f"Embedding model: {settings.embedding_model}")
    print(f"Ollama base URL: {settings.ollama_base_url}")
    print(f"Qdrant URL: {settings.qdrant_url}")
    print(f"Qdrant collection: {settings.qdrant_collection}")
    print(f"Retrieval top_k: {settings.retrieval_top_k}")


if __name__ == "__main__":
    main()
