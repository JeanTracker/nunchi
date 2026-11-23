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
use std::os::unix::fs::{DirBuilderExt, OpenOptionsExt};
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

/// 대기 요청 파일 (요구 이력 93): 새 엔진은 `<세션>.job`에 적는다. 0.5.0까지의 분석기는 `.json`만 읽어
/// 새 엔진이 넣은 작업을 가져가 옛 형식으로 쓰지 못한다. 새 분석기는 둘 다 읽는다(옛 훅이 넣은 요청도 맡음)
const JOB_EXT: &str = ".job";

fn is_job(p: &Path) -> bool {
    let n = p.to_string_lossy();
    n.ends_with(JOB_EXT) || n.ends_with(".json")
}

// ---------- 대기열 ----------

/// 분석 요청을 남긴다. 이미 있으면 더 최신 응답 시각으로 합치고, force는 한 번이라도 있으면 남긴다
pub fn enqueue(home: &Path, session_id: &str, transcript_path: &str, source_ts: &str, force: bool, by: &str) -> std::io::Result<()> {
    let path = queue_dir(home).join(format!("{session_id}{JOB_EXT}"));
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
        Ok(rd) => rd.flatten().map(|e| e.path()).filter(|p| is_job(p)).collect(),
        Err(_) => vec![],
    };
    paths.sort();
    let mut out: Vec<Item> = paths
        .into_iter()
        .map(|p| Item { v: store::read_obj(&p), path: p })
        .filter(|i| py::opt_truthy(i.v.get("session_id")) && py::opt_truthy(i.v.get("source_ts")))
        .collect();
    out.sort_by_key(|i| i.v.get("queued_at").map(py::str_of).unwrap_or_default());
    merge_same_session(out)
}

/// 한 세션의 요청이 `.json`(옛 훅)과 `.job`(새 엔진) 두 파일에 있으면 하나로 합친다 (요구 이력 93).
/// 한 파일일 때 enqueue가 지키던 규칙과 같게: 더 최신 응답 시각(과 그 기록 경로)을 남기고, force와 관제 요청은
/// 하나라도 있으면 남기고, 먼저 넣은 시각을 쓴다. 옛 시각의 요청을 나중에 맡으면 흐름이 맞지 않아 처음부터 다시
/// 시작하므로(실제로 46턴을 다시 분석했다) 진 쪽 파일은 지운다
fn merge_same_session(items: Vec<Item>) -> Vec<Item> {
    let mut out: Vec<Item> = Vec::new();
    for it in items {
        let Some(k) = out.iter().position(|o| o.sid() == it.sid()) else {
            out.push(it);
            continue;
        };
        let (mut win, lose) = if it.ts() > out[k].ts() { (it, out.remove(k)) } else { let w = out.remove(k); (w, it) };
        let any = |key: &str| py::opt_truthy(win.v.get(key)) || py::opt_truthy(lose.v.get(key));
        let force = any("force");
        let control = win.v.get("by") == Some(&Value::from("control")) || lose.v.get("by") == Some(&Value::from("control"));
        let first = [win.v.get("queued_at"), lose.v.get("queued_at")].into_iter().flatten().map(py::str_of).filter(|q| !q.is_empty()).min();
        win.v.insert("force".into(), Value::Bool(force));
        if control {
            win.v.insert("by".into(), Value::from("control"));
        }
        if let Some(q) = first {
            win.v.insert("queued_at".into(), Value::from(q));
        }
        // 합친 요청은 늘 `.job`에 둔다: 옛 분석기가 읽는 `.json`에 남기면 그쪽이 가져가 옛 형식으로 쓸 수 있다
        let job = win.path.with_file_name(format!("{}{JOB_EXT}", win.sid()));
        let _ = store::write_compact(&job, &Value::Object(win.v.clone()));
        for old in [&win.path, &lose.path] {
            if *old != job && store::read_obj(old).get("source_ts").map(py::str_of) <= Some(win.ts()) {
                let _ = std::fs::remove_file(old);
            }
        }
        win.path = job;
        out.insert(k.min(out.len()), win);
    }
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
/// 실패 이유는 코드로 남긴다: mod가 화면 언어로 옮긴다 (요구 이력 76). spawn·timeout:<초>·exit:<코드>·output·no-turns·not-utf8·io
fn run_claude(prompt: &str, model: &str, lang: &str, shared: &Shared) -> Result<String, String> {
    let mut cmd = Command::new("claude");
    cmd.args(["-p", "--output-format", "json", "--no-session-persistence", "--disable-slash-commands", "--tools", ""]);
    if !model.is_empty() {
        cmd.args(["--model", model]);
    }
    // 세션의 분석 언어로 Claude Code 언어 설정을 덮어쓴다: 덮어쓰지 않으면 사용자의 language를 물려받는다 (SCREEN §8 2026-11-17 언어)
    cmd.arg("--settings").arg(json!({"language": flow::settings_language(lang)}).to_string());
    cmd.args(["--", prompt]).env("CONTROL_TUI_ANALYZER", "1");
    let stdout = run_child(cmd, shared)?;
    let v: Value = serde_json::from_slice(&stdout).map_err(|_| "output".to_string())?;
    match v.as_object() {
        Some(o) => Ok(o.get("result").map(py::str_of).unwrap_or_default()),
        None => Err("output".into()),
    }
}

struct CodexOutput(PathBuf);

impl Drop for CodexOutput {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.0);
    }
}

