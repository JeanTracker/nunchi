// 눈치 mod (REQUIREMENTS R17, SCREEN §11, BUILD_PLAN §4.4)
// 분석기(nunchi-engine)가 쓴 분석 결과(<관제 홈>/sessions/<세션 ID>/analysis.json)를 읽기만 하고, 세션 옆 패널(좁으면 입력창 위 한 줄)에 보인다.
// 분석은 하지 않는다. 분석 상태는 같은 폴더의 analysis_status.json에서 읽는다.
// /nunchi로 켜면 세션 폴더에 want를 남긴다. 그러면 응답이 끝날 때마다 분석기가 이 세션을 분석한다 (요구 이력 53).
// 켜지 않았고 분석 결과도 없는 세션, /nunchi off로 끈 세션, 사람이 패널을 닫은 세션에서는 패널을 저절로 열지 않는다 (요구 이력 84).
import { atom, read, update } from 'claude-code'
import type { Register, EngineInterface } from 'claude-code'

import type { View, Left, More, Ask } from '../types'
import { drawRows, type Row, type Span } from './rows'
import { TEXT, pick, norm, langName, failText, columns, ASK_LANG, OPT_KO, OPT_EN, OPT_FOLLOW, ASK_REBUILD, OPT_KEEP, OPT_REBUILD, ASK_BUILD, OPT_BUILD_CANCEL, OPT_BUILD_GO, type Ui } from './lang'

const PANE = 'nunchi'
const EMPTY: View = {
  basis: 0, total: 0, latest: 0, state: 'none', asks: [], askCount: 0,
  digest: '', digestTurn: 0, goal: '', goalTurn: 0, firstGoal: '', firstTurn: 0, direction: '', decisions: [], decisionCount: 0, recent: '', left: [], leftCount: 0, known: [], handled: [], handledTurn: 0, openWarn: 0, openSince: 0, past: [], pastCount: 0, ratio: 0.4, tick: 0,
  terms: [], termsMore: 0, on: false, off: false, noHook: false, error: '', control: false, behind: 0, pending: false,
  ui: 'ko', want: 'ko', from: 'default', flowLang: 'ko', analyzed: false, rebuilding: false,
}
const view = atom({ plugin: 'nunchi', key: 'view' } as const, EMPTY, { shape: 'view-16' })
// 펼친 수 (요구 이력 74): view와 따로 둔다. view는 분석 결과가 올 때마다 통째로 다시 쓰여 함께 두면 풀린다. 이 세션에만 (요구 이력 77)
const NO_MORE: More = { decisions: 0, asks: 0, left: 0, handled: 0 }
const more = atom({ plugin: 'nunchi', key: 'more' } as const, NO_MORE, { shape: 'more-4' })
// 글 펼침 (요구 이력 88): 덩어리마다 펼친 때의 분석 기준 턴. 기준 턴이 바뀌면(새 분석) 풀린 것으로 본다. 개수 펼침(more)과 따로
const textOpened = atom({ plugin: 'nunchi', key: 'open' } as const, {} as Record<string, number>, { shape: 'open-1' })

// 펼친 수 바꾸기 (요구 이력 74·78). `… n개 더`는 그 덩어리를 한 번에 모두 펼치고, 다 펼친 뒤의 `접기`는 처음 3개로
type Totals = { decisions: number; asks: number; left: number; handled: number }
const SECTIONS = ['decisions', 'asks', 'left', 'handled'] as const
export function moved(m: More, t: Totals, op: { op?: string; d?: number; k?: string }): More {
  const room = (k: typeof SECTIONS[number]) => Math.max(0, t[k] - SHOWN)
  const now = (k: typeof SECTIONS[number]) => Math.min(m[k], room(k))
  const base: More = { decisions: now('decisions'), asks: now('asks'), left: now('left'), handled: now('handled') }
  if (op.op === 'more' && (SECTIONS as readonly string[]).includes(op.k ?? '')) {
    const k = op.k as typeof SECTIONS[number]
    base[k] = base[k] >= room(k) ? 0 : room(k)
    return base
  }
  return m
}
const SAVED = '/mod.json'   // mod가 쓰는 값: 고른 언어·첫 알림 (요구 이력 76). 펼침은 저장하지 않는다(요구 이력 77). 사람이 고치는 config.json과 따로

/** mod.json을 읽고 합쳐 쓴다. 값이 그대로면 쓰지 않는다. undefined인 키는 지운다 (요구 이력 76, BUILD_PLAN §4.14) */
async function saveMod($: EngineInterface, patch: Record<string, unknown>): Promise<void> {
  const path = (await controlHome($)) + SAVED
  const old = (await readJson($, path)) ?? {}
  const next: Record<string, unknown> = { ...old }
  for (const [k, v] of Object.entries(patch)) { if (v === undefined) delete next[k]; else next[k] = v }
  if (JSON.stringify(next) === JSON.stringify(old)) return
  await $.fs.write(path, JSON.stringify(next) + '\n')
}

// 프롬프트 복사가 실패한 결정과 그때의 분석 기준 턴 (요구 이력 89): 그 결정 아래 요청 글을 흐리게 보인다
const revealed = new Map<string, number>()
/** 열린 빠뜨림 목록 (찾은 순서) */
function openList(v: View) {
  // 찾은 턴, 그다음 먼저 정한 결정부터
  return v.decisions.filter(d => d.warn).sort((a, b) => (a.warn!.at - b.warn!.at) || (a.turn - b.turn)).map(d => ({ text: d.text, at: d.warn!.at, kind: d.warn!.kind, what: d.warn!.what, quote: d.warn!.quote }))
}
async function copyPrompt($: EngineInterface, _id: string, surface?: string) {
  const v = await read($, view)
  const T = TEXT[v.ui]
  const xs = openList(v)
  if (!xs.length) return
  const P = TEXT[v.flowLang === 'ko' ? 'ko' : 'en']   // 결정 글 · 어긋난 점은 분석 언어라 틀도 분석 언어로 (요구 이력 90 검토)
  const r: any = await $.ui.copy({ text: P.prompt(xs), ...(surface ? { surface } : {}) } as any).catch(() => ({ isCopied: false }))
  if (r?.isCopied) $.ui.toast(T.copied)
  else { revealed.set('all', v.basis); $.ui.toast(T.copyFailed); await update($, view, x => ({ ...x, tick: (x?.tick ?? 0) + 1 })) }
}

async function apply($: EngineInterface, op: { op?: string; d?: number; k?: string }) {
  const v = await read($, view)
  if (op.op === 'text') {   // 펼치기 ↔ 줄이기 (요구 이력 88): 지금 기준 턴에 펼쳤으면 접고, 아니면 펼친다
    await update($, textOpened, x => { const o = { ...(x ?? {}) }; if (o[op.k ?? ''] === v.basis) delete o[op.k ?? '']; else o[op.k ?? ''] = v.basis; return o })
    return
  }
  // 질문 덩어리는 지난 질문만 접고 펼친다 (요구 이력 86): 처음 보이는 수(SHOWN) 위로 지난 질문 수만큼
  await update($, more, x => moved({ ...NO_MORE, ...(x ?? {}) }, { decisions: v.decisionCount, asks: SHOWN + v.pastCount, left: v.leftCount, handled: v.handled.length }, op))
}

const SHOWN = 3
const MAX_RATIO = 0.45   // Claude Code가 옆 패널에 허락하는 폭
let paneDrawnAt = 0      // 패널이 마지막으로 그려진 때. 패널이 보이는 동안은 띠를 두지 않는다
let askedColumns = 0     // 마지막으로 요청한 옆 패널 폭
let opened = false       // 이 세션에서 패널을 한 번 열었는지 (켠 세션·분석된 세션만 저절로 연다)
let dismissed = false    // 사람이 패널을 닫았는지 (요구 이력 84). 그 세션 동안 저절로 다시 열지 않는다. /nunchi가 푼다
let sawTurnAt = 0        // mod가 이 세션의 발화나 응답 끝을 처음 본 때 (훅 없음 판정, 요구 이력 84)
let hooked = false       // 훅 기록 파일을 한 번 봤는지 (보면 다시 보지 않는다)
const HOOK_GRACE_MS = 5000   // 발화·응답 끝 뒤 훅이 기록을 적을 때까지 기다리는 시간
let titledUi: Ui | '' = ''    // 패널 제목을 붙인 화면 언어 (요구 이력 85)
let commandUi: Ui | '' = ''   // /nunchi 명령 설명을 등록한 화면 언어 (요구 이력 84: 언어를 바꾸면 다시 등록한다)
let shownUi: Ui = 'ko'   // 지금 화면 언어 (요구 이력 76). 패널 제목처럼 그리기 밖에서 쓰는 문구용, 판정할 때마다 바꾼다

async function controlHome($: EngineInterface): Promise<string> {
  return (await $.env.get('CONTROL_TUI_HOME')) || ((await $.env.get('HOME')) || '') + '/.claude-control'
}

async function sessionId($: EngineInterface): Promise<string> {
  // 시험용: NUNCHI_MOD_SESSION을 주면 다른 세션의 분석을 본다 (실제 사용에서는 비워 둔다)
  return (await $.env.get('NUNCHI_MOD_SESSION')) || (await $.session.id())
}

async function sessionDir($: EngineInterface): Promise<string> {
  return (await controlHome($)) + '/sessions/' + (await sessionId($))
}

