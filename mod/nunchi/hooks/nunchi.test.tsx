import { expect, test, mock } from 'claude-code/testing'
import { answersAfter, answerEnded, promptSent, humanPrompt, paneClosed, paneAsked, mayAutoOpen, pieces as piecesOf } from './register.js'
import { pick, norm, failText } from './lang.js'

// SCREEN §11: 관제 분석 결과를 읽어 세션 옆 패널에 보인다
const ANALYSIS = {
  last_turn: 3,
  flow: {
    version: 3,
    until: 3,
    current_goal: { text: 'CHANGELOG 만들기', turn: 3 },
    steps: [
      { index: 1, grounded: true, label: '시작', summary: 'README 설치 절', agent_summary: '설치 절 추가', digest: 'README 설치 절을 요청함' },
      { index: 2, grounded: true, label: '확정', summary: '설치 절 확정', agent_summary: '확정함', title: '설치 절 확정' },
      { index: 3, grounded: true, label: '구체화', summary: 'CHANGELOG 요청', agent_summary: 'CHANGELOG를 만들고 폭을 물음', shift: true, digest: '설치 절을 정한 뒤 CHANGELOG를 요청함' },
    ],
    requests: [
      { id: 'R1', from_turn: 1, summary: '설치 절 추가', state: 'addressed', tool_failed: true },
      { id: 'R2', from_turn: 3, summary: '테스트 돌리기', state: 'deferred' },
    ],
    asks: [
      { id: 'Q1', turn: 1, last_turn: 1, summary: '색 고르기', quote: '색은 어느 쪽으로 할까요?', state: 'open' },
      { id: 'Q2', turn: 3, last_turn: 3, summary: '폭 정하기', quote: '폭은 몇 칸으로 할지 알려 주세요', state: 'partial' },
      { id: 'Q3', turn: 2, summary: '진행할지', quote: '진행할까요?', state: 'answered', by_blanket: true },
    ],
  },
}

const GLOSS = { turn: 3, total: 3, items: [
  { id: 'R17', means: ['세션 안(mod)에서 흐름을 빠르게 되짚고, 부족하면 관제로 간다'] },
  { id: '요구 이력 46', means: ['6,000자 상한 없애기', 'dockColumns 지우기'] },
] }

const PANE = {
  plugin: 'nunchi',
  component: 'Pane',
  requestId: 'nunchi',
  props: { title: '눈치', isFocused: false, bodyColumns: 50, placement: 'dock', scroll: { offset: 0, bodyRows: 30 }, view: {} },
} as const

// 패널 본문은 보통 글자로 그린다 (요구 이력 77: 키를 받는 본문은 없앰)
async function mountPane($: any, spec: any) {
  return $.ui.mount(spec)
}

function engine(on: any, status: unknown, want = false, analysis: unknown = ANALYSIS, events = '', files: Record<string, string> = {}) {
  on('command.register', () => ({ value: { command: 'nunchi' } }))
  on('ui.open', () => ({ value: { isPlaced: true } }))
  on('session.start', (_: unknown, e: any) => ({ cwd: e.cwd }))
  on('session.id', () => ({ value: 'abc' }))
  on('settings.read', () => ({ value: { language: '한국어' } }))   // Claude Code 언어 설정 (요구 이력 76): 기존 시험은 한국어 화면
  on('env.get', (_: unknown, e: any) => ({ value: e.name === 'HOME' ? '/home/me' : undefined }))
  on('clock.every', () => ({ value: null }))
  on('clock.now', () => ({ value: 1000 }))
  on('fs.read', (_: unknown, e: any) => {
    const p = String(e.path ?? e)
    for (const [end, text] of Object.entries(files)) if (p.endsWith(end)) return { value: text }
    if (p.endsWith('/sessions/abc/analysis.json')) return { value: JSON.stringify(analysis) }
    if (p.endsWith('/sessions/abc/analysis_status.json')) return { value: JSON.stringify(status) }
    if (p.endsWith('/sessions/abc/glossary.json')) return { value: JSON.stringify(GLOSS) }
    if (p.endsWith('/sessions/abc/want') && want) return { value: '{"at":"x"}' }
    if (p.endsWith('/sessions/abc/events.jsonl') && events) return { value: events }
    throw new Error('missing ' + p)
  })
}

test('the sections come in the order goal, decisions, questions, requests (요구 이력 71)', async ($, on) => {
  engine(on, { state: 'idle', turn: 0 })
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  const ui = await mountPane($, { ...PANE, surface: 'terminal' })
  // 요구 이력 87·89: 처리 결과가 결정 사항과 에이전트 질문 사이, 이름은 두 낱말이라 통째로 읽는다
  const heads = (await ui.findAll({ type: 'Text', text: /^(목표|결정 사항|처리 결과|에이전트 질문|남은 요청)(\s|$)/ }))
    .map(t => (String(t.text).match(/^(목표|결정 사항|처리 결과|에이전트 질문|남은 요청)/) ?? [''])[0])
  expect(heads.filter((h, k) => heads.indexOf(h) === k)).toEqual(['목표', '결정 사항', '처리 결과', '에이전트 질문', '남은 요청'])
  for (const old of [/에이전트가 묻는 것/, /^지금까지/, /정한 것/, /^남은 것/]) {
    expect((await ui.find({ type: 'Text', text: old }))).toBeFalsy()
  }
  await ui.unmount()
})

