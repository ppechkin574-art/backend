from pydantic import BaseModel


class ApiTimingRowDTO(BaseModel):
    """Aggregated client-observed latency for a single endpoint (RUM)."""

    endpoint: str
    count: int
    p50_ms: float
    p95_ms: float
    avg_ms: float
    error_rate: float  # 0..1, share of non-2xx/3xx samples


class ApiTimingSummaryDTO(BaseModel):
    window_hours: int
    total_samples: int
    rows: list[ApiTimingRowDTO]
