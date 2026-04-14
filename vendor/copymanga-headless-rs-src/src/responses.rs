use std::collections::HashMap;
use std::ops::{Deref, DerefMut};

use serde::{Deserialize, Serialize};

#[derive(Default, Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct CopyResp {
    pub code: i64,
    pub message: String,
    pub results: serde_json::Value,
}

#[derive(Default, Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(default, rename_all = "camelCase")]
pub struct Pagination<T> {
    pub list: Vec<T>,
    pub total: i64,
    pub limit: i64,
    pub offset: i64,
}

#[derive(Default, Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(default, rename_all = "camelCase")]
pub struct AuthorRespData {
    pub name: String,
    pub alias: Option<String>,
    #[serde(rename = "path_word")]
    pub path_word: String,
}

#[derive(Default, Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct SearchRespData(pub Pagination<ComicInSearchRespData>);

impl Deref for SearchRespData {
    type Target = Pagination<ComicInSearchRespData>;

    fn deref(&self) -> &Self::Target {
        &self.0
    }
}

impl DerefMut for SearchRespData {
    fn deref_mut(&mut self) -> &mut Self::Target {
        &mut self.0
    }
}

#[derive(Default, Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ComicInSearchRespData {
    pub name: String,
    pub alias: Option<String>,
    #[serde(rename = "path_word")]
    pub path_word: String,
    pub cover: String,
    pub ban: i64,
    pub author: Vec<AuthorRespData>,
    pub popular: i64,
}

#[derive(Default, Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(default, rename_all = "camelCase")]
#[allow(clippy::struct_excessive_bools)]
pub struct GetComicRespData {
    #[serde(rename = "is_banned")]
    pub is_banned: bool,
    #[serde(rename = "is_lock")]
    pub is_lock: bool,
    #[serde(rename = "is_login")]
    pub is_login: bool,
    #[serde(rename = "is_mobile_bind")]
    pub is_mobile_bind: bool,
    #[serde(rename = "is_vip")]
    pub is_vip: bool,
    pub comic: ComicInGetComicRespData,
    pub popular: i64,
    pub groups: HashMap<String, GroupRespData>,
}

#[derive(Default, Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(default, rename_all = "camelCase")]
#[allow(clippy::struct_excessive_bools)]
pub struct ComicInGetComicRespData {
    pub uuid: String,
    #[serde(rename = "b_404")]
    pub b_404: bool,
    #[serde(rename = "b_hidden")]
    pub b_hidden: bool,
    pub ban: i64,
    #[serde(rename = "ban_ip")]
    pub ban_ip: Option<bool>,
    pub name: String,
    pub alias: Option<String>,
    #[serde(rename = "path_word")]
    pub path_word: String,
    #[serde(rename = "close_comment")]
    pub close_comment: bool,
    #[serde(rename = "close_roast")]
    pub close_roast: bool,
    pub free_type: LabeledValueRespData,
    pub restrict: LabeledValueRespData,
    pub reclass: LabeledValueRespData,
    #[serde(rename = "seo_baidu")]
    pub seo_baidu: Option<String>,
    pub region: LabeledValueRespData,
    pub status: LabeledValueRespData,
    pub author: Vec<AuthorRespData>,
    pub theme: Vec<ThemeRespData>,
    pub brief: String,
    #[serde(rename = "datetime_updated")]
    pub datetime_updated: String,
    pub cover: String,
    #[serde(rename = "last_chapter")]
    pub last_chapter: LastChapterRespData,
    pub popular: i64,
}

#[derive(Default, Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(default, rename_all = "camelCase")]
pub struct LabeledValueRespData {
    pub value: i64,
    pub display: String,
}

#[derive(Default, Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(default, rename_all = "camelCase")]
pub struct ThemeRespData {
    pub name: String,
    #[serde(rename = "path_word")]
    pub path_word: String,
}

#[derive(Default, Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(default, rename_all = "camelCase")]
pub struct LastChapterRespData {
    pub uuid: String,
    pub name: String,
}

