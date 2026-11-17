// 눈치 mod (REQUIREMENTS R17, SCREEN §11, BUILD_PLAN §4.4)
// 분석기(nunchi-engine)가 쓴 분석 결과(<관제 홈>/sessions/<세션 ID>/analysis.json)를 읽기만 하고, 세션 옆 패널(좁으면 입력창 위 한 줄)에 보인다.
// 분석은 하지 않는다. 분석 상태는 같은 폴더의 analysis_status.json에서 읽는다.
// /nunchi로 켜면 세션 폴더에 want를 남긴다. 그러면 응답이 끝날 때마다 분석기가 이 세션을 분석한다 (요구 이력 53).
// 켜지 않았고 분석 결과도 없는 세션에서는 패널을 저절로 열지 않는다.
import { atom, read, update } from 'claude-code'
import type { Register, EngineInterface } from 'claude-code'

import type { View, Left, More } from '../types'
import { drawRows, type Row, type Span } from './rows'

const PANE = 'nunchi'
const EMPTY: View = {
  basis: 0, total: 0, latest: 0, state: 'none', asks: [], askCount: 0, blanketClosed: 0,
  digest: '', digestTurn: 0, goal: '', goalTurn: 0, decisions: [], decisionCount: 0, recent: '', left: [], leftCount: 0, ratio: 0.4, tick: 0,
  terms: [], termsMore: 0, on: false, error: '', control: false, behind: 0,
}
const view = atom({ plugin: 'nunchi', key: 'view' } as const, EMPTY, { shape: 'view-9' })
// 펼친 수 (요구 이력 74): view와 따로 둔다. view는 분석 결과가 올 때마다 통째로 다시 쓰여 함께 두면 풀린다
const NO_MORE: More = { decisions: 0, asks: 0, left: 0, all: false }
const more = atom({ plugin: 'nunchi', key: 'more' } as const, NO_MORE, { shape: 'more-2' })
const STEP = 5   // 한 번 누를 때 더 보이는 수

// 펼친 수 바꾸기 (요구 이력 74·75). 모두 펼침은 개수가 아니라 표시라 목록이 늘어도 모두 보이고, 줄이기는 실제 개수에서 줄인다
type Totals = { decisions: number; asks: number; left: number }
const SECTIONS = ['decisions', 'asks', 'left'] as const
export function moved(m: More, t: Totals, op: { op?: string; d?: number; k?: string }): More {
  const room = (k: typeof SECTIONS[number]) => Math.max(0, t[k] - SHOWN)
  const now = (k: typeof SECTIONS[number]) => m.all ? room(k) : Math.min(m[k], room(k))
  const base: More = { decisions: now('decisions'), asks: now('asks'), left: now('left'), all: false }
  if (op.op === 'all') return { ...base, all: true }
  if (op.op === 'none' || op.op === 'more' && op.k === 'collapse') return NO_MORE
  if (op.op === 'step') {
    if (m.all && (op.d ?? 0) > 0) return m
    for (const k of SECTIONS) base[k] = Math.max(0, Math.min(room(k), base[k] + STEP * Math.sign(op.d ?? 0)))
    return base
  }
  if (op.op === 'more' && (SECTIONS as readonly string[]).includes(op.k ?? '')) {
    const k = op.k as typeof SECTIONS[number]
    base[k] = base[k] >= room(k) ? 0 : Math.min(room(k), base[k] + STEP)
    return base
  }
  return m
}
const SAVED = '/mod.json'   // 새 세션에도 모두 펼칠지 (요구 이력 75). 사람이 고치는 config.json과 따로

async function apply($: EngineInterface, op: { op?: string; d?: number; k?: string }) {
  const v = await read($, view)
  await update($, more, x => moved(x ?? NO_MORE, { decisions: v.decisionCount, asks: v.askCount, left: v.leftCount }, op))
  if (op.op === 'all' || op.op === 'none') {
    await $.fs.write((await controlHome($)) + SAVED, JSON.stringify({ expand: op.op }) + '\n')
    $.ui.toast(op.op === 'all' ? '눈치: 모두 펼쳤습니다. 새 세션도 모두 펼친 채 엽니다' : '눈치: 모두 접었습니다. 새 세션도 처음 3개로 엽니다')
  }
}

