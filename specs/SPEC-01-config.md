# SPEC-01: Configuração e Variáveis de Ambiente

## Objetivo
Carregar, validar e expor todas as configurações do bot de forma centralizada e segura.

## Arquivo `.env.example`

```env
# === POLYMARKET API ===
POLY_API_KEY=your-api-key-here
POLY_API_SECRET=your-secret-here
POLY_API_PASSPHRASE=your-passphrase-here
POLY_WALLET_ADDRESS=0x...your-proxy-wallet...
POLY_PRIVATE_KEY=your-private-key-here  # Apenas necessário para execução real

# === TRADERS A MONITORAR ===
# Lista separada por vírgula de endereços proxy
TRADER_WALLETS=0x02227b8f5a9636e895607edd3185ed6ee5598ff7,0xc2e7800b5af46e6093872b177b7a5e7f0563be51

# === TELEGRAM ===
TELEGRAM_BOT_TOKEN=your-bot-token
TELEGRAM_CHAT_ID=8512554637

# === ESTRATÉGIA ===
CAPITAL_PER_TRADE_USD=5.0        # Valor por trade em USDC
MAX_TOTAL_EXPOSURE_USD=100.0     # Exposição máxima total
MAX_DAILY_LOSS_USD=20.0          # Stop diário
MIN_MARKET_VOLUME_USD=5000.0     # Volume mínimo do mercado
MIN_PROBABILITY=0.30              # Probabilidade mínima (30%)
MAX_PROBABILITY=0.75              # Probabilidade máxima (75%)
MAX_TRADE_AGE_MINUTES=60         # Ignorar trades mais antigos que X min
TAKE_PROFIT_PCT=0.20             # Saída antecipada em +20% (0 = desativado)
SLIPPAGE_TOLERANCE=0.02          # 2% de slippage tolerado

# === OPERAÇÃO ===
DRY_RUN=true                     # true = não executa trades reais
POLL_INTERVAL_SECONDS=30         # Intervalo de polling por trader
POSITION_CHECK_INTERVAL_SECONDS=60
LOG_LEVEL=INFO                   # DEBUG, INFO, WARNING, ERROR
```

## Módulo `src/config.py`

### Classe `Config`
- Carrega variáveis do `.env` via `python-dotenv`
- Valida todas as variáveis obrigatórias na inicialização
- Lança `ConfigError` com mensagem clara se algo estiver faltando ou inválido
- Expõe propriedades tipadas (não strings brutas)

### Validações obrigatórias
- `POLY_API_KEY`, `POLY_API_SECRET`, `POLY_API_PASSPHRASE` — não vazios
- `POLY_WALLET_ADDRESS` — formato de endereço Ethereum válido (0x + 40 hex)
- `TRADER_WALLETS` — pelo menos 1 endereço válido
- `TELEGRAM_BOT_TOKEN` — não vazio
- `TELEGRAM_CHAT_ID` — numérico
- `CAPITAL_PER_TRADE_USD` — float > 0 e <= MAX_TOTAL_EXPOSURE_USD
- `MIN_PROBABILITY` < `MAX_PROBABILITY`, ambos entre 0.0 e 1.0

### Comportamento no dry-run
- Se `DRY_RUN=true`, `POLY_PRIVATE_KEY` é opcional
- Log de aviso explícito: "🧪 DRY RUN MODE — nenhum trade real será executado"

## Testes (SPEC-01)

```
tests/unit/test_config.py

- test_config_loads_valid_env
- test_config_raises_on_missing_api_key
- test_config_raises_on_invalid_wallet_address
- test_config_raises_on_invalid_probability_range
- test_config_dry_run_does_not_require_private_key
- test_config_parses_trader_wallets_list
- test_config_defaults_applied_when_optional_missing
```
