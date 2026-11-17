//! nunchi 엔진: Claude Code 훅 기록과 백그라운드 분석기 (BUILD_PLAN §4.13).
//! 실행 파일은 main.rs. 모듈은 시험(tests/)에서도 쓰도록 라이브러리로 둔다.

pub mod clock;
pub mod flow;
pub mod glossary;
pub mod hook;
pub mod py;
pub mod store;
pub mod transcript;
pub mod worker;
#[cfg(feature = "dev")]
pub mod dev;
