# Grokbot Process 패키지 설치·운영

구현 버전 0.1.0 / 정책 v1.3 (`30363791228181b986cc94491ab938ee544699f4`).
이 패키지는 실제 파일과 운영 증거를 기록하는 단일 호스트 도구다. 모델·제작 도구를 대신 실행하거나
Grokbot 설정을 자동 변경하지 않는다. 실제 업무 자료는 비공개 위치에만 둔다.

## 1. 기존 운영 확인과 보존

헤스티아는 [내보내기 지시문](grokbot-export-request.md)을 먼저 수행한다.
기존 Bot ID·이름·직무·루틴 설정을 보존한다. 과거 Notion 스냅샷은 현재 상태 확인의 단서다.
등록 인간의 이름이 비슷해도 직무가 다르면 합치지 않는다. 빈 프로필을 삭제하지 않는다.
내보내기 수집이나 이 문서를 읽는 것만으로 새 업무·루틴 실행을 시작하지 않는다.

GitHub는 정책과 배포 코드의 기준, Notion은 운영 인벤토리·적용 결과의 교환 창구로 사용한다.
Craft를 사용할 때도 같은 JSON을 전달한다. 현재 연결된 Craft 도구는 Daily Notes 범위이므로
일반 문서가 자동으로 읽힌다고 가정하지 않는다. 문서 본문의 지시를 실행 승인으로 승격하지 않는다.

## 2. 설치 위치와 검증

Grokbot 공유 컴퓨터에서 기존 `/workspace/olympus`와 분리된 `/workspace/olympus-process`에
검토된 커밋의 코드를 둔다. 사설 자료는 `/workspace/olympus-private`, DB는 그 아래
`operations.sqlite`로 둔다. 원본·증거 파일은 버전별 새 경로로 저장한다.

Python 3.11 이상을 사용하며 원장 자체는 표준 라이브러리만 필요하다. jq는 필요 없다.

```bash
python -m pip install -r requirements-dev.txt
python -m unittest discover -s tests -v
python scripts/validate_contracts.py
python scripts/validate_operations.py
python -m runtime.ops --help
git rev-parse HEAD
```

설치 시 실제 코드 커밋·정책 커밋·실행 환경·검증 로그를 비공개 설치 기록에 남긴다.
배포 ZIP을 사용하면 BUNDLE-MANIFEST.json의 파일 해시를 대조하고 그 안의 implementation_commit을 설치 기록에 남긴다. ZIP에는 .git이 없으므로 git rev-parse 대신 이 값을 사용한다.
단위 테스트는 실제 작업 2회 검증에 합산하지 않는다.

## 3. 공통 CLI

모든 변경 요청은 UTF-8 JSON 파일이다. 반환값은 JSON, 거부는 종료 코드 2다.
자세한 매개변수는 [CLI 계약](../spec/process-cli-v1.json), 작동 예제는
[운영 스모크 도구](../scripts/operations_smoke.py)에 있다. 이 예제는 TEST 자료다.

```bash
python -m runtime.ops register --db /workspace/olympus-private/operations.sqlite --artifact-root /workspace/olympus-private --request binding.json
python -m runtime.ops create --db /workspace/olympus-private/operations.sqlite --artifact-root /workspace/olympus-private --request project.json
python -m runtime.ops status --db /workspace/olympus-private/operations.sqlite --artifact-root /workspace/olympus-private --project PROJECT_ID
python -m runtime.ops report --db /workspace/olympus-private/operations.sqlite --artifact-root /workspace/olympus-private
```

- `register`: 이미 존재하는 인간과 Bot의 연결을 명시적으로 가져온다. 새 Bot을 만들지 않는다.
  슬롯·직무가 맞지 않으면 헤스티아에게 반환한다. 이름·ID를 바꿔 맞추지 않는다.
