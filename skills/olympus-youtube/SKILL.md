---
name: olympus-youtube
description: OLYMPUS 유튜브 제작의 인계·검수·복구 절차. 헤스티아가 승인한 해당 라인 업무에서 사용한다.
version: 0.1.0
---

# 유튜브 Process

상위 기준은 헌법 v1.3, OLY-OPS-001..006과 공통 olympus-process Skill이다.
상태는 DRAFT다. 설치·실제 수동 검증 2회를 완료하기 전 VALIDATED나 루틴 활성화로 표시하지 않는다.

현재 채널의 기존 3권 배정·원본 문학 방향·07·12·18·19 슬롯·편집 도구를 보존한다. 기존 클립 제작 담당의 슬롯·도구 연결이 확인되지 않으면 해당 인계는 BLOCKED다.

## 실행 준비

헤스티아 계획, 실제 Bot·단일 직무 연결, 입력 파일·버전·해시, 완료 조건, 독립 검수자,
예산·사용 가능한 도구가 필요하다. 입력 누락은 DRAFT/BLOCKED로 남긴다. 현재 정책과 관련된
기억·원형·템플릿 버전을 고정하고 작업에 필요한 문맥만 받는다. 기존 인간을 먼저 검색한다.

## 단계와 검수

- **research** / `ARTEMIS-SOURCE-HUNTER`: 권별 근거와 출처. 선행: 없음. 필수 점검: PARENT_GOD_REVIEW, SOURCE_ACCESS, FACT_SCOPE.
- **script** / `APOLLO-SHORTS-SCRIPT`: 권별 숏츠 대본. 선행: research. 필수 점검: PARENT_GOD_REVIEW, SCRIPT_SOURCE, READING_TIME.
- **hook** / `APHRODITE-HOOK-WRITER`: 대본 의미와 맞는 훅. 선행: script. 필수 점검: PARENT_GOD_REVIEW, HOOK_PROMISE, MEANING.
- **assembly** / `HEPHAESTUS-VIDEO-ASSEMBLER`: 기존 클립·음성·자막을 조립한 영상. 선행: script, hook. 필수 점검: PARENT_GOD_REVIEW, VIDEO_PLAYBACK, AUDIO_SUBTITLE_SYNC, CLIP_INPUT_HASH.
- **metadata** / `HERMES-METADATA-PACKAGER`: 영상·제목·설명·썸네일의 게시 준비 매니페스트. 선행: assembly. 필수 점검: PARENT_GOD_REVIEW, MANIFEST_MATCH, CHANNEL_SETTINGS.

각 산출물은 별도 원자 업무와 단일 인간의 책임이다. 부모 신의 직무 검수 근거를 먼저 남기고,
지정된 독립 검수자가 해당 파일 버전의 의미·매체 규격을 판정한다. 단계가 불필요한 프로젝트는
헤스티아가 실행 전 새 DAG·버전을 확정한다. 실행자가 중간 단계를 임의로 생략하지 않는다.

## 실행·복구·보고

제작 전 claim(PRODUCTION), 파일과 점검 근거 준비 후 submit, 검수 전 claim(REVIEW),
정확한 attempt_id·result_digest로 review를 호출한다. 반려는 실패 항목·수정 단계·재사용 가능한
산출물을 명시한다. 동일 실패 2회·수정 최대 2회·총시도 6회와 상위 예산을 지킨다.
중단은 block, 원격 결과·비용 확인은 reconcile로 처리한다. 입력 변경은 영향 단계와 후속 단계만 갱신한다.

출력에는 산출물 링크·해시, 검수 근거, 총비용·대기·수정 횟수, 실제/미확인 상태를 포함한다.
공개·제출·배포는 별도의 승인된 실행이며 이 Skill과 원장이 수행하지 않는다.
공개 준비 완료를 공개 완료라고 보고하지 않는다. 일반 내부 인계는 헤스티아가 처리한다.

회고는 병목 하나와 근거만 남긴다. 실제 성과가 없으면 UNMEASURED다. 기억 승격은 독립 검증 후 수행한다.
