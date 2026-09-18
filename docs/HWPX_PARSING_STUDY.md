# HWPX 파싱 함께 공부하기: 1단계

## 이번 단계에서 실제로 만든 것

`read_document(path) -> str`의 interface는 유지했다. `.hwpx`도 HWP CLI가 구조화 Markdown으로 추출하고, 기존 표·각주·이미지 보강과 조·항 청킹을 통과한다. HWP 5.0 바이너리 파서를 새로 작성한 것은 아니다. HWPX의 내부 구조를 이해한 뒤 필요한 정보가 Markdown에서 빠지는 경우에만 더 깊은 구조 파서를 추가한다.

## 실습 1: ZIP 패키지를 열어보기

```powershell
python -m zipfile -l tests/fixtures/mixed_rich_policy.hwpx
$env:HWP_CLI_PATH = "C:\path\to\hwp.exe"
& $env:HWP_CLI_PATH info tests/fixtures/mixed_rich_policy.hwpx
```

HWPX는 ZIP 안에 `Contents/content.hpf`, `Contents/header.xml`, `Contents/section0.xml` 등으로 나뉜다. 파일 이름만 보고 읽기 순서를 가정하지 말고 `content.hpf`의 spine을 확인한다. [한컴의 HWPX 구조 설명](https://tech.hancom.com/hwpxformat/)에도 패키지와 spine 순서가 설명되어 있다.

```python
from zipfile import ZipFile
import xml.etree.ElementTree as ET

with ZipFile("tests/fixtures/mixed_rich_policy.hwpx") as package:
    root = ET.fromstring(package.read("Contents/content.hpf"))
    order = [
        node.attrib["idref"]
        for node in root.iter()
        if node.tag.rsplit("}", 1)[-1] == "itemref"
    ]
    print(order)  # ['header', 'section0']; manifest의 id → href로 연결한다.
```

## 실습 2: 텍스트만 뽑았을 때 무엇이 빠지나

```python
from zipfile import ZipFile
import xml.etree.ElementTree as ET

with ZipFile("tests/fixtures/mixed_rich_policy.hwpx") as package:
    section = ET.fromstring(package.read("Contents/section0.xml"))
    text = " ".join(
        node.text or ""
        for node in section.iter()
        if node.tag.rsplit("}", 1)[-1] == "t"
    )
    print(text)
```

이 합성 파일에서 텍스트 노드만 이어 붙이면 231자가 나오지만, HWP CLI의 Markdown 추출은 334자다. 텍스트만 읽는 결과에는 목록의 `1.`·`2.` 번호, `[^1]` 각주 참조, 표의 열·값 관계가 없다. 그러므로 XML의 글자만 읽는 방식은 규정 RAG의 근거 추출기로 충분하지 않다. [사용자가 공유한 글](https://dbhyeong.github.io/blog/hwp-hwpx-format-parsing-python)은 형식 입문 자료로 유용하지만, 글의 간단한 추출 방식을 그대로 운영 파서로 쓰지 않는다.

## 실습 3: 현재 입력 경로와 다음 단계

```text
.hwp 또는 .hwpx
→ HWP CLI cat/convert
→ 표·번호·각주·이미지 보강
→ 조·항 청킹
→ 항 벡터 색인과 조 출처
```

이번 합성 HWP를 HWPX로 엄격 변환했을 때 HWP CLI의 Markdown 출력은 동일했다. 이미지도 `convert --media-dir`로 추출됐고, 테스트 대역 OCR을 넣은 결과 4개 조의 표·각주·이미지 내용이 해당 조에 남았다. 같은 도구가 변환과 추출을 수행했으므로 실제 사내 HWPX 전체에 대한 보장은 아니다.

다음 학습에서는 `hwp cat --format json`의 구조와 HWPX `section*.xml`을 나란히 보며 **표 셀, 번호 정의, 각주 참조, 그림과 캡션**을 잃지 않는 중간 구조를 정의한다. 원본 XML의 순서와 출처를 보존한 뒤 기존 조·항 청커에 연결할지 결정한다.
