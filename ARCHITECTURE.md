# 멀티 에이전트 아키텍처 (v0.1)

## 흐름

```
ProjectInput(+사용자 실측 입력)
      │
  Planning ──► Data ──┬──► Creative ─┐         (Creative ∥ AI 병렬)
 (범위·규모)  (수요·LOS) └──► AI ──────┤
                                       ▼
                                  Engineering ──► Reflection ──┐
                                 (문서 조립)      (체크리스트 점검) │
                                       ▲                         │ AI 소유 섹션 누락 시
                                       └──── AI 재작성 ◄──────────┘ (최대 N회, LLM 실연결 시)
```

- 코드: [app/pipeline.py](app/pipeline.py), 에이전트: [app/agents/](app/agents/), 공유 상태: [app/state.py](app/state.py)
- 모든 에이전트는 `run(state) -> state`. 공유 상태(`ReportState`)에 자기 몫만 채운다.

## 에이전트별 역할과 LLM 사용 여부

| 에이전트 | 하는 일 | LLM |
|---|---|---|
| Planning | 목표년도(1·3년), 공간적 범위(반경·교차로 수) 결정 | 안 씀 (규칙) |
| Data | 유발교통량, 교차로 LOS 계산. 실측이 없으면 `needs_input`으로 반환 | 안 씀 (계산) |
| Creative | LOS 표 등 표·도표 생성 | 안 씀 |
| AI | 문제점·개선방안 5개 섹션 문장 생성 | **씀** |
| Engineering | 별표 1 순서로 문서 조립, 미작성은 `[미작성]` 표시, 디스클레이머 삽입 | 안 씀 |
| Reflection | 체크리스트 v0.1로 누락 점검, MOCK·빈 응답은 작성으로 인정 안 함 | 안 씀 (현재) |

원칙: **숫자는 코드가 계산하고 LLM은 문장만 쓴다.** LLM이 수치를 만들지 못하게 프롬프트에 분석 결과만 주고 새 수치 금지를 명시한다.

## 현재 한계 (v0.1)

- 원단위: 임시값(KTDB 승인 전). 결과에 `PROVISIONAL` 경고가 붙는다.
- 규모 배수: 시행령 별표 1 미확보라 공간적 범위는 최소 구간 임시 적용(`spatial_provisional`).
- LOS 기준: HCM 임시값(도로용량편람 미적용).
- 체크리스트 52개 자동 항목 중 현재 파이프라인이 채우는 건 일부(샘플 입력 기준 7개). 나머지는 현장 조사·사용자 입력이 필요한 항목이다.
- LLM 미연결(mock) 상태에서는 AI 섹션이 모두 "미검증"으로 분류된다.
