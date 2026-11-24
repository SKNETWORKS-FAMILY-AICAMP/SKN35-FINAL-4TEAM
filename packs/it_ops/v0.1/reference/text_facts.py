"""임시 쓰기 검사에서 문구 전체 대신 버전·생성 번호의 필수 사실을 비교한다."""

import re

VERSION = r"(?<![A-Za-z0-9_.+-])v\d+(?:\.\d+)+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?(?![A-Za-z0-9_.+-])"


def text_facts_match(actual, expected):
    if not isinstance(actual, str) or not actual.strip():
        return False
    versions = set(re.findall(VERSION, expected))
    if not versions or set(re.findall(VERSION, actual)) != versions:
        return False
    refs = set(re.findall(r"#(\d+)", expected))
    if refs:
        remainder = re.sub(VERSION, "", actual)
        if set(re.findall(r"(?<!\d)#?(\d+)(?!\d)", remainder)) != refs:
            return False
    return True
