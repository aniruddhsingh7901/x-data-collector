# Aggressive Scraping Implementation Plan

## 🎯 Goal
Scrape 100M tweets per day with 100 accounts, targeting hashtags/keywords with complete pagination (posts, comments, retweets).

## 📊 Calculation
- 100 accounts × 400 requests/15min × 4 cycles/hour × 24 hours = **9.6M requests/day**
- Average 10-20 tweets per request = **96M - 192M tweets/day** ✅ Goal achievable!

---

## 🔧 Required Modifications

### 1. **Account Format Support** (`account.py`)

**Current format:**
```
username:password:email:email_password
```

**New format:**
```
username:password:email:email_password:ct0:auth_token:proxy
JenniferTu63671:ruthking15215:wdxbzkvhqp@rambler.ru:1198718MYNTva:d0dc507929e9880670a7f0388ef0387db571d931753f708a50e913368ca5d6719d461b792b73b03ca758fcc645d78283e10bde504ccff866b0df39fe89ff3bdfd619de91ca37b7bcba822656a141e14d:cbb381e1e18af71bfc8d177d7d1b1e8707581066:5.249.176.154:5432:uae2k:ddfivl8d
```

**Changes:**
```python
# In accounts_pool.py - modify load_from_file()
async def load_from_file(self, filepath: str, line_format: str):
    """
    Enhanced format: username:password:email:email_password:ct0:auth_token:proxy
    """
    # Parse ct0 and auth_token
    # Set cookies directly: {"ct0": ct0, "auth_token": auth_token}
    # Set active=True (skip login)
```

---

### 2. **Aggressive Rate Limiting** (`accounts_pool.py`)

