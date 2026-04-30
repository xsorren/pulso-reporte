"""
Smoke test for the FAISS knowledge base.

Runs a set of representative queries against base_conocimiento.index and prints
the top-K matching chunks, tagging which ones come from the master index
([INDICE_MAESTRO_PULSO_VITAL_v1]) vs the original PDFs.

Usage:
    OPENAI_API_KEY=sk-... python smoke_test_indice.py
    OPENAI_API_KEY=sk-... python smoke_test_indice.py "tu consulta libre"
    OPENAI_API_KEY=sk-... python smoke_test_indice.py --k 3
"""
from __future__ import annotations

import argparse
import os
import pickle
import sys
from pathlib import Path

import faiss
import numpy as np
from openai import OpenAI


INDEX_FILE = "base_conocimiento.index"
TEXTOS_FILE = "textos.pkl"
EMBEDDING_MODEL = "text-embedding-3-small"
SENTINEL_TAG = "[INDICE_MAESTRO_PULSO_VITAL_v1]"

DEFAULT_QUERIES = [
    "cliente con hijos pequeños de 0 a 5 años busca proteger educación universitaria",
    "cliente con capital excedente y fondo de emergencia busca rendimiento alto",
    "cliente con hijos mayores de 5 años busca acumulación para educación",
    "cliente sin seguro de gastos médicos mayores con buena liquidez",
    "empresario que quiere proteger persona clave de su empresa",
    "cliente con baja liquidez busca protección barata para su familia",
    "persona con patrimonio amplio busca herencia y protección vitalicia",
    "cliente quiere ahorrar pero no tiene disciplina y no necesita liquidez frecuente",
    "persona busca retiro con posible deducibilidad fiscal",
    "cliente busca inversión flexible con protección y tiene fondo de emergencia",
]


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke test del índice FAISS")
    parser.add_argument("query", nargs="?", help="Consulta libre (opcional)")
    parser.add_argument("--k", type=int, default=5, help="Top-K resultados (default 5)")
    args = parser.parse_args()

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("ERROR: OPENAI_API_KEY no está configurada.", file=sys.stderr)
        return 1

    base = Path(__file__).resolve().parent
    index_path = base / INDEX_FILE
    textos_path = base / TEXTOS_FILE
    if not index_path.exists() or not textos_path.exists():
        print(f"ERROR: faltan {INDEX_FILE} o {TEXTOS_FILE}", file=sys.stderr)
        return 1

    print(f"Cargando índice ({index_path.name})...")
    index = faiss.read_index(str(index_path))
    with textos_path.open("rb") as f:
        textos: list[str] = pickle.load(f)
    print(f"  Vectores: {index.ntotal}  |  Textos: {len(textos)}")

    queries = [args.query] if args.query else DEFAULT_QUERIES
    client = OpenAI(api_key=api_key)

    for q in queries:
        emb = client.embeddings.create(model=EMBEDDING_MODEL, input=[q]).data[0].embedding
        vec = np.array([emb], dtype="float32")
        D, I = index.search(vec, args.k)

        print(f"\n>>> {q}")
        for rank, (dist, i) in enumerate(zip(D[0], I[0]), 1):
            if 0 <= i < len(textos):
                t = textos[i]
                tag = "MAESTRO" if SENTINEL_TAG in t else "PDF    "
                preview = t.replace("\n", " ")[:160]
                print(f"  [{rank}] dist={dist:.3f} [{tag}] {preview}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
