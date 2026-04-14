use std::path::PathBuf;

use clap::{Parser, Subcommand, ValueEnum};

const DEFAULT_API_DOMAIN: &str = "api.2025copy.com";

#[derive(Debug, Clone, Parser)]
#[command(name = "copymanga-headless-rs")]
#[command(about = "Headless CopyManga downloader that keeps upstream runtime behavior closer to the original")]
pub struct Cli {
    #[arg(long, default_value = DEFAULT_API_DOMAIN)]
    pub api_domain: String,
    #[arg(long)]
    pub state_dir: Option<PathBuf>,
    #[arg(long, value_enum, default_value_t = DownloadFormat::Webp)]
    pub download_format: DownloadFormat,
    #[arg(long, default_value_t = 3)]
    pub api_retries: u32,
    #[arg(long, default_value_t = 1)]
    pub retry_base_sec: u64,
    #[arg(long, default_value_t = 0.5)]
    pub retry_jitter_sec: f64,
    #[arg(long, default_value_t = 60)]
    pub risk_wait_sec: u64,
    #[arg(long, default_value_t = 3)]
    pub chapter_concurrency: usize,
    #[arg(long, default_value_t = 30)]
    pub image_concurrency: usize,
    #[arg(long, default_value_t = 0)]
    pub chapter_interval_sec: u64,
    #[arg(long, default_value_t = 0)]
    pub image_interval_sec: u64,
    #[command(subcommand)]
    pub command: Command,
}

#[derive(Debug, Clone, Subcommand)]
pub enum Command {
    Search {
        keyword: String,
        #[arg(long, default_value_t = 1)]
        page: i64,
        #[arg(long, default_value_t = 10)]
        limit: i64,
        #[arg(long)]
        json: bool,
    },
    Comic {
        comic_path_word: String,
        #[arg(long)]
        json: bool,
    },
    Chapters {
        comic_path_word: String,
        #[arg(long)]
        group: String,
        #[arg(long)]
        json: bool,
    },
    DownloadChapter {
        comic_path_word: String,
        #[arg(long)]
        chapter_uuid: String,
        #[arg(long)]
        output_root: PathBuf,
        #[arg(long)]
        skip_existing: bool,
        #[arg(long)]
        max_images: Option<usize>,
    },
    DownloadGroup {
        comic_path_word: String,
        #[arg(long)]
        group: String,
        #[arg(long)]
        output_root: PathBuf,
        #[arg(long)]
        limit: Option<usize>,
        #[arg(long)]
        reverse: bool,
        #[arg(long)]
        skip_existing: bool,
        #[arg(long)]
        max_images: Option<usize>,
    },
}

#[derive(Debug, Copy, Clone, PartialEq, Eq, ValueEnum)]
pub enum DownloadFormat {
    Webp,
    Jpeg,
}

impl DownloadFormat {
    pub fn extension(self) -> &'static str {
        match self {
            DownloadFormat::Webp => "webp",
            DownloadFormat::Jpeg => "jpg",
        }
    }

    pub fn to_image_format(self) -> image::ImageFormat {
        match self {
            DownloadFormat::Webp => image::ImageFormat::WebP,
            DownloadFormat::Jpeg => image::ImageFormat::Jpeg,
        }
    }
}

#[derive(Debug, Clone)]
pub struct RuntimeConfig {
    pub api_domain: String,
    pub state_dir: PathBuf,
    pub download_format: DownloadFormat,
    pub api_retries: u32,
    pub retry_base_sec: u64,
    pub retry_jitter_sec: f64,
    pub risk_wait_sec: u64,
    pub chapter_concurrency: usize,
    pub image_concurrency: usize,
    pub chapter_interval_sec: u64,
    pub image_interval_sec: u64,
}

impl RuntimeConfig {
    pub fn from_cli(cli: &Cli) -> anyhow::Result<Self> {
        let state_dir = match &cli.state_dir {
            Some(path) => path.clone(),
            None => default_state_dir()?,
        };
        Ok(Self {
            api_domain: cli.api_domain.clone(),
            state_dir,
            download_format: cli.download_format,
            api_retries: cli.api_retries,
            retry_base_sec: cli.retry_base_sec,
            retry_jitter_sec: cli.retry_jitter_sec,
            risk_wait_sec: cli.risk_wait_sec,
            chapter_concurrency: cli.chapter_concurrency,
            image_concurrency: cli.image_concurrency,
            chapter_interval_sec: cli.chapter_interval_sec,
            image_interval_sec: cli.image_interval_sec,
        })
    }
}

fn default_state_dir() -> anyhow::Result<PathBuf> {
    if let Some(base) = dirs::data_local_dir() {
        return Ok(base
            .join("mangaloader-epub-postprocess")
            .join("copymanga-headless-rs"));
    }
    Ok(std::env::current_dir()?.join(".copymanga-headless-rs"))
}
