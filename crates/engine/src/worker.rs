//! 관제 화면 밖에서 도는 분석기 (control_tui/worker.py와 analyzer.py의 Analyzer를 옮김. 요구 이력 52·53, BUILD_PLAN §4.7).
//!
//! 대기열 `<홈>/queue/<세션>.json`, 자리 잠금 `analyzer-<n>.lock`(flock, 파이썬 fcntl.flock과 같은 잠금),
//! 세션 맡기 `<세션>.claim`. 분석은 스레드 하나가 한 건씩, 고른 세션 먼저, 나머지는 최근 응답부터.
//! 실제로 쓰이는 목표 흐름 분석만 옮겼다(옛 요청 체크 한 번 묻기는 테스트에서만 쓰이던 길이라 옮기지 않음).

use crate::store::{self, read_analysis, write_analysis, write_status};
use crate::transcript::{parse_turns, Turn};
use crate::{clock, flow, glossary, py};
use serde_json::{json, Map, Value};
use std::collections::{HashMap, HashSet};
use std::fs::File;
use std::io::{Read, Write};
use std::os::unix::fs::OpenOptionsExt;
use std::os::unix::io::AsRawFd;
use std::os::unix::process::CommandExt;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::sync::{Arc, Condvar, Mutex};
use std::time::{Duration, Instant};

const QUEUE: &str = "queue";
const PRIORITY_FILE: &str = "priority";
const MAX_WORKERS: i64 = 2;
const POLL: Duration = Duration::from_millis(500);
pub const MAX_ATTEMPTS: u32 = 2;
const TIMEOUT_SECONDS: u64 = 150;
const REPLY_POLL: Duration = Duration::from_millis(250);
const FLOW_STEPS_PER_JOB: usize = 10;

/// 시험에서 줄이는 시간 (CONTROL_TUI_RETRY_SECONDS, CONTROL_TUI_REPLY_WAIT). 기본은 파이썬과 같은 60초·5초
fn env_secs(name: &str, default: f64) -> Duration {
    let s = std::env::var(name).ok().and_then(|v| v.parse::<f64>().ok()).unwrap_or(default);
    Duration::from_secs_f64(s.max(0.0))
}

fn queue_dir(home: &Path) -> PathBuf {
    home.join(QUEUE)
}

// ---------- 대기열 ----------

/// 분석 요청을 남긴다. 이미 있으면 더 최신 응답 시각으로 합치고, force는 한 번이라도 있으면 남긴다
pub fn enqueue(home: &Path, session_id: &str, transcript_path: &str, source_ts: &str, force: bool, by: &str) -> std::io::Result<()> {
    let path = queue_dir(home).join(format!("{session_id}.json"));
    let old = store::read_obj(&path);
    let (mut ts, mut tp) = (source_ts.to_string(), transcript_path.to_string());
    if let Some(Value::String(old_ts)) = old.get("source_ts") {
        if old_ts.as_str() > source_ts {
            ts = old_ts.clone();
            if let Some(v) = old.get("transcript_path").filter(|v| py::truthy(v)) {
                tp = py::str_of(v);
            }
        }
    }
    let queued_at = match old.get("queued_at") {
        Some(v) if py::truthy(v) => v.clone(),
        _ => Value::from(clock::now_us()),
    };
    let control = by == "control" || old.get("by") == Some(&Value::from("control"));
    let item = json!({"session_id": session_id, "transcript_path": tp, "source_ts": ts,
                      "force": force || py::opt_truthy(old.get("force")), "queued_at": queued_at,
                      "by": if control { "control" } else { by }});
    store::write_compact(&path, &item)
}

/// /nunchi로 켜고 끈 표시: 켬 Some(true), 끔 Some(false), 없음 None. on이 없는 옛 표시는 켬
pub fn want_state(home: &Path, session_id: &str) -> Option<bool> {
    let path = home.join("sessions").join(session_id).join("want");
    if !path.exists() {
        return None;
    }
    Some(store::read_obj(&path).get("on") != Some(&Value::Bool(false)))
}

struct Item {
    v: Map<String, Value>,
    path: PathBuf,
}

impl Item {
    fn sid(&self) -> String {
        py::str_of(&self.v["session_id"])
    }
    fn ts(&self) -> String {
        py::str_of(&self.v["source_ts"])
    }
}

