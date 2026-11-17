// 눈치 mod (REQUIREMENTS R17, SCREEN §11, BUILD_PLAN §4.4)
// 분석기(nunchi-engine)가 쓴 분석 결과(<관제 홈>/sessions/<세션 ID>/analysis.json)를 읽기만 하고, 세션 옆 패널(좁으면 입력창 위 한 줄)에 보인다.
// 분석은 하지 않는다. 분석 상태는 같은 폴더의 analysis_status.json에서 읽는다.
// /nunchi로 켜면 세션 폴더에 want를 남긴다. 그러면 응답이 끝날 때마다 분석기가 이 세션을 분석한다 (요구 이력 53).
// 켜지 않았고 분석 결과도 없는 세션에서는 패널을 저절로 열지 않는다.
import { atom, read, update } from 'claude-code'
import type { Register, EngineInterface } from 'claude-code'

import type { View, Left, More } from '../types'
import { drawRows, type Row, type Span } from './rows'
import { TEXT, pick, norm, langName, failText, columns, ASK_LANG, OPT_KO, OPT_EN, OPT_FOLLOW, type Ui } from './lang'

const PANE = 'nunchi'
const EMPTY: View = {
  basis: 0, total: 0, latest: 0, state: 'none', asks: [], askCount: 0, blanketClosed: 0,
  digest: '', digestTurn: 0, goal: '', goalTurn: 0, decisions: [], decisionCount: 0, recent: '', left: [], leftCount: 0, ratio: 0.4, tick: 0,
  terms: [], termsMore: 0, on: false, error: '', control: false, behind: 0,
  ui: 'ko', want: 'ko', from: 'default', flowLang: 'ko', analyzed: false, rebuilding: false,
}
const view = atom({ plugin: 'nunchi', key: 'view' } as const, EMPTY, { shape: 'view-10' })
// 펼친 수 (요구 이력 74): view와 따로 둔다. view는 분석 결과가 올 때마다 통째로 다시 쓰여 함께 두면 풀린다. 이 세션에만 (요구 이력 77)
const NO_MORE: More = { decisions: 0, asks: 0, left: 0 }
const more = atom({ plugin: 'nunchi', key: 'more' } as const, NO_MORE, { shape: 'more-3' })
const STEP = 5   // 한 번 누를 때 더 보이는 수

