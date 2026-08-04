"""CJ O-NE 배송조회 센서."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import DeliveryStatus
from .const import (
    ACTIVE_SLOT_LIMIT,
    CONF_ACTIVE_SLOT_COUNT,
    CONF_COMPLETED_SLOT_COUNT,
    COMPLETED_RECENT_LIMIT,
    DEFAULT_ACTIVE_SLOT_COUNT,
    DEFAULT_COMPLETED_SLOT_COUNT,
    DOMAIN,
)
from .coordinator import CJOneDeliveryCoordinator, DeliveryEvent

SLOT_FIELDS: tuple[tuple[str, str], ...] = (
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
SLOT_FIELD_NAMES = dict(SLOT_FIELDS)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry[CJOneDeliveryCoordinator],
    async_add_entities: AddEntitiesCallback,
) -> None:
    """택배 상태 센서를 설정합니다."""
    coordinator = entry.runtime_data
    async_add_entities(
        [
            CJOneDeliverySummarySensor(coordinator),
            CJOneDeliveryDeliveryListSensor(coordinator, "active"),
            CJOneDeliveryDeliveryListSensor(coordinator, "completed_recent"),
            *[
                CJOneDeliveryDeliverySlotFieldSensor(coordinator, "active", index, field)
                for index in range(ACTIVE_SLOT_LIMIT)
                for field, _name in SLOT_FIELDS
            ],
            *[
                CJOneDeliveryDeliverySlotFieldSensor(
                    coordinator,
                    "completed_recent",
                    index,
                    field,
                )
                for index in range(COMPLETED_RECENT_LIMIT)
                for field, _name in SLOT_FIELDS
            ],
            CJOneDeliveryLastEventSensor(coordinator),
        ]
    )


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
        active_count = len(self.coordinator.active_statuses)
        return f"진행중 {active_count}건"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """요약과 인증 상태 속성을 반환합니다."""
        last_event = self.coordinator.last_event
        return {
            "active_count": len(self.coordinator.active_statuses),
            "completed_recent_count": len(self.coordinator.completed_statuses),
            "active_slot_count": _active_slot_count(self.coordinator.config_entry),
            "completed_slot_count": _completed_slot_count(self.coordinator.config_entry),
            "completed_recent_limit": _completed_slot_count(self.coordinator.config_entry),
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
            self._attr_name = "배송완료 최근 배송"
            self._attr_unique_id = f"{coordinator.config_entry.entry_id}_completed_recent"

    @property
    def native_value(self) -> int:
        """목록에 포함된 배송건 수를 반환합니다."""
        return len(self._statuses)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """배송 목록 요약 속성을 반환합니다."""
        attrs: dict[str, Any] = {
            "deliveries": [
                _delivery_summary_payload(status, index)
                for index, status in enumerate(self._statuses, start=1)
            ],
            "last_error": self.coordinator.last_error or "",
        }
        if self._list_type == "completed_recent":
            attrs["completed_recent_limit"] = _completed_slot_count(
                self.coordinator.config_entry
            )
        return attrs

    @property
    def _statuses(self) -> list[DeliveryStatus]:
        """이 센서가 표시할 배송 목록을 반환합니다."""
        if self._list_type == "active":
            return self.coordinator.active_statuses
        return self.coordinator.completed_statuses


class CJOneDeliveryDeliverySlotFieldSensor(
    CoordinatorEntity[CJOneDeliveryCoordinator],
    SensorEntity,
):
    """배송 슬롯 아래에 묶이는 세부 정보 센서."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: CJOneDeliveryCoordinator,
        slot_type: str,
        slot_index: int,
        field: str,
    ) -> None:
        """배송 슬롯 세부 센서를 초기화합니다."""
        super().__init__(coordinator)
        self._slot_type = slot_type
        self._slot_index = slot_index
        self._field = field
        self._attr_device_info = _slot_device_info(coordinator, slot_type, slot_index)
        number = slot_index + 1
        field_name = SLOT_FIELD_NAMES[field]
        if slot_type == "active":
            self._attr_unique_id = (
                f"{coordinator.config_entry.entry_id}_active_{number}_{field}"
            )
        else:
            self._attr_unique_id = (
                f"{coordinator.config_entry.entry_id}_completed_{number}_{field}"
            )
        self._attr_name = field_name

    @property
    def native_value(self) -> str:
        """슬롯 배송의 세부 정보 값을 반환합니다."""
        status = self._status
        if status is None:
            return "사용 안 함" if not self._is_enabled_slot else "없음"

        payload = _delivery_payload(status)
        if self._field == "detail":
            return "상세 있음" if payload["tracking_history"] else "상세 없음"
        return str(payload.get(self._field) or "없음")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """슬롯 배송 공통 속성과 상세 정보를 반환합니다."""
        status = self._status
        attrs: dict[str, Any] = {
            "slot_type": self._slot_type,
            "slot_index": self._slot_index + 1,
            "field": self._field,
            "is_empty": status is None,
            "is_enabled": self._is_enabled_slot,
            "last_error": self.coordinator.last_error or "",
        }
        if status is None:
            return attrs

        payload = _delivery_payload(status)
        if self._field == "detail":
            attrs.update(
                {
                    "tracking_number": payload["tracking_number"],
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
        """이 슬롯에 표시할 배송 상태를 반환합니다."""
        if not self._is_enabled_slot:
            return None
        statuses = (
            self.coordinator.active_statuses
            if self._slot_type == "active"
            else self.coordinator.completed_statuses
        )
        if self._slot_index >= len(statuses):
            return None
        return statuses[self._slot_index]

    @property
    def _is_enabled_slot(self) -> bool:
        """옵션에서 활성화된 슬롯인지 반환합니다."""
        if self._slot_type == "active":
            return self._slot_index < _active_slot_count(self.coordinator.config_entry)
        return self._slot_index < _completed_slot_count(self.coordinator.config_entry)


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


def _delivery_summary_payload(
    status: DeliveryStatus,
    slot_index: int,
) -> dict[str, str | int]:
    """목록 센서에 넣을 가벼운 배송 요약 값을 만듭니다."""
    return {
        "slot_index": slot_index,
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


def _active_slot_count(entry: ConfigEntry) -> int:
    """옵션에 설정된 진행중 슬롯 개수를 반환합니다."""
    return int(
        entry.options.get(
            CONF_ACTIVE_SLOT_COUNT,
            DEFAULT_ACTIVE_SLOT_COUNT,
        )
    )


def _completed_slot_count(entry: ConfigEntry) -> int:
    """옵션에 설정된 완료 슬롯 개수를 반환합니다."""
    return int(
        entry.options.get(
            CONF_COMPLETED_SLOT_COUNT,
            DEFAULT_COMPLETED_SLOT_COUNT,
        )
    )


def _device_info(coordinator: CJOneDeliveryCoordinator) -> dict[str, Any]:
    """생성된 센서를 하나의 CJ O-NE 기기 아래 묶습니다."""
    return {
        "identifiers": {(DOMAIN, coordinator.config_entry.entry_id)},
        "name": "CJ O-NE 배송조회",
        "manufacturer": "CJ Logistics",
    }


def _slot_device_info(
    coordinator: CJOneDeliveryCoordinator,
    slot_type: str,
    slot_index: int,
) -> dict[str, Any]:
    """배송 슬롯별 세부 센서를 하나의 기기 아래 묶습니다."""
    number = slot_index + 1
    slot_id = "active" if slot_type == "active" else "completed"
    slot_name = (
        f"진행중 배송 슬롯 {number}"
        if slot_type == "active"
        else f"배송완료 슬롯 {number}"
    )
    return {
        "identifiers": {
            (DOMAIN, f"{coordinator.config_entry.entry_id}_{slot_id}_{number}")
        },
        "name": slot_name,
        "manufacturer": "CJ Logistics",
        "via_device": (DOMAIN, coordinator.config_entry.entry_id),
    }