fn run_codex(prompt: &str, model: &str, shared: &Shared) -> Result<String, String> {
    let path = std::env::temp_dir().join(format!("nunchi-codex-{}-{}", std::process::id(), clock::now_us()));
    std::fs::DirBuilder::new().mode(0o700).create(&path).map_err(|_| "io".to_string())?;
    let output = CodexOutput(path);
    let message = output.0.join("message.json");
    let mut cmd = Command::new("codex");
    cmd.args(["exec", "--ephemeral", "--ignore-user-config", "--ignore-rules",
              "--skip-git-repo-check", "--disable", "hooks", "--disable", "shell_tool",
              "--sandbox", "read-only", "--model", model, "--output-last-message"])
        .arg(&message).args(["--", prompt]).current_dir(&output.0).env("CONTROL_TUI_ANALYZER", "1");
    run_child(cmd, shared)?;
    std::fs::read_to_string(&message).map_err(|_| "output".into())
}

fn run_child(mut cmd: Command, shared: &Shared) -> Result<Vec<u8>, String> {
    cmd.stdin(Stdio::null()).stdout(Stdio::piped()).stderr(Stdio::piped());
    detach(&mut cmd);
    let mut child = cmd.spawn().map_err(|_| "spawn".to_string())?;
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
    let Some(status) = status else { return Err(format!("timeout:{TIMEOUT_SECONDS}")) };
    if !status.success() {
        let code = status.code().map(i64::from).unwrap_or_else(|| {
            use std::os::unix::process::ExitStatusExt;
            -(status.signal().unwrap_or(0) as i64)
        });
        return Err(format!("exit:{code}"));
    }
    Ok(stdout)
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
                if py::get(&existing, "source_ts") == Some(&Value::from(ts)) && !flow_pending(&existing) && !rebuild_asked(dir) {
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
        write_status(dir, "queued", 0, &rebuild_mark(dir));
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
    let Some(last) = turns.last() else { return Err("no-turns".into()) };
    start_rebuild(&job.dir, &job.ts, last.index)?;
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
        write_analysis(&job.dir, base, &job.ts, json!({}), last.index).map_err(|_| "io".to_string())?;
    }
    let since = sh.m.lock().unwrap().since.clone();
    let mut extra = vec![("since", Value::from(since)), ("source_ts", Value::from(job.ts.as_str()))];
    extra.extend(rebuild_mark(&job.dir));
    write_status(&job.dir, "running", last.index, &extra);
    advance_flow(sh, &job.dir, &turns)?;
    write_status(&job.dir, "idle", 0, &[]);
    Ok(())
}

/// 목표 흐름을 새 턴만큼 이어 적는다. 한 턴마다 저장해 화면이 따라오게 한다
// ---------- 다시 분석 (요구 이력 76, BUILD_PLAN §4.14) ----------

const REBUILD_MARK: &str = "rebuild"; // 세션 폴더: {"lang", "at"}. 분석기가 그 세션을 맡아 초기화할 때 지운다
const REBUILD_BACKUP: &str = "analysis.prev.json"; // 다시 분석이 끝날 때까지 남기는 이전 결과

