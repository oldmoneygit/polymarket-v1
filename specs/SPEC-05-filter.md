# SPEC-05: Filtro de Qualidade de Trades

## Objetivo
Avaliar se um trade detectado deve ser copiado, baseado em critérios de qualidade configuráveis. Puro — sem I/O, completamente testável.

## Classe `TradeFilter`

```python
@dataclass
class FilterResult:
    passed: bool
    reason: str    # "OK" ou motivo da rejeição
```

```python
class TradeFilter:
    def evaluate(
        self, 
        trade: TraderTrade, 
        market: MarketInfo,
        config: Config
    ) -> FilterResult
```

## Critérios (em ordem de avaliação)

### 1. Mercado esportivo
```
if market.category != "sports":
    return FilterResult(False, "Mercado não é esportivo")
```

### 2. Mercado aberto
```
if market.is_resolved:
    return FilterResult(False, "Mercado já resolvido")
if market.end_date < now:
    return FilterResult(False, "Mercado expirado")
```

### 3. Volume mínimo
```
if market.volume < config.min_market_volume_usd:
    return FilterResult(False, f"Volume ${market.volume:.0f} abaixo do mínimo ${config.min_market_volume_usd:.0f}")
```

### 4. Probabilidade no range
```
# Preço = probabilidade implícita
price = trade.price
if price < config.min_probability or price > config.max_probability:
    return FilterResult(False, f"Preço {price:.0%} fora do range {config.min_probability:.0%}-{config.max_probability:.0%}")
```

### 5. Trade recente
```
age_minutes = (now - trade.timestamp) / 60
if age_minutes > config.max_trade_age_minutes:
    return FilterResult(False, f"Trade com {age_minutes:.0f}min, limite é {config.max_trade_age_minutes}min")
```

### 6. Apenas BUY (v1)
```
if trade.side != "BUY":
    return FilterResult(False, "Apenas trades de compra são copiados")
```

### 7. Exposição disponível
```
if current_exposure + config.capital_per_trade > config.max_total_exposure:
    return FilterResult(False, "Exposição máxima atingida")
```

## Testes (SPEC-05)

```
tests/unit/test_filter.py
- test_passes_all_criteria
- test_fails_non_sports_market
- test_fails_resolved_market
- test_fails_expired_market
- test_fails_low_volume
- test_fails_price_too_low
- test_fails_price_too_high
- test_fails_old_trade
- test_fails_sell_trade
- test_fails_max_exposure_reached
- test_filter_reason_message_is_descriptive
```
