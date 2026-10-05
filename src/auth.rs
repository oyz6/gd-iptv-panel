use std::collections::HashMap;
use std::sync::Mutex;
use std::time::{Duration, Instant};

const TOKEN_TTL: Duration = Duration::from_secs(7 * 24 * 3600);

pub struct TokenStore {
    tokens: Mutex<HashMap<String, Instant>>,
}

impl TokenStore {
    pub fn new() -> Self {
        Self {
            tokens: Mutex::new(HashMap::new()),
        }
    }

    pub fn issue(&self) -> String {
        let token = uuid::Uuid::new_v4().simple().to_string();
        let mut map = self.tokens.lock().unwrap();
        let now = Instant::now();
        map.retain(|_, exp| *exp > now);
        map.insert(token.clone(), now + TOKEN_TTL);
        token
    }

    pub fn check(&self, token: &str) -> bool {
        if token.is_empty() {
            return false;
        }
        let mut map = self.tokens.lock().unwrap();
        let now = Instant::now();
        match map.get(token) {
            Some(exp) if *exp > now => true,
            _ => {
                map.remove(token);
                false
            }
        }
    }

    pub fn revoke(&self, token: &str) {
        self.tokens.lock().unwrap().remove(token);
    }
}
