"""Strategy configuration — maps wallets to strategies.

3 strategies running in parallel:
  1. copy_sports: Original copy traders (sports/esports)
  2. copy_geopolitical: High-conviction geopolitical/certainty traders
  3. ultra_fast: Ultra-short-term market signal providers (5min/15min crypto)
"""

from __future__ import annotations

# Strategy 1: Copy Trading Original (sports/esports)
COPY_SPORTS_WALLETS: dict[str, dict[str, str]] = {
    "0xf195721ad850377c96cd634457c70cd9e8308057": {"name": "JaJackson", "tier": "S", "focus": "NHL"},
    "0xa8e089ade142c95538e06196e09c85681112ad50": {"name": "Wannac", "tier": "S", "focus": "NBA high-prob"},
    "0x492442eab586f242b53bda933fd5de859c8a3782": {"name": "0x4924", "tier": "S", "focus": "NBA totals"},
    "0xead152b855effa6b5b5837f53b24c0756830c76a": {"name": "elkmonkey", "tier": "A", "focus": "Multi-sport"},
    "0x02227b8f5a9636e895607edd3185ed6ee5598ff7": {"name": "HorizonSplendidView", "tier": "A", "focus": "UCL"},
    "0xc2e7800b5af46e6093872b177b7a5e7f0563be51": {"name": "beachboy4", "tier": "A", "focus": "MLS"},
    "0x37c1874a60d348903594a96703e0507c518fc53a": {"name": "CemeterySun", "tier": "A", "focus": "NBA spreads"},
    "0xd106952ebf30a3125affd8a23b6c1f30c35fc79c": {"name": "Herdonia", "tier": "A", "focus": "NBA totals"},
    "0x9eb9133542965213982f3db49097f6cc4184cb5d": {"name": "Stealcopper2gamble", "tier": "S", "focus": "Valorant"},
}

# Strategy 2: Copy Trading Geopolitical/Certainties
COPY_GEO_WALLETS: dict[str, dict[str, str]] = {
    "0x6ffb4354cbe6e0f9989e3b55564ec5fb8646a834": {"name": "AgricultureSecretary", "tier": "S", "focus": "Politics/Certainties"},
    "0xdbade4c82fb72780a0db9a38f821d8671aba9c95": {"name": "SwissMiss", "tier": "S", "focus": "Geopolitics"},
    "0xe3726a1b9c6ba2f06585d1c9e01d00afaedaeb38": {"name": "cry.eth2", "tier": "A", "focus": "Multi-outcome MM"},
}

# Strategy 3: Ultra-Fast Signal Providers (for sentiment, not direct copy)
ULTRA_FAST_WALLETS: dict[str, dict[str, str]] = {
    "0x63ce342161250d705dc0b16df89036c8e5f9ba9a": {"name": "0x8dxd", "tier": "S", "focus": "BTC 5min/15min"},
    "0xd0d6053c3c37e727402d84c14069780d360993aa": {"name": "Uncommon-Oat", "tier": "S", "focus": "Multi-crypto 5min"},
    "0xd84c2b6d65dc596f49c7b6aadd6d74ca91e407b9": {"name": "BoneReader", "tier": "S", "focus": "BTC 5min specialist"},
    "0x2d8b401d2f0e6937afebf18e19e11ca568a5260a": {"name": "vidarx", "tier": "A", "focus": "BTC 5min directional"},
    "0x1f0ebc543b2d411f66947041625c0aa1ce61cf86": {"name": "Awful-Alfalfa", "tier": "A", "focus": "BTC/ETH 15min+4h"},
}

# Merge all wallets with strategy tag
ALL_WALLETS: dict[str, dict[str, str]] = {}
for w, info in COPY_SPORTS_WALLETS.items():
    ALL_WALLETS[w] = {**info, "strategy": "copy_sports"}
for w, info in COPY_GEO_WALLETS.items():
    ALL_WALLETS[w] = {**info, "strategy": "copy_geopolitical"}
for w, info in ULTRA_FAST_WALLETS.items():
    ALL_WALLETS[w] = {**info, "strategy": "ultra_fast"}


def get_strategy_for_wallet(wallet: str) -> str:
    """Return the strategy name for a wallet address."""
    info = ALL_WALLETS.get(wallet.lower())
    if info:
        return info["strategy"]
    return "copy_sports"  # Default


def get_wallet_name(wallet: str) -> str:
    """Return human-readable name for a wallet."""
    info = ALL_WALLETS.get(wallet.lower())
    if info:
        return info["name"]
    return wallet[:10] + "..."


def get_wallets_for_strategy(strategy: str) -> list[str]:
    """Return all wallet addresses for a given strategy."""
    return [w for w, info in ALL_WALLETS.items() if info["strategy"] == strategy]