// 관제 패널을 앞으로 가져온다 (요구 이력 56). 관제 화면은 지웠지만(요구 이력 70) 살아 있는 관제(control.json)가 있을 때만 쓰이므로 남겨 둔다
const FOCUS_SCRIPT = `on run argv
  set targetId to item 1 of argv
  tell application "iTerm2"
    repeat with w in windows
      repeat with t in tabs of w
        repeat with s in sessions of t
          if (id of s) is targetId then
            select w
            tell t to select
            tell s to select
            activate
            return "ok"
          end if
        end repeat
      end repeat
    end repeat
  end tell
  return "missing"
end run`

/** 관제로 (요구 이력 56, BUILD_PLAN §4.8): 이 세션으로 와 달라는 요청(goto)을 남기고 관제 패널을 앞으로 */
export async function goControl($: EngineInterface): Promise<string> {
  const T = TEXT[shownUi]
  const home = await controlHome($)
  const ctl = await readJson($, home + '/control.json')
  if (!ctl?.iterm_session_id) return T.controlOff
  const alive = await $.process.run(['kill', '-0', String(ctl.pid ?? '')]).catch(() => null)
  if (!alive || alive.exitCode !== 0) return T.controlOff
  await $.fs.write(home + '/goto', JSON.stringify({ session: await sessionId($), at: (await $.clock.now()) / 1000 }) + '\n')
  const r = await $.process.run(['osascript', '-e', FOCUS_SCRIPT, String(ctl.iterm_session_id)]).catch(() => null)
  if (!r || r.exitCode !== 0 || !String(r.stdout).includes('ok')) return T.controlMissing
  return ''
}

async function readJson($: EngineInterface, path: string): Promise<any> {
  try {
    return JSON.parse(String(await $.fs.read(path)))
  } catch {
    return null
  }
}

// 글자 수 상한은 아주 긴 글을 막는 것뿐. 보이는 길이는 줄 수가 정하고, 잘리면 …가 보인다 (요구 이력 80)
function one(text: unknown, cut = 1000): string {
  return String(text ?? '').split(/\s+/).join(' ').trim().slice(0, cut)
}

/** 켠 세션이거나 분석 결과가 있으면 패널을 둔다 (요구 이력 53). /nunchi off로 끈 세션은 두지 않는다 (요구 이력 84) */
export function enabled(v: View): boolean {
  return !v.off && (v.on || v.basis > 0 || !!v.goal)
}

/** 켜짐 표시 want의 세 상태 (요구 이력 62·84): 파일이 없으면 none, on이 false면 off, 그 밖(on이 없는 옛 파일 포함)은 on. 엔진 want_state와 같다 */
export function wantOf(want: any): 'none' | 'on' | 'off' {
  if (want === null || want === undefined) return 'none'
  return want?.on === false ? 'off' : 'on'
}

// /clear 뒤 켜짐 이어주기 (요구 이력 98). /clear는 새 세션 ID를 만들고 켜짐 표시는 이전 ID 폴더에만 있다.
// 훅의 SessionStart에는 이전 ID가 없으므로, Claude Code 안에서 계속 도는 mod가 ID가 바뀐 것을 보고 짝을 짓는다
let lastSession = ''     // 지난 갱신 때 본 세션 ID
let carry: { from: string; lang: string; at: number } | null = null   // 이어 켤지 아직 정하지 못한 바뀜
const CARRY_WAIT_MS = 30_000   // 새 세션의 시작 기록이 늦게 와도 이만큼 다시 본다
const START_SLACK_MS = 5_000   // 시작 기록 시각(초 단위)이 바뀜을 본 때보다 앞설 수 있는 폭

/** 바뀐 때 무렵의 마지막 SessionStart 원인. 아직 없으면 null */
async function startSource($: EngineInterface, dir: string, since: number): Promise<string | null> {
  let text = ''
  try { text = String(await $.fs.read(dir + '/events.jsonl')) } catch { return null }
  let source: string | null = null
  for (const line of text.split('\n')) {
    if (!line.includes('"SessionStart"')) continue
    try {
      const r = JSON.parse(line)
      if (r.event === 'SessionStart' && Date.parse(r.ts) >= since - START_SLACK_MS) source = String(r.data?.source ?? '')
    } catch { /* 깨진 줄은 건너뛴다 */ }
  }
  return source
}

async function keepOnAfterClear($: EngineInterface): Promise<void> {
  if (await $.env.get('NUNCHI_MOD_SESSION')) return   // 다른 세션을 보는 시험 모드
  const id = await $.session.id()
  const home = await controlHome($)
  const now = await $.clock.now()
  if (lastSession && id !== lastSession) {
    const before = await readJson($, home + '/sessions/' + lastSession + '/want')
    carry = wantOf(before) === 'on' ? { from: lastSession, lang: String(before?.lang ?? ''), at: now } : null
  }
  lastSession = id
  if (!carry) return
  const dir = home + '/sessions/' + id
  if (wantOf(await readJson($, dir + '/want')) !== 'none') { carry = null; return }   // 이미 켜거나 끈 세션은 그대로
  const source = await startSource($, dir, carry.at)
  if (source === null) {
    if (now - carry.at > CARRY_WAIT_MS) carry = null
    return
  }
  if (source === 'clear') {
    const lang = carry.lang || (await language($)).analysis
    await $.fs.write(dir + '/want', JSON.stringify({ at: new Date(now).toISOString(), by: 'nunchi', on: true, lang, carried_from: carry.from }) + '\n')
  }
  carry = null
}

/** 이 세션의 발화나 응답 끝을 본 뒤 HOOK_GRACE_MS가 지나도 훅 기록이 없는지. 파일이 없다는 것만으로는 알리지 않는다:
 *  세션 도중 설치하면 첫 발화 전에는 기록이 없어도 훅이 돈다 (요구 이력 84). exists가 실패하면 모름(알리지 않음) */
async function hookMissing($: EngineInterface, dir: string): Promise<boolean> {
  if (hooked) return false
  try {
    if (await $.fs.exists(dir + '/events.jsonl')) { hooked = true; return false }   // 있으면 언제든 확인된 것
  } catch { return false }
  return !!sawTurnAt && (await $.clock.now()) - sawTurnAt >= HOOK_GRACE_MS   // 없다는 판정만 발화·응답 끝을 본 뒤로 미룬다
}
/** 패널이 닫힐 때 (ui.close): 사람이 닫았으면 그 세션 동안 저절로 다시 열지 않는다 (요구 이력 84) */
export function paneClosed(e: { id?: string; origin?: { kind?: string } }) {
  if (e?.id === PANE && e?.origin?.kind === 'person') dismissed = true
}
/** 저절로 열어도 되는지: 둘 자리(enabled)이고 사람이 닫지 않았을 때 (요구 이력 84). /nunchi는 이것과 상관없이 연다 */
export function mayAutoOpen(v: View): boolean {
  return enabled(v) && !dismissed
}
/** /nunchi로 켜거나 열면 사람이 닫은 것을 푼다 */
export function paneAsked() { dismissed = false }
async function sawTurn($: EngineInterface) {
  if (!sawTurnAt) sawTurnAt = await $.clock.now()
}

