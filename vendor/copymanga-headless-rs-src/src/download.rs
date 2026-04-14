use std::io::Cursor;
use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::time::Duration;

use anyhow::{anyhow, Context};
use bytes::Bytes;
use image::ImageFormat;
use serde::Serialize;
use tokio::sync::Semaphore;
use tokio::task::JoinSet;
use tokio::time::sleep;

use crate::config::{DownloadFormat, RuntimeConfig};
use crate::copy_client::CopyClient;
use crate::errors::{CopyMangaError, RiskControlError};
use crate::responses::{
    ChapterInGetChapterRespData, ChapterInGetChaptersRespData, GetChapterRespData, GetComicRespData,
};

#[derive(Debug, Clone, Serialize)]
pub struct SearchRow {
    pub name: String,
    pub path_word: String,
    pub popular: i64,
}

#[derive(Debug, Clone, Serialize)]
pub struct ComicSummary {
    pub name: String,
    pub path_word: String,
    pub author: Vec<String>,
    pub groups: Vec<GroupSummary>,
}

#[derive(Debug, Clone, Serialize)]
pub struct GroupSummary {
    pub path_word: String,
    pub name: String,
    pub count: u32,
}

#[derive(Debug, Clone, Serialize)]
pub struct ChapterRow {
    pub index: i64,
    pub ordered: i64,
    pub name: String,
    pub uuid: String,
}

#[derive(Clone)]
pub struct DownloadManager {
    config: Arc<RuntimeConfig>,
    copy_client: CopyClient,
    chapter_sem: Arc<Semaphore>,
    img_sem: Arc<Semaphore>,
}

#[derive(Debug, Clone)]
pub struct DownloadChapterArgs {
    pub comic_path_word: String,
    pub output_root: PathBuf,
    pub skip_existing: bool,
    pub max_images: Option<usize>,
}

impl DownloadManager {
    pub fn new(config: Arc<RuntimeConfig>, copy_client: CopyClient) -> Self {
        Self {
            chapter_sem: Arc::new(Semaphore::new(config.chapter_concurrency)),
            img_sem: Arc::new(Semaphore::new(config.image_concurrency)),
            config,
            copy_client,
        }
    }

    pub fn comic_summary(comic: &GetComicRespData) -> ComicSummary {
        let mut groups = comic
            .groups
            .iter()
            .map(|(path_word, group)| GroupSummary {
                path_word: path_word.clone(),
                name: group.name.clone(),
                count: group.count,
            })
            .collect::<Vec<_>>();
        groups.sort_by(|a, b| a.path_word.cmp(&b.path_word));
        ComicSummary {
            name: comic.comic.name.clone(),
            path_word: comic.comic.path_word.clone(),
            author: comic.comic.author.iter().map(|author| author.name.clone()).collect(),
            groups,
        }
    }

    pub fn chapter_rows(chapters: &[ChapterInGetChaptersRespData]) -> Vec<ChapterRow> {
        chapters
            .iter()
            .map(|chapter| ChapterRow {
                index: chapter.index,
                ordered: chapter.ordered,
                name: chapter.name.clone(),
                uuid: chapter.uuid.clone(),
            })
            .collect()
    }

    pub async fn download_one_chapter(
        &self,
        comic_title: &str,
        group_title: &str,
        chapter: &ChapterInGetChaptersRespData,
        args: &DownloadChapterArgs,
    ) -> anyhow::Result<PathBuf> {
        let chapter_data = self
            .get_chapter_with_retry(&args.comic_path_word, &chapter.uuid)
            .await
            .context(format!("failed to fetch chapter {}", chapter.uuid))?;
        self.download_chapter_to_dir(comic_title, group_title, chapter, &chapter_data, args)
            .await
    }

