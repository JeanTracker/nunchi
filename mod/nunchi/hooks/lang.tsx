// 눈치 패널의 언어 (요구 이력 76, SCREEN §11 언어, BUILD_PLAN §4.14)
// 화면 문구는 한국어·영어 두 벌. 분석 문장의 언어는 세션마다 엔진이 정하고, 여기서는 판정과 표시 문구만 다룬다.

export type Ui = 'ko' | 'en'

const KO = /^(한국어|한국말|한글|korean|kor|ko([-_].*)?)$/
const EN = /^(english|영어|en([-_].*)?)$/

/** 언어 이름을 ko · en · (소문자 원래 값, 40자까지)로 맞춘다. 빈 값이면 '' */
export function norm(raw: unknown): string {
  const s = String(raw ?? '').trim().toLowerCase()
  if (!s) return ''
  if (KO.test(s)) return 'ko'
  if (EN.test(s)) return 'en'
  return s.slice(0, 40)
}

/** 터미널 언어(LC_ALL·LANG)는 ko가 아니면 en (C, ja_JP.UTF-8 같은 값을 분석기에 넘기지 않는다) */
function terminal(raw: unknown): string {
  const s = String(raw ?? '').trim()
  if (!s) return ''
  return norm(s.split('.')[0]) === 'ko' ? 'ko' : 'en'
}

export type Picked = { ui: Ui; analysis: string; from: 'saved' | 'claude' | 'terminal' | 'default' }

/** 차례: mod.json에 고른 값 → Claude Code language → LC_ALL → LANG → en */
export function pick(o: { saved?: unknown; setting?: unknown; lcAll?: unknown; lang?: unknown }): Picked {
  const saved = norm(o.saved)
  const done = (analysis: string, from: Picked['from']): Picked => ({ ui: analysis === 'ko' ? 'ko' : 'en', analysis, from })
  if (saved === 'ko' || saved === 'en') return done(saved, 'saved')
  const setting = norm(o.setting)
  if (setting) return done(setting, 'claude')
  const t = terminal(o.lcAll) || terminal(o.lang)
  if (t) return done(t, 'terminal')
  return done('en', 'default')
}

/** 분석 언어 이름 (질문 창·언어 줄에 보인다) */
export function langName(code: string): string {
  return code === 'ko' ? '한국어' : code === 'en' ? 'English' : code
}

/** 분석기 --settings에 넘길 이름 */
export function settingsName(code: string): string {
  return code === 'ko' ? '한국어' : code === 'en' ? 'English' : code
}