test('the pane shows the goal, decisions, the agent\'s questions and open requests (요구 이력 71)', async ($, on) => {
  engine(on, { state: 'idle', turn: 0 })
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  const ui = await mountPane($, { ...PANE, surface: 'terminal' })
  // 요구 이력 86: 마지막 응답(#3)이 물은 것만 펼쳐 보이고, 그 전에 물은 것은 '지난 질문'으로 접는다
  expect((await ui.find({ type: 'Text', text: /^에이전트 질문 1$/ }))).toBeTruthy()
  expect((await ui.find({ type: 'Text', text: /1 폭 정하기 #3 · 일부 답함/ }))).toBeTruthy()
  expect((await ui.find({ type: 'Text', text: /색 고르기/ }))).toBeFalsy()
  expect((await ui.find({ type: 'Button', key: 'more-asks' }))?.text).toBe('지난 질문 1개')
  await ui.press({ key: 'more-asks' })
  expect((await ui.find({ type: 'Text', text: /2 색 고르기 #1$/ }))).toBeTruthy()          // 펼치면 지난 질문이 같은 꼴로
  expect((await ui.find({ type: 'Text', text: /“폭은 몇 칸으로 할지 알려 주세요”/ }))).toBeTruthy()
  expect((await ui.find({ type: 'Text', text: /통째 승인/ }))).toBeFalsy()   // 내용·턴 없는 내부 용어 줄은 두지 않는다 (요구 이력 82)
  expect((await ui.find({ type: 'Text', text: /흐름\s+#1–#3/ }))).toBeTruthy()             // 처음부터 한 덩어리 정리 (요구 이력 57)
  expect((await ui.find({ type: 'Text', text: /^\s+설치 절을 정한 뒤 CHANGELOG를 요청함$/ }))).toBeTruthy()
  expect((await ui.find({ type: 'Text', text: /README 설치 절을 요청함/ }))).toBeFalsy()   // 마지막 정리 하나만
  expect((await ui.find({ type: 'Text', text: /^목표\s+#3부터$/ }))).toBeTruthy()            // 덩어리 이름 줄 (요구 이력 71)
  expect((await ui.find({ type: 'Text', text: /^\s+CHANGELOG 만들기$/ }))).toBeTruthy()      // 다음 줄에 들여 쓴 내용
  expect((await ui.find({ type: 'Text', text: /^결정 사항 1$/ }))).toBeTruthy()
  expect((await ui.find({ type: 'Text', text: /✔ 설치 절 확정\s+#2/ }))).toBeTruthy()       // 정한 턴을 붙인다
  expect((await ui.find({ type: 'Text', text: /CHANGELOG를 만들고 폭을 물음/ }))).toBeFalsy()      // 방금은 목표에서 뺐다 (요구 이력 87)
  expect((await ui.find({ type: 'Text', text: /^처리 결과 #3$/ }))).toBeTruthy()                   // 마지막 턴(#3)에 생긴 내 요청 (요구 이력 87·88)
  expect((await ui.find({ type: 'Text', text: /^ ⊘ 테스트 돌리기$/ }))).toBeTruthy()
  expect((await ui.find({ type: 'Text', text: /테스트 돌리기 — 못 했거나 미룸/ }))).toBeTruthy()
  expect((await ui.find({ type: 'Text', text: /도구 실패/ }))).toBeFalsy()          // 도구 실패는 보이지 않는다 (요구 이력 48)
  expect((await ui.find({ type: 'Text', text: /대화 정리/ }))).toBeFalsy()          // 턴별 목록은 두지 않는다
  await ui.unmount()
})

test('a session with only its first turn analyzed shows the goal without a flow summary', async ($, on) => {
  const first = { ...ANALYSIS, last_turn: 1, flow: { ...ANALYSIS.flow, until: 1, steps: ANALYSIS.flow.steps.slice(0, 1) } }
  engine(on, { state: 'idle', turn: 0 }, false, first)
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  const ui = await mountPane($, { ...PANE, surface: 'terminal' })
  expect((await ui.find({ type: 'Text', text: /흐름\s+#1/ }))).toBeFalsy()
  expect((await ui.find({ type: 'Text', text: /^목표/ }))).toBeTruthy()   // 목표가 덩어리 머리 줄이 됨 (요구 이력 71)
  await ui.unmount()
})

test('while the control analyzes, the head shows 분석 중', async ($, on) => {
  engine(on, { state: 'running', turn: 3 })
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  const ui = await mountPane($, { ...PANE, surface: 'terminal' })
  expect((await ui.find({ type: 'Text', text: /분석 중/ }))).toBeTruthy()
  await ui.unmount()
})

// 요구 이력 55: /nunchi로 켜지 않은 세션은 옛 결과가 더 이어지지 않는다고 머리 줄에 알린다
test('a session not turned on says automatic analysis is off', async ($, on) => {
  engine(on, { state: 'idle', turn: 0 })
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  const ui = await mountPane($, { ...PANE, surface: 'terminal' })
  expect((await ui.find({ type: 'Text', text: /자동 분석 꺼짐 · \/nunchi로 켜기/ }))).toBeTruthy()
  await ui.unmount()
})

test('a session turned on with /nunchi does not say it is off', async ($, on) => {
  engine(on, { state: 'idle', turn: 0 }, true)
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  const ui = await mountPane($, { ...PANE, surface: 'terminal' })
  expect((await ui.find({ type: 'Text', text: /#3 응답까지 반영/ }))).toBeTruthy()
  expect((await ui.find({ type: 'Text', text: /자동 분석 꺼짐/ }))).toBeFalsy()
  await ui.unmount()
})

test('on a narrow pane a cut handled line shows Expand, and Expand wraps it onto indented lines (요구 이력 80·88)', async ($, on) => {
  const quiet = { ...ANALYSIS, flow: { ...ANALYSIS.flow, requests: ANALYSIS.flow.requests.filter((r: any) => r.from_turn !== 3) } }   // 마지막 턴에 요청이 없으면 에이전트가 한 일 한 줄
  engine(on, { state: 'idle', turn: 0 }, true, quiet)
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  const ui = await mountPane($, { ...PANE, props: { ...PANE.props, bodyColumns: 24 }, surface: 'terminal' })
  const texts = async () => (await ui.findAll({ type: 'Text' })).map((x: any) => String(x.text ?? ''))
  let all = await texts()
  expect(all.filter(t => /^ · CHANGELOG/.test(t))).toEqual([' · CHANGELOG를 만들 …'])           // 기본은 한 줄, 넘치면 …
  expect(all.some(t => /물음/.test(t))).toBe(false)
  expect((await ui.find({ type: 'Button', key: 'text-handled' }))?.text).toBe('펼치기')
  await ui.press({ key: 'text-handled' })
  all = await texts()
  expect(all.some(t => /^ · CHANGELOG/.test(t) && !/…$/.test(t))).toBe(true)                     // 잘리지 않고
  expect(all.some(t => /^\s+.*물음$/.test(t))).toBe(true)                                        // 들여 쓴 다음 줄로
  expect((await ui.find({ type: 'Button', key: 'text-handled' }))?.text).toBe('줄이기')
  await ui.unmount()
})

test('the glossary of the last answer shows at the bottom', async ($, on) => {
  engine(on, { state: 'idle', turn: 0 })
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  const ui = await mountPane($, { ...PANE, surface: 'terminal' })
  expect((await ui.find({ type: 'Text', text: /번호 풀이/ }))).toBeTruthy()
  expect((await ui.find({ type: 'Text', text: /^ R17$/ }))).toBeTruthy()
  expect((await ui.find({ type: 'Text', text: /세션 안\(mod\)에서 흐름을 빠르게/ }))).toBeTruthy()
  expect((await ui.find({ type: 'Text', text: /① 6,000자 상한 없애기/ }))).toBeTruthy()      // 같은 번호의 두 뜻
  expect((await ui.find({ type: 'Text', text: /② dockColumns 지우기/ }))).toBeTruthy()
  expect((await ui.find({ type: 'Text', text: /1개 더/ }))).toBeTruthy()
  await ui.unmount()
})


// 요구 이력 53: 켜지 않은 세션은 패널을 열지 않고, /nunchi로 켜면 관제 없이도 분석 대상이 된다
function bare(on: any, status: unknown, opened: string[], written: string[], want = false) {
  on('command.register', () => ({ value: { command: 'nunchi' } }))
  on('ui.open', (_: unknown, e: any) => { opened.push(String(e.id)); return { value: { isPlaced: true } } })
  on('session.start', (_: unknown, e: any) => ({ cwd: e.cwd }))
  on('session.id', () => ({ value: 'abc' }))
  on('settings.read', () => ({ value: { language: '한국어' } }))   // Claude Code 언어 설정 (요구 이력 76): 기존 시험은 한국어 화면
  on('env.get', (_: unknown, e: any) => ({ value: e.name === 'HOME' ? '/home/me' : undefined }))
  on('clock.every', () => ({ value: null }))
  on('clock.now', () => ({ value: 1000 }))
  on('fs.write', (_: unknown, e: any) => { written.push(String(e.path)); if (String(e.path).endsWith('/want')) want = true; return { value: null } })   // want를 쓸 때만 켬 (mod.json 쓰기는 켜지 않음)
  on('fs.read', (_: unknown, e: any) => {
    const p = String(e.path ?? e)
    if (p.endsWith('/sessions/abc/analysis_status.json') && status) return { value: JSON.stringify(status) }
    if (p.endsWith('/sessions/abc/want') && want) return { value: '{"at":"x"}' }
    throw new Error('missing ' + p)
  })
}

test('a session that never turned nunchi on and has no analysis opens no pane', async ($, on) => {
  const opened: string[] = [], written: string[] = []
  bare(on, null, opened, written)
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  expect(opened.length).toBe(0)
  const ui = await mountPane($, { ...PANE, surface: 'terminal' })
  expect((await ui.find({ type: 'Text', text: /눈치 꺼짐 · \/nunchi로 켜면/ }))).toBeTruthy()
  await ui.unmount()
})

test('/nunchi writes the want mark, opens the pane and says the next answer will be analyzed', async ($, on) => {
  const opened: string[] = [], written: string[] = []
  bare(on, null, opened, written)
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  const r = await $.command.run({ command: 'nunchi' })
  expect(written.some(p => p.endsWith('/home/me/.claude-control/sessions/abc/want'))).toBe(true)
  expect(opened).toContain('nunchi')
  expect(String(r.text)).toMatch(/다음 응답이 끝나면 이 세션을 분석합니다/)
  const ui = await mountPane($, { ...PANE, surface: 'terminal' })
  expect((await ui.find({ type: 'Text', text: /눈치 켜짐 · 다음 응답이 끝나면 분석합니다/ }))).toBeTruthy()
  await ui.unmount()
})

test('a turned-on session opens by itself and shows waiting and failure lines', async ($, on) => {
  const opened: string[] = [], written: string[] = []
  bare(on, { state: 'queued', turn: 0 }, opened, written, true)
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  expect(opened).toContain('nunchi')
  const ui = await mountPane($, { ...PANE, surface: 'terminal' })
  expect((await ui.find({ type: 'Text', text: /분석 대기/ }))).toBeTruthy()
  await ui.unmount()
})

test('a failed analysis shows its reason', async ($, on) => {
  const opened: string[] = [], written: string[] = []
  bare(on, { state: 'failed', turn: 0, error: '시간 초과 (150초)' }, opened, written, true)
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  const ui = await mountPane($, { ...PANE, surface: 'terminal' })
  expect((await ui.find({ type: 'Text', text: /분석 실패 · 시간 초과/ }))).toBeTruthy()
  await ui.unmount()
})

// 요구 이력 56: 관제로 버튼. 관제가 켜져 있으면 goto를 남기고 관제 패널을 앞으로, 꺼져 있으면 안내
function withControl(on: any, runs: string[][], written: Record<string, string>, control: boolean, alive = true) {
  on('command.register', () => ({ value: { command: 'nunchi' } }))
  on('ui.open', () => ({ value: { isPlaced: true } }))
  on('session.start', (_: unknown, e: any) => ({ cwd: e.cwd }))
  on('session.id', () => ({ value: 'abc' }))
  on('settings.read', () => ({ value: { language: '한국어' } }))   // Claude Code 언어 설정 (요구 이력 76): 기존 시험은 한국어 화면
  on('env.get', (_: unknown, e: any) => ({ value: e.name === 'HOME' ? '/home/me' : undefined }))
  on('clock.every', () => ({ value: null }))
  on('clock.now', () => ({ value: 5000 }))
  on('fs.write', (_: unknown, e: any) => { written[String(e.path)] = String(e.data ?? e.content ?? e.text ?? ''); return { value: null } })
  on('process.run', (_: unknown, e: any) => {
    const argv = (e.argv ?? e) as string[]
    runs.push([...argv])
    const ok = argv[0] === 'kill' ? alive : true
    return { value: { exitCode: ok ? 0 : 1, stdout: argv[0] === 'osascript' ? 'ok\n' : '', stderr: '' } }
  })
  on('fs.read', (_: unknown, e: any) => {
    const p = String(e.path ?? e)
    if (p.endsWith('/sessions/abc/analysis.json')) return { value: JSON.stringify(ANALYSIS) }
    if (p.endsWith('/sessions/abc/want')) return { value: '{"at":"x"}' }
    if (p.endsWith('/.claude-control/control.json') && control) return { value: '{"iterm_session_id":"CTRL-1","pid":4321}' }
    throw new Error('missing ' + p)
  })
}

test('with the control running, 관제로 leaves a goto and brings the control panel to front', async ($, on) => {
  const runs: string[][] = []
  const written: Record<string, string> = {}
  withControl(on, runs, written, true)
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  const ui = await mountPane($, { ...PANE, surface: 'terminal' })
  expect((await ui.find({ type: 'Text', text: /또는 ⌘숫자/ }))).toBeTruthy()
  await ui.press({ key: 'control' })
  expect(runs.some(r => r[0] === 'kill' && r[2] === '4321')).toBe(true)
  const goto = Object.entries(written).find(([p]) => p.endsWith('/.claude-control/goto'))
  expect(goto && JSON.parse(goto[1]).session).toBe('abc')
  expect(JSON.parse(goto![1]).at).toBe(5)                       // 초 단위 (관제가 time.time()과 비교)
  expect(runs.some(r => r[0] === 'osascript' && r[r.length - 1] === 'CTRL-1')).toBe(true)
  await ui.unmount()
})

test('without the control, the tail says nothing and offers no button (요구 이력 70)', async ($, on) => {
  const runs: string[][] = []
  withControl(on, runs, {}, false)
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  const ui = await mountPane($, { ...PANE, surface: 'terminal' })
  expect((await ui.find({ type: 'Text', text: /관제/ }))).toBeFalsy()   // 지운 관제 화면을 켜라고 하지 않는다
  expect((await ui.find({ type: 'Text', text: /또는 ⌘숫자/ }))).toBeFalsy()
  await ui.unmount()
})

test('a stale control file (dead pid) does not write goto or run osascript', async ($, on) => {
  const runs: string[][] = []
  const written: Record<string, string> = {}
  withControl(on, runs, written, true, false)
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  const ui = await mountPane($, { ...PANE, surface: 'terminal' })
  await ui.press({ key: 'control' })
  expect(Object.keys(written).some(p => p.endsWith('/goto'))).toBe(false)
  expect(runs.some(r => r[0] === 'osascript')).toBe(false)
  await ui.unmount()
})

test('a wide symbol touching the next letter gets one space after it (요구 이력 58)', async ($, on) => {
  const touching = { ...ANALYSIS, flow: { ...ANALYSIS.flow, current_goal: { text: 'A→B …끝 ◆ 그대로 ─선', turn: 3 } } }
  engine(on, { state: 'idle', turn: 0 }, false, touching)
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  const ui = await mountPane($, { ...PANE, surface: 'terminal' })
  expect((await ui.find({ type: 'Text', text: /^\s+A→ B … 끝 ◆ 그대로 ─선$/ }))).toBeTruthy()   // 괘선은 그대로
  await ui.unmount()
})

test('links in the pane are drawn as Link elements a click opens (요구 이력 60)', async ($, on) => {
  const requests = ANALYSIS.flow.requests.map((r: any) => r.id === 'R2' ? { ...r, summary: '[가이드](https://example.com/g) 읽기' } : r)   // 방금 대신 요청 요약의 링크 (요구 이력 87)
  const linked = { ...ANALYSIS, flow: { ...ANALYSIS.flow, requests,
    current_goal: { text: 'https://claude.ai/artifact/R8EpVcd9cueTtn7Ep2MS82 확인.', turn: 3 } } }   // 주소로 시작: 목표 2줄 상한(요구 이력 77) 안에서 주소가 두 줄에 나뉜다
  engine(on, { state: 'idle', turn: 0 }, false, linked)
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  const ui = await mountPane($, { ...PANE, props: { ...PANE.props, bodyColumns: 30 }, surface: 'terminal' })
  const hrefs = (await ui.findAll({ type: 'Link' })).map((l: any) => l.props?.href)
  expect(hrefs.filter((h: string) => h === 'https://claude.ai/artifact/R8EpVcd9cueTtn7Ep2MS82').length).toBe(2)  // 줄이 나뉘어도 조각마다 같은 주소
  expect(hrefs).toContain('https://example.com/g')
  expect(hrefs).not.toContain('https://claude.ai/artifact/R8EpVcd9cueTtn7Ep2MS82.')                           // 끝 마침표는 주소가 아니다
  expect((await ui.find({ type: 'Text', text: /\]\(/ }))).toBeFalsy()                                           // [이름](주소)는 이름만
  await ui.unmount()
})

test('more than three remaining requests end with how many more (요구 이력 64)', async ($, on) => {
  const many = { ...ANALYSIS, flow: { ...ANALYSIS.flow, requests: [1, 2, 3, 4].map(i =>
    ({ id: `R${i}`, from_turn: i, summary: `남은 일 ${i}`, state: 'deferred' })) } }
  engine(on, { state: 'idle', turn: 0 }, false, many)
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  const ui = await mountPane($, { ...PANE, surface: 'terminal' })
  expect((await ui.find({ type: 'Text', text: /남은 요청 4/ }))).toBeTruthy()
  expect((await ui.find({ type: 'Text', text: /남은 일 4/ }))).toBeFalsy()
  expect((await ui.find({ type: 'Button', key: 'more-left' }))?.text).toBe('… 1개 더')   // 관제 c는 뺐다 (요구 이력 70). 버튼이다 (요구 이력 74)
  await ui.unmount()
})

test('the head says how many answers came after the analyzed one (요구 이력 65)', async ($, on) => {
  const at = { ...ANALYSIS, source_ts: '2026-11-16T05:57:07.474Z' }
  const ev = [
    { ts: '2026-11-16T05:57:07.474Z', event: 'Stop' },            // 분석이 본 응답
    { ts: '2026-11-16T06:07:56.011Z', event: 'UserPromptSubmit' },
    { ts: '2026-11-16T06:08:06.653Z', event: 'Stop' },
    { ts: '2026-11-16T06:08:57.311Z', event: 'Stop' },
    { ts: '2026-11-16T06:09:14.662Z', event: 'Stop' },             // 같은 턴에서 이어 끝난 응답도 센다
  ].map(e => JSON.stringify(e)).join('\n') + '\n'
  engine(on, { state: 'idle', turn: 0 }, false, at, ev)
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  const ui = await mountPane($, { ...PANE, surface: 'terminal' })
  expect((await ui.find({ type: 'Text', text: /^눈치 · #3 응답까지 반영 · 응답 3개 밀림$/ }))).toBeTruthy()
  expect((await ui.find({ type: 'Text', text: /^\s+자동 분석 꺼짐/ }))).toBeTruthy()   // 50칸보다 넓어 상태는 다음 줄로 (요구 이력 82)
  await ui.unmount()
})

test('nothing is said when the analysis has seen the last answer', async ($, on) => {
  const at = { ...ANALYSIS, source_ts: '2026-11-16T06:09:14.662Z' }
  const ev = JSON.stringify({ ts: '2026-11-16T06:09:14.662Z', event: 'Stop' }) + '\n'
  engine(on, { state: 'idle', turn: 0 }, false, at, ev)
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  const ui = await mountPane($, { ...PANE, surface: 'terminal' })
  expect((await ui.find({ type: 'Text', text: /밀림/ }))).toBeFalsy()
  await ui.unmount()
})

test('a request still in progress stays in what is left with a half mark (요구 이력 66)', async ($, on) => {
  const prog = { ...ANALYSIS, flow: { ...ANALYSIS.flow, requests: [
    { id: 'R1', from_turn: 2, by_turn: 4, summary: '약관 취소 버튼', state: 'in_progress', agent_quote: '병합은 하지 않았습니다' }] } }
  engine(on, { state: 'idle', turn: 0 }, false, prog)
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  const ui = await mountPane($, { ...PANE, surface: 'terminal' })
  expect((await ui.find({ type: 'Text', text: /남은 요청 1/ }))).toBeTruthy()
  expect((await ui.find({ type: 'Text', text: /◐ 약관 취소 버튼 — 진행 중 #4/ }))).toBeTruthy()
  await ui.unmount()
})

test('the events file is read again only after an answer ends, not every second', async () => {
  let reads = 0
  let now = 1000
  let ev = JSON.stringify({ ts: '2026-11-16T05:57:07.474Z', event: 'Stop' }) + '\n'
  const fake: any = { clock: { now: async () => now }, fs: { read: async () => { reads++; return ev } } }
  answerEnded(-99999)   // 앞 테스트가 남긴 값을 지운다
  const since = '2026-11-16T05:57:07.474Z'
  expect((await answersAfter(fake, '/d', since)).behind).toBe(0)
  ev += JSON.stringify({ ts: '2026-11-16T06:08:00.000Z', event: 'PostToolUse' }) + '\n'
  ev += JSON.stringify({ ts: '2026-11-16T06:08:06.653Z', event: 'Stop' }) + '\n'
  now = 2000
  expect((await answersAfter(fake, '/d', since)).behind).toBe(0)       // 응답이 끝났다는 알림 전에는 다시 읽지 않는다
  expect(reads).toBe(1)
  answerEnded(now)
  expect((await answersAfter(fake, '/d', since)).behind).toBe(1)       // 응답이 끝나면 다시 센다
  now = 9000
  await answersAfter(fake, '/d', since)
  expect(reads).toBe(2)                                       // 5초가 지나면 다시 읽지 않는다
  expect((await answersAfter(fake, '/d', '2026-11-16T06:08:06.653Z')).behind).toBe(0)   // 분석 기준이 바뀌면 다시 센다
  expect(reads).toBe(3)
})

test('a bare link stops before Korean particles, backticks and bold marks', async () => {
  const { pieces } = await Promise.resolve({ pieces: piecesOf })
  const hrefs = (t: string) => pieces(t).filter(p => p.href).map(p => p.href)
  expect(hrefs('https://git.example.com/merge_requests/12를 올렸습니다')).toEqual(['https://git.example.com/merge_requests/12'])
  expect(hrefs('주소는 `https://x.com/a` 입니다')).toEqual(['https://x.com/a'])
  expect(hrefs('**https://x.com/a**에서 보세요')).toEqual(['https://x.com/a'])
  expect(hrefs('https://x.com/a?b=1&c=2.')).toEqual(['https://x.com/a?b=1&c=2'])
})

// 요구 이력 72: 의사결정은 정한 내용 한 줄을 먼저, 없으면 제목. 최근 것부터 (요구 이력 74)
test('decisions show what was decided before the title, newest first (요구 이력 72·74)', async ($, on) => {
  const steps = [
    ...ANALYSIS.flow.steps,
    { index: 4, grounded: true, label: '확정', summary: '폭 확정', agent_summary: '', title: '권장안으로 결정', decision: '폭은 40칸으로 두기로 함' },
  ]
  engine(on, { state: 'idle', turn: 0 }, false, { ...ANALYSIS, last_turn: 4, flow: { ...ANALYSIS.flow, until: 4, steps } })
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  const ui = await mountPane($, { ...PANE, surface: 'terminal' })
  expect((await ui.find({ type: 'Text', text: /✔ 폭은 40칸으로 두기로 함\s+#4/ }))).toBeTruthy()
  expect((await ui.find({ type: 'Text', text: /권장안으로 결정/ }))).toBeFalsy()
  expect((await ui.find({ type: 'Text', text: /✔ 설치 절 확정\s+#2/ }))).toBeTruthy()   // decision이 없으면 제목
  const order = (await ui.findAll({ type: 'Text', text: /^\s+✔ / })).map((x: any) => String(x.text ?? ''))
  expect(order.findIndex(t => t.includes('#4'))).toBeLessThan(order.findIndex(t => t.includes('#2')))
  await ui.unmount()
})

// 요구 이력 74·78: … n개 더는 버튼. 누르면 그 덩어리를 모두 펼치고, 같은 자리가 접기가 되어 처음 3개로 돌아간다
test('more opens the whole list at once, then fold takes it back to three (요구 이력 74·78)', async ($, on) => {
  const many = { ...ANALYSIS, flow: { ...ANALYSIS.flow, requests: [1, 2, 3, 4, 5, 6, 7, 8, 9].map(i =>
    ({ id: `R${i}`, from_turn: i, summary: `남은 일 ${i}`, state: 'deferred' })) } }
  engine(on, { state: 'idle', turn: 0 }, false, many)
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  const ui = await mountPane($, { ...PANE, surface: 'terminal' })
  const seen = async (i: number) => Boolean(await ui.find({ type: 'Text', text: new RegExp(`남은 일 ${i} `) }))
  const label = async (key: string) => (await ui.find({ type: 'Button', key }))?.text
  expect(await seen(3)).toBe(true)
  expect(await seen(4)).toBe(false)
  expect(await label('more-left')).toBe('… 6개 더')
  await ui.press({ key: 'more-left' })
  expect(await seen(9)).toBe(true)                     // 한 번에 모두
  expect(await label('more-left')).toBe('접기')
  await ui.press({ key: 'more-left' })
  expect(await seen(4)).toBe(false)
  expect(await label('more-left')).toBe('… 6개 더')
  await ui.unmount()
})

test('what was opened stays open when the pane is drawn again (요구 이력 74)', async ($, on) => {
  const many = { ...ANALYSIS, flow: { ...ANALYSIS.flow, asks: [1, 2, 3, 4, 5, 6].map(i =>
    ({ id: `Q${i}`, turn: i, last_turn: i, summary: `물음 ${i}`, quote: `물음 ${i}?`, state: 'open' })) } }
  engine(on, { state: 'idle', turn: 0 }, false, many)
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  let ui = await mountPane($, { ...PANE, surface: 'terminal' })
  expect((await ui.find({ type: 'Text', text: /물음 1 #1/ }))).toBeFalsy()      // 최근 물은 것부터 3개
  await ui.press({ key: 'more-asks' })
  expect((await ui.find({ type: 'Text', text: /물음 1 #1/ }))).toBeTruthy()
  await ui.unmount()
  ui = await mountPane($, { ...PANE, surface: 'terminal' })
  expect((await ui.find({ type: 'Text', text: /물음 1 #1/ }))).toBeTruthy()
  await ui.unmount()
})

test('what was opened stays open when a new analysis result comes in (요구 이력 74)', async ($, on) => {
  const asks = [1, 2, 3, 4, 5, 6].map(i => ({ id: `Q${i}`, turn: i, last_turn: i, summary: `물음 ${i}`, quote: `물음 ${i}?`, state: 'open' }))
  const live: any = { ...ANALYSIS, flow: { ...ANALYSIS.flow, asks } }
  engine(on, { state: 'idle', turn: 0 }, true, live)
  on('fs.write', () => ({ value: undefined }))
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  const ui = await mountPane($, { ...PANE, surface: 'terminal' })
  await ui.press({ key: 'more-asks' })                     // 지난 질문(#1·#2) 펼치기 (요구 이력 86: 마지막 응답 #3 이후에 물은 것이 지금 질문)
  expect((await ui.find({ type: 'Text', text: /물음 1 #1/ }))).toBeTruthy()
  live.flow = { ...live.flow, asks: [...asks, { id: 'Q7', turn: 7, last_turn: 7, summary: '물음 7', quote: '물음 7?', state: 'open' }] }
  await $.command.run({ command: 'nunchi' } as any)        // 분석 결과를 다시 읽는다
  expect((await ui.find({ type: 'Text', text: /에이전트 질문 5/ }))).toBeTruthy()
  expect((await ui.find({ type: 'Text', text: /물음 7 #7/ }))).toBeTruthy()
  expect((await ui.find({ type: 'Text', text: /물음 2 #2/ }))).toBeTruthy()   // 펼친 지난 질문이 그대로
  await ui.unmount()
})

// 요구 이력 77·78: 키(요구 이력 75), mod.json 저장, 맨 아래 펼치기·줄이기 버튼은 없앴다. 펼침은 덩어리별, 이 세션에만
function lots(n: number) {
  const k = Array.from({ length: n }, (_, i) => i + 1)
  return { ...ANALYSIS, last_turn: 3 + n, flow: { ...ANALYSIS.flow, until: 3 + n,
    steps: [...ANALYSIS.flow.steps.filter(x => x.label !== '확정'), ...k.map(i => ({ index: 3 + i, grounded: true, label: '확정', summary: '', agent_summary: '', title: `결정 ${i}` }))],
    asks: k.map(i => ({ id: `Q${i}`, turn: i, last_turn: i, summary: `물음 ${i}`, quote: '', state: 'open' })),
    requests: k.map(i => ({ id: `R${i}`, from_turn: i, summary: `일 ${i}`, state: 'open' })) } }
}
async function counts(ui: any) {
  const n = async (re: RegExp) => (await ui.findAll({ type: 'Text', text: re })).length
  return [await n(/^\s+✔ 결정 \d+\s+#\d+$/), await n(/^ \d+ 물음 \d+ #\d+/), await n(/^ ○ 일 \d+ #\d+$/)]
}

test('there are no bottom buttons and each list opens on its own (요구 이력 78)', async ($, on) => {
  engine(on, { state: 'idle', turn: 0 }, false, lots(12))
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  const ui = await mountPane($, { ...PANE, surface: 'terminal' })
  expect(await counts(ui)).toEqual([3, 0, 3])      // 질문은 모두 마지막 응답 전에 물은 것이라 접힌다 (요구 이력 86)
  expect((await ui.find({ type: 'Button', key: 'expand' }))).toBeFalsy()
  expect((await ui.find({ type: 'Button', key: 'shrink' }))).toBeFalsy()
  expect((await ui.find({ type: 'Text', text: /펼치기|줄이기/ }))).toBeFalsy()
  await ui.press({ key: 'more-asks' })
  expect(await counts(ui)).toEqual([3, 12, 3])
  await ui.unmount()
})

test('keys do nothing, nothing is saved, and a new session starts with three (요구 이력 77)', async ($, on) => {
  const written: Record<string, string> = {}
  // 이미 첫 알림을 띄운 상태(noticed, 요구 이력 76)에서: 펼침 때문에 mod.json을 쓰는 일이 없어야 한다
  engine(on, { state: 'idle', turn: 0 }, false, lots(12), '', { '/home/me/.claude-control/mod.json': '{"expand":"all","noticed":true}' })
  on('fs.write', (_: unknown, e: any) => { written[String(e.path)] = String(e.text ?? ''); return { value: undefined } })
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  const ui = await mountPane($, { ...PANE, surface: 'terminal' })
  expect(await counts(ui)).toEqual([3, 0, 3])      // 옛 mod.json의 모두 펼침은 쓰지 않는다 (질문은 지난 질문이라 접힘, 요구 이력 86)
  expect((await ui.find({ type: 'Client' } as any))).toBeFalsy()   // 본문은 보통 글자 (끌어 복사할 수 있게)
  await ui.press({ key: 'more-decisions' })
  expect(await counts(ui)).toEqual([12, 0, 3])
  expect(Object.keys(written).some(p => p.endsWith('/mod.json'))).toBe(false)
  await ui.unmount()
})

test('vscode draws the same rows (요구 이력 75·77)', async ($, on) => {
  engine(on, { state: 'idle', turn: 0 }, false, lots(5))
  await $.session.start({ cwd: '/', surface: 'vscode', isInteractive: true })
  const ui = await $.ui.mount({ ...PANE, surface: 'vscode' } as any)
  expect((await ui.find({ type: 'Client' } as any))).toBeFalsy()
  expect((await ui.find({ type: 'Text', text: /^목표\s+#3부터$/ }))).toBeTruthy()
  expect((await ui.find({ type: 'Button', key: 'more-left' }))?.text).toBe('… 2개 더')
  await ui.press({ key: 'more-left' })
  expect((await ui.find({ type: 'Text', text: /일 5 #5/ }))).toBeTruthy()
  await ui.unmount()
})

// ---------- 언어 (요구 이력 76, SCREEN §11 언어, BUILD_PLAN §4.14) ----------

const MOD = '/home/me/.claude-control/mod.json'

// 언어 시험 엔진: Claude Code language(setting)·터미널 언어(env)·mod.json(files)을 정하고, 질문 창 답(answers, null이면 Esc)을 차례로 준다
function langEngine(on: any, o: { setting?: unknown; env?: Record<string, string>; files?: Record<string, string>; analysis?: unknown; status?: unknown;
  answers?: (string | null)[]; toasts?: string[]; asked?: any[]; runs?: string[][]; run?: (argv: string[]) => { exitCode: number; stdout: string } } = {}) {
  const files: Record<string, string> = { ...(o.files ?? {}) }
  const answers = [...(o.answers ?? [])]
  on('command.register', () => ({ value: { command: 'nunchi' } }))
  on('ui.open', () => ({ value: { isPlaced: true } }))
  on('session.start', (_: unknown, e: any) => ({ cwd: e.cwd }))
  on('session.id', () => ({ value: 'abc' }))
  on('settings.read', () => ({ value: o.setting === undefined ? {} : { language: o.setting } }))
  on('env.get', (_: unknown, e: any) => ({ value: e.name === 'HOME' ? '/home/me' : o.env?.[e.name] }))
  on('clock.every', () => ({ value: null }))
  on('clock.now', () => ({ value: 1000 }))
  on('ui.toast', (_: unknown, e: any) => { o.toasts?.push(String(e.text ?? e)); return { value: undefined } })
  on('fs.write', (_: unknown, e: any) => { files[String(e.path)] = String(e.text ?? ''); return { value: undefined } })
  on('process.run', (_: unknown, e: any) => {
    const argv = [...((e.argv ?? e) as string[])]
    o.runs?.push(argv)
    // 엔진 build가 볼 켜짐 표시를 함께 적어 둔다 (want를 엔진에 맡기기 전에 썼는지 본다)
    if (argv.includes('build') && !argv.includes('--count')) o.runs?.push(['want-at-build', files['/home/me/.claude-control/sessions/abc/want'] ?? ''])
    const r = o.run?.(argv) ?? { exitCode: 0, stdout: '' }
    return { value: { ...r, stderr: '' } }
  })
  on('fs.read', (_: unknown, e: any) => {
    const p = String(e.path ?? e)
    if (p in files) return { value: files[p] }
    if (p.endsWith('/sessions/abc/analysis.json') && o.analysis !== null) return { value: JSON.stringify(o.analysis ?? ANALYSIS) }
    if (p.endsWith('/sessions/abc/analysis_status.json')) return { value: JSON.stringify(o.status ?? { state: 'idle', turn: 0 }) }
    throw new Error('missing ' + p)
  })
  on('tool.call', (_: unknown, e: any) => {
    o.asked?.push(e)
    const a = answers.shift()
    if (a == null) return { deny: 'esc' }
    const q = String(e.questions?.[0]?.question ?? '')
    return { result: { answers: { [q]: a } } }
  })
  return files
}

test('the language comes from the saved choice, then Claude Code, then the terminal, then English (요구 이력 76)', async () => {
  expect(norm(' 한국어 ')).toBe('ko')
  expect(norm('Korean')).toBe('ko')
  expect(norm('ko_KR')).toBe('ko')
  expect(norm('English')).toBe('en')
  expect(norm('en-US')).toBe('en')
  expect(norm('Japanese')).toBe('japanese')
  expect(pick({ saved: 'en', setting: '한국어' })).toEqual({ ui: 'en', analysis: 'en', from: 'saved' })
  expect(pick({ setting: '한국어', lang: 'en_US.UTF-8' })).toEqual({ ui: 'ko', analysis: 'ko', from: 'claude' })
  expect(pick({ setting: 'japanese' })).toEqual({ ui: 'en', analysis: 'japanese', from: 'claude' })   // 화면은 영어, 분석은 그 언어
  expect(pick({ lcAll: 'ko_KR.UTF-8', lang: 'en_US.UTF-8' })).toEqual({ ui: 'ko', analysis: 'ko', from: 'terminal' })
  expect(pick({ lang: 'ja_JP.UTF-8' })).toEqual({ ui: 'en', analysis: 'en', from: 'terminal' })        // 터미널 값은 분석기에 넘기지 않는다
  expect(pick({ lang: 'C' })).toEqual({ ui: 'en', analysis: 'en', from: 'terminal' })
  expect(pick({})).toEqual({ ui: 'en', analysis: 'en', from: 'default' })
})

test('with Claude Code set to English the pane is in English and quotes stay as written (요구 이력 76)', async ($, on) => {
  langEngine(on, { setting: 'English', files: { [MOD]: '{"noticed":true}' } })
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  const ui = await mountPane($, { ...PANE, surface: 'terminal' })
  expect((await ui.find({ type: 'Text', text: /^Nunchi · through answer #3/ }))).toBeTruthy()
  for (const head of [/^Goal  since #3/, /^Decisions 1/, /^Agent questions 1/, /^Open requests 1 of mine/]) {
    expect((await ui.find({ type: 'Text', text: head }))).toBeTruthy()
  }
  expect((await ui.find({ type: 'Button', key: 'more-asks' }))?.text).toBe('1 earlier question')   // 지난 질문 버튼 (요구 이력 86)
  expect((await ui.find({ type: 'Text', text: /partly answered/ }))).toBeTruthy()
  expect((await ui.find({ type: 'Text', text: /테스트 돌리기 — deferred/ }))).toBeTruthy()   // 요약은 분석 언어 그대로, 상태 이름만 화면 언어
  expect((await ui.find({ type: 'Text', text: /“폭은 몇 칸으로 할지 알려 주세요”/ }))).toBeTruthy()
  for (const ko of [/^목표/, /^결정 사항/, /^에이전트 질문/, /^남은 요청/, /반영/]) {
    expect((await ui.find({ type: 'Text', text: ko }))).toBeFalsy()
  }
  await ui.unmount()
})

test('when the session was analyzed in another language the head says how to rebuild it (요구 이력 76)', async ($, on) => {
  langEngine(on, { setting: 'English', files: { [MOD]: '{"noticed":true}' } })
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  const ui = await mountPane($, { ...PANE, surface: 'terminal' })
  expect((await ui.find({ type: 'Text', text: 'analysis: 한국어 · /nunchi language to rebuild' }))).toBeTruthy()
  await ui.unmount()
})

test('the analyzer\'s own claude -p leaves no session folder and no notice (요구 이력 76)', async ($, on) => {
  // 분석 호출마다 session.start가 돌아 lang만 든 빈 세션 폴더가 쌓였다 (L4 실제 확인에서 찾음). 훅처럼 분석기 자신은 건너뛴다
  const toasts: string[] = []
  const files = langEngine(on, { setting: '한국어', env: { CONTROL_TUI_ANALYZER: '1' }, toasts })
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: false })
  expect(Object.keys(files)).toEqual([])
  expect(toasts).toEqual([])
})

test('while the first analysis has written no flow yet, no language line and no rebuild question (요구 이력 76)', async ($, on) => {
  // 엔진은 첫 분석에서 흐름 없는 결과를 먼저 적는다. 흐름이 없으면 언어를 모르니 한국어로 치지 않는다 (L4 실제 확인에서 찾음)
  const asked: any[] = []
  const { flow: _, ...noFlow } = ANALYSIS as any
  langEngine(on, { setting: 'English', analysis: { ...noFlow, last_turn: 1 }, status: { state: 'running', turn: 1 },
    answers: ['한국어'], asked, files: { [MOD]: '{"noticed":true}' } })
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  const ui = await mountPane($, { ...PANE, surface: 'terminal' })
  expect((await ui.find({ type: 'Text', text: /^analysis:/ }))).toBeFalsy()
  await $.command.run({ command: 'nunchi', args: 'language' } as any)
  expect(asked.length).toBe(1)
  await ui.unmount()
})

test('no language line when the session is already in the chosen language, and Japanese shows English labels (요구 이력 76)', async ($, on) => {
  langEngine(on, { setting: 'japanese', files: { [MOD]: '{"noticed":true}' },
    analysis: { ...ANALYSIS, flow: { ...ANALYSIS.flow, lang: 'japanese' } } })
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  const ui = await mountPane($, { ...PANE, surface: 'terminal' })
  expect((await ui.find({ type: 'Text', text: /^Goal/ }))).toBeTruthy()
  expect((await ui.find({ type: 'Text', text: /^analysis:/ }))).toBeFalsy()
  await ui.unmount()
})

test('the first session tells once which language it uses, and never again (요구 이력 76)', async ($, on) => {
  const toasts: string[] = []
  const files = langEngine(on, { setting: '한국어', toasts, files: { [MOD]: '{"expand":"all"}' } })
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  expect(toasts).toEqual(['눈치: 한국어로 표시합니다 · /nunchi language로 변경'])
  expect(JSON.parse(files[MOD]!)).toEqual({ expand: 'all', noticed: true })   // 펼침 저장은 남는다
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })   // 다시 불러와도 (session.start가 다시 옴)
  expect(toasts.length).toBe(1)
  await (await mountPane($, { ...PANE, surface: 'terminal' })).unmount()   // 열었다 닫아 1초 갱신 타이머를 정리한다
})

test('the notice is in English when Claude Code is set to English (요구 이력 76)', async ($, on) => {
  const toasts: string[] = []
  langEngine(on, { setting: 'English', toasts })
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  expect(toasts).toEqual(['Nunchi: showing English · change with /nunchi language'])
  await (await mountPane($, { ...PANE, surface: 'terminal' })).unmount()   // 열었다 닫아 1초 갱신 타이머를 정리한다
})

test('/nunchi language asks with the current language first and saves the choice (요구 이력 76)', async ($, on) => {
  const asked: any[] = []
  const files = langEngine(on, { setting: '한국어', files: { [MOD]: '{"noticed":true,"expand":"all"}' }, answers: ['English'], asked })
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  const r = await $.command.run({ command: 'nunchi', args: 'language' } as any)
  const q = asked[0]?.questions?.[0]
  expect(q?.question).toBe('눈치 언어를 고르세요. 지금: 한국어 (Claude Code 설정)')
  expect(q?.options?.map((x: any) => x.label ?? x)).toEqual(['한국어', 'English', 'Claude Code 설정 따르기'])
  expect(JSON.parse(files[MOD]!)).toEqual({ noticed: true, expand: 'all', language: 'en' })
  expect(String(r.text)).toMatch(/^Nunchi language: English/)
  const ui = await mountPane($, { ...PANE, surface: 'terminal' })
  expect((await ui.find({ type: 'Text', text: /^Goal/ }))).toBeTruthy()      // 패널 문구가 바로 바뀐다
  await ui.unmount()
})

test('on an English screen the language question is all English except the language names (요구 이력 79)', async ($, on) => {
  const asked: any[] = []
  langEngine(on, { env: { LANG: 'en_US.UTF-8' }, files: { [MOD]: '{"noticed":true}' }, answers: [null], asked })
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  await $.command.run({ command: 'nunchi', args: 'language' } as any)
  const q = asked[0]?.questions?.[0]
  expect(q?.question).toBe('Choose the Nunchi language. Now: English')
  expect(q?.options?.map((x: any) => x.label ?? x)).toEqual(['English', '한국어', 'Follow the Claude Code setting'])
  await (await mountPane($, { ...PANE, surface: 'terminal' })).unmount()
})

test('a language with no screen text of its own asks in English (요구 이력 79)', async ($, on) => {
  const asked: any[] = []
  langEngine(on, { setting: 'japanese', files: { [MOD]: '{"noticed":true}' }, answers: [null], asked })
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  await $.command.run({ command: 'nunchi', args: 'language' } as any)
  const q = asked[0]?.questions?.[0]
  expect(String(q?.question)).toMatch(/^Choose the Nunchi language\. Now: .* \(Claude Code setting\)$/)
  expect(q?.options?.map((x: any) => x.label ?? x)).toContain('Follow the Claude Code setting')
  await (await mountPane($, { ...PANE, surface: 'terminal' })).unmount()
})

test('following Claude Code removes the saved choice, and Esc changes nothing (요구 이력 76)', async ($, on) => {
  const files = langEngine(on, { setting: '한국어', files: { [MOD]: '{"noticed":true,"language":"en"}' }, answers: ['Follow the Claude Code setting', null] })
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  const r = await $.command.run({ command: 'nunchi', args: 'language' } as any)
  expect(JSON.parse(files[MOD]!)).toEqual({ noticed: true })
  expect(String(r.text)).toMatch(/Claude Code 설정을 따릅니다\(지금 한국어\)/)
  const before = files[MOD]
  const r2 = await $.command.run({ command: 'nunchi', args: 'language' } as any)
  expect(files[MOD]).toBe(before)
  expect(String(r2.text)).toMatch(/바꾸지 않았습니다/)
  await (await mountPane($, { ...PANE, surface: 'terminal' })).unmount()   // 열었다 닫아 1초 갱신 타이머를 정리한다
})

test('/nunchi without arguments still turns nunchi on (요구 이력 76)', async ($, on) => {
  const files = langEngine(on, { setting: '한국어', analysis: null, files: { [MOD]: '{"noticed":true}' } })
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  const r = await $.command.run({ command: 'nunchi' } as any)
  expect(Object.keys(files).some(p => p.endsWith('/sessions/abc/want'))).toBe(true)
  expect(String(r.text)).toMatch(/눈치를 켰습니다/)
  await (await mountPane($, { ...PANE, surface: 'terminal' })).unmount()   // 열었다 닫아 1초 갱신 타이머를 정리한다
})

test('failure codes from the engine read in the screen language, unknown text as is (요구 이력 76)', async () => {
  expect(failText('exit:1', 'ko')).toBe('claude 종료 코드 1')
  expect(failText('exit:1', 'en')).toBe('claude exited with 1')
  expect(failText('timeout:150', 'ko')).toBe('시간 초과 (150초)')
  expect(failText('timeout:150', 'en')).toBe('timed out (150s)')
  expect(failText('no-turns', 'en')).toBe('no turns recorded to analyze')
  expect(failText('시간 초과 (150초)', 'en')).toBe('시간 초과 (150초)')   // 옛 결과
})

test('a failed analysis shows the translated reason in English (요구 이력 76)', async ($, on) => {
  langEngine(on, { setting: 'English', analysis: null, status: { state: 'failed', turn: 0, error: 'exit:1' }, files: { [MOD]: '{"noticed":true}' } })
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  const ui = await mountPane($, { ...PANE, surface: 'terminal' })
  expect((await ui.find({ type: 'Text', text: 'Analysis failed · claude exited with 1' }))).toBeTruthy()
  await ui.unmount()
})

test('more and fold read in English (요구 이력 76·78)', async ($, on) => {
  langEngine(on, { setting: 'English', analysis: lots(5), files: { [MOD]: '{"noticed":true}' } })
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  const ui = await mountPane($, { ...PANE, surface: 'terminal' })
  expect((await ui.find({ type: 'Button', key: 'more-left' }))?.text).toBe('… 2 more')
  await ui.press({ key: 'more-left' })
  expect((await ui.find({ type: 'Button', key: 'more-left' }))?.text).toBe('Collapse')
  await ui.unmount()
})

test('the session start writes the analysis language for the engine, /nunchi puts it in want (요구 이력 76)', async ($, on) => {
  const files = langEngine(on, { setting: 'japanese', analysis: null, files: { [MOD]: '{"noticed":true}' } })
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  expect(files['/home/me/.claude-control/sessions/abc/lang']).toBe('japanese\n')
  await $.command.run({ command: 'nunchi' } as any)
  expect(JSON.parse(files['/home/me/.claude-control/sessions/abc/want']!).lang).toBe('japanese')
  await (await mountPane($, { ...PANE, surface: 'terminal' })).unmount()
})

test('choosing a language rewrites want for a session not analyzed yet (요구 이력 76)', async ($, on) => {
  const want = '/home/me/.claude-control/sessions/abc/want'
  const files = langEngine(on, { setting: '한국어', analysis: null, answers: ['English'],
    files: { [MOD]: '{"noticed":true}', [want]: '{"at":"x","by":"nunchi","lang":"ko"}' } })
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  await $.command.run({ command: 'nunchi', args: 'language' } as any)
  expect(JSON.parse(files[want]!)).toEqual({ at: 'x', by: 'nunchi', lang: 'en' })
  expect(files['/home/me/.claude-control/sessions/abc/lang']).toBe('en\n')
  await (await mountPane($, { ...PANE, surface: 'terminal' })).unmount()
})

// ---------- 다시 분석 (요구 이력 76 L3) ----------

test('choosing another language for an analyzed session asks whether to rebuild, keep first (요구 이력 76)', async ($, on) => {
  const asked: any[] = []
  langEngine(on, { setting: '한국어', answers: ['English', null], asked, files: { [MOD]: '{"noticed":true}' } })
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  const r = await $.command.run({ command: 'nunchi', args: 'language' } as any)
  const q = asked[1]?.questions?.[0]
  expect(q?.question).toBe('This session is analyzed in 한국어. Rebuild it in English? (3 answers · at least 3 analysis calls)')
  expect(q?.options?.map((x: any) => x.label ?? x)).toEqual(['Keep it (new sessions in English)', 'Rebuild now'])
  expect(String(r.text)).toMatch(/This session keeps its 한국어 analysis/)   // Esc는 그대로 두기
  await (await mountPane($, { ...PANE, surface: 'terminal' })).unmount()
})

test('rebuild now hands the session to the engine through emit.sh (요구 이력 76)', async ($, on) => {
  const runs: string[][] = []
  langEngine(on, { setting: '한국어', answers: ['English', 'Rebuild now'], runs, files: { [MOD]: '{"noticed":true}' } })
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  const r = await $.command.run({ command: 'nunchi', args: 'language' } as any)
  const call = runs.find(a => a.includes('rebuild'))!
  expect(call[0]).toBe('sh')
  expect(call[1]).toMatch(/\/hooks\/emit\.sh$/)
  expect(call.slice(2)).toEqual(['rebuild', 'abc', 'en'])
  expect(String(r.text)).toMatch(/Rebuilding this session in English from the start/)
  await (await mountPane($, { ...PANE, surface: 'terminal' })).unmount()
})

// ---------- 지금까지 분석 /nunchi build (요구 이력 93) ----------

const WANT = '/home/me/.claude-control/sessions/abc/want'
const plan = (o: object) => () => ({ exitCode: 0, stdout: JSON.stringify(o) + '\n' })

test('build shows how many answers it will analyze and cancel comes first; Esc changes nothing (요구 이력 93)', async ($, on) => {
  const asked: any[] = [], runs: string[][] = []
  const files = langEngine(on, { setting: '한국어', answers: [null], asked, runs, files: { [MOD]: '{"noticed":true}' }, run: plan({ total: 44, done: 0, todo: 44, fresh: true }) })
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  const r = await $.command.run({ command: 'nunchi', args: 'build' } as any)
  const q = asked[0]?.questions?.[0]
  expect(q?.question).toBe('이 세션의 응답 44개를 지금 엔진으로 처음부터 분석할까요? (분석 호출 44회 이상 · 이 계정 사용량)')
  expect(q?.options?.map((x: any) => x.label ?? x)).toEqual(['그만두기', '분석하기 (응답 44개)'])
  expect(String(r.text)).toBe('분석하지 않았습니다. 아무것도 바꾸지 않았습니다.')
  expect(runs.filter(a => a.includes('build')).map(a => a.slice(2))).toEqual([['build', 'abc', 'ko', '--count']])   // 세기만 했다
  expect(files[WANT]).toBeUndefined()   // 켜지 않았다
  await (await mountPane($, { ...PANE, surface: 'terminal' })).unmount()
})

test('build turns the session on before handing it to the engine, then says it analyzes from the start (요구 이력 93)', async ($, on) => {
  const runs: string[][] = []
  const files = langEngine(on, { setting: '한국어', answers: ['분석하기 (응답 44개)'], runs, files: { [MOD]: '{"noticed":true}' }, run: plan({ total: 44, done: 0, todo: 44, fresh: true }) })
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  const r = await $.command.run({ command: 'nunchi', args: 'build' } as any)
  const calls = runs.filter(a => a[0] === 'sh' && a.includes('build'))
  expect(calls[0][1]).toMatch(/\/hooks\/emit\.sh$/)
  expect(calls.map(a => a.slice(2))).toEqual([['build', 'abc', 'ko', '--count'], ['build', 'abc', 'ko']])
  expect(JSON.parse(runs.find(a => a[0] === 'want-at-build')![1])).toMatchObject({ on: true, by: 'nunchi', lang: 'ko' })   // 맡기기 전에 켰다
  expect(JSON.parse(files[WANT])).toMatchObject({ on: true })
  expect(String(r.text)).toBe('응답 44개를 처음부터 분석합니다. 눈치는 켜 두어 다음 응답부터도 분석합니다(/nunchi off로 끄기).')
  await (await mountPane($, { ...PANE, surface: 'terminal' })).unmount()
})

test('build with nothing left asks nothing, turns on and says it is up to date (요구 이력 93)', async ($, on) => {
  const asked: any[] = [], runs: string[][] = []
  const files = langEngine(on, { setting: '한국어', asked, runs, files: { [MOD]: '{"noticed":true}' }, run: plan({ total: 3, done: 3, todo: 0, fresh: false }) })
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  const r = await $.command.run({ command: 'nunchi', args: 'build' } as any)
  expect(asked.length).toBe(0)
  expect(runs.filter(a => a[0] === 'sh' && a.includes('build')).length).toBe(1)   // 맡기지 않는다
  expect(JSON.parse(files[WANT])).toMatchObject({ on: true })
  expect(String(r.text)).toBe('분석이 최신입니다(#3 응답까지). 눈치는 켜 두었습니다.')
  await (await mountPane($, { ...PANE, surface: 'terminal' })).unmount()
})

test('build without records says why and changes nothing (요구 이력 93)', async ($, on) => {
  const files = langEngine(on, { setting: '한국어', files: { [MOD]: '{"noticed":true}' }, run: () => ({ exitCode: 1, stdout: '' }) })
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  const r = await $.command.run({ command: 'nunchi', args: 'build' } as any)
  expect(String(r.text)).toBe('이 세션의 기록이 없어 분석하지 못합니다. 세션을 다시 시작한 뒤(claude --resume) 해 보세요.')
  expect(files[WANT]).toBeUndefined()
  await (await mountPane($, { ...PANE, surface: 'terminal' })).unmount()
})

test('build reads in English on an English screen, with no Hangul (요구 이력 93)', async ($, on) => {
  const asked: any[] = []
  langEngine(on, { setting: 'English', answers: ['Analyze (5 answers)'], asked, files: { [MOD]: '{"noticed":true}' }, run: plan({ total: 9, done: 4, todo: 5, fresh: false }) })
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  const r = await $.command.run({ command: 'nunchi', args: 'build' } as any)
  const q = asked[0]?.questions?.[0]
  expect(q?.question).toBe('Analyze the 5 answers not analyzed yet now? (at least 5 analysis calls · on your account\'s quota)')
  expect(q?.options?.map((x: any) => x.label ?? x)).toEqual(['Cancel', 'Analyze (5 answers)'])
  expect(String(r.text)).toBe('Analyzing the 5 answers not analyzed yet. Nunchi stays on and keeps analyzing later answers (/nunchi off to stop).')
  const u = String((await $.command.run({ command: 'nunchi', args: 'nope' } as any)).text)
  expect(u).toMatch(/\/nunchi build      analyze the conversation so far, now/)
  for (const t of [q?.question, ...q?.options?.map((x: any) => x.label ?? x), String(r.text), u]) expect(String(t)).not.toMatch(/[가-힣]/)
  await (await mountPane($, { ...PANE, surface: 'terminal' })).unmount()
})

test('no rebuild question when the session is already in that language or not analyzed (요구 이력 76)', async ($, on) => {
  const asked: any[] = []
  langEngine(on, { setting: '한국어', answers: ['한국어'], asked, files: { [MOD]: '{"noticed":true}' } })
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  await $.command.run({ command: 'nunchi', args: 'language' } as any)
  expect(asked.length).toBe(1)
  await (await mountPane($, { ...PANE, surface: 'terminal' })).unmount()
})

test('while rebuilding the head says it is rebuilding from the start (요구 이력 76)', async ($, on) => {
  langEngine(on, { setting: 'English', status: { state: 'running', turn: 2, rebuild: true },
    analysis: { ...ANALYSIS, last_turn: 3, flow: { ...ANALYSIS.flow, lang: 'en', until: 1, steps: ANALYSIS.flow.steps.slice(0, 1) } },
    files: { [MOD]: '{"noticed":true}' } })
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  const ui = await mountPane($, { ...PANE, surface: 'terminal' })
  expect((await ui.find({ type: 'Text', text: /Rebuilding from the start #2\/#3/ }))).toBeTruthy()
  expect((await ui.find({ type: 'Text', text: /^analysis:/ }))).toBeFalsy()
  await ui.unmount()
})

test('right after the reset, before any turn is written, the head already says rebuilding (요구 이력 76)', async ($, on) => {
  langEngine(on, { setting: '한국어', status: { state: 'running', turn: 1, rebuild: true },
    analysis: { last_turn: 3, flow: { version: 3, lang: 'en', until: 0, steps: [], requests: [], asks: [] } },
    files: { [MOD]: '{"noticed":true}' } })
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  const ui = await mountPane($, { ...PANE, surface: 'terminal' })
  expect((await ui.find({ type: 'Text', text: /흐름 처음부터 만드는 중 #1\/#3/ }))).toBeTruthy()
  await ui.unmount()
})

// 요구 이력 80: 2줄·1줄로 자르면 결론과 할 일이 사라졌다. 덩어리마다 줄 수를 다시 정하고, 글자 수로 미리 자르지 않는다
const LONG = {
  ...ANALYSIS, last_turn: 6,
  flow: {
    ...ANALYSIS.flow, until: 6,
    current_goal: { text: '눈치 패널 하단 안내를 상태바처럼 고정하고, 현재 세션 우선으로 펼치기·줄이기 키를 바꾸고, advisor 주도로 패널 디자인 리뷰하기', turn: 3 },
    steps: [...ANALYSIS.flow.steps,
      { index: 5, grounded: true, label: '확정', summary: '헤더', agent_summary: '', decision: 'APOLLOQA-36312는 네이티브 타이틀바 대신 웹 헤더를 유지하고 제목만 없애는 지금 결정으로 간다' },
      { index: 6, grounded: true, label: '구체화', summary: '확인', agent_summary: '확인함' }],
    requests: [{ id: 'R1', from_turn: 1, by_turn: 3, summary: 'CI 불일치 팝업에서 확인을 누르면 네이티브 브리지 logout 호출', state: 'in_progress' }],
    asks: [{ id: 'Q1', turn: 2, last_turn: 6, summary: 'useHead 문서 제목을 화면에 둘지 뺄지', quote: '`useHead` 제목은 화면에 보이지 않으니 빼도 되지만, 검색 결과와 탭 이름에는 남습니다. 둘까요?', state: 'open' }],
  },
}

async function lines($: any, on: any, cols: number): Promise<{ ui: any, all: string[] }> {
  engine(on, { state: 'idle', turn: 0 }, true, LONG)
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  const ui = await mountPane($, { ...PANE, props: { ...PANE.props, bodyColumns: cols }, surface: 'terminal' })
  const all: string[] = (await ui.findAll({ type: 'Text' })).map((x: any) => String(x.text ?? ''))
  return { ui, all }
}

test('at 46 columns the end of a decision, a request and a question still shows (요구 이력 80)', async ($, on) => {
  const { ui, all } = await lines($, on, 46)
  expect(all.some(t => /결정으로 간다\s+#5$/.test(t))).toBe(true)          // 결론과 턴이 보인다 (전에는 '유지하 …')
  expect(all.some(t => /^\s+브리지 logout 호출 — 진행 중 #3$/.test(t))).toBe(true)   // 할 일이 끝까지 보인다 (전에는 '네이…')
  expect(all.some(t => /뺄지/.test(t))).toBe(true)                          // '~할지' 어미가 남는다
  expect(all.some(t => /#6 · 처음 #2$/.test(t))).toBe(true)                // 마지막으로 물은 턴과 처음 물은 턴 (요구 이력 86)
  expect(all.some(t => /상태바처럼 고정하고/.test(t)) && all.some(t => /^\s+리뷰하기$/.test(t))).toBe(true)   // 목표 4줄
  const width = (t: string) => [...t].reduce((n, ch) => n + (/[가-힣]/.test(ch) ? 2 : 1), 0)
  for (const t of all.filter(t => /^\s/.test(t))) expect(width(t)).toBeLessThanOrEqual(46)   // 본문 줄은 패널 폭을 넘지 않는다
  await ui.unmount()
})

test('a wide pane shows a long quote whole instead of cutting it at 60 characters (요구 이력 80)', async ($, on) => {
  const { ui, all } = await lines($, on, 120)
  expect(all.some(t => /탭 이름에는 남습니다\. 둘까요\?”$/.test(t))).toBe(true)
  await ui.unmount()
})

test('text past its line limit still ends with … and keeps the turn (요구 이력 80)', async ($, on) => {
  const { ui, all } = await lines($, on, 24)
  expect(all.some(t => /^\s+\S.* …\s+#5$/.test(t))).toBe(true)   // 3줄을 넘친 결정: 마지막 줄 끝이 …, 턴은 남는다
  await ui.unmount()
})

test('a text that fills its lines exactly is not cut for the turn; the turn moves to the next line (요구 이력 80)', async ($, on) => {
  // 46칸: 결정 글 폭 41칸. 3줄을 거의 채우는 글
  const text = '가나다라마바사아자차 가나다라마바사아자차 가나다라마바사아자차 가나다라마바사아자차 가나다라마바사아자'   // [✔ 20] [20 20] [20 18] → 마지막 줄 39칸, 꼬리 5칸이 안 들어감
  const steps = [...LONG.flow.steps.slice(0, 3), { index: 5, grounded: true, label: '확정', summary: 'x', agent_summary: '', decision: text }]
  engine(on, { state: 'idle', turn: 0 }, true, { ...LONG, flow: { ...LONG.flow, steps } })
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  const ui = await mountPane($, { ...PANE, props: { ...PANE.props, bodyColumns: 46 }, surface: 'terminal' })
  const all: string[] = (await ui.findAll({ type: 'Text' })).map((x: any) => String(x.text ?? ''))
  expect(all.some(t => /가나다라마바사아자$/.test(t))).toBe(true)     // 글 끝까지, … 없이
  expect(all.some(t => /^\s+#5$/.test(t))).toBe(true)                 // 턴은 다음 줄
  await ui.unmount()
})

for (const cols of [24, 34]) test(`at ${cols} columns a long question tail keeps the summary and stays inside the pane (요구 이력 80)`, async ($, on) => {
  const asks = [{ id: 'Q1', turn: 2, last_turn: 6, summary: '기획서와 다른 세 곳의 처리 방법', quote: '어떻게 할까요?', state: 'partial' }]   // 마지막 응답이 다시 물음
  const width = (t: string) => [...t].reduce((n, ch) => n + (/[\uac00-\ud7a3]/.test(ch) ? 2 : 1), 0)
  engine(on, { state: 'idle', turn: 0 }, true, { ...LONG, flow: { ...LONG.flow, asks } })
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  const ui = await mountPane($, { ...PANE, props: { ...PANE.props, bodyColumns: cols }, surface: 'terminal' })
  const all: string[] = (await ui.findAll({ type: 'Text' })).map((x: any) => String(x.text ?? ''))
  expect(all.some(t => /^ 1 기획서와/.test(t))).toBe(true)          // 요약이 지워지지 않는다
  expect(all.some(t => /처음 #2/.test(t)) && all.some(t => /일부 답함|답함$/.test(t))).toBe(true)
  for (const t of all.filter(t => /^\s/.test(t))) expect(width(t)).toBeLessThanOrEqual(cols)
  await ui.unmount()
})

// 요구 이력 82: 머리 줄 기준 시점, 새 요청 반영 전, 목표 두 층
const prompt = (ts: string, text: string) => JSON.stringify({ ts, event: 'UserPromptSubmit', data: { prompt: text, permission_mode: 'default' } })

test('a human prompt after the analyzed answer shows new request pending, even while analyzing (요구 이력 82)', async ($, on) => {
  const at = { ...ANALYSIS, source_ts: '2026-11-18T01:00:00.000Z' }
  const ev = [JSON.stringify({ ts: '2026-11-18T01:00:00.000Z', event: 'Stop' }), prompt('2026-11-18T01:05:00.000Z', '줄 수 조정이랑 글자 수 자르기 같이 고쳐줘')].join('\n') + '\n'
  engine(on, { state: 'running', turn: 4 }, true, at, ev)
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  const ui = await mountPane($, { ...PANE, surface: 'terminal' })
  const all: string[] = (await ui.findAll({ type: 'Text' })).map((x: any) => String(x.text ?? ''))
  expect(all.some(t => /^눈치 · #3 응답까지 반영 · 새 요청 반영 전/.test(t))).toBe(true)
  await ui.unmount()
})

test('agent, cross-session, task and idle-notice prompts do not count as new requests (요구 이력 82)', async ($, on) => {
  for (const p of ['<agent-message from="a1">\n[Subagent hand-back] …', '<cross-session-message from="x">hi', '<task-notification>\n<task-id>1</task-id>', '[Cross-session idle notice] peer is idle', '', '   '])
    expect(humanPrompt(p)).toBe(false)
  for (const p of ['그래. 패널 너비를 넓히면 볼 수 있어?', 'agent-message라는 말이 들어간 요청', '  앞에 빈칸이 있는 요청'])
    expect(humanPrompt(p)).toBe(true)
  const at = { ...ANALYSIS, source_ts: '2026-11-18T02:00:00.000Z' }
  const ev = [prompt('2026-11-18T02:01:00.000Z', '<agent-message from="a1">\n[Subagent hand-back] done'), prompt('2026-11-18T01:59:00.000Z', '분석 전에 보낸 요청')].join('\n') + '\n'
  engine(on, { state: 'idle', turn: 0 }, true, at, ev)
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  const ui = await mountPane($, { ...PANE, surface: 'terminal' })
  expect((await ui.find({ type: 'Text', text: /반영 전/ }))).toBeFalsy()
  await ui.unmount()
})

test('a submitted prompt makes the events file read again, and a big file is read from its tail (요구 이력 82)', async () => {
  let reads: any[] = []
  let now = 50000
  const since = '2026-11-18T03:00:00.000Z'
  let ev = JSON.stringify({ ts: since, event: 'Stop' }) + '\n'
  let size = 100
  const fake: any = { clock: { now: async () => now }, fs: {
    stat: async () => ({ size }),
    read: async (_p: string, o?: any) => { reads.push(o ?? null); return o ? 'cut line\n' + ev : ev },
  } }
  answerEnded(-99999)
  expect((await answersAfter(fake, '/d', since)).pending).toBe(false)
  ev += prompt('2026-11-18T03:01:00.000Z', '새 요청') + '\n'
  now = 51000
  expect((await answersAfter(fake, '/d', since)).pending).toBe(false)   // 보냈다는 알림 전에는 다시 읽지 않는다
  promptSent(now)
  expect((await answersAfter(fake, '/d', since)).pending).toBe(true)    // 발화를 보내면 다시 읽는다
  expect(reads.every(o => o === null)).toBe(true)                        // 작은 파일은 통째로
  size = 5 * 1024 * 1024
  promptSent(now)
  const r = await answersAfter(fake, '/d', since)
  expect(r.pending).toBe(true)
  expect(reads[reads.length - 1]).toEqual({ offset: size - 3 * 1024 * 1024, length: 3 * 1024 * 1024 })   // 4 MiB 상한 안에서 끝부분만
})

const TWO = { ...ANALYSIS, flow: { ...ANALYSIS.flow,
  first_goal: { text: '눈치 패널 노출 내용과 디자인을 UX 관점에서 리뷰하기', turn: 1 },
  steps: ANALYSIS.flow.steps.map((x: any) => x.index === 3 ? { ...x, direction: '좁힘' } : x) } }

test('the goal shows the first goal above the current one with its direction when their turns differ (요구 이력 82)', async ($, on) => {
  engine(on, { state: 'idle', turn: 0 }, true, TWO)
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  const ui = await mountPane($, { ...PANE, surface: 'terminal' })
  const all: string[] = (await ui.findAll({ type: 'Text' })).map((x: any) => String(x.text ?? ''))
  const at = (re: RegExp) => all.findIndex(t => re.test(t))
  expect(at(/^목표\s+처음 #1$/)).toBeGreaterThanOrEqual(0)
  expect(at(/^\s+눈치 패널 노출 내용과/)).toBeGreaterThan(at(/^목표\s+처음 #1$/))
  expect(at(/^ 지금\s+#3부터 · 좁힘$/)).toBeGreaterThan(at(/^\s+눈치 패널 노출 내용과/))
  expect(at(/^\s+CHANGELOG 만들기$/)).toBeGreaterThan(at(/^ 지금/))
  await ui.unmount()
})

test('one goal layer when the first and current goals share a turn, even if their texts differ (요구 이력 82)', async ($, on) => {
  const same = { ...TWO, flow: { ...TWO.flow, current_goal: { text: 'CHANGELOG 만들기', turn: 1 } } }
  engine(on, { state: 'idle', turn: 0 }, true, same)
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  const ui = await mountPane($, { ...PANE, surface: 'terminal' })
  expect((await ui.find({ type: 'Text', text: /처음 #/ }))).toBeFalsy()
  expect((await ui.find({ type: 'Text', text: /^목표\s+#1부터$/ }))).toBeTruthy()
  await ui.unmount()
})

test('the two goal layers and the head read in English on an English screen (요구 이력 82)', async ($, on) => {
  langEngine(on, { setting: 'English', analysis: TWO, files: { [MOD]: '{"noticed":true}' } })
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  const ui = await mountPane($, { ...PANE, surface: 'terminal' })
  expect((await ui.find({ type: 'Text', text: /^Goal\s+first #1$/ }))).toBeTruthy()
  expect((await ui.find({ type: 'Text', text: /^ Now\s+since #3 · narrowed$/ }))).toBeTruthy()
  expect((await ui.find({ type: 'Text', text: /좁힘|처음|지금/ }))).toBeFalsy()
  await ui.unmount()
})

test('submitting a prompt runs the hook, and the head then says a new request is pending (요구 이력 82)', async ($, on) => {
  const since = '2026-11-18T04:00:00.000Z'
  const files: Record<string, string> = { '/sessions/abc/events.jsonl': JSON.stringify({ ts: since, event: 'Stop' }) + '\n' }
  engine(on, { state: 'idle', turn: 0 }, true, { ...ANALYSIS, source_ts: since }, '', files)
  on('prompt.submit', (_: unknown, e: any) => ({ text: e.text }))
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  const pending = async () => {
    const ui = await mountPane($, { ...PANE, surface: 'terminal' })
    const got = !!(await ui.find({ type: 'Text', text: /새 요청 반영 전/ }))
    await ui.unmount()
    return got
  }
  expect(await pending()).toBe(false)
  files['/sessions/abc/events.jsonl'] += prompt('2026-11-18T04:01:00.000Z', '새 요청') + '\n'
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })   // 다시 그려도
  expect(await pending()).toBe(false)                                              // 알림 전에는 파일을 다시 읽지 않는다
  await $.prompt.submit({ text: '새 요청' })
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  expect(await pending()).toBe(true)                                               // 발화를 보내면 훅이 다시 읽게 한다
})

// 요구 이력 62·84: 켜짐 표시 세 상태(켜지 않음·켜짐·꺼짐), 끄기·상태·모르는 인자, 사람이 닫은 패널, 훅 기록 없음
const SDIR = '/home/me/.claude-control/sessions/abc'
function offWorld(on: any, o: { want?: unknown; analysis?: unknown; status?: unknown; events?: boolean; setting?: string; answers?: (string | null)[]; panes?: string[] } = {}) {
  const w = {
    files: { [MOD]: '{"noticed":true}' } as Record<string, string>,
    opened: [] as string[], titles: [] as string[], closed: [] as string[], registered: [] as any[], asked: [] as any[], now: 100000, events: o.events ?? true,
  }
  if (o.want !== undefined) w.files[SDIR + '/want'] = JSON.stringify(o.want)
  const answers = [...(o.answers ?? [])]
  on('command.register', (_: unknown, e: any) => { w.registered.push(e); return { value: { command: 'nunchi' } } })
  on('ui.open', (_: unknown, e: any) => { w.opened.push(String(e.id)); w.titles.push(String(e.title)); return { value: { isPlaced: true } } })
  on('ui.close', (_: unknown, e: any) => { w.closed.push(String(e.id)); return { value: undefined } })
  on('ui.panes', () => ({ value: (o.panes ?? []).map(id => ({ id, title: '', isShown: true, isFocused: false, isPlaced: true })) }))
  on('session.start', (_: unknown, e: any) => ({ cwd: e.cwd }))
  on('session.id', () => ({ value: 'abc' }))
  on('settings.read', () => ({ value: { language: o.setting ?? '한국어' } }))
  on('env.get', (_: unknown, e: any) => ({ value: e.name === 'HOME' ? '/home/me' : undefined }))
  on('clock.every', () => ({ value: null }))
  on('clock.now', () => ({ value: w.now }))
  on('prompt.submit', (_: unknown, e: any) => ({ text: e.text }))
  on('fs.write', (_: unknown, e: any) => { w.files[String(e.path)] = String(e.text ?? ''); return { value: undefined } })
  on('fs.exists', (_: unknown, e: any) => ({ value: String(e.path ?? e).endsWith('/events.jsonl') ? w.events : String(e.path ?? e) in w.files }))
  on('process.run', () => ({ value: { exitCode: 0, stdout: '', stderr: '' } }))
  on('fs.read', (_: unknown, e: any) => {
    const p = String(e.path ?? e)
    if (p in w.files) return { value: w.files[p] }
    if (p.endsWith('/sessions/abc/analysis.json') && o.analysis !== null) return { value: JSON.stringify(o.analysis ?? { ...ANALYSIS, analyzed_at: '2026-11-18T05:07:00Z' }) }
    if (p.endsWith('/sessions/abc/analysis_status.json')) return { value: JSON.stringify(o.status ?? { state: 'idle', turn: 0 }) }
    throw new Error('missing ' + p)
  })
  on('tool.call', (_: unknown, e: any) => {
    w.asked.push(e)
    const a = answers.shift()
    if (a == null) return { deny: 'esc' }
    return { result: { answers: { [String(e.questions?.[0]?.question ?? '')]: a } } }
  })
  return w
}
const wantIn = (w: { files: Record<string, string> }) => JSON.parse(w.files[SDIR + '/want'] ?? 'null')
const BAND = { plugin: 'nunchi', component: 'AbovePrompt', surface: 'terminal',
  props: { hasSurvey: false, isCollapsed: false, isWorking: false, maxRows: 3, bodyColumns: 120 }, viewport: { columns: 200, rows: 50 } } as any

test('/nunchi registers with every argument in the hint and runs mid-turn (요구 이력 84)', async ($, on) => {
  const w = offWorld(on, { analysis: null })
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  expect(w.registered[0]?.argumentHint).toBe('[on|off|status|language|build]')
  expect(w.registered[0]?.immediate).toBe(true)
  await (await mountPane($, { ...PANE, surface: 'terminal' })).unmount()   // 열었다 닫아 남은 비동기 일을 정리한다
})

test('/nunchi off keeps the language, closes the pane, and says the result stays (요구 이력 62·84)', async ($, on) => {
  const w = offWorld(on, { want: { at: 'x', by: 'nunchi', lang: 'en' } })
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  expect(w.opened).toContain('nunchi')                                  // 켠 세션은 저절로 열린다
  const r = await $.command.run({ command: 'nunchi', args: 'off' } as any)
  expect(wantIn(w)).toMatchObject({ on: false, lang: 'en', by: 'nunchi' })
  expect(w.closed).toEqual(['nunchi'])
  expect(String(r.text)).toBe('눈치를 껐습니다. 이 세션은 더 분석하지 않습니다(결과는 #3 응답까지 반영한 그대로 남깁니다). 다시 켜려면 /nunchi')
  await (await mountPane($, { ...PANE, surface: 'terminal' })).unmount()   // 열었다 닫아 남은 비동기 일을 정리한다
})

test('a turned-off session with a result opens no pane and shows no band, even on a wide window (요구 이력 84)', async ($, on) => {
  const w = offWorld(on, { want: { at: 'x', on: false } })
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  expect(w.opened.length).toBe(0)
  const band = await $.ui.mount(BAND)
  expect((await band.find({ type: 'Text', text: /목표/ }))).toBeFalsy()
  await band.unmount()
  expect(w.opened.length).toBe(0)                                       // 넓은 창에서도 다시 열지 않는다
  await (await mountPane($, { ...PANE, surface: 'terminal' })).unmount()   // 열었다 닫아 남은 비동기 일을 정리한다
})

test('/nunchi turns a turned-off session back on and says it picks up again (요구 이력 84)', async ($, on) => {
  const w = offWorld(on, { want: { at: 'x', on: false, lang: 'ko' } })
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  const r = await $.command.run({ command: 'nunchi', args: 'on' } as any)
  expect(wantIn(w)).toMatchObject({ on: true, lang: 'ko' })
  expect(w.opened).toContain('nunchi')
  expect(String(r.text)).toBe('눈치를 다시 켰습니다. 다음 응답이 끝나면 이어서 분석합니다.')
  await (await mountPane($, { ...PANE, surface: 'terminal' })).unmount()   // 열었다 닫아 남은 비동기 일을 정리한다
})

test('/nunchi status answers five lines without opening or writing anything (요구 이력 62·84)', async ($, on) => {
  const w = offWorld(on, { want: { at: 'x', on: true } })
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  const before = JSON.stringify(w.files), opens = w.opened.length
  const r = await $.command.run({ command: 'nunchi', args: 'status' } as any)
  const lines = String(r.text).split('\n')
  expect(lines.length).toBe(5)
  expect(lines[0]).toBe('눈치  켜짐 · 응답이 끝날 때마다 분석')
  expect(lines[1]).toMatch(/^분석  #3 응답까지 반영 · \d\d:\d\d$/)
  expect(lines[2]).toBe('상태  쉼')
  expect(lines[3]).toBe('훅    기록 있음')                            // 기록 파일이 있으면 발화 전이라도 확인된 것
  expect(lines[4]).toBe('언어  한국어 (Claude Code 설정)')
  expect(JSON.stringify(w.files)).toBe(before)
  expect(w.opened.length).toBe(opens)
  await (await mountPane($, { ...PANE, surface: 'terminal' })).unmount()   // 열었다 닫아 남은 비동기 일을 정리한다
})

test('/nunchi status tells a turned-off session from one never turned on (요구 이력 84)', async ($, on) => {
  const w = offWorld(on, { want: { at: 'x', on: false }, analysis: null, status: { state: 'queued', turn: 0 }, events: false })
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  const r = String((await $.command.run({ command: 'nunchi', args: 'status' } as any)).text).split('\n')
  expect(r[0]).toBe('눈치  꺼짐 · /nunchi로 다시 켜기')
  expect(r[3]).toBe('훅    아직 모름 · 첫 응답이 끝나면 확인')    // 기록이 없어도 발화를 보기 전에는 없다고 하지 않는다
  expect(r[1]).toBe('분석  아직 없음')
  expect(r[2]).toBe('상태  분석 대기')
  delete w.files[SDIR + '/want']
  const r2 = String((await $.command.run({ command: 'nunchi', args: 'status' } as any)).text).split('\n')
  expect(r2[0]).toBe('눈치  켜지 않음 · /nunchi로 켜기')
  await (await mountPane($, { ...PANE, surface: 'terminal' })).unmount()   // 열었다 닫아 남은 비동기 일을 정리한다
})

test('an unknown argument changes nothing and lists the commands (요구 이력 84)', async ($, on) => {
  const w = offWorld(on, { analysis: null })
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  const r = await $.command.run({ command: 'nunchi', args: 'of' } as any)
  expect(wantIn(w)).toBe(null)
  expect(w.opened.length).toBe(0)
  const lines = String(r.text).split('\n')
  expect(lines[0]).toBe('모르는 명령입니다: of')
  expect(lines.slice(1).map(l => l.split(/\s{2,}/)[0])).toEqual(['/nunchi', '/nunchi off', '/nunchi status', '/nunchi language', '/nunchi build'])
  await (await mountPane($, { ...PANE, surface: 'terminal' })).unmount()   // 열었다 닫아 남은 비동기 일을 정리한다
})

test('a pane the person closed is not opened by itself again until /nunchi (요구 이력 84)', async () => {
  // 시험 도구의 $.ui에는 close가 없고, 시험이 불러온 모듈은 엔진이 돌리는 모듈과 따로라 판단 함수를 직접 시험한다
  const v = { ...JSON.parse(JSON.stringify({})), basis: 3, goal: 'x', on: true, off: false } as any
  expect(mayAutoOpen(v)).toBe(true)
  paneClosed({ id: 'other', origin: { kind: 'person' } })               // 다른 패널은 상관없다
  paneClosed({ id: 'nunchi', origin: { kind: 'plugin' } })              // 끄기의 닫기는 off가 막는다
  paneClosed({ id: 'nunchi', origin: { kind: 'unload' } })
  expect(mayAutoOpen(v)).toBe(true)
  paneClosed({ id: 'nunchi', origin: { kind: 'person' } })
  expect(mayAutoOpen(v)).toBe(false)
  paneAsked()                                                            // /nunchi
  expect(mayAutoOpen(v)).toBe(true)
  expect(mayAutoOpen({ ...v, off: true })).toBe(false)                  // 끈 세션은 결과가 있어도 열지 않는다
  expect(mayAutoOpen({ ...v, on: false, basis: 0, goal: '' })).toBe(false)
})

test('a turned-on session reopens on a wide window when the pane is missing (요구 이력 53)', async ($, on) => {
  const w = offWorld(on, { want: { at: 'x', on: true } })
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  const n = w.opened.length
  const band = await $.ui.mount(BAND)
  expect((await band.find({ type: 'Text', text: /목표/ }))).toBeTruthy()
  await band.unmount()
  expect(w.opened.length).toBeGreaterThan(n)
  await (await mountPane($, { ...PANE, surface: 'terminal' })).unmount()   // 열었다 닫아 남은 비동기 일을 정리한다
})

test('the no-hook line waits until a prompt was seen, then shows while the record is missing (요구 이력 84)', async ($, on) => {
  const w = offWorld(on, { want: { at: 'x', on: true }, events: false })
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  const red = async () => {
    const ui = await mountPane($, { ...PANE, surface: 'terminal' })
    const got = !!(await ui.find({ type: 'Text', text: /훅 기록 없음 · 세션 다시 시작/ }))
    await ui.unmount()
    return got
  }
  expect(await red()).toBe(false)                     // 세션 도중 설치: 첫 발화 전에는 기록이 없어도 알리지 않는다
  const again = () => $.command.run({ command: 'nunchi', args: 'status' } as any)   // 다시 읽기 (세션 시작은 판정을 처음으로 되돌린다)
  await $.prompt.submit({ text: '다음 요청' })
  await again()
  expect(await red()).toBe(false)                     // 훅이 적을 시간을 준다
  w.now += 6000
  await again()
  expect(await red()).toBe(true)
  const st = String((await again()).text).split('\n')
  expect(st[3]).toBe('훅    기록 없음 · 세션 다시 시작 (claude --resume)')   // 이름 '훅'이 두 번 나오지 않는다
  const r = await $.command.run({ command: 'nunchi' } as any)
  expect(String(r.text)).toMatch(/훅 기록이 없어 분석이 돌지 않습니다/)
  w.events = true
  await again()
  expect(await red()).toBe(false)                     // 기록이 생기면 사라진다
  await (await mountPane($, { ...PANE, surface: 'terminal' })).unmount()   // 열었다 닫아 남은 비동기 일을 정리한다
})

test('/nunchi language in a turned-off session does not offer a rebuild (요구 이력 84)', async ($, on) => {
  const w = offWorld(on, { want: { at: 'x', on: false, lang: 'ko' }, answers: ['English'] })
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  const r = await $.command.run({ command: 'nunchi', args: 'language' } as any)
  expect(w.asked.length).toBe(1)                      // 언어만 묻고 다시 분석은 묻지 않는다
  expect(String(r.text)).toMatch(/Nunchi is off here, so nothing is rebuilt/)
  expect(wantIn(w)).toMatchObject({ on: false, lang: 'en' })
  await (await mountPane($, { ...PANE, surface: 'terminal' })).unmount()   // 열었다 닫아 남은 비동기 일을 정리한다
})

test('the command description, off, status and usage read in English on an English screen (요구 이력 76·84)', async ($, on) => {
  const w = offWorld(on, { want: { at: 'x', on: true }, setting: 'English',
    analysis: { ...ANALYSIS, analyzed_at: '2026-11-18T05:07:00Z', flow: { ...ANALYSIS.flow, lang: 'en' } } })   // 영어로 분석된 세션
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  expect(w.registered.at(-1)?.description).toBe('Turn on Nunchi: analyze this session and open the panel · off · status · language · build')
  const st = String((await $.command.run({ command: 'nunchi', args: 'status' } as any)).text).split('\n')
  expect(st[0]).toBe('Nunchi    on · analyzes after every answer')
  expect(st[1]).toMatch(/^Analysis  through answer #3 · \d\d:\d\d$/)
  expect(st[2]).toBe('State     idle')
  expect(st[3]).toBe('Hooks     recording')
  expect(st[4]).toBe('Language  English (Claude Code setting)')
  const u = String((await $.command.run({ command: 'nunchi', args: 'stop' } as any)).text).split('\n')
  expect(u[0]).toBe('Unknown command: stop')
  expect(u[2]).toBe('/nunchi off        turn off · close the panel')
  const off = await $.command.run({ command: 'nunchi', args: 'off' } as any)
  expect(String(off.text)).toBe('Turned Nunchi off. This session is no longer analyzed (the result through answer #3 stays as it is). Run /nunchi to turn it back on.')
  const back = await $.command.run({ command: 'nunchi' } as any)
  expect(String(back.text)).toBe('Turned Nunchi back on. It picks up the analysis after the next answer.')
  for (const t of [...st, ...u, String(off.text), String(back.text)]) expect(t).not.toMatch(/[가-힣]/)   // 한글이 섞이지 않는다
  await (await mountPane($, { ...PANE, surface: 'terminal' })).unmount()   // 열었다 닫아 남은 비동기 일을 정리한다
})

test('switching the language mid-session registers the command again in the new language (요구 이력 84)', async ($, on) => {
  const w = offWorld(on, { want: { at: 'x', on: true }, answers: ['English', '그대로 두기 (새 세션부터 English)'] })
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  expect(w.registered.at(-1)?.description).toBe('눈치 켜기: 이 세션을 분석하고 패널을 연다 · off 끄기 · status 상태 · language 언어 · build 지금까지 분석')
  const n = w.registered.length
  await $.command.run({ command: 'nunchi', args: 'language' } as any)
  expect(w.registered.length).toBe(n + 1)
  expect(w.registered.at(-1)).toMatchObject({ name: 'nunchi', argumentHint: '[on|off|status|language|build]', immediate: true,
    description: 'Turn on Nunchi: analyze this session and open the panel · off · status · language · build' })
  await $.command.run({ command: 'nunchi', args: 'status' } as any)
  expect(w.registered.length).toBe(n + 1)                                // 언어가 그대로면 다시 등록하지 않는다
  await (await mountPane($, { ...PANE, surface: 'terminal' })).unmount()   // 열었다 닫아 남은 비동기 일을 정리한다
})

test('switching the language retitles an open pane, and never opens a closed one (요구 이력 85)', async ($, on) => {
  const w = offWorld(on, { want: { at: 'x', on: true }, answers: ['English', '그대로 두기 (새 세션부터 English)'], panes: ['nunchi'] })
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  expect(w.titles.at(-1)).toBe('눈치')
  await $.command.run({ command: 'nunchi', args: 'language' } as any)
  expect(w.titles.at(-1)).toBe('Nunchi')
  await (await mountPane($, { ...PANE, surface: 'terminal' })).unmount()   // 열었다 닫아 남은 비동기 일을 정리한다
})

test('a language switch with the pane closed opens nothing (요구 이력 85)', async ($, on) => {
  const w = offWorld(on, { want: { at: 'x', on: true }, answers: ['English', '그대로 두기 (새 세션부터 English)'], panes: [] })
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  const n = w.opened.length
  await $.command.run({ command: 'nunchi', args: 'language' } as any)
  expect(w.opened.length).toBe(n)
  await (await mountPane($, { ...PANE, surface: 'terminal' })).unmount()   // 열었다 닫아 남은 비동기 일을 정리한다
})

// 요구 이력 86: 이 세션 검토(review/screens/panel-review.html)를 본뜬 결과. 새 흐름이라 단계마다 decision_by 칸이 있다
const SESSION = {
  last_turn: 11, analyzed_at: '2026-11-19T01:00:00Z',
  flow: {
    version: 3, until: 11,
    first_goal: { text: '설치 점검', turn: 1 }, current_goal: { text: '끄기·상태 마무리', turn: 9 },
    steps: [
      { index: 4, grounded: true, label: '확정', summary: '커밋', agent_summary: '', decision: '', decision_by: '' },                       // 순서 승인: 결정 아님
      { index: 5, grounded: true, label: '질문', summary: '버전', agent_summary: '', decision: '마켓 정보만 바꿀 때는 버전을 올리지 않음', decision_by: 'agent' },
      { index: 9, grounded: true, label: '확정', summary: '진행', agent_summary: '', decision: '끄기와 상태를 함께 만듦', decision_by: 'user' },
      { index: 11, grounded: true, label: '구체화', summary: '지침', agent_summary: '커밋과 배포를 물음', decision: '다국어 규칙을 지침 17번에 넣음', decision_by: 'user' },
    ],
    asks: [
      { id: 'Q2', turn: 3, last_turn: 9, summary: '다른 세션에서 입력해 보기', quote: '입력해 보시면', state: 'closed' },
      { id: 'Q3', turn: 6, last_turn: 6, summary: 'off만 만들지', quote: '함께 만들까요', state: 'open' },
      { id: 'Q5', turn: 8, last_turn: 9, summary: '230MB 복사본 지울지', quote: '지울까요?', state: 'open' },
      { id: 'Q8', turn: 9, last_turn: 11, summary: '커밋할지', quote: '커밋할까요?', state: 'open' },
      { id: 'Q9', turn: 9, last_turn: 9, summary: '시험 폴더 지울지', quote: '지울지 정해 주세요', state: 'open' },
      { id: 'Q10', turn: 11, last_turn: 11, summary: '0.5.1로 올려 배포할지', quote: '0.5.1로 올려 배포까지 할지', state: 'open' },
    ],
    requests: [
      { id: 'R1', from_turn: 7, summary: '계획 검토 결과 정리', state: 'deferred', agent_quote: '세 번째 항목은 다음에 보겠습니다' },
      { id: 'R2', from_turn: 11, by_turn: 11, summary: '흔들리는 패널 테스트 원인 찾기', state: 'no_result', agent_quote: '원인 못 찾음' },
    ],
  },
}
async function sessionPane($: any, on: any, setting = '한국어') {
  offWorld(on, { want: { at: 'x', on: true }, analysis: SESSION, setting })
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  const ui = await mountPane($, { ...PANE, surface: 'terminal' })
  const texts = async () => (await ui.findAll({ type: 'Text' })).map((x: any) => String(x.text ?? ''))
  return { ui, texts }
}

test('only the questions of the last answer show, newest first, and the earlier ones fold (요구 이력 86)', async ($, on) => {
  const { ui, texts } = await sessionPane($, on)
  let all = await texts()
  expect(all.filter(t => /^에이전트 질문 \d/.test(t))).toEqual(['에이전트 질문 2'])   // 줄 하나 (안쪽 글 조각은 숫자 없이 따로 잡힌다)
  const asked = all.filter(t => /^ \d .+#\d/.test(t))   // 번호 조각만 따로 잡힌 것은 뺀다
  expect(asked[0]).toMatch(/^ 1 0\.5\.1로 올려 배포할지 #11$/)              // 같은 턴이면 나중에 생긴 것이 위
  expect(asked[1]).toMatch(/^ 2 커밋할지 #11 · 처음 #9$/)                   // 마지막으로 물은 턴과 처음 물은 턴
  expect(asked.length).toBe(2)
  expect(all.some(t => /230MB|시험 폴더|off만/.test(t))).toBe(false)         // 지난 질문은 접힌다
  expect(all.some(t => /다른 세션/.test(t))).toBe(false)                     // 지나간 질문은 보이지 않는다
  expect((await ui.find({ type: 'Button', key: 'more-asks' }))?.text).toBe('지난 질문 3개')
  await ui.press({ key: 'more-asks' })
  all = await texts()
  expect(all.filter(t => /^ \d .+#\d/.test(t)).map(t => t.replace(/\s+#.*/, ''))).toEqual([' 1 0.5.1로 올려 배포할지', ' 2 커밋할지', ' 3 시험 폴더 지울지', ' 4 230MB 복사본 지울지', ' 5 off만 만들지'])   // 둘 다 #9면 나중에 생긴 Q9가 위
  expect((await ui.find({ type: 'Button', key: 'more-asks' }))?.text).toBe('접기')
  expect(all.some(t => /다른 세션/.test(t))).toBe(false)
  await ui.unmount()
})

test('decisions are the settled requirements, not order approvals, and an accepted proposal says so (요구 이력 86)', async ($, on) => {
  const { ui, texts } = await sessionPane($, on)
  const all = await texts()
  expect(all).toContain('결정 사항 3')
  const d = all.filter(t => /✔/.test(t))
  expect(d[0]).toMatch(/✔ 다국어 규칙을 지침 17번에 넣음\s+#11$/)            // 관계가 구체화여도 결정
  expect(d[1]).toMatch(/✔ 끄기와 상태를 함께 만듦\s+#9$/)
  expect(d[2]).toMatch(/✔ 마켓 정보만 바꿀 때는 버전을 올리지 않음/)
  expect(all.some(t => /^\s*#5 · 제안 승인$/.test(t))).toBe(true)              // 폭이 모자라 꼬리는 다음 줄 (요구 이력 80)
  expect(all.some(t => /커밋\s+#4/.test(t))).toBe(false)                     // 정해진 것이 없는 확정 턴은 넣지 않는다
  await ui.unmount()
})

test('a deferred request carries the agent\'s words, and an investigation without a result is a known issue (요구 이력 86)', async ($, on) => {
  const { ui, texts } = await sessionPane($, on)
  const all = await texts()
  expect(all).toContain('남은 요청 1 내 요청 중')
  expect(all.some(t => /⊘ 계획 검토 결과 정리 #7$/.test(t))).toBe(true)      // 원문이 있으면 고정 문구는 붙이지 않는다
  expect(all.some(t => /^\s+“세 번째 항목은 다음에 보겠습니다”$/.test(t))).toBe(true)
  expect(all.some(t => /못 했거나 미룸/.test(t))).toBe(false)
  expect(all).toContain('알려진 문제 1')
  expect(all.some(t => /◇ 흔들리는 패널 테스트 원인 찾기 #11$/.test(t))).toBe(true)
  expect(all.some(t => /^\s+“원인 못 찾음”$/.test(t))).toBe(true)
  await ui.unmount()
})

test('the new question, decision and known-issue labels read in English on an English screen (요구 이력 86)', async ($, on) => {
  const { ui, texts } = await sessionPane($, on, 'English')
  const all = await texts()
  expect(all).toContain('Agent questions 2')
  expect(all.some(t => /^ 2 커밋할지 #11 · first #9$/.test(t))).toBe(true)
  expect((await ui.find({ type: 'Button', key: 'more-asks' }))?.text).toBe('3 earlier questions')
  expect(all.some(t => /#5 · approved proposal$/.test(t))).toBe(true)
  expect(all).toContain('Known issues 1')
  for (const t of all.filter(t => /^(Agent questions|Decisions|Open requests|Known issues)/.test(t))) expect(t).not.toMatch(/[가-힣]/)
  await ui.unmount()
})

test('a turn can settle several requirements, newest turn first, and an accepted proposal says so (요구 이력 87)', async ($, on) => {
  const listed = { ...SESSION, flow: { ...SESSION.flow, steps: [
    { index: 4, grounded: true, label: '확정', summary: '커밋', agent_summary: '', decisions: [{ text: '플러그인은 HTTPS 주소로 받는다', by: 'agent', quote: '커밋하고 푸시해줘' }] },
    { index: 9, grounded: true, label: '확정', summary: '진행', agent_summary: '', decisions: [] },                                   // 순서 승인만: 결정 없음
    { index: 14, grounded: true, label: '확정', summary: '답', agent_summary: '', decisions: [
      { text: '에이전트 질문은 제목을 두고 지난 질문은 접는다', by: 'user', quote: '지난 질문은 펼치기' },
      { text: '의사결정은 설계 요건만 담는다', by: 'agent', quote: '2. 좋아.' }] },
  ] } }
  offWorld(on, { want: { at: 'x', on: true }, analysis: listed })
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  const ui = await mountPane($, { ...PANE, props: { ...PANE.props, bodyColumns: 95 }, surface: 'terminal' })
  const all = (await ui.findAll({ type: 'Text' })).map((x: any) => String(x.text ?? ''))
  expect(all).toContain('결정 사항 3')
  const d = all.filter(t => /✔/.test(t))
  expect(d[0]).toMatch(/✔ 에이전트 질문은 제목을 두고 지난 질문은 접는다\s+#14-1$/)          // 한 턴에 둘이면 턴-순번 (요구 이력 90)
  expect(d[1]).toMatch(/✔ 의사결정은 설계 요건만 담는다\s+#14-2 · 제안 승인$/)
  expect(d[2]).toMatch(/✔ 플러그인은 HTTPS 주소로 받는다\s+#4 · 제안 승인$/)
  expect(all.some(t => /#9/.test(t) && /✔/.test(t))).toBe(false)
  await ui.unmount()
})

// 요구 이력 88: 펼치기는 지금 보이는 항목의 잘린 글만 풀고, 숨은 항목(… n개 더)은 그대로. 새 분석이 오면 기본 줄 수로
test('Expand un-cuts only the shown items, never the hidden ones, and folds back on a new analysis (요구 이력 88)', async ($, on) => {
  const long = (i: number) => `결정 ${i}: 패널 글은 한국어와 영어 문구 표에 둘 다 넣고 세션 도중 언어를 바꾸면 패널 제목과 명령 설명도 다시 등록하며 영어 화면 시험을 함께 넣고 실제 화면도 두 언어로 확인한다 끝${i}`   // 46칸 3줄을 넘는다
  const steps = [1, 2, 3, 4, 5].map(i => ({ index: i, grounded: true, label: '구체화', summary: `s${i}`, agent_summary: '', decisions: [{ text: long(i), by: 'user', quote: 'q' }] }))
  const live: any = { ...SESSION, last_turn: 5, flow: { ...SESSION.flow, until: 5, steps, asks: [], requests: [] } }
  offWorld(on, { want: { at: 'x', on: true }, analysis: live })
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  const ui = await mountPane($, { ...PANE, props: { ...PANE.props, bodyColumns: 46 }, surface: 'terminal' })
  const texts = async () => (await ui.findAll({ type: 'Text' })).map((x: any) => String(x.text ?? ''))
  let all = await texts()
  expect(all.some(t => /끝5/.test(t))).toBe(false)                                   // 3줄에서 잘림
  expect((await ui.find({ type: 'Button', key: 'text-decisions' }))?.text).toBe('펼치기')
  expect((await ui.find({ type: 'Button', key: 'more-decisions' }))?.text).toBe('… 2개 더')
  await ui.press({ key: 'text-decisions' })
  all = await texts()
  expect(all.some(t => /끝5/.test(t)) && all.some(t => /끝4/.test(t)) && all.some(t => /끝3/.test(t))).toBe(true)   // 보이는 3개는 다 보인다
  expect(all.some(t => /결정 2:|결정 1:/.test(t))).toBe(false)                           // 숨은 2개는 그대로 숨는다
  expect((await ui.find({ type: 'Button', key: 'more-decisions' }))?.text).toBe('… 2개 더')
  expect((await ui.find({ type: 'Button', key: 'text-decisions' }))?.text).toBe('줄이기')
  live.last_turn = 6; live.flow = { ...live.flow, until: 6 }                             // 새 분석 (기준 턴이 바뀜)
  await $.command.run({ command: 'nunchi', args: 'status' } as any)                     // 다시 읽기
  all = await texts()
  expect(all.some(t => /끝5/.test(t))).toBe(false)                                       // 기본 줄 수로 돌아간다
  expect((await ui.find({ type: 'Button', key: 'text-decisions' }))?.text).toBe('펼치기')
  await ui.unmount()
})

test('the handled block and its buttons read in English on an English screen, without Expand (요구 이력 88)', async ($, on) => {
  const quiet = { ...SESSION, flow: { ...SESSION.flow, requests: [{ id: 'R9', from_turn: 11, by_turn: 11, summary: 'a very long request summary that will not fit on one narrow line at all', state: 'addressed', agent_quote: 'done' }] } }
  offWorld(on, { want: { at: 'x', on: true }, analysis: quiet, setting: 'English' })
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  const ui = await mountPane($, { ...PANE, props: { ...PANE.props, bodyColumns: 46 }, surface: 'terminal' })
  const all = (await ui.findAll({ type: 'Text' })).map((x: any) => String(x.text ?? ''))
  expect(all).toContain('Handled #11')
  expect((await ui.find({ type: 'Button', key: 'text-handled' }))?.text).toBe('Full text')
  await ui.press({ key: 'text-handled' })
  expect((await ui.find({ type: 'Button', key: 'text-handled' }))?.text).toBe('Shorten')
  await ui.unmount()
})

// 요구 이력 89: 바뀐 결정은 숨고, 처리 결과 맨 위에 '결정 #턴 바뀜: from → to'. 같은 구절의 요청은 그 줄이 대신한다. 처리 결과에는 인용이 없다
const CHANGED = {
  last_turn: 3, analyzed_at: '2026-11-19T06:00:00Z',
  flow: { version: 3, until: 3, first_goal: { text: 'status 다듬기', turn: 1 }, current_goal: { text: 'status 다듬기', turn: 1 },
    steps: [
      { index: 1, grounded: true, label: '시작', summary: 's1', agent_summary: '', decisions: [
        { id: 'D1-1', text: '/nunchi status는 다섯 줄로 답한다', by: 'user', quote: '다섯 줄로', replaces: [], from: '', to: '' },
        { id: 'D1-2', text: '줄 순서는 눈치·분석·상태·훅·언어', by: 'user', quote: '순서로', replaces: [], from: '', to: '' }] },
      { index: 2, grounded: true, label: '구체화', summary: 's2', agent_summary: '', decisions: [] },
      { index: 3, grounded: true, label: '확정', summary: 's3', agent_summary: '여섯 줄로 둠', decisions: [
        { id: 'D3-1', text: '/nunchi status 답은 여섯 줄로 한다', by: 'agent', quote: '상태 답은 여섯 줄로 바꾸자', replaces: ['D1-1'], from: '다섯 줄', to: '여섯 줄' }] },
    ],
    asks: [],
    requests: [
      { id: 'R3', from_turn: 3, by_turn: 3, summary: '상태 답을 여섯 줄로 바꾸기', quote: '상태 답은 여섯 줄로 바꾸자', state: 'addressed', agent_quote: '여섯 줄로 두겠습니다' },
      { id: 'R4', from_turn: 3, by_turn: 3, summary: '안내서 고치기', quote: '안내서도', state: 'addressed', agent_quote: '안내서도 고쳤습니다' },
    ] } }

test('a replaced decision is hidden and the handled block says what changed, without quotes (요구 이력 89)', async ($, on) => {
  offWorld(on, { want: { at: 'x', on: true }, analysis: CHANGED })
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  const ui = await mountPane($, { ...PANE, props: { ...PANE.props, bodyColumns: 60 }, surface: 'terminal' })
  const all = (await ui.findAll({ type: 'Text' })).map((x: any) => String(x.text ?? ''))
  expect(all).toContain('결정 사항 2')
  expect(all.some(t => /다섯 줄로 답한다/.test(t))).toBe(false)                         // 바뀐 옛 결정은 숨는다
  expect(all.some(t => /✔ \/nunchi status 답은 여섯 줄로 한다/.test(t))).toBe(true)      // 지금 정해진 내용만
  expect(all.some(t => /줄 순서는/.test(t))).toBe(true)                                   // 바뀌지 않은 결정은 남는다
  const h = all.filter(t => /^ [✔◐⊘○◇] /.test(t))   // 처리 결과 줄 (머리 줄의 ' · #n'은 빼고)
  expect(h[0]).toBe(' ✔ 결정 #1-1 바뀜: 다섯 줄 → 여섯 줄')                                 // 바뀜 줄이 맨 위, #1에 결정이 둘이라 #1-1 (요구 이력 90)
  expect(h.some(t => /여섯 줄로 바꾸기/.test(t))).toBe(false)                             // 같은 구절의 요청은 대신한다
  expect(h.some(t => /안내서 고치기/.test(t))).toBe(true)
  expect(all.some(t => /여섯 줄로 두겠습니다|안내서도 고쳤습니다/.test(t))).toBe(false)   // 처리 결과에는 인용이 없다
  expect((await ui.find({ type: 'Button', key: 'text-handled' }))).toBeFalsy()             // 잘린 것이 없으면 펼치기도 없다
  await ui.unmount()
})

test('the change line reads in English on an English screen, and falls back when what changed is unknown (요구 이력 89)', async ($, on) => {
  const unknown = JSON.parse(JSON.stringify(CHANGED))
  unknown.flow.steps[2].decisions[0].from = ''; unknown.flow.steps[2].decisions[0].to = ''
  offWorld(on, { want: { at: 'x', on: true }, analysis: unknown, setting: 'English' })
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  const ui = await mountPane($, { ...PANE, props: { ...PANE.props, bodyColumns: 90 }, surface: 'terminal' })   // 한 줄에 다 들어가게
  const all = (await ui.findAll({ type: 'Text' })).map((x: any) => String(x.text ?? ''))
  expect(all).toContain(' ✔ Decision #1-1 changed → /nunchi status 답은 여섯 줄로 한다')   // 바뀐 부분을 못 따면 새 결정 문장
  expect(all).toContain('Decisions 2')
  await ui.unmount()
})

// 요구 이력 87·89: 마지막 답이 지난 결정을 어기면 결정 줄의 ✔ 자리에 ⚠, 찾은 턴에만 처리 결과 맨 위에 ⚠ 줄, 그 결정 아래 프롬프트 복사
function broken(at: number, extra: any[] = [], checks: any[] = [{ id: 'D1-1', kind: '어김', what: '상태 문구가 한국어만', quote: '한국어로만' }]) {
  const many = [2, 3, 4, 5].map(i => ({ index: i, grounded: true, label: '구체화', summary: `s${i}`, agent_summary: '', decisions: [{ id: `D${i}-1`, text: `요건 ${i}`, by: 'user', quote: 'q', replaces: [], from: '', to: '' }] }))
  return { last_turn: at, analyzed_at: '2026-11-19T06:00:00Z', flow: { version: 3, until: at, first_goal: { text: 'g', turn: 1 }, current_goal: { text: 'g', turn: 1 },
    steps: [
      { index: 1, grounded: true, label: '시작', summary: 's1', agent_summary: '', decisions: [{ id: 'D1-1', text: '보이는 글은 모두 한국어·영어로 둔다', by: 'user', quote: 'q', replaces: [], from: '', to: '' }] },
      ...many,
      { index: 6, grounded: true, label: '구체화', summary: 's6', agent_summary: '상태 줄 추가', decisions: [], checks },
      ...extra,
    ], asks: [], requests: [] } }
}
async function copyWorld(on: any, analysis: any, isCopied: boolean, setting = '한국어') {
  const copied: any[] = [], toasts: string[] = []
  offWorld(on, { want: { at: 'x', on: true }, analysis, setting })
  on('ui.copy', (_: unknown, e: any) => { copied.push(e); return { value: isCopied ? { isCopied: true } : { isCopied: false, reason: 'no-clipboard' } } })
  on('ui.toast', (_: unknown, e: any) => { toasts.push(String(e.text ?? e)); return { value: undefined } })
  return { copied, toasts }
}

test('a broken decision shows ⚠ in place of ✔, stays visible when folded, and offers only a copy button (요구 이력 87·89)', async ($, on) => {
  const { copied, toasts } = await copyWorld(on, broken(6), true)
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  const ui = await mountPane($, { ...PANE, props: { ...PANE.props, bodyColumns: 70 }, surface: 'terminal' })
  const all = (await ui.findAll({ type: 'Text' })).map((x: any) => String(x.text ?? ''))
  expect(all.some(t => /⚠ 보이는 글은 모두 한국어·영어로 둔다\s+#1 · #6 어김$/.test(t))).toBe(true)   // 최근 3개(5·4·3) 밖이어도 보인다
  expect(all.some(t => /✔ 보이는 글은/.test(t))).toBe(false)
  expect((await ui.find({ type: 'Button', key: 'copy-D1-1' }))).toBeFalsy()                          // 결정 줄 아래에는 버튼이 없다 (요구 이력 90)
  expect((await ui.find({ type: 'Button', key: 'copy-prompt' }))?.text).toBe('프롬프트 복사')           // 처리 결과에 하나
  expect(all.some(t => /결정대로 고쳐 줘/.test(t))).toBe(false)                                       // 요청 글은 보이지 않는다
  const hs = all.filter(t => /^ [✔◐⊘○◇⚠] \S/.test(t))
  expect(hs[0]).toBe(' ⚠ 열린 빠뜨림 1')                                                              // 개수 줄이 늘 첫 줄, 버튼은 여기 (요구 이력 90)
  expect(hs[1]).toBe(' ⚠ 결정 #1 어김: 상태 문구가 한국어만')                                          // 찾은 턴에는 상세 줄
  await ui.press({ key: 'copy-prompt' })
  expect(copied[0]?.text).toBe('앞서 정한 결정이 지켜지지 않았어. 결정: "보이는 글은 모두 한국어·영어로 둔다". 어긋난 점: 상태 문구가 한국어만 (네가 쓴 말: "한국어로만"). 결정대로 고쳐 줘.')   // 번호 대신 에이전트가 쓴 말
  expect(toasts.at(-1)).toBe('복사했습니다 · 입력창에 붙여 넣으세요')
  expect((await ui.findAll({ type: 'Text' })).some((x: any) => /결정대로 고쳐 줘/.test(String(x.text ?? '')))).toBe(false)
  await ui.unmount()
})

test('when copying fails the request text appears under ⚠ so it can be dragged (요구 이력 89)', async ($, on) => {
  const { toasts } = await copyWorld(on, broken(6), false)
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  const ui = await mountPane($, { ...PANE, props: { ...PANE.props, bodyColumns: 70 }, surface: 'terminal' })
  await ui.press({ key: 'copy-prompt' })
  expect(toasts.at(-1)).toBe('복사하지 못했습니다 · 아래 글을 끌어서 복사하세요')
  const all = (await ui.findAll({ type: 'Text' })).map((x: any) => String(x.text ?? '')).join('\n')
  expect(all).toMatch(/앞서 정한 결정이 지켜지지 않았어/)
  await ui.unmount()
})

test('after the found turn only the decision keeps ⚠, and a fix turns it back to ✔ (요구 이력 87·89)', async ($, on) => {
  const later = broken(7, [{ index: 7, grounded: true, label: '구체화', summary: 's7', agent_summary: '다른 일', decisions: [] }])
  const w = offWorld(on, { want: { at: 'x', on: true }, analysis: later })
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  let ui = await mountPane($, { ...PANE, props: { ...PANE.props, bodyColumns: 70 }, surface: 'terminal' })
  let all = (await ui.findAll({ type: 'Text' })).map((x: any) => String(x.text ?? ''))
  expect(all.some(t => /⚠ 보이는 글은/.test(t))).toBe(true)
  expect(all.some(t => /^ ⚠ 결정 #1/.test(t))).toBe(false)                                            // 처리 결과의 ⚠ 줄은 찾은 턴에만
  expect(all).toContain(' ⚠ 열린 빠뜨림 1 · #6부터')                                                 // 그 뒤에는 열린 빠뜨림 줄과 버튼 하나, 언제부터인지 (요구 이력 90)
  expect((await ui.find({ type: 'Button', key: 'copy-prompt' }))?.text).toBe('프롬프트 복사')
  await ui.unmount()
  void w
})

test('a fix closes ⚠ and the handled block says it was fixed; an English screen reads in English (요구 이력 87·89)', async ($, on) => {
  const fixed = broken(7, [{ index: 7, grounded: true, label: '정정', summary: 's7', agent_summary: '고침', decisions: [], checks: [{ id: 'D1-1', kind: '고침', what: '영어 글 표에도 넣음', quote: '넣었습니다' }] }])
  offWorld(on, { want: { at: 'x', on: true }, analysis: fixed, setting: 'English' })
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  const ui = await mountPane($, { ...PANE, props: { ...PANE.props, bodyColumns: 70 }, surface: 'terminal' })
  const all = (await ui.findAll({ type: 'Text' })).map((x: any) => String(x.text ?? ''))
  expect(all.some(t => /⚠/.test(t))).toBe(false)
  expect(all).toContain(' ✔ Decision #1 fixed: 영어 글 표에도 넣음')
  expect((await ui.find({ type: 'Button', key: 'copy-prompt' }))).toBeFalsy()                        // 열린 빠뜨림이 없으면 버튼도 없다
  await ui.unmount()
})

test('the ⚠ tag, copy button and toasts read in English (요구 이력 89)', async ($, on) => {
  const en: any = broken(6, [], [{ id: 'D1-1', kind: '빠뜨림', what: 'status lines', quote: 'q' }]); en.flow.lang = 'en'   // 영어로 분석된 세션: 복사 글 틀도 분석 언어
  const { copied, toasts } = await copyWorld(on, en, true, 'English')
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  const ui = await mountPane($, { ...PANE, props: { ...PANE.props, bodyColumns: 80 }, surface: 'terminal' })
  const all = (await ui.findAll({ type: 'Text' })).map((x: any) => String(x.text ?? ''))
  expect(all.some(t => /#1 · missed in #6$/.test(t))).toBe(true)
  expect(all).toContain(' ⚠ Decision #1 missed: status lines')
  expect((await ui.find({ type: 'Button', key: 'copy-prompt' }))?.text).toBe('Copy prompt')
  await ui.press({ key: 'copy-prompt' })
  expect(String(copied[0]?.text)).toBe('An earlier decision was not followed. Decision: "보이는 글은 모두 한국어·영어로 둔다". What was missed: status lines (you wrote: "q"). Please fix it to match the decision.')
  expect(toasts.at(-1)).toBe('Copied · paste it into the prompt')
  await ui.unmount()
})

test('one copy prompt covers every open omission, and a pasted fix request does not repeat the fix line (요구 이력 90)', async ($, on) => {
  const two = broken(6, [], [{ id: 'D1-1', kind: '어김', what: '상태 문구가 한국어만', quote: 'q' }, { id: 'D2-1', kind: '빠뜨림', what: '시험을 안 넣음', quote: 'q' }])
  const { copied } = await copyWorld(on, two, true)
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  const ui = await mountPane($, { ...PANE, props: { ...PANE.props, bodyColumns: 80 }, surface: 'terminal' })
  expect((await ui.findAll({ type: 'Button', key: 'copy-prompt' })).length).toBe(1)
  await ui.press({ key: 'copy-prompt' })
  expect(String(copied[0]?.text).split('\n')).toEqual([
    '앞서 정한 결정 2개가 지켜지지 않았어. 결정대로 고쳐 줘.',
    '1) 결정: "보이는 글은 모두 한국어·영어로 둔다" / 어긋난 점: 상태 문구가 한국어만 (네가 쓴 말: "q")',
    '2) 결정: "요건 2" / 빠진 점: 시험을 안 넣음 (네가 쓴 말: "q")'])
  await ui.unmount()
})

test('in a fix turn the pasted fix request is not listed again beside the fix line (요구 이력 90)', async ($, on) => {
  const fixed: any = broken(7, [{ index: 7, grounded: true, label: '정정', summary: 's7', agent_summary: '고침', decisions: [], checks: [{ id: 'D1-1', kind: '고침', what: '영어도 넣음', quote: 'q' }] }])
  fixed.flow.requests = [{ id: 'R9', from_turn: 7, by_turn: 7, summary: '결정대로 되돌리기', quote: '결정대로 고쳐 줘', state: 'addressed' },
                         { id: 'R10', from_turn: 7, by_turn: 7, summary: '안내서 고치기', quote: '안내서도', state: 'addressed' }]
  offWorld(on, { want: { at: 'x', on: true }, analysis: fixed })
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  const ui = await mountPane($, { ...PANE, props: { ...PANE.props, bodyColumns: 80 }, surface: 'terminal' })
  const h = (await ui.findAll({ type: 'Text' })).map((x: any) => String(x.text ?? '')).filter((t: string) => /^ [✔◐⊘○◇⚠] \S/.test(t))   // 색칠한 표시 조각만 따로 잡힌 것은 뺀다
  expect(h).toEqual([' ✔ 결정 #1 고침: 영어도 넣음', ' ✔ 안내서 고치기'])
  await ui.unmount()
})

for (const [setting, want] of [['한국어', '남은 요청 없음'], ['English', 'Open requests none']] as const) test(`with no open requests the heading has no "of mine" tail (${setting}, 요구 이력 92)`, async ($, on) => {
  offWorld(on, { want: { at: 'x', on: true }, analysis: { ...SESSION, flow: { ...SESSION.flow, requests: [] } }, setting })
  await $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
  const ui = await mountPane($, { ...PANE, surface: 'terminal' })
  const all = (await ui.findAll({ type: 'Text' })).map((x: any) => String(x.text ?? ''))
  expect(all).toContain(want)
  expect(all.some(t => /none of mine|없음 내 요청 중/.test(t))).toBe(false)
  await ui.unmount()
})
// /clear는 새 세션 ID를 만든다(요구 이력 100: 새 세션은 꺼진 채 시작). 세션 ID를 바꿔 가며 시험하는 준비
const HOME_S = '/home/me/.claude-control/sessions/'
function clearing(on: any, o: { setting?: string; files: Record<string, string>; written: Record<string, string> }) {
  const s = { id: 'old', now: 100_000 }
  on('command.register', () => ({ value: { command: 'nunchi' } }))
  on('ui.open', () => ({ value: { isPlaced: true } }))
  on('session.start', (_: unknown, e: any) => ({ cwd: e.cwd }))
  on('session.id', () => ({ value: s.id }))
  on('settings.read', () => ({ value: { language: o.setting ?? '한국어' } }))
  on('env.get', (_: unknown, e: any) => ({ value: e.name === 'HOME' ? '/home/me' : undefined }))
  on('clock.every', () => ({ value: null }))
  on('clock.now', () => ({ value: s.now }))
  on('fs.write', (_: unknown, e: any) => { o.files[String(e.path)] = String(e.text ?? e.content ?? e.data ?? ''); o.written[String(e.path)] = o.files[String(e.path)]; return { value: null } })
  on('fs.read', (_: unknown, e: any) => {
    const p = String(e.path ?? e)
    if (p in o.files) return { value: o.files[p] }
    if (p.endsWith('/mod.json')) return { value: '{"noticed":true}' }
    throw new Error('missing ' + p)
  })
  return s
}
const ON = (lang = 'en') => JSON.stringify({ at: 'x', by: 'nunchi', on: true, lang }) + '\n'

// 요구 이력 99: 새 세션의 패널 상태를 아직 한 번도 만들지 않았으면(첫 갱신 전, /clear 직후 등) 켜짐·꺼짐을 모르니 제목만 그린다.
// 세션을 시작하면 1초 갱신이 패널보다 먼저 돌아 그 순간을 잡을 수 없어, 시작 없이 패널만 붙인다
test('before the first refresh the pane shows only the title, not off (요구 이력 99)', async ($, on) => {
  const files: Record<string, string> = { [HOME_S + 'fresh-ko/want']: ON('ko') }, written: Record<string, string> = {}
  const s = clearing(on, { files, written })
  s.id = 'fresh-ko'
  const ui = await mountPane($, { ...PANE, surface: 'terminal' })
  const all = (await ui.findAll({ type: 'Text' })).map((x: any) => String(x.text ?? '')).filter(t => t.trim())
  expect(all).toContain('눈치')
  expect(all.some(t => /꺼짐|켜짐/.test(t))).toBe(false)
  await ui.unmount()
})

test('before the first refresh an English screen shows the English title only, with no Hangul (요구 이력 99)', async ($, on) => {
  const files: Record<string, string> = { [HOME_S + 'fresh-en/want']: ON('en') }, written: Record<string, string> = {}
  const s = clearing(on, { setting: 'English', files, written })
  s.id = 'fresh-en'
  await $.command.run({ command: 'nunchi', args: 'nope' } as any)   // 화면 언어만 정한다 (갱신하지 않는 답)
  const ui = await mountPane($, { ...PANE, surface: 'terminal' })
  const all = (await ui.findAll({ type: 'Text' })).map((x: any) => String(x.text ?? '')).filter(t => t.trim())
  expect(all).toContain('Nunchi')
  expect(all.some(t => /Nunchi (on|off)/.test(t))).toBe(false)
  for (const t of all) expect(t).not.toMatch(/[가-힣]/)
  await ui.unmount()
})
// 패널 상태를 세션 ID마다 따로 두고(실제 Claude Code처럼) 1초 갱신을 가짜 시계로 붙잡는다
function clearHeld(on: any, o: { setting?: string; files: Record<string, string> }) {
  const s = { id: 'old' }
  const clock = mock.clock(on, { now: 100_000 })
  const owner: Record<string, string> = {}
  on('state.get', async (_: unknown, e: any, next: any) => {
    const r = await next(e)
    return owner[e.key] === undefined || owner[e.key] === s.id ? r : { value: { version: r.value.version } }   // 다른 세션이 쓴 값은 없는 것으로
  })
  on('state.set', async (_: unknown, e: any, next: any) => { owner[e.key] = s.id; return next(e) })
  on('command.register', () => ({ value: { command: 'nunchi' } }))
  on('ui.open', () => ({ value: { isPlaced: true } }))
  on('session.start', (_: unknown, e: any) => ({ cwd: e.cwd }))
  on('session.id', () => ({ value: s.id }))
  on('settings.read', () => ({ value: { language: o.setting ?? '한국어' } }))
  on('env.get', (_: unknown, e: any) => ({ value: e.name === 'HOME' ? '/home/me' : undefined }))
  on('fs.write', (_: unknown, e: any) => { o.files[String(e.path)] = String(e.text ?? e.content ?? e.data ?? ''); return { value: null } })
  on('fs.read', (_: unknown, e: any) => {
    const p = String(e.path ?? e)
    if (p in o.files) return { value: o.files[p] }
    if (p.endsWith('/mod.json')) return { value: '{"noticed":true}' }
    throw new Error('missing ' + p)
  })
  return { s, clock }
}
const start = ($: any) => $.session.start({ cwd: '/', surface: 'terminal', isInteractive: true })
const shown = async ($: any) => {
  const ui = await mountPane($, { ...PANE, surface: 'terminal' })
  const all = (await ui.findAll({ type: 'Text' })).map((x: any) => String(x.text ?? '')).filter((t: string) => t.trim())
  await ui.unmount()
  return [...new Set(all)]
}
test('a session refreshed in English and then cleared draws the English title before its first refresh, with no Hangul (요구 이력 99)', async ($, on) => {
  const files: Record<string, string> = { [HOME_S + 'old/want']: ON('en') }
  const { s } = clearHeld(on, { setting: 'English', files })
  await start($)                                               // 이전 세션을 영어 화면으로 한 번 갱신했다
  expect(await shown($)).toContain('Nunchi on · analyzes after the next answer')
  s.id = 'new'                                                 // /clear: ID가 바뀌고 새 세션의 패널 상태는 아직 없다. 시계를 움직이지 않아 갱신은 돌지 않는다
  const all = await shown($)
  expect(all).toEqual(['Nunchi'])
  for (const t of all) expect(t).not.toMatch(/[가-힣]/)
})
const startRec = (id: string, source: string, ms: number) =>
  JSON.stringify({ ts: new Date(ms).toISOString(), session_id: id, event: 'SessionStart', data: { source } }) + '\n'
for (const [setting, want] of [['한국어', '눈치 꺼짐 · /nunchi로 켜면 이 세션을 분석합니다'], ['English', 'Nunchi off · /nunchi to analyze this session']] as const)
test(`after /clear in a turned-on session the new session starts off and says how to turn it on, ${setting} (요구 이력 100)`, async ($, on) => {
  const files: Record<string, string> = { [HOME_S + 'old/want']: ON('en'), [HOME_S + 'new/events.jsonl']: startRec('new', 'clear', 101_000) }
  const { s, clock } = clearHeld(on, { setting, files })
  await start($)
  s.id = 'new'
  await clock.advance(1000)
  const all = await shown($)
  expect(all).toContain(want)
  if (setting === 'English') for (const t of all) expect(t).not.toMatch(/[가-힣]/)
  expect(files[HOME_S + 'new/want']).toBeUndefined()
})