export function buildView(analysis: any, status: any, tick: number, ratio: number, gloss: any = null, on = false, ui: Ui = 'ko'): View {
  const T = TEXT[ui]
  const terms = (gloss?.items ?? []).map((x: any) => ({ id: one(x.id, 20), means: (x.means ?? []).map((m: any) => one(m)) }))
  const termsMore = Math.max(0, (gloss?.total ?? 0) - terms.length)
  const error = status?.state === 'failed' ? one(failText(one(status?.error, 200), ui), 60) : ''   // 엔진은 실패 이유를 코드로 남긴다 (요구 이력 76)
  const rebuilding = !!status?.rebuild && (status?.state === 'running' || status?.state === 'queued')
  const base = { ...EMPTY, state: status?.state ?? 'none', latest: status?.turn ?? 0, tick, ratio, terms, termsMore, on, error, ui, rebuilding }
  if (!analysis) return base
  const flow = analysis.flow ?? {}
  const steps: any[] = (flow.steps ?? []).filter((s: any) => s.grounded)
  const basis = flow.until ?? analysis.last_turn ?? 0
  // 에이전트 질문 (요구 이력 86): 답했거나 지나간 것은 빼고, 마지막으로 물은 턴이 늦은 것부터(같으면 나중에 생긴 것부터).
  // 마지막 응답(basis)에서 묻거나 다시 물은 것이 지금 질문, 나머지는 지난 질문
  const lastAsked = (a: any) => a.last_turn ?? a.turn ?? 0
  const qn = (a: any) => Number(String(a.id ?? '').replace(/\D/g, '')) || 0
  const open = (flow.asks ?? []).filter((a: any) => a.state !== 'answered' && a.state !== 'closed')
    .sort((a: any, b: any) => lastAsked(b) - lastAsked(a) || qn(b) - qn(a))
  const toAsk = (a: any, k: number): Ask => ({
    n: k + 1, summary: one(a.summary), turn: lastAsked(a), first: a.turn ?? lastAsked(a), quote: one(a.quote), partial: a.state === 'partial',
  })
  const nowOpen = open.filter((a: any) => lastAsked(a) >= basis)
  const pastOpen = open.filter((a: any) => lastAsked(a) < basis)
  const asks = nowOpen.map(toAsk)
  const past = pastOpen.map((a: any, k: number) => toAsk(a, nowOpen.length + k))
  // 바뀐 결정 (요구 이력 89): 뒤 결정의 replaces가 가리키는 결정은 숨긴다(옛 단계는 고쳐 쓰지 않으므로 패널이 거른다)
  const idOf = (s: any, d: any, k: number) => String(d?.id || `D${s.index ?? 0}-${k + 1}`)
  const replaced = new Set<string>()
  for (const s of steps) for (const d of (Array.isArray(s.decisions) ? s.decisions : [])) for (const r of (d.replaces ?? [])) replaced.add(String(r))
  const left: Left[] = [], known: Left[] = [], handled: Left[] = []
  // 결정 바뀜 줄 (요구 이력 89): 마지막 분석 턴의 결정이 지난 결정을 바꿨으면 처리 결과 맨 위에 '결정 #턴 바뀜: from → to'
  const changeQuotes = new Set<string>()
  const lastStep = (flow.steps ?? []).find((s: any) => s.index === basis)
  // 결정 번호 (요구 이력 90): 한 턴에 결정이 둘 이상이면 '턴-순번', 아니면 '턴'. 결정 줄 꼬리와 처리 결과가 같은 번호를 쓴다
  const labelIn = (s: any, k: number) => (Array.isArray(s.decisions) && s.decisions.length > 1 ? `${s.index ?? 0}-${k + 1}` : `${s.index ?? 0}`)
  const turnOfId = (id: string) => { for (const s of flow.steps ?? []) for (const [k, d] of (Array.isArray(s.decisions) ? s.decisions : []).entries()) if (String(d?.id || `D${s.index}-${k + 1}`) === id) return labelIn(s, k); return '' }
  const fixTurn = (Array.isArray(lastStep?.checks) ? lastStep.checks : []).some((c: any) => c.kind === '고침')
  // 직전 턴까지 열려 있던 빠뜨림으로 만든 복사 글 (두 언어 모두): 그 글에서 나온 요청은 고침 줄이 대신한다 (요구 이력 90)
  const pastedFrom: string[] = []
  if (fixTurn) {
    const before = new Map<string, any>()
    for (const s of flow.steps ?? []) if ((s.index ?? 0) < basis) for (const c of (Array.isArray(s.checks) ? s.checks : [])) before.set(String(c.id), { ...c, at: s.index ?? 0 })
    const texts = new Map<string, string>()
    for (const s of flow.steps ?? []) for (const [k, d] of (Array.isArray(s.decisions) ? s.decisions : []).entries()) texts.set(String(d?.id || `D${s.index}-${k + 1}`), one(d.text))
    const xs = [...before.values()].filter(c => c.kind !== '고침').map(c => ({ text: texts.get(String(c.id)) ?? '', at: c.at, kind: String(c.kind), what: one(c.what), quote: one(c.quote) }))
    if (xs.length) for (const u of ['ko', 'en'] as Ui[]) pastedFrom.push(TEXT[u].prompt(xs))
  }
  // 빠뜨림 줄 (요구 이력 87·89): 찾은 그 턴에만 맨 위에 ⚠, 고친 턴에는 ✔ 고침
  for (const c of (Array.isArray(lastStep?.checks) ? lastStep.checks : [])) {
    const t = turnOfId(String(c.id))
    if (c.kind === '고침') handled.push({ mark: '✔', summary: T.fixed(t, one(c.what)), note: '', turn: basis, quote: '' })
    else handled.push({ mark: '⚠', summary: T.broke(t, String(c.kind), one(c.what)), note: '', turn: basis, quote: '' })
  }
  for (const d of (Array.isArray(lastStep?.decisions) ? lastStep.decisions : [])) for (const r of (d.replaces ?? [])) {
    handled.push({ mark: '✔', summary: T.changed(turnOfId(String(r)) as any, one(d.from), one(d.to), one(d.text)), note: '', turn: basis, quote: '' })
    changeQuotes.add(one(d.quote))
  }
  for (const r of flow.requests ?? []) {
    const quote = one(r.agent_quote)
    if (r.state === 'open') left.push({ mark: '○', summary: one(r.summary), note: '', turn: r.from_turn ?? 0, quote: '' })
    // ⊘는 에이전트가 못 했다·미뤘다고 한 원문을 붙인다. 원문이 없을 때만 고정 문구 (요구 이력 86)
    else if (r.state === 'deferred') left.push({ mark: '⊘', summary: one(r.summary), note: quote ? '' : T.deferred, turn: r.from_turn ?? 0, quote })
    else if (r.state === 'in_progress') left.push({ mark: '◐', summary: one(r.summary), note: T.inProgress, turn: r.by_turn ?? r.from_turn ?? 0, quote: '' })   // 요구 이력 66
    // 조사는 했으나 결과 없음: 남은 요청이 아니라 알려진 문제 (요구 이력 86)
    else if (r.state === 'no_result') known.push({ mark: '◇', summary: one(r.summary), note: '', turn: r.by_turn ?? r.from_turn ?? 0, quote })
    // 처리 결과 (요구 이력 87·88): 마지막 분석 턴(basis)에 생겼거나 상태가 바뀐 내 요청. 바뀜 줄과 같은 구절의 요청은 그 줄이 대신한다 (요구 이력 89)
    const mark = ({ addressed: '✔', in_progress: '◐', deferred: '⊘', open: '○', no_result: '◇' } as Record<string, string>)[r.state]
    const fixAsk = fixTurn && !!one(r.quote) && pastedFrom.some(t => t.includes(one(r.quote)))   // 프롬프트 복사로 보낸 고침 요청은 '결정 고침' 줄이 대신한다 (요구 이력 90)
    if (mark && basis && ((r.from_turn ?? 0) === basis || (r.by_turn ?? 0) === basis) && !changeQuotes.has(one(r.quote)) && !fixAsk) handled.push({ mark, summary: one(r.summary), note: '', turn: basis, quote: '' })
  }
  // 도구 실패(△)는 보이지 않는다: 도구 사용은 모으지도 보이지도 않는다 (요구 이력 48)
  // 의사결정 (요구 이력 71·86·87): 그 턴에 정해진 설계 요건. 관계가 확정인지와 상관없다(작업 순서 승인은 분석기가 넣지 않는다).
  // 분석기의 요약이라 원문 대조가 없으므로 정한 턴을 함께 보인다. 최근 것부터 놓아 펼친 것이 아래로 이어진다 (요구 이력 74).
  // 흐름 형식이 세 가지다: 새 흐름은 단계의 decisions 목록, 요구 이력 86 사이의 흐름은 decision 한 줄과 decision_by,
  // 그 전 옛 흐름은 확정 턴을 결정으로 보고 정한 것 → 제목 → 요약 (요구 이력 72)
  // 열린 빠뜨림 (요구 이력 87·89): 결정마다 마지막 판정이 어김·빠뜨림이고 그 결정이 바뀌지 않았으면 열림. 엔진 open_checks와 같다
  const lastCheck = new Map<string, { at: number; kind: string; what: string; quote: string }>()
  for (const s of flow.steps ?? []) for (const c of (Array.isArray(s.checks) ? s.checks : [])) lastCheck.set(String(c.id), { at: s.index ?? 0, kind: String(c.kind), what: one(c.what), quote: one(c.quote) })
  const warnOf = (id: string) => { const c = lastCheck.get(id); return c && c.kind !== '고침' && !replaced.has(id) ? c : undefined }
  const decisionsOf = (s: any): View['decisions'] => {
    const turn = s.index ?? 0
    if (Array.isArray(s.decisions)) return s.decisions.map((d: any, k: number) => ({ text: one(d.text), turn, label: labelIn(s, k), proposed: d.by === 'agent', id: idOf(s, d, k), warn: warnOf(idOf(s, d, k)) }))
      .filter((d: any) => d.text && !replaced.has(d.id))
    if ('decision_by' in s) return one(s.decision) ? [{ text: one(s.decision), turn, proposed: s.decision_by === 'agent' }] : []
    return s.label === '확정' ? [{ text: one(s.decision || s.title || s.summary), turn, proposed: false }] : []
  }
  const decisions = steps.slice().reverse().flatMap(decisionsOf)
  const decided = decisions
  const last = steps.length ? steps[steps.length - 1] : null
  // 처음부터 이 턴까지 한 덩어리 정리: 분석기가 턴마다 써 둔 digest 중 마지막 것 (요구 이력 57, 추정)
  const digested = (flow.steps ?? []).filter((s: any) => s.digest).pop()
  return {
    ...base,
    // 이 세션의 분석 언어. 엔진은 ko면 적지 않는다 (요구 이력 76).
    // 첫 분석은 흐름 없는 결과를 먼저 적으니, 흐름이 생기기 전에는 언어를 모르는 것으로 둔다
    flowLang: analysis.flow ? norm(flow.lang) || 'ko' : EMPTY.flowLang,
    analyzed: !!analysis.flow,
    basis,
    total: analysis.last_turn ?? 0,
    state: status?.state ?? 'idle',
    asks,
    askCount: asks.length,
    past,
    pastCount: past.length,
    digest: digested && digested.index > 1 ? one(digested.digest) : '',
    digestTurn: digested?.index ?? 0,
    goal: one(flow.current_goal?.text ?? analysis.current_goal ?? ''),
    goalTurn: flow.current_goal?.turn ?? 0,
    // 처음 목표 (요구 이력 82): 지금 목표와 다른 턴일 때만 그린다. 큰 목표라는 보장이 없어 '처음'이라 부른다
    firstGoal: one(flow.first_goal?.text ?? ''),
    firstTurn: flow.first_goal?.turn ?? 0,
    direction: String(steps.find((s: any) => s.shift && s.index === flow.current_goal?.turn)?.direction ?? ''),
    decisions,
    decisionCount: decided.length,
    recent: one(last?.agent_summary ?? ''),
    left,
    leftCount: left.length,
    known,
    // 요청이 없던 턴이면 에이전트가 한 일 요약 한 줄 (요구 이력 87)
    handled: handled.length ? handled : last && last.index === basis && one(last.agent_summary) ? [{ mark: '·', summary: one(last.agent_summary), note: '', turn: basis, quote: '' }] : [],
    handledTurn: basis,
    openWarn: decisions.filter(d => d.warn).length,
    openSince: Math.min(...decisions.filter(d => d.warn).map(d => d.warn!.at), Infinity) === Infinity ? 0 : Math.min(...decisions.filter(d => d.warn).map(d => d.warn!.at)),
  }
}

