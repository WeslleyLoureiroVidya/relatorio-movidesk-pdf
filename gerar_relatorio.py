import json
import os
import re
import sys
import time
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

MOVIDESK_USER = os.environ.get("MOVIDESK_USER")
MOVIDESK_PASSWORD = os.environ.get("MOVIDESK_PASSWORD")
MAIL_USERNAME = os.environ.get("MAIL_USERNAME")
MAIL_PASSWORD = os.environ.get("MAIL_PASSWORD")
MAIL_DESTINATARIO = os.environ.get("MAIL_DESTINATARIO")

BASE = "https://vidya-code.movidesk.com"
NOME_ARQUIVO_PDF = "relatorio_artigos_movidesk.pdf"

TAMANHO_PAGINA = 80
MAX_PAGINAS = 100
PAUSA = 0.25  # segundos entre consultas
MAX_FALHAS_SEGUIDAS = 5


def validar_variaveis():
    variaveis = {
        "MOVIDESK_USER": MOVIDESK_USER,
        "MOVIDESK_PASSWORD": MOVIDESK_PASSWORD,
        "MAIL_USERNAME": MAIL_USERNAME,
        "MAIL_PASSWORD": MAIL_PASSWORD,
        "MAIL_DESTINATARIO": MAIL_DESTINATARIO,
    }
    faltando = [nome for nome, valor in variaveis.items() if not valor]
    if faltando:
        print("Variáveis de ambiente ausentes: " + ", ".join(faltando))
        sys.exit(1)


# ---------------------------------------------------------------- login

def ler_json(texto):
    """Aceita JSON puro ou JSONP (callback(...))."""
    texto = (texto or "").strip()
    if not texto:
        return None
    try:
        if texto[0] in "{[":
            return json.loads(texto)
        achado = re.match(r"^[^(]*\((.*)\)\s*;?\s*$", texto, re.DOTALL)
        if achado:
            return json.loads(achado.group(1))
    except ValueError:
        return None
    return None


def extrair_token(html):
    padroes = [
        r'name="__RequestVerificationToken"[^>]*value="([^"]+)"',
        r'value="([^"]+)"[^>]*name="__RequestVerificationToken"',
    ]
    for padrao in padroes:
        achado = re.search(padrao, html)
        if achado:
            return achado.group(1)
    return None


def criar_sessao_logada():
    sessao = requests.Session()
    sessao.headers.update({"User-Agent": "Mozilla/5.0 (relatorio-automatico)"})

    pagina = sessao.get(BASE + "/", timeout=60)
    token = extrair_token(pagina.text)
    if token is None:
        print("Aviso: token anti-forgery não encontrado na página de login.")

    dados = {
        "UseCaptcha": "False",
        "ValidateCaptcha": "False",
        "ReturnUrl": "",
        "SsoProviderType": "",
        "UserName": MOVIDESK_USER,
        "UserNameError": "",
        "Password": MOVIDESK_PASSWORD,
        "PasswordError": "",
    }
    if token:
        dados["__RequestVerificationToken"] = token

    cabecalhos = {
        "X-Requested-With": "XMLHttpRequest",
        "Referer": BASE + "/",
        "Accept": "application/json, text/javascript, */*; q=0.01",
    }
    resposta = sessao.post(
        BASE + "/Account/Login", data=dados, headers=cabecalhos, timeout=60
    )
    print(f"Login: HTTP {resposta.status_code}")
    print("Resposta do login (início):", resposta.text[:150].replace("\n", " "))

    # Confirma que a sessão está valida consultando a lista de artigos
    teste = sessao.get(
        BASE + "/KbArticle/Json", params={"Start": 0, "Limit": 1}, timeout=60
    )
    dados_teste = ler_json(teste.text)
    if not isinstance(dados_teste, dict) or "results" not in dados_teste:
        print("Falha no login: a lista de artigos não foi retornada.")
        print("Possíveis causas: usuário/senha errados, MFA ou captcha ativo.")
        sys.exit(1)

    print("Login confirmado.")
    return sessao


# ---------------------------------------------------------------- dados

def obter_json(sessao, caminho, params):
    for tentativa in range(3):
        try:
            resposta = sessao.get(BASE + caminho, params=params, timeout=60)
            if resposta.status_code == 200:
                dados = ler_json(resposta.text)
                if dados is not None:
                    return dados
            print(f"Falha em {caminho}: HTTP {resposta.status_code}")
        except Exception as e:
            print(f"Erro de conexão em {caminho}: {e}")
        time.sleep(2)
    return None