/// 기다리는 요청 (오래된 것부터)
fn pending(home: &Path) -> Vec<Item> {
    let mut paths: Vec<PathBuf> = match std::fs::read_dir(queue_dir(home)) {
        Ok(rd) => rd.flatten().map(|e| e.path()).filter(|p| p.to_string_lossy().ends_with(".json")).collect(),
        Err(_) => vec![],
    };
    paths.sort();
    let mut out: Vec<Item> = paths
        .into_iter()
        .map(|p| Item { v: store::read_obj(&p), path: p })
        .filter(|i| py::opt_truthy(i.v.get("session_id")) && py::opt_truthy(i.v.get("source_ts")))
        .collect();
    out.sort_by_key(|i| i.v.get("queued_at").map(py::str_of).unwrap_or_default());
    out
}

/// 요청을 지운다. 그 사이 더 최신 요청으로 바뀌었으면 지우지 않는다
fn drop_item(item: &Item) {
    if store::read_obj(&item.path).get("source_ts") == item.v.get("source_ts") {
        let _ = std::fs::remove_file(&item.path);
    }
}

// ---------- 자리 잠금과 세션 맡기 ----------

fn try_lock(path: &Path) -> Option<File> {
    if let Some(dir) = path.parent() {
        let _ = std::fs::create_dir_all(dir);
    }
    let f = std::fs::OpenOptions::new().read(true).write(true).create(true).mode(0o600).open(path).ok()?;
    // 파이썬 fcntl.flock과 같은 flock(2). 둘이 섞여 돌아도 자리를 같이 센다
    if unsafe { libc::flock(f.as_raw_fd(), libc::LOCK_EX | libc::LOCK_NB) } == 0 { Some(f) } else { None }
}

fn take_slot(home: &Path, workers: i64) -> Option<File> {
    (0..workers.clamp(1, MAX_WORKERS)).find_map(|n| try_lock(&home.join(format!("analyzer-{n}.lock"))))
}

fn free_slot(home: &Path, workers: i64) -> bool {
    take_slot(home, workers).is_some() // 닫히면 풀린다
}

pub fn alive(pid: i64) -> bool {
    if pid <= 0 || pid > i32::MAX as i64 {
        return pid == 0; // 파이썬 os.kill(0, 0)은 성공한다
    }
    unsafe { libc::kill(pid as i32, 0) == 0 || std::io::Error::last_os_error().raw_os_error() == Some(libc::EPERM) }
}

fn read_pid(path: &Path) -> Option<i64> {
    let t = std::fs::read_to_string(path).ok()?;
    if t.is_empty() { Some(0) } else { py::strip(&t).parse().ok() }
}

/// 이 세션을 이 분석기가 맡는다. 다른 분석기가 살아서 맡고 있으면 false. 죽은 분석기의 표시는 걷어 낸다
fn claim(home: &Path, session_id: &str) -> bool {
    let path = queue_dir(home).join(format!("{session_id}.claim"));
    let _ = std::fs::create_dir_all(queue_dir(home));
    let me = std::process::id() as i64;
    for _ in 0..2 {
        match std::fs::OpenOptions::new().write(true).create_new(true).mode(0o600).open(&path) {
            Ok(mut f) => {
                let _ = f.write_all(me.to_string().as_bytes());
                return true;
            }
            Err(e) if e.kind() == std::io::ErrorKind::AlreadyExists => {
                let pid = read_pid(&path).unwrap_or(0);
                if pid == me {
                    return true;
                }
                if pid != 0 && alive(pid) {
                    return false;
                }
                let _ = std::fs::remove_file(&path);
            }
            Err(_) => return false,
        }
    }
    false
}

fn release(home: &Path, session_id: &str) {
    let path = queue_dir(home).join(format!("{session_id}.claim"));
    if std::fs::read_to_string(&path).ok().as_deref() == Some(std::process::id().to_string().as_str()) {
        let _ = std::fs::remove_file(&path);
    }
}

/// 다른 살아 있는 분석기가 맡고 있지 않은 요청인지
fn claim_free(home: &Path, session_id: &str) -> bool {
    match read_pid(&queue_dir(home).join(format!("{session_id}.claim"))) {
        None => true,
        Some(pid) => !(pid != 0 && pid != std::process::id() as i64 && alive(pid)),
    }
}

