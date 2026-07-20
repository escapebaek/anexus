# Journal Stand 앱 사용법

과 구성원 전용 학술지 열람 기능. 구조: Journal(학술지) -> Issue(호) -> Paper(논문).
논문 PDF는 Backblaze B2(private)에 저장되고, 로그인 + 승인된 사용자에게만 짧은 유효시간의
서명 URL로 열람/다운로드를 제공한다. Journal/Paper의 표지는 파일 업로드가 아니라
**외부 이미지 URL을 붙여넣는 방식**(`cover_image_url`)이다 (Supabase storage 업로드 경로에서
원인 불명의 실패가 있어 더 간단하고 안정적인 방식으로 대체함. 자세한 배경은 6번 참고).

## 1. 화면 구조

- `/journal/` : 학술지 목록 (매거진 스탠드 그리드)
- `/journal/<journal-slug>/` : 해당 학술지의 최신호 논문 목록 (제목 + short_summary 미리보기)
- `/journal/<journal-slug>/issue/<issue-id>/` : 특정(지난) 호 논문 목록
- `/journal/paper/<paper-id>/` : 논문 상세 (좌: PDF 리더 iframe, 우: ai_summary 전체 요약 + 다운로드 버튼)

접근 제어: 모든 뷰가 `@login_required` + `@user_is_approved` (accounts/decorators.py). 로그인 + 승인된
계정만 접근 가능.

## 2. Admin에서 수동으로 관리하기

`/admin/` 접속 후:

1. **Journal** 추가: 이름 입력하면 slug 자동 생성(직접 확인/수정 가능), `is_active` 체크해야 스탠드
   화면에 노출됨. Cover Image URL은 파일 업로드가 아니라 **이미지 주소(링크)를 붙여넣는 칸**임 (예:
   저널 공식 홈페이지의 표지 이미지 링크, 이미지 호스팅 서비스 링크 등). 비워두면 책 아이콘 placeholder가 뜸.
2. Journal 안의 인라인에서 **Issue** 추가: volume/number/발행일 입력. number는 비워도 됨(비우면 나중에
   bulk import 시 issue 참조 문자열이 `slug:volume:` 처럼 끝에 콜론만 붙는 형태가 되니 주의).
3. Issue 안의 인라인에서 **Paper** 추가: title/authors/short_summary/ai_summary/cover_image_url/pdf_file/order
   직접 입력 가능 (cover_image_url도 Journal과 마찬가지로 링크 붙여넣기 방식). 논문 한두 개만 추가할 땐
   이 방법이 제일 간단함.

논문이 많을 땐 아래 3번 bulk import 명령을 쓰는 게 훨씬 편함.

## 3. Backblaze B2 저장소 설정 (최초 1회)

`.env`(로컬) / Render 대시보드 Environment 탭(운영)에 아래 값 등록:

```
B2_KEY_ID=<Application Key ID>
B2_APPLICATION_KEY=<Application Key>
B2_BUCKET=<버킷 이름, 예: anexus-papers>
B2_ENDPOINT_URL=https://s3.<region>.backblazeb2.com
B2_REGION=<region, 예: us-west-004>
```

- B2 버킷은 반드시 **Private**로 생성 (Public으로 하면 카드 등록을 요구함).
- App Key는 해당 버킷에만 Read/Write 권한으로 발급.
- 값이 비어 있어도 사이트 자체는 정상 부팅됨. 다만 논문 업로드/열람 기능만 동작 안 함.

값 설정 후 모델/코드는 안 건드려도 됨 (`anhub/storage_backends.py`의 `PaperStorage`, `generate_paper_url`이
이 설정을 그대로 사용).

## 4. 논문 일괄 업로드 (import_papers 명령)

### 4-1. 준비: PDF + 짝꿍 텍스트 파일

폴더 하나에 논문마다 `파일명.pdf`와 `파일명.txt`를 같은 이름으로 짝지어 넣는다.

```
C:\papers\vol1_no1\
  01_paper.pdf
  01_paper.txt
  02_paper.pdf
  02_paper.txt
```

파일명 앞에 `01_`, `02_` 처럼 번호를 붙이면 그 순서 그대로 화면 노출 순서(order)가 매겨진다.
(안 붙이면 알파벳/숫자 순으로 처리됨)

`.txt` 파일 형식:

```
Title: <영어 논문 제목>
Authors: <저자, 콤마로 구분>
Summary: <한 줄 요약, 이슈 논문 목록에 미리보기로 노출>
===
<3~5문단 전체 요약, 논문 상세 페이지에 노출>
```

`.txt`가 아예 없으면 파일명이 제목으로 쓰이고 저자/요약은 빈 채로 등록됨(급하게 먼저 PDF만 올려두고
싶을 때 이렇게 해도 됨. 나중에 admin에서 텍스트만 채워 넣으면 됨).

마크다운 볼드(`**Title:**`)나 구분선으로 `---`를 써도 자동으로 인식하므로, Claude 채팅 답변을
그대로 복사해서 붙여넣어도 된다.

### 4-2. Claude(구독)에게 요약 요청할 때 쓸 프롬프트

```
첨부한 논문을 요약해줘. 답변은 다른 설명 없이 아래 형식 그대로만 출력해줘:
Title: <영어 논문 제목>
Authors: <저자, 콤마로 구분>
Summary: <핵심을 담은 한 문장 요약>
===
<3~5문단 전체 요약>
```

