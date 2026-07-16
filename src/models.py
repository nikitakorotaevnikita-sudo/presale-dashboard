from dataclasses import dataclass, fields
from typing import Optional


@dataclass
class StatusEvent:
    request_id: str
    request: str
    org: str
    product: str
    scale: str
    service: str
    initiator: str
    team: str
    business_unit: str
    status: str
    prev_status: str
    date_start: str
    date_end: str
    month: Optional[int]
    duration_rd: float
    work_duration_rd: float  # «Длительность проработки запроса (раб. дн.)»
    hours: Optional[float]
    note: str
    link: str = ""  # URL из гиперссылки ячейки «Запрос на пресейл» (Aura)


EVENT_FIELDS = [f.name for f in fields(StatusEvent)]

# Разрез (имя на русском в UI) -> атрибут StatusEvent
DIMENSION_ATTR = {
    "услуга": "service",
    "продукт": "product",
    "масштаб": "scale",
    "инициатор": "initiator",
    "команда": "team",
}
