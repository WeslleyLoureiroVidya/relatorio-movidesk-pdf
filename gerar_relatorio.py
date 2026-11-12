import os
import sys
import time
import smtplib
from datetime import datetime, timedelta
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

URLS_CANDIDATAS = [
    "https://api.movidesk.com/public/v1/kb/article",
    "https://api.movidesk.com/public/v1/article",
]
TAMANHO_PAGINA = 100
MAX_PAGINAS = 100
ESPERA_ENTRE_PAGINAS = 7  # limite da API: 10 requisições por minuto

STATUS_NOMES = {1: "Publicado", 2: "Suspenso", 4: "Suspenso"}


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


def buscar_pagina(url, pagina):
    params = {
        "token": MOVIDESK_TOKEN,
        "page": pagina,
        "pageSize": TAMANHO_PAGINA,
    }
    return requests.get(url, params=params, timeout=60)


def buscar_com_url(url):
    """Retorna a lista de artigos, ou None se a URL deu 404."""
    artigos = []
    total = None

    for pagina in range(MAX_PAGINAS):
        if pagina > 0:
            time.sleep(ESPERA_ENTRE_PAGINAS)

        try:
            response = buscar_pagina(url, pagina)
        except Exception as e:
            print(f"Erro de conexão: {e}")
            return artigos

        if response.status_code == 404 and pagina == 0:
            print(f"404 em {url}")
            return None

        if response.status_code != 200:
            print(f"Erro na API do Movidesk: {response.status_code}")
            print(response.text[:300])
            return artigos

        try:
            dados = response.json()
        except ValueError:
            print("Resposta da API não é JSON válido:")
            print(response.text[:300])
            return artigos

        if isinstance(dados, dict):
            itens = dados.get("items") or []
            if total is None:
                total = dados.get("totalSize")
        else:
            itens = dados

        if not itens:
            break

        artigos.extend(itens)
        if total is not None and len(artigos) >= total:
            break

    return artigos


def buscar_artigos_movidesk():
    for url in URLS_CANDIDATAS:
        print(f"Tentando {url}")
        resultado = buscar_com_url(url)
        if resultado is not None:
            print(f"Endpoint que funcionou: {url}")
            return resultado
    return []


def parse_data(texto):
    if not texto:
        return None
    try:
        return datetime.strptime(str(texto)[:10], "%Y-%m-%d")
    except ValueError:
        return None


def data_curta(texto):
    data = parse_data(texto)
    if data is None:
        return "-"
    return data.strftime("%d/%m/%Y")


def data_atualizacao(artigo):
    return artigo.get("updatedAt") or artigo.get("updatedDate")


def nome_menu(artigo):
    menu = artigo.get("menu")
    if isinstance(menu, dict) and menu.get("name"):
        return str(menu["name"])
    return "-"


def nome_status(artigo):
    return STATUS_NOMES.get(artigo.get("status"), "-")


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
        Paragraph("Relatório - Base de Conhecimento", titulo_estilo)
    )
    data_atual = datetime.now().strftime("%d/%m/%Y")
    elementos.append(
        Paragraph(f"Gerado em: {data_atual}", subtitulo_estilo)
    )

    limite = datetime.now() - timedelta(days=30)
    total_artigos = len(artigos)
    publicados = sum(1 for a in artigos if a.get("status") == 1)
    suspensos = sum(1 for a in artigos if a.get("status") in (2, 4))
    recentes = 0
    for a in artigos:
        data = parse_data(data_atualizacao(a))
        if data is not None and data >= limite:
            recentes += 1

    cab_resumo = [
        Paragraph("Total de Artigos", cabecalho_estilo),
        Paragraph("Publicados", cabecalho_estilo),
        Paragraph("Suspensos", cabecalho_estilo),
        Paragraph("Atualizados (30 dias)", cabecalho_estilo),
    ]
    val_resumo = [
        Paragraph(str(total_artigos), celula_estilo),
        Paragraph(str(publicados), celula_estilo),
        Paragraph(str(suspensos), celula_estilo),
        Paragraph(str(recentes), celula_estilo),
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
        artigos,
        key=lambda a: str(data_atualizacao(a) or ""),
        reverse=True,
    )

    cabecalho = [
        Paragraph("#", cabecalho_estilo),
        Paragraph("Título do Artigo", cabecalho_estilo),
        Paragraph("Status", cabecalho_estilo),
        Paragraph("Menu", cabecalho_estilo),
        Paragraph("Criado", cabecalho_estilo),
        Paragraph("Atualizado", cabecalho_estilo),
    ]
    tabela_dados = [cabecalho]

    for index, artigo in enumerate(artigos_ordenados, start=1):
        titulo = artigo.get("title") or "Sem título"
        linha = []
        linha.append(Paragraph(str(index), celula_estilo))
        linha.append(Paragraph(escape(str(titulo)), celula_estilo))
        linha.append(Paragraph(nome_status(artigo), celula_estilo))
        linha.append(Paragraph(escape(nome_menu(artigo)), celula_estilo))
        linha.append(
            Paragraph(data_curta(artigo.get("createdAt") or artigo.get("createdDate")), celula_estilo)
        )
        linha.append(
            Paragraph(data_curta(data_atualizacao(artigo)), celula_estilo)
        )
        tabela_dados.append(linha)

    tabela_artigos = Table(
        tabela_dados, colWidths=[28, 215, 60, 90, 62, 62], repeatRows=1
    )
    estilo_artigos = TableStyle(
        [
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1F2937")),
            ("ALIGN", (0, 0), (0, -1), "CENTER"),
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
        "Olá!\n\nSegue em anexo o relatório dos artigos da Base de "
        "Conhecimento do Movidesk.\n\n"
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
