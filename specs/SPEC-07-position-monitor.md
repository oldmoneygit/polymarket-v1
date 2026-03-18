# SPEC-07: Monitor de Posições

## Objetivo
Monitorar posições abertas e detectar quando mercados resolvem, calculando P&L final.

## Classe `PositionMonitor`

### Loop
Roda a cada `config.position_check_interval_seconds` (default: 60s).

### Para cada posição aberta

```python
market = await polymarket.get_market_info(position.condition_id)

if market.is_resolved:
    # Determinar se ganhou ou perdeu
    # YES token: ganhou se outcome == "Yes"
    # NO token: ganhou se outcome == "No"
    won = determine_outcome(position, market)
    
    if won:
        pnl = position.shares - position.usdc_invested  # Recebe $1/share
    else:
        pnl = -position.usdc_invested
    
    repository.update_position_result(position.id, won, pnl)
    await notifier.send_position_resolved(position, won, pnl)
```

### Take profit antecipado (opcional)
Se `config.take_profit_pct > 0`:
```python
current_price = market.yes_price if position.is_yes else market.no_price
unrealized_pnl_pct = (current_price - position.entry_price) / position.entry_price

if unrealized_pnl_pct >= config.take_profit_pct:
    # Vender posição
    await executor.sell_position(position, current_price)
```

## Testes (SPEC-07)

```
tests/unit/test_position_monitor.py
- test_resolved_market_yes_win_calculates_pnl
- test_resolved_market_yes_loss_calculates_pnl
- test_unresolved_market_no_action
- test_take_profit_triggers_sell
- test_take_profit_disabled_no_sell
```
