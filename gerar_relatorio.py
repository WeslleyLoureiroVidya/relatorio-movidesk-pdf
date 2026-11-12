import os
import sys
import smtplib
from datetime import datetime
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from xml.sax.saxutils import escape

import requests
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

MOVIDESK_TOKEN = os.environ.get("MOVIDESK_TOKEN")
MAIL_USERNAME = os.environ.get("MAIL_USERNAME")
MAIL_PASSWORD = os.environ.get("MAIL_PASSWORD")
MAIL_DESTINATARIO = os.environ.get("MAIL_DESTINATARIO")

NOME_ARQUIVO_PDF = "relatorio_artigos_movidesk.pdf"

# API pública do Movidesk (confirme na documentação se o caminho mudou)
URL_ARTIGOS = "https://api.movidesk.com/public/v1/article"
TAMANHO_PAGINA = 100
MAX_PAGINAS = 50


def validar_variaveis():
    faltando = [
        nome
        for nome, valor in [
            ("MOVIDESK_TOKEN", MOVIDESK_TOKEN),
            ("MAIL_USERNAME", MAIL_USERNAME),
            ("MAIL_PASSWORD", MAIL_PASSWORD),
            ("MAIL_DESTINATARIO", MAIL_DESTINATARIO),
        ]
        if not valor
    ]
    if faltando:
        print(f"Variáveis de ambiente ausentes: {', '.join(faltando)}")
        sys.exit(1)


def buscar_artigos_movidesk():
    artigos = []
    primeiro_id_anterior = None

    for pagina in range(MAX_PAGINAS):
        params = {
            "token": MOVIDESK_TOKEN,
            "$top": TAMANHO_PAGINA,
            "$skip": pagina * TAMANHO_PAGINA,
        }
        try:
            response = requests.get(URL_ARTIGOS, params=params, timeout=60)
        except Exception as e:
            print(f"Erro de conexão: {e}")
            return artigos

        if response.status_code != 200:
            print(f"Erro na API do Movidesk: {response.status_code}")
            print(response.text[:500])
            return artigos

        try:
            dados = response.json()
        except ValueError:
            print("Resposta da API não é JSON válido:")
            print(response.text[:500])
            return artigos

        lote = dados if isinstance(dados, list) else [dados]
        if not lote:
            break

        # Proteção caso a API ignore o $skip e repita a mesma página
        primeiro_id = lote[0].get("id") if isinstance(lote[0], dict) else None
        if primeiro_id is not None and primeiro_id == primeiro_id_anterior:
            break
        primeiro_id_anterior = primeiro_id

        artigos.extend(lote)
        if len(lote) < TAMANHO_PAGINA:
            break

    return artigos


def numero(artigo, *chaves):
    """Retorna o primeiro valor numérico encontrado entre as chaves."""
    for chave in chaves:
        valor = artigo.get(chave)
        if isinstance(valor, (int, float)):
            return int(valor)
    return 0


def contar_comentarios(artigo):
    comentarios = artigo.get("comments")
    if isinstance(comentarios, list) and comentarios:
        return len(comentarios)
    return numero(artigo, "commentsCount", "commentCount")


def gerar_pdf(artigos):
    doc = SimpleDocTemplate(
        NOME_ARQUIVO_PDF,
        pagesize=A4,
        rightMargin=30,
        leftMargin=30,
        topMargin=30,
        bottomMargin=30,
    )
    elementos = []
    styles = getSampleStyleSheet()

    titulo_estilo = ParagraphStyle(
        "TituloRelatorio",
        parent=styles["Heading1"],
        fontSize=18,
        textColor=colors.HexColor("#1E3A8A"),
        spaceAfter=6,
    )
    subtitulo_estilo = ParagraphStyle(
        "SubTituloRelatorio",
        parent=styles["Normal"],
        fontSize=10,
        textColor=colors.HexColor("#4B5563"),
        spaceAfter=15,
    )
    celula_estilo = ParagraphStyle(
        "CelulaTabela",
        parent=styles["Normal"],
        fontSize=9,
        textColor=colors.HexColor("#1F2937"),
    )
    cabecalho_estilo = ParagraphStyle(
        "CabecalhoTabela",
        parent=styles["Normal"],
        fontSize=9,
        textColor=colors.white,
        fontName="Helvetica-Bold",
    )

    elementos.append(
        Paragraph("Relatório Consolidado - Base de Conhecimento", titulo_estilo)
    )
    data_atual = datetime.now().strftime("%d/%m/%Y")
    elementos.append(
        Paragraph(f"Gerado em: {data_atual} | Ranking de artigos", subtitulo_estilo)
    )

    total_artigos = len(artigos)
    total_views = sum(numero(a, "views", "viewCount", "viewsCount") for a in artigos)
    total_likes = sum(numero(a, "likes", "likesCount") for a in artigos)
    total_comments = sum(contar_comentarios(a) for a in artigos)

    resumo_data = [
        [
            Paragraph("Total de Artigos", cabecalho_estilo),
            Paragraph("Total de Visualizações", cabecalho_estilo),
            Paragraph("Total de Curtidas", cabecalho_estilo),
            Paragraph("Total de Comentários", cabecalho_estilo),
        ],
        [
            Paragraph(str(total_artigos), celula_estilo),
            Paragraph(str(total_views), celula_estilo),