const KO_T = {
  title: '눈치',
  command: '눈치 켜기: 이 세션을 분석하고 패널을 연다 · language로 언어 바꾸기',
  queued: '분석 대기', running: '분석 중',
  failed: '분석 실패 · ',
  onWaiting: '눈치 켜짐 · 다음 응답이 끝나면 분석합니다',
  offIdle: '눈치 꺼짐 · /nunchi로 켜면 이 세션을 분석합니다',
  asOf: (n: number) => ` · #${n} 기준`,
  behind: (n: number) => ` · 응답 ${n}개 밀림`,
  rebuilding: (k: number, n: number) => `흐름 처음부터 만드는 중 #${k}/#${n}`,
  catching: (k: number, n: number) => `밀린 턴 반영 중 #${k}/#${n}`,
  autoOff: '자동 분석 꺼짐 · /nunchi로 켜기',
  langLine: (name: string) => `분석: ${name} · /nunchi language로 다시 분석`,
  goal: '목표', since: (n: number) => `  #${n}부터`,
  flow: (n: number) => ` 흐름  #1–#${n}`, recent: ' 방금',
  decisions: '의사결정 ',
  asks: '에이전트 질문 ', none: '없음',
  stale: '부터 답 없음', partial: ' · 일부 답함',
  blanket: (n: number) => `   통째 승인으로 닫은 것 ${n}`,
  left: '남은 요청 ', mine: ' 내 요청 중',
  deferred: '못 했거나 미룸', inProgress: '진행 중',
  terms: '번호 풀이', termsNote: '  이번 응답 · 문서 원문', noDoc: '문서에 없음',
  more: (n: number) => `… ${n}개 더`, collapse: '접기',
  control: '관제로', controlOr: '  또는 ⌘숫자',
  controlOff: '관제가 꺼져 있습니다. 다른 패널에서 nunchi로 켜세요.',
  controlMissing: '관제 패널을 찾지 못했습니다. ⌘숫자로 옮겨 가세요.',
  narrow: ' 창이 좁아 패널 대신 입력창 위 한 줄로 보입니다.',
  opened: '눈치 패널을 열었습니다.',
  turnedOn: '눈치를 켰습니다. 다음 응답이 끝나면 이 세션을 분석합니다.',
  notice: '눈치: 한국어로 표시합니다 · /nunchi language로 변경',
  band: '눈치 ', bandGoal: '목표: ', bandAsks: ' · 질문 ', bandLeft: ' · 요청 ', bandAsOf: (n: number) => ` · #${n} 기준`, bandOff: ' · 분석 꺼짐',
  langNow: (name: string, from: string) => `지금 눈치 언어: ${name}${from}`,
  fromClaude: ' (Claude Code 설정)',
  langSet: (name: string) => `눈치 언어: ${name}. 패널 문구는 바로 바뀌고, 새 세션부터 ${name}로 분석합니다.`,
  langFollow: (name: string) => `눈치 언어: Claude Code 설정을 따릅니다(지금 ${name}).`,
  langKept: (name: string) => ` 이 세션은 ${name} 분석을 그대로 둡니다. /nunchi language로 언제든 다시 분석할 수 있습니다.`,
  langRebuild: (name: string) => ` 이 세션을 ${name}로 처음부터 다시 분석합니다.`,
  rebuildFailed: ' 다시 분석을 시작하지 못했습니다. 세션을 다시 시작한 뒤 해 보세요.',
  unchanged: '눈치 언어를 바꾸지 않았습니다.',
}
type T = typeof KO_T

const EN_T: T = {
  title: 'Nunchi',
  command: 'Turn on Nunchi: analyze this session and open the panel · language to switch languages',
  queued: 'Queued', running: 'Analyzing',
  failed: 'Analysis failed · ',
  onWaiting: 'Nunchi on · analyzes after the next answer',
  offIdle: 'Nunchi off · /nunchi to analyze this session',
  asOf: (n: number) => ` · as of #${n}`,
  behind: (n: number) => ` · ${n} answer${n === 1 ? '' : 's'} behind`,
  rebuilding: (k: number, n: number) => `Rebuilding from the start #${k}/#${n}`,
  catching: (k: number, n: number) => `Catching up #${k}/#${n}`,
  autoOff: 'Auto analysis off · /nunchi to turn on',
  langLine: (name: string) => `analysis: ${name} · /nunchi language to rebuild`,
  goal: 'Goal', since: (n: number) => `  since #${n}`,
  flow: (n: number) => ` Flow  #1–#${n}`, recent: ' Just now',
  decisions: 'Decisions ',
  asks: 'Agent questions ', none: 'none',
  stale: ' · no answer since', partial: ' · partly answered',
  blanket: (n: number) => `   closed by a blanket yes ${n}`,
  left: 'Open requests ', mine: ' of mine',
  deferred: 'deferred', inProgress: 'in progress',
  terms: 'Numbers', termsNote: '  this answer · source text', noDoc: 'not in the docs',
  more: (n: number) => `… ${n} more`, collapse: 'Collapse',
  control: 'To control', controlOr: '  or ⌘number',
  controlOff: 'The control screen is off. Start it with nunchi in another pane.',
  controlMissing: 'Could not find the control pane. Switch with ⌘number.',
  narrow: ' The window is narrow, so it shows as one line above the input box.',
  opened: 'Opened the Nunchi panel.',
  turnedOn: 'Turned on Nunchi. It analyzes this session after the next answer.',
  notice: 'Nunchi: showing English · change with /nunchi language',
  band: 'Nunchi ', bandGoal: 'Goal: ', bandAsks: ' · asks ', bandLeft: ' · open ', bandAsOf: (n: number) => ` · as of #${n}`, bandOff: ' · analysis off',
  langNow: (name: string, from: string) => `Nunchi language now: ${name}${from}`,
  fromClaude: ' (Claude Code setting)',
  langSet: (name: string) => `Nunchi language: ${name}. The panel switches now; new sessions are analyzed in ${name}.`,
  langFollow: (name: string) => `Nunchi language: follows the Claude Code setting (now ${name}).`,
  langKept: (name: string) => ` This session keeps its ${name} analysis. Run /nunchi language any time to rebuild it.`,
  langRebuild: (name: string) => ` Rebuilding this session in ${name} from the start.`,
  rebuildFailed: ' Could not start the rebuild. Restart the session and try again.',
  unchanged: 'Nunchi language unchanged.',
}

