# Coin Trading

Bybit USDT 무기한 선물을 대상으로 하는 **리스크 우선** 자동매매 연구 프로젝트입니다.
현재 단계에서는 실거래를 지원하지 않으며, 백테스트와 Bybit 테스트넷 검증을 먼저 수행합니다.

## 핵심 설계

- 가격·거래량·기술 지표가 주 신호를 만든다.
- 멀티모달 LLM은 차트 이미지와 수치 데이터를 보조 분석한다.
- 결정론적 리스크 엔진만 포지션 크기와 주문 허용 여부를 결정한다.
- LLM 오류, 지연, 응답 없음은 모두 `NO_TRADE`로 안전하게 실패한다.
- 손절 없는 주문과 설정 한도를 넘는 주문은 실행 계층에서 거부한다.

자세한 판단 근거는 [아키텍처](docs/architecture.md), 단계별 작업은
[로드맵](docs/roadmap.md), 강제 운영 규칙은 [트레이딩 정책](docs/trading-policy.md)을 참고하세요.

## 개발 환경

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
pytest
```

API 키는 `.env.example`을 참고해 `.env`에만 저장합니다. Bybit 키에는 출금 권한을 부여하지
않고 IP 화이트리스트를 설정해야 합니다. `LIVE_TRADING=false`가 기본값입니다.

## 시장 데이터 계층

`coin_trading.market_data`는 Bybit V5 공개 API에서 선형 무기한 캔들을 수집합니다. REST 수집기는
최신순 응답을 자동으로 페이지네이션하고 미확정 캔들을 제외한 뒤, 중복·누락·시간 순서와 OHLCV를
검증합니다. WebSocket 파서는 `confirm=true` 캔들만 내보내며 ticker snapshot/delta를 병합해
펀딩비와 미결제약정을 제공합니다. `ImmutableJsonlStore`는 원본 배치를 `data/raw` 아래에 배치별
JSONL 파일로 한 번만 생성합니다.

UTC 시각 범위를 지정해 공개 REST 데이터(인증 키 불필요)를 내려받을 수 있습니다.

```bash
coin-trading-download \
  --symbol BTCUSDT \
  --interval 60 \
  --start 2025-01-01T00:00:00Z \
  --end 2026-01-01T00:00:00Z
```

## 전략 연구 계층

`coin_trading.strategy`는 확정 캔들에서 *EMA*, *RSI*, *MACD*, *볼린저밴드*, *ATR*, 거래량 비율을
코드로 계산합니다. 시장을 추세·횡보·고변동성으로 분류하고, 상위 시간대 추세가 일치할 때만
눌림목 또는 거래량 돌파 신호를 허용합니다. 백테스터는 신호 다음 캔들 시가에 진입하며 수수료,
슬리피지, 펀딩비와 보수적인 손절 우선 체결을 반영합니다. `walk_forward`는 학습 구간에서 선택한
파라미터를 시간상 분리된 다음 검증 구간에 적용합니다.

## 멀티모달 검토 계층

`coin_trading.multimodal`은 고정된 120개 확정 캔들 차트와 코드에서 계산한 지표 요약만 Responses
API에 전달합니다. 구조화된 검토가 규칙 기반 신호와 일치할 때만 합의 게이트를 통과하며, 시간 초과,
API 오류, 낮은 신뢰도, 잘못된 무효화 가격은 모두 `NO_TRADE`로 처리됩니다.

## 테스트넷 실행 계층

`coin_trading.execution`은 Bybit 테스트넷에서만 작동합니다. 시작할 때 거래소 포지션과 주문을
복구해야 하며, 손절이나 목표가가 없는 기존 포지션이 발견되면 신규 주문을 차단합니다. 주문에는
결정적 `orderLinkId`와 전체 포지션용 시장가 TP/SL을 함께 설정하고 거래소 단위에 맞게 정규화합니다.

## 운영 계층

실전과 다른 테스트넷 체결 환경을 전략 평가에 사용하지 않습니다. `coin_trading.operations`의 로컬
페이퍼 브로커가 메인넷 공개 확정 캔들로 진입·손절·목표 체결을 보수적으로 모사합니다. 테스트넷은
API 예외 검증, Demo Trading은 지원되는 주문 API 통합 검증에만 사용합니다. 파일 기반 킬 스위치,
JSONL 감사 로그, 일일 손익·승률·손익비 리포트를 제공합니다.

## 브랜치 계획

1. `codex/bootstrap-foundation`: 설정, 도메인 모델, 리스크 가드
2. `codex/bybit-market-data`: V5 시세 수집, 저장, 데이터 품질 검증
3. `codex/strategy-research`: 지표·시장 국면·백테스트와 워크포워드 검증
4. `codex/multimodal-analysis`: 차트 렌더링, LLM 구조화 출력, 평가셋
5. `codex/testnet-execution`: 테스트넷 주문, 보호 주문, 재시작 복구
6. `codex/operations`: 관측성, 일일 리포트, 킬 스위치, 배포

> 이 소프트웨어는 투자 자문이 아닙니다. 선물 거래는 원금 전액을 잃을 수 있습니다.