fn rebuild_asked(dir: &Path) -> bool {
    dir.join(REBUILD_MARK).exists()
}

/// 상태 파일에 다시 분석 중임을 적는다: mod가 `흐름 처음부터 만드는 중`을 고른다
fn rebuild_mark(dir: &Path) -> Vec<(&'static str, Value)> {
    if rebuild_asked(dir) || dir.join(REBUILD_BACKUP).exists() { vec![("rebuild", Value::Bool(true))] } else { vec![] }
}

/// 표시가 있으면: 이전 결과를 백업하고, 새 언어의 빈 흐름으로 처음부터. 표시는 지워 10턴씩 나눠 도는 동안 다시 초기화하지 않는다
fn start_rebuild(dir: &Path, ts: &str, last_turn: i64) -> Result<(), String> {
    if !rebuild_asked(dir) {
        return Ok(());
    }
    let mark = store::read_obj(&dir.join(REBUILD_MARK));
    let lang = flow::clean_lang(mark.get("lang").and_then(Value::as_str).unwrap_or(""));
    if let Some(old) = read_analysis(dir) {
        if !dir.join(REBUILD_BACKUP).exists() {
            store::write_json(&dir.join(REBUILD_BACKUP), &old).map_err(|_| "io".to_string())?;
        }
    }
    let mut base = Map::new();
    base.insert("first_goal".into(), Value::from(""));
    base.insert("current_goal".into(), Value::from(""));
    base.insert("turns".into(), json!([]));
    base.insert("last_response_summary".into(), Value::from(""));
    base.insert("ledger".into(), json!([]));
    base.insert("forgotten".into(), json!([]));
    base.insert("flow".into(), flow::empty_in(&lang));
    write_analysis(dir, base, ts, json!({}), last_turn).map_err(|_| "io".to_string())?;
    let _ = std::fs::remove_file(dir.join(REBUILD_MARK));
    Ok(())
}

/// `nunchi-engine rebuild <세션 ID> <언어>`: 그 세션을 새 언어로 처음부터 다시 분석해 달라고 남기고 분석기를 깨운다.
/// 초기화는 분석기가 그 세션을 맡은 뒤에 한다(돌던 분석이 덮어쓰지 않게). 0 성공, 1 기록 없음
pub fn rebuild_main(args: &[String]) -> i32 {
    let (Some(sid), Some(lang)) = (args.first(), args.get(1)) else {
        eprintln!("usage: nunchi-engine rebuild SESSION LANG");
        return 2;
    };
    if sid.is_empty() || sid.contains('/') || sid.contains("..") {
        return 2;
    }
    let home = store::home_dir();
    let dir = home.join("sessions").join(sid);
    let tp = events_field(&dir, "transcript_path").unwrap_or_default();
    let ts = last_answer_ts(&dir).unwrap_or_default();
    if tp.is_empty() || ts.is_empty() {
        eprintln!("no record for {sid}");
        return 1;
    }
    let mark = json!({"lang": flow::clean_lang(lang), "at": clock::now_us()});
    if store::write_json(&dir.join(REBUILD_MARK), &mark).is_err() || enqueue(&home, sid, &tp, &ts, true, "nunchi").is_err() {
        return 1;
    }
    write_status(&dir, "queued", 0, &[("rebuild", Value::Bool(true))]);
    wake(&home, store::load_settings(&home).analyze_workers);
    0
}