Claude 답변을 통째로 복사해서 해당 PDF와 같은 이름의 `.txt`로 저장하면 됨.

### 4-3. 대상 issue 확인

```
python manage.py import_papers --list-issues
```

등록된 모든 issue의 `id`와 `journal-slug:volume:number` 참조 문자열을 보여줌. 이 중 하나를
`--issue` 값으로 그대로 쓰면 됨. **id 숫자를 쓰는 게 제일 간단하고 실수가 적음** (number가 비어있는
issue는 참조 문자열 끝에 콜론만 남아 헷갈리기 쉬움).

예: `id=1  --issue "bja:137:2"   (BJA Volume 137 Issue 2)`
- `--issue "bja:137:2"` = 실제 매칭에 쓰이는 값 (volume/number 원본 그대로 조합)
- `(BJA Volume 137 Issue 2)` = 사람이 보기 좋은 설명 문구일 뿐(`Issue.__str__`). 이 표기 형식이
  바뀌어도(예: Vol./No. -> Volume/Issue) `--issue` 문자열 자체는 영향받지 않음.

### 4-4. 미리보기 (dry-run)

```
python manage.py import_papers "C:\papers\vol1_no1" --issue 1 --dry-run
```

실제로 저장/업로드하지 않고, 각 PDF가 어떤 제목/저자로 인식되는지, 이미 같은 제목이 있어서
건너뛰어질 것들, `.txt`나 요약이 없는 파일에 대한 경고를 미리 보여줌. 마지막 줄에 최종
issue 이름(`Dry run: would import N new paper(s), skipped M already-existing, into <issue 이름>`)이
나오니 원하는 저널/호가 맞는지 여기서 한 번 더 확인.

### 4-5. 실제 실행

```
python manage.py import_papers "C:\papers\vol1_no1" --issue 1
```

- PDF는 B2로 업로드되고, Paper 레코드가 생성됨.
- **같은 issue 안에 제목이 이미 존재하면 자동으로 건너뜀** (재업로드해도 중복 안 생김). 논문 몇 개를
  깜빡했을 때 전체 다시 넣어도 안전함.
- 정말 의도적으로 같은 제목을 다시 넣고 싶으면 `--force` 추가.
- order는 해당 issue의 기존 최대값 다음부터 자동으로 이어붙음.

## 5. 자주 만나는 에러

- **`No issue found for journal 'x' volume 'y' number 'z'`**: `--issue`에 넣은 slug:volume:number가
  실제 값과 다름. `--list-issues`로 정확한 값 확인하거나 그냥 id 숫자를 쓸 것.
- **`column "..." of relation "journal_paper" does not exist`**: 모델(migrations)은 바뀌었는데
  실제 DB에 `python manage.py migrate`를 아직 안 돌린 것. migrate 먼저 실행.
- **`ModuleNotFoundError: No module named 'boto3'` (또는 다른 패키지)**: 실제 사용 중인 가상환경에
  `pip install -r requirements.txt`가 아직 반영 안 된 것.
- **PDF 리더/다운로드가 안 뜸**: B2 환경변수(`B2_KEY_ID` 등)가 비어있거나 틀림. 설정 확인.

## 6. 참고: 필드 요약

| 필드 | 위치 | 용도 |
|---|---|---|
| `Journal.name / slug / description / cover_image_url / is_active / order` | 학술지 목록 카드 | is_active 꺼두면 스탠드에서 숨김. cover_image_url은 파일 업로드가 아니라 외부 이미지 링크 |
| `Issue.volume / number / publish_date` | 호 정보 | 화면/문자열 표기는 "Volume {volume} Issue {number}" (예: BJA Volume 137 Issue 2). 최신호는 publish_date가 가장 최근인 것으로 자동 결정 |
| `Paper.title / authors / short_summary / ai_summary / cover_image_url / pdf_file / order` | 논문 | short_summary = 목록 미리보기(1줄), ai_summary = 상세페이지 전체 요약, cover_image_url = 있을 때만 목록에 작은 표지 썸네일 표시 (역시 외부 이미지 링크 방식) |

### 왜 표지는 파일 업로드가 아니라 URL 방식인가
원래는 Journal/Paper 표지도 논문 PDF와 마찬가지로 파일 업로드(Django ImageField, 기존 Supabase storage
경유)로 만들었는데, admin에서 업로드하면 에러 없이 "성공적으로 변경했습니다"라고 뜨고 DB에도 파일 경로가
저장되는데 정작 Supabase 버킷에는 파일이 전혀 생성되지 않는 원인 불명의 문제가 있었다. 버킷이 Public인 것도,
경로/버킷 이름이 맞는 것도 다 확인했지만 원인을 못 찾아서, 더 간단하고 확실한 방식(외부 URL 붙여넣기)으로
대체했다. 표지 이미지는 어차피 저널 홈페이지나 이미지 호스팅 서비스에 이미 있는 경우가 많아서 이 방식이
실용적이기도 함. (논문 PDF는 이 문제와 무관 - B2 업로드는 별도 코드 경로라 정상 동작.)

## 7. 코드 위치

- 모델/뷰/URL: `journal/models.py`, `journal/views.py`, `journal/urls.py`, `journal/admin.py`
- 템플릿: `journal/templates/journal/`
- B2 저장소 백엔드 + 서명 URL 발급: `anhub/storage_backends.py` (`PaperStorage`, `generate_paper_url`)
- 일괄 업로드 명령: `journal/management/commands/import_papers.py`
