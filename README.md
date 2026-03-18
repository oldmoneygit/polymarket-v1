# Polymarket Sports Copy Trading Bot

Bot de copy trading para mercados esportivos na Polymarket. Monitora traders top, filtra oportunidades e executa trades automaticamente.

## ⚠️ Segurança

**NUNCA** commite o arquivo `.env`. Nunca poste suas chaves em nenhum lugar.

## Setup

```bash
# 1. Instalar dependências
pip install -r requirements.txt

# 2. Configurar
cp .env.example .env
# Editar .env com suas credenciais

# 3. Rodar em dry-run (sem dinheiro real)
python src/main.py

# 4. Rodar testes
pytest tests/unit/ -v
```

## Documentação

- [PRD — Visão do produto](docs/PRD.md)
- [Arquitetura](docs/ARCHITECTURE.md)
- [SPEC-01: Config](specs/SPEC-01-config.md)
- [SPEC-02: Polymarket API](specs/SPEC-02-polymarket-api.md)
- [SPEC-03: CLOB API](specs/SPEC-03-clob-api.md)
- [SPEC-04: Monitor de Traders](specs/SPEC-04-trader-monitor.md)
- [SPEC-05: Filtros](specs/SPEC-05-filter.md)
- [SPEC-06: Executor](specs/SPEC-06-executor.md)
- [SPEC-07: Monitor de Posições](specs/SPEC-07-position-monitor.md)
- [SPEC-08: Telegram](specs/SPEC-08-telegram-notifier.md)
- [SPEC-09: Banco de Dados](specs/SPEC-09-database.md)
- [SPEC-10: Testes E2E](specs/SPEC-10-e2e-tests.md)