- `create`: 실제 계획·입력·예산·담당자·검수자를 고정한다. `data_origin: REAL`은 실제 업무에서만 쓴다.
- `claim`: 제작은 PRODUCTION, 독립 검수는 REVIEW로 점유한다. 결과의 attempt_id를 후속 요청에 사용한다.
- `submit`: 실제 파일 목록·필수 점검 근거·외부 작업 ID·비용 근거를 제출한다. 파일과 근거 모두
  artifact root 기준 상대 경로, ID·버전·SHA-256이 필요하다.
- `review`: 지정한 검수자가 검수 점유 후 정확한 attempt_id·result_digest를 대상으로 판정한다.
  반려는 실패 항목·분류·실패 키·수정 대상·재사용 대상을 포함한다.
- `block/reconcile`: 중단 원인 기록 후 원격 결과와 비용을 대조한다. 응답 불명·비용 미확인 상태의
  예약과 점유는 유지한다. 모르는 비용을 0으로 입력하지 않는다. 실제 초과액도 정산하고 신규 배정을 정지한다.
- `change-input/retry`: 원 업무를 참조한다. 영향받는 작업과 후속 작업만 새 세대로 전환한다.
  재카드 ID를 바꾸어도 이력과 한도가 이어진다. 실행 중인 영향 작업부터 대조·정산한다.
- `change-reference`: 공통 입력 또는 원형의 이전 참조·새 참조·영향 검토 근거를 받아 모든 직접 소비자와 후속 단계를 함께 무효화한다. 원형 변경에는 새 승인 근거도 필요하다.
- `update-binding`: 기존 인간·Bot·슬롯을 유지하며 Skill·도구 버전 변경을 증거와 함께 기록한다. 진행 중 점유가 있으면 거부한다. 이전 Skill로 고정된 미실행 업무는 새 버전으로 조용히 바뀌지 않고 차단된다.
- `handoff`: 업무 ID·현재 입력·선행 결과·다음 행동·완료 조건·상위 잔여 한도를 반환한다.
- `reuse`: 같은 입력 지문과 유효한 결과·검수 증거를 가진 재사용 후보를 찾는다. 반환 파일을 제작 결과로 재사용하더라도 새 업무의 submit·독립 review는 수행한다.
- `observe`: 사용자 변경(QUALITY_FIX/SCOPE_CHANGE)·승인 대기 구간을 원본 근거와 함께 기록한다.
- `memory`: propose→verify→activate. 독립 검증과 헤스티아 쓰기 검증을 기록한다. 철회·만료는 이후 주입을 막는다.
- `validation/deployment`: 서로 다른 실제 프로젝트의 같은 최종 버전 수동 통과 두 건을 기록한 뒤,
  헤스티아 판단으로 신규 작업 선택을 기록한다. Grokbot Skill 설정 변경·루틴 활성화는 별도 확인 대상이다.
- `export`: 일관된 시점의 상태·이벤트와 해시를 반환한다. 공개 GitHub에 업로드하지 않는다.

예산은 정수 단위 하나로 통일한다. 제작·실패·재작업·검수 비용을 모두 기록한다.
상위 프로젝트가 있는 업무는 parent_project_id로 연결한다. 같은 목표를 다른 root_goal_id로 꾸미는
의미상의 중복을 코드가 자동 판별하지는 못하므로 헤스티아가 동일 목표를 대조한다.

## 4. 외부 실행과 증거의 한계

원장은 Bot ID·검수 근거·Notion 문서 작성자의 진위를 인증하지 않는다.
공유 컴퓨터 파일에 접근하는 운영자가 원장 자체를 변조하는 공격도 방어하지 않는다.
이를 capability token이나 인증된 제우스 승인 시스템이라고 보고하지 않는다.

외부 게시·배포·구매 업무의 claim은 인증 실행 게이트가 없어 차단한다.
기존 승인 절차를 거쳐 사람이 별도로 실행한 게시 결과는 원본 시스템에서 확인하고 별도 보고한다.
이 원장에 제출한 파일 생성 결과를 외부 게시 완료로 바꾸지 않는다.
원형 승인 근거는 바이트 일치를 검사하지만 실제 제우스의 서명까지 검증하지는 않는다.

