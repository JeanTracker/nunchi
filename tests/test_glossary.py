"""번호 풀이 (요구 이력 51, REQUIREMENTS R1·R17): 응답의 기획 번호를 프로젝트 문서 원문으로."""

import pytest

from control_tui import glossary

from tests.test_flow_view import app_for, make_session, ready, text_of

REQ = """# 요구사항: 시험
| ID | 요구사항 | 근거 요청 | 완료 기준 |
| --- | --- | --- | --- |
| R1 | 대화를 본다 | 1 | 보인다 |
| R4 | ~~도구를 본다~~ (없앰) | 3 | – |
| R17 | 세션 안에서 되짚는다 | 41 | 패널 |

| 차례 | 요청 핵심 | 바뀐 점 |
| --- | --- | --- |
| 1~3 | 기억 시각화 | 출발점 |
| 41 | 관제와 mod를 나눠 정리하자 | R17 |
| 46 | 6,000자 상한 없애기 | R8 |
| 46 | dockColumns 지우기 | R17 |
"""
SCREEN = "# 화면구성: 시험\n\n## 8. 확인 결과\n\n## 11. 세션 안 화면 (mod)\n"
PLAN = "# 구현 계획: 시험\n\n## 8. 테스트\n\n### 4.5 에이전트가 묻는 것\n\n| Phase | 할 일 |\n| --- | --- |\n| 4c. 요청 기록 기억 관점 | x |\n"


@pytest.fixture
def project(tmp_path):
    d = tmp_path / "proj" / "docs"
    d.mkdir(parents=True)
    (d / "REQUIREMENTS.md").write_text(REQ, encoding="utf-8")
    (d / "SCREEN.md").write_text(SCREEN, encoding="utf-8")
    (d / "BUILD_PLAN.md").write_text(PLAN, encoding="utf-8")
    return tmp_path / "proj"


def means(got):
    return {it["id"]: it["means"] for it in got["items"]}


def test_ids_with_korean_particles_are_found_in_order_once():
    text = "R17까지 바꾸고 R4도 보며, 구현 계획 §4.5를 고쳤고 다시 R17을. Phase 4c와 요구 이력 41을, R1~R16. BR2 아님"
    assert glossary.find(text) == ["R17", "R4", "§4.5", "Phase 4c", "요구 이력 41", "R1~R16"]


def test_meanings_come_verbatim_from_project_docs(project):
    got = glossary.explain("R17과 R4, 요구 이력 41, Phase 4c, 요구 이력 2", project, limit=9)
    m = means(got)
    assert m["R17"] == ["세션 안에서 되짚는다"]
    assert m["R4"] == ["도구를 본다 (없앰)"]                    # 줄 긋기 표시는 뺀다
    assert m["요구 이력 41"] == ["관제와 mod를 나눠 정리하자"]
    assert m["Phase 4c"] == ["요청 기록 기억 관점"]
    assert m["요구 이력 2"] == ["기억 시각화"]                 # 1~3 범위 줄


def test_same_number_with_two_meanings_shows_both_and_unknown_is_empty(project):
    m = means(glossary.explain("요구 이력 46과 R99", project))
    assert m["요구 이력 46"] == ["6,000자 상한 없애기", "dockColumns 지우기"]
    assert m["R99"] == []                                         # 화면에서 '문서에 없음'


def test_section_number_follows_the_doc_named_before_it(project):
    m = means(glossary.explain("화면 문서 §8과 §11, 구현 계획 §4.5", project))
    assert m["§8"] == ["화면구성: 확인 결과"]                     # 구현 계획 §8(테스트)은 빼고
    assert m["§11"] == ["화면구성: 세션 안 화면 (mod)"]
    assert m["§4.5"] == ["구현 계획: 에이전트가 묻는 것"]


def test_no_docs_means_no_glossary(tmp_path):
    assert glossary.explain("R17", tmp_path) == {"items": [], "total": 0}


def test_limit_counts_the_rest(project):
    got = glossary.explain("R1 R4 R17 §8 §11 §4.5 요구 이력 41", project)
    assert len(got["items"]) == 5 and got["total"] == 7


@pytest.mark.asyncio
async def test_control_shows_glossary_under_the_last_answer(tmp_path, project):
    home, _, _ = make_session(tmp_path, n=2, last_answer="mod 화면 요구(R17)를 새로 만들고 화면 문서 §11을 썼습니다.")
    app = app_for(home)
    async with app.run_test(size=(160, 46)) as pilot:
        await ready(app, pilot)
        app.conversation.view.cwd = str(project)
        app.conversation.refresh_content()
        await pilot.pause()
        text = text_of(app)
        assert "번호 풀이  이번 응답 · 문서 원문" in text
        assert "R17" in text and "세션 안에서 되짚는다" in text
        assert "화면구성: 세션 안 화면 (mod)" in text
