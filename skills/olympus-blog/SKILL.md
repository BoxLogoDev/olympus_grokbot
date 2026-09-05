---
name: olympus-blog
description: OLYMPUS 블로그 제작의 인계·검수·복구 절차. 헤스티아가 승인한 해당 라인 업무에서 사용한다.
version: 0.1.0
---

# 블로그 Process

상위 기준은 헌법 v1.3, OLY-OPS-001..006과 공통 olympus-process Skill이다.
상태는 DRAFT다. 설치·실제 수동 검증 2회를 완료하기 전 VALIDATED나 루틴 활성화로 표시하지 않는다.

원고 한 편과 대표 이미지·출처·게시 준비 묶음을 만든다. 기존 블로그 담당이 Notion 초안 전용이라면 그 경계를 유지한다.

## 실행 준비

헤스티아 계획, 실제 Bot·단일 직무 연결, 입력 파일·버전·해시, 완료 조건, 독립 검수자,
예산·사용 가능한 도구가 필요하다. 입력 누락은 DRAFT/BLOCKED로 남긴다. 현재 정책과 관련된
기억·원형·템플릿 버전을 고정하고 작업에 필요한 문맥만 받는다. 기존 인간을 먼저 검색한다.

## 단계와 검수

- **sources** / `ARTEMIS-SOURCE-HUNTER`: 자료·출처 묶음. 선행: 없음. 필수 점검: PARENT_GOD_REVIEW, SOURCE_ACCESS, FACT_SCOPE.
- **draft** / `APOLLO-BLOG-WRITER`: 원고. 선행: sources. 필수 점검: PARENT_GOD_REVIEW, CLAIM_CITATIONS, READER_PURPOSE.
- **edit** / `APOLLO-COPY-EDITOR`: 교정된 원고. 선행: draft. 필수 점검: PARENT_GOD_REVIEW, CLARITY, FACT_PRESERVATION.
- **cover** / `APHRODITE-COVER-ART-DIRECTOR`: 대표 이미지 제작 지시·대체 텍스트. 선행: edit. 필수 점검: PARENT_GOD_REVIEW, ARTICLE_RELEVANCE, ALT_TEXT.
- **image** / `HEPHAESTUS-IMAGE-PROCESSOR`: 허용된 원본을 가공한 대표 이미지. 선행: cover. 필수 점검: PARENT_GOD_REVIEW, LICENSE, IMAGE_FORMAT.
- **metadata** / `HERMES-METADATA-PACKAGER`: 게시 준비 파일·메타데이터. 선행: edit, image. 필수 점검: PARENT_GOD_REVIEW, MANIFEST_MATCH, DRAFT_ONLY.

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