const SHOWN = 3
const MAX_RATIO = 0.45   // Claude Code가 옆 패널에 허락하는 폭
let paneDrawnAt = 0      // 패널이 마지막으로 그려진 때. 패널이 보이는 동안은 띠를 두지 않는다
let askedColumns = 0     // 마지막으로 요청한 옆 패널 폭
let opened = false       // 이 세션에서 패널을 한 번 열었는지 (켠 세션·분석된 세션만 저절로 연다)

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
  const home = await controlHome($)
  const ctl = await readJson($, home + '/control.json')
  if (!ctl?.iterm_session_id) return '관제가 꺼져 있습니다. 다른 패널에서 nunchi로 켜세요.'
  const alive = await $.process.run(['kill', '-0', String(ctl.pid ?? '')]).catch(() => null)
  if (!alive || alive.exitCode !== 0) return '관제가 꺼져 있습니다. 다른 패널에서 nunchi로 켜세요.'
  await $.fs.write(home + '/goto', JSON.stringify({ session: await sessionId($), at: (await $.clock.now()) / 1000 }) + '\n')
  const r = await $.process.run(['osascript', '-e', FOCUS_SCRIPT, String(ctl.iterm_session_id)]).catch(() => null)
  if (!r || r.exitCode !== 0 || !String(r.stdout).includes('ok')) return '관제 패널을 찾지 못했습니다. ⌘숫자로 옮겨 가세요.'
  return ''
}

async function readJson($: EngineInterface, path: string): Promise<any> {
  try {
    return JSON.parse(String(await $.fs.read(path)))
  } catch {
    return null
  }
}

function one(text: unknown, cut = 200): string {
  return String(text ?? '').split(/\s+/).join(' ').trim().slice(0, cut)
}

/** 켠 세션이거나 분석 결과가 있으면 패널을 둔다 (요구 이력 53) */
export function enabled(v: View): boolean {
  return v.on || v.basis > 0 || !!v.goal
}

