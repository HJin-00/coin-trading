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

## 브랜치 계획

1. `codex/bootstrap-foundation`: 설정, 도메인 모델, 리스크 가드
2. `codex/bybit-market-data`: V5 시세 수집, 저장, 데이터 품질 검증
3. `codex/strategy-research`: 지표·시장 국면·백테스트와 워크포워드 검증
4. `codex/multimodal-analysis`: 차트 렌더링, LLM 구조화 출력, 평가셋
5. `codex/testnet-execution`: 테스트넷 주문, 보호 주문, 재시작 복구
6. `codex/operations`: 관측성, 일일 리포트, 킬 스위치, 배포

> 이 소프트웨어는 투자 자문이 아닙니다. 선물 거래는 원금 전액을 잃을 수 있습니다.

