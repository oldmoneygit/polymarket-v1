# SPEC-09: Banco de Dados (SQLite)

## Objetivo
Persistência local leve usando SQLite. Sem dependência externa — funciona direto no Windows.

## Schema

### Tabela `seen_hashes`
```sql
CREATE TABLE seen_hashes (
    hash TEXT PRIMARY KEY,
    trader_wallet TEXT NOT NULL,
    created_at INTEGER NOT NULL  -- Unix timestamp
);
```

### Tabela `positions`
```sql
CREATE TABLE positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    condition_id TEXT NOT NULL,
    token_id TEXT NOT NULL,
    side TEXT NOT NULL,              -- "BUY"
    outcome TEXT NOT NULL,           -- "Yes" ou "No"
    entry_price REAL NOT NULL,
    shares REAL NOT NULL,
    usdc_invested REAL NOT NULL,
    trader_copied TEXT NOT NULL,
    market_title TEXT NOT NULL,
    opened_at INTEGER NOT NULL,
    closed_at INTEGER,
    status TEXT NOT NULL DEFAULT 'open',  -- "open", "won", "lost", "sold"
    pnl REAL,
    order_id TEXT,
    dry_run INTEGER NOT NULL DEFAULT 0   -- 0 ou 1
);
```

### Tabela `bot_state`
```sql
CREATE TABLE bot_state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at INTEGER NOT NULL
);
-- Usado para: "paused" (true/false), "daily_reset_date"
```

## Classe `Repository`

### Métodos

```python
def save_seen_hash(hash: str, trader_wallet: str) -> None
def is_seen(hash: str) -> bool
def load_seen_hashes(days_back: int = 7) -> set[str]

def save_position(position: Position) -> int  # retorna ID
def get_open_positions() -> list[Position]
def update_position_result(id: int, status: str, pnl: float) -> None
def get_total_open_exposure() -> float

def get_daily_pnl(date: date | None = None) -> float  # hoje se None
def get_total_pnl() -> float
def get_pnl_history(days: int = 30) -> list[tuple[date, float]]

def get_state(key: str, default: str = "") -> str
def set_state(key: str, value: str) -> None
```

### Inicialização
- Criar banco em `data/polymarket_bot.db`
- Executar migrations (CREATE TABLE IF NOT EXISTS) no startup
- Não usar ORM — SQL direto com `sqlite3` da stdlib

## Testes (SPEC-09)

```
tests/unit/test_repository.py
- test_save_and_check_seen_hash
- test_is_seen_returns_false_for_unknown
- test_save_and_retrieve_position
- test_update_position_result
- test_get_daily_pnl_empty
- test_get_daily_pnl_with_trades
- test_get_total_open_exposure
- test_state_get_set
- test_database_created_on_init
- test_load_seen_hashes_respects_days_back
```