**Strategy:**
- Track requests per endpoint per account
- Self-impose 400 requests per 15 minutes per endpoint
- 5-minute cooldown after 400 requests (before Twitter's limit)
- 15-minute cooldown if Twitter actually rate limits

**Implementation:**
```python
class AccountsPool:
    # New fields per account
    # request_count: {"SearchTimeline": 395, "UserTweets": 150}
    # cooldown_until: {"SearchTimeline": "2024-11-29T01:05:00"}
    
    async def get_for_queue_or_wait(self, queue: str):
        """
        Enhanced logic:
        1. Check if account has < 400 requests in last 15 min
        2. Check if account is in cooldown
        3. If all accounts exhausted, wait for shortest cooldown
        """
        
    async def apply_aggressive_cooldown(self, username: str, queue: str):
        """
        Apply 5-minute cooldown after 400 requests
        """
        cooldown_until = utc.now() + timedelta(minutes=5)
        await self.lock_until(username, queue, int(cooldown_until.timestamp()))
    
    async def track_request(self, username: str, queue: str):
        """
        Increment request counter
        Check if reached 400 → apply cooldown
        """
```

**Database schema update:**
```sql
ALTER TABLE accounts ADD COLUMN request_counts TEXT DEFAULT '{}';
-- Format: {"SearchTimeline": [{"timestamp": 1732843800, "count": 1}, ...]}
```

---

### 3. **Pagination Continuation** (`api.py` + new `pagination_state.py`)

**Problem:** When Account A gets rate limited mid-pagination, Account B must continue from the same cursor.

**Solution: Shared Pagination State**

```python
# New file: pagination_state.py
class PaginationStateManager:
    """
    Track pagination cursors across accounts
    Key: query_hash (hash of search query/params)
    Value: {
        "cursor": "DAABCgABGVb...",
        "count": 150,
        "last_account": "user1",
        "last_updated": "2024-11-29T01:00:00"
    }
    """
    
    def __init__(self, db_path: str):
        self.states: Dict[str, Dict] = {}
        self.db_path = db_path
    
    async def get_cursor(self, query_hash: str) -> Optional[str]:
        """Get continuation cursor for query"""
        
    async def update_cursor(self, query_hash: str, cursor: str, count: int):
        """Update cursor after successful page"""
        
    async def clear_cursor(self, query_hash: str):
        """Clear when pagination complete"""
```

**Modified API search:**
```python
class API:
    def __init__(self, ...):
        self.pagination_state = PaginationStateManager("pagination.db")
    
    async def search(self, q: str, limit=-1, kv: dict = None):
        """
        Enhanced with continuation:
        1. Generate query_hash from q + kv
        2. Check if pagination_state has cursor
        3. If yes, start from that cursor
        4. On rate limit, save current cursor
        5. Next account continues from saved cursor
        """
        query_hash = hashlib.md5(f"{q}:{json.dumps(kv)}".encode()).hexdigest()
        
        # Try to get existing cursor
        start_cursor = await self.pagination_state.get_cursor(query_hash)
        if start_cursor:
            logger.info(f"Continuing pagination from cursor: {start_cursor[:20]}...")
```

---

### 4. **Request Tracking** (`queue_client.py`)

**Enhanced tracking:**
```python
class QueueClient:
    async def req(self, method: str, url: str, params: dict = None):
        # ... existing code ...
        
        try:
            rep = await ctx.req(method, url, params=params)
            await self._check_rep(rep)
            
            ctx.req_count += 1
            
            # NEW: Track request in pool
            await self.pool.track_request(ctx.acc.username, self.queue)
            
            # NEW: Check if approaching limit (400 requests)
            count = await self.pool.get_request_count(ctx.acc.username, self.queue)
            if count >= 400:
                logger.info(f"Account {ctx.acc.username} reached 400 requests on {self.queue}")
                await self.pool.apply_aggressive_cooldown(ctx.acc.username, self.queue)
                raise HandledError()  # Switch to next account
            
            return rep
```

---

### 5. **Enhanced Stats Tracking** (`accounts_pool.py`)

```python
async def get_request_count(self, username: str, queue: str, window_minutes: int = 15) -> int:
    """
    Count requests in last N minutes for specific queue
    Returns: number of requests
    """
    qs = """
    SELECT request_counts FROM accounts WHERE username = :username
    """
    row = await fetchone(self._db_file, qs, {"username": username})
    
    if not row:
        return 0
    
    counts = json.loads(row["request_counts"])
    queue_counts = counts.get(queue, [])
    
    # Filter requests in last 15 minutes
    cutoff = utc.ts() - (window_minutes * 60)
    recent = [c for c in queue_counts if c["timestamp"] > cutoff]
    
    return sum(c["count"] for c in recent)
```

---

## 📝 Implementation Steps

### Step 1: Modify Account Loading
```python
# accounts_pool.py
async def add_account_with_tokens(
    self,
    username: str,
    password: str,
    email: str,
    email_password: str,
    ct0: str,
    auth_token: str,
    proxy: str,
):
    """Add account with pre-existing tokens (skip login)"""
    account = Account(
        username=username,
        password=password,
        email=email,
        email_password=email_password,
        user_agent=UserAgent().safari,
        active=True,  # Already has tokens
        locks={},
        stats={},
        headers={
            "authorization": TOKEN,
            "x-csrf-token": ct0,
            "x-twitter-auth-type": "OAuth2Session",
        },
        cookies={
            "ct0": ct0,
            "auth_token": auth_token,
        },
        proxy=proxy,
    )
    await self.save(account)
```

### Step 2: Add Request Tracking Table
```sql
CREATE TABLE IF NOT EXISTS request_tracking (
    username TEXT,
    queue TEXT,
    timestamp INTEGER,
    count INTEGER DEFAULT 1,
    PRIMARY KEY (username, queue, timestamp)
);

CREATE INDEX idx_tracking_time ON request_tracking(timestamp);
```

### Step 3: Create Pagination State Manager
```python
# pagination_state.py - full implementation
```

### Step 4: Modify queue_client.py
- Add aggressive limit checking (400 req/15min)
- Apply 5-min cooldown before Twitter's limit
- Save pagination cursor on rate limit

### Step 5: Modify api.py
- Integrate PaginationStateManager
- Continue from saved cursor when switching accounts
- Track complete vs incomplete queries

---

## 🎮 Usage Example

```python
import asyncio
from twscrape import API, gather

async def aggressive_scrape():
    api = API("accounts.db", aggressive_mode=True)
    
    # Search with automatic pagination continuation
    hashtags = ["#bitcoin", "#crypto", "#web3"]
    
    for tag in hashtags:
        print(f"Scraping {tag}...")
        
        # This will automatically:
        # 1. Use multiple accounts
        # 2. Continue pagination across accounts
        # 3. Apply 5-min cooldown at 400 req
        # 4. Handle Twitter's rate limits
        tweets = []
        async for tweet in api.search(f"{tag} since:2024-10-29", limit=1000000):
            tweets.append(tweet)
            
            # Get comments for each tweet
            async for reply in api.tweet_replies(tweet.id, limit=1000):
                tweets.append(reply)
        
        print(f"Scraped {len(tweets)} tweets for {tag}")

asyncio.run(aggressive_scrape())
```

---

## 📈 Expected Performance

**With 100 accounts:**
- 400 requests per 15 min per account
- 4 cycles per hour (15 min each)
- 5 min cooldown between cycles
- Effective: ~20 min per cycle (15 min scraping + 5 min cooldown)

**Calculation:**
```
100 accounts × 400 requests × 3 cycles/hour × 24 hours = 2.88M requests/day
With 20-50 tweets per request = 57.6M - 144M tweets/day
```

**To reach 100M with buffer:**
- Use ~350 requests per cycle (leaving buffer)
- Focus on high-yield endpoints (search returns 20+ tweets/request)

---

## ⚠️ Important Considerations

1. **IP Rotation**: Your accounts have proxies - good! This prevents IP-based bans.

2. **Request Distribution**: Spread requests across different endpoints to avoid suspicion.

3. **Error Handling**: Some accounts may still get banned. The system will mark them inactive and continue with others.

4. **Data Storage**: 100M tweets/day = ~50GB/day (compressed). Plan storage accordingly.

5. **Monitoring**: Track:
   - Requests per account
   - Ban rate
   - Tweets scraped per hour
   - Failed queries

---

## 🚀 Next Steps

Would you like me to:
1. **Create the modified files** with all changes?
2. **Start with account loading** (parse your format)?
3. **Focus on pagination continuation** first?
4. **Implement request tracking** system?

Let me know which part to implement first!
