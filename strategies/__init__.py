"""Strategy registry — maps names to scan functions (D-01)."""

from strategies.momentum import scan as momentum_scan
from strategies.mean_reversion import scan as mean_reversion_scan
from strategies.catalyst import scan as catalyst_scan

REGISTRY: dict[str, callable] = {
    "momentum":       momentum_scan,
    "mean_reversion": mean_reversion_scan,
    "catalyst":       catalyst_scan,
}
