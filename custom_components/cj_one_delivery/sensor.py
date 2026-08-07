"""CJ O-NE 배송조회 센서."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import DeliveryStatus
from .const import (
    CONF_COMPLETED_RETENTION_DAYS,
    DEFAULT_COMPLETED_RETENTION_DAYS,
    DOMAIN,
)
from .coordinator import CJOneDeliveryCoordinator, DeliveryEvent

PARCEL_FIELDS: tuple[tuple[str, str], ...] = (
    ("status", "상태"),
    ("product_name", "상품명"),
    ("tracking_number_display", "운송장 번호"),
    ("sender", "보내는 분"),
    ("receiver", "받는 분"),
    ("last_location", "최근 위치"),
    ("last_event_time", "최근 일시"),
    ("courier", "배송기사"),
    ("detail", "배송 상세"),
)
PARCEL_FIELD_NAMES = dict(PARCEL_FIELDS)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry[CJOneDeliveryCoordinator],
    async_add_entities: AddEntitiesCallback,
) -> None:
    """택배 상태 센서를 설정합니다."""
    coordinator = entry.runtime_data
    known_tracking_numbers: set[str] = set()

    def _sync_entities() -> None:
        """코디네이터 데이터에 맞춰 운송장별 엔티티를 추가/정리합니다."""
        current = set(coordinator.data or {})
        new_numbers = current - known_tracking_numbers
        removed_numbers = known_tracking_numbers - current
        if new_numbers:
            known_tracking_numbers.update(new_numbers)
            async_add_entities(
                [
                    CJOneDeliveryParcelFieldSensor(coordinator, tracking_number, field)
                    for tracking_number in new_numbers
                    for field, _name in PARCEL_FIELDS
                ]
            )
        known_tracking_numbers.difference_update(removed_numbers)
        _cleanup_stale_entities(hass, entry, current)

    async_add_entities(
        [
            CJOneDeliverySummarySensor(coordinator),
            CJOneDeliveryDeliveryListSensor(coordinator, "active"),
            CJOneDeliveryDeliveryListSensor(coordinator, "completed"),
            CJOneDeliveryLastEventSensor(coordinator),
        ]
    )
    _sync_entities()
    entry.async_on_unload(coordinator.async_add_listener(_sync_entities))


class CJOneDeliverySummarySensor(
    CoordinatorEntity[CJOneDeliveryCoordinator],
    SensorEntity,
):
    """배송 목록 전체 요약 센서."""

    _attr_has_entity_name = True
    _attr_name = "배송 요약"

    def __init__(self, coordinator: CJOneDeliveryCoordinator) -> None:
        """요약 센서를 초기화합니다."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_summary"
        self._attr_device_info = _device_info(coordinator)

    @property
    def native_value(self) -> str:
        """배송 목록 요약 문구를 반환합니다."""
        active_count = len(_active_statuses(self.coordinator.data or {}))
        return f"진행중 {active_count}건"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """요약과 인증 상태 속성을 반환합니다."""
        data = self.coordinator.data or {}
        last_event = self.coordinator.last_event
        return {
            "active_count": len(_active_statuses(data)),
            "completed_count": len(_completed_statuses(data)),
            "completed_retention_days": _completed_retention_days(
                self.coordinator.config_entry
            ),
            "last_changed_summary": last_event.announcement if last_event else "",
            "last_error": self.coordinator.last_error or "",
        }


