"""
Script exploratorio (no es un test de pytest) para verificar a ojo que
embed_text() / embed_batch() están produciendo embeddings sensatos.

Uso:
    python scripts/check_embeddings.py

Qué hace: genera embeddings para varios pares de frases y calcula su
similitud coseno. Como normalizamos los vectores (normalize_embeddings=True
en embeddings.py), la similitud coseno es simplemente el producto punto.
"""

import numpy as np

from app.core.embeddings import embed_text, embed_batch


def cosine_sim(a: list[float], b: list[float]) -> float:
    # Con vectores normalizados (norma == 1), esto YA ES la similitud coseno.
    return float(np.dot(a, b))


def check(nombre: str, texto_a: str, texto_b: str, esperado: str):
    va = embed_text(texto_a)
    vb = embed_text(texto_b)
    sim = cosine_sim(va, vb)
    print(f"[{nombre}] esperado: {esperado}")
    print(f"  A: {texto_a!r}")
    print(f"  B: {texto_b!r}")
    print(f"  similitud coseno = {sim:.4f}\n")


def main():
    print("=== 1. Frases parecidas (paráfrasis) -> similitud ALTA ===")
    check(
        "parafraseo",
        "¿Cuántos usuarios se registraron el mes pasado?",
        "Número de usuarios nuevos dados de alta en el último mes",
        "cercana a 1 (ej. > 0.6)",
    )

    print("=== 2. Frases de dominios distintos -> similitud BAJA ===")
    check(
        "dominios distintos",
        "¿Cuántos usuarios se registraron el mes pasado?",
        "La receta de la tortilla de patatas lleva huevo, patata y cebolla",
        "baja (ej. < 0.3)",
    )

    print("=== 3. Texto idéntico consigo mismo -> similitud debe ser ~1.0 ===")
    print("   (esto confirma que normalize_embeddings=True funciona: el")
    print("    ángulo de un vector consigo mismo es 0, coseno(0) = 1)\n")
    texto = "tabla users con columna created_at"
    v1 = embed_text(texto)
    v2 = embed_text(texto)
    sim_self = cosine_sim(v1, v2)
    norma = float(np.linalg.norm(v1))
    print(f"  similitud consigo mismo = {sim_self:.6f} (debería ser ~1.0)")
    print(f"  norma del vector        = {norma:.6f} (debería ser ~1.0)\n")

    print("=== 4. embed_batch debe dar el MISMO resultado que embed_text uno a uno ===")
    frases = [
        "¿Cuántos usuarios se registraron el mes pasado?",
        "tabla invoices con columna status",
    ]
    batch_result = embed_batch(frases)
    individuales = [embed_text(f) for f in frases]
    for i, (b, ind) in enumerate(zip(batch_result, individuales)):
        diff = float(np.max(np.abs(np.array(b) - np.array(ind))))
        print(f"  frase {i}: diferencia máxima entre batch e individual = {diff:.8f}")
    print("  (debería ser ~0.0 -> mismo modelo, mismo resultado, venga en batch o no)\n")

    print("=== bonus: caso vacío ===")
    print(f"  embed_batch([]) = {embed_batch([])!r} (debería ser [] sin lanzar error)")


if __name__ == "__main__":
    main()
