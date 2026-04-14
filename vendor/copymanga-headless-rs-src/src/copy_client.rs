use std::sync::Arc;
use std::time::Duration;

use anyhow::{anyhow, Context};
use base64::{engine::general_purpose, Engine};
use bytes::Bytes;
use image::ImageFormat;
use parking_lot::RwLock;
use reqwest::StatusCode;
use reqwest_middleware::{ClientBuilder as MiddlewareClientBuilder, ClientWithMiddleware, RequestBuilder};
use reqwest_retry::{policies::ExponentialBackoff, Jitter, RetryTransientMiddleware};
use serde_json::json;

use crate::account_pool::{Account, AccountPool};
use crate::config::RuntimeConfig;
use crate::errors::{CopyMangaError, CopyMangaResult, RiskControlError};
use crate::responses::{
    ChapterInGetChaptersRespData, CopyResp, GetChapterRespData, GetChaptersRespData, GetComicRespData,
    LoginRespData, SearchRespData,
};

#[derive(Clone)]
pub struct CopyClient {
    config: Arc<RuntimeConfig>,
    account_pool: Arc<tokio::sync::RwLock<AccountPool>>,
    api_client: ClientWithMiddleware,
    img_client: ClientWithMiddleware,
}

impl CopyClient {
    pub fn new(config: Arc<RuntimeConfig>, account_pool: Arc<tokio::sync::RwLock<AccountPool>>) -> Self {
        let api_client = create_api_client(&config);
        let img_client = create_img_client(&config);
        Self {
            config,
            account_pool,
            api_client,
            img_client,
        }
    }

    pub async fn register(&self, username: &str, password: &str) -> CopyMangaResult<()> {
        let form = json!({
            "username": username,
            "password": password,
            "source": "freeSite"
        });
        let http_resp = self
            .api_client
            .post(format!("https://{}/api/v3/register", self.api_domain()))
            .form(&form)
            .send_with_timeout_msg()
            .await?;
        let status = http_resp.status();
        let body = http_resp.text().await?;
        if status.as_u16() == 210 {
            return Err(RiskControlError::Register(body).into());
        } else if status != StatusCode::OK {
            return Err(anyhow!("register failed with unexpected status({status}): {body}").into());
        }
        let copy_resp = serde_json::from_str::<CopyResp>(&body)
            .context(format!("register failed while parsing body as CopyResp: {body}"))?;
        if copy_resp.code != 200 {
            return Err(anyhow!("register failed with unexpected code: {copy_resp:?}").into());
        }
        Ok(())
    }

    pub async fn login(&self, username: &str, password: &str) -> CopyMangaResult<LoginRespData> {
        const SALT: i32 = 1729;
        let encoded_password =
            general_purpose::STANDARD.encode(format!("{password}-{SALT}").as_bytes());
        let form = json!({
            "username": username,
            "password": encoded_password,
            "salt": SALT,
        });
        let http_resp = self
            .api_client
            .post(format!("https://{}/api/v3/login", self.api_domain()))
            .form(&form)
            .send_with_timeout_msg()
            .await?;
        let status = http_resp.status();
        let body = http_resp.text().await?;
        if status.as_u16() == 210 {
            return Err(RiskControlError::Login(body).into());
        } else if status != StatusCode::OK {
            return Err(anyhow!("login failed with unexpected status({status}): {body}").into());
        }
        let copy_resp = serde_json::from_str::<CopyResp>(&body)
            .context(format!("login failed while parsing body as CopyResp: {body}"))?;
        if copy_resp.code != 200 {
            return Err(anyhow!("login failed with unexpected code: {copy_resp:?}").into());
        }
        let results_str = copy_resp.results.to_string();
        let login_resp = serde_json::from_str::<LoginRespData>(&results_str)
            .context(format!("login failed while parsing results as LoginRespData: {results_str}"))?;
        Ok(login_resp)
    }

    pub async fn search(&self, keyword: &str, page_num: i64) -> CopyMangaResult<SearchRespData> {
        const LIMIT: i64 = 20;
        let offset = (page_num - 1) * LIMIT;
        let params = json!({
            "limit": LIMIT,
            "offset": offset,
            "q": keyword,
            "q_type": "",
            "platform": 1,
        });
        let http_resp = self
            .api_client
            .get(format!("https://{}/api/v3/search/comic", self.api_domain()))
            .query(&params)
            .send_with_timeout_msg()
            .await?;
        let status = http_resp.status();
        let body = http_resp.text().await?;
        if status.as_u16() == 210 {
            return Err(RiskControlError::Search(body).into());
        } else if status != StatusCode::OK {
            return Err(anyhow!("search failed with unexpected status({status}): {body}").into());
        }
        let copy_resp = serde_json::from_str::<CopyResp>(&body)
            .context(format!("search failed while parsing body as CopyResp: {body}"))?;
        if copy_resp.code != 200 {
            return Err(anyhow!("search failed with unexpected code: {copy_resp:?}").into());
        }
        let results_str = copy_resp.results.to_string();
        let search_resp = serde_json::from_str::<SearchRespData>(&results_str)
            .context(format!("search failed while parsing results as SearchRespData: {results_str}"))?;
        Ok(search_resp)
    }

