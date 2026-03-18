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
├── dashboard.py            # Streamlit dashboard (live API + SQLite)
│
├── src/
│   ├── __init__.py
│   ├── main.py             # Entry point — inicia todos os servicos
│   ├── config.py           # Carrega e valida .env
│   ├── errors.py           # Hierarquia de erros tipados (ErrorCode + PolymarketError)
│   │
│   ├── api/
│   │   ├── __init__.py
│   │   ├── polymarket.py   # Cliente da Polymarket Data API + Gamma API
│   │   ├── clob.py         # Cliente da CLOB API (execucao de ordens + order book)
│   │   ├── rate_limiter.py # Rate limiting (token bucket) para APIs
│   │   └── websocket.py    # WebSocket para dados em tempo real
│   │
│   ├── monitor/
│   │   ├── __init__.py
│   │   ├── trader.py       # Monitor de atividade dos traders (com cooldown)
│   │   └── position.py     # Monitor de posicoes abertas e resolucao
│   │
│   ├── strategy/
│   │   ├── __init__.py
│   │   ├── filter.py       # Filtros de qualidade de trade
│   │   ├── scanner.py      # Scanner de mercados high-probability (Wannac)
│   │   ├── confluence.py   # Detector de confluencia multi-trader
│   │   ├── momentum.py     # Detector de momentum (movimentos rapidos)
│   │   └── kelly.py        # Kelly Criterion para position sizing
│   │
│   ├── executor/
│   │   ├── __init__.py
│   │   └── trade.py        # Execucao com order book checks + position averaging
│   │
│   ├── notifier/
│   │   ├── __init__.py
│   │   └── telegram.py     # Formatacao e envio de notificacoes
│   │
│   ├── db/
│   │   ├── __init__.py
│   │   ├── models.py       # Modelos de dados (dataclasses)
│   │   └── repository.py   # SQLite — leitura e escrita + position averaging
│   │
│   └── backtest/
│       ├── __init__.py
│       └── engine.py       # Backtesting engine event-driven
│
├── tests/
│   ├── __init__.py
│   ├── conftest.py         # Fixtures compartilhadas
│   ├── unit/               # 19 test files
│   │   ├── test_config.py
│   │   ├── test_models.py
│   │   ├── test_filter.py
│   │   ├── test_repository.py
│   │   ├── test_polymarket_api.py
│   │   ├── test_clob_api.py
│   │   ├── test_executor.py
│   │   ├── test_trader_monitor.py
│   │   ├── test_position_monitor.py
│   │   ├── test_telegram_notifier.py
│   │   ├── test_errors.py
│   │   ├── test_rate_limiter.py
│   │   ├── test_websocket.py
│   │   ├── test_scanner.py
│   │   ├── test_confluence.py
│   │   ├── test_momentum.py
│   │   ├── test_kelly.py
│   │   ├── test_main.py
│   │   └── test_backtest.py
│   ├── integration/
│   └── e2e/
│
├── docs/
│   ├── PRD.md
│   └── ARCHITECTURE.md (este arquivo)
│
├── specs/                  # 10 especificacoes detalhadas
│
├── data/                   # SQLite database (runtime)
└── logs/                   # Rotating log files (gitignore)
```

---

## Fluxo de Dados

```
┌─────────────────────────────────────────────────────────────┐
│                         main.py (Bot)                       │
│  Inicia loops assincronos em paralelo:                      │
│  - trader_monitor_loop (30s interval)                       │
│  - position_monitor_loop (60s interval)                     │
│                                                             │
│  Componentes de estrategia:                                 │
│  - ConfluenceDetector (multi-trader signal)                 │
│  - MomentumDetector (price movement signal)                 │
│  - HighProbScanner (Wannac strategy signal)                 │
└──────────────┬──────────────────────────────────────────────┘
               │
               ▼
┌─────────────────────────┐
│   TraderMonitor         │
│   ─────────────────     │
│   Para cada trader:     │
│   1. GET /activity      │
│   2. Hash dedup         │
│   3. Copy cooldown      │
│      (1h per market)    │
│   4. Callback           │
└────────────┬────────────┘
             │ novo trade detectado
             ▼
┌─────────────────────────┐
│   Pipeline do Bot       │
│   ─────────────────     │
│   1. Confluence check   │
│   2. Fetch market info  │
│   3. Momentum tracking  │
│   4. Scanner check      │
│   5. TradeFilter        │
│   6. TradeExecutor      │
│   7. Telegram notify    │
└────────────┬────────────┘
             │ passou nos filtros
             ▼
