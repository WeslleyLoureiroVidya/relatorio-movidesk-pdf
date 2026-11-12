import calendar
import json
import os
import re
import sys
import time
import smtplib
from datetime import date, datetime, timedelta, timezone
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

PERIODO = os.environ.get("PERIODO", "acumulado")
DATA_INICIO = os.environ.get("DATA_INICIO", "")
DATA_FIM = os.environ.get("DATA_FIM", "")

BASE = "https://vidya-code.movidesk.com"
NOME_ARQUIVO_PDF = "relatorio_artigos_movidesk.pdf"

TAMANHO_PAGINA = 80
MAX_PAGINAS = 100
MAX_PAGINAS_FEEDBACK = 10
PAUSA = 0.4  # segundos entre consultas
MAX_FALHAS_SEGUIDAS = 8
MAX_DIAGNOSTICOS = 6
LIMITE_TEXTO_COMENTARIO = 300

NOMES_AVALIACAO = {1: "Positivo", 2: "Negativo"}

contador_diagnosticos = {"n": 0}


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


# -------------------------------------------------------------- período

def hoje_brasil():
    fuso = timezone(timedelta(hours=-3))
    return datetime.now(fuso).date()


def intervalo_mes(ano, mes):
    ultimo = calendar.monthrange(ano, mes)[1]
    return date(ano, mes, 1), date(ano, mes, ultimo)


def intervalo_ano(ano):
    return date(ano, 1, 1), date(ano, 12, 31)


def montar_periodo(modo, id_periodo, inicio, fim):
    return {
        "modo": modo,
        "id": id_periodo,
        "inicio": inicio.strftime("%Y-%m-%d"),
        "fim": fim.strftime("%Y-%m-%d"),
        "filtrado": True,
        "rotulo": f"Período: {inicio.strftime('%d/%m/%Y')} a {fim.strftime('%d/%m/%Y')}",
    }


def ler_data_iso(texto, nome_campo):
    try:
        return datetime.strptime(texto.strip(), "%Y-%m-%d").date()
    except ValueError:
        print(f"Data inválida em {nome_campo}: use o formato AAAA-MM-DD (ex.: 2026-10-01).")
        sys.exit(1)


def definir_periodo():
    modo = (PERIODO or "acumulado").strip().lower()
    hoje = hoje_brasil()

    if modo == "acumulado":
        return {
            "modo": modo, "id": "", "inicio": "", "fim": "",
            "filtrado": False, "rotulo": "Acumulado até hoje",
        }

    if modo == "este_mes":
        inicio, fim = intervalo_mes(hoje.year, hoje.month)
        return montar_periodo(modo, "7", inicio, fim)

    if modo == "mes_passado":
        if hoje.month == 1:
            inicio, fim = intervalo_mes(hoje.year - 1, 12)
        else:
            inicio, fim = intervalo_mes(hoje.year, hoje.month - 1)
        return montar_periodo(modo, "8", inicio, fim)

    if modo == "este_ano":
        inicio, fim = intervalo_ano(hoje.year)
        return montar_periodo(modo, "10", inicio, fim)

    if modo == "ano_passado":
        inicio, fim = intervalo_ano(hoje.year - 1)
        return montar_periodo(modo, "11", inicio, fim)

    if modo == "personalizado":
        if not DATA_INICIO.strip() or not DATA_FIM.strip():
            print("No período personalizado, informe data_inicio e data_fim (AAAA-MM-DD).")
            sys.exit(1)
        inicio = ler_data_iso(DATA_INICIO, "data_inicio")
        fim = ler_data_iso(DATA_FIM, "data_fim")
        if inicio > fim:
            print("A data de início não pode ser maior que a data de fim.")
            sys.exit(1)
        return montar_periodo(modo, "", inicio, fim)

    print(f"Período desconhecido: {modo}")
    print("Use: acumulado, este_mes, mes_passado, este_ano, ano_passado ou personalizado.")
    sys.exit(1)


def params_periodo(periodo):
    return {
        "period": periodo["id"],
        "periodStartDate": periodo["inicio"],
        "periodEndDate": periodo["fim"],
    }


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


def parece_html(texto):
    return (texto or "").lstrip()[:1] == "<"


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


def fazer_login(sessao):
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


def criar_sessao_logada():
    sessao = requests.Session()
    sessao.headers.update({"User-Agent": "Mozilla/5.0 (relatorio-automatico)"})

    fazer_login(sessao)

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

def registrar_falha(caminho, params, resposta):
    if contador_diagnosticos["n"] >= MAX_DIAGNOSTICOS:
        return
    contador_diagnosticos["n"] += 1
    trecho = (resposta.text or "")[:120].replace("\n", " ").replace("\r", " ")
    print(
        f"[diagnóstico] {caminho} artigo={params.get('articleId')} "
        f"HTTP {resposta.status_code} "
        f"tipo={resposta.headers.get('Content-Type')} "
        f"tamanho={len(resposta.text or '')} "
        f"início={trecho!r}"
    )


def obter_json(sessao, caminho, params):
    relogou = False
    tentativa = 0

    while tentativa < 3:
        tentativa += 1
        try:
            resposta = sessao.get(BASE + caminho, params=params, timeout=60)
        except Exception as e:
            print(f"Erro de conexão em {caminho}: {e}")
            time.sleep(2)
            continue

        if resposta.status_code == 200:
            dados = ler_json(resposta.text)
            if dados is not None:
                return dados

            if parece_html(resposta.text) and not relogou:
                print("Sessão parece ter expirado. Refazendo login...")
                relogou = True
                try:
                    fazer_login(sessao)
                except Exception as e:
                    print(f"Erro ao refazer login: {e}")
                tentativa -= 1
                continue

        registrar_falha(caminho, params, resposta)
        print(f"Falha em {caminho}: HTTP {resposta.status_code}")
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


