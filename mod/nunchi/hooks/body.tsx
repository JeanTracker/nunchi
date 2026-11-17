// 눈치 패널 본문 (요구 이력 75): 키를 직접 받는다. 패널 본문을 한 번 클릭한 뒤 ] 펼치기, [ 줄이기,
// Shift+] (또는 }) 모두 펼치기 저장, Shift+[ (또는 {) 모두 접기 저장. 받은 키는 훅 모듈로 보내고(ui.message), 줄은 훅 모듈이 만든다.
import type { ClientModule, JsonValue } from 'claude-code'
import { drawRows, type Row } from './rows'

const Body: ClientModule<{ rows: JsonValue }> = (p, s) => {
  s.onKey(k => {
    if (k.key === '}' || (k.key === ']' && k.shift)) s.post({ op: 'all' })
    else if (k.key === '{' || (k.key === '[' && k.shift)) s.post({ op: 'none' })
    else if (k.key === ']') s.post({ op: 'step', d: 1 })
    else if (k.key === '[') s.post({ op: 'step', d: -1 })
  })
  return drawRows(p.rows as unknown as Row[], s.elements, k => s.post({ op: 'more', k }))
}
export default Body