    pub async fn download_group(
        &self,
        comic_title: &str,
        group_title: &str,
        chapters: Vec<ChapterInGetChaptersRespData>,
        args: DownloadChapterArgs,
    ) -> anyhow::Result<()> {
        let total = chapters.len();
        let mut join_set = JoinSet::new();
        for (position, chapter) in chapters.into_iter().enumerate() {
            let manager = self.clone();
            let comic_title = comic_title.to_string();
            let group_title = group_title.to_string();
            let args = args.clone();
            let chapter_sem = self.chapter_sem.clone();
            join_set.spawn(async move {
                let _permit = chapter_sem.acquire_owned().await?;
                println!("[{}/{}] {} ({})", position + 1, total, chapter.name, chapter.uuid);
                manager
                    .download_one_chapter(&comic_title, &group_title, &chapter, &args)
                    .await
            });
        }
        while let Some(result) = join_set.join_next().await {
            result??;
        }
        Ok(())
    }

    async fn get_chapter_with_retry(
        &self,
        comic_path_word: &str,
        chapter_uuid: &str,
    ) -> anyhow::Result<GetChapterRespData> {
        let mut retry_count = 0;
        loop {
            match self.copy_client.get_chapter(comic_path_word, chapter_uuid).await {
                Ok(data) => return Ok(data),
                Err(CopyMangaError::Anyhow(err)) => return Err(err),
                Err(CopyMangaError::RiskControl(RiskControlError::Register(_))) => {
                    sleep(Duration::from_secs(self.config.risk_wait_sec)).await;
                }
                Err(err) => {
                    let base_ms = self.config.retry_base_sec.saturating_mul(1000);
                    let jitter_ms = (self.config.retry_jitter_sec.max(0.0) * 1000.0) as u64;
                    let wait_time = base_ms + (rand::random::<u64>() % (jitter_ms.saturating_add(1)));
                    sleep(Duration::from_millis(wait_time.max(1000))).await;
                    if retry_count < 5 {
                        retry_count += 1;
                        continue;
                    }
                    return Err(err.into());
                }
            }
        }
    }

    async fn download_chapter_to_dir(
        &self,
        comic_title: &str,
        group_title: &str,
        chapter: &ChapterInGetChaptersRespData,
        chapter_data: &GetChapterRespData,
        args: &DownloadChapterArgs,
    ) -> anyhow::Result<PathBuf> {
        let destination = chapter_output_dir(&args.output_root, comic_title, group_title, chapter);
        let temp_download_dir = temp_download_dir(&destination);
        std::fs::create_dir_all(&temp_download_dir)
            .context(format!("failed to create temp dir {}", temp_download_dir.display()))?;
        self.clean_temp_download_dir(&temp_download_dir)?;

        let url_and_index_pairs = collect_page_jobs(&chapter_data.chapter, args.max_images);
        if url_and_index_pairs.is_empty() {
            return Err(anyhow!("no image urls were found for chapter {}", chapter.uuid));
        }

        let mut join_set = JoinSet::new();
        for (url, index) in url_and_index_pairs {
            let manager = self.clone();
            let temp_download_dir = temp_download_dir.clone();
            let img_sem = self.img_sem.clone();
            let skip_existing = args.skip_existing;
            join_set.spawn(async move {
                let _permit = img_sem.acquire_owned().await?;
                manager
                    .download_image(url, index, &temp_download_dir, skip_existing)
                    .await
            });
        }

        let mut success_count = 0usize;
        while let Some(result) = join_set.join_next().await {
            result??;
            success_count += 1;
        }
        if success_count == 0 {
            return Err(anyhow!("chapter download produced no files"));
        }

        if destination.exists() {
            std::fs::remove_dir_all(&destination)
                .context(format!("failed to remove existing destination {}", destination.display()))?;
        }
        if let Some(parent) = destination.parent() {
            std::fs::create_dir_all(parent)
                .context(format!("failed to create destination parent {}", parent.display()))?;
        }
        std::fs::rename(&temp_download_dir, &destination).context(format!(
            "failed to rename {} to {}",
            temp_download_dir.display(),
            destination.display()
        ))?;

        if self.config.chapter_interval_sec > 0 {
            sleep(Duration::from_secs(self.config.chapter_interval_sec)).await;
        }
        println!("Downloaded {} pages -> {}", success_count, destination.display());
        Ok(destination)
    }

