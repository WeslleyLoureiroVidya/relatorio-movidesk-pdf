import csv
import os
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

MOVIDESK_TOKEN = os.environ.get("MOVIDESK_TOKEN")
MAIL_USERNAME = os.environ.get("MAIL_USERNAME")
MAIL_PASSWORD = os.environ.get("MAIL_PASSWORD")
MAIL_DESTINATARIO = os.environ.get("MAIL_DESTINATARIO")

NOME_ARQUIVO_PDF = "relatorio_artigos_movidesk.pdf"
ARQUIVO_METRICAS = "metricas_artigos.csv"

URLS_CANDIDATAS = [
    "https://api.movidesk.com/public/v1/kb/article",
    "https://api.movidesk.com/public/v1/article",
]
TAMANHO_PAGINA = 100
MAX_PAGINAS = 100
ESPERA_ENTRE_PAGINAS = 7  # limite da API: 10 requisições por minuto

# Nome interno da métrica -> nomes aceitos como campo da API ou coluna do CSV
ALIASES = {
    "id": ["id"],
    "titulo": ["titulo", "título", "title"],
    "views": ["views", "visualizacoes", "visualizações", "viewcount", "viewscount"],
    "lidos": ["lidos", "leituras", "reads", "readcount"],
    "likes": ["likes", "curtidas", "likescount"],
    "dislikes": ["dislikes", "descurtidas", "dislikescount"],
    "comentarios": ["comentarios", "comentários", "comments", "commentscount"],
}
METRICAS = ["views", "lidos", "likes", "dislikes", "comentarios"]


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


# ---------------------------------------------------------------- API

def buscar_com_url(url):
    """Retorna a lista de artigos, ou None se a URL deu 404."""
    artigos = []
    total = None

    for pagina in range(MAX_PAGINAS):
        if pagina > 0:
            time.sleep(ESPERA_ENTRE_PAGINAS)

        params = {
            "token": MOVIDESK_TOKEN,
            "page": pagina,
            "pageSize": TAMANHO_PAGINA,
        }
        try:
            response = requests.get(url, params=params, timeout=60)
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


# ------------------------------------------------------------ métricas

def normalizar_titulo(texto):
    return " ".join(str(texto or "").lower().split())


def para_numero(valor):
    if valor is None:
        return None
    if isinstance(valor, bool):
        return None
    if isinstance(valor, (int, float)):
        return int(valor)
    texto = str(valor).strip().replace(".", "").replace(",", ".")
    if not texto:
        return None
    try:
        return int(float(texto))
    except ValueError:
        return None


def pegar(origem, nome_interno):
    """Busca o valor em um dict (item da API ou linha do CSV) usando os aliases."""
    chaves = {str(k).strip().lower(): v for k, v in origem.items()}
    for alias in ALIASES[nome_interno]:
        if alias in chaves and chaves[alias] not in (None, ""):
            return chaves[alias]
    return None


def contar_comentarios_api(item):
    comentarios = item.get("comments")
    if isinstance(comentarios, list):
        return len(comentarios)
    return para_numero(pegar(item, "comentarios"))


def registro_da_api(item):
    registro = {
        "id": str(item.get("id")) if item.get("id") is not None else None,
        "titulo": item.get("title") or "Sem título",
    }
    for metrica in METRICAS:
        if metrica == "comentarios":
            registro[metrica] = contar_comentarios_api(item)
        else:
            registro[metrica] = para_numero(pegar(item, metrica))
    return registro


def ler_csv(caminho):
    if not os.path.exists(caminho):
        print(f"Arquivo {caminho} não encontrado: usando só os dados da API.")
        return []

    with open(caminho, "r", encoding="utf-8-sig", newline="") as f:
        primeira = f.readline()
        f.seek(0)
        delimitador = ";" if primeira.count(";") >= primeira.count(",") else ","
        leitor = csv.DictReader(f, delimiter=delimitador)
        linhas = [dict(linha) for linha in leitor]

    print(f"{len(linhas)} linhas lidas de {caminho}.")
    return linhas