    pub async fn get_comic(&self, comic_path_word: &str) -> CopyMangaResult<GetComicRespData> {
        let params = json!({ "platform": 1 });
        let http_resp = self
            .api_client
            .get(format!("https://{}/api/v3/comic2/{comic_path_word}", self.api_domain()))
            .query(&params)
            .send_with_timeout_msg()
            .await?;
        let status = http_resp.status();
        let body = http_resp.text().await?;
        if status.as_u16() == 210 {
            return Err(RiskControlError::GetComic(body).into());
        } else if status != StatusCode::OK {
            return Err(anyhow!("get comic failed with unexpected status({status}): {body}").into());
        }
        let copy_resp = serde_json::from_str::<CopyResp>(&body)
            .context(format!("get comic failed while parsing body as CopyResp: {body}"))?;
        if copy_resp.code != 200 {
            return Err(anyhow!("get comic failed with unexpected code: {copy_resp:?}").into());
        }
        let results_str = copy_resp.results.to_string();
        let comic_resp = serde_json::from_str::<GetComicRespData>(&results_str)
            .context(format!("get comic failed while parsing results as GetComicRespData: {results_str}"))?;
        Ok(comic_resp)
    }

    pub async fn get_group_chapters(
        &self,
        comic_path_word: &str,
        group_path_word: &str,
    ) -> CopyMangaResult<Vec<ChapterInGetChaptersRespData>> {
        const LIMIT: i64 = 100;
        let mut chapters = vec![];
        let mut first_page = self
            .get_chapters(comic_path_word, group_path_word, LIMIT, 0)
            .await?;
        chapters.append(&mut first_page.list);
        let total_pages = first_page.total / LIMIT + 1;
        if total_pages == 1 {
            return Ok(chapters);
        }
        let mut join_set = tokio::task::JoinSet::new();
        for page in 2..=total_pages {
            let comic_path_word = comic_path_word.to_string();
            let group_path_word = group_path_word.to_string();
            let copy_client = self.clone();
            join_set.spawn(async move {
                let offset = (page - 1) * LIMIT;
                let response = copy_client
                    .get_chapters(&comic_path_word, &group_path_word, LIMIT, offset)
                    .await?;
                Ok::<_, CopyMangaError>(response)
            });
        }
        while let Some(result) = join_set.join_next().await {
            let mut response = result??;
            chapters.append(&mut response.list);
        }
        Ok(chapters)
    }

    pub async fn get_chapters(
        &self,
        comic_path_word: &str,
        group_path_word: &str,
        limit: i64,
        offset: i64,
    ) -> CopyMangaResult<GetChaptersRespData> {
        let params = json!({
            "limit": limit,
            "offset": offset,
        });
        let http_resp = self
            .api_client
            .get(format!(
                "https://{}/api/v3/comic/{comic_path_word}/group/{group_path_word}/chapters",
                self.api_domain()
            ))
            .query(&params)
            .send_with_timeout_msg()
            .await?;
        let status = http_resp.status();
        let body = http_resp.text().await?;
        if status.as_u16() == 210 {
            return Err(RiskControlError::GetChapters(body).into());
        } else if status != StatusCode::OK {
            return Err(anyhow!("get chapters failed with unexpected status({status}): {body}").into());
        }
        let copy_resp = serde_json::from_str::<CopyResp>(&body)
            .context(format!("get chapters failed while parsing body as CopyResp: {body}"))?;
        if copy_resp.code != 200 {
            return Err(anyhow!("get chapters failed with unexpected code: {copy_resp:?}").into());
        }
        let results_str = copy_resp.results.to_string();
        let chapters = serde_json::from_str::<GetChaptersRespData>(&results_str)
            .context(format!("get chapters failed while parsing results as GetChaptersRespData: {results_str}"))?;
        Ok(chapters)
    }