/// `nunchi-engine build <세션 ID> <언어> [--count]` (요구 이력 93): 이 세션의 지금까지 대화를 지금 분석한다.
/// 분석이 없거나 옛 엔진 형식이면 처음부터(다시 분석 표시), 아니면 아직 분석하지 않은 응답만.
/// 한 줄 JSON `{"total", "done", "todo", "fresh"}`를 내고, `--count`면 세기만 한다. 할 것이 없으면 맡기지 않는다.
/// 0 성공, 1 기록 없음·읽지 못함, 2 인자 오류
pub fn build_main(args: &[String]) -> i32 {
    let (Some(sid), Some(lang)) = (args.first(), args.get(1)) else {
        eprintln!("usage: nunchi-engine build SESSION LANG [--count]");
        return 2;
    };
    if sid.is_empty() || sid.contains('/') || sid.contains("..") {
        return 2;
    }
    let count_only = args.iter().skip(2).any(|a| a == "--count");
    let home = store::home_dir();
    let dir = home.join("sessions").join(sid);
    let tp = events_field(&dir, "transcript_path").unwrap_or_default();
    let ts = last_answer_ts(&dir).unwrap_or_default();
    if tp.is_empty() || ts.is_empty() {
        eprintln!("no record for {sid}");
        return 1;
    }
    let turns = match parse_turns(Path::new(&tp), &ts) {
        Ok(t) => t,
        Err(_) => return 1,
    };
    let plan = build_plan(read_analysis(&dir).as_ref(), &turns);
    println!("{}", plan);
    if count_only || plan["todo"] == json!(0) {
        return 0;
    }
    let fresh = plan["fresh"] == json!(true);
    if fresh && read_analysis(&dir).is_some() {
        let mark = json!({"lang": flow::clean_lang(lang), "at": clock::now_us()});
        if store::write_json(&dir.join(REBUILD_MARK), &mark).is_err() {
            return 1;
        }
    }
    if enqueue(&home, sid, &tp, &ts, true, "nunchi").is_err() {
        return 1;
    }
    let extra: Vec<(&str, Value)> = if fresh { vec![("rebuild", Value::Bool(true))] } else { vec![] };
    write_status(&dir, "queued", 0, &extra);
    wake(&home, store::load_settings(&home).analyze_workers);
    0
}

/// 마지막 응답 시각: 기록의 마지막 Stop, 없으면 지난 분석의 기준 시각
fn last_answer_ts(dir: &Path) -> Option<String> {
    let last_stop = std::fs::read_to_string(event_path(dir)).unwrap_or_default().lines()
        .filter_map(|l| serde_json::from_str::<Value>(l).ok())
        .filter(|v| py::get(v, "event") == Some(&Value::from("Stop")))
        .filter_map(|v| py::get(&v, "ts").map(py::str_of)).last();
    last_stop.or_else(|| read_analysis(dir).and_then(|a| py::get(&a, "source_ts").map(py::str_of))).filter(|t| !t.is_empty())
}

/// 지금 분석할 것 (요구 이력 93). 흐름이 없거나, 근거가 확인된 단계 중 결정 목록(`decisions`)이 없는 것이 있으면
/// 옛 엔진(0.5.0까지)이 쓴 흐름이라 처음부터 다시 한다(분석은 이어서 하므로 그대로 두면 옛 단계가 끝까지 남는다)
pub fn build_plan(analysis: Option<&Value>, turns: &[Turn]) -> Value {
    let total = turns.iter().map(|t| t.index).max().unwrap_or(0);
    let flow = analysis.and_then(|a| py::get(a, "flow")).filter(|f| f.is_object());
    let old = flow.map(|f| py::get(f, "steps").and_then(Value::as_array).map(|st| {
        st.iter().any(|x| py::get(x, "grounded") == Some(&Value::Bool(true)) && py::get(x, "decisions").is_none())
    }).unwrap_or(false)).unwrap_or(false);
    let fresh = flow.is_none() || old || !flow.map(|f| flow::valid_for(f, turns)).unwrap_or(false);
    let done = if fresh { 0 } else { flow.and_then(|f| py::int_or(py::get(f, "until"), 0)).unwrap_or(0) };
    let todo = (total - done).max(0);
    json!({"total": total, "done": done, "todo": todo, "fresh": fresh && todo > 0})
}

/// 새 흐름의 분석 언어 (요구 이력 76): /nunchi가 쓴 want의 lang → mod가 세션 시작 때 적은 lang 파일 → ko
fn session_lang(dir: &Path) -> String {
    let from_want = store::read_obj(&dir.join("want")).get("lang").and_then(Value::as_str).map(String::from);
    let from_file = || std::fs::read_to_string(dir.join("lang")).ok().map(|t| t.trim().to_string());
    flow::clean_lang(&from_want.filter(|l| !l.trim().is_empty()).or_else(from_file).unwrap_or_default())
}

