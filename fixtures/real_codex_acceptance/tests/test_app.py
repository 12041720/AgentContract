import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.app import calculate_total


def test_calculate_total() -> None:
    assert calculate_total([10.0, 20.0], 0.1) == 33.0
    assert calculate_total([100.0], 0.05) == 105.0
