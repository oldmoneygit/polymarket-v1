# PRD — Polymarket Sports Copy Trading Bot

**Versão:** 1.0  
**Data:** 2026-03-17  
**Status:** Em planejamento  

---

## 1. Visão Geral

Bot automatizado de copy trading focado em **mercados esportivos da Polymarket**, com foco inicial em futebol. O bot monitora traders top identificados no leaderboard, detecta entradas novas em mercados esportivos com critérios de qualidade, executa trades proporcionais na carteira do usuário e notifica via Telegram.

### Objetivo principal
Gerar lucro consistente de **$10/dia** com capital inicial de **$500**, através de copy trading disciplinado de traders comprovados em mercados de futebol.

### Não é objetivo (fora de escopo v1)
- Arbitragem de alta frequência
- Mercados de crypto (BTC 5min/15min)
- Machine learning / AI decision making
- Multi-exchange arbitrage

---

## 2. Usuário

**Jeferson** — trader iniciante em prediction markets, familiarizado com esportes (futebol), sem background técnico profundo em trading algorítmico. Quer visibilidade total sobre o que o bot faz, notificações em tempo real, e controle fácil para pausar/parar.

---

## 3. Problema

Traders top na Polymarket identificam oportunidades em mercados esportivos com conhecimento especializado. Essas oportunidades ficam abertas por horas ou dias — não por milissegundos. Um bot pode monitorar esses traders 24/7 e copiar suas posições proporcionalmente, sem necessidade de infraestrutura de alta frequência.

---

## 4. Solução

### Fluxo principal

```
[Monitor de Traders]
        ↓
  Detecta novo trade de trader top em mercado esportivo
        ↓
[Filtro de Qualidade]
  - Volume do mercado > $5.000
  - Probabilidade entre 30% e 75%
  - Trade recente (< 60 minutos)
  - Mercado ainda não resolvido
        ↓
[Executor de Trade]
  - Calcula tamanho proporcional (% do capital configurado)
  - Coloca ordem GTC limit
  - Registra no banco local
        ↓
[Notificador Telegram]
  - Envia alerta de trade executado
  - Inclui: mercado, lado, preço, tamanho, trader copiado
        ↓
[Monitor de Posições]
  - Acompanha posições abertas
  - Notifica na resolução (ganho ou perda)
  - Opcional: saída antecipada em +20% de ganho
```

---

## 5. Traders-alvo (v1)

Identificados via análise do leaderboard em 2026-03-17:

| Nome | Endereço | Foco |
|------|----------|------|
| HorizonSplendidView | `0x02227b8f5a9636e895607edd3185ed6ee5598ff7` | Futebol europeu (UCL, etc.) |
| beachboy4 | `0xc2e7800b5af46e6093872b177b7a5e7f0563be51` | MLS / futebol americano |
| reachingthesky | resolver via username → endereço | A confirmar |

---

## 6. Requisitos Funcionais

### RF-01: Monitoramento de traders
- Polling da Data API da Polymarket a cada **30 segundos** por trader
- Detecção de trades novos via deduplicação por `transactionHash`
- Suporte a múltiplos traders simultaneamente
- Persistência de trades já vistos (não reprocessar após restart)

### RF-02: Filtro de qualidade
- Verificar se o mercado é esportivo (por slug/categoria: soccer, nba, nhl, nfl, mls, ucl, epl, etc.)
- Verificar volume mínimo configurável (default: $5.000)
- Verificar probabilidade dentro do range configurável (default: 10%-90% — range amplo para capturar Wannac high-prob e sleepy-panda value bets)
- Verificar tempo desde o trade do trader (default: < 60min)
- Verificar se mercado ainda está aberto

### RF-03: Execução de trade
- Calcular tamanho: `min(capital_por_trade, max_por_mercado)`
- Colocar ordem GTC limit ao preço atual de mercado + slippage tolerância
- Retry em caso de falha de rede (3x com backoff)
- Nunca exceder exposição total configurada

### RF-04: Gestão de posições
- Registrar todas as posições abertas localmente (SQLite)
- Monitorar resolução de mercados
- Calcular P&L por trade e acumulado
- Opcional: saída antecipada quando lucro atingir `take_profit_%`

### RF-05: Notificações Telegram
- Notificar ao detectar trade de trader monitorado (mesmo sem copiar)
- Notificar ao executar trade
- Notificar ao resolver posição (ganho/perda)
- Notificar erros críticos (falha de API, saldo insuficiente)
- Comando `/status` para ver posições abertas e P&L
- Comando `/pause` e `/resume` para controlar o bot

### RF-06: Controles de risco
- Stop diário: se perda do dia > `max_daily_loss`, pausar automaticamente
- Capital máximo por trade configurável
- Capital máximo total exposto configurável
- Dry-run mode: executa tudo menos o trade real

---

## 7. Requisitos Não-Funcionais

- **Linguagem:** Python 3.11+
- **Execução:** Windows 10 (PC local do usuário)
- **Dependências externas:** Polymarket Data API, Polymarket CLOB API, Telegram Bot API
- **Banco de dados:** SQLite (sem dependência externa)
- **Configuração:** arquivo `.env` (nunca commitar)
- **Logs:** arquivo rotativo diário em `logs/`
- **Testes:** pytest + cobertura mínima de 80% nas funções críticas
- **Startup:** deve iniciar em < 10 segundos
- **Polling interval:** configurável, default 30s por trader

---

## 8. Métricas de Sucesso

- Bot roda 24/7 sem crash manual por > 7 dias
- Detecta 100% dos trades dos traders monitorados (zero miss)
- Executa trades em < 5 minutos após detecção
- Notificações chegam em < 30 segundos após evento
- P&L positivo após 30 dias de operação

---

## 9. Riscos

| Risco | Probabilidade | Impacto | Mitigação |
|-------|--------------|---------|-----------|
| Trader copiado muda de estratégia | Média | Alto | Monitorar win rate, pausar se cair abaixo de 50% |
| API da Polymarket fica indisponível | Baixa | Médio | Retry + notificação de downtime |
| Mercado resolve de surpresa | Média | Médio | Stop loss configurável |
| Rate limit da API | Baixa | Baixo | Respeitar limites, backoff exponencial |
| PC desligado / sem internet | Alta | Alto | Documentar necessidade de uptime; considerar VPS em v2 |

---

## 10. Roadmap

### v1.0 (atual)
- Monitor de traders
- Filtro de qualidade
- Executor com dry-run
- Notificações básicas Telegram
- SQLite para persistência
- Dashboard simples via Telegram

### v2.0 (futuro)
- Deploy em servidor Linux (openclaw/srv1278850)
- Mais traders monitorados
- Análise de win rate histórico dos traders
- Filtros avançados por liga/competição
- Web dashboard (opcional)
loss configurável |
| Rate limit da API | Baixa | Baixo | Respeitar limites, backoff exponencial |
| PC desligado / sem internet | Alta | Alto | Documentar necessidade de uptime; considerar VPS em v2 |

---

## 10. Roadmap

### v1.0 (atual)
- Monitor de traders
- Filtro de qualidade
- Executor com dry-run
- Notificações básicas Telegram
- SQLite para persistência
- Dashboard simples via Telegram

### v2.0 (futuro)
- Deploy em servidor Linux (openclaw/srv1278850)
- Mais traders monitorados
- Análise de win rate histórico dos traders
- Filtros avançados por liga/competição
- Web dashboard (opcional)
