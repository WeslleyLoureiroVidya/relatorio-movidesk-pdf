import csv
import os
import sys

from gerar_relatorio import buscar_artigos_movidesk

SAIDA = "modelo_metricas_artigos.csv"
COLUNAS = ["id", "titulo", "views", "lidos", "likes", "dislikes", "comentarios"]


if __name__ == "__main__":
    if not os.environ.get("MOVIDESK_TOKEN"):
        print("Variável MOVIDESK_TOKEN ausente.")
        sys.exit(1)

    artigos = buscar_artigos_movidesk()
    if not artigos:
        print("Nenhum artigo retornado pela API.")
        sys.exit(1)

    artigos.sort(key=lambda a: str(a.get("title") or "").lower())

    with open(SAIDA, "w", encoding="utf-8-sig", newline="") as f:
        escritor = csv.writer(f, delimiter=";")
        escritor.writerow(COLUNAS)
        for a in artigos:
            escritor.writerow([a.get("id"), a.get("title") or "Sem título", "", "", "", "", ""])

    print(f"{len(artigos)} artigos gravados em {SAIDA}")
