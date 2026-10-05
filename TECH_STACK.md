# 기술 스택 결정 (2026-09-07)

솔로 개발 + 11월 30일 배포 마감을 최우선 기준으로, Python 기반으로 통일해서 컨텍스트 스위칭을 최소화하는 방향으로 결정.

## 백엔드
- **FastAPI** (Python)
  - 공공데이터 API(국가교통DB·TAAS) 호출이 많으므로 async 지원이 유리
  - Pydantic으로 교통영향평가 분석표(법정 서식) 데이터 구조를 스키마로 관리하기 좋음
  - 자동 생성되는 OpenAPI 문서로 나중에 API 형태 확장도 쉬움

## 프론트엔드
- MVP 단계: **FastAPI + Jinja2 + 순수 `fetch`** (서버 렌더링, 별도 프론트 빌드/배포 파이프라인 없이 하나의 앱으로 관리)
  - ※ 2026-10 구현 시 htmx 대신 `fetch`로 결과 HTML 조각을 주입하는 방식으로 변경: 교차로·접근로가 중첩 입력이라 JSON으로 보내는 게 단순했고, 외부 CDN 의존을 피하기 위해서.
  - 입력 폼 → 결과 대시보드 정도의 상호작용에는 htmx로 충분하고, React 빌드 세팅에 쓸 시간을 아낄 수 있음
  - 시간이 남으면 (Week 11-12 버퍼) 대시보드 부분만 별도 React/Next.js로 교체 검토

## 데이터베이스
- **PostgreSQL** (Railway/Supabase 등 매니지드 무료·저가 티어)
  - 프로젝트 입력값, 표준 원단위 참조 테이블, 생성된 평가서 이력 저장
  - MVP 극초반 로컬 개발 단계에서는 SQLite로 빠르게 시작하고, Week 4 백엔드 단계 진입 시 Postgres로 전환해도 무방

## 문서 생성 (핵심 산출물)
- **python-docx**: 법정 서식(분석표 포함) 기반 .docx 초안 조립
- **WeasyPrint** 또는 **reportlab**: PDF 출력이 필요하면 HTML 템플릿 → PDF 변환
- 시각화(교통량 배분도·LOS 등급표)는 **matplotlib**으로 이미지 생성 후 문서에 삽입

## 배포
- **Railway** (또는 Render): git push 기반 배포, Postgres 매니지드 인스턴스 같이 제공, 개인 프로젝트 규모에 적합한 저비용
- 도메인 연결은 후순위 (Week 9-10에 처리)

## 인증
- MVP 단계에서는 **최소한의 인증만**: 이메일 기반 간단 로그인 (예: fastapi-users 라이브러리) 또는 초기엔 베타 초대 코드 방식으로 시작
- 결제·팀 기능 등은 11월 목표에서 제외 (완성 이후 과제로 남김)

## 외부 연동
- 국가교통DB / TAAS: Week 1에 API 키 신청 후 실제 응답 포맷(REST/XML/CSV 등) 확인해서 이 문서에 추가 기록 예정
- 개선대책 문구 생성: Claude API 연동 (Anthropic API, Messages API 직접 호출)

## 보류/후순위 (11월 이후 과제)
- Celery/Redis 등 비동기 작업 큐 — MVP는 동기 처리로 충분, 응답이 느린 외부 API만 타임아웃 넉넉히 설정
- 다중 지자체 확장, 다양한 사업유형 확장
- 결제·팀 협업 기능

## 배포 URL (2026-09-07 등록)
- 임시 목업/플레이스홀더: https://cheerful-pithivier-714396.netlify.app/ (Netlify Drop으로 배포, VWorld 등 서비스URL 필수 항목 등록용)
- 추후 실제 서비스는 Railway 등으로 재배포 예정 (TECH_STACK 배포 항목 참고), 이 URL은 그 전까지 자리 지킴이 역할