// ---------- 깨우기 ----------

/// 새 세션으로 떼어 낸다 (파이썬 start_new_session=True와 같은 setsid. 프로세스 묶음만 새로 만드는 것과 다르다)
fn detach(cmd: &mut Command) {
    unsafe {
        cmd.pre_exec(|| {
            libc::setsid();
            Ok(())
        });
    }
}

/// 빈 자리가 있으면 분석기를 하나 띄운다. CONTROL_TUI_WORKER=0이면 띄우지 않는다(시험)
pub fn wake(home: &Path, workers: i64) -> bool {
    if std::env::var("CONTROL_TUI_WORKER").as_deref() == Ok("0") || !free_slot(home, workers) {
        return false;
    }
    let Ok(exe) = std::env::current_exe() else { return false };
    let root = exe.parent().and_then(Path::parent).map(Path::to_path_buf).unwrap_or_else(|| PathBuf::from("/"));
    let mut cmd = Command::new(&exe);
    cmd.args(["worker", "--home"]).arg(home).current_dir(root).env("CONTROL_TUI_HOME", home).env_remove("CONTROL_TUI_ANALYZER");
    cmd.stdin(Stdio::null()).stdout(Stdio::null()).stderr(Stdio::null());
    detach(&mut cmd);
    cmd.spawn().is_ok()
}

// ---------- claude -p ----------

/// claude -p로 한 번 묻는다. 분석기 자신은 기록되지 않게 표시하고, 저장과 도구는 모두 끈다
fn run_claude(prompt: &str, model: &str, shared: &Shared) -> Result<String, String> {
    let mut cmd = Command::new("claude");
    cmd.args(["-p", "--output-format", "json", "--no-session-persistence", "--disable-slash-commands", "--tools", ""]);
    if !model.is_empty() {
        cmd.args(["--model", model]);
    }
    cmd.args(["--", prompt]).env("CONTROL_TUI_ANALYZER", "1");
    cmd.stdin(Stdio::null()).stdout(Stdio::piped()).stderr(Stdio::piped());
    detach(&mut cmd);
    let mut child = cmd.spawn().map_err(|e| format!("claude 실행 실패: {}", io_kind(&e)))?;
    shared.set_child(Some(child.id()));
    let mut out = child.stdout.take().unwrap();
    let mut err = child.stderr.take().unwrap();
    let reader = std::thread::spawn(move || {
        let mut s = Vec::new();
        let _ = out.read_to_end(&mut s);
        s
    });
    let drain_err = std::thread::spawn(move || {
        let mut s = Vec::new();
        let _ = err.read_to_end(&mut s);
    });
    let deadline = Instant::now() + Duration::from_secs(TIMEOUT_SECONDS);
    let status = loop {
        match child.try_wait() {
            Ok(Some(st)) => break Some(st),
            Ok(None) if Instant::now() < deadline => std::thread::sleep(Duration::from_millis(50)),
            _ => {
                let _ = child.kill();
                let _ = child.wait();
                break None;
            }
        }
    };
    shared.set_child(None);
    let stdout = reader.join().unwrap_or_default();
    let _ = drain_err.join();
    let Some(status) = status else { return Err(format!("시간 초과 ({TIMEOUT_SECONDS}초)")) };
    if !status.success() {
        let code = status.code().map(i64::from).unwrap_or_else(|| {
            use std::os::unix::process::ExitStatusExt;
            -(status.signal().unwrap_or(0) as i64)
        });
        return Err(format!("claude 종료 코드 {code}"));
    }
    let v: Value = serde_json::from_slice(&stdout).map_err(|_| "claude 출력을 읽지 못했습니다".to_string())?;
    match v.as_object() {
        Some(o) => Ok(o.get("result").map(py::str_of).unwrap_or_default()),
        None => Err("claude 출력을 읽지 못했습니다".into()),
    }
}

fn io_kind(e: &std::io::Error) -> &'static str {
    match e.kind() {
        std::io::ErrorKind::NotFound => "FileNotFoundError",
        std::io::ErrorKind::PermissionDenied => "PermissionError",
        _ => "OSError",
    }
}

