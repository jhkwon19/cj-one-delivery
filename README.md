# CJ O-NE 배송조회 Home Assistant 커스텀 통합구성요소

이 저장소는 CJ O-NE 택배 배송상태를 조회하는 Home Assistant 커스텀 통합구성요소입니다.

## 현재 상태

- Home Assistant 통합구성요소 기본 구조는 `custom_components/cj_one_delivery` 아래에 있습니다.
- UI 설정 플로우는 휴대폰 번호 입력 후 인증번호를 입력하는 2단계 구조입니다.
- 센서 엔티티는 요약/목록/최근 이벤트 센서와 대시보드용 고정 슬롯 센서가 생성됩니다.
- 앱의 네이티브 KISA 암호화 브릿지 동작을 Python으로 재현해 `api.py`에 구현했습니다.
- 휴대폰 인증, 토큰 발급, 개인고객 배송조회 목록 호출 경로를 구현했습니다.
- 실제 Home Assistant 환경에서 계정 등록과 배송조회 응답 필드 매핑 검증이 필요합니다.

## 앱 분석 결과

- 패키지명: `com.cjkoreaexpress`
- 확인한 앱 버전: `6.3.3`, `versionCode 657`
- 앱 형태: `assets/res/www` 아래 화면 HTML/JS가 있는 하이브리드 앱
- 운영 API 기본 주소: `https://dxcstmapp.cjlogistics.com/`
- 휴대폰 인증번호 발송: `app.do?cmd=SMS_AUTH`, 파라미터 `PHONE`
- 개인고객 인증번호 검증: `app.do?cmd=COMPARE_AUTH_C2`, 파라미터 `PHONE`, `AUTH_KEY`, `REQ_DATE`, `MBLAPP_ID`
- 토큰 발급: `kioskapp.do?cmd=AUTHORIZATION`
- 토큰 갱신: `kioskapp.do?cmd=REFRESH`
- 개인 배송조회 목록: `delivery.do?cmd=GEN_DIV_SCH`
- 배송예정 건수: `delivery.do?cmd=GEN_DIV_SCH_CNT`

SMS 인증 성공 후 앱은 `USRID`를 저장하고 `AUTHORIZATION` API로 `ACCESSTOKEN`과
`REFRESHTOKEN`을 발급받습니다. 이후 배송조회 API에는 access token을 붙입니다.

앱 API 호출은 단순 JSON POST가 아니라 네이티브 브릿지 `exWNCustomHttpSendPost`를
통과합니다. JS에서는 `H_PARAM`, `KISA_ENABLE`, `BOOL_ENC`, `TOKEN` 값을 구성하고,
`exWNKisaEncrypt`로 암호화합니다. 현재 통합구성요소는 이 형식을 Python에서 재현합니다.

확인한 암호화 방식은 다음과 같습니다.

- `H_PARAM`: 헤더 JSON을 `encodeURIComponent` 형식으로 인코딩한 뒤 SEED-CBC로 암호화
- 요청 본문: `sendData` JSON을 같은 방식으로 암호화해 `{"B_PARAM": "..."}`로 전송
- 응답 본문: 응답 JSON의 `B_PARAM`을 SEED-CBC로 복호화한 뒤 URI 디코딩
- `KISA_ENABLE`, `BOOL_ENC`: 암호화 URL에서 `Y`
- `authentication`: 앱이 생성하는 AES-CBC 기반 시간 포함 헤더

## 구현 검증 체크리스트

1. Home Assistant에서 통합구성요소 추가 화면을 열고 휴대폰 번호를 입력합니다.
2. 문자 인증번호 수신 여부를 확인합니다.
3. 인증번호 입력 후 토큰 발급이 성공하는지 확인합니다.
4. 로그인된 배송 목록이 자동 조회되고 대표 센서 속성에 배송 목록이 표시되는지 확인합니다.
5. 배송조회 응답의 실제 필드명을 보고 센서 속성 매핑을 보정합니다.

## 로컬 Home Assistant 설치

`custom_components/cj_one_delivery` 폴더를 Home Assistant의 `config/custom_components`
디렉터리에 복사하거나 심볼릭 링크로 연결합니다. 이후 Home Assistant를 재시작하고
설정 > 기기 및 서비스에서 `CJ O-NE 배송조회`를 추가합니다.

## 대시보드 구성

이 통합구성요소는 커스텀 카드를 요구하지 않습니다. 진행중/완료 배송 슬롯을 Home
Assistant 기기처럼 나누고, 각 슬롯 아래에 상태, 상품명, 운송장 번호, 최근 위치 같은
세부 센서를 생성합니다. 대시보드에서는 기본 `엔티티` 카드나 `섹션`을 사용해 원하는
슬롯 센서만 배치하면 됩니다.

예를 들어 `진행중 배송 슬롯 1`에는 다음 센서가 묶입니다.

- `상태`
- `상품명`
- `운송장 번호`
- `보내는 분`
- `받는 분`
- `최근 위치`
- `최근 일시`
- `배송기사`
- `배송 상세`

## 엔티티 구조

기본 생성 센서는 다음과 같습니다.

- `배송 요약`: `진행중 N건`을 상태값으로 표시하고, 진행중/완료 건수와 최근 변경 요약,
  인증 상태를 속성에 저장합니다.
- `진행중 배송`: 진행중 배송 수를 상태값으로 표시하고, `deliveries` 속성에 진행중 배송
  전체 목록과 상세 타임라인을 저장합니다.
- `배송완료 최근 5건`: 최근 완료 배송 수를 상태값으로 표시하고, `deliveries` 속성에
  최근 완료일 기준 5건의 배송 목록과 상세 타임라인을 저장합니다.
- `최근 배송 이벤트`: 마지막으로 변경된 배송 상태를 방송하기 좋은 문장으로 표시합니다.
  구글 스피커 방송 자동화는 이 센서의 상태 변경을 트리거로 사용하면 됩니다.

대시보드에 바로 배치할 수 있는 고정 슬롯별 세부 센서도 함께 생성됩니다.

- `진행중 배송 슬롯 1` ~ `진행중 배송 슬롯 3`: 최근 일시 기준 진행중 배송 최대 3건
- `배송완료 슬롯 1` ~ `배송완료 슬롯 5`: 최근 완료일 기준 배송완료 최대 5건

각 슬롯은 Home Assistant 기기처럼 묶이고, 아래 세부 센서가 붙습니다.

- `상태`
- `상품명`
- `운송장 번호`
- `보내는 분`
- `받는 분`
- `최근 위치`
- `최근 일시`
- `배송기사`
- `배송 상세`

해당 순번의 배송이 없으면 세부 센서 상태값은 `없음`이고 `is_empty` 속성이 `true`가
됩니다. `배송 상세` 센서는 배송기본정보와 배송상세 타임라인을 속성에 저장합니다.
