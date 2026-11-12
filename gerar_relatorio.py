import os
from datetime import datetime
import smtplib
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
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


def buscar_artigos_movidesk():
  url = f"https://vidya-code.movidesk.com/api/v1/reports/articles?token={MOVIDESK_TOKEN}"
  try:
    response = requests.get(url)
    if response.status_code == 200:
      return response.json()
    else:
      url_fallback = (
          f"https://vidya-code.movidesk.com/api/v1/kb?token={MOVIDESK_TOKEN}"
      )
      response_fb = requests.get(url_fallback)
      if response_fb.status_code == 200:
        return response_fb.json()

      print(f"Erro na API do Movidesk: {response.status_code} - {response.text}")
      return []
  except Exception as e:
    print(f"Erro de conexão: {e}")
    return []


def gerar_pdf(artigos):
  if isinstance(artigos, dict):
    artigos = (
        artigos.get("articles")
        or artigos.get("value")
        or list(artigos.values())[0]
        if artigos
        else []
    )

  if not isinstance(artigos, list):
    artigos = []

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
      Paragraph(
          f"Gerado em: {data_atual} | Período de análise: Últimos 30 dias",
          subtitulo_estilo,
      )
  )

  total_artigos = len(artigos)
  total_views = sum(a.get("views", 0) for a in artigos)
  total_likes = sum(a.get("likes", 0) for a in artigos)
  total_comments = sum(
      len(a.get("comments", [])) or a.get("commentsCount", 0) for a in artigos
  )

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
          Paragraph(str(total_likes), celula_estilo),
          Paragraph(str(total_comments), celula_estilo),
      ],
  ]

  tabela_resumo = Table(resumo_data, colWidths=[130, 130, 130, 130])
  tabela_resumo.setStyle(
      TableStyle([
          ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2563EB")),
          ("ALIGN", (0, 0), (-1, -1), "CENTER"),
          ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
          ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
          ("TOPPADDING", (0, 0), (-1, -1), 8),
          ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#D1D5DB")),
      ])
  )

  elementos.append(tabela_resumo)
  elementos.append(Spacer(1, 15))

  artigos_ordenados = sorted(
      artigos, key=lambda x: x.get("views", 0), reverse=True
  )

  tabela_dados = [[
      Paragraph("#", cabecalho_estilo),
      Paragraph("Título do Artigo", cabecalho_estilo),
      Paragraph("Views", cabecalho_estilo),
      Paragraph("Likes", cabecalho_estilo),