// ---------- 분석기 (스레드 하나가 한 건씩) ----------

#[derive(Clone)]
struct Job {
    sid: String,
    ts: String,
    dir: PathBuf,
    transcript: PathBuf,
}

#[derive(Default)]
struct State {
    jobs: Vec<Job>, // 세션마다 하나, 넣은 차례 (같은 세션은 자리를 지키고 바꾼다)
    running: Option<Job>,
    since: String,
    failed: HashMap<(String, String), (u32, Instant)>,
    priority: String,
    stopped: bool,
    child: Option<u32>,
}

struct Shared {
    m: Mutex<State>,
    cv: Condvar,
    model: String,
    reply_wait: Duration,
    retry: Duration,
}

impl Shared {
    fn set_child(&self, pid: Option<u32>) {
        let mut st = self.m.lock().unwrap();
        st.child = pid;
        if st.stopped {
            if let Some(p) = pid {
                unsafe { libc::kill(p as i32, libc::SIGKILL) };
            }
        }
    }
    fn stopped(&self) -> bool {
        self.m.lock().unwrap().stopped
    }
}

fn flow_pending(a: &Value) -> bool {
    let f = py::get(a, "flow").cloned().unwrap_or(Value::Null);
    let until = py::int_or(py::get(&f, "until"), 0).unwrap_or(0);
    let last = py::int_or(py::get(a, "last_turn"), 0).unwrap_or(0);
    until < last
}

fn order(st: &State) -> Vec<String> {
    let mut ids: Vec<&Job> = st.jobs.iter().collect();
    ids.sort_by(|a, b| b.ts.cmp(&a.ts)); // 안정 정렬: 같은 시각은 넣은 차례
    let mut out: Vec<String> = ids.into_iter().map(|j| j.sid.clone()).collect();
    if let Some(i) = out.iter().position(|s| *s == st.priority) {
        let p = out.remove(i);
        out.insert(0, p);
    }
    out
}

pub struct Analyzer {
    shared: Arc<Shared>,
    thread: Option<std::thread::JoinHandle<()>>,
}

impl Analyzer {
    fn new(model: String) -> Analyzer {
        let shared = Arc::new(Shared {
            m: Mutex::new(State::default()),
            cv: Condvar::new(),
            model,
            reply_wait: env_secs("CONTROL_TUI_REPLY_WAIT", 5.0),
            retry: env_secs("CONTROL_TUI_RETRY_SECONDS", 60.0),
        });
        let s2 = shared.clone();
        let thread = std::thread::Builder::new().name("analyzer".into()).spawn(move || run_loop(&s2)).ok();
        Analyzer { shared, thread }
    }

    /// 응답 시각에 대한 분석이 없으면 예약한다. 예약했으면 true
    fn request(&self, sid: &str, dir: &Path, transcript: &str, ts: &str, force: bool) -> bool {
        if transcript.is_empty() || ts.is_empty() {
            return false;
        }
        let key = (sid.to_string(), ts.to_string());
        {
            let mut st = self.shared.m.lock().unwrap();
            if st.stopped {
                return false;
            }
            if let Some(existing) = read_analysis(dir) {
                if py::get(&existing, "source_ts") == Some(&Value::from(ts)) && !flow_pending(&existing) {
                    return false;
                }
            }
            if st.running.as_ref().map(|j| j.sid == sid && j.ts == ts).unwrap_or(false) {
                return false;
            }
            if st.jobs.iter().any(|j| j.sid == sid && j.ts == ts) {
                return false;
            }
            if force {
                st.failed.remove(&key);
            } else if let Some((attempts, when)) = st.failed.get(&key) {
                if *attempts >= MAX_ATTEMPTS || when.elapsed() < self.shared.retry {
                    return false;
                }
            }
            let job = Job { sid: sid.into(), ts: ts.into(), dir: dir.into(), transcript: transcript.into() };
            match st.jobs.iter_mut().find(|j| j.sid == sid) {
                Some(j) => *j = job,
                None => st.jobs.push(job),
            }
            self.shared.cv.notify_all();
        }
        write_status(dir, "queued", 0, &[]);
        true
    }

    fn prioritize(&self, sid: &str) {
        self.shared.m.lock().unwrap().priority = sid.to_string();
    }

