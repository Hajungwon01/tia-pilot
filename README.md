# 교통영향평가 초안 자동화

서울시 공동주택(아파트) 교통영향평가서 **초안**을 만드는 개인 프로젝트입니다.
사업 개요와 교차로 현장조사 값을 입력하면 유발교통량·서비스수준(LOS, 사업 미시행/시행/개선 후)을 계산하고,
지침 체크리스트로 누락을 점검한 뒤 Word(.docx) 초안을 내려받을 수 있습니다.

> **초안 작성 지원 도구입니다.** 실제 인허가 제출용이 아니며, 최종 검토·날인은 교통기술사 등 전문가가 해야 합니다.
> 현재 유발 원단위는 **임시값**(KTDB 승인 전)이라 수치는 잠정입니다.

구조·한계는 [ARCHITECTURE.md](ARCHITECTURE.md), 작업 목록은 [BACKLOG.md](BACKLOG.md), 과정 산출물은 [DELIVERABLES.md](DELIVERABLES.md).

## 실행

```bash
python -m venv .venv
.venv\Scripts\activate          # macOS/Linux: source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env            # 실제 LLM을 쓰려면 키를 채운다(없어도 mock으로 동작)
uvicorn app.main:app --reload --port 8000
```

브라우저에서 http://localhost:8000 을 열고 **“샘플 입력 채우기” → “분석 실행”**.

### LLM과 비용

- 웹 폼의 **“실제 LLM으로 문단 작성”은 기본 꺼짐**입니다. 꺼져 있으면 키가 설정돼 있어도 외부 호출을 하지 않습니다.
- 켜면 호출이 5회 이상 발생해 비용이 듭니다. 서버에 키가 없으면 켤 수 없습니다.
- 배포할 때는 **`APP_ACCESS_CODE`를 반드시 설정**하세요(실제 LLM 사용 시 코드를 요구). 시간당 실제 LLM 분석은 `MAX_LIVE_RUNS_PER_HOUR`(기본 10회)로 제한됩니다.
- `.env` 설정: [.env.example](.env.example)

### API

| 메서드 | 경로 | 설명 |
|---|---|---|
| GET | `/` | 입력 폼 |
| GET | `/health` | 상태, LLM 사용 가능 여부 |
| POST | `/api/analyze` | JSON 분석 요청 → 결과 요약(JSON) + `download_url` |
| GET | `/api/report/{job_id}.docx` | Word 초안 다운로드 |
| POST | `/ui/analyze` | 폼이 쓰는 엔드포인트(결과 HTML 조각) |

요청 예시와 필드는 `app/service.py`의 `AnalyzeRequest`를 보세요. 비율은 소수로 보냅니다(2% → `0.02`).
분석 결과는 서버 메모리에 1시간 보관됩니다(재시작하면 사라짐).

### 명령줄 도구

```bash
python scripts/export_docx.py              # 샘플로 DOCX 생성 (LLM은 mock 강제)
python scripts/export_docx.py --live       # 설정된 실제 LLM 사용(비용 발생)
python scripts/smoke_llm.py                # LLM 실연결 점검
python -m pytest -q                        # 테스트(항상 mock, 외부 호출 없음)
```

## 근거 자료

- 교통영향평가 지침(국토교통부고시 제2021-317호), 도시교통정비 촉진법 시행령, 서울특별시 교통영향평가에 관한 조례
- 도로용량편람 2013(국토교통부): 신호교차로 서비스수준 <표 8-2>, 지체식 d1·d2 — 원문 확인