export function buildView(analysis: any, status: any, tick: number, ratio: number, gloss: any = null, on = false): View {
  const terms = (gloss?.items ?? []).map((x: any) => ({ id: one(x.id, 20), means: (x.means ?? []).map((m: any) => one(m, 120)) }))
  const termsMore = Math.max(0, (gloss?.total ?? 0) - terms.length)
  const error = status?.state === 'failed' ? one(status?.error, 60) : ''
  const base = { ...EMPTY, state: status?.state ?? 'none', latest: status?.turn ?? 0, tick, ratio, terms, termsMore, on, error }
  if (!analysis) return base
  const flow = analysis.flow ?? {}
  const steps: any[] = (flow.steps ?? []).filter((s: any) => s.grounded)
  const basis = flow.until ?? analysis.last_turn ?? 0
  const open = (flow.asks ?? []).filter((a: any) => a.state !== 'answered')
    .sort((a: any, b: any) => (b.last_turn ?? b.turn ?? 0) - (a.last_turn ?? a.turn ?? 0))
  const asks = open.map((a: any, k: number) => ({
    n: k + 1, summary: one(a.summary, 60), turn: a.turn ?? 0, quote: one(a.quote, 60),
    partial: a.state === 'partial', stale: (a.last_turn ?? a.turn ?? 0) < basis - 1,
  }))
  const left: Left[] = []
  for (const r of flow.requests ?? []) {
    if (r.state === 'open') left.push({ mark: '○', summary: one(r.summary), note: '', turn: r.from_turn ?? 0 })
    else if (r.state === 'deferred') left.push({ mark: '⊘', summary: one(r.summary), note: '못 했거나 미룸', turn: r.from_turn ?? 0 })
    else if (r.state === 'in_progress') left.push({ mark: '◐', summary: one(r.summary), note: '진행 중', turn: r.by_turn ?? r.from_turn ?? 0 })   // 요구 이력 66
  }
  // 도구 실패(△)는 보이지 않는다: 도구 사용은 모으지도 보이지도 않는다 (요구 이력 48)
  // 의사결정 (요구 이력 71): 관계가 확정인 턴. 분석기의 요약이라 원문 대조가 없으므로 정한 턴을 함께 보인다
  // 정한 내용 한 줄(decision)을 먼저, 없으면 제목 (요구 이력 72). 최근 것부터 놓아 펼친 것이 아래로 이어진다 (요구 이력 74)
  const decided = steps.filter((s: any) => s.label === '확정')
  const decisions = decided.slice().reverse().map((s: any) => ({ text: one(s.decision || s.title || s.summary, 120), turn: s.index ?? 0 }))
  const last = steps.length ? steps[steps.length - 1] : null
  // 처음부터 이 턴까지 한 덩어리 정리: 분석기가 턴마다 써 둔 digest 중 마지막 것 (요구 이력 57, 추정)
  const digested = (flow.steps ?? []).filter((s: any) => s.digest).pop()
  return {
    ...base,
    basis,
    total: analysis.last_turn ?? 0,
    state: status?.state ?? 'idle',
    asks,
    askCount: open.length,
    blanketClosed: (flow.asks ?? []).filter((a: any) => a.state === 'answered' && a.by_blanket).length,
    digest: digested && digested.index > 1 ? one(digested.digest, 240) : '',
    digestTurn: digested?.index ?? 0,
    goal: one(flow.current_goal?.text ?? analysis.current_goal ?? ''),
    goalTurn: flow.current_goal?.turn ?? 0,
    decisions,
    decisionCount: decided.length,
    recent: one(last?.agent_summary ?? '', 240),
    left,
    leftCount: left.length,
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

/** 칸 수(한글 2칸)에 맞춰 여러 줄로 감싼다. 넘치면 마지막 줄 끝을 …로 (요구 이력 50) */
function wrapParts(text: string, cols: number, maxLines: number): Piece[][] {
  const wide = (ch: string) => /[\u1100-\u115f\u2e80-\ua4cf\uac00-\ud7a3\uf900-\ufaff\ufe30-\ufe4f\uff00-\uff60\uffe0-\uffe6\u2714]/.test(ch) ? 2 : 1
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
    const room = cols - 2
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
function wrap(text: string, cols: number, maxLines: number): string[] {
  return wrapParts(text, cols, maxLines).map(flat)
}

function dots(tick: number, state = 'running'): string {
  return (state === 'queued' ? '분석 대기' : '분석 중') + ['.', '..', '...'][tick % 3]
}

async function openPane($: EngineInterface) {
  opened = true
  return $.ui.open({ id: PANE, title: '눈치' })
}

// 분석이 본 마지막 응답 뒤에 끝난 응답 수 (요구 이력 65). 훅이 모든 세션의 Stop을 events.jsonl에 남긴다.
// 한 턴 안에서 이어 끝난 응답도 센다(그것도 아직 분석에 없는 내용, 요구 이력 64).
// 파일에는 도구 기록도 쌓여 일하는 동안 매초 커지므로, 처음·이 세션 응답이 끝난 뒤 잠깐·분석 기준이 바뀔 때만 읽는다.
const RECOUNT_MS = 5000      // 응답이 끝난 뒤 훅이 Stop을 적을 때까지 기다리는 동안 다시 센다
let countedSince: string | null = null
let recountUntil = 0
let behindCount = 0
export function answerEnded(now: number) { recountUntil = now + RECOUNT_MS }
export async function answersAfter($: EngineInterface, dir: string, since: string): Promise<number> {
  const now = await $.clock.now()
  if (since === countedSince && now > recountUntil) return behindCount
  countedSince = since
  try {
    const stops = String(await $.fs.read(dir + '/events.jsonl')).split('\n').filter(l => l.includes('"Stop"')).map(l => {
      try { const e = JSON.parse(l); return e.event === 'Stop' ? String(e.ts ?? '') : '' } catch { return '' }
    })
    behindCount = since ? stops.filter(ts => ts && ts > since).length : 0
  } catch {
    behindCount = 0
  }
  return behindCount
}

async function refresh($: EngineInterface) {
  const dir = await sessionDir($)
  const home = await controlHome($)
  const [analysis, status, config, gloss, want, ctl] = await Promise.all([
    readJson($, dir + '/analysis.json'), readJson($, dir + '/analysis_status.json'),
    readJson($, home + '/config.json'), readJson($, dir + '/glossary.json'),
    readJson($, dir + '/want'), readJson($, home + '/control.json'),
  ])
  const ratio = Math.min(MAX_RATIO, Math.max(0.2, Number(config?.mod_width_ratio) || 0.4))
  const behind = await answersAfter($, dir, String(analysis?.source_ts ?? ''))
  await update($, view, old => ({ ...buildView(analysis, status, (old?.tick ?? 0) + 1, ratio, gloss, want !== null),
    control: !!ctl?.iterm_session_id, behind }))
  if (!opened && enabled(await read($, view))) void openPane($)   // 켠 세션이나 관제가 분석한 세션만 저절로 연다
}

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    await $.command.register({ name: 'nunchi', description: '눈치 켜기: 이 세션을 분석하고 패널을 연다' })
    await refresh($)
    // 저장해 둔 모두 펼침 (요구 이력 75): 이 세션에서 아직 펼치거나 접지 않았을 때만
    const saved = await readJson($, (await controlHome($)) + SAVED)
    const now = await read($, more)
    if (saved?.expand === 'all' && !now.all && !now.decisions && !now.asks && !now.left) await update($, more, () => ({ ...NO_MORE, all: true }))
    $.clock.every(1000, () => { void refresh($) })   // 분석 파일이 바뀌면 다시 그린다. '분석 중' 점도 1초마다
    return next(e)
  })

  on('turn.complete', async ($, e, next) => {
    if (!(e as any).agentId) answerEnded(await $.clock.now())   // 이 세션 응답이 끝남: 밀린 응답 수를 다시 센다 (하위 에이전트 끝은 빼고)
    return next(e)
  })

  on('command.run', { command: 'nunchi' }, async $ => {
    const dir = await sessionDir($)
    const was = (await readJson($, dir + '/want')) !== null
    await $.fs.write(dir + '/want', JSON.stringify({ at: new Date(await $.clock.now()).toISOString(), by: 'nunchi' }) + '\n')
    await refresh($)
    const r = await openPane($)
    const where = r.isPlaced ? '' : ' 창이 좁아 패널 대신 입력창 위 한 줄로 보입니다.'
    const v = await read($, view)
    if (was || v.basis > 0) return { text: '눈치 패널을 열었습니다.' + where }
    return { text: '눈치를 켰습니다. 다음 응답이 끝나면 이 세션을 분석합니다.' + where }
  })

  on('ui.message', async ($, e) => {
    const d = (e as any).data
    if (d && typeof d === 'object' && typeof d.op === 'string') await apply($, d)
    return {}
  })

  on('ui.render', { component: 'Pane', requestId: PANE }, async ($, e) => {
    const els: any = $.ui.resolve(e)
    const { Box, Text, Button, Client } = els
    const v = await read($, view)
    const m = await read($, more)
    const cols = Math.max(20, e.props.bodyColumns ?? 50)
    const toControl = async () => {
      const problem = await goControl($)
      if (problem) $.ui.toast(problem)
    }
    const tail = v.control
      ? <Box flexDirection="row"><Button key="control" hotkey="1" onPress={() => { void toControl() }}>관제로</Button><Text dimColor>  또는 ⌘숫자</Text></Box>
      : null   // 관제 화면을 지워(요구 이력 70) 켜라고 하지 않는다
    paneDrawnAt = await $.clock.now()
    // viewport는 패널을 뺀 나머지 폭이라(실측 2026-11-12: 200칸 창에서 141), 창 전체 = 나머지 + 패널 + 경계로 본다
    const whole = (e.viewport?.columns ?? 0) + (e.props.placement === 'dock' ? cols + 2 : 0)
    const want = Math.round(whole * v.ratio)
    if (e.props.placement === 'dock' && want >= 24 && Math.abs(want - askedColumns) > 1) {
      askedColumns = want   // 창 폭의 비율로 다시 요청한다 (사용자가 끌어 정한 폭이 있으면 그것이 앞선다)
      void $.ui.open({ id: PANE, title: '눈치', columns: want })
    }
    // 본문 줄 (요구 이력 75): 다 만든 줄을 키를 받는 본문(Client)에 넘긴다. Client가 없는 화면은 같은 줄을 여기서 그린다
    // vscode·모바일 표에도 Client가 들어 있지만 빈 상자로 그린다(시험 2026-11-17): 화면 이름으로 고른다
    const keys = !!Client && (e.surface === 'terminal' || e.surface === 'desktop')
    const rows: Row[] = []
    const row = (...s: Span[]) => { rows.push({ s: s.filter(x => x.t) }) }
    const sp = (t: string, o: Omit<Span, 't'> = {}): Span => ({ t, ...o })
    const parts = (line: Piece[], o: Omit<Span, 't' | 'href'> = {}): Span[] => line.map(p => p.href ? { t: p.t, href: p.href } : { t: p.t, ...o })
    const busy = v.state === 'running' || v.state === 'queued'
    const rebuilding = busy && v.latest > 0 && v.total > 0 && v.latest < v.total
    if (!v.goal && v.basis === 0) {   // 아직 분석 결과가 없다 (SCREEN §11)
      row(sp('눈치', { b: 1 }))
      row(v.state === 'running' || v.state === 'queued' ? sp(dots(v.tick, v.state), { c: 'yellow' })
        : v.state === 'failed' ? sp('분석 실패 · ' + v.error, { c: 'red' })
        : v.on ? sp('눈치 켜짐 · 다음 응답이 끝나면 분석합니다', { d: 1 })
        : sp('눈치 꺼짐 · /nunchi로 켜면 이 세션을 분석합니다', { d: 1 }))
    } else {
      // … n개 더 (요구 이력 74): 누를 때마다 그 덩어리만 5개씩, 다 펼치면 접기
      const shownOf = (k: keyof Totals, total: number) => m.all ? total : Math.min(total, SHOWN + m[k])
      const moreRow = (k: keyof Totals, total: number) => {
        if (total <= SHOWN) return
        const rest = total - shownOf(k, total)
        rows.push({ more: k, label: rest > 0 ? `… ${rest}개 더` : '접기' })
      }
      row(sp('눈치', { b: 1 }), sp(` · #${v.basis} 기준`, { d: 1 }),
        v.behind > 0 && !busy ? sp(` · 응답 ${v.behind}개 밀림`, { c: 'yellow' }) : sp(''),
        rebuilding ? sp(`  ${v.basis <= 1 ? '흐름 처음부터 만드는 중' : '밀린 턴 반영 중'} #${v.latest}/#${v.total} ${dots(v.tick)}`, { c: 'yellow' })
          : busy ? sp('  ' + dots(v.tick, v.state), { c: 'yellow' })
          : v.state === 'failed' ? sp('  분석 실패 · ' + v.error, { c: 'red' })
          : !v.on ? sp('  자동 분석 꺼짐 · /nunchi로 켜기', { c: 'yellow' }) : sp(''))
      row(sp(' '))
      // 차례 (요구 이력 71): 목표 → 의사결정 → 에이전트 질문 → 남은 요청
      row(sp('목표', { b: 1 }), sp(v.goalTurn ? `  #${v.goalTurn}부터` : '', { d: 1 }))
      for (const line of wrapParts(v.goal, cols - 4, 3)) row(sp('   '), ...parts(line))
      if (v.digest) {
        row(sp(` 흐름  #1–#${v.digestTurn}`, { d: 1 }))
        for (const line of wrapParts(v.digest, cols - 4, 3)) row(sp('   ', { d: 1 }), ...parts(line, { d: 1 }))
      }
      if (v.recent) {
        row(sp(' 방금', { d: 1 }))
        for (const line of wrapParts(v.recent, cols - 4, 3)) row(sp('   ', { d: 1 }), ...parts(line, { d: 1 }))
      }
      if (v.decisions.length) {
        row(sp(' '))
        row(sp('의사결정 ', { b: 1 }), sp(String(v.decisionCount), { c: 'green' }))
        for (const d of v.decisions.slice(0, shownOf('decisions', v.decisionCount))) {
          const lines = wrapParts('✔ ' + d.text, cols - 12, 2)
          lines.forEach((line, k) => row(sp('   '), sp(k ? '  ' : ''), ...parts(line),
            k === lines.length - 1 && d.turn ? sp(`  #${d.turn}`, { d: 1 }) : sp('')))
        }
        moreRow('decisions', v.decisionCount)
      }
      row(sp(' '))
      row(sp('에이전트 질문 ', { b: 1 }), sp(v.askCount ? String(v.askCount) : '없음', { c: v.askCount ? 'yellow' : 'green' }))
      for (const a of v.asks.slice(0, shownOf('asks', v.askCount))) {
        row(sp(` ${a.n} `, { c: 'yellow', b: 1 }), ...parts(cutParts(a.summary, cols - 12)),
          sp(` #${a.turn}${a.stale ? '부터 답 없음' : ''}${a.partial ? ' · 일부 답함' : ''}`, { d: 1 }))
        row(sp('   “', { d: 1 }), ...parts(cutParts(a.quote, cols - 6), { d: 1 }), sp('”', { d: 1 }))
      }
      moreRow('asks', v.askCount)
      if (v.blanketClosed) row(sp(`   통째 승인으로 닫은 것 ${v.blanketClosed}`, { d: 1 }))
      row(sp(' '))
      row(sp('남은 요청 ', { b: 1 }), sp(v.leftCount ? String(v.leftCount) : '없음', { c: v.leftCount ? 'yellow' : 'green' }), sp(' 내 요청 중', { d: 1 }))
      for (const x of v.left.slice(0, shownOf('left', v.leftCount)))
        row(sp(` ${x.mark} `, { c: 'yellow' }), ...parts(cutParts(x.summary + (x.note ? ' — ' + x.note : ''), cols - 8)), sp(` #${x.turn}`, { d: 1 }))
      moreRow('left', v.leftCount)
      if (v.terms.length) {
        row(sp(' '))
        row(sp('번호 풀이', { b: 1 }), sp('  이번 응답 · 문서 원문', { d: 1 }))
        for (const x of v.terms) {
          row(sp(` ${x.id}`, { c: 'yellow' }))
          ;(x.means.length ? x.means.slice(0, 2) : ['문서에 없음']).forEach((mean, k) => {
            for (const line of wrapParts((x.means.length > 1 ? '①②'[k] + ' ' : '') + mean, cols - 4, 2))
              row(sp('   '), ...parts(line, x.means.length ? {} : { d: 1 }))
          })
        }
        if (v.termsMore) row(sp(`   … ${v.termsMore}개 더`, { d: 1 }))
      }
      const totals: Totals = { decisions: v.decisionCount, asks: v.askCount, left: v.leftCount }
      const overflow = SECTIONS.some(k => totals[k] > SHOWN)
      // 실제로 3개 넘게 그려진 덩어리가 있을 때만 (펼친 뒤 목록이 줄면 접을 것이 없다)
      const expanded = SECTIONS.some(k => shownOf(k, totals[k]) > SHOWN)
      row(sp(' '))
      if (expanded) rows.push({ more: 'collapse', label: '모두 접기' })
      if (overflow && keys) row(sp('] 펼치기 · [ 줄이기 · shift와 함께 누르면 새 세션에도 (패널을 클릭한 뒤)', { d: 1 }))
    }
    const body = keys
      ? <Client key="body" module="./body.tsx" props={{ rows }} />
      : drawRows(rows, els, k => { void apply($, { op: 'more', k }) })
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
    if ((e.viewport?.columns ?? 0) >= 110 && enabled(v)) {   // 켜지 않은 세션에서는 열지 않는다 (요구 이력 53)
      const mine = (await $.ui.panes()).find(x => x.id === PANE)
      if (!mine || !mine.isPlaced) void openPane($)
    }
    const busy = v.state === 'running' || v.state === 'queued'
    if (!v.goal && !busy) return next(e)
    if (!busy && v.leftCount === 0 && !v.goal) return next(e)
    const { Text } = $.ui.resolve(e)
    return (
      <Text>
        <Text bold>눈치 </Text>
        <Text>목표: {cut(v.goal, Math.max(10, (e.props.bodyColumns ?? 80) - 52))}</Text>
        <Text color={v.askCount ? 'yellow' : 'green'}> · 질문 {v.askCount}</Text>
        <Text color={v.leftCount ? 'yellow' : 'green'}> · 요청 {v.leftCount}</Text>
        {busy ? <Text color="yellow"> · {dots(v.tick, v.state)}</Text> : <Text dimColor> · #{v.basis} 기준</Text>}
        {!busy && !v.on ? <Text color="yellow"> · 분석 꺼짐</Text> : null}
      </Text>
    )
  })
}
