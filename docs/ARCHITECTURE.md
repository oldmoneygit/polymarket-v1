# Arquitetura do Sistema

## Estrutura de Pastas

```
polymarket-bot/
├── .env                    # Credenciais e config (NUNCA commitar)
├── .env.example            # Template de config (commitar)
├── .gitignore
├── requirements.txt
├── requirements-dev.txt    # pytest, coverage, etc.
├── README.md
│
├── src/
│   ├── __init__.py
│   ├── main.py             # Entry point — inicia todos os serviços
│   ├── config.py           # Carrega e valida .env
│   │
│   ├── api/
│   │   ├── __init__.py
│   │   ├── polymarket.py   # Cliente da Polymarket Data API
│   │   ├── clob.py         # Cliente da CLOB API (execução de ordens)
│   │   └── telegram.py     # Cliente do Telegram Bot API
│   │
│   ├── monitor/
│   │   ├── __init__.py
│   │   ├── trader.py       # Monitor de atividade dos traders
│   │   └── position.py     # Monitor de posições abertas e resolução
│   │
│   ├── strategy/
│   │   ├── __init__.py
│   │   └── filter.py       # Filtros de qualidade de trade
│   │
│   ├── executor/
│   │   ├── __init__.py
│   │   └── trade.py        # Execução de ordens na CLOB
│   │
│   ├── notifier/
│   │   ├── __init__.py
│   │   └── telegram.py     # Formatação e envio de notificações
│   │
│   └── db/
│       ├── __init__.py
│       ├── models.py        # Modelos de dados (dataclasses)
│       └── repository.py   # SQLite — leitura e escrita
│
├── tests/
│   ├── __init__.py
│   ├── conftest.py         # Fixtures compartilhadas
│   ├── unit/
│   │   ├── test_config.py
│   │   ├── test_filter.py
│   │   ├── test_repository.py
│   │   └── test_models.py
│   ├── integration/
│   │   ├── test_polymarket_api.py
│   │   ├── test_clob_api.py
│   │   └── test_telegram_api.py
│   └── e2e/
│       ├── test_full_flow_dry_run.py
│       └── test_monitor_to_notify.py
│
├── docs/
│   ├── PRD.md
│   ├── ARCHITECTURE.md (este arquivo)
│   └── API_REFERENCE.md
│
├── specs/
│   ├── SPEC-01-config.md
│   ├── SPEC-02-polymarket-api.md
│   ├── SPEC-03-clob-api.md
│   ├── SPEC-04-trader-monitor.md
│   ├── SPEC-05-filter.md
│   ├── SPEC-06-executor.md
│   ├── SPEC-07-position-monitor.md
│   ├── SPEC-08-telegram-notifier.md
│   ├── SPEC-09-database.md
│   └── SPEC-10-e2e-tests.md
│
└── logs/                   # Gerado em runtime (gitignore)
```

---

## Fluxo de Dados

```
┌─────────────────────────────────────────────────────┐
│                      main.py                        │
│  Inicia loops assíncronos em paralelo:              │
│  - trader_monitor_loop (30s interval)               │
│  - position_monitor_loop (60s interval)             │
│  - telegram_command_loop (sempre ativo)             │
└──────────────┬──────────────────────────────────────┘
               │
               ▼
┌─────────────────────────┐
│   TraderMonitor         │
│   ─────────────────     │
│   Para cada trader:     │
│   1. GET /activity?     │
│      user=0x...         │
│   2. Filtra trades      │
│      novos (hash dedup) │
│   3. Passa pro Filter   │
└────────────┬────────────┘
             │ novo trade detectado
             ▼
┌─────────────────────────┐
│   TradeFilter           │
│   ─────────────────     │
│   Verifica:             │
│   - É mercado esportivo?│
│   - Volume >= mínimo?   │
│   - Prob dentro do      │
│     range?              │
│   - Trade recente?      │
│   - Mercado aberto?     │
└────────────┬────────────┘
             │ passou nos filtros
             ▼
┌─────────────────────────┐     ┌───────────────────┐
│   TradeExecutor         │────▶│  Telegram Notifier │
│   ─────────────────     │     │  "Trade executado" │
│   1. Calcula tamanho    │     └───────────────────┘
│   2. Verifica saldo     │
│   3. Coloca ordem CLOB  │
│   4. Salva no SQLite    │
└─────────────────────────┘

┌─────────────────────────┐     ┌───────────────────┐
│   PositionMonitor       │────▶│  Telegram Notifier │
│   ─────────────────     │     │  "Mercado resolveu"│
│   1. Lista posições     │     │  "Ganhou $X"       │
│      abertas no SQLite  │     └───────────────────┘
│   2. Checa se resolveu  │
│   3. Calcula P&L        │
│   4. Atualiza SQLite    │
└─────────────────────────┘
```

---

## Módulos e Responsabilidades

### `src/api/polymarket.py`
- `get_trader_activity(wallet, limit)` → lista de trades recentes
- `get_market_info(condition_id)` → detalhes do mercado (volume, status, probabilidade atual)
- `get_market_by_slug(slug)` → busca mercado por slug

### `src/api/clob.py`
- `create_order(market_id, side, price, size)` → coloca ordem na CLOB
- `cancel_order(order_id)` → cancela ordem
- `get_positions()` → posições abertas
- `get_balance()` → saldo USDC disponível

### `src/monitor/trader.py`
- `TraderMonitor` — classe que roda loop de polling
- Mantém set de `seen_hashes` em memória + SQLite

### `src/strategy/filter.py`
- `TradeFilter.evaluate(trade, market_info)` → `FilterResult(passed, reason)`
- Completamente testável de forma isolada (sem I/O)

### `src/executor/trade.py`
- `TradeExecutor.execute(trade, market_info)` → `ExecutionResult`
- Dry-run mode: loga mas não chama CLOB API

### `src/db/repository.py`
- `save_seen_hash(hash)` / `is_seen(hash)`
- `save_position(position)` / `get_open_positions()`
- `update_position_result(id, outcome, pnl)`
- `get_daily_pnl()` / `get_total_pnl()`

### `src/notifier/telegram.py`
- `send_trade_detected(trade, market_info)`
- `send_trade_executed(trade, execution)`
- `send_position_resolved(position, outcome, pnl)`
- `send_error(message)`
- `send_status(positions, pnl)`