def listar_artigos(sessao):
    artigos = []
    vistos = set()
    inicio = 0

    for _ in range(MAX_PAGINAS):
        dados = obter_json(
            sessao, "/KbArticle/Json", {"Start": inicio, "Limit": TAMANHO_PAGINA}
        )
        if not isinstance(dados, dict):
            break

        itens = dados.get("results") or []
        total = dados.get("hits")

        for item in itens:
            id_artigo = item.get("Id")
            if id_artigo not in vistos:
                vistos.add(id_artigo)
                artigos.append(item)

        inicio += TAMANHO_PAGINA
        if not itens or (total is not None and inicio >= total):
            break
        time.sleep(PAUSA)

    return artigos


def para_int(valor):
    if isinstance(valor, bool):
        return None
    if isinstance(valor, (int, float)):
        return int(valor)
    return None


def coletar_metricas(sessao, artigos):
    registros = []
    falhas_seguidas = 0
    estrutura_comentario_mostrada = False

    for posicao, artigo in enumerate(artigos, start=1):
        id_artigo = artigo.get("Id")
        registro = {
            "id": id_artigo,
            "titulo": artigo.get("Title") or "Sem título",
            "likes": para_int(artigo.get("PositiveRatingCount")),
            "dislikes": para_int(artigo.get("NegativeRatingCount")),
            "views": None,
            "lidos": None,
            "comentarios": None,
        }

        painel = obter_json(
            sessao,
            "/KbArticle/Dashboard",
            {
                "articleId": id_artigo,
                "periodStartDate": "",
                "periodEndDate": "",
                "period": "",
                "language": "",
            },
        )
        if isinstance(painel, dict):
            engajamento = painel.get("engagement") or {}
            registro["views"] = para_int(engajamento.get("NumberOfViews"))
            registro["lidos"] = para_int(engajamento.get("NumberOfReadings"))
            falhas_seguidas = 0
        else:
            falhas_seguidas += 1

        time.sleep(PAUSA)

        feedback = obter_json(
            sessao,
            "/KbArticle/SearchSettingsFieldsFeedback",
            {
                "period": "",
                "periodStartDate": "",
                "periodEndDate": "",
                "articleId": id_artigo,
                "onlyComments": "true",
                "language": "",
                "page": 1,
            },
        )
        if isinstance(feedback, dict):
            resultados = feedback.get("results") or []
            quantidade = para_int(feedback.get("count"))
            if quantidade is None:
                quantidade = len(resultados)
            registro["comentarios"] = quantidade

            if resultados and not estrutura_comentario_mostrada:
                primeiro = resultados[0]
                if isinstance(primeiro, dict):
                    print("Estrutura de um comentário (campos):", sorted(primeiro.keys()))
                estrutura_comentario_mostrada = True

        registros.append(registro)

        if falhas_seguidas >= MAX_FALHAS_SEGUIDAS:
            print("Muitas falhas seguidas: a sessão pode ter expirado. Abortando.")
            sys.exit(1)

        if posicao % 20 == 0:
            print(f"{posicao}/{len(artigos)} artigos consultados...")
        time.sleep(PAUSA)

    return registros


def metrica_disponivel(registros, metrica):
    return any(r.get(metrica) is not None for r in registros)


def top(registros, metrica, quantidade):
    candidatos = [r for r in registros if (r.get(metrica) or 0) > 0]
    candidatos.sort(key=lambda r: r[metrica], reverse=True)
    return candidatos[:quantidade]


# ----------------------------------------------------------------- PDF

def criar_estilos():
    styles = getSampleStyleSheet()
    return {
        "titulo": ParagraphStyle(
            "TituloRelatorio", parent=styles["Heading1"], fontSize=18,
            textColor=colors.HexColor("#1E3A8A"), spaceAfter=6,
        ),
        "subtitulo": ParagraphStyle(
            "SubTituloRelatorio", parent=styles["Normal"], fontSize=10,
            textColor=colors.HexColor("#4B5563"), spaceAfter=12,
        ),
        "secao": ParagraphStyle(
            "SecaoRelatorio", parent=styles["Heading2"], fontSize=13,
            textColor=colors.HexColor("#1F2937"), spaceBefore=14, spaceAfter=6,
        ),
        "celula": ParagraphStyle(
            "CelulaTabela", parent=styles["Normal"], fontSize=9,
            textColor=colors.HexColor("#1F2937"),
        ),
        "cabecalho": ParagraphStyle(
            "CabecalhoTabela", parent=styles["Normal"], fontSize=9,
            textColor=colors.white, fontName="Helvetica-Bold",
        ),
        "aviso": ParagraphStyle(
            "AvisoRelatorio", parent=styles["Normal"], fontSize=9,
            textColor=colors.HexColor("#92400E"),
        ),
    }


def estilo_tabela(cor_cabecalho):
    return TableStyle(
        [
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(cor_cabecalho)),
            ("ALIGN", (0, 0), (0, -1), "CENTER"),
            ("ALIGN", (2, 0), (-1, -1), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F9FAFB")]),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#E5E7EB")),
        ]
    )


