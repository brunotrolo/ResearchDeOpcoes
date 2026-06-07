"""ResearchDeOpcoes — motor quantitativo de opções (B3).

Arquitetura "Cérebro Local, Painel na Nuvem":
    - Cérebro: este pacote Python, rodando no Dell via Task Scheduler.
    - Painel: Google Sheets (abas-espelho lidas via gspread).
    - Pager: alertas por e-mail (smtplib).

Dois módulos de negócio:
    - app.escudo  -> Módulo 1 (Defesa de posições ativas).
    - app.radar   -> Módulo 2 (Prospecção de prêmios).
"""

__version__ = "0.1.0"
