"""CJ O-NE 배송조회 앱 백엔드 API 클라이언트.

앱의 하이브리드 JS와 네이티브 브릿지를 분석해 확인한 요청 포맷을 재현합니다.
요청/응답 본문과 H_PARAM 헤더는 앱과 같은 SEED-CBC 기반 KISA 래퍼를 사용합니다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import base64
import hashlib
import json
import logging
from typing import Any
from urllib.parse import quote, unquote

from aiohttp import ClientSession
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from .exceptions import CJOneDeliveryError, CannotConnect, InvalidAuth
from .const import COMPLETED_RECENT_LIMIT

_LOGGER = logging.getLogger(__name__)

APP_ID = "cjkoreaexpress"
APP_VERSION = "6.3.3"
BASE_URL = "https://dxcstmapp.cjlogistics.com/"
SMS_AUTH_URL = f"{BASE_URL}app.do?cmd=SMS_AUTH"
COMPARE_AUTH_C_URL = f"{BASE_URL}app.do?cmd=COMPARE_AUTH_C2"
AUTHORIZATION_URL = f"{BASE_URL}kioskapp.do?cmd=AUTHORIZATION"
REFRESH_URL = f"{BASE_URL}kioskapp.do?cmd=REFRESH"
DELIVERY_LIST_URL = f"{BASE_URL}delivery.do?cmd=GEN_DIV_SCH"
DELIVERY_INFO_URL = f"{BASE_URL}delivery.do?cmd=INFO"
DELIVERY_COUNT_URL = f"{BASE_URL}delivery.do?cmd=GEN_DIV_SCH_CNT"

SEED_KEY = bytes([9, 15, 9, 10, 7, 4, 3, 9, 5, 6, 13, 2, 9, 5, 14, 2])
SEED_IV = bytes([7, 10, 5, 11, 13, 12, 6, 5, 11, 6, 4, 15, 5, 10, 15, 3])

AUTH_TYPE1_IV = bytes([1, 2, 3, 4, 5, 6, 7, 8, 9, 16, 17, 18, 19, 20, 21, 22])
AUTH_TYPE1_KEY = bytes([35, 105, 112, 97, 115, 116, 115, 101, 114, 57, 64, 0, 0, 0, 0, 0])
AUTH_TYPE2_KEY = bytes([39, 105, 112, 97, 115, 116, 115, 101, 114, 107, 101, 121, 0, 0, 0, 0])


@dataclass(slots=True)
class DeliveryStatus:
    """API 클라이언트가 반환하는 정규화된 택배 상태."""

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


@dataclass(slots=True)
class AuthSession:
    """SMS 인증 후 발급되는 앱 인증 세션."""

    user_id: str
    access_token: str
    refresh_token: str


class CJOneDeliveryClient:
    """CJ O-NE 배송조회 앱 API용 얇은 비동기 클라이언트."""

    def __init__(
        self,
        session: ClientSession,
        phone_number: str,
        user_id: str | None = None,
        access_token: str | None = None,
        refresh_token: str | None = None,
        device_id: str | None = None,
    ) -> None:
        """클라이언트를 초기화합니다."""
        self._session = session
        self._phone_number = _normalize_phone_number(phone_number)
        self._user_id = user_id
        self._access_token = access_token
        self._refresh_token = refresh_token
        self._device_id = device_id or _make_device_id(self._phone_number)

    async def async_send_verification_code(self) -> None:
        """전화번호 인증번호 발송을 요청합니다."""
        _LOGGER.debug("CJ O-NE 인증번호 발송 요청: %s", self._phone_number)
        response = await self._async_app_post(
            SMS_AUTH_URL,
            {"PHONE": self._phone_number},
            screen_code="0x02",
            skip_token=True,
        )
        if response.get("RES_CD") != "S":
            raise CannotConnect(response.get("RES_MSG", "인증번호 발송에 실패했습니다."))

    async def async_verify_code(self, auth_code: str) -> AuthSession:
        """인증번호를 검증하고 이후 요청에 사용할 인증 세션을 반환합니다."""
        _LOGGER.debug("CJ O-NE 인증번호 검증 요청: %s", self._phone_number)
        response = await self._async_app_post(
            COMPARE_AUTH_C_URL,
            {
                "PHONE": self._phone_number,
                "AUTH_KEY": auth_code,
                "REQ_DATE": _request_timestamp(),
                "MBLAPP_ID": APP_ID,
            },
            skip_token=True,
        )
        if response.get("RES_CD") != "S":
            raise InvalidAuth("인증번호가 올바르지 않습니다.")

        user_id = response.get("USRID")
        if not user_id:
            raise CannotConnect("인증 응답에 사용자 ID가 없습니다.")

        self._user_id = user_id
        token_response = await self._async_app_post(
            AUTHORIZATION_URL,
            {},
            skip_token=True,
        )
        if token_response.get("RES_CD") != "S":
            raise CannotConnect(
                token_response.get("RES_MSG", "인증 토큰 발급에 실패했습니다.")
            )

        access_token = token_response.get("ACCESSTOKEN")
        refresh_token = token_response.get("REFRESHTOKEN")
        if not access_token or not refresh_token:
            raise CannotConnect("토큰 발급 응답에 토큰 값이 없습니다.")

        return AuthSession(
            user_id=user_id,
            access_token=access_token,
            refresh_token=refresh_token,
        )

    async def async_validate_token(self) -> None:
        """저장된 인증 토큰이 유효한지 확인합니다."""
        if not self._access_token or not self._refresh_token or not self._user_id:
            raise InvalidAuth("저장된 인증 토큰이 없습니다.")

    async def async_get_delivery_status(
        self,
        tracking_number: str,
    ) -> DeliveryStatus:
        """운송장 번호 하나의 택배 상태를 조회합니다."""
        statuses = await self.async_get_delivery_statuses()
        tracking_digits = _normalize_phone_number(tracking_number)
        return statuses.get(
            tracking_digits,
            DeliveryStatus(
                tracking_number=tracking_digits,
                status="조회 결과 없음",
                status_detail="앱 배송조회 목록에서 해당 운송장 번호를 찾지 못했습니다.",
            ),
        )

    async def async_get_delivery_statuses(self) -> dict[str, DeliveryStatus]:
        """로그인된 전화번호의 전체 배송상황 목록을 조회합니다."""
        if not self._access_token or not self._user_id:
            raise InvalidAuth("저장된 인증 토큰이 없습니다.")

        rows = await self._async_get_delivery_rows()
        _LOGGER.debug(
            "CJ O-NE 배송 목록 응답: count=%s",
            len(rows),
        )
        statuses: dict[str, DeliveryStatus] = {}
        for row in _filter_display_rows(rows):
            if not isinstance(row, dict):
                continue
            detail = await self._async_get_delivery_detail(row)
            status = _delivery_status_from_row(row, detail)
            key = status.tracking_number or f"delivery_{len(statuses) + 1}"
            statuses[key] = status
        return statuses

    async def _async_get_delivery_rows(self) -> list[dict[str, Any]]:
        """앱과 같이 배송 목록 전체 페이지를 조회합니다."""
        first_response = await self._async_app_post(
            DELIVERY_LIST_URL,
            self._build_delivery_list_payload(page=1),
            token=self._access_token,
        )
        rows = _find_delivery_rows(first_response)
        total_page = _get_total_page(rows, first_response)

        for page in range(2, total_page + 1):
            response = await self._async_app_post(
                DELIVERY_LIST_URL,
                self._build_delivery_list_payload(page=page),
                token=self._access_token,
            )
            rows.extend(_find_delivery_rows(response))

        return _deduplicate_rows(rows)

    async def _async_get_delivery_detail(
        self,
        row: dict[str, Any],
    ) -> dict[str, Any] | None:
        """운송장 상세 기본정보와 배송 타임라인을 조회합니다."""
        tracking_number = _normalize_phone_number(str(row.get("TRSPBILLNUM", "")))
        if not tracking_number:
            return None

        try:
            return await self._async_app_post(
                DELIVERY_INFO_URL,
                {
                    "TRSPBILLNUM": tracking_number,
                    "PRNGNUM": tracking_number,
                    "SCH_DIV": "01",
                },
                token=self._access_token,
            )
        except CJOneDeliveryError as err:
            _LOGGER.debug("CJ O-NE 배송 상세 조회 실패(%s): %s", tracking_number, err)
            return None

    async def _async_app_post(
        self,
        url: str,
        data: dict[str, Any],
        *,
        screen_code: str | None = None,
        skip_token: bool = False,
        token: str | None = None,
    ) -> dict[str, Any]:
        """앱과 같은 형식으로 API를 호출합니다."""
        header_token = None if skip_token else token or self._access_token
        headers = {
            "Content-Type": "application/json; charset=utf-8",
            "H_PARAM": _kisa_encrypt(
                _quote_json(
                    self._build_header_payload(
                        screen_code=screen_code,
                        token=header_token,
                    )
                )
            ),
            "KISA_ENABLE": "Y",
            "BOOL_ENC": "Y",
            "authentication": _build_authentication(self._device_id),
        }
        if header_token:
            headers["TOKEN"] = header_token

        body = {"B_PARAM": _kisa_encrypt(_quote_json(data))}

        async with self._session.post(url, headers=headers, json=body, timeout=60) as resp:
            text = await resp.text()
            if resp.status >= 400:
                raise CannotConnect(f"CJ O-NE API HTTP 오류: {resp.status}")

        try:
            payload = json.loads(text)
        except json.JSONDecodeError as err:
            raise CannotConnect("CJ O-NE API 응답이 JSON 형식이 아닙니다.") from err

        encrypted_body = payload.get("B_PARAM")
        if not encrypted_body:
            return payload

        decrypted = unquote(_kisa_decrypt(str(encrypted_body))).replace("\n", " ").replace("+", " ")
        try:
            return json.loads(decrypted)
        except json.JSONDecodeError as err:
            raise CannotConnect("CJ O-NE API 암호화 응답을 JSON으로 해석하지 못했습니다.") from err

    def _build_header_payload(
        self,
        *,
        screen_code: str | None,
        token: str | None,
    ) -> dict[str, Any]:
        """앱의 H_PARAM 헤더 JSON을 구성합니다."""
        payload: dict[str, Any] = {
            "DEV_OS": "ANDROID",
            "DEV_OS_VER": "13",
            "APP_VER_INFO": APP_VERSION,
            "PUSH_TOKEN": "",
        }
        if token:
            payload["TOKEN"] = token

        if screen_code == "0x02":
            payload.update(
                {
                    "USRID": "",
                    "USRNM": "",
                    "DTYOFCCD": "",
                    "DTYOFCNM": "",
                    "DTYOFCDIVCD": "",
                }
            )
            return payload

        payload.update(
            {
                "USRNM": "",
                "DTYOFCCD": "",
                "DTYOFCNM": "",
                "DTYOFCDIVCD": "",
                "CUST_TYPE": "01",
                "USRID": self._user_id or "",
            }
        )
        return payload

    def _build_delivery_list_payload(self, *, page: int) -> dict[str, Any]:
        """개인고객 배송조회 API 파라미터를 구성합니다."""
        tel1, tel2, tel3 = _split_phone_number(self._phone_number)
        return {
            "USR_ID": self._user_id or "",
            "PG_NUM": str(page),
            "AUTH_TEL1": tel1,
            "AUTH_TEL2": tel2,
            "AUTH_TEL3": tel3,
            "PRNGDIVCD": "",
            "SCH_DIV_STS": "",
            "SCH_DIV_STR_DT": "",
            "SCH_DIV_END_DT": "",
            "ORDER_TY": "",
            "APP_OS_DV_ID": "Android",
            "IDFA_VAL": "",
        }


def _normalize_phone_number(phone_number: str) -> str:
    """전화번호에서 숫자만 남깁니다."""
    return "".join(char for char in phone_number if char.isdigit())


def _request_timestamp() -> str:
    """앱 인증 요청 시간 형식 값을 반환합니다."""
    return datetime.now().strftime("%Y%m%d%H%M%S")


def _quote_json(value: dict[str, Any]) -> str:
    """앱과 같은 JSON URI 인코딩 문자열을 반환합니다."""
    raw = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return quote(raw, safe="").replace("%7B", "%7b").replace("%7b", "%7b")


def _kisa_encrypt(plain_text: str) -> str:
    """앱의 exWNKisaEncrypt와 같은 SEED-CBC 암호화 문자열을 반환합니다."""
    encryptor = _cipher(algorithms.SEED(SEED_KEY), modes.CBC(SEED_IV)).encryptor()
    encrypted = encryptor.update(_pkcs7_pad(plain_text.encode())) + encryptor.finalize()
    return _java_big_integer_hex(encrypted)


def _kisa_decrypt(encrypted_text: str) -> str:
    """앱의 exWNKisaDecrypt와 같은 SEED-CBC 복호화 문자열을 반환합니다."""
    encrypted = _java_big_integer_to_bytes(encrypted_text)
    decryptor = _cipher(algorithms.SEED(SEED_KEY), modes.CBC(SEED_IV)).decryptor()
    padded = decryptor.update(encrypted) + decryptor.finalize()
    return _pkcs7_unpad(padded).decode()


def _build_authentication(device_id: str) -> str:
    """앱의 authentication 헤더 값을 생성합니다."""
    first = _aes_cbc_encrypt_b64("MOBCST|any".encode(), AUTH_TYPE1_KEY, AUTH_TYPE1_IV)
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S.%f")[:18]
    second_plain = f"{first}^{device_id.upper()}|{timestamp}".encode()
    return _aes_cbc_encrypt_b64(second_plain, AUTH_TYPE2_KEY, AUTH_TYPE1_IV)


def _aes_cbc_encrypt_b64(data: bytes, key: bytes, iv: bytes) -> str:
    encryptor = _cipher(algorithms.AES(key), modes.CBC(iv)).encryptor()
    encrypted = encryptor.update(_pkcs7_pad(data)) + encryptor.finalize()
    return base64.urlsafe_b64encode(encrypted).decode()


def _cipher(algorithm: algorithms.CipherAlgorithm, mode: modes.Mode) -> Cipher:
    return Cipher(algorithm, mode)


def _pkcs7_pad(data: bytes, block_size: int = 16) -> bytes:
    padding = block_size - (len(data) % block_size)
    return data + bytes([padding]) * padding


def _pkcs7_unpad(data: bytes) -> bytes:
    padding = data[-1]
    if padding < 1 or padding > 16 or data[-padding:] != bytes([padding]) * padding:
        raise CannotConnect("CJ O-NE API 암호문 패딩이 올바르지 않습니다.")
    return data[:-padding]


def _java_big_integer_hex(data: bytes) -> str:
    value = int.from_bytes(data, byteorder="big", signed=True)
    return format(value, "x")


def _java_big_integer_to_bytes(value: str) -> bytes:
    number = int(value, 16)
    if number == 0:
        return b"\x00"
    length = max(1, (number.bit_length() + 8) // 8)
    while True:
        try:
            data = number.to_bytes(length, byteorder="big", signed=True)
        except OverflowError:
            length += 1
            continue
        if len(data) % 16 == 0:
            return data
        length += 1


def _make_device_id(phone_number: str) -> str:
    """서버 인증 헤더용 16자리 안정 장치 ID를 만듭니다."""
    return hashlib.sha256(phone_number.encode()).hexdigest()[:16].upper()


def _split_phone_number(phone_number: str) -> tuple[str, str, str]:
    """01012345678 형식 전화번호를 앱 저장 형식처럼 세 구간으로 나눕니다."""
    if len(phone_number) == 11:
        return phone_number[:3], phone_number[3:7], phone_number[7:]
    if len(phone_number) == 10:
        return phone_number[:3], phone_number[3:6], phone_number[6:]
    return phone_number[:3], phone_number[3:-4], phone_number[-4:]


def _delivery_status_from_row(
    row: dict[str, Any],
    detail: dict[str, Any] | None = None,
) -> DeliveryStatus:
    """앱 배송 목록 행을 Home Assistant 센서 상태로 정규화합니다."""
    source = detail or row
    tracking_number = _normalize_phone_number(str(source.get("TRSPBILLNUM", row.get("TRSPBILLNUM", ""))))
    status = str(
        source.get("SCNDIVNM")
        or source.get("DIVNM")
        or source.get("DLV_DIV_NM")
        or source.get("SCH_DIV_STS_NM")
        or _latest_history_message(detail)
        or _parcel_status_name(str(source.get("SCNDIVCD", "")))
        or "상태 확인"
    )
    return DeliveryStatus(
        tracking_number=tracking_number,
        status=status,
        status_detail=str(source.get("SKUNM") or source.get("GOODS_NM") or source.get("ITEM_NM") or "") or None,
        sender=str(source.get("SNDPRSNNM") or source.get("SNDR_NM") or source.get("SENDER_NM") or "") or None,
        receiver=str(source.get("RCVRNM") or source.get("RCVR_NM") or source.get("RECEIVER_NM") or "") or None,
        last_location=_latest_history_location(detail) or str(source.get("BRANNM") or source.get("BRAN_NM") or source.get("SCNBRANNM") or "") or None,
        last_event_time=_latest_history_time(detail) or _format_scan_time(source),
        display_group="배송완료" if _is_completed_delivery(source) else "진행중",
        basic_info=_build_basic_info(source, detail),
        tracking_history=_build_tracking_history(detail),
        raw={"list_row": row, "detail": detail} if detail else row,
    )


def _find_delivery_rows(response: dict[str, Any]) -> list[dict[str, Any]]:
    """배송조회 응답에서 배송 목록 배열을 찾습니다."""
    for key in ("list", "LIST", "rows", "ROWS", "row", "ROW"):
        value = response.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]

    for value in response.values():
        if isinstance(value, dict):
            rows = _find_delivery_rows(value)
            if rows:
                return rows
        if isinstance(value, list) and any(
            isinstance(item, dict) and "TRSPBILLNUM" in item for item in value
        ):
            return [item for item in value if isinstance(item, dict)]

    return []


def _format_scan_time(row: dict[str, Any]) -> str | None:
    """앱 배송 목록의 스캔 일시를 보기 좋은 문자열로 변환합니다."""
    scan_date = str(row.get("SCNDT") or "")
    scan_time = str(row.get("SCNHR") or "")
    if len(scan_date) == 8 and len(scan_time) >= 4:
        return (
            f"{scan_date[:4]}-{scan_date[4:6]}-{scan_date[6:8]} "
            f"{scan_time[:2]}:{scan_time[2:4]}"
        )
    if len(scan_date) == 8:
        return f"{scan_date[:4]}-{scan_date[4:6]}-{scan_date[6:8]}"
    return str(row.get("DLV_DTM") or row.get("SCAN_DTM") or "") or None


def _build_basic_info(
    source: dict[str, Any],
    detail: dict[str, Any] | None,
) -> dict[str, str]:
    """배송 상세 기본정보를 구성합니다."""
    carrier = "CJ대한통운"
    fare_div = str(source.get("FAREDIV") or "")
    fare_type = {"01": "선불", "02": "착불"}.get(fare_div, "신용" if fare_div else "")
    latest_history = _latest_history_row(detail)
    fields = {
        "운송장 번호": _format_tracking_number(str(source.get("TRSPBILLNUM") or "")),
        "택배회사": carrier,
        "상품정보": str(source.get("SKUNM") or source.get("GOODS_NM") or source.get("ITEM_NM") or ""),
        "보내는 분": str(source.get("SNDPRSNNM") or source.get("SNDR_NM") or ""),
        "받는 분": str(source.get("RCVRNM") or source.get("RCVR_NM") or ""),
        "배송기사": _courier_text(latest_history or source),
        "운임구분": fare_type,
    }
    return {key: value for key, value in fields.items() if value}


def _build_tracking_history(detail: dict[str, Any] | None) -> list[dict[str, str]] | None:
    """배송 상세 타임라인을 구성합니다."""
    if not detail:
        return None
    rows = detail.get("list")
    if not isinstance(rows, list):
        return None

    history: list[dict[str, str]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        item = {
            "상태": str(row.get("SCNDIVNM") or _parcel_status_name(str(row.get("SKUSTSCD", ""))) or ""),
            "일시": _format_work_time(row),
            "위치": str(row.get("BRANNM") or ""),
            "내용": str(row.get("DLVMSG") or ""),
            "배송기사": _courier_text(row),
        }
        history.append({key: value for key, value in item.items() if value})
    return history


def _latest_history_message(detail: dict[str, Any] | None) -> str | None:
    """가장 최근 배송 상세 메시지를 반환합니다."""
    history = _build_tracking_history(detail)
    if not history:
        return None
    return history[0].get("내용") or history[0].get("상태")


def _latest_history_row(detail: dict[str, Any] | None) -> dict[str, Any] | None:
    """가장 최근 배송 상세 원본 행을 반환합니다."""
    if not detail:
        return None
    rows = detail.get("list")
    if not isinstance(rows, list) or not rows or not isinstance(rows[0], dict):
        return None
    return rows[0]


def _latest_history_location(detail: dict[str, Any] | None) -> str | None:
    """가장 최근 배송 상세 위치를 반환합니다."""
    history = _build_tracking_history(detail)
    if not history:
        return None
    return history[0].get("위치")


def _latest_history_time(detail: dict[str, Any] | None) -> str | None:
    """가장 최근 배송 상세 일시를 반환합니다."""
    history = _build_tracking_history(detail)
    if not history:
        return None
    return history[0].get("일시")


def _format_work_time(row: dict[str, Any]) -> str:
    """상세 타임라인의 작업 일시를 보기 좋게 변환합니다."""
    work_date = str(row.get("WRKDT") or "")
    work_time = str(row.get("WRKHR") or "")
    if len(work_date) == 8 and len(work_time) >= 6:
        return (
            f"{work_date[:4]}-{work_date[4:6]}-{work_date[6:8]} "
            f"{work_time[:2]}:{work_time[2:4]}:{work_time[4:6]}"
        )
    if len(work_date) == 8:
        return f"{work_date[:4]}-{work_date[4:6]}-{work_date[6:8]}"
    return ""


def _format_tracking_number(tracking_number: str) -> str:
    """운송장 번호를 앱 표시처럼 네 자리 단위로 포맷합니다."""
    digits = _normalize_phone_number(tracking_number)
    return "-".join(digits[index : index + 4] for index in range(0, len(digits), 4))


def _courier_text(source: dict[str, Any]) -> str:
    """배송기사 이름과 전화번호 문자열을 반환합니다."""
    name = str(source.get("EMPNM") or source.get("SCNEMPNM") or "")
    phone = str(source.get("CLPHNUM") or source.get("TELNUM") or "")
    if name and phone:
        return f"{name}({phone})"
    return name or phone


def _get_total_page(rows: list[dict[str, Any]], response: dict[str, Any]) -> int:
    """배송조회 응답에서 전체 페이지 수를 가져옵니다."""
    candidates: list[Any] = []
    if rows:
        candidates.append(rows[0].get("TOT_PAGE"))
    candidates.extend(
        [
            response.get("TOT_PAGE"),
            response.get("tot_page"),
            response.get("TOTAL_PAGE"),
            response.get("totalPage"),
        ]
    )
    for candidate in candidates:
        try:
            return max(1, int(candidate))
        except (TypeError, ValueError):
            continue
    return 1


def _deduplicate_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """운송장 번호 기준으로 중복 배송건을 제거합니다."""
    deduplicated: dict[str, dict[str, Any]] = {}
    for index, row in enumerate(rows):
        tracking_number = _normalize_phone_number(str(row.get("TRSPBILLNUM", "")))
        key = tracking_number or f"delivery_{index}"
        deduplicated[key] = row
    return list(deduplicated.values())


def _filter_display_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """진행중 배송 전체와 최근 완료 배송 일부만 반환합니다."""
    active_rows = [row for row in rows if not _is_completed_delivery(row)]
    completed_rows = [row for row in rows if _is_completed_delivery(row)]
    active_rows.sort(key=_row_sort_key, reverse=True)
    completed_rows.sort(key=_row_sort_key, reverse=True)
    return active_rows + completed_rows[:COMPLETED_RECENT_LIMIT]


def _is_completed_delivery(row: dict[str, Any]) -> bool:
    """배송완료 건인지 반환합니다."""
    return str(row.get("SCNDIVCD", "")) == "91" or _parcel_status_name(
        str(row.get("SCNDIVCD", ""))
    ) == "배송완료"


def _row_sort_key(row: dict[str, Any]) -> str:
    """배송건 정렬용 스캔 일시 문자열을 반환합니다."""
    return f"{row.get('SCNDT', '')}{row.get('SCNHR', '')}"


def _parcel_status_name(status_code: str) -> str | None:
    """앱의 개인고객 배송 상태 코드명을 반환합니다."""
    if status_code in ("12", "13", "01", ""):
        return "배송예약"
    if status_code in ("11", "30", "42", "43"):
        return "상품이동중"
    if status_code in ("82", "83", "84"):
        return "배송출발"
    if status_code == "91":
        return "배송완료"
    if status_code in ("9927", "9928"):
        return "국제택배 항공"
    if status_code in ("9929", "9933", "9936"):
        return "국제택배 세관"
    return None