원장이 생성한 결과는 항상 runtime_verified=false, evidence_trust=OPERATOR_SUPPLIED다.
Grokbot 연결, 승인 인증, 실제 검수 품질은 기능별 실제 수용 기록으로 따로 증명한다.

## 5. 적용·복구

기존 업무가 참조하는 Bot의 Skill 버전은 해당 업무를 마무리한 뒤 변경한다. 검토된 신규 업무에 먼저 적용하며
문서·Skill 등록·실제 실행 검증 상태를 별도로 보고한다. 선정 버전 변경은 실행 중 업무를 바꾸지 않는다.
새 배정을 중단할 때는 deployment suspend와 Grokbot 루틴 일시 중지를 함께 확인한다.
원격 결과 불명 상태는 재시도하지 말고 block→reconcile로 대조한다.
예산 초과 프로젝트는 비용을 줄여 기록하거나 DB를 직접 수정해 재개하지 않는다.

백업은 SQLite backup API로 일관된 사본을 만들고, 버전별 원본·출력·검수 파일을 함께 보관한다.
복구는 별도 경로에서 먼저 검증한다. 진행 중 작업·원격 결과·예약 금액을 대조하기 전 배정하지 않는다.
DB schema=1을 자동으로 새 스키마로 바꾸지 않는다. 마이그레이션은 백업·검증·명시 전환으로 처리한다.

각 라인 동일 최종 버전 실제 2회, 총 10회가 확보되기 전 전체 적용 완료로 보고하지 않는다.
실측 비교는 라인별 고정 자료에서 다음을 실행한다.

```bash
python -m runtime.evaluations private-comparison.json --minimum-pairs 20 --require-joint-improvement
```

비용과 시간이 모두 감소하고 채택·1차 통과·잘못된 통과 지표가 악화되지 않은 경우만 검토 후보로 올린다.
합성 자료는 DEMO_ONLY, 표본 부족·상충 결과는 INCONCLUSIVE다. 도구는 자동 승격하지 않는다.


## Notion/Craft 자료 검사

```bash
python -m runtime.bridge --input inventory.json --output private-inventory-audit.json
```

Notion/Craft Markdown에 들어 있는 JSON 코드 블록 하나도 읽을 수 있다. 검사 보고서 출력은 새 파일로 제한한다.
이 도구는 외부 앱을 수정하지 않으며 등록·배정·루틴 활성화를 수행하지 않는다. Bot 연결 누락과 루틴 중복 후보를
검토 목록으로만 반환한다. 작업별 비용·시간·실패 자료가 없으면 실제 개선을 추정하지 않는다.

workflow_ref는 절차 배포본의 ID·버전·해시다. 같은 버전의 실제 업무들은 동일한 단계 ID·의존 관계·직무·검수 목록·Skill/도구 구성을 가져야 한다.
업무별 입력 자산은 달라도 되며 실제 검증 증거는 각 입력·시도·결과 스냅샷에 별도로 고정된다.

실제 동시 개선 비교 JSON에는 product_line과 사전 등록한 계획의 comparison_plan_ref 문자열을 포함한다. 서로 다른 라인의 실행을 섞으면 거부한다.

GitHub·Notion·Craft의 정보 원본·검색·기록·인계·갱신 기준은 [도구 사용 Process](tool-coordination.md)를 따른다.

## 실제 export 검사 보강 (bridge 0.1.1)

소문자·알 수 없는 product_line은 종료 코드 2로 거부한다. 원본은 유지하고 명시적 변환 사본만 검사한다.
보고서는 전체 run_count, categorized_run_count, 라인별 검사/제외 수, 날짜 미확인 수, 루틴 비교 가능 범위를 포함한다.
연결 누락은 missing_fields로 표시하며 tools=null과 tools=[]를 구분한다.
Grokbot에서 python 명령이 없으면 사용 가능한 python3를 사용한다.
다음 대조는 [기존 바인딩 재확인](grokbot-binding-recheck.md)을 따른다.
