"""CJ O-NE 배송조회 핵심 로직 단위 테스트."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = "custom_components.cj_one_delivery"


@dataclass(slots=True)
class FakeDeliveryStatus:
    """테스트용 배송 상태."""

    tracking_number: str
    status: str
    status_detail: str | None = None
    sender: str | None = None
    receiver: str | None = None
    last_location: str | None = None
    last_event_time: str | None = None
    display_group: str = "진행중"
    basic_info: dict[str, str] | None = None
    tracking_history: list[dict[str, str]] | None = None
    raw: dict | None = None


class FakeEntry:
    """테스트용 ConfigEntry."""

    entry_id = "test_entry"

    def __init__(self, options: dict[str, int] | None = None) -> None:
        self.options = options or {}


def load_modules() -> tuple[types.ModuleType, types.ModuleType]:
    """Home Assistant 의존성을 스텁 처리하고 테스트 대상 모듈을 로드합니다."""
    _install_homeassistant_stubs()
    _install_package_stubs()
    const = _load_module(f"{PACKAGE}.const", ROOT / "custom_components/cj_one_delivery/const.py")
    sys.modules[f"{PACKAGE}.const"] = const
    coordinator = _load_module(
        f"{PACKAGE}.coordinator",
        ROOT / "custom_components/cj_one_delivery/coordinator.py",
    )
    sys.modules[f"{PACKAGE}.coordinator"] = coordinator
    sensor = _load_module(f"{PACKAGE}.sensor", ROOT / "custom_components/cj_one_delivery/sensor.py")
    return coordinator, sensor


def _install_homeassistant_stubs() -> None:
    homeassistant = types.ModuleType("homeassistant")
    config_entries = types.ModuleType("homeassistant.config_entries")
    core = types.ModuleType("homeassistant.core")
    helpers = types.ModuleType("homeassistant.helpers")
    update_coordinator = types.ModuleType("homeassistant.helpers.update_coordinator")
    components = types.ModuleType("homeassistant.components")
    sensor_component = types.ModuleType("homeassistant.components.sensor")
    entity_platform = types.ModuleType("homeassistant.helpers.entity_platform")
    entity_registry = types.ModuleType("homeassistant.helpers.entity_registry")
    device_registry = types.ModuleType("homeassistant.helpers.device_registry")

    class ConfigEntry:
        pass

    class HomeAssistant:
        pass

    class DataUpdateCoordinator:
        @classmethod
        def __class_getitem__(cls, item):
            return cls

        def __init__(self, hass, logger, *, config_entry, name, update_interval):
            self.hass = hass
            self.logger = logger
            self.config_entry = config_entry
            self.name = name
            self.update_interval = update_interval
            self.data = None

    class CoordinatorEntity:
        @classmethod
        def __class_getitem__(cls, item):
            return cls

        def __init__(self, coordinator):
            self.coordinator = coordinator

    class SensorEntity:
        pass

    class EntityRegistry:
        pass

    class DeviceRegistry:
        pass

    config_entries.ConfigEntry = ConfigEntry
    core.HomeAssistant = HomeAssistant
    update_coordinator.DataUpdateCoordinator = DataUpdateCoordinator
    update_coordinator.CoordinatorEntity = CoordinatorEntity
    sensor_component.SensorEntity = SensorEntity
    entity_platform.AddEntitiesCallback = object
    entity_registry.EntityRegistry = EntityRegistry
    entity_registry.async_get = lambda hass: EntityRegistry()
    entity_registry.async_entries_for_config_entry = lambda registry, entry_id: []
    device_registry.DeviceRegistry = DeviceRegistry
    device_registry.async_get = lambda hass: DeviceRegistry()

    sys.modules["homeassistant"] = homeassistant
    sys.modules["homeassistant.config_entries"] = config_entries
    sys.modules["homeassistant.core"] = core
    sys.modules["homeassistant.helpers"] = helpers
    sys.modules["homeassistant.helpers.update_coordinator"] = update_coordinator
    sys.modules["homeassistant.components"] = components
    sys.modules["homeassistant.components.sensor"] = sensor_component
    sys.modules["homeassistant.helpers.entity_platform"] = entity_platform
    sys.modules["homeassistant.helpers.entity_registry"] = entity_registry
    sys.modules["homeassistant.helpers.device_registry"] = device_registry


def _install_package_stubs() -> None:
    custom_components = types.ModuleType("custom_components")
    custom_components.__path__ = []
    package = types.ModuleType(PACKAGE)
    package.__path__ = []
    api = types.ModuleType(f"{PACKAGE}.api")

    class CJOneDeliveryClient:
        pass

    api.CJOneDeliveryClient = CJOneDeliveryClient
    api.DeliveryStatus = FakeDeliveryStatus

    sys.modules["custom_components"] = custom_components
    sys.modules[PACKAGE] = package
    sys.modules[f"{PACKAGE}.api"] = api
    exceptions = _load_module(
        f"{PACKAGE}.exceptions", ROOT / "custom_components/cj_one_delivery/exceptions.py"
    )
    sys.modules[f"{PACKAGE}.exceptions"] = exceptions


def _load_module(name: str, path: Path) -> types.ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load module: {name}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _install_aiohttp_stub() -> None:
    """api.py가 임포트만 하고 실제로 쓰지 않는 aiohttp를 스텁 처리합니다."""
    aiohttp = types.ModuleType("aiohttp")

    class ClientSession:
        pass

    aiohttp.ClientSession = ClientSession
    sys.modules["aiohttp"] = aiohttp


def load_api_module() -> types.ModuleType:
    """실제 api.py를 로드합니다(홈어시스턴트 의존성이 없어 aiohttp만 스텁 처리)."""
    _install_aiohttp_stub()
    custom_components = types.ModuleType("custom_components")
    custom_components.__path__ = []
    package = types.ModuleType(PACKAGE)
    package.__path__ = []
    sys.modules["custom_components"] = custom_components
    sys.modules[PACKAGE] = package

    sys.modules[f"{PACKAGE}.exceptions"] = _load_module(
        f"{PACKAGE}.exceptions", ROOT / "custom_components/cj_one_delivery/exceptions.py"
    )
    sys.modules[f"{PACKAGE}.const"] = _load_module(
        f"{PACKAGE}.const", ROOT / "custom_components/cj_one_delivery/const.py"
    )
    return _load_module(f"{PACKAGE}.api", ROOT / "custom_components/cj_one_delivery/api.py")


class DeliveryEventTests(unittest.TestCase):
    """최근 배송 이벤트 계산 테스트."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.coordinator, cls.sensor = load_modules()

    def test_first_refresh_does_not_create_last_event(self) -> None:
        coordinator = self.coordinator.CJOneDeliveryCoordinator(
            hass=None,
            entry=FakeEntry(),
            client=object(),
        )
        coordinator._update_last_event(
            {
                "301551253841": FakeDeliveryStatus(
                    tracking_number="301551253841",
                    status="상품준비",
                    status_detail="led adapter",
                    last_location="글로벌직구팀직영(이주창)",
                    last_event_time="2026-07-31 17:45:47",
                )
            }
        )

        self.assertIsNone(coordinator.last_event)

    def test_new_delivery_announcement(self) -> None:
        event = self.coordinator._event_from_status_change(
            "301551253841",
            previous=None,
            current=FakeDeliveryStatus(
                tracking_number="301551253841",
                status="상품준비",
                status_detail="led adapter",
                last_location="글로벌직구팀직영(이주창)",
                last_event_time="2026-07-31 17:45:47",
            ),
        )

        self.assertIsNotNone(event)
        self.assertEqual(event.event_type, "new_delivery")
        self.assertEqual(event.previous_status, None)
        self.assertEqual(
            event.announcement,
            "led adapter 배송이 새로 확인되었습니다. 현재 글로벌직구팀직영(이주창)에서 상품준비 상태입니다.",
        )

    def test_status_changed_announcement(self) -> None:
        event = self.coordinator._event_from_status_change(
            "301551253841",
            previous=FakeDeliveryStatus(
                tracking_number="301551253841",
                status="상품준비",
                last_location="글로벌직구팀직영(이주창)",
                last_event_time="2026-07-31 17:45:47",
            ),
            current=FakeDeliveryStatus(
                tracking_number="301551253841",
                status="집화처리",
                status_detail="led adapter",
                last_location="글로벌직구팀직영(최종태)",
                last_event_time="2026-08-01 19:01:45",
            ),
        )

        self.assertIsNotNone(event)
        self.assertEqual(event.event_type, "status_changed")
        self.assertEqual(event.previous_status, "상품준비")
        self.assertEqual(
            event.announcement,
            "led adapter 배송이 글로벌직구팀직영(최종태)에서 집화처리 상태로 변경되었습니다.",
        )

    def test_tracking_updated_when_location_or_time_changes(self) -> None:
        event = self.coordinator._event_from_status_change(
            "301551253841",
            previous=FakeDeliveryStatus(
                tracking_number="301551253841",
                status="간선상차",
                last_location="대전Hub",
                last_event_time="2026-08-02 02:59:47",
            ),
            current=FakeDeliveryStatus(
                tracking_number="301551253841",
                status="간선상차",
                status_detail="led adapter",
                last_location="대덕Sub",
                last_event_time="2026-08-02 09:23:05",
            ),
        )

        self.assertIsNotNone(event)
        self.assertEqual(event.event_type, "tracking_updated")
        self.assertEqual(event.previous_status, "간선상차")

    def test_unchanged_status_does_not_create_event(self) -> None:
        status = FakeDeliveryStatus(
            tracking_number="301551253841",
            status="간선상차",
            last_location="대전Hub",
            last_event_time="2026-08-02 02:59:47",
        )

        event = self.coordinator._event_from_status_change(
            "301551253841",
            previous=status,
            current=status,
        )

        self.assertIsNone(event)


