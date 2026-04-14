use anyhow::anyhow;
use std::fmt::{Display, Formatter};

pub type CopyMangaResult<T> = Result<T, CopyMangaError>;

#[derive(Debug)]
pub enum CopyMangaError {
    Anyhow(anyhow::Error),
    RiskControl(RiskControlError),
}

impl From<anyhow::Error> for CopyMangaError {
    fn from(err: anyhow::Error) -> Self {
        CopyMangaError::Anyhow(err)
    }
}

impl From<reqwest::Error> for CopyMangaError {
    fn from(err: reqwest::Error) -> Self {
        CopyMangaError::Anyhow(err.into())
    }
}

impl From<tokio::task::JoinError> for CopyMangaError {
    fn from(err: tokio::task::JoinError) -> Self {
        CopyMangaError::Anyhow(err.into())
    }
}

impl From<tokio::sync::AcquireError> for CopyMangaError {
    fn from(err: tokio::sync::AcquireError) -> Self {
        CopyMangaError::Anyhow(err.into())
    }
}

impl From<CopyMangaError> for anyhow::Error {
    fn from(err: CopyMangaError) -> Self {
        match err {
            CopyMangaError::Anyhow(err) => err,
            CopyMangaError::RiskControl(err) => match err {
                RiskControlError::Register(err) => anyhow!(err),
                RiskControlError::Login(err) => anyhow!(err),
                RiskControlError::GetUserProfile(err) => anyhow!(err),
                RiskControlError::Search(err) => anyhow!(err),
                RiskControlError::GetComic(err) => anyhow!(err),
                RiskControlError::GetChapter(err) => anyhow!(err),
                RiskControlError::GetChapters(err) => anyhow!(err),
                RiskControlError::GetFavorite(err) => anyhow!(err),
            },
        }
    }
}

impl From<RiskControlError> for CopyMangaError {
    fn from(err: RiskControlError) -> Self {
        CopyMangaError::RiskControl(err)
    }
}

impl Display for CopyMangaError {
    fn fmt(&self, f: &mut Formatter<'_>) -> std::fmt::Result {
        match self {
            CopyMangaError::Anyhow(err) => write!(f, "{err}"),
            CopyMangaError::RiskControl(err) => write!(f, "{err}"),
        }
    }
}

#[derive(Debug)]
pub enum RiskControlError {
    Register(String),
    Login(String),
    GetUserProfile(String),
    Search(String),
    GetComic(String),
    GetChapter(String),
    GetChapters(String),
    GetFavorite(String),
}

impl Display for RiskControlError {
    fn fmt(&self, f: &mut Formatter<'_>) -> std::fmt::Result {
        match self {
            RiskControlError::Register(body) => write!(f, "risk control during register: {body}"),
            RiskControlError::Login(body) => write!(f, "risk control during login: {body}"),
            RiskControlError::GetUserProfile(body) => {
                write!(f, "risk control during get user profile: {body}")
            }
            RiskControlError::Search(body) => write!(f, "risk control during search: {body}"),
            RiskControlError::GetComic(body) => write!(f, "risk control during get comic: {body}"),
            RiskControlError::GetChapter(body) => {
                write!(f, "risk control during get chapter: {body}")
            }
            RiskControlError::GetChapters(body) => {
                write!(f, "risk control during get chapters: {body}")
            }
            RiskControlError::GetFavorite(body) => {
                write!(f, "risk control during get favorite: {body}")
            }
        }
    }
}

impl std::error::Error for RiskControlError {}