class CJOneDeliveryDeliveryListSensor(
    CoordinatorEntity[CJOneDeliveryCoordinator],
    SensorEntity,
):
    """진행중 또는 완료 배송 목록 센서."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: CJOneDeliveryCoordinator,
        list_type: str,
    ) -> None:
        """배송 목록 센서를 초기화합니다."""
        super().__init__(coordinator)
        self._attr_device_info = _device_info(coordinator)
        self._list_type = list_type
        if list_type == "active":
            self._attr_name = "진행중 배송"
            self._attr_unique_id = f"{coordinator.config_entry.entry_id}_active"
        else:
            self._attr_name = "배송완료"
            self._attr_unique_id = f"{coordinator.config_entry.entry_id}_completed"

    @property
    def native_value(self) -> int:
        """목록에 포함된 배송건 수를 반환합니다."""
        return len(self._statuses)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """배송 목록 요약 속성을 반환합니다."""
        attrs: dict[str, Any] = {
            "deliveries": [_delivery_summary_payload(status) for status in self._statuses],
            "last_error": self.coordinator.last_error or "",
        }
        if self._list_type == "completed":
            attrs["completed_retention_days"] = _completed_retention_days(
                self.coordinator.config_entry
            )
        return attrs

    @property
    def _statuses(self) -> list[DeliveryStatus]:
        """이 센서가 표시할 배송 목록을 반환합니다."""
        data = self.coordinator.data or {}
        if self._list_type == "active":
            return _active_statuses(data)
        return _completed_statuses(data)


class CJOneDeliveryParcelFieldSensor(
    CoordinatorEntity[CJOneDeliveryCoordinator],
    SensorEntity,
):
    """운송장 번호별로 묶이는 배송 세부 정보 센서."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: CJOneDeliveryCoordinator,
        tracking_number: str,
        field: str,
    ) -> None:
        """운송장 세부 센서를 초기화합니다."""
        super().__init__(coordinator)
        self._tracking_number = tracking_number
        self._field = field
        self._attr_device_info = _parcel_device_info(coordinator, tracking_number)
        self._attr_unique_id = (
            f"{coordinator.config_entry.entry_id}_{tracking_number}_{field}"
        )
        self._attr_name = PARCEL_FIELD_NAMES[field]

    @property
    def available(self) -> bool:
        """운송장 번호가 더 이상 목록에 없으면 사용 불가로 표시합니다."""
        return super().available and self._status is not None

    @property
    def native_value(self) -> str:
        """이 운송장의 세부 정보 값을 반환합니다."""
        status = self._status
        if status is None:
            return "없음"

        payload = _delivery_payload(status)
        if self._field == "detail":
            return "상세 있음" if payload["tracking_history"] else "상세 없음"
        return str(payload.get(self._field) or "없음")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """운송장 공통 속성과 상세 정보를 반환합니다."""
        status = self._status
        attrs: dict[str, Any] = {
            "tracking_number": self._tracking_number,
            "field": self._field,
            "is_empty": status is None,
            "last_error": self.coordinator.last_error or "",
        }
        if status is None:
            return attrs

        payload = _delivery_payload(status)
        attrs["display_group"] = payload["display_group"]
        if self._field == "detail":
            attrs.update(
                {
                    "tracking_number_display": payload["tracking_number_display"],
                    "status": payload["status"],
                    "product_name": payload["product_name"],
                    "last_location": payload["last_location"],
                    "last_event_time": payload["last_event_time"],
                }
            )
            attrs["basic_info"] = payload["basic_info"]
            attrs["tracking_history"] = payload["tracking_history"]
        return attrs

    @property
    def _status(self) -> DeliveryStatus | None:
        """이 운송장 번호에 해당하는 배송 상태를 반환합니다."""
        data = self.coordinator.data or {}
        return data.get(self._tracking_number)


