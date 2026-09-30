# strategy package
from .base_strategy import BaseStrategy
from .ema_crossover import EMACrossoverStrategy
from .supertrend import SuperTrendStrategy
from .multi_confirmation import MultiConfirmationStrategy

__all__ = [
    "BaseStrategy",
    "EMACrossoverStrategy",
    "SuperTrendStrategy",
    "MultiConfirmationStrategy",
]
