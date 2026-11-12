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

URL_ARTIGOS = "https://api.movidesk.com/public/v1/article"
TAMANHO_PAGINA = 100
MAX_PAGINAS = 50

CHAVES_VIEWS = ("views", "viewCount", "viewsCount")
CHAVES_LIKES = ("likes", "likesCount")
CHAVES_DISLIKES = ("dislikes", "dislikesCount")


def validar_variaveis():
    variaveis = {
        "MOVIDESK_TOKEN": MOVIDESK_TOKEN,
        "MAIL_USERNAME": MAIL_USERNAME,
        "MAIL_PASSWORD": MAIL_PASSWORD,
        "MAIL_DESTINATARIO": MAIL_DESTINATARIO,
    }
    faltando = [nome for nome, valor in variaveis.items() if not valor]
    if faltando:
        print("Variáveis de ambiente ausentes: " + ", ".join(faltando))
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

        primeiro_id = None
        if isinstance(lote[0], dict):
            primeiro_id = lote[0].get("id")
        if primeiro_id is not None and primeiro_id == primeiro_id_anterior:
            break
        primeiro_id_anterior = primeiro_id

        artigos.extend(lote)
        if len(lote) < TAMANHO_PAGINA:
            break

    return artigos


def numero(artigo, chaves):
    for chave in chaves:
        valor = artigo.get(chave)
        if isinstance(valor, (int, float)):
            return int(valor)
    return 0


def contar_comentarios(artigo):
    comentarios = artigo.get("comments")
    if isinstance(comentarios, list) and comentarios:
        return len(comentarios)
    return numero(artigo, ("commentsCount", "commentCount"))


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
    total_views = sum(numero(a, CHAVES_VIEWS) for a in artigos)
    total_likes = sum(numero(a, CHAVES_LIKES) for a in artigos)
    total_comments = sum(contar_comentarios(a) for a in artigos)

    cab_resumo = [
        Paragraph("Total de Artigos", cabecalho_estilo),
        Paragraph("Total de Visualizações", cabecalho_estilo),
        Paragraph("Total de Curtidas", cabecalho_estilo),
        Paragraph("Total de Comentários", cabecalho_estilo),
    ]
    val_resumo = [
        Paragraph(str(total_artigos), celula_estilo),
        Paragraph(str(total_views), celula_estilo),
        Paragraph(str(total_likes), celula_estilo),
        Paragraph(str(total_comments), celula_estilo),
    ]
    resumo_data = [cab_resumo, val_resumo]

    tabela_resumo = Table(resumo_data, colWidths=[130, 130, 130, 130])
    estilo_resumo = TableStyle(
        [
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2563EB")),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ("TOPPADDING", (0, 0), (-1, -1), 8),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#D1D5DB")),
        ]
    )
    tabela_resumo.setStyle(estilo_resumo)
    elementos.append(tabela_resumo)
    elementos.append(Spacer(1, 15))

    artigos_ordenados = sorted(
        artigos, key=lambda a: numero(a, CHAVES_VIEWS), reverse=True
    )

    cabecalho = [
        Paragraph("#", cabecalho_estilo),
        Paragraph("Título do Artigo", cabecalho_estilo),
        Paragraph("Views", cabecalho_estilo),
        Paragraph("Likes", cabecalho_estilo),
        Paragraph("Dislikes", cabecalho_estilo),
        Paragraph("Coment.", cabecalho_estilo),
    ]
    tabela_dados = [cabecalho]

    for index, artigo in enumerate(artigos_ordenados, start=1):
        titulo = (
            artigo.get("title")
            or artigo.get("subject")
            or artigo.get("articleTitle")
            or "Sem título"
        )
        views = numero(artigo, CHAVES_VIEWS)
        likes = numero(artigo, CHAVES_LIKES)
        dislikes = numero(artigo, CHAVES_DISLIKES)
        comentarios = contar_comentarios(artigo)

        linha = []
        linha.append(Paragraph(str(index), celula_estilo))
        linha.append(Paragraph(escape(str(titulo)), celula_estilo))
        linha.append(Paragraph(str(views), celula_estilo))
        linha.append(Paragraph(str(likes), celula_estilo))
        linha.append(Paragraph(str(dislikes), celula_estilo))
        linha.append(Paragraph(str(comentarios), celula_estilo))
        tabela_dados.append(linha)

    tabela_artigos = Table(
        tabela_dados, colWidths=[25, 275, 50, 50, 50, 70], repeatRows=1
    )
    estilo_artigos = TableStyle(
        [
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1F2937")),
            ("ALIGN", (0, 0), (0, -1), "CENTER"),
            ("ALIGN", (2, 0), (-1, -1), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F9FAFB")]),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#E5E7EB")),
        ]
    )
    tabela_artigos.setStyle(estilo_artigos)
    elementos.append(tabela_artigos)

    doc.build(elementos)
    print(f"PDF gerado: {NOME_ARQUIVO_PDF}")


def enviar_email():
    if not os.path.exists(NOME_ARQUIVO_PDF):
        print("Arquivo PDF não foi gerado.")
        sys.exit(1)

    msg = MIMEMultipart()
    msg["From"] = MAIL_USERNAME
    msg["To"] = MAIL_DESTINATARIO
    msg["Subject"] = "Relatório Automatizado - Artigos Movidesk"

    corpo = (
        "Olá!\n\nSegue em anexo o relatório consolidado com o ranking dos "
        "artigos da Base de Conhecimento do Movidesk.\n\n"
        "Atenciosamente,\nAutomação VIDYA"
    )
    msg.attach(MIMEText(corpo, "plain", "utf-8"))

    with open(NOME_ARQUIVO_PDF, "rb") as f:
        part = MIMEBase("application", "pdf")
        part.set_payload(f.read())
    encoders.encode_base64(part)
    part.add_header(
        "Content-Disposition", f'attachment; filename="{NOME_ARQUIVO_PDF}"'
    )
    msg.attach(part)

    destinatarios = [e.strip() for e in MAIL_DESTINATARIO.split(",")]

    try:
        with smtplib.SMTP("smtp.gmail.com", 587, timeout=60) as server:
            server.starttls()
            server.login(MAIL_USERNAME, MAIL_PASSWORD)
            server.sendmail(MAIL_USERNAME, destinatarios, msg.as_string())
        print("E-mail enviado com sucesso!")
    except Exception as e:
        print(f"Erro ao enviar e-mail: {e}")
        sys.exit(1)


if __name__ == "__main__":
    validar_variaveis()
    dados_artigos = buscar_artigos_movidesk()

    if not dados_artigos:
        print("Nenhum dado retornado pela API do Movidesk.")
        sys.exit(1)

    if isinstance(dados_artigos[0], dict):
        print("Campos disponíveis no artigo:", sorted(dados_artigos[0].keys()))
    print(f"{len(dados_artigos)} artigos recebidos.")

    gerar_pdf(dados_artigos)
    enviar_email()