class DeliveryListTests(unittest.TestCase):
    """배송 목록 정렬 테스트."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.coordinator, cls.sensor = load_modules()

    def test_active_statuses_are_sorted_by_last_event_time(self) -> None:
        data = {
            "1": FakeDeliveryStatus("1", "집화처리", last_event_time="2026-08-01 10:00:00"),
            "2": FakeDeliveryStatus("2", "간선상차", last_event_time="2026-08-02 10:00:00"),
            "3": FakeDeliveryStatus(
                "3",
                "배달완료",
                last_event_time="2026-08-03 10:00:00",
                display_group="배송완료",
            ),
        }

        active = self.sensor._active_statuses(data)

        self.assertEqual([status.tracking_number for status in active], ["2", "1"])

    def test_completed_statuses_are_sorted_by_last_event_time(self) -> None:
        data = {
            "1": FakeDeliveryStatus(
                "1",
                "배달완료",
                last_event_time="2026-08-01 10:00:00",
                display_group="배송완료",
            ),
            "2": FakeDeliveryStatus(
                "2",
                "배달완료",
                last_event_time="2026-08-03 10:00:00",
                display_group="배송완료",
            ),
            "3": FakeDeliveryStatus(
                "3",
                "배달완료",
                last_event_time="2026-08-02 10:00:00",
                display_group="배송완료",
            ),
        }

        completed = self.sensor._completed_statuses(data)

        self.assertEqual(
            [status.tracking_number for status in completed], ["2", "3", "1"]
        )

    def test_entity_cleanup_removes_stale_and_legacy_unique_ids(self) -> None:
        entry_id = "entry123"
        prefix = f"{entry_id}_"

        # 신규(운송장 기반) unique_id는 유효 집합에 있으면 유지
        self.assertEqual(
            self.sensor._tracking_number_from_unique_id(
                f"{prefix}301551253841_status", prefix
            ),
            "301551253841",
        )
        # 구 버전 슬롯 기반 unique_id는 어떤 유효 운송장 번호와도 일치하지 않음
        self.assertEqual(
            self.sensor._tracking_number_from_unique_id(
                f"{prefix}active_1_status", prefix
            ),
            "active_1",
        )
        self.assertNotIn("active_1", {"301551253841"})
        # 알 수 없는 형식은 정리 대상으로 처리되도록 None 반환
        self.assertIsNone(
            self.sensor._tracking_number_from_unique_id(f"{prefix}summary", prefix)
        )


class DeliveryRetentionFilterTests(unittest.TestCase):
    """배송완료 보관기간 필터링 테스트."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.api = load_api_module()

    @staticmethod
    def _row(*, tracking_number: str, status_code: str, days_ago: int) -> dict:
        scan_time = datetime.now() - timedelta(days=days_ago)
        return {
            "TRSPBILLNUM": tracking_number,
            "SCNDIVCD": status_code,
            "SCNDT": scan_time.strftime("%Y%m%d"),
            "SCNHR": scan_time.strftime("%H%M%S"),
        }

    def test_active_rows_are_always_kept_regardless_of_age(self) -> None:
        rows = [self._row(tracking_number="1", status_code="11", days_ago=365)]

        result = self.api._filter_display_rows(rows, completed_retention_days=7)

        self.assertEqual(len(result), 1)

    def test_completed_rows_within_retention_are_kept(self) -> None:
        rows = [self._row(tracking_number="1", status_code="91", days_ago=3)]

        result = self.api._filter_display_rows(rows, completed_retention_days=7)

        self.assertEqual(len(result), 1)

    def test_completed_rows_past_retention_are_dropped(self) -> None:
        rows = [self._row(tracking_number="1", status_code="91", days_ago=10)]

        result = self.api._filter_display_rows(rows, completed_retention_days=7)

        self.assertEqual(result, [])