def texto_limpo(valor):
    if isinstance(valor, str):
        return valor.strip()
    return ""


def contar_classificacao(painel, valor):
    classificacao = painel.get("classification") or {}
    for item in classificacao.get("items") or []:
        if item.get("value") == valor:
            contagem = para_int(item.get("count"))
            return contagem if contagem is not None else 0
    return 0


def resumir_feedback(entrada):
    data = texto_limpo(entrada.get("DateFormatted"))
    if not data:
        data = texto_limpo(entrada.get("ResponseDate"))[:10]

    codigo = entrada.get("ArticleEvaluationPositiveNegativeResponse")
    return {
        "data": data,
        "autor": texto_limpo(entrada.get("personName")),
        "avaliacao": NOMES_AVALIACAO.get(codigo, "-"),
        "motivo": texto_limpo(entrada.get("KbArticleEvaSettingsFieldsFeedbackName")),
        "comentario": texto_limpo(entrada.get("comments")),
    }


def buscar_feedbacks(sessao, id_artigo, periodo):
    """Retorna a lista de feedbacks do artigo, ou None se a consulta falhou."""
    entradas = []

    for pagina in range(1, MAX_PAGINAS_FEEDBACK + 1):
        params = {
            "articleId": id_artigo,
            "onlyComments": "false",
            "language": "",
            "page": pagina,
        }
        params.update(params_periodo(periodo))

        dados = obter_json(sessao, "/KbArticle/SearchSettingsFieldsFeedback", params)
        if not isinstance(dados, dict):
            if pagina == 1:
                return None
            break

        resultados = dados.get("results") or []
        for item in resultados:
            if isinstance(item, dict):
                entradas.append(item)

        if not dados.get("hasMore") or not resultados:
            break
        time.sleep(PAUSA)

    return entradas


def coletar_metricas(sessao, artigos, periodo):
    registros = []
    falhas_seguidas = 0

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
            "feedbacks": [],
        }

        if periodo["filtrado"]:
            registro["likes"] = None
            registro["dislikes"] = None

        params_painel = {"articleId": id_artigo, "language": ""}
        params_painel.update(params_periodo(periodo))
        painel = obter_json(sessao, "/KbArticle/Dashboard", params_painel)

        if isinstance(painel, dict):
            engajamento = painel.get("engagement") or {}
            registro["views"] = para_int(engajamento.get("NumberOfViews"))
            registro["lidos"] = para_int(engajamento.get("NumberOfReadings"))
            if periodo["filtrado"]:
                registro["likes"] = contar_classificacao(painel, 1)
                registro["dislikes"] = contar_classificacao(painel, 2)
            falhas_seguidas = 0
        else:
            falhas_seguidas += 1

        time.sleep(PAUSA)

        entradas = buscar_feedbacks(sessao, id_artigo, periodo)
        if entradas is not None:
            resumos = [resumir_feedback(e) for e in entradas]
            com_conteudo = [r for r in resumos if r["motivo"] or r["comentario"]]
            registro["feedbacks"] = com_conteudo
            registro["comentarios"] = len(com_conteudo)

        registros.append(registro)

        if falhas_seguidas >= MAX_FALHAS_SEGUIDAS:
            print(f"Muitas falhas seguidas (último artigo: {id_artigo}). Abortando.")
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
            textColor=colors.HexColor("#4B5563"), spaceAfter=4,
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
        "item_titulo": ParagraphStyle(
            "ItemTitulo", parent=styles["Normal"], fontSize=10,
            textColor=colors.HexColor("#1F2937"), spaceBefore=8, spaceAfter=2,
        ),
        "detalhe": ParagraphStyle(
            "DetalheFeedback", parent=styles["Normal"], fontSize=8.5,
            textColor=colors.HexColor("#374151"), leftIndent=12, spaceAfter=1,
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


def linha_feedback(fb):
    partes = []
    if fb["data"]:
        partes.append(fb["data"])
    if fb["autor"]:
        partes.append(fb["autor"])
    if fb["avaliacao"] != "-":
        partes.append(fb["avaliacao"])
    if fb["motivo"]:
        partes.append("Motivo: " + fb["motivo"])
    if fb["comentario"]:
        comentario = fb["comentario"]
        if len(comentario) > LIMITE_TEXTO_COMENTARIO:
            comentario = comentario[:LIMITE_TEXTO_COMENTARIO] + "..."
        partes.append("Comentário: " + comentario)
    return " | ".join(partes)


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

    elementos.append(
        Paragraph(
            "Inclui o motivo escolhido pelo leitor e o texto livre, quando houver.",
            estilos["celula"],
        )
    )

    for r in itens:
        titulo = escape(str(r["titulo"]))
        elementos.append(
            Paragraph(f"<b>{titulo}</b> - {r['comentarios']} comentário(s)", estilos["item_titulo"])
        )
        for fb in r["feedbacks"]:
            elementos.append(Paragraph(escape(linha_feedback(fb)), estilos["detalhe"]))


def gerar_pdf(registros, periodo):
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
            f"Gerado em: {data_atual} | {len(registros)} artigos analisados",
            estilos["subtitulo"],
        )
    )
    elementos.append(Paragraph(escape(periodo["rotulo"]), estilos["subtitulo"]))
    elementos.append(Spacer(1, 6))

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

def enviar_email(periodo):
    if not os.path.exists(NOME_ARQUIVO_PDF):
        print("Arquivo PDF não foi gerado.")
        sys.exit(1)
