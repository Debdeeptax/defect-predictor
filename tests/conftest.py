from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SAMPLE_PROJECT = ROOT / "data" / "samples" / "sample_project"


@pytest.fixture(scope="session")
def engine():
    from config import Config
    from app.services.prediction_engine import PredictionEngine
    return PredictionEngine.from_config(Config)


@pytest.fixture(scope="session")
def sample_extraction():
    from app.metrics.metric_extractor import MetricExtractor
    return MetricExtractor().extract(SAMPLE_PROJECT)


@pytest.fixture(scope="session")
def sample_payload(engine, sample_extraction):
    return engine.predict(sample_extraction)
