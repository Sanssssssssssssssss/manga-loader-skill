use std::sync::Arc;

use anyhow::Context;
use parking_lot::RwLock;
use serde::{Deserialize, Serialize};

use crate::copy_client::CopyClient;
use crate::errors::CopyMangaResult;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Account {
    pub username: String,
    pub password: String,
    pub token: String,
    pub limited_at: i64,
}

#[derive(Debug)]
pub struct AccountPool {
    account_path: std::path::PathBuf,
    accounts: Vec<Arc<RwLock<Account>>>,
}

impl AccountPool {
    pub fn new(state_dir: &std::path::Path) -> anyhow::Result<Self> {
        std::fs::create_dir_all(state_dir)
            .context(format!("failed to create state dir: {}", state_dir.display()))?;
        let account_path = state_dir.join("account.json");
        if !account_path.exists() {
            std::fs::write(&account_path, "[]")
                .context(format!("failed to create account file: {}", account_path.display()))?;
        }
        let accounts_string = std::fs::read_to_string(&account_path)
            .context(format!("failed to read account file: {}", account_path.display()))?;
        let accounts: Vec<Account> = serde_json::from_str(&accounts_string).context(format!(
            "failed to parse account file as Vec<Account>: {accounts_string}"
        ))?;
        let accounts = accounts
            .into_iter()
            .map(|account| Arc::new(RwLock::new(account)))
            .collect();
        Ok(Self {
            account_path,
            accounts,
        })
    }

    pub fn get_available_account(&self) -> Option<Arc<RwLock<Account>>> {
        let now = chrono::Local::now().timestamp();
        self.accounts
            .iter()
            .find(|account| now - account.read().limited_at > 60)
            .cloned()
    }

    pub async fn register(&mut self, copy_client: &CopyClient) -> CopyMangaResult<Arc<RwLock<Account>>> {
        use fake::faker::internet::en::Password;
        use fake::faker::name::en::{FirstName, LastName};
        use fake::Fake;

        let first_name = FirstName().fake::<String>();
        let last_name = LastName().fake::<String>();
        let number = rand::random::<u16>();
        let username = format!("{first_name}{last_name}{number}")
            .chars()
            .filter(|ch| ch.is_alphanumeric())
            .collect::<String>();
        let password = Password(10..30).fake::<String>();

        copy_client.register(&username, &password).await?;
        let login_resp = copy_client.login(&username, &password).await?;
        let account = Account {
            username,
            password,
            token: login_resp.token,
            limited_at: 0,
        };
        let account = Arc::new(RwLock::new(account));
        self.accounts.push(account.clone());
        self.save().context("failed to save auto-registered account")?;
        Ok(account)
    }

    pub fn save(&mut self) -> anyhow::Result<()> {
        let accounts: Vec<Account> = self.accounts.iter().map(|account| account.read().clone()).collect();
        let accounts_json = serde_json::to_string_pretty(&accounts)
            .context("failed to serialize account pool as json")?;
        std::fs::write(&self.account_path, accounts_json)
            .context(format!("failed to write {}", self.account_path.display()))?;
        Ok(())
    }
}