fn advance_flow(sh: &Shared, dir: &Path, turns: &[Turn]) -> Result<(), String> {
    let mut data = read_analysis(dir).unwrap_or_else(|| json!({}));
    let mut f = flow::migrate(py::get(&data, "flow"), turns).unwrap_or(Value::Null);
    if !flow::valid_for(&f, turns) {
        f = flow::empty_in(&session_lang(dir)); // 흐름을 새로 만들 때 이 세션의 분석 언어를 정한다 (요구 이력 76)
    }
    let rebuilt = !py::opt_truthy(py::get(&f, "steps"));
    let before = flow::shifts_count(&f);
    let left_before: HashSet<String> = flow::remaining(&f).iter().map(|r| py::str_of(&r["id"])).collect();
    let mut kept: Option<Value> = None;
    if flow::grown(&f, turns) {
        kept = Some(f.clone());
        f = flow::rewind(&f);
    }
    let codex_model = crate::codex::analysis_model(dir)?;
    let until = py::int_or(py::get(&f, "until"), 0).unwrap_or(0);
    let todo: Vec<&Turn> = turns.iter().filter(|t| t.index > until).take(FLOW_STEPS_PER_JOB).collect();
    let since = sh.m.lock().unwrap().since.clone();
    for t in todo {
        if sh.stopped() {
            return Ok(());
        }
        let mut extra = vec![("since", Value::from(since.as_str()))];
        extra.extend(rebuild_mark(dir));
        write_status(dir, "running", t.index, &extra);
        let lang = flow::lang_of(&f);
        let mut runner = |p: &str| match &codex_model {
            Some(model) => run_codex(p, model, sh),
            None => run_claude(p, &sh.model, &lang, sh),
        };
        f = flow::advance(&f, turns, t, &mut runner, 2)?;
        let fell_back = py::list(py::get(&f, "steps")).last().map(|s| py::opt_truthy(py::get(s, "fallback"))).unwrap_or(false);
        let mut restored = false;
        if let Some(k) = kept.take() {
            if py::eq_int(py::get(&k, "until"), t.index) && fell_back {
                f = k; // 다시 적기가 대체 단계로 끝났으면 앞서 적은 것을 둔다
                restored = true;
            }
        }
        // Codex 분석은 대체 단계를 적지 않고 실패로 돌려 다시 시도하게 한다. 앞서 적은 것을 되살렸으면 실패가 아니다
        if codex_model.is_some() && fell_back && !restored {
            return Err("output".into());
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
        store::write_json(&dir.join("analysis.json"), &data).map_err(|_| "io".to_string())?;
    }
    // 다시 분석이 끝까지 따라잡으면 이전 결과 백업을 지운다 (요구 이력 76). 중간에 멈추면 남겨 둔다
    let until = py::int_or(py::get(&f, "until"), 0).unwrap_or(0);
    if turns.last().map(|t| until >= t.index).unwrap_or(false) {
        let _ = std::fs::remove_file(dir.join(REBUILD_BACKUP));
    }
    Ok(())
}

// ---------- 분석기 본체 ----------

fn event_path(dir: &Path) -> PathBuf {
    let codex = dir.join(crate::codex::EVENTS);
    if codex.exists() { codex } else { dir.join("events.jsonl") }
}

fn events_field(dir: &Path, key: &str) -> Option<String> {
    let text = std::fs::read_to_string(event_path(dir)).ok()?;
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
    let mut got = glossary::explain_shown(&body, &cwd);   // 응답이 이미 풀어 쓴 번호는 뺀다 (요구 이력 82)
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
                // 이미 더 최신 응답까지 분석한 결과가 있으면 이 요청은 지난 것이다: 맡으면 흐름이 맞지 않아 처음부터 다시 한다
                // 시각끼리만 견준다(옛 결과의 source_ts에는 시각이 아닌 글이 있을 수 있다). 같은 꼴의 ISO 시각은 글자 순서가 시간 순서다
                let iso = |t: &str| t.len() >= 20 && t.as_bytes()[..4].iter().all(u8::is_ascii_digit) && t.as_bytes()[10] == b'T';
                let newer = py::get(e, "source_ts").map(py::str_of).map(|t| iso(&t) && iso(&ts) && t.as_str() > ts.as_str()).unwrap_or(false);
                if newer && !an.busy_with(&sid) && !rebuild_asked(&sdir) {
                    drop_item(item);
                    release(home, &sid);
                    mine.remove(&sid);
                    continue;
                }
                if py::truthy(e) && py::get(e, "source_ts") == item.v.get("source_ts") && !flow_pending(e) && !an.busy_with(&sid) && !rebuild_asked(&sdir) {
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
