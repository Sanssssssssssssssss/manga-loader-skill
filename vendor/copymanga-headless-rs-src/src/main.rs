mod account_pool;
mod config;
mod copy_client;
mod download;
mod errors;
mod responses;

use std::sync::Arc;

use anyhow::Context;
use clap::Parser;
use serde_json::json;

use crate::account_pool::AccountPool;
use crate::config::{Cli, Command, RuntimeConfig};
use crate::copy_client::CopyClient;
use crate::download::{DownloadChapterArgs, DownloadManager, SearchRow};

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    let cli = Cli::parse();
    let runtime_config = Arc::new(RuntimeConfig::from_cli(&cli)?);
    let account_pool = Arc::new(tokio::sync::RwLock::new(
        AccountPool::new(&runtime_config.state_dir)
            .context("failed to initialize account pool")?,
    ));
    let copy_client = CopyClient::new(runtime_config.clone(), account_pool);
    let downloader = DownloadManager::new(runtime_config, copy_client.clone());

    match cli.command {
        Command::Search { keyword, page, limit, json } => {
            let results = copy_client.search(&keyword, page).await?.0;
            let rows = results
                .list
                .into_iter()
                .take(limit.max(0) as usize)
                .map(|item| SearchRow {
                    name: item.name,
                    path_word: item.path_word,
                    popular: item.popular,
                })
                .collect::<Vec<_>>();
            print_value(&rows, json)?;
        }
        Command::Comic {
            comic_path_word,
            json,
        } => {
            let comic = copy_client.get_comic(&comic_path_word).await?;
            let summary = DownloadManager::comic_summary(&comic);
            print_value(&summary, json)?;
        }
        Command::Chapters {
            comic_path_word,
            group,
            json,
        } => {
            let chapters = copy_client.get_group_chapters(&comic_path_word, &group).await?;
            let rows = DownloadManager::chapter_rows(&chapters);
            print_value(&rows, json)?;
        }
        Command::DownloadChapter {
            comic_path_word,
            chapter_uuid,
            output_root,
            skip_existing,
            max_images,
        } => {
            let comic = copy_client.get_comic(&comic_path_word).await?;
            let chapters = all_group_chapters(&copy_client, &comic_path_word, &comic).await?;
            let chapter = chapters
                .into_iter()
                .find(|row| row.uuid == chapter_uuid)
                .with_context(|| format!("chapter uuid not found: {chapter_uuid}"))?;
            let group_title = comic
                .groups
                .get(&chapter.group_path_word)
                .map(|group| group.name.clone())
                .unwrap_or_else(|| chapter.group_path_word.clone());
            let args = DownloadChapterArgs {
                comic_path_word,
                output_root,
                skip_existing,
                max_images,
            };
            downloader
                .download_one_chapter(&comic.comic.name, &group_title, &chapter, &args)
                .await?;
        }
        Command::DownloadGroup {
            comic_path_word,
            group,
            output_root,
            limit,
            reverse,
            skip_existing,
            max_images,
        } => {
            let comic = copy_client.get_comic(&comic_path_word).await?;
            let group_title = comic
                .groups
                .get(&group)
                .map(|item| item.name.clone())
                .with_context(|| format!("group not found in comic metadata: {group}"))?;
            let mut chapters = copy_client.get_group_chapters(&comic_path_word, &group).await?;
            if reverse {
                chapters.reverse();
            }
            if let Some(limit) = limit {
                chapters.truncate(limit);
            }
            if chapters.is_empty() {
                anyhow::bail!("no chapters matched the requested group selection");
            }
            let args = DownloadChapterArgs {
                comic_path_word,
                output_root,
                skip_existing,
                max_images,
            };
            downloader
                .download_group(&comic.comic.name, &group_title, chapters, args)
                .await?;
        }
    }

    Ok(())
}

async fn all_group_chapters(
    copy_client: &CopyClient,
    comic_path_word: &str,
    comic: &crate::responses::GetComicRespData,
) -> anyhow::Result<Vec<crate::responses::ChapterInGetChaptersRespData>> {
    let mut chapters = Vec::new();
    let group_path_words = comic.groups.keys().cloned().collect::<Vec<_>>();
    for group_path_word in group_path_words {
        let mut rows = copy_client
            .get_group_chapters(comic_path_word, &group_path_word)
            .await
            .map_err(anyhow::Error::from)
            .with_context(|| format!("failed to get chapters for group {group_path_word}"))?;
        chapters.append(&mut rows);
    }
    Ok(chapters)
}

fn print_value<T: serde::Serialize>(value: &T, as_json: bool) -> anyhow::Result<()> {
    if as_json {
        println!("{}", serde_json::to_string_pretty(value)?);
        return Ok(());
    }
    match serde_json::to_value(value)? {
        serde_json::Value::Array(items) => {
            for item in items {
                println!("{}", serde_json::to_string(&item)?);
            }
        }
        object => {
            println!("{}", serde_json::to_string_pretty(&json!(object))?);
        }
    }
    Ok(())
}
