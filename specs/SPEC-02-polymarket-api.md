# SPEC-02: Cliente Polymarket Data API

## Objetivo
Wrapper tipado e resiliente para a Polymarket Data API. Responsável por buscar atividade de traders e informações de mercados.

## Endpoints utilizados

### GET `/activity`
```
https://data-api.polymarket.com/activity
  ?user={wallet_address}
  &type=TRADE
  &limit=50
```
Retorna lista de trades recentes de um trader.

### GET `/markets`
```
https://gamma-api.polymarket.com/markets
  ?condition_ids={condition_id}
```
Retorna detalhes de um mercado (volume, status, probabilidades).

## Modelos de dados

```python
@dataclass
class TraderTrade:
    proxy_wallet: str
    timestamp: int           # Unix timestamp
    condition_id: str
    transaction_hash: str
    price: float             # 0.0 a 1.0
    size: float              # Quantidade de shares
    usdc_size: float         # Valor em USDC
    side: str                # "BUY" ou "SELL"
    outcome: str             # "Yes" ou "No"
    title: str               # "Will PSG win on..."
    slug: str                # "ucl-psg1-cfc1-2026-03-11-psg1"
    event_slug: str          # "ucl-psg1-cfc1-2026-03-11"
    trader_name: str

@dataclass  
class MarketInfo:
    condition_id: str
    question: str
    category: str            # "sports", "crypto", "politics", etc.
    volume: float            # Volume total em USDC
    liquidity: float
    end_date: datetime
    is_resolved: bool
    yes_price: float         # Preço atual do YES
    no_price: float          # Preço atual do NO
    slug: str
```

## Classe `PolymarketClient`

### Métodos

```python
async def get_trader_activity(
    wallet: str, 
    limit: int = 50
) -> list[TraderTrade]
```
- Faz GET na Data API
- Converte resposta JSON para lista de `TraderTrade`
- Lança `APIError` em caso de erro HTTP

```python
async def get_market_info(
    condition_id: str
) -> MarketInfo | None
```
- Faz GET na Gamma API
- Retorna None se mercado não encontrado
- Determina `category` pelo slug (se contém "soccer", "mls", "ucl", "premier", etc. → "sports")

### Resiliência
- Timeout de 10 segundos por request
- Retry automático em erros 5xx e timeout (3x, backoff 1s/2s/4s)
- Rate limit: máximo 60 req/min (1 req/segundo de margem)
- Session persistente com `aiohttp.ClientSession`

## Detecção de mercados esportivos

Slugs que indicam mercado esportivo:
```python
SPORTS_KEYWORDS = [
    "soccer", "football", "mls", "ucl", "epl", "laliga",
    "bundesliga", "seriea", "ligue1", "premier", "champions",
    "copa", "world-cup", "nba", "nfl", "mlb", "nhl",
    "win-on", "beat", "match", "game"
]
```
Se qualquer keyword estiver no slug ou event_slug → categoria = "sports"

## Testes (SPEC-02)

```
tests/unit/test_polymarket_api.py
- test_parse_trader_activity_response          # mock HTTP, valida parsing
- test_parse_market_info_response
- test_detect_sports_market_by_slug
- test_detect_non_sports_market
- test_api_error_raises_exception
- test_retry_on_500_error

tests/integration/test_polymarket_api.py
- test_real_get_trader_activity               # Chama API real, smoke test
- test_real_get_market_info
```