// 넓게 그려지는 기호(… → ◆ ● ① ⚠ 등) 바로 뒤에 글자가 붙으면 한 칸 띄운다 (요구 이력 58).
// iTerm이 영문 외 글자를 Noto Sans CJK KR로 그리면 이 기호들이 한 칸의 약 1.7배로 그려져 뒤 글자를 덮는다.
// 범위는 SCREEN §8 기호 겹침 실측에서 정했다(BUILD_PLAN §4.9). 괘선(─ │ ┊ └)은 터미널이 직접 그려 넣지 않는다.
const WIDE = /[\u00a7\u00a9\u00b1\u00b6\u00bc-\u00be\u00d7\u00f7\u2010\u2014-\u2016\u2020\u2021\u2025-\u2027\u2030\u2035\u203b\u2042\u2047-\u2049\u2051\u2100-\u214f\u2190-\u23ff\u2460-\u24ff\u25a0-\u27bf]/
export function gap(text: string): string {
  return text.replace(new RegExp(WIDE.source + '(?=[^\\s])', 'g'), m => m + ' ')
}

// 글 속 링크 (요구 이력 60): 맨 주소(https://…)와 마크다운 [이름](주소). 줄을 감싸거나 잘라도 조각마다 원래 주소를 들고 간다.
export type Piece = { t: string; href?: string }
const URL_RE = /\[([^\]\n]+)\]\((https?:\/\/[^\s)]+)\)|(https?:\/\/[A-Za-z0-9\-._~:\/?#@!$&*+,;=%]+)/g   // 맨 주소는 ASCII 주소 글자만 (뒤 한글 조사·백틱이 붙지 않게)
export function pieces(text: string): Piece[] {
  const out: Piece[] = []
  let at = 0
  for (const m of text.matchAll(URL_RE)) {
    let url: string = m[2] ?? m[3] ?? ""
    let label: string = m[1] ?? url
    if (!m[2]) {   // 맨 주소 끝의 문장 부호는 주소가 아니다
      const trail = /[.,;:!?*]+$/.exec(url)
      if (trail) { url = url.slice(0, -trail[0].length); label = url }
    }
    if (m.index! > at) out.push({ t: gap(text.slice(at, m.index)) })
    out.push({ t: label, href: url })
    at = m.index! + (m[2] ? m[0].length : url.length)
  }
  if (at < text.length) out.push({ t: gap(text.slice(at)) })
  return out
}
const flat = (line: Piece[]) => line.map(p => p.t).join('')
function push(line: Piece[], t: string, href?: string) {
  const last = line[line.length - 1]
  if (last && last.href === href) last.t += t
  else line.push(href ? { t, href } : { t })
}

/** 칸 수(한글 2칸)로 자른다. 대화 정리는 턴마다 한 줄 (SCREEN §11) */
function cutParts(text: string, cols: number): Piece[] {
  const line: Piece[] = []
  let used = 0
  for (const p of pieces(text)) {
    for (const ch of p.t) {
      const w = /[\u1100-\u115f\u2e80-\ua4cf\uac00-\ud7a3\uf900-\ufaff\ufe30-\ufe4f\uff00-\uff60\uffe0-\uffe6]/.test(ch) ? 2 : 1
      if (used + w > cols - 1) { push(line, '…'); return line }
      push(line, ch, p.href)
      used += w
    }
  }
  return line
}
function cut(text: string, cols: number): string {
  return flat(cutParts(text, cols))
}

const wide = (ch: string) => /[\u1100-\u115f\u2e80-\ua4cf\uac00-\ud7a3\uf900-\ufaff\ufe30-\ufe4f\uff00-\uff60\uffe0-\uffe6\u2714\u26a0]/.test(ch) ? 2 : 1   // ✔ ⚠는 넓게 그려진다 (요구 이력 58·89)
const width = (t: string) => [...t].reduce((n, ch) => n + wide(ch), 0)

/** 칸 수(한글 2칸)에 맞춰 여러 줄로 감싼다. 넘치면 마지막 줄 끝을 …로 (요구 이력 50).
 *  tail: 넘쳐 자를 때 마지막 줄 끝에 비워 둘 꼬리(턴 번호 등)의 칸 수 (요구 이력 80) */
function wrapParts(text: string, cols: number, maxLines: number, tail = 0): Piece[][] {
  const words: Piece[] = []   // 링크는 한 낱말 (빈칸이 없다)
  for (const p of pieces(text)) {
    if (p.href) words.push(p)
    else for (const w of p.t.split(/(\s+)/)) if (w) words.push({ t: w })
  }
  const lines: Piece[][] = []
  let cur: Piece[] = []
  let used = 0
  const blank = () => !flat(cur).trim()
  const close = () => {
    const last = cur[cur.length - 1]
    if (last && !last.href) last.t = last.t.trimEnd()
    lines.push(cur.filter(p => p.t)); cur = []; used = 0
  }
  for (const word of words) {
    const w = [...word.t].reduce((n, ch) => n + wide(ch), 0)
    if (used + w > cols && !blank()) {
      close()
      if (/^\s+$/.test(word.t)) continue
    }
    if (w > cols) {   // 한 낱말이 한 줄보다 길면 글자 단위로 자른다 (링크 조각은 같은 주소)
      for (const ch of word.t) {
        if (used + wide(ch) > cols) { lines.push(cur); cur = []; used = 0 }
        push(cur, ch, word.href)
        used += wide(ch)
      }
      continue
    }
    push(cur, word.t, word.href)
    used += w
  }
  if (!blank()) close()
  if (lines.length > maxLines) {
    const kept = lines.slice(0, maxLines)
    const last = kept[maxLines - 1] ?? []
    const room = cols - 2 - tail
    const trimmed: Piece[] = []
    let n = 0
    for (const p of last) for (const ch of p.t) {
      if (n + wide(ch) > room - 1) break
      push(trimmed, ch, p.href); n += wide(ch)
    }
    push(trimmed, ' …')
    kept[maxLines - 1] = trimmed
    return kept
  }
  return lines
}
/** 글을 감싸고 끝에 꼬리(턴 번호·꼬리표)를 붙인다 (요구 이력 80). 마지막 줄에 들어가면 그 줄 끝에, 아니면 다음 줄에.
 *  글이 줄 수 안에 들어가면 꼬리 때문에 자르지 않는다. 꼬리가 폭의 절반보다 길면 자리를 비우지 않고 따로 감싼다 */
function wrapTail(text: string, cols: number, maxLines: number, tail: string): { lines: Piece[][]; inline: boolean; tailLines: Piece[][] } {
  const tw = width(tail)
  const lines = wrapParts(text, cols, maxLines, tw <= cols / 2 ? tw : 0)
  if (!lines.length) lines.push([])   // 요약이 비어도 번호·턴 줄은 그린다
  const inline = !tail || width(flat(lines[lines.length - 1] ?? [])) + tw <= cols
  return { lines, inline, tailLines: inline ? [] : wrapParts(tail.trim(), cols, 2) }
}
function wrap(text: string, cols: number, maxLines: number): string[] {
  return wrapParts(text, cols, maxLines).map(flat)
}

function dots(tick: number, state = 'running', ui: Ui = 'ko'): string {
  return (state === 'queued' ? TEXT[ui].queued : TEXT[ui].running) + ['.', '..', '...'][tick % 3]
}

async function openPane($: EngineInterface) {
  opened = true
  titledUi = shownUi
  return $.ui.open({ id: PANE, title: TEXT[shownUi].title })
}

/** 화면 언어가 바뀌면 열려 있는 패널의 제목만 새 언어로 다시 붙인다 (요구 이력 85). 닫혔거나 꺼진 패널은 열지 않는다 */
async function retitle($: EngineInterface, ui: Ui) {
  if (!titledUi || titledUi === ui) return
  titledUi = ui
  try {
    if ((await $.ui.panes()).some(x => x.id === PANE)) await $.ui.open({ id: PANE, title: TEXT[ui].title, ...(askedColumns ? { columns: askedColumns } : {}) })
  } catch { /* 제목은 다음에 열 때 붙는다 */ }
}

/** 언어 판정 (요구 이력 76): mod.json에 고른 값 → Claude Code language → LC_ALL → LANG → en */
async function language($: EngineInterface, saved?: any) {
  const mod = saved === undefined ? await readJson($, (await controlHome($)) + SAVED) : saved
  let setting: unknown
  try { setting = await $.settings.read({ key: 'language' }) } catch { setting = undefined }
  const p = pick({ saved: mod?.language, setting, lcAll: await $.env.get('LC_ALL'), lang: await $.env.get('LANG') })
  shownUi = p.ui
  return p
}

// 분석이 본 마지막 응답 뒤에 끝난 응답 수 (요구 이력 65)와 사람이 보낸 발화가 있는지 (요구 이력 82).
// 훅이 모든 세션의 Stop과 UserPromptSubmit을 events.jsonl에 남긴다. 한 턴 안에서 이어 끝난 응답도 센다(요구 이력 64).
// 파일에는 도구 기록도 쌓여 일하는 동안 매초 커지므로, 처음·응답이 끝나거나 발화를 보낸 뒤 잠깐·분석 기준이 바뀔 때만 읽는다.
const RECOUNT_MS = 5000      // 응답이 끝나거나 발화를 보낸 뒤 훅이 기록을 적을 때까지 기다리는 동안 다시 센다
const TAIL = 3 * 1024 * 1024 // 파일이 크면 끝부분만 읽는다 ($.fs.read는 4 MiB까지)
let countedSince: string | null = null
let recountUntil = 0
let counted: After = { behind: 0, pending: false }
export type After = { behind: number; pending: boolean }
export function answerEnded(now: number) { recountUntil = now + RECOUNT_MS }
export const promptSent = answerEnded
/** 사람이 보낸 발화인지: 다른 에이전트·세션이 보낸 메시지와 알림도 UserPromptSubmit을 남긴다 (요구 이력 82) */
export function humanPrompt(prompt: unknown): boolean {
  const p = String(prompt ?? '').trimStart()
  return !!p && !/^(<agent-message|<cross-session-message|<task-notification|\[Cross-session idle notice\])/.test(p)
}
async function readEvents($: EngineInterface, path: string): Promise<string> {
  let size = 0
  try { size = Number((await $.fs.stat(path))?.size ?? 0) } catch { size = 0 }
  if (size <= TAIL) return String(await $.fs.read(path))
  const text = String(await $.fs.read(path, { offset: size - TAIL, length: TAIL }))
  return text.slice(text.indexOf('\n') + 1)   // 앞 조각 줄은 버린다
}
export async function answersAfter($: EngineInterface, dir: string, since: string): Promise<After> {
  const now = await $.clock.now()
  if (since === countedSince && now > recountUntil) return counted
  countedSince = since
  try {
    let behind = 0, pending = false
    if (since) for (const l of (await readEvents($, dir + '/events.jsonl')).split('\n')) {
      if (!l.includes('"Stop"') && !l.includes('"UserPromptSubmit"')) continue
      try {
        const e = JSON.parse(l)
        if (!(String(e.ts ?? '') > since)) continue
        if (e.event === 'Stop') behind++
        else if (e.event === 'UserPromptSubmit' && humanPrompt(e.data?.prompt)) pending = true
      } catch { /* 깨진 줄은 건너뛴다 */ }
    }
    counted = { behind, pending }
  } catch {
    counted = { behind: 0, pending: false }
  }
  return counted
}

async function refresh($: EngineInterface) {
  try { await keepOnAfterClear($) } catch { /* 이어 켜기를 못 해도 그리기는 그대로 (요구 이력 98) */ }
  const dir = await sessionDir($)
  const home = await controlHome($)
  const [analysis, status, config, gloss, want, ctl, saved] = await Promise.all([
    readJson($, dir + '/analysis.json'), readJson($, dir + '/analysis_status.json'),
    readJson($, home + '/config.json'), readJson($, dir + '/glossary.json'),
    readJson($, dir + '/want'), readJson($, home + '/control.json'), readJson($, home + SAVED),
  ])
  const ratio = Math.min(MAX_RATIO, Math.max(0.2, Number(config?.mod_width_ratio) || 0.4))
  const { behind, pending } = await answersAfter($, dir, String(analysis?.source_ts ?? ''))
  const lang = await language($, saved)   // 1초마다 다시 정하므로 다른 세션에서 바꿔도 곧 따라온다
  await registerCommand($, lang.ui)       // 명령 설명도 따라 바꾼다
  await retitle($, lang.ui)               // 열린 패널의 제목도
  const w = wantOf(want)
  const noHook = await hookMissing($, dir)
  await update($, view, old => ({ ...buildView(analysis, status, (old?.tick ?? 0) + 1, ratio, gloss, w === 'on', lang.ui),
    off: w === 'off', noHook, control: !!ctl?.iterm_session_id, behind, pending, want: lang.analysis, from: lang.from }))
  if (!opened && mayAutoOpen(await read($, view))) void openPane($)   // 켠 세션이나 관제가 분석한 세션만 저절로 연다
}

/** 엔진이 새 흐름을 만들 때 쓸 이 세션의 분석 언어 (요구 이력 76, BUILD_PLAN §4.14). Claude Code 설정은 프로젝트마다 다를 수 있어 세션 폴더에 둔다 */
async function noteLang($: EngineInterface, lang: string): Promise<void> {
  try { await $.fs.write((await sessionDir($)) + '/lang', lang + '\n') } catch { /* 세션 폴더가 아직 없으면 엔진은 ko로 본다 */ }
}

/** /nunchi language (요구 이력 76): 질문 창에서 고른다. Esc·-p(거절)면 바꾸지 않는다 */
async function chooseLanguage($: EngineInterface): Promise<string> {
  const now = await language($)
  const T = TEXT[now.ui]
  const from = now.from === 'claude' ? T.fromClaude : ''
  const follow = OPT_FOLLOW(now.ui)
  const opts = now.analysis === 'en' ? [OPT_EN, OPT_KO, follow] : [OPT_KO, OPT_EN, follow]   // 지금 언어가 맨 위
  let answer: string
  try {
    answer = await $.ui.ask(ASK_LANG(now.ui, langName(now.analysis), from), opts)
  } catch {
    return T.unchanged + ' ' + T.langNow(langName(now.analysis), from)
  }
  const picked = answer === OPT_KO ? 'ko' : answer === OPT_EN ? 'en' : answer === follow ? undefined : norm(answer)
  if (picked !== undefined && picked !== 'ko' && picked !== 'en') return T.unchanged   // 직접 쓴 글은 두 언어만 받는다
  await saveMod($, { language: picked })
  const after = await language($)
  await noteLang($, after.analysis)
  // 켰지만 아직 분석 전인 세션이 옛 언어로 분석되지 않게 want의 lang도 바꾼다
  const dir = await sessionDir($)
  const want = await readJson($, dir + '/want')
  if (want && want.lang !== after.analysis) await $.fs.write(dir + '/want', JSON.stringify({ ...want, lang: after.analysis }) + '\n')
  await refresh($)
  const T2 = TEXT[after.ui]
  const said = picked === undefined ? T2.langFollow(langName(after.analysis)) : T2.langSet(langName(after.analysis))
  // 이 세션이 이미 다른 언어로 분석돼 있으면 이어서 묻는다 (요구 이력 76). 비용이 들지 않는 '그대로 두기'가 먼저:
  // 창이 뜬 채 종료하면 첫 항목이 답으로 들어온 것을 봤다 (SCREEN §8 2026-11-17 언어)
  const v = await read($, view)
  if (!v.analyzed || v.flowLang === after.analysis) return said
  if (v.off) return said + T2.offNoRebuild   // 꺼진 세션은 다시 분석하지 않는다 (요구 이력 84): emit.sh rebuild는 대기 상태를 곧바로 쓴다
  const was = langName(v.flowLang), to = langName(after.analysis)
  let again = ''
  try {
    again = await $.ui.ask(ASK_REBUILD(after.ui, was, to, v.total || v.basis), [OPT_KEEP(after.ui, to), OPT_REBUILD(after.ui)])
  } catch { /* Esc: 그대로 둔다 */ }
  if (again !== OPT_REBUILD(after.ui)) return said + T2.langKept(was)
  return said + ((await askRebuild($, after.analysis)) ? T2.langRebuild(to) : T2.rebuildFailed)
}

/** 엔진에 다시 분석을 맡긴다: 플러그인의 훅 입구(emit.sh)가 이 컴퓨터용 엔진을 골라 넘긴다. 초기화는 분석기가 그 세션을 맡은 뒤에 한다 */
async function askRebuild($: EngineInterface, lang: string): Promise<boolean> {
  const r = await $.process.run(['sh', $.plugin.root + '/hooks/emit.sh', 'rebuild', await sessionId($), lang]).catch(() => null)
  if (!r || r.exitCode !== 0) return false
  await refresh($)
  return true
}

/** 엔진의 build를 부른다 (요구 이력 93): 한 줄 JSON {total, done, todo, fresh}. 기록이 없거나 엔진이 못 돌면 null */
async function engineBuild($: EngineInterface, lang: string, countOnly: boolean): Promise<{ total: number; todo: number; fresh: boolean } | null> {
  const argv = ['sh', $.plugin.root + '/hooks/emit.sh', 'build', await sessionId($), lang, ...(countOnly ? ['--count'] : [])]
  const r = await $.process.run(argv).catch(() => null)
  if (!r || r.exitCode !== 0) return null
  try {
    const o = JSON.parse(String(r.stdout ?? '').trim().split('\n').pop() ?? '')
    return { total: Number(o.total) || 0, todo: Number(o.todo) || 0, fresh: !!o.fresh }
  } catch { return null }
}

/** /nunchi build (요구 이력 93): 지금까지 대화를 지금 분석한다. 분석할 응답 수를 먼저 보이고 확인을 받으며, 세션을 켠다 */
async function build($: EngineInterface): Promise<string> {
  const lang = await language($)
  const T = TEXT[lang.ui]
  const plan = await engineBuild($, lang.analysis, true)
  if (!plan) return T.buildNoRecord
  if (plan.todo > 0) {
    let answer = ''
    try {
      answer = await $.ui.ask(ASK_BUILD(lang.ui, plan.todo, plan.fresh), [OPT_BUILD_CANCEL(lang.ui), OPT_BUILD_GO(lang.ui, plan.todo)])
    } catch { /* Esc: 그만둔다 */ }
    if (answer !== OPT_BUILD_GO(lang.ui, plan.todo)) return T.buildCancelled
  }
  // 켠다: 분석기는 꺼진 세션의 요청을 버리므로 엔진에 맡기기 전에 쓴다
  const dir = await sessionDir($)
  const old = await readJson($, dir + '/want')
  const at = new Date(await $.clock.now()).toISOString()
  await $.fs.write(dir + '/want', JSON.stringify({ at, by: 'nunchi', on: true, lang: plan.fresh ? lang.analysis : old?.lang ?? lang.analysis }) + '\n')
  const started = plan.todo > 0 ? await engineBuild($, lang.analysis, false) : plan
  paneAsked()
  await refresh($)
  const r = await openPane($)
  const where = r.isPlaced ? '' : T.narrow
  if (!started) return T.buildNoRecord
  if (plan.todo === 0) return T.buildUpToDate(plan.total) + where
  return (plan.fresh ? T.buildFresh(plan.todo) : T.buildMore(plan.todo)) + where
}

/** /nunchi를 화면 언어의 설명으로 등록한다. 같은 이름으로 다시 등록하면 바뀐다 (요구 이력 76·84) */
async function registerCommand($: EngineInterface, ui: Ui) {
  if (commandUi === ui) return
  commandUi = ui
  try {
    await $.command.register({ name: 'nunchi', description: TEXT[ui].command, argumentHint: '[on|off|status|language|build]', immediate: true })   // 응답 중에도 바로 (요구 이력 84)
  } catch { commandUi = '' }   // 다음 갱신에서 다시 해 본다
}

/** HH:MM (이 컴퓨터 시각) */
function hhmm(iso: unknown): string {
  const d = new Date(String(iso ?? ''))
  if (isNaN(d.getTime())) return ''
  return String(d.getHours()).padStart(2, '0') + ':' + String(d.getMinutes()).padStart(2, '0')
}

/** /nunchi status (요구 이력 62·84): 패널을 열지 않고 아무것도 바꾸지 않는다. 다섯 줄 */
async function statusText($: EngineInterface): Promise<string> {
  await refresh($)
  const v = await read($, view)
  const T = TEXT[v.ui]
  const analysis = await readJson($, (await sessionDir($)) + '/analysis.json')
  const state = v.state === 'failed' ? T.failed + v.error
    : v.rebuilding ? T.rebuilding(v.latest, v.total || v.latest)
    : v.state === 'running' ? T.stRunning(v.latest)
    : v.state === 'queued' ? T.queued
    : T.stIdle
  const hook = v.noHook ? T.stHookMissing : hooked ? T.stHooked : T.stHookUnknown
  const lang = langName(v.want) + (v.from === 'claude' ? T.fromClaude : '') + (v.analyzed && v.flowLang !== v.want ? ' · ' + T.langLine(langName(v.flowLang)) : '')
  return [
    T.stNunchi + (v.off ? T.stOff : v.on ? T.stOn : T.stNever),
    T.stAnalysis + (v.basis > 0 ? T.stAsOf(v.basis, hhmm(analysis?.analyzed_at)) : T.stNone),
    T.stState + state,
    T.stHook + hook,
    T.stLang + lang,
  ].join('\n')
}

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    // 분석기 자신의 claude -p는 건너뛴다: 훅과 같은 표시 (hook.rs). 안 그러면 분석 호출마다 빈 세션 폴더가 생긴다
    if ((await $.env.get('CONTROL_TUI_ANALYZER')) === '1') return next(e)
    dismissed = false; sawTurnAt = 0; hooked = false; titledUi = ''   // 세션마다 새로 본다 (다시 불러올 때도)
    const first = await language($)
    commandUi = ''
    await registerCommand($, first.ui)
    await noteLang($, first.analysis)
    await refresh($)
    $.clock.every(1000, () => { void refresh($) })   // 분석 파일이 바뀌면 다시 그린다. '분석 중' 점도 1초마다
    // 설치 뒤 첫 세션: 묻지 않고 정한 언어와 바꾸는 법을 한 번 알린다 (요구 이력 76). 다시 불러와도·다른 세션에서도 다시 띄우지 않는다
    try {
      const saved = await readJson($, (await controlHome($)) + SAVED)
      if (!saved?.noticed) {
        $.ui.toast(TEXT[first.ui].notice)
        await saveMod($, { noticed: true })
      }
    } catch { /* 알림을 못 남겨도 세션은 그대로 */ }
    return next(e)
  })

  // 발화를 보내면 기록을 다시 읽는다: 새 요청 반영 전 표시 (요구 이력 82)
  on('prompt.submit', async ($, e, next) => {
    await sawTurn($)
    promptSent(await $.clock.now())   // next(e)가 턴 끝까지 걸릴 수 있으니 먼저 연다
    const r = await next(e)
    promptSent(await $.clock.now())
    return r
  })

  on('turn.complete', async ($, e, next) => {
    if (!(e as any).agentId) { answerEnded(await $.clock.now()); await sawTurn($) }   // 이 세션 응답이 끝남: 밀린 응답 수를 다시 센다 (하위 에이전트 끝은 빼고)
    return next(e)
  })

  // 사람이 패널을 닫으면 그 세션 동안 저절로 다시 열지 않는다 (요구 이력 84). 끄기의 닫기(plugin)는 off가 막는다
  on('ui.close', async ($, e, next) => {
    paneClosed(e as any)
    return next(e)
  })

  // /nunchi [on|off|status|language|build] (요구 이력 62·76·84·93)
  on('command.run', { command: 'nunchi' }, async ($, e) => {
    const arg = String((e as any).args ?? '').trim()
    const word = arg.toLowerCase()
    if (word === 'language') return { text: await chooseLanguage($) }
    if (word === 'status') return { text: await statusText($) }
    if (word === 'build') return { text: await build($) }
    if (word && word !== 'on' && word !== 'off') {
      const T = TEXT[(await language($)).ui]
      return { text: [T.unknown(arg), ...T.usage].join('\n') }   // 아무것도 바꾸지 않는다
    }
    const dir = await sessionDir($)
    const old = await readJson($, dir + '/want')
    const was = wantOf(old)
    const lang = await language($)   // 이 세션을 처음 분석할 언어 (엔진이 흐름에 고정한다, 요구 이력 76)
    const at = new Date(await $.clock.now()).toISOString()
    if (word === 'off') {
      // 분석 언어(lang)는 그대로 두고 on만 끈다. 보기를 먼저 고쳐야 닫은 뒤 다시 열지 않는다
      await $.fs.write(dir + '/want', JSON.stringify({ ...(old && typeof old === 'object' ? old : {}), at, by: 'nunchi', on: false, lang: old?.lang ?? lang.analysis }) + '\n')
      await refresh($)
      try { await $.ui.close({ id: PANE }) } catch { /* 이미 닫혔거나 거절돼도 꺼짐은 남는다 */ }
      const v = await read($, view)
      return { text: TEXT[v.ui].turnedOff(v.basis) }
    }
    await $.fs.write(dir + '/want', JSON.stringify({ at, by: 'nunchi', on: true, lang: was === 'off' && old?.lang ? old.lang : lang.analysis }) + '\n')
    paneAsked()
    await refresh($)
    const r = await openPane($)
    const v = await read($, view)
    const T = TEXT[v.ui]
    const where = r.isPlaced ? '' : T.narrow
    const hook = v.noHook ? T.noHookReply : ''
    if (was === 'off') return { text: T.turnedBack + where + hook }
    if (was === 'on' || v.basis > 0) return { text: T.opened + where + hook }
    return { text: T.turnedOn + where + hook }
  })

  on('ui.render', { component: 'Pane', requestId: PANE }, async ($, e) => {
    const els: any = $.ui.resolve(e)
    const { Box, Text, Button } = els
    const v = await read($, view)
    const m = { ...NO_MORE, ...(await read($, more)) }
    const openSet = await read($, textOpened)
    const T = TEXT[v.ui]
    const cols = Math.max(20, e.props.bodyColumns ?? 50)
    const toControl = async () => {
      const problem = await goControl($)
      if (problem) $.ui.toast(problem)
    }
    const tail = v.control
      ? <Box flexDirection="row"><Button key="control" hotkey="1" onPress={() => { void toControl() }}>{T.control}</Button><Text dimColor>{T.controlOr}</Text></Box>
      : null   // 관제 화면을 지워(요구 이력 70) 켜라고 하지 않는다
    paneDrawnAt = await $.clock.now()
    // viewport는 패널을 뺀 나머지 폭이라(실측 2026-11-12: 200칸 창에서 141), 창 전체 = 나머지 + 패널 + 경계로 본다
    const whole = (e.viewport?.columns ?? 0) + (e.props.placement === 'dock' ? cols + 2 : 0)
    const want = Math.round(whole * v.ratio)
    if (e.props.placement === 'dock' && want >= 24 && Math.abs(want - askedColumns) > 1 && !v.off) {   // 끈 뒤 그리던 중이면 다시 열지 않는다 (요구 이력 84)
      askedColumns = want   // 창 폭의 비율로 다시 요청한다 (사용자가 끌어 정한 폭이 있으면 그것이 앞선다)
      void $.ui.open({ id: PANE, title: T.title, columns: want })
    }
    // 본문 줄: 다 만든 줄을 보통 글자로 그린다. 키를 받는 본문(요구 이력 75)은 글자를 끌어 복사할 수 없어 없앴다 (요구 이력 77)
    const rows: Row[] = []
    const row = (...s: Span[]) => { rows.push({ s: s.filter(x => x.t) }) }
    const sp = (t: string, o: Omit<Span, 't'> = {}): Span => ({ t, ...o })
    const parts = (line: Piece[], o: Omit<Span, 't' | 'href'> = {}): Span[] => line.map(p => p.href ? { t: p.t, href: p.href } : { t: p.t, ...o })
    const busy = v.state === 'running' || v.state === 'queued'
    const rebuilding = busy && v.latest > 0 && v.total > 0 && v.latest < v.total
    // 다시 분석 중 (요구 이력 76): 엔진이 상태 파일에 rebuild를 적는다. 처음 턴(결과 없음)부터 같은 문구
    const progress = v.rebuilding ? T.rebuilding(v.latest, v.total || v.latest) : v.basis <= 1 ? T.rebuilding(v.latest, v.total) : T.catching(v.latest, v.total)
    if (!v.goal && v.basis === 0) {   // 아직 분석 결과가 없다 (SCREEN §11)
      row(sp(T.title, { b: 1 }))
      if (v.noHook) row(sp(T.noHook, { c: 'red' }))   // 고칠 일이 앞선다 (요구 이력 62·84)
      row(v.rebuilding && busy ? sp(progress + ' ' + dots(v.tick, v.state, v.ui).replace(/^[^.]*/, ''), { c: 'yellow' })
        : v.state === 'running' || v.state === 'queued' ? sp(dots(v.tick, v.state, v.ui), { c: 'yellow' })
        : v.state === 'failed' ? sp(T.failed + v.error, { c: 'red' })
        : v.on ? sp(T.onWaiting, { d: 1 })
        : sp(T.offIdle, { d: 1 }))
    } else {
      // … n개 더 (요구 이력 74·78): 누르면 그 덩어리를 모두 펼치고, 다 펼치면 접기
      const shownOf = (k: keyof Totals, total: number) => Math.min(total, SHOWN + m[k])
      const moreRow = (k: keyof Totals, total: number) => {
        if (total <= SHOWN) return
        const rest = total - shownOf(k, total)
        rows.push({ more: k, label: rest > 0 ? T.more(rest) : T.collapse })
      }
      // 머리 (요구 이력 82): 어느 응답까지 반영했는지, 사람이 보낸 새 발화가 있으면 분석 중이어도 먼저 알린다
      const lag = v.pending ? sp(T.pending, { c: 'yellow' }) : v.behind > 0 && !busy ? sp(T.behind(v.behind), { c: 'yellow' }) : sp('')
      const status = rebuilding || (v.rebuilding && busy) ? sp(`  ${progress} ${dots(v.tick, 'running', v.ui).replace(/^[^.]*/, '')}`, { c: 'yellow' })
          : busy ? sp('  ' + dots(v.tick, v.state, v.ui), { c: 'yellow' })
          : v.state === 'failed' ? sp('  ' + T.failed + v.error, { c: 'red' })
          : !v.on ? sp('  ' + T.autoOff, { c: 'yellow' }) : sp('')
      // 패널보다 넓으면 상태(분석 중 등)부터 다음 줄로, 그래도 넓으면 새 요청·밀림도 (요구 이력 82)
      const fits = (xs: Span[]) => width(xs.map(x => x.t).join('')) <= cols
      const next = (xs: Span[]) => xs.length && row(sp('  '), ...xs.map((x, k) => k ? x : { ...x, t: x.t.replace(/^\s*(· )?/, '') }))
      const head = [sp(T.title, { b: 1 }), sp(T.asOf(v.basis), { d: 1 })]
      if (fits([...head, lag, status])) row(...head, lag, status)
      else if (fits([...head, lag])) { row(...head, lag); next([status].filter(x => x.t)) }
      else { row(...head); next([lag, status].filter(x => x.t)) }
      if (v.noHook) row(sp(T.noHook, { c: 'red' }))   // 고칠 일이 앞선다 (요구 이력 62·84)
      // 화면과 이 세션의 분석 언어가 다르면 (요구 이력 76): 고른 분석 언어와 다를 때 다시 분석하는 법
      if (v.analyzed && v.flowLang !== v.want && !v.rebuilding) row(sp(T.langLine(langName(v.flowLang)), { c: 'yellow', d: 1 }))
      row(sp(' '))
      // 차례 (요구 이력 71·87): 목표 → 의사결정 → 처리 결과 → 에이전트 질문 → 남은 요청 → 알려진 문제
      // 펼치기 (요구 이력 88): 덩어리마다 지금 보이는 항목의 줄 수 상한과 인용 한 줄 자름만 푼다. 숨은 항목(… n개 더)은 그대로.
      // 펼친 때의 분석 기준 턴과 지금 기준 턴이 같을 때만 펼친 것으로 본다(새 분석이 오면 기본 줄 수로)
      const isOpen = (k: string) => openSet?.[k] === v.basis
      const cut: Record<string, boolean> = {}
      const heads: Record<string, number> = {}
      const head2 = (k: string, ...s: Span[]) => { heads[k] = rows.length; row(...s) }
      const ALL = 999
      const fitLines = (k: string, text: string, w: number, max: number) => {
        if (isOpen(k)) return wrapParts(text, w, ALL)
        if (wrapParts(text, w, ALL).length > max) cut[k] = true
        return wrapParts(text, w, max)
      }
      const fitTail = (k: string, text: string, w: number, max: number, tl: string) => {
        if (isOpen(k)) return wrapTail(text, w, ALL, tl)
        if (wrapParts(text, w, ALL).length > max) cut[k] = true
        return wrapTail(text, w, max, tl)
      }
      // 인용 “…”: 접혀 있으면 한 줄로 자르고, 펼치면 감싸서 다 보인다 (요구 이력 80·88)
      const quoteRows = (k: string, q: string) => {
        if (!q) return
        if (!isOpen(k)) {
          const c = cutParts(q, cols - 6)
          if (flat(c) !== gap(q) && flat(c) !== q) cut[k] = true
          row(sp('   “', { d: 1 }), ...parts(c, { d: 1 }), sp('”', { d: 1 }))
          return
        }
        const ls = wrapParts(q, cols - 6, ALL)
        ls.forEach((line, i) => row(sp(i ? '    ' : '   “', { d: 1 }), ...parts(line, { d: 1 }), sp(i === ls.length - 1 ? '”' : '', { d: 1 })))
      }
      // 목표 두 층 (요구 이력 82): 처음 목표가 지금 목표와 다른 턴이면 위에 '처음'(흐리게 2줄), 아래 '지금'
      if (v.firstGoal && v.firstTurn && v.goalTurn > v.firstTurn) {
        head2('goal', sp(T.goal, { b: 1 }), sp(T.first(v.firstTurn), { d: 1 }))
        for (const line of fitLines('goal', v.firstGoal, cols - 4, 2)) row(sp('   ', { d: 1 }), ...parts(line, { d: 1 }))
        row(sp(T.now, { b: 1 }), sp(T.since(v.goalTurn) + T.dir(v.direction), { d: 1 }))
      } else head2('goal', sp(T.goal, { b: 1 }), sp(v.goalTurn ? T.since(v.goalTurn) : '', { d: 1 }))
      // 목표 4줄·흐름 3줄 (요구 이력 80). 방금은 처리 결과로 옮겼다 (요구 이력 87)
      for (const line of fitLines('goal', v.goal, cols - 4, 4)) row(sp('   '), ...parts(line))
      if (v.digest) {
        row(sp(T.flow(v.digestTurn), { d: 1 }))
        for (const line of fitLines('goal', v.digest, cols - 4, 3)) row(sp('   ', { d: 1 }), ...parts(line, { d: 1 }))
      }
      if (v.decisions.length) {
        row(sp(' '))
        head2('decisions', sp(T.decisions, { b: 1 }), sp(String(v.decisionCount), { c: 'green' }))
        // ⚠가 붙은 결정은 접혀 있어도 늘 보인다 (요구 이력 87·89)
        const shownD = v.decisions.slice(0, shownOf('decisions', v.decisionCount))
        const listed = [...shownD, ...v.decisions.filter(d => d.warn && !shownD.includes(d))]
        for (const d of listed) {
          // 들여쓰기만 빼고 폭을 다 써서 3줄, #턴은 끝에 (요구 이력 80)
          const tail = (d.turn ? `  #${d.label ?? d.turn}` : '') + (d.proposed ? T.proposed : '') + (d.warn ? T.warnTag(d.warn.at, d.warn.kind) : '')   // 제안 승인 (요구 이력 86), 빠뜨림 (요구 이력 89)
          const { lines, inline, tailLines } = fitTail('decisions', (d.warn ? '⚠ ' : '✔ ') + d.text, cols - 5, 3, tail)
          lines.forEach((line, k) => {
            const ps = parts(line)
            if (k === 0 && d.warn && ps[0]) { ps[0] = { ...ps[0], t: ps[0].t.replace(/^⚠ /, '') }; ps.unshift({ t: '⚠ ', c: 'yellow' }) }   // 기호만 노랑
            row(sp('   '), sp(k ? '  ' : ''), ...ps, k === lines.length - 1 && inline ? sp(tail, { d: 1 }) : sp(''))
          })
          for (const line of tailLines) row(sp('     '), ...parts(line, { d: 1 }))
        }
        moreRow('decisions', v.decisionCount)
      }
      // 처리 결과 (요구 이력 87·88·89): 의사결정과 에이전트 질문 사이, 항목마다 한 줄, 3개까지. 펼치면 다 감싼다. 인용은 두지 않는다(그 응답은 옆 대화창에 있다)
      if (v.handled.length || v.openWarn) {
        row(sp(' '))
        head2('handled', sp(T.handled, { b: 1 }), sp(`#${v.handledTurn}`, { d: 1 }))
        // 프롬프트 복사 하나 (요구 이력 90): 열린 빠뜨림이 있는 동안 처리 결과 맨 위에, 모두를 한 글로. 글은 복사에 실패한 뒤에만 보인다
        // 찾은 턴에는 첫 ⚠ 줄 오른쪽에 붙이고, 그 뒤 턴에는 '⚠ 열린 빠뜨림 n' 줄을 둔다
        // 개수 줄은 열린 빠뜨림이 있는 동안 늘 처리 결과 첫 줄(3줄 상한 밖), 버튼은 그 줄에 하나 (요구 이력 90 검토)
        if (v.openWarn) rows.push({ s: [sp(' ⚠ ', { c: 'yellow' }), sp(T.openWarn(v.openWarn, v.openSince, v.handledTurn))], btn: { k: 'copy', label: T.copyPrompt, key: 'copy-prompt', act: 'copy:all' } })
        for (const h of v.handled.slice(0, shownOf('handled', v.handled.length))) {
          const lead = ` ${h.mark} `
          for (const [k, line] of fitLines('handled', h.summary, cols - 4, 1).entries())
            row(k ? sp('   ') : sp(lead, { c: h.mark === '✔' ? 'green' : 'yellow' }), ...parts(line))
        }
        moreRow('handled', v.handled.length)
        if (v.openWarn) {
          if (revealed.get('all') === v.basis) for (const line of wrapParts(TEXT[v.flowLang === 'ko' ? 'ko' : 'en'].prompt(openList(v)), cols - 6, ALL)) row(sp('   ', { d: 1 }), ...parts(line, { d: 1 }))
        }
      }
      row(sp(' '))
      head2('asks', sp(T.asks, { b: 1 }), sp(v.askCount ? String(v.askCount) : T.none, { c: v.askCount ? 'yellow' : 'green' }))
      // 지금 질문은 모두, 지난 질문은 버튼으로 접고 펼친다 (요구 이력 86)
      const pastOpen = m.asks > 0
      for (const a of [...v.asks, ...(pastOpen ? v.past : [])]) {
        // 요약은 2줄 감싸기, 턴과 꼬리표는 끝에 붙이고 안 들어가면 다음 줄 (요구 이력 80). 턴은 마지막으로 물은 턴
        const lead = ` ${a.n} `
        const tail = ` #${a.turn}${a.first && a.first < a.turn ? T.firstAsked(a.first) : ''}${a.partial ? T.partial : ''}`
        const room = cols - width(lead)
        const { lines, inline, tailLines } = fitTail('asks', a.summary, room, 2, tail)
        lines.forEach((line, k) => row(k ? sp(' '.repeat(width(lead))) : sp(lead, { c: 'yellow', b: 1 }), ...parts(line),
          k === lines.length - 1 && inline ? sp(tail, { d: 1 }) : sp('')))
        for (const line of tailLines) row(sp(' '.repeat(width(lead))), ...parts(line, { d: 1 }))
        quoteRows('asks', a.quote)
      }
      if (v.pastCount) rows.push({ more: 'asks', label: pastOpen ? T.collapse : T.pastAsks(v.pastCount) })
      row(sp(' '))
      // 없으면 '내 요청 중'을 붙이지 않는다: 'Open requests none of mine'처럼 어색해진다 (요구 이력 92)
      head2('left', sp(T.left, { b: 1 }), sp(v.leftCount ? String(v.leftCount) : T.none, { c: v.leftCount ? 'yellow' : 'green' }), sp(v.leftCount ? T.mine : '', { d: 1 }))
      for (const x of v.left.slice(0, shownOf('left', v.leftCount))) {
        // 2줄 감싸기, #턴은 끝에 (요구 이력 80). 표시 ○◐⊘는 넓게 그려질 수 있어 4칸으로 본다
        const tail = ` #${x.turn}`
        const room = cols - 4
        const { lines, inline, tailLines } = fitTail('left', x.summary + (x.note ? ' — ' + x.note : ''), room, 2, tail)
        lines.forEach((line, k) => row(k ? sp('   ') : sp(` ${x.mark} `, { c: 'yellow' }), ...parts(line),
          k === lines.length - 1 && inline ? sp(tail, { d: 1 }) : sp('')))
        for (const line of tailLines) row(sp('   '), ...parts(line, { d: 1 }))
        quoteRows('left', x.quote)   // ⊘의 에이전트 원문 (요구 이력 86)
      }
      moreRow('left', v.leftCount)
      // 알려진 문제 (요구 이력 86): 조사는 했으나 결과 없음. 있을 때만
      if (v.known.length) {
        row(sp(' '))
        head2('known', sp(T.known, { b: 1 }), sp(String(v.known.length), { c: 'yellow' }))
        for (const x of v.known) {
          const { lines, inline, tailLines } = fitTail('known', x.summary, cols - 4, 2, ` #${x.turn}`)
          lines.forEach((line, k) => row(k ? sp('   ') : sp(` ${x.mark} `, { c: 'yellow' }), ...parts(line),
            k === lines.length - 1 && inline ? sp(` #${x.turn}`, { d: 1 }) : sp('')))
          for (const line of tailLines) row(sp('   '), ...parts(line, { d: 1 }))
          quoteRows('known', x.quote)
        }
      }
      // 잘린 글이 있거나 펼친 덩어리의 제목 줄 오른쪽에 펼치기·줄이기 (요구 이력 88)
      for (const [k, i] of Object.entries(heads)) {
        const r = rows[i]
        if (r && 's' in r && (cut[k] || isOpen(k))) r.btn = { k, label: isOpen(k) ? T.shorten : T.expand }
      }
      if (v.terms.length) {
        row(sp(' '))
        row(sp(T.terms, { b: 1 }), sp(T.termsNote, { d: 1 }))
        for (const x of v.terms) {
          row(sp(` ${x.id}`, { c: 'yellow' }))
          ;(x.means.length ? x.means.slice(0, 2) : [T.noDoc]).forEach((mean, k) => {
            for (const line of wrapParts((x.means.length > 1 ? '①②'[k] + ' ' : '') + mean, cols - 4, 2))
              row(sp('   '), ...parts(line, x.means.length ? {} : { d: 1 }))
          })
        }
        if (v.termsMore) row(sp('   ' + T.more(v.termsMore), { d: 1 }))
      }
    }
    const body = drawRows(rows, els, (k, p) => {
      if (k.startsWith('copy:')) { void copyPrompt($, k.slice(5), p?.surface); return }
      void apply($, k.startsWith('text:') ? { op: 'text', k: k.slice(5) } : { op: 'more', k })
    })
    return (
      <Box flexDirection="column">
        {body}
        {tail}
      </Box>
    )
  })

  on('ui.render', { component: 'AbovePrompt' }, async ($, e, next) => {
    // 패널이 옆이든 입력창 위든 그려지고 있으면 띠는 두지 않는다 (겹쳐 보이지 않게). 패널은 1초마다 다시 그려진다
    if ((await $.clock.now()) - paneDrawnAt < 3000) return next(e)
    // 좁은 창에서 시작해 패널이 기다리는 중인데 창이 넓어졌으면 다시 연다 (관제 확인 2026-11-12: 넓혀도 저절로 붙지 않음)
    const v = await read($, view)
    if (v.off) return next(e)   // 끈 세션은 띠도 두지 않는다 (요구 이력 84)
    if ((e.viewport?.columns ?? 0) >= 110 && mayAutoOpen(v)) {   // 켜지 않은 세션·사람이 닫은 패널은 열지 않는다 (요구 이력 53·84)
      const mine = (await $.ui.panes()).find(x => x.id === PANE)
      if (!mine || !mine.isPlaced) void openPane($)
    }
    const busy = v.state === 'running' || v.state === 'queued'
    if (!v.goal && !busy) return next(e)
    if (!busy && v.leftCount === 0 && !v.goal) return next(e)
    const { Text } = $.ui.resolve(e)
    const T = TEXT[v.ui]
    // 목표 자르기 폭: 고정 라벨의 실제 칸 수를 뺀다 (요구 이력 76: 영어 라벨은 폭이 다르다. 한국어 보통 상태에서 예전 52칸과 같다)
    const tailText = T.bandAsks + v.askCount + T.bandLeft + v.leftCount + (busy ? ' · ' + dots(v.tick, v.state, v.ui) : T.bandAsOf(v.basis)) + (!busy && !v.on ? T.bandOff : '')
    const fixed = columns(T.band + T.bandGoal + tailText) + 12
    return (
      <Text>
        <Text bold>{T.band}</Text>
        <Text>{T.bandGoal}{cut(v.goal, Math.max(10, (e.props.bodyColumns ?? 80) - fixed))}</Text>
        <Text color={v.askCount ? 'yellow' : 'green'}>{T.bandAsks}{v.askCount}</Text>
        <Text color={v.leftCount ? 'yellow' : 'green'}>{T.bandLeft}{v.leftCount}</Text>
        {busy ? <Text color="yellow"> · {dots(v.tick, v.state, v.ui)}</Text> : <Text dimColor>{T.bandAsOf(v.basis)}</Text>}
        {!busy && !v.on ? <Text color="yellow">{T.bandOff}</Text> : null}
      </Text>
    )
  })
}
