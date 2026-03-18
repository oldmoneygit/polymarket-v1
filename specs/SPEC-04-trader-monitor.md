# SPEC-04: Monitor de Traders

## Objetivo
Loop assíncrono que monitora múltiplos traders em paralelo, detecta novos trades e os encaminha para o pipeline de processamento.

## Classe `TraderMonitor`

### Inicialização
```python
TraderMonitor(
    config: Config,
    polymarket_client: PolymarketClient,
    repository: Repository,
    on_new_trade: Callable[[TraderTrade], Awaitable[None]]
)
```
`on_new_trade` é o callback chamado quando um trade novo é detectado.

### Loop principal
```python
async def start():
    while True:
        for wallet in config.trader_wallets:
            await self._check_trader(wallet)
            await asyncio.sleep(1)  # 1s entre traders para não spammar
        await asyncio.sleep(config.poll_interval_seconds)
```

### Deduplicação
- Mantém set em memória `seen_hashes: set[str]`
- Na inicialização, carrega hashes do SQLite (últimos 7 dias)
- Antes de processar: `if hash in seen_hashes: continue`
- Após processar: `seen_hashes.add(hash)` + `repository.save_seen_hash(hash)`

### Detecção de trade novo
Para cada trade retornado pela API:
1. Verificar se `transaction_hash` já foi visto
2. Verificar se `timestamp` é recente (< `config.max_trade_age_minutes`)
3. Se novo: chamar `on_new_trade(trade)`

### Tratamento de erros
- Se API falha para um trader: log warning, continua com próximo
- Se API falha 3x consecutivas para mesmo trader: notificar Telegram

## Testes (SPEC-04)

```
tests/unit/test_trader_monitor.py
- test_new_trade_triggers_callback
- test_already_seen_trade_skipped
- test_old_trade_skipped (timestamp > max_age)
- test_api_failure_continues_other_traders
- test_deduplication_persists_across_restarts  # mock SQLite
- test_multiple_traders_all_checked
```
