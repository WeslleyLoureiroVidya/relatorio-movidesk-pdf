import os
import sys

import requests

from gerar_relatorio import buscar_artigos_movidesk

TOKEN = os.environ.get("MOVIDESK_TOKEN")
BASE = "https://api.movidesk.com/public/v1"
MODELOS = [
    BASE + "/kb/article/{id}",
    BASE + "/article/{id}",
    BASE + "/article/{id}/kb",
]


def resumo(valor):
    texto = str(valor).replace("\n", " ")
    return texto[:80]


if __name__ == "__main__":
    if not TOKEN:
        print("Variável MOVIDESK_TOKEN ausente.")
        sys.exit(1)

    artigos = buscar_artigos_movidesk()
    if not artigos:
        print("Nenhum artigo retornado pela listagem.")
        sys.exit(1)

    print("CAMPOS NA LISTAGEM:", sorted(artigos[0].keys()))

    for artigo in artigos[:2]:
        id_artigo = artigo.get("id")
        print("\n=== Artigo", id_artigo, "===")
        for modelo in MODELOS:
            url = modelo.format(id=id_artigo)
            try:
                resposta = requests.get(url, params={"token": TOKEN}, timeout=60)
            except Exception as e:
                print(url, "-> erro de conexão:", e)
                continue

            print(url, "->", resposta.status_code)
            if resposta.status_code != 200:
                continue

            try:
                dados = resposta.json()
            except ValueError:
                print("   resposta não é JSON")
                continue

            if isinstance(dados, dict):
                print("   CAMPOS:", sorted(dados.keys()))
                for chave, valor in dados.items():
                    if chave not in ("contentHtml", "contentText"):
                        print("   ", chave, "=", resumo(valor))
            break
