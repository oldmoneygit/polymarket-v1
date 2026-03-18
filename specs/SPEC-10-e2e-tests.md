# SPEC-10: Testes E2E

## Objetivo
Validar o fluxo completo do bot de ponta a ponta, do monitor até a notificação, sem executar trades reais (dry-run obrigatório nos testes E2E).

## Ambiente de teste E2E

- `DRY_RUN=true` sempre
- API da Polymarket: chamadas reais (smoke tests)
- CLOB API: mock (nunca tocar em dinheiro real nos testes)
- Telegram: mock (não enviar mensagens reais durante CI)
- SQLite: banco temporário em memória ou arquivo temp

## Teste E2E 1: Fluxo completo dry-run

**Cenário:** Bot detecta trade real de trader monitorado, passa pelos filtros, "executa" em dry-run e "notifica".

```
tests/e2e/test_full_flow_dry_run.py

Arrange:
- Config com DRY_RUN=true
- Traders reais: HorizonSplendidView + beachboy4
- Mock do CLOB (não executa ordem real)
- Mock do Telegram (captura mensagens)

Act:
- Roda TraderMonitor por 1 ciclo completo
- Busca atividade real da API da Polymarket

Assert:
- Pelo menos 1 trade foi detectado (API real)
- Para cada trade detectado: FilterResult foi calculado
- Se passou no filtro: ExecutionResult com dry_run=True
- Telegram mock recebeu ao menos 1 mensagem
- SQLite tem ao menos 1 registro (seen_hash ou position)
```

## Teste E2E 2: Persistência entre restarts

**Cenário:** Bot detecta trade, salva hash, reinicia, não reprocessa o mesmo trade.

```
tests/e2e/test_deduplication_across_restart.py

Act:
- Ciclo 1: detecta trade X, salva hash
- Reinicializa TraderMonitor com mesmo banco
- Ciclo 2: mesmo trade X na API (mock retorna mesmo dado)

Assert:
- Callback on_new_trade chamado apenas 1 vez no total
```

## Teste E2E 3: Stop diário

**Cenário:** P&L do dia atinge o limite, bot para de executar.

```
tests/e2e/test_daily_stop.py

Arrange:
- Repository com P&L do dia = -$19.90
- config.max_daily_loss_usd = 20.0
- Trade novo detectado e passa filtros

Act:
- TradeExecutor.execute() chamado

Assert:
- Retorna ExecutionResult(success=False, error="Stop diário atingido")
- Telegram mock recebe mensagem de pausa
- Nenhuma ordem colocada no CLOB
```

## Teste E2E 4: Comando /status via Telegram

```
tests/e2e/test_telegram_commands.py

Arrange:
- 2 posições abertas no SQLite
- Bot rodando com Telegram handler ativo (mock)

Act:
- Simula recebimento do comando /status

Assert:
- Resposta contém número de posições abertas
- Resposta contém P&L do dia
- Resposta contém modo (DRY RUN ou LIVE)
```

## Como rodar os testes

```bash
# Todos os testes (unit + integration + e2e)
pytest tests/ -v --tb=short

# Apenas unit tests (rápidos, sem API externa)
pytest tests/unit/ -v

# Com coverage report
pytest tests/unit/ --cov=src --cov-report=html --cov-report=term-missing

# E2E (precisa de .env configurado)
pytest tests/e2e/ -v -s

# Testes de integração (chamam API real)
pytest tests/integration/ -v -s --timeout=30
```

## Cobertura mínima exigida

| Módulo | Mínimo |
|--------|--------|
| `src/strategy/filter.py` | 100% |
| `src/db/repository.py` | 95% |
| `src/config.py` | 90% |
| `src/monitor/trader.py` | 85% |
| `src/executor/trade.py` | 85% |
| Overall | 80% |