    async fn download_image(
        &self,
        url: String,
        index: i64,
        temp_download_dir: &Path,
        skip_existing: bool,
    ) -> anyhow::Result<()> {
        let extension = self.config.download_format.extension();
        let save_path = temp_download_dir.join(format!("{:03}.{extension}", index + 1));
        if skip_existing && save_path.exists() {
            return Ok(());
        }
        let (img_data, img_format) = self
            .copy_client
            .get_img_data_and_format(&url)
            .await
            .context(format!("failed to download image {url}"))?;
        save_img(&save_path, self.config.download_format, &img_data, img_format)?;
        if self.config.image_interval_sec > 0 {
            sleep(Duration::from_secs(self.config.image_interval_sec)).await;
        }
        Ok(())
    }

    fn clean_temp_download_dir(&self, temp_download_dir: &Path) -> anyhow::Result<()> {
        if !temp_download_dir.exists() {
            return Ok(());
        }
        let extension = self.config.download_format.extension();
        for entry in std::fs::read_dir(temp_download_dir)
            .context(format!("failed to read {}", temp_download_dir.display()))?
        {
            let path = entry?.path();
            let should_keep = path
                .extension()
                .and_then(|ext| ext.to_str())
                .is_some_and(|ext| ext.eq_ignore_ascii_case(extension));
            if should_keep {
                continue;
            }
            if path.is_file() {
                let _ = std::fs::remove_file(path);
            }
        }
        Ok(())
    }
}

fn collect_page_jobs(
    chapter: &ChapterInGetChapterRespData,
    max_images: Option<usize>,
) -> Vec<(String, i64)> {
    let mut jobs = chapter
        .contents
        .iter()
        .enumerate()
        .filter_map(|(i, content)| {
            let index = chapter.words.get(i).copied()?;
            Some((content.url.replace(".c800x.", ".c1500x."), index))
        })
        .collect::<Vec<_>>();
    if let Some(max_images) = max_images {
        jobs.truncate(max_images);
    }
    jobs
}

fn chapter_output_dir(
    output_root: &Path,
    comic_title: &str,
    group_title: &str,
    chapter: &ChapterInGetChaptersRespData,
) -> PathBuf {
    output_root
        .join(sanitize_filename(comic_title))
        .join(sanitize_filename(group_title))
        .join(format!(
            "{:04} {}",
            chapter.index + 1,
            sanitize_filename(&chapter.name)
        ))
}

fn temp_download_dir(destination: &Path) -> PathBuf {
    let name = destination
        .file_name()
        .and_then(|value| value.to_str())
        .unwrap_or("chapter");
    destination
        .parent()
        .unwrap_or_else(|| Path::new("."))
        .join(format!(".downloading {name}"))
}

fn save_img(
    save_path: &Path,
    target_format: DownloadFormat,
    src_img_data: &Bytes,
    src_format: ImageFormat,
) -> anyhow::Result<()> {
    let target = target_format.to_image_format();
    if target == src_format {
        std::fs::write(save_path, src_img_data)
            .context(format!("failed to write {}", save_path.display()))?;
        return Ok(());
    }
    let img = image::load_from_memory(src_img_data).context("failed to decode image bytes")?;
    let mut converted = Vec::new();
    match target {
        ImageFormat::WebP => img
            .to_rgba8()
            .write_to(&mut Cursor::new(&mut converted), ImageFormat::WebP),
        ImageFormat::Jpeg => img
            .to_rgb8()
            .write_to(&mut Cursor::new(&mut converted), ImageFormat::Jpeg),
        _ => return Err(anyhow!("unsupported target image format: {target:?}")),
    }
    .context(format!("failed to convert {src_format:?} to {target:?}"))?;
    std::fs::write(save_path, converted)
        .context(format!("failed to write {}", save_path.display()))?;
    Ok(())
}

fn sanitize_filename(name: &str) -> String {
    let mut result = String::new();
    for ch in name.chars() {
        let invalid = matches!(ch, '<' | '>' | ':' | '"' | '/' | '\\' | '|' | '?' | '*')
            || ch.is_control();
        result.push(if invalid { '_' } else { ch });
    }
    let trimmed = result.trim().trim_end_matches(['.', ' ']).to_string();
    if trimmed.is_empty() {
        "untitled".to_string()
    } else {
        trimmed
    }
}