    fn attempts(&self, sid: &str, ts: &str) -> u32 {
        self.shared.m.lock().unwrap().failed.get(&(sid.to_string(), ts.to_string())).map(|x| x.0).unwrap_or(0)
    }

    fn busy_with(&self, sid: &str) -> bool {
        let st = self.shared.m.lock().unwrap();
        st.running.is_some() || st.jobs.iter().any(|j| j.sid == sid)
    }

    fn idle(&self) -> bool {
        let st = self.shared.m.lock().unwrap();
        st.running.is_none() && st.jobs.is_empty()
    }

    /// 기다리던 분석은 버리고, 도는 claude -p는 멈춘다
    fn shutdown(&mut self) {
        {
            let mut st = self.shared.m.lock().unwrap();
            st.stopped = true;
            st.jobs.clear();
            if let Some(p) = st.child {
                unsafe { libc::kill(p as i32, libc::SIGKILL) };
            }
            self.shared.cv.notify_all();
        }
        if let Some(t) = self.thread.take() {
            let _ = t.join();
        }
    }
}

fn run_loop(sh: &Shared) {
    loop {
        let job = {
            let mut st = sh.m.lock().unwrap();
            while st.jobs.is_empty() && !st.stopped {
                st = sh.cv.wait(st).unwrap();
            }
            if st.stopped {
                return;
            }
            let sid = order(&st)[0].clone();
            let i = st.jobs.iter().position(|j| j.sid == sid).unwrap();
            let job = st.jobs.remove(i);
            st.running = Some(job.clone());
            st.since = clock::now_us();
            job
        };
        run_job(sh, &job);
        let mut st = sh.m.lock().unwrap();
        st.running = None;
        sh.cv.notify_all();
    }
}

/// 응답 시각까지의 턴. 마지막 턴에 글이 아직 없으면 기록에 적힐 때까지 잠깐 기다린다 (Stop 훅이 글보다 먼저 온다)
fn read_turns(sh: &Shared, transcript: &Path, ts: &str) -> Result<Vec<Turn>, String> {
    let deadline = Instant::now() + sh.reply_wait;
    loop {
        let turns = if transcript.exists() { parse_turns(transcript, ts)? } else { vec![] };
        if turns.last().map(|t| !py::strip(&t.final_response).is_empty()).unwrap_or(false) {
            return Ok(turns);
        }
        if sh.stopped() || Instant::now() >= deadline {
            return Ok(turns);
        }
        std::thread::sleep(REPLY_POLL);
    }
}

fn run_job(sh: &Shared, job: &Job) {
    let key = (job.sid.clone(), job.ts.clone());
    match analyze(sh, job) {
        Ok(()) => {
            sh.m.lock().unwrap().failed.remove(&key);
        }
        Err(e) => {
            if sh.stopped() {
                return;
            }
            let msg = py::take(&e, 120);
            let attempts = {
                let mut st = sh.m.lock().unwrap();
                let a = st.failed.get(&key).map(|x| x.0).unwrap_or(0) + 1;
                st.failed.insert(key, (a, Instant::now()));
                a
            };
            write_status(&job.dir, "failed", 0, &[("error", Value::from(msg)), ("source_ts", Value::from(job.ts.clone())), ("attempts", Value::from(attempts))]);
        }
    }
}

fn analyze(sh: &Shared, job: &Job) -> Result<(), String> {
    let turns = read_turns(sh, &job.transcript, &job.ts)?;
    let Some(last) = turns.last() else { return Err("턴 기록이 없어 분석하지 않았습니다".into()) };
    let old = read_analysis(&job.dir);
    let same = old.as_ref().map(|o| py::truthy(o) && py::get(o, "source_ts") == Some(&Value::from(job.ts.as_str()))).unwrap_or(false);
    if !same {
        let get_or = |k: &str| old.as_ref().and_then(|o| py::get(o, k)).cloned().unwrap_or_else(|| Value::from(""));
        let mut base = Map::new();
        base.insert("first_goal".into(), get_or("first_goal"));
        base.insert("current_goal".into(), get_or("current_goal"));
        base.insert("turns".into(), json!([]));
        base.insert("last_response_summary".into(), Value::from(""));
        base.insert("ledger".into(), json!([]));
        base.insert("forgotten".into(), json!([]));
        if let Some(f) = old.as_ref().and_then(|o| py::get(o, "flow")).filter(|f| py::truthy(f)) {
            base.insert("flow".into(), f.clone());
        }
        write_analysis(&job.dir, base, &job.ts, json!({}), last.index).map_err(|e| e.to_string())?;
    }
    let since = sh.m.lock().unwrap().since.clone();
    write_status(&job.dir, "running", last.index, &[("since", Value::from(since)), ("source_ts", Value::from(job.ts.as_str()))]);
    let r = advance_flow(sh, &job.dir, &turns);
    write_status(&job.dir, "idle", 0, &[]);
    r
}