def montar_registros(artigos_api, linhas_csv):
    registros = [registro_da_api(a) for a in artigos_api]
    por_id = {r["id"]: r for r in registros if r["id"]}
    por_titulo = {normalizar_titulo(r["titulo"]): r for r in registros}

    for linha in linhas_csv:
        id_csv = pegar(linha, "id")
        titulo_csv = pegar(linha, "titulo")

        alvo = None
        if id_csv is not None:
            alvo = por_id.get(str(id_csv).strip())
        if alvo is None and titulo_csv is not None:
            alvo = por_titulo.get(normalizar_titulo(titulo_csv))

        if alvo is None:
            alvo = {"id": None, "titulo": titulo_csv or "Sem título"}
            for metrica in METRICAS:
                alvo[metrica] = None
            registros.append(alvo)
            if titulo_csv:
                por_titulo[normalizar_titulo(titulo_csv)] = alvo

        for metrica in METRICAS:
            valor = para_numero(pegar(linha, metrica))
            if valor is not None:
                alvo[metrica] = valor

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


def adicionar_ranking(elementos, estilos, titulo_secao, rotulo, registros, metrica, quantidade, cor):
    elementos.append(Paragraph(titulo_secao, estilos["secao"]))

    if not metrica_disponivel(registros, metrica):
        elementos.append(
            Paragraph(
                "Dado não disponível: a API do Movidesk não retorna esta métrica "
                f"e ela não consta em {ARQUIVO_METRICAS}.",
                estilos["aviso"],
            )
        )
        return

    itens = top(registros, metrica, quantidade)
    if not itens:
        elementos.append(Paragraph("Nenhum artigo com valor maior que zero.", estilos["celula"]))
        return

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
    elementos.append(tabela)


def adicionar_comentarios(elementos, estilos, registros):
    elementos.append(Paragraph("Artigos com comentários", estilos["secao"]))

    if not metrica_disponivel(registros, "comentarios"):
        elementos.append(
            Paragraph(
                "Dado não disponível: a API do Movidesk não retorna comentários "
                f"e eles não constam em {ARQUIVO_METRICAS}.",
                estilos["aviso"],
            )
        )
        return

    itens = [r for r in registros if (r.get("comentarios") or 0) > 0]
    itens.sort(key=lambda r: r["comentarios"], reverse=True)

    if not itens:
        elementos.append(Paragraph("Nenhum artigo possui comentários.", estilos["celula"]))
        return

    linhas = [[
        Paragraph("#", estilos["cabecalho"]),
        Paragraph("Título do Artigo", estilos["cabecalho"]),
        Paragraph("Comentários", estilos["cabecalho"]),
    ]]
    for posicao, r in enumerate(itens, start=1):
        linhas.append([
            Paragraph(str(posicao), estilos["celula"]),
            Paragraph(escape(str(r["titulo"])), estilos["celula"]),
            Paragraph(str(r["comentarios"]), estilos["celula"]),
        ])

    tabela = Table(linhas, colWidths=[28, 407, 90], repeatRows=1)
    tabela.setStyle(estilo_tabela("#7C3AED"))
    elementos.append(tabela)


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
            f"Gerado em: {data_atual} | {len(registros)} artigos analisados",
            estilos["subtitulo"],
        )
    )

    adicionar_ranking(elementos, estilos, "Top 10 - Artigos mais vistos (até hoje)",
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

    artigos_api = buscar_artigos_movidesk()
    linhas_csv = ler_csv(ARQUIVO_METRICAS)

    if not artigos_api and not linhas_csv:
        print("Nenhum dado retornado pela API nem pelo CSV.")
        sys.exit(1)

    registros_finais = montar_registros(artigos_api, linhas_csv)
    print(f"{len(registros_finais)} artigos no relatório.")

    for nome_metrica in METRICAS:
        status = "ok" if metrica_disponivel(registros_finais, nome_metrica) else "SEM DADOS"
        print(f"Métrica {nome_metrica}: {status}")

    gerar_pdf(registros_finais)
    enviar_email()