def montar_tabela(estilos, rotulo, itens, metrica, cor):
    linhas = [[
        Paragraph("#", estilos["cabecalho"]),
        Paragraph("Título do Artigo", estilos["cabecalho"]),
        Paragraph(rotulo, estilos["cabecalho"]),
    ]]
    for posicao, r in enumerate(itens, start=1):
        linhas.append([
            Paragraph(str(posicao), estilos["celula"]),
            Paragraph(escape(str(r["titulo"])), estilos["celula"]),
            Paragraph(str(r[metrica]), estilos["celula"]),
        ])
    tabela = Table(linhas, colWidths=[28, 407, 90], repeatRows=1)
    tabela.setStyle(estilo_tabela(cor))
    return tabela


def adicionar_ranking(elementos, estilos, titulo_secao, rotulo, registros, metrica, quantidade, cor):
    elementos.append(Paragraph(titulo_secao, estilos["secao"]))

    if not metrica_disponivel(registros, metrica):
        elementos.append(
            Paragraph("Dado não disponível: o Movidesk não retornou esta métrica.", estilos["aviso"])
        )
        return

    itens = top(registros, metrica, quantidade)
    if not itens:
        elementos.append(Paragraph("Nenhum artigo com valor maior que zero.", estilos["celula"]))
        return

    elementos.append(montar_tabela(estilos, rotulo, itens, metrica, cor))


def adicionar_comentarios(elementos, estilos, registros):
    elementos.append(Paragraph("Artigos com comentários", estilos["secao"]))

    if not metrica_disponivel(registros, "comentarios"):
        elementos.append(
            Paragraph("Dado não disponível: o Movidesk não retornou comentários.", estilos["aviso"])
        )
        return

    itens = [r for r in registros if (r.get("comentarios") or 0) > 0]
    itens.sort(key=lambda r: r["comentarios"], reverse=True)

    if not itens:
        elementos.append(Paragraph("Nenhum artigo possui comentários.", estilos["celula"]))
        return

    elementos.append(montar_tabela(estilos, "Comentários", itens, "comentarios", "#7C3AED"))


def gerar_pdf(registros):
    doc = SimpleDocTemplate(
        NOME_ARQUIVO_PDF, pagesize=A4,
        rightMargin=30, leftMargin=30, topMargin=30, bottomMargin=30,
    )
    estilos = criar_estilos()
    elementos = []

    elementos.append(Paragraph("Relatório - Base de Conhecimento", estilos["titulo"]))
    data_atual = datetime.now().strftime("%d/%m/%Y")
    elementos.append(
        Paragraph(
            f"Gerado em: {data_atual} | {len(registros)} artigos analisados | "
            "Dados acumulados até hoje",
            estilos["subtitulo"],
        )
    )

    adicionar_ranking(elementos, estilos, "Top 10 - Artigos mais vistos",
                      "Visualizações", registros, "views", 10, "#2563EB")
    adicionar_ranking(elementos, estilos, "Top 10 - Artigos mais lidos",
                      "Leituras", registros, "lidos", 10, "#0891B2")
    adicionar_ranking(elementos, estilos, "Top 5 - Artigos com mais likes",
                      "Likes", registros, "likes", 5, "#16A34A")
    adicionar_ranking(elementos, estilos, "Top 5 - Artigos com mais dislikes",
                      "Dislikes", registros, "dislikes", 5, "#DC2626")
    adicionar_comentarios(elementos, estilos, registros)

    elementos.append(Spacer(1, 10))
    doc.build(elementos)
    print(f"PDF gerado: {NOME_ARQUIVO_PDF}")


# --------------------------------------------------------------- e-mail

def enviar_email():
    if not os.path.exists(NOME_ARQUIVO_PDF):
        print("Arquivo PDF não foi gerado.")
        sys.exit(1)

    msg = MIMEMultipart()
    msg["From"] = MAIL_USERNAME
    msg["To"] = MAIL_DESTINATARIO
    msg["Subject"] = "Relatório Automatizado - Artigos Movidesk"

    corpo = (
        "Olá!\n\nSegue em anexo o relatório com os rankings dos artigos da "
        "Base de Conhecimento do Movidesk.\n\n"
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

    sessao_movidesk = criar_sessao_logada()

    lista = listar_artigos(sessao_movidesk)
    if not lista:
        print("Nenhum artigo retornado pelo painel.")
        sys.exit(1)
    print(f"{len(lista)} artigos encontrados.")

    registros_finais = coletar_metricas(sessao_movidesk, lista)

    for nome_metrica in ["views", "lidos", "likes", "dislikes", "comentarios"]:
        status = "ok" if metrica_disponivel(registros_finais, nome_metrica) else "SEM DADOS"
        print(f"Métrica {nome_metrica}: {status}")

    gerar_pdf(registros_finais)
    enviar_email()