class CJOneDeliveryLastEventSensor(
    CoordinatorEntity[CJOneDeliveryCoordinator],
    SensorEntity,
):
    """자동화와 방송에 사용할 최근 배송 변경 이벤트 센서."""

    _attr_has_entity_name = True
    _attr_name = "최근 배송 이벤트"

    def __init__(self, coordinator: CJOneDeliveryCoordinator) -> None:
        """최근 이벤트 센서를 초기화합니다."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_last_event"
        self._attr_device_info = _device_info(coordinator)

    @property
    def native_value(self) -> str:
        """최근 변경 이벤트 방송 문장을 반환합니다."""
        event = self.coordinator.last_event
        return event.announcement if event else "배송 변경 이벤트 없음"

    @property
    def extra_state_attributes(self) -> dict[str, str]:
        """자동화 조건에서 사용할 최근 이벤트 속성을 반환합니다."""
        event = self.coordinator.last_event
        if event is None:
            return {
                "event_type": "",
                "tracking_number": "",
                "product_name": "",
                "status": "",
                "previous_status": "",
                "location": "",
                "event_time": "",
                "announcement": "",
            }
        return _event_payload(event)


def _delivery_payload(status: DeliveryStatus) -> dict[str, Any]:
    """배송건 하나를 대시보드용 속성 값으로 변환합니다."""
    basic_info = status.basic_info or {}
    courier = basic_info.get("배송기사", "")
    return {
        "tracking_number": status.tracking_number,
        "tracking_number_display": _format_tracking_number(status.tracking_number),
        "status": status.status,
        "display_group": status.display_group,
        "product_name": status.status_detail or "",
        "sender": status.sender or basic_info.get("보내는 분", ""),
        "receiver": status.receiver or basic_info.get("받는 분", ""),
        "last_location": status.last_location or "",
        "last_event_time": status.last_event_time or "",
        "courier": courier,
        "basic_info": basic_info,
        "tracking_history": status.tracking_history or [],
    }


def _delivery_summary_payload(status: DeliveryStatus) -> dict[str, str]:
    """목록 센서에 넣을 가벼운 배송 요약 값을 만듭니다."""
    return {
        "tracking_number": status.tracking_number,
        "tracking_number_display": _format_tracking_number(status.tracking_number),
        "status": status.status,
        "product_name": status.status_detail or "",
        "last_location": status.last_location or "",
        "last_event_time": status.last_event_time or "",
    }


def _event_payload(event: DeliveryEvent) -> dict[str, str]:
    """최근 이벤트를 Home Assistant 속성 값으로 변환합니다."""
    return {
        "event_type": event.event_type,
        "tracking_number": event.tracking_number,
        "product_name": event.product_name or "",
        "status": event.status,
        "previous_status": event.previous_status or "",
        "location": event.location or "",
        "event_time": event.event_time or "",
        "announcement": event.announcement,
    }


def _format_tracking_number(tracking_number: str) -> str:
    """운송장 번호를 네 자리 단위로 포맷합니다."""
    digits = "".join(char for char in tracking_number if char.isdigit())
    return "-".join(digits[index : index + 4] for index in range(0, len(digits), 4))


def _active_statuses(data: dict[str, DeliveryStatus]) -> list[DeliveryStatus]:
    """진행중 배송 목록을 최근 일시순으로 반환합니다."""
    active = [status for status in data.values() if status.display_group == "진행중"]
    return sorted(active, key=lambda status: status.last_event_time or "", reverse=True)


def _completed_statuses(data: dict[str, DeliveryStatus]) -> list[DeliveryStatus]:
    """완료 배송 목록을 최근 일시순으로 반환합니다."""
    completed = [status for status in data.values() if status.display_group == "배송완료"]
    return sorted(completed, key=lambda status: status.last_event_time or "", reverse=True)


def _completed_retention_days(entry: ConfigEntry) -> int:
    """설정된 배송완료 보관 일수를 반환합니다."""
    return int(
        entry.options.get(
            CONF_COMPLETED_RETENTION_DAYS,
            DEFAULT_COMPLETED_RETENTION_DAYS,
        )
    )


def _cleanup_stale_entities(
    hass: HomeAssistant,
    entry: ConfigEntry,
    valid_tracking_numbers: set[str],
) -> None:
    """유효하지 않은 운송장 번호의 센서와 기기를 레지스트리에서 정리합니다.

    보관기간이 지나 사라진 배송건과, 이전 버전(슬롯 방식)에서 남은 엔티티를
    같은 방식으로 함께 정리한다 — 둘 다 unique_id의 운송장 번호 부분이
    현재 유효 집합에 없다는 공통점을 이용한다.
    """
    entity_registry = er.async_get(hass)
    device_registry = dr.async_get(hass)
    entry_prefix = f"{entry.entry_id}_"
    fixed_unique_ids = {
        f"{entry.entry_id}_summary",
        f"{entry.entry_id}_active",
        f"{entry.entry_id}_completed",
        f"{entry.entry_id}_last_event",
    }

    for entity_entry in er.async_entries_for_config_entry(entity_registry, entry.entry_id):
        if entity_entry.domain != "sensor" or entity_entry.platform != DOMAIN:
            continue
        if entity_entry.unique_id in fixed_unique_ids:
            continue
        tracking_number = _tracking_number_from_unique_id(
            entity_entry.unique_id, entry_prefix
        )
        if tracking_number is None or tracking_number not in valid_tracking_numbers:
            entity_registry.async_remove(entity_entry.entity_id)

    for device_entry in dr.async_entries_for_config_entry(device_registry, entry.entry_id):
        identifiers = {
            identifier for domain, identifier in device_entry.identifiers if domain == DOMAIN
        }
        if entry.entry_id in identifiers:
            continue  # 통합구성요소 메인 기기는 유지
        tracking_number = next(
            (
                identifier[len(entry_prefix) :]
                for identifier in identifiers
                if identifier.startswith(entry_prefix)
            ),
            None,
        )
        if tracking_number is None or tracking_number not in valid_tracking_numbers:
            device_registry.async_remove_device(device_entry.id)


def _tracking_number_from_unique_id(unique_id: str, entry_prefix: str) -> str | None:
    """센서 unique_id에서 운송장 번호 부분을 추출합니다."""
    if not unique_id.startswith(entry_prefix):
        return None
    remainder = unique_id[len(entry_prefix) :]
    for field, _name in PARCEL_FIELDS:
        suffix = f"_{field}"
        if remainder.endswith(suffix):
            return remainder[: -len(suffix)]
    return None


def _device_info(coordinator: CJOneDeliveryCoordinator) -> dict[str, Any]:
    """생성된 센서를 하나의 CJ O-NE 기기 아래 묶습니다."""
    return {
        "identifiers": {(DOMAIN, coordinator.config_entry.entry_id)},
        "name": "CJ O-NE 배송조회",
        "manufacturer": "CJ Logistics",
    }


def _parcel_device_info(
    coordinator: CJOneDeliveryCoordinator,
    tracking_number: str,
) -> dict[str, Any]:
    """운송장 번호별 세부 센서를 하나의 기기 아래 묶습니다."""
    return {
        "identifiers": {
            (DOMAIN, f"{coordinator.config_entry.entry_id}_{tracking_number}")
        },
        "name": f"택배 {_format_tracking_number(tracking_number)}",
        "manufacturer": "CJ Logistics",
        "via_device": (DOMAIN, coordinator.config_entry.entry_id),
    }
