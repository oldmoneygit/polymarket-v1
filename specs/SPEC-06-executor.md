# SPEC-06: Executor de Trades

## Objetivo
Receber um trade aprovado pelo filtro e executar a ordem correspondente na CLOB, com todos os controles de segurança.

## Classe `TradeExecutor`

```python
@dataclass
class ExecutionResult:
    success: bool
    order_id: str | None
    price: float
    usdc_spent: float
    error: str | None
    dry_run: bool
```

```python
class TradeExecutor:
    async def execute(
        self,
        trade: TraderTrade,
        market: MarketInfo,
        config: Config
    ) -> ExecutionResult
```

## Fluxo de execução

### 1. Verificar saldo
```python
balance = await clob.get_balance()
if balance < config.capital_per_trade_usd:
    return ExecutionResult(success=False, error=f"Saldo insuficiente: ${balance:.2f}")
```

### 2. Verificar stop diário
```python
daily_loss = repository.get_daily_pnl()
if daily_loss <= -config.max_daily_loss_usd:
    return ExecutionResult(success=False, error="Stop diário atingido")
```

### 3. Determinar token_id
O `trade.asset` é o token ID do outcome copiado (YES ou NO shares).

### 4. Calcular tamanho
```python
amount = config.capital_per_trade_usd
# Não ultrapassar exposição máxima
current_exposure = repository.get_total_open_exposure()
amount = min(amount, config.max_total_exposure_usd - current_exposure)
if amount <= 0:
    return ExecutionResult(success=False, error="Sem capital disponível")
```

### 5. Executar ordem
```python
result = await clob.create_market_order(
    token_id=trade.asset,
    side="BUY",
    amount_usdc=amount
)
```

### 6. Salvar posição
```python
position = Position(
    condition_id=trade.condition_id,
    token_id=trade.asset,
    side=trade.side,
    entry_price=result.price,
    shares=result.filled_size,
    usdc_invested=result.filled_size * result.price,
    trader_copied=trade.proxy_wallet,
    market_title=trade.title,
    opened_at=datetime.now(),
    status="open"
)
repository.save_position(position)
```

## Testes (SPEC-06)

```
tests/unit/test_executor.py
- test_dry_run_returns_simulated_result
- test_insufficient_balance_returns_error
- test_daily_stop_prevents_execution
- test_max_exposure_limits_trade_size
- test_successful_execution_saves_position
- test_clob_error_returns_failure_gracefully
```