#[derive(Default, Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(default, rename_all = "camelCase")]
pub struct GroupRespData {
    #[serde(rename = "path_word")]
    pub path_word: String,
    pub count: u32,
    pub name: String,
}

#[derive(Default, Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct GetChaptersRespData(pub Pagination<ChapterInGetChaptersRespData>);

impl Deref for GetChaptersRespData {
    type Target = Pagination<ChapterInGetChaptersRespData>;

    fn deref(&self) -> &Self::Target {
        &self.0
    }
}

impl DerefMut for GetChaptersRespData {
    fn deref_mut(&mut self) -> &mut Self::Target {
        &mut self.0
    }
}

#[derive(Default, Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ChapterInGetChaptersRespData {
    pub index: i64,
    pub uuid: String,
    pub count: i64,
    pub ordered: i64,
    pub size: i64,
    pub name: String,
    #[serde(rename = "comic_id")]
    pub comic_id: String,
    #[serde(rename = "comic_path_word")]
    pub comic_path_word: String,
    #[serde(rename = "group_id")]
    pub group_id: Option<String>,
    #[serde(rename = "group_path_word")]
    pub group_path_word: String,
    #[serde(rename = "type")]
    pub type_field: i64,
    pub news: String,
    #[serde(rename = "datetime_created")]
    pub datetime_created: String,
    pub prev: Option<String>,
    pub next: Option<String>,
}

#[derive(Default, Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
#[allow(clippy::struct_excessive_bools)]
pub struct GetChapterRespData {
    #[serde(rename = "is_banned")]
    pub is_banned: bool,
    #[serde(rename = "show_app")]
    pub show_app: bool,
    #[serde(rename = "is_lock")]
    pub is_lock: bool,
    #[serde(rename = "is_login")]
    pub is_login: bool,
    #[serde(rename = "is_mobile_bind")]
    pub is_mobile_bind: bool,
    #[serde(rename = "is_vip")]
    pub is_vip: bool,
    pub comic: ComicInGetChapterRespData,
    pub chapter: ChapterInGetChapterRespData,
}

#[derive(Default, Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ComicInGetChapterRespData {
    pub name: String,
    pub uuid: String,
    #[serde(rename = "path_word")]
    pub path_word: String,
    pub restrict: RestrictRespData,
}

#[derive(Default, Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct RestrictRespData {
    pub value: i64,
    pub display: String,
}

#[derive(Default, Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ChapterInGetChapterRespData {
    pub index: i64,
    pub uuid: String,
    pub count: i64,
    pub ordered: i64,
    pub size: i64,
    pub name: String,
    #[serde(rename = "comic_id")]
    pub comic_id: String,
    #[serde(rename = "comic_path_word")]
    pub comic_path_word: String,
    #[serde(rename = "group_id")]
    pub group_id: Option<String>,
    #[serde(rename = "group_path_word")]
    pub group_path_word: String,
    #[serde(rename = "type")]
    pub type_field: i64,
    pub news: String,
    #[serde(rename = "datetime_created")]
    pub datetime_created: String,
    pub prev: Option<String>,
    pub next: Option<String>,
    pub contents: Vec<ContentRespData>,
    pub words: Vec<i64>,
    #[serde(rename = "is_long")]
    pub is_long: bool,
}

#[derive(Default, Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ContentRespData {
    pub url: String,
}

#[derive(Default, Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct LoginRespData {
    pub token: String,
    #[serde(rename = "user_id")]
    pub user_id: String,
    pub username: String,
    pub nickname: String,
    pub avatar: String,
    #[serde(rename = "datetime_created")]
    pub datetime_created: String,
    pub ticket: f64,
    #[serde(rename = "reward_ticket")]
    pub reward_ticket: f64,
    pub downloads: i64,
    #[serde(rename = "vip_downloads")]
    pub vip_downloads: i64,
    #[serde(rename = "reward_downloads")]
    pub reward_downloads: i64,
    #[serde(rename = "scy_answer")]
    pub scy_answer: bool,
}