    pub async fn get_chapter(
        &self,
        comic_path_word: &str,
        chapter_uuid: &str,
    ) -> CopyMangaResult<GetChapterRespData> {
        let account = if let Some(account) = self.get_account_from_pool().await {
            account
        } else {
            let mut account_pool = self.account_pool.write().await;
            match account_pool.get_available_account() {
                Some(account) => account,
                None => account_pool.register(self).await?,
            }
        };
        let token = account.read().token.clone();
        let authorization = format!("Token {token}");
        let params = json!({ "platform": 1 });
        let http_resp = self
            .api_client
            .get(format!(
                "https://{}/api/v3/comic/{comic_path_word}/chapter2/{chapter_uuid}",
                self.api_domain()
            ))
            .query(&params)
            .header("authorization", authorization)
            .send_with_timeout_msg()
            .await?;
        let status = http_resp.status();
        let body = http_resp.text().await?;
        if status.as_u16() == 210 {
            account.write().limited_at = chrono::Local::now().timestamp();
            self.account_pool.write().await.save()?;
            return Err(RiskControlError::GetChapter(body).into());
        } else if status != StatusCode::OK {
            return Err(anyhow!("get chapter failed with unexpected status({status}): {body}").into());
        }
        let copy_resp = serde_json::from_str::<CopyResp>(&body)
            .context(format!("get chapter failed while parsing body as CopyResp: {body}"))?;
        if copy_resp.code != 200 {
            return Err(anyhow!("get chapter failed with unexpected code: {copy_resp:?}").into());
        }
        let results_str = copy_resp.results.to_string();
        let chapter = serde_json::from_str::<GetChapterRespData>(&results_str)
            .context(format!("get chapter failed while parsing results as GetChapterRespData: {results_str}"))?;
        Ok(chapter)
    }

    pub async fn get_img_data_and_format(&self, url: &str) -> anyhow::Result<(Bytes, ImageFormat)> {
        let http_resp = self.img_client.get(url).send_with_timeout_msg().await?;
        let status = http_resp.status();
        if status != StatusCode::OK {
            let body = http_resp.text().await?;
            return Err(anyhow!("download image {url} failed with unexpected status({status}): {body}"));
        }
        let content_type = http_resp
            .headers()
            .get("content-type")
            .ok_or_else(|| anyhow!("response missing content-type"))?
            .to_str()
            .context("response content-type was not utf-8")?
            .to_string();
        let img_data = http_resp.bytes().await?;
        let img_format = match content_type.as_str() {
            "image/webp" => ImageFormat::WebP,
            "image/jpeg" => ImageFormat::Jpeg,
            _ => return Err(anyhow!("unexpected source image format: {content_type}")),
        };
        Ok((img_data, img_format))
    }

    fn api_domain(&self) -> &str {
        &self.config.api_domain
    }

    async fn get_account_from_pool(&self) -> Option<Arc<RwLock<Account>>> {
        self.account_pool.read().await.get_available_account()
    }
}

trait SendWithTimeoutMsg {
    async fn send_with_timeout_msg(self) -> anyhow::Result<reqwest::Response>;
}

impl SendWithTimeoutMsg for RequestBuilder {
    async fn send_with_timeout_msg(self) -> anyhow::Result<reqwest::Response> {
        self.send().await.map_err(|err| {
            if err.is_timeout() || err.is_middleware() {
                anyhow::Error::from(err).context("network timeout, try another route or proxy")
            } else {
                anyhow::Error::from(err)
            }
        })
    }
}

fn create_img_client(config: &RuntimeConfig) -> ClientWithMiddleware {
    let retry_base = u32::try_from(config.retry_base_sec).unwrap_or(u32::MAX);
    let retry_policy = ExponentialBackoff::builder()
        .base(retry_base)
        .build_with_max_retries(config.api_retries);
    let client = reqwest::ClientBuilder::new().build().expect("create img client");
    MiddlewareClientBuilder::new(client)
        .with(RetryTransientMiddleware::new_with_policy(retry_policy))
        .build()
}

fn create_api_client(config: &RuntimeConfig) -> ClientWithMiddleware {
    use reqwest::header::{HeaderMap, HeaderValue};

    let retry_base = u32::try_from(config.retry_base_sec).unwrap_or(u32::MAX);
    let retry_policy = ExponentialBackoff::builder()
        .base(retry_base)
        .jitter(Jitter::Bounded)
        .build_with_max_retries(config.api_retries);

    let mut headers = HeaderMap::new();
    headers.insert("User-Agent", HeaderValue::from_static("COPY/3.0.0"));
    headers.insert("Accept", HeaderValue::from_static("application/json"));
    headers.insert("version", HeaderValue::from_static("2025.08.15"));
    headers.insert("platform", HeaderValue::from_static("1"));
    headers.insert("webp", HeaderValue::from_static("1"));
    headers.insert("region", HeaderValue::from_static("1"));

    let client = reqwest::ClientBuilder::new()
        .default_headers(headers)
        .timeout(Duration::from_secs(3))
        .build()
        .expect("create api client");

    MiddlewareClientBuilder::new(client)
        .with(RetryTransientMiddleware::new_with_policy(retry_policy))
        .build()
}