export const TEXT: Record<Ui, T> = { ko: KO_T, en: EN_T }

// 질문 창 (요구 이력 76·79). 설명과 '설정 따르기'는 화면 언어로(한국어 화면이 아니면 영어), 언어 이름은 그 언어로
export const ASK_LANG = (ui: Ui, now: string, from: string) => ui === 'ko' ? `눈치 언어를 고르세요. 지금: ${now}${from}` : `Choose the Nunchi language. Now: ${now}${from}`
export const OPT_KO = '한국어'
export const OPT_EN = 'English'
export const OPT_FOLLOW = (ui: Ui) => ui === 'ko' ? 'Claude Code 설정 따르기' : 'Follow the Claude Code setting'
export const ASK_REBUILD = (ui: Ui, was: string, to: string, turns: number) => ui === 'ko'
  ? `이 세션은 ${was}로 분석돼 있습니다. ${to}로 다시 분석할까요? (응답 ${turns}개 · 분석 호출 ${turns}회 이상)`
  : `This session is analyzed in ${was}. Rebuild it in ${to}? (${turns} answers · at least ${turns} analysis calls)`
export const OPT_KEEP = (ui: Ui, to: string) => ui === 'ko' ? `그대로 두기 (새 세션부터 ${to})` : `Keep it (new sessions in ${to})`
export const OPT_REBUILD = (ui: Ui) => ui === 'ko' ? '지금 다시 분석' : 'Rebuild now'

/** 엔진이 남긴 실패 이유(코드)를 화면 문구로. 모르는 글(옛 결과)은 그대로 */
export function failText(code: string, ui: Ui): string {
  const ko = ui === 'ko'
  const m = /^exit:(-?\d+)$/.exec(code)
  if (m) return ko ? `claude 종료 코드 ${m[1]}` : `claude exited with ${m[1]}`
  const t = /^timeout(?::(\d+))?$/.exec(code)
  if (t) return ko ? `시간 초과${t[1] ? ` (${t[1]}초)` : ''}` : `timed out${t[1] ? ` (${t[1]}s)` : ''}`
  switch (code) {
    case 'spawn': return ko ? 'claude 실행 실패' : 'could not start claude'
    case 'output': return ko ? 'claude 출력을 읽지 못했습니다' : 'could not read claude output'
    case 'no-turns': return ko ? '턴 기록이 없어 분석하지 못했습니다' : 'no turns recorded to analyze'
    case 'not-utf8': return ko ? '대화 기록이 UTF-8이 아닙니다' : 'the transcript is not UTF-8'
    case 'io': return ko ? '파일을 읽거나 쓰지 못했습니다' : 'could not read or write a file'
  }
  return code
}

/** 칸 수 (한글 등 넓은 글자 2칸) */
export function columns(text: string): number {
  let n = 0
  for (const ch of text) n += /[ᄀ-ᅟ⺀-꓏가-힣豈-﫿︰-﹏＀-｠￠-￦]/.test(ch) ? 2 : 1
  return n
}
