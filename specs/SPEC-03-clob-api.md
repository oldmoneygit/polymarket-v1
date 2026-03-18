# SPEC-03: Cliente CLOB API (Execução de Ordens)

## Objetivo
Interface com a CLOB (Central Limit Order Book) da Polymarket para execução de ordens, consulta de saldo e posições.

## Autenticação
A CLOB API usa autenticação L1 (assinatura com private key) ou L2 (API Key/Secret/Passphrase). Vamos usar L2 (API Key já criada pelo usuário).

Endpoint base: `https://clob.polymarket.com`

## Credenciais necessárias
- `api_key` — do `.env`
- `api_secret` — do `.env`  
- `api_passphrase` — do `.env`
- `wallet_address` — endereço proxy do `.env`

## Biblioteca base
Usar a biblioteca oficial: `py-clob-client`
```
pip install py-clob-client
```

## Classe `CLOBClient`

### `async def get_balance() -> float`
Retorna saldo USDC disponível na carteira proxy.

### `async def get_open_positions() -> list[Position]`
Lista todas as posições abertas (shares que ainda não resolveram).

### `async def create_market_order(token_id, side, amount_usdc) -> OrderResult`
Cria ordem de mercado (executa ao melhor preço disponível).
- `token_id` — ID do asset (YES ou NO token)
- `side` — "BUY"
- `amount_usdc` — valor em USDC a gastar
- Usa FOK (Fill-or-Kill): executa tudo ou cancela

### `async def create_limit_order(token_id, side, price, size) -> OrderResult`
Cria ordem limit GTC.
- `price` — preço desejado (0.0 a 1.0)
- `size` — quantidade de shares

### Dry-run
Todos os métodos de escrita verificam `config.dry_run`:
```python
if self.config.dry_run:
    logger.info(f"[DRY RUN] Would create order: {token_id} {side} {amount_usdc}")
    return OrderResult(order_id="dry-run-fake-id", status="simulated")
```

## Modelo `OrderResult`

```python
@dataclass
class OrderResult:
    order_id: str
    status: str           # "live", "filled", "canceled", "simulated"
    price: float
    size: float
    filled_size: float
    timestamp: datetime
```

## Testes (SPEC-03)

```
tests/unit/test_clob_api.py
- test_dry_run_does_not_call_api
- test_create_order_returns_result
- test_insufficient_balance_raises_error

tests/integration/test_clob_api.py
- test_real_get_balance                  # Chama API real, verifica saldo
- test_real_create_tiny_dry_run_order   # Se dry_run=true, não executa
```
