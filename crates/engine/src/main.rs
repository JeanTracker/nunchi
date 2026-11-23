//! nunchi 엔진: Claude Code 훅 기록과 백그라운드 분석기 (BUILD_PLAN §4.13).
//!
//!   nunchi-engine hook              훅 입력(stdin)을 기록하고, 필요하면 분석기를 깨운다
//!   nunchi-engine worker --home D   대기열이 빌 때까지 분석하고 끝난다


use nunchi_engine::{clock, codex, hook, store, worker};
use std::io::Write;
use std::path::PathBuf;

/// 어디서 멈추든 errors.log에 남기고 끝낸다. 분석 스레드가 멈춘 채 자리 잠금을 쥐고 있지 않게 한다
fn on_panic(code: i32, label: &'static str) {
    std::panic::set_hook(Box::new(move |info| {
        let msg = info.payload().downcast_ref::<&str>().map(|s| s.to_string())
            .or_else(|| info.payload().downcast_ref::<String>().cloned()).unwrap_or_default();
        let at = info.location().map(|l| format!(" ({}:{})", l.file(), l.line())).unwrap_or_default();
        let home = store::home_dir();
        let _ = std::fs::create_dir_all(&home);
        if let Ok(mut f) = std::fs::OpenOptions::new().append(true).create(true).open(home.join("errors.log")) {
            let _ = writeln!(f, "{} {label} 실패: panic: {msg}{at}", clock::now_iso());
        }
        std::process::exit(code);
    }));
}

fn worker_main(args: &[String]) -> i32 {
    let mut home: PathBuf = store::home_dir();
    let mut it = args.iter();
    while let Some(a) = it.next() {
        if a == "--home" {
            if let Some(h) = it.next() {
                home = PathBuf::from(h);
            }
        }
    }
    std::env::set_var("CONTROL_TUI_HOME", &home); // panic 기록이 같은 곳으로 가게
    worker::drain(&home);
    0
}

fn main() {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let code = match args.first().map(String::as_str) {
        Some("hook") => {
            on_panic(0, "emit");
            hook::main()
        }
        Some("codex-hook") => {
            on_panic(0, "codex-hook");
            codex::main()
        }
        Some("worker") => {
            on_panic(1, "worker");
            worker_main(&args[1..])
        }
        Some("--version") => {
            println!("nunchi-engine {} (src {})", env!("CARGO_PKG_VERSION"), env!("NUNCHI_SOURCE_HASH"));
            0
        }
        Some("rebuild") => {
            on_panic(1, "worker");
            worker::rebuild_main(&args[1..])
        }
        Some("build") => {
            on_panic(1, "worker");
            worker::build_main(&args[1..])
        }
        #[cfg(feature = "dev")]
        Some("dev") => nunchi_engine::dev::main(&args[1..]),
        _ => {
            eprintln!("usage: nunchi-engine hook | codex-hook | worker --home DIR | rebuild SESSION LANG | build SESSION LANG [--count]");
            2
        }
    };
    std::process::exit(code);
}
