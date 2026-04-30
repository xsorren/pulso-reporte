"""
Append the master product index (indice_maestro.md) to the existing FAISS knowledge base.

Run once after editing indice_maestro.md to refresh the search index.

Usage:
    OPENAI_API_KEY=sk-... python agregar_indice_maestro.py

Output:
    base_conocimiento.index.new
    textos.pkl.new

Replace the originals manually after verifying:
    mv base_conocimiento.index.new base_conocimiento.index
    mv textos.pkl.new textos.pkl
"""
from __future__ import annotations

import os
import pickle
import re
import sys
from pathlib import Path

import faiss
import numpy as np
from openai import OpenAI


INDEX_FILE = "base_conocimiento.index"
TEXTOS_FILE = "textos.pkl"
MAESTRO_FILE = "indice_maestro.md"
EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIM = 1536
BATCH_SIZE = 50

SENTINEL_TAG = "[INDICE_MAESTRO_PULSO_VITAL_v1]"


def chunk_indice_maestro(text: str) -> list[str]:
    """
    Splits the master index into semantic chunks:
      - Each '## PRODUCTO: Name' ficha becomes one chunk.
      - Each top-level '# N. Section' becomes one chunk (except the section that
        only contains product fichas, which is replaced by the per-product chunks).

    Tiny chunks (<80 chars, e.g. orphan headers) are discarded.
    """
    lines = text.split("\n")
    chunks: list[str] = []
    current: list[str] = []
    inside = False

    def flush() -> None:
        nonlocal current
        if current:
            content = "\n".join(current).strip()
            if len(content) >= 80:
                chunks.append(content)
        current = []

    for line in lines:
        if re.match(r"^#\s+\d+\.\s", line) or re.match(r"^##\s+PRODUCTO:\s", line):
            flush()
            current = [line]
            inside = True
        elif inside:
            current.append(line)

    flush()
    return chunks


def annotate_chunks(chunks: list[str]) -> list[str]:
    """
    Prefix every chunk with a sentinel tag so we can detect duplicates and
    so the search results are easy to identify as coming from the master index.
    """
    return [f"{SENTINEL_TAG}\n{c}" for c in chunks]


def embed_batch(client: OpenAI, texts: list[str]) -> np.ndarray:
    all_vecs: list[list[float]] = []
    for i in range(0, len(texts), BATCH_SIZE):
        batch = texts[i : i + BATCH_SIZE]
        resp = client.embeddings.create(model=EMBEDDING_MODEL, input=batch)
        all_vecs.extend(d.embedding for d in resp.data)
    return np.array(all_vecs, dtype="float32")


def main() -> int:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("ERROR: OPENAI_API_KEY no está configurada.", file=sys.stderr)
        return 1

    base = Path(__file__).resolve().parent
    index_path = base / INDEX_FILE
    textos_path = base / TEXTOS_FILE
    maestro_path = base / MAESTRO_FILE

    for p in (index_path, textos_path, maestro_path):
        if not p.exists():
            print(f"ERROR: no existe {p}", file=sys.stderr)
            return 1

    print(f"Leyendo {maestro_path.name}...")
    master_text = maestro_path.read_text(encoding="utf-8")

    raw_chunks = chunk_indice_maestro(master_text)
    if not raw_chunks:
        print("ERROR: no se generaron chunks del índice maestro.", file=sys.stderr)
        return 1
    chunks = annotate_chunks(raw_chunks)
    print(f"Generados {len(chunks)} chunks.")

    print(f"Cargando índice FAISS y textos existentes...")
    index = faiss.read_index(str(index_path))
    with textos_path.open("rb") as f:
        textos: list[str] = pickle.load(f)
    print(f"  Vectores existentes: {index.ntotal}")
    print(f"  Textos existentes:   {len(textos)}")

    if any(SENTINEL_TAG in t for t in textos):
        print(
            f"\n⚠️  Detectado sentinel '{SENTINEL_TAG}' en los textos existentes.\n"
            f"   El índice maestro ya fue cargado. Abortando para evitar duplicados.\n"
            f"   Si querés reemplazarlo, primero recreá el índice desde cero.",
            file=sys.stderr,
        )
        return 2

    if index.d != EMBEDDING_DIM:
        print(
            f"ERROR: dimensión del índice ({index.d}) != esperada ({EMBEDDING_DIM}).\n"
            f"El índice fue creado con un modelo distinto a {EMBEDDING_MODEL}.",
            file=sys.stderr,
        )
        return 1

    print(f"Generando embeddings con {EMBEDDING_MODEL}...")
    client = OpenAI(api_key=api_key)
    vectors = embed_batch(client, chunks)
    print(f"  Embeddings shape: {vectors.shape}")

    if vectors.shape[1] != index.d:
        print(
            f"ERROR: dimensión de embeddings ({vectors.shape[1]}) != índice ({index.d}).",
            file=sys.stderr,
        )
        return 1

    print("Apendiendo al índice y a los textos...")
    index.add(vectors)
    textos.extend(chunks)
    print(f"  Vectores tras append: {index.ntotal}")
    print(f"  Textos tras append:   {len(textos)}")

    new_index = index_path.with_suffix(index_path.suffix + ".new")
    new_textos = textos_path.with_suffix(textos_path.suffix + ".new")
    faiss.write_index(index, str(new_index))
    with new_textos.open("wb") as f:
        pickle.dump(textos, f)

    print("\n✅ Listo.")
    print(f"   {new_index.name}")
    print(f"   {new_textos.name}")
    print(
        "\nVerificá los archivos y luego activalos:\n"
        f"   mv {new_index.name} {index_path.name}\n"
        f"   mv {new_textos.name} {textos_path.name}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