// 펼친 수 바꾸기 (요구 이력 74·77). 덩어리별 `… n개 더`는 그 덩어리만, 맨 아래 펼치기·줄이기는 세 덩어리 함께 5개씩
type Totals = { decisions: number; asks: number; left: number }
const SECTIONS = ['decisions', 'asks', 'left'] as const
export function moved(m: More, t: Totals, op: { op?: string; d?: number; k?: string }): More {
  const room = (k: typeof SECTIONS[number]) => Math.max(0, t[k] - SHOWN)
  const now = (k: typeof SECTIONS[number]) => Math.min(m[k], room(k))
  const base: More = { decisions: now('decisions'), asks: now('asks'), left: now('left') }
  if (op.op === 'step' || op.op === 'more' && (op.k === 'expand' || op.k === 'shrink')) {
    const d = op.op === 'step' ? Math.sign(op.d ?? 0) : op.k === 'expand' ? 1 : -1
    for (const k of SECTIONS) base[k] = Math.max(0, Math.min(room(k), base[k] + STEP * d))
    return base
  }
  if (op.op === 'more' && (SECTIONS as readonly string[]).includes(op.k ?? '')) {
    const k = op.k as typeof SECTIONS[number]
    base[k] = base[k] >= room(k) ? 0 : Math.min(room(k), base[k] + STEP)
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

async function apply($: EngineInterface, op: { op?: string; d?: number; k?: string }) {
  const v = await read($, view)
  await update($, more, x => moved(x ?? NO_MORE, { decisions: v.decisionCount, asks: v.askCount, left: v.leftCount }, op))
}

const SHOWN = 3
const MAX_RATIO = 0.45   // Claude Code가 옆 패널에 허락하는 폭
let paneDrawnAt = 0      // 패널이 마지막으로 그려진 때. 패널이 보이는 동안은 띠를 두지 않는다
let askedColumns = 0     // 마지막으로 요청한 옆 패널 폭
let opened = false       // 이 세션에서 패널을 한 번 열었는지 (켠 세션·분석된 세션만 저절로 연다)
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

function one(text: unknown, cut = 200): string {
  return String(text ?? '').split(/\s+/).join(' ').trim().slice(0, cut)
}

/** 켠 세션이거나 분석 결과가 있으면 패널을 둔다 (요구 이력 53) */
export function enabled(v: View): boolean {
  return v.on || v.basis > 0 || !!v.goal
}

export function buildView(analysis: any, status: any, tick: number, ratio: number, gloss: any = null, on = false, ui: Ui = 'ko'): View {
  const T = TEXT[ui]
  const terms = (gloss?.items ?? []).map((x: any) => ({ id: one(x.id, 20), means: (x.means ?? []).map((m: any) => one(m, 120)) }))
  const termsMore = Math.max(0, (gloss?.total ?? 0) - terms.length)
  const error = status?.state === 'failed' ? one(failText(one(status?.error, 200), ui), 60) : ''   // 엔진은 실패 이유를 코드로 남긴다 (요구 이력 76)
  const rebuilding = !!status?.rebuild && (status?.state === 'running' || status?.state === 'queued')
  const base = { ...EMPTY, state: status?.state ?? 'none', latest: status?.turn ?? 0, tick, ratio, terms, termsMore, on, error, ui, rebuilding }
  if (!analysis) return base
  const flow = analysis.flow ?? {}
  const steps: any[] = (flow.steps ?? []).filter((s: any) => s.grounded)
  const basis = flow.until ?? analysis.last_turn ?? 0
  const open = (flow.asks ?? []).filter((a: any) => a.state !== 'answered')
    .sort((a: any, b: any) => (b.last_turn ?? b.turn ?? 0) - (a.last_turn ?? a.turn ?? 0))
  const asks = open.map((a: any, k: number) => ({
    n: k + 1, summary: one(a.summary, 100), turn: a.turn ?? 0, quote: one(a.quote, 60),   // 요약 100: 영어 세션은 엔진이 100자까지 남긴다 (요구 이력 76)
    partial: a.state === 'partial', stale: (a.last_turn ?? a.turn ?? 0) < basis - 1,
  }))
  const left: Left[] = []
  for (const r of flow.requests ?? []) {
    if (r.state === 'open') left.push({ mark: '○', summary: one(r.summary), note: '', turn: r.from_turn ?? 0 })
    else if (r.state === 'deferred') left.push({ mark: '⊘', summary: one(r.summary), note: T.deferred, turn: r.from_turn ?? 0 })
    else if (r.state === 'in_progress') left.push({ mark: '◐', summary: one(r.summary), note: T.inProgress, turn: r.by_turn ?? r.from_turn ?? 0 })   // 요구 이력 66
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
    flowLang: norm(flow.lang) || 'ko',   // 이 세션의 분석 언어. 엔진은 ko면 적지 않는다 (요구 이력 76)
    analyzed: true,
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

function dots(tick: number, state = 'running', ui: Ui = 'ko'): string {
  return (state === 'queued' ? TEXT[ui].queued : TEXT[ui].running) + ['.', '..', '...'][tick % 3]
}

async function openPane($: EngineInterface) {
  opened = true
  return $.ui.open({ id: PANE, title: TEXT[shownUi].title })
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
  const [analysis, status, config, gloss, want, ctl, saved] = await Promise.all([
    readJson($, dir + '/analysis.json'), readJson($, dir + '/analysis_status.json'),
    readJson($, home + '/config.json'), readJson($, dir + '/glossary.json'),
    readJson($, dir + '/want'), readJson($, home + '/control.json'), readJson($, home + SAVED),
  ])
  const ratio = Math.min(MAX_RATIO, Math.max(0.2, Number(config?.mod_width_ratio) || 0.4))
  const behind = await answersAfter($, dir, String(analysis?.source_ts ?? ''))
  const lang = await language($, saved)   // 1초마다 다시 정하므로 다른 세션에서 바꿔도 곧 따라온다
  await update($, view, old => ({ ...buildView(analysis, status, (old?.tick ?? 0) + 1, ratio, gloss, want !== null, lang.ui),
    control: !!ctl?.iterm_session_id, behind, want: lang.analysis, from: lang.from }))
  if (!opened && enabled(await read($, view))) void openPane($)   // 켠 세션이나 관제가 분석한 세션만 저절로 연다
}

/** /nunchi language (요구 이력 76): 질문 창에서 고른다. Esc·-p(거절)면 바꾸지 않는다 */
async function chooseLanguage($: EngineInterface): Promise<string> {
  const now = await language($)
  const T = TEXT[now.ui]
  const from = now.from === 'claude' ? T.fromClaude : ''
  const opts = now.analysis === 'en' ? [OPT_EN, OPT_KO, OPT_FOLLOW] : [OPT_KO, OPT_EN, OPT_FOLLOW]   // 지금 언어가 맨 위
  let answer: string
  try {
    answer = await $.ui.ask(ASK_LANG(langName(now.analysis), from), opts)
  } catch {
    return T.unchanged + ' ' + T.langNow(langName(now.analysis), from)
  }
  const picked = answer === OPT_KO ? 'ko' : answer === OPT_EN ? 'en' : answer === OPT_FOLLOW ? undefined : norm(answer)
  if (picked !== undefined && picked !== 'ko' && picked !== 'en') return T.unchanged   // 직접 쓴 글은 두 언어만 받는다
  await saveMod($, { language: picked })
  const after = await language($)
  await refresh($)
  const T2 = TEXT[after.ui]
  return picked === undefined ? T2.langFollow(langName(after.analysis)) : T2.langSet(langName(after.analysis))
}

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    const first = await language($)
    await $.command.register({ name: 'nunchi', description: TEXT[first.ui].command, argumentHint: '[language]' })
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

  on('turn.complete', async ($, e, next) => {
    if (!(e as any).agentId) answerEnded(await $.clock.now())   // 이 세션 응답이 끝남: 밀린 응답 수를 다시 센다 (하위 에이전트 끝은 빼고)
    return next(e)
  })

  on('command.run', { command: 'nunchi' }, async ($, e) => {
    if (String((e as any).args ?? '').trim().toLowerCase() === 'language') return { text: await chooseLanguage($) }
    const dir = await sessionDir($)
    const was = (await readJson($, dir + '/want')) !== null
    await $.fs.write(dir + '/want', JSON.stringify({ at: new Date(await $.clock.now()).toISOString(), by: 'nunchi' }) + '\n')
    await refresh($)
    const r = await openPane($)
    const T = TEXT[(await read($, view)).ui]
    const where = r.isPlaced ? '' : T.narrow
    const v = await read($, view)
    if (was || v.basis > 0) return { text: T.opened + where }
    return { text: T.turnedOn + where }
  })

  on('ui.render', { component: 'Pane', requestId: PANE }, async ($, e) => {
    const els: any = $.ui.resolve(e)
    const { Box, Text, Button } = els
    const v = await read($, view)
    const m = await read($, more)
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
    if (e.props.placement === 'dock' && want >= 24 && Math.abs(want - askedColumns) > 1) {
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
      row(v.rebuilding && busy ? sp(progress + ' ' + dots(v.tick, v.state, v.ui).replace(/^[^.]*/, ''), { c: 'yellow' })
        : v.state === 'running' || v.state === 'queued' ? sp(dots(v.tick, v.state, v.ui), { c: 'yellow' })
        : v.state === 'failed' ? sp(T.failed + v.error, { c: 'red' })
        : v.on ? sp(T.onWaiting, { d: 1 })
        : sp(T.offIdle, { d: 1 }))
    } else {
      // … n개 더 (요구 이력 74): 누를 때마다 그 덩어리만 5개씩, 다 펼치면 접기
      const shownOf = (k: keyof Totals, total: number) => Math.min(total, SHOWN + m[k])
      const moreRow = (k: keyof Totals, total: number) => {
        if (total <= SHOWN) return
        const rest = total - shownOf(k, total)
        rows.push({ more: k, label: rest > 0 ? T.more(rest) : T.collapse })
      }
      row(sp(T.title, { b: 1 }), sp(T.asOf(v.basis), { d: 1 }),
        v.behind > 0 && !busy ? sp(T.behind(v.behind), { c: 'yellow' }) : sp(''),
        rebuilding || (v.rebuilding && busy) ? sp(`  ${progress} ${dots(v.tick, 'running', v.ui).replace(/^[^.]*/, '')}`, { c: 'yellow' })
          : busy ? sp('  ' + dots(v.tick, v.state, v.ui), { c: 'yellow' })
          : v.state === 'failed' ? sp('  ' + T.failed + v.error, { c: 'red' })
          : !v.on ? sp('  ' + T.autoOff, { c: 'yellow' }) : sp(''))
      // 화면과 이 세션의 분석 언어가 다르면 (요구 이력 76): 고른 분석 언어와 다를 때 다시 분석하는 법
      if (v.analyzed && v.flowLang !== v.want && !v.rebuilding) row(sp(T.langLine(langName(v.flowLang)), { c: 'yellow', d: 1 }))
      row(sp(' '))
      // 차례 (요구 이력 71): 목표 → 의사결정 → 에이전트 질문 → 남은 요청
      row(sp(T.goal, { b: 1 }), sp(v.goalTurn ? T.since(v.goalTurn) : '', { d: 1 }))
      // 목표·흐름·방금은 각 2줄까지: 목표 덩어리가 길어 아래 덩어리가 첫 화면에서 밀리지 않게 (요구 이력 77)
      for (const line of wrapParts(v.goal, cols - 4, 2)) row(sp('   '), ...parts(line))
      if (v.digest) {
        row(sp(T.flow(v.digestTurn), { d: 1 }))
        for (const line of wrapParts(v.digest, cols - 4, 2)) row(sp('   ', { d: 1 }), ...parts(line, { d: 1 }))
      }
      if (v.recent) {
        row(sp(T.recent, { d: 1 }))
        for (const line of wrapParts(v.recent, cols - 4, 2)) row(sp('   ', { d: 1 }), ...parts(line, { d: 1 }))
      }
      if (v.decisions.length) {
        row(sp(' '))
        row(sp(T.decisions, { b: 1 }), sp(String(v.decisionCount), { c: 'green' }))
        for (const d of v.decisions.slice(0, shownOf('decisions', v.decisionCount))) {
          const lines = wrapParts('✔ ' + d.text, cols - 12, 2)
          lines.forEach((line, k) => row(sp('   '), sp(k ? '  ' : ''), ...parts(line),
            k === lines.length - 1 && d.turn ? sp(`  #${d.turn}`, { d: 1 }) : sp('')))
        }
        moreRow('decisions', v.decisionCount)
      }
      row(sp(' '))
      row(sp(T.asks, { b: 1 }), sp(v.askCount ? String(v.askCount) : T.none, { c: v.askCount ? 'yellow' : 'green' }))
      for (const a of v.asks.slice(0, shownOf('asks', v.askCount))) {
        row(sp(` ${a.n} `, { c: 'yellow', b: 1 }), ...parts(cutParts(a.summary, cols - 12)),
          sp(` #${a.turn}${a.stale ? T.stale : ''}${a.partial ? T.partial : ''}`, { d: 1 }))
        row(sp('   “', { d: 1 }), ...parts(cutParts(a.quote, cols - 6), { d: 1 }), sp('”', { d: 1 }))
      }
      moreRow('asks', v.askCount)
      if (v.blanketClosed) row(sp(T.blanket(v.blanketClosed), { d: 1 }))
      row(sp(' '))
      row(sp(T.left, { b: 1 }), sp(v.leftCount ? String(v.leftCount) : T.none, { c: v.leftCount ? 'yellow' : 'green' }), sp(T.mine, { d: 1 }))
      for (const x of v.left.slice(0, shownOf('left', v.leftCount)))
        row(sp(` ${x.mark} `, { c: 'yellow' }), ...parts(cutParts(x.summary + (x.note ? ' — ' + x.note : ''), cols - 8)), sp(` #${x.turn}`, { d: 1 }))
      moreRow('left', v.leftCount)
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
      // 맨 아래 펼치기·줄이기 (요구 이력 77): 세 덩어리를 함께 5개씩. 넘치는 덩어리가 없으면 두지 않는다
      const totals: Totals = { decisions: v.decisionCount, asks: v.askCount, left: v.leftCount }
      if (SECTIONS.some(k => totals[k] > SHOWN)) {
        row(sp(' '))
        rows.push({ btns: [{ k: 'expand', label: T.expand }, { k: 'shrink', label: T.shrink }] })
      }
    }
    const body = drawRows(rows, els, k => { void apply($, { op: 'more', k }) })
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