/// 목표 흐름을 새 턴만큼 이어 적는다. 한 턴마다 저장해 화면이 따라오게 한다
fn advance_flow(sh: &Shared, dir: &Path, turns: &[Turn]) -> Result<(), String> {
    let mut data = read_analysis(dir).unwrap_or_else(|| json!({}));
    let mut f = flow::migrate(py::get(&data, "flow"), turns).unwrap_or(Value::Null);
    if !flow::valid_for(&f, turns) {
        f = flow::empty();
    }
    let rebuilt = !py::opt_truthy(py::get(&f, "steps"));
    let before = flow::shifts_count(&f);
    let left_before: HashSet<String> = flow::remaining(&f).iter().map(|r| py::str_of(&r["id"])).collect();
    let mut kept: Option<Value> = None;
    if flow::grown(&f, turns) {
        kept = Some(f.clone());
        f = flow::rewind(&f);
    }
    let until = py::int_or(py::get(&f, "until"), 0).unwrap_or(0);
    let todo: Vec<&Turn> = turns.iter().filter(|t| t.index > until).take(FLOW_STEPS_PER_JOB).collect();
    let since = sh.m.lock().unwrap().since.clone();
    for t in todo {
        if sh.stopped() {
            return Ok(());
        }
        write_status(dir, "running", t.index, &[("since", Value::from(since.as_str()))]);
        let mut runner = |p: &str| run_claude(p, &sh.model, sh);
        f = flow::advance(&f, turns, t, &mut runner, 2)?;
        if let Some(k) = kept.take() {
            let fell_back = py::list(py::get(&f, "steps")).last().map(|s| py::opt_truthy(py::get(s, "fallback"))).unwrap_or(false);
            if py::eq_int(py::get(&k, "until"), t.index) && fell_back {
                f = k; // 다시 적기가 대체 단계로 끝났으면 앞서 적은 것을 둔다
            }
        }
        if let Some(d) = read_analysis(dir) {
            data = d;
        }
        data["flow"] = f.clone();
        let cg_text = py::get(&f, "current_goal").and_then(|c| py::get(c, "text")).cloned();
        if cg_text.as_ref().map(py::truthy).unwrap_or(false) {
            let prev_fg = py::get(&data, "first_goal").cloned().unwrap_or_else(|| Value::from(""));
            data["first_goal"] = py::get(&f, "first_goal").and_then(|g| py::get(g, "text")).cloned().unwrap_or(prev_fg);
            data["current_goal"] = cg_text.unwrap();
        }
        if !rebuilt {
            let left = flow::remaining(&f);
            let new_missed: Vec<Value> = left.iter().filter(|r| !left_before.contains(&py::str_of(&r["id"]))).map(|r| r["summary"].clone()).collect();
            let prev_ts = py::get(&data, "source_ts").cloned().unwrap_or_else(|| Value::from(""));
            data["changes"] = json!({"missed_before": left_before.len(), "missed_after": left.len(), "new_missed": new_missed,
                                     "goal_changed": flow::shifts_count(&f) > before, "prev_source_ts": prev_ts});
            data["analyzed_at"] = Value::from(clock::now_us());
        }
        store::write_json(&dir.join("analysis.json"), &data).map_err(|e| e.to_string())?;
    }
    Ok(())
}

// ---------- 분석기 본체 ----------

fn events_field(dir: &Path, key: &str) -> Option<String> {
    let text = std::fs::read_to_string(dir.join("events.jsonl")).ok()?;
    let mut out = String::new();
    for line in text.lines() {
        if let Ok(v) = serde_json::from_str::<Value>(line) {
            if let Some(x) = py::get(&v, key).filter(|x| py::truthy(x)) {
                out = py::str_of(x);
            }
        }
    }
    Some(out)
}

