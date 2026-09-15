# ⚡ OLYMPUS

**제우스는 목표와 승인을, 헤스티아는 배분과 보고를, 신과 인간은 단일 직무의 결과를 맡는다.**

현재 기준: **v1.4 · 2026-09-15 · DOCUMENTED**
다섯 라인: 유튜브 · 이모티콘 · 웹·앱 · 블로그 · 캐릭터

[헌법 v1.4](OLYMPUS_Agent_Architecture_v1.4.md) · [봇 프롬프트](prompts/OLYMPUS_Bot_Prompts_v1.4.md) · [기계 판독 계약](spec/olympus-contracts-v1.yaml) · [개정 판단과 적용 절차](docs/decisions/2026-09-15-constitution-v1.4.md)

## 이번 개정

| 개선 | 적용 결과 |
|---|---|
| 제작 책임 | 캐릭터 원화·창작 동작은 아프로디테, 웹·앱·파일 변환·영상 조립은 헤파이스토스 |
| 승인 후 실행 인계 | 제품상 필요한 직접 사용자 조작만 실행자 채팅으로 인계하고 헤스티아에 결과 복귀 |
| 이모티콘 | 상품과 공통 캐릭터를 분리하고 명세·매트릭스 → 시안 → 검수 → 패키징 → 제출 연결 |
| 민음사 제작 | 약 35초·4컷을 기본으로 사용하고 카드의 구체 값이 프로필 기본값보다 우선 |
| 민음사 큐 | 해당 파일 검수 PASS만 편입 질문 없이 추가, CONDITIONAL_PASS·FAIL은 홀드 |
| 공개 승인 | 이미 승인된 정확한 단건·유한 묶음은 재질문 없이 처리; 큐 편입은 공개 승인이 아님 |
| 결정 충돌 | 최신 확인된 결정·현재 정책·업무 카드·프로필 기본값의 범위와 우선순위 명시 |

**Fatal Giggle 제작 중단을 유지한다.** 민음사는 07·12·18·19 슬롯을 사용하며 실제 시간대는 현재 채널 설정에서 확인한다. 의도적 번호 공백 #036은 자동으로 채우지 않는다. 실제 게시·예약·채널 설정 변경은 이 저장소 개정으로 수행되지 않는다.

## 조직과 책임

| 신 | 단일 부서 책임 |
|---|---|
| 헤스티아 | 요청 접수, 프로젝트 DAG, 배분·인계·통합 보고 |
| 헤라 | 정책·브랜드·독립 품질 검수 |
| 아테나 | 목표·타깃·요구사항·우선순위 |
| 아르테미스 | 조사·출처·사실 및 규격 검증 |
| 아폴론 | 글·대본·대사·장면 명세 |
| 아프로디테 | 시각·UX 방향, 캐릭터 그림·창작 동작 |
| 디오니소스 | 기본안과 분리한 실험 제안 |
| 헤파이스토스 | 웹·앱·자동화, 파일 변환·영상 조립 |
| 포세이돈 | 서버·DB·저장소·인프라 신뢰성 |
| 헤르메스 | 승인된 게시·제출·릴리스 |
| 데메테르 | 일정·분석·회고·자산 축적 |
| 아레스 | 사고 분류·격리·복구 |

인간은 하나의 지속적 직무를 가지며 업무 카드마다 책임 인간은 한 명이다. 기존 인간을 먼저 검색하고 새 인간은 필요할 때만 등록한다. 인간·이름·과거 작업은 삭제하지 않는다. 현재 슬롯은 **91개(배정 후보 89개 + 보존 전용 2개)**이며 슬롯 수는 실제 인간 수가 아니다. [인간 레지스트리](registry/humans.yaml)는 기존의 빈 초기 상태다.

## 운영 문서

| 목적 | 문서 |
|---|---|
| 공통 실행·복구·평가 | [운영 플레이북](playbooks/agent-operations.md), [운영 계약](spec/operations-v1.yaml) |
| 유튜브 제작·큐·공개 | [유튜브 플레이북](playbooks/youtube-shorts.md) |
| 이모티콘 상품 제작 | [이모티콘 플레이북](playbooks/emoticon.md), [상품 카드 예시](templates/emoticon-project.yaml) |
| 카카오 참고 규격 | [공식 가이드 적용](playbooks/kakao-emoticon-guides.md) |
| 공통 캐릭터 자산 | [캐릭터 플레이북](playbooks/character-production.md), [밤](characters/bam/character.yaml), [실행 템플릿](templates/character-production.yaml) |
| 슬롯·메시지 계약 | [슬롯](registry/slots.yaml), [계약 예시](templates/contracts.example.yaml) |
| 로컬 검증 | [런타임 안내](runtime/README.md), [정적 계약 검사](scripts/validate_contracts.py) |

## 적용 상태와 검증

헌법·프롬프트·YAML·플레이북은 문서 기준선이다. 로컬 원장·평가기는 **LOCAL_SIMULATION_ONLY**이며 실제 Bot·인증 승인 큐·게시·예약의 적용 완료를 뜻하지 않는다. 실제 전환은 로드한 policy_version·policy_commit, 기존 인간 연결, 관련 수용 시나리오의 증거로 확인한다.

```bash
python scripts/validate_contracts.py
python -m unittest discover -s tests -v
```

이슈 #3–#7의 실제 운영 적용과 [Draft PR #8](https://github.com/BoxLogoDev/olympus_grokbot/pull/8)은 별도 추적 대상이다. 로컬 테스트 통과로 닫지 않는다.

## 이전 기준선

[v1.3 헌법](OLYMPUS_Agent_Architecture_v1.3.md) · [v1.3 프롬프트](prompts/OLYMPUS_Bot_Prompts_v1.3.md) · [v1.2](OLYMPUS_Agent_Architecture_v1.2.md) · [v1.1](OLYMPUS_Agent_Architecture_v1.1.md) · [v1.0](OLYMPUS_Agent_Architecture_v1.0.md) · [v0.4](OLYMPUS_Agent_Architecture_v0.4.md)

과거 문서는 당시 판단을 보존한다. 새 업무에는 현재 v1.4 묶음을 사용하고 진행 중 업무는 영향 검토 후 전환한다.
