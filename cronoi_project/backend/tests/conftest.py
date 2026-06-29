import os
import sys

# tests/ dizinini ve backend kökünü import yoluna ekle (qa_support + app.*)
sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


def pytest_configure(config):
    config.addinivalue_line("markers", "slow: uzun süren derin regresyon kapısı (varsayılan hariç)")