/// mod가 읽을 번호 풀이. 보조 정보라 실패해도 넘어간다
fn write_glossary(dir: &Path) {
    let Some(tp) = events_field(dir, "transcript_path") else { return };
    let cwd = events_field(dir, "cwd").unwrap_or_default();
    let turns = if tp.is_empty() { vec![] } else {
        match parse_turns(Path::new(&tp), "") {
            Ok(t) => t,
            Err(_) => return,
        }
    };
    let last = turns.last();
    let body = last.map(|t| if t.final_response.is_empty() { t.response.clone() } else { t.final_response.clone() }).unwrap_or_default();
    let mut got = glossary::explain(&body, &cwd);
    got["turn"] = Value::from(last.map(|t| t.index).unwrap_or(0));
    let _ = store::write_json(&dir.join("glossary.json"), &got);
}

/// 대기열이 빌 때까지 분석한다. 처리를 끝낸 요청 수. 자리가 없으면 바로 0
pub fn drain(home: &Path) -> usize {
    let st = store::load_settings(home);
    // slot이 살아 있는 동안 자리 잠금을 쥔다 (None으로 바꾸면 풀린다)
    #[allow(unused_assignments)]
    let Some(mut slot) = take_slot(home, st.analyze_workers).map(Some) else { return 0 };
    let mut an = Analyzer::new(st.analyze_model.clone());
    let mut mine: HashSet<String> = HashSet::new();
    let mut done = 0;
    loop {
        let prio = std::fs::read_to_string(home.join(QUEUE).join(PRIORITY_FILE)).map(|t| py::strip(&t).to_string()).unwrap_or_default();
        an.prioritize(&prio);
        let mut items = pending(home);
        items.sort_by_key(|i| i.sid() != prio);
        for item in &items {
            let sid = item.sid();
            if !mine.contains(&sid) && item.v.get("by") != Some(&Value::from("control")) && want_state(home, &sid) == Some(false) {
                drop_item(item); // /nunchi off로 끈 세션: 훅이 넣은 요청은 버린다
                continue;
            }
            if !mine.contains(&sid) {
                if !claim(home, &sid) {
                    continue;
                }
                mine.insert(sid.clone());
            }
            let sdir = home.join("sessions").join(&sid);
            let ts = item.ts();
            let existing = read_analysis(&sdir);
            if let Some(e) = &existing {
                if py::truthy(e) && py::get(e, "source_ts") == item.v.get("source_ts") && !flow_pending(e) && !an.busy_with(&sid) {
                    drop_item(item);
                    release(home, &sid);
                    mine.remove(&sid);
                    write_glossary(&sdir);
                    done += 1;
                    continue;
                }
            }
            let force = py::opt_truthy(item.v.get("force"));
            if an.attempts(&sid, &ts) >= MAX_ATTEMPTS && !force {
                drop_item(item); // 정해진 횟수를 다 썼다. 상태 파일에 실패가 남아 있다
                release(home, &sid);
                mine.remove(&sid);
                continue;
            }
            let tp = item.v.get("transcript_path").map(py::str_of).unwrap_or_default();
            if force {
                an.request(&sid, &sdir, &tp, &ts, true);
                let mut v2 = item.v.clone();
                v2.insert("force".into(), Value::Bool(false));
                if store::read_obj(&item.path).get("source_ts") == item.v.get("source_ts") {
                    let _ = store::write_compact(&item.path, &Value::Object(v2));
                }
            } else {
                an.request(&sid, &sdir, &tp, &ts, false);
            }
        }
        if mine.is_empty() && an.idle() {
            // 끝내기 전에 자리를 내놓고 한 번 더 본다: 그 사이 들어온 요청을 놓치지 않는다
            slot = None;
            if !pending(home).iter().any(|i| claim_free(home, &i.sid())) {
                break;
            }
            slot = take_slot(home, st.analyze_workers);
            if slot.is_none() {
                break; // 다른 분석기가 이어 받았다
            }
        }
        std::thread::sleep(POLL);
    }
    an.shutdown();
    for sid in mine {
        release(home, &sid);
    }
    drop(slot);
    done
}
