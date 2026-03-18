# SPEC-08: Notificador Telegram

## Objetivo
Enviar notificações formatadas ao usuário e processar comandos de controle via Telegram.

## Biblioteca
`python-telegram-bot` (versão async)

## Mensagens enviadas

### Trade detectado (sem copiar — filtro rejeitou)
```
🔍 Trade detectado — NÃO copiado
Trader: HorizonSplendidView
Mercado: Will PSG win on 2026-03-11?
Lado: YES @ $0.52
Valor: $8,991
Motivo: Volume $3,200 abaixo do mínimo $5,000
```

### Trade executado
```
✅ Trade executado
Trader copiado: HorizonSplendidView
Mercado: Will PSG win on 2026-03-11?
Lado: YES @ $0.52
Investido: $5.00
Modo: 🧪 DRY RUN (sem dinheiro real)
```

### Posição resolvida — ganhou
```
🏆 Posição resolvida — GANHOU!
Mercado: Will PSG win on 2026-03-11?
Resultado: YES ✓
Investido: $5.00
Recebido: $9.62
Lucro: +$4.62 (+92%)
P&L do dia: +$12.30
```

### Posição resolvida — perdeu
```
❌ Posição resolvida — perdeu
Mercado: Will PSG win on 2026-03-11?
Resultado: YES ✗ (resolveu NO)
Investido: $5.00
Perda: -$5.00
P&L do dia: -$2.70
```

### Erro crítico
```
⚠️ ERRO CRÍTICO
Bot pausado por segurança.
Erro: Stop diário atingido (-$20.00)
Use /resume para retomar manualmente.
```

## Comandos do bot

### `/status`
```
📊 Status do Bot
Mode: 🟢 ATIVO (DRY RUN)
Posições abertas: 3
P&L hoje: +$8.20
P&L total: +$47.50
Exposição atual: $15.00 / $100.00

Posições abertas:
• PSG vs Chelsea YES @ $0.52 — atual $0.71 (+37%)
• Man City vs Arsenal YES @ $0.63 — atual $0.65 (+3%)
• Flamengo vs Palmeiras YES @ $0.45 — atual $0.48 (+7%)
```

### `/pause`
Pausa o bot (não executa novos trades).

### `/resume`
Retoma o bot.

### `/pnl`
Histórico completo de P&L.

## Testes (SPEC-08)

```
tests/unit/test_telegram_notifier.py
- test_format_trade_executed_message
- test_format_position_resolved_win
- test_format_position_resolved_loss
- test_format_status_message
- test_dry_run_flag_shown_in_messages
```