┌─────────────────────────┐     ┌───────────────────┐
│   TradeExecutor         │────▶│  Telegram Notifier │
│   ─────────────────     │     │  "Trade executado" │
│   1. Verifica saldo     │     └───────────────────┘
│   2. Daily stop check   │
│   3. Order book check   │
│      (liquidez/slippage)│
│   4. Position averaging │
│   5. Coloca ordem CLOB  │
│   6. Salva no SQLite    │
└─────────────────────────┘

┌─────────────────────────┐     ┌───────────────────┐
│   PositionMonitor       │────▶│  Telegram Notifier │
│   ─────────────────     │     │  "Mercado resolveu"│
│   1. Lista posicoes     │     │  "Ganhou $X"       │
│      abertas no SQLite  │     └───────────────────┘
│   2. Checa se resolveu  │
│   3. Calcula P&L        │
│   4. Atualiza SQLite    │
└─────────────────────────┘
```

---

## Modulos e Responsabilidades

### `src/errors.py`
- `ErrorCode` enum — classifica erros em retryable/non-retryable
- `PolymarketError` — exception base com factory methods

### `src/api/polymarket.py`
- `get_trader_activity(wallet, limit)` — lista de trades recentes
- `get_market_info(condition_id)` — detalhes do mercado
- Rate limiting integrado via `PolymarketRateLimiter`
- `SPORTS_SLUG_PREFIXES` para deteccao rapida de esportes

### `src/api/clob.py`
- `get_order_book(token_id)` — snapshot do order book com liquidez
- `estimate_slippage(book, amount, side)` — estimativa de slippage
- `get_price_history(token_id)` — historico OHLC
- `create_market_order()` — FOK order
- `create_fak_order()` — Fill-And-Kill (melhor para copy trading)
- `create_gtd_order()` — Good-Til-Date (expira antes do jogo)
- `create_limit_order()` — GTC order
- `get_balance()` / `get_open_positions()`

### `src/api/rate_limiter.py`
- `RateLimiter` — sliding window token bucket
- `PolymarketRateLimiter` — limites por endpoint (GET, POST, order)

### `src/api/websocket.py`
- `PolymarketWebSocket` — WebSocket para trades e precos em tempo real
- Auto-reconnect com exponential backoff

### `src/monitor/trader.py`
- `TraderMonitor` — polling loop com hash dedup + market cooldown
- 1h cooldown por mercado por trader para evitar posicoes duplicadas

### `src/monitor/position.py`
- `PositionMonitor` — resolucao de mercados e take-profit

### `src/strategy/filter.py`
- `TradeFilter.evaluate()` — filtros: sports, volume, prob range, idade, side, exposure

### `src/strategy/scanner.py`
- `HighProbScanner` — detecta mercados >85% perto de resolver (Wannac strategy)

### `src/strategy/confluence.py`
- `ConfluenceDetector` — detecta quando 2+ traders concordam
- Tier S (3x peso): JaJackson, Wannac, 0x4924
- Tier A (1x peso): elkmonkey, HorizonSplendidView, beachboy4, CemeterySun, Herdonia

### `src/strategy/momentum.py`
- `MomentumDetector` — detecta movimentos >10% em <30min
- Pode ser bootstrapped com historico de precos

### `src/strategy/kelly.py`
- `kelly_fraction()` — fracao de Kelly otima
- `fractional_kelly()` — 1/4 Kelly conservador
- `estimate_win_prob_from_trader()` — blend trader win rate + market price

### `src/executor/trade.py`
- `TradeExecutor.execute()` — pipeline completo de execucao
- Pre-checks: saldo, daily stop, exposure, order book, slippage
- Position averaging: entra em posicoes existentes

### `src/db/repository.py`
- `save_seen_hash()` / `is_seen()` / `load_seen_hashes()`
- `save_position()` / `get_open_positions()`
- `find_open_position()` / `update_position_average()` — position averaging
- `update_position_result()` — resolucao
- `get_daily_pnl()` / `get_total_pnl()` / `get_pnl_history()`

### `src/notifier/telegram.py`
- Formatacao e envio de notificacoes
- `send_trade_detected()`, `send_trade_executed()`, `send_position_resolved()`
- `send_error()`, `send_status()`

### `src/backtest/engine.py`
- `BacktestEngine` — backtesting event-driven
- `BacktestResult` — metricas: win_rate, profit_factor, sharpe_estimate, drawdown
- Aplica mesmos filtros do bot em modo simulado

### `dashboard.py`
- Streamlit dashboard com live API + SQLite
- Metricas, tabelas, graficos, sinais de estrategia