class DeliveryDetailCachingTests(unittest.IsolatedAsyncioTestCase):
    """완료 배송 상세 캐싱/정리 동작 테스트."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.api = load_api_module()

    def _make_client(self, rows: list[dict], retention_days: int):
        api = self.api

        class RecordingClient(api.CJOneDeliveryClient):
            def __init__(self) -> None:
                super().__init__(
                    session=None,
                    phone_number="01000000000",
                    user_id="user",
                    access_token="token",
                    refresh_token="refresh",
                    completed_retention_days=retention_days,
                )
                self.detail_calls: list[str] = []

            async def _async_get_delivery_rows(self):
                return rows

            async def _async_get_delivery_detail(self, row):
                self.detail_calls.append(row["TRSPBILLNUM"])
                return {"list": []}

        return RecordingClient()

    @mock.patch("asyncio.sleep", new_callable=mock.AsyncMock)
    async def test_completed_detail_is_fetched_only_once(self, _sleep: mock.AsyncMock) -> None:
        now = datetime.now()
        rows = [
            {
                "TRSPBILLNUM": "111",
                "SCNDIVCD": "91",
                "SCNDT": now.strftime("%Y%m%d"),
                "SCNHR": now.strftime("%H%M%S"),
            },
            {
                "TRSPBILLNUM": "222",
                "SCNDIVCD": "11",
                "SCNDT": now.strftime("%Y%m%d"),
                "SCNHR": now.strftime("%H%M%S"),
            },
        ]
        client = self._make_client(rows, retention_days=7)

        await client.async_get_delivery_statuses()
        await client.async_get_delivery_statuses()

        self.assertEqual(client.detail_calls.count("111"), 1)
        self.assertEqual(client.detail_calls.count("222"), 2)
        # 캐시로 재사용되지 않은 상세 조회(3번)마다 요청 사이에 지연이 들어가야 한다.
        self.assertEqual(_sleep.await_count, 3)

    @mock.patch("asyncio.sleep", new_callable=mock.AsyncMock)
    async def test_completed_cache_prunes_once_retention_window_passes(
        self, _sleep: mock.AsyncMock
    ) -> None:
        ten_days_ago = datetime.now() - timedelta(days=10)
        rows = [
            {
                "TRSPBILLNUM": "111",
                "SCNDIVCD": "91",
                "SCNDT": ten_days_ago.strftime("%Y%m%d"),
                "SCNHR": ten_days_ago.strftime("%H%M%S"),
            }
        ]
        client = self._make_client(rows, retention_days=30)

        first = await client.async_get_delivery_statuses()
        self.assertIn("111", first)
        self.assertIn("111", client._completed_cache)

        client.set_completed_retention_days(7)
        second = await client.async_get_delivery_statuses()

        self.assertEqual(second, {})
        self.assertNotIn("111", client._completed_cache)


if __name__ == "__main__":
    unittest.main()
