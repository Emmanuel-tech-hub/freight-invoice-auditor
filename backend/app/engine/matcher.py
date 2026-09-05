from __future__ import annotations

from app.models import RateCard, Shipment


def index_shipments(shipments: list[Shipment]) -> dict[str, Shipment]:
    return {s.shipment_id: s for s in shipments}


def index_rate_cards(rate_cards: list[RateCard]) -> dict[tuple[str, str], RateCard]:
    return {(rc.lane, rc.service_level): rc for rc in rate_cards}


def find_rate_card(
    rate_cards_by_key: dict[tuple[str, str], RateCard], shipment: Shipment
) -> RateCard | None:
    return rate_cards_by_key.get((shipment.lane, shipment.service_level))
