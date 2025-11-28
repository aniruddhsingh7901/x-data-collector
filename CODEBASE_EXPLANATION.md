# TwScrape - Complete Codebase Explanation

## 🎯 Project Overview

**twscrape** is a Python library that scrapes Twitter/X data using Twitter's GraphQL API and Search API. It mimics browser behavior to collect tweets, users, and trends while managing multiple Twitter accounts to handle rate limits.

### Key Features:
1. **Account Pool Management** - Manages multiple Twitter accounts and rotates between them
2. **Async Operations** - Uses Python's async/await for concurrent scraping
3. **Rate Limit Handling** - Automatically switches accounts when rate limited
4. **Login System** - Handles Twitter login flow including 2FA and email verification
5. **Data Parsing** - Converts Twitter's raw JSON responses into structured Python objects

---

## 📁 File-by-File Breakdown

### 1️⃣ **twscrape/__init__.py** - Package Entry Point

```python
# Imports and exposes main components for external use
from .account import Account
from .accounts_pool import AccountsPool, NoAccountError
from .api import API
from .logger import set_log_level
from .models import *
from .utils import gather
```

**Purpose**: This is the package's public interface. When you `import twscrape`, these are the classes/functions available.

**Example**:
```python
from twscrape import API, gather

# API class is available directly
api = API()

# gather utility is available
results = await gather(api.search("python"))
```

---

### 2️⃣ **twscrape/account.py** - Account Data Structure

This file defines how Twitter account credentials and session data are stored.

#### Core Class: `Account`

```python
@dataclass
class Account(JSONTrait):
    username: str          # Twitter username
    password: str          # Twitter password
    email: str            # Email for verification
    email_password: str   # Email password for auto-verification
    user_agent: str       # Browser user agent string
    active: bool          # Is account logged in?
    locks: dict[str, datetime]    # Rate limit locks per API endpoint
    stats: dict[str, int]         # Request count per endpoint
    headers: dict[str, str]       # HTTP headers for requests
    cookies: dict[str, str]       # Session cookies
    mfa_code: str | None         # 2FA secret (if enabled)
    proxy: str | None            # Proxy URL
    error_msg: str | None        # Last error message
    last_used: datetime | None   # Last request timestamp
```

**Key Methods**:

1. **`from_rs(rs: sqlite3.Row)`** - Load account from database row
   - Deserializes JSON fields (locks, stats, headers, cookies)
   - Converts datetime strings back to datetime objects
   
2. **`to_rs()`** - Convert account to database format
   - Serializes complex fields to JSON strings
   - Prepares data for SQLite storage

3. **`make_client(proxy=None)`** - Creates HTTP client for requests
   - Sets up proxy (priority: parameter > env var > account.proxy)
   - Configures headers with user agent and authorization
   - Adds CSRF token from cookies if available

**Example Flow**:
```python
# Create account
acc = Account(
    username="user1",
    password="pass1",
    email="user1@mail.com",
    email_password="emailpass",
    user_agent="Mozilla/5.0...",
    active=False,
    locks={},
    stats={},
    headers={},
    cookies={}
)

# Make HTTP client
client = acc.make_client(proxy="http://proxy.com:8080")

# Client is configured with:
# - Proxy settings
# - User agent
# - Authorization token (Bearer token)
# - CSRF token from cookies
```

**Important Constants**:
```python
TOKEN = "Bearer AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs%3D1..."
# This is Twitter's public API token - same for all users
```

---

### 3️⃣ **twscrape/models.py** - Data Models & Parsing (800+ lines)

This is the **largest and most complex file**. It defines data structures and parsing logic.

#### A. Base Class: `JSONTrait`

```python
@dataclass
class JSONTrait:
    def dict(self):
        return asdict(self)  # Convert to dictionary
    
    def json(self):
        return json.dumps(self.dict(), default=str)  # Convert to JSON string
```

All data models inherit from this to easily convert to dict/JSON.

#### B. Core Data Models

**1. User Model**
```python
@dataclass
class User(JSONTrait):
    id: int                    # Numeric user ID
    username: str              # @username
    displayname: str           # Display name
    rawDescription: str        # Bio text
    created: datetime          # Account creation date
    followersCount: int        # Follower count
    friendsCount: int          # Following count
    statusesCount: int         # Tweet count
    # ... many more fields
```

**2. Tweet Model**
```python
@dataclass
class Tweet(JSONTrait):
    id: int                    # Tweet ID
    url: str                   # Tweet URL
    date: datetime             # When posted
    user: User                 # Author
    rawContent: str            # Tweet text
    replyCount: int           
    retweetCount: int
    likeCount: int
    quotedTweet: Optional["Tweet"]    # Quoted tweet
    retweetedTweet: Optional["Tweet"] # Retweeted tweet
    media: Media              # Photos/videos
    # ... many more fields
```

**3. Media Models**
```python
@dataclass
class MediaPhoto(JSONTrait):
    url: str  # Direct image URL

@dataclass
class MediaVideo(JSONTrait):
    thumbnailUrl: str
    variants: list[MediaVideoVariant]  # Different quality versions
    duration: int  # Milliseconds
    views: int | None

@dataclass
class Media(JSONTrait):
    photos: list[MediaPhoto]
    videos: list[MediaVideo]
    animated: list[MediaAnimated]  # GIFs
```

#### C. Parsing Functions

**Key Parsing Flow**:
```
Twitter JSON Response
        ↓
   to_old_rep()  ← Normalizes structure
        ↓
  _parse_items()  ← Iterates through items
        ↓
   Tweet.parse() or User.parse()  ← Creates objects
        ↓
   Yield parsed objects
```

**1. `to_old_rep(obj: dict)` - Normalizes Twitter Response**

Twitter's API returns nested JSON with `__typename` markers. This function flattens it:

```python
def to_old_rep(obj: dict) -> dict[str, dict]:
    # Extracts all typed objects
    tmp = get_typed_object(obj, defaultdict(list))
    
    # Normalize tweets
    tweets = {str(x["rest_id"]): to_old_obj(x) for x in tmp.get("Tweet", [])}
    
    # Normalize users
    users = {str(x["rest_id"]): to_old_obj(x) for x in tmp.get("User", [])}
    
    return {"tweets": tweets, "users": users, "trends": trends}
```

**2. `Tweet.parse(obj: dict, res: dict)` - Parse Tweet**

```python
@staticmethod
def parse(obj: dict, res: dict):
    # Get user object
    tw_usr = User.parse(res["users"][obj["user_id_str"]])
    
    # Find retweet if exists
    rt_obj = get_or(res, f"tweets.{_first(obj, rt_id_path)}")
    
    # Create Tweet object
    doc = Tweet(
        id=int(obj["id_str"]),
        url=f"https://x.com/{tw_usr.username}/status/{obj['id_str']}",
        user=tw_usr,
        rawContent=obj["full_text"],
        replyCount=obj["reply_count"],
        retweetCount=obj["retweet_count"],
        # ... many more fields
        retweetedTweet=Tweet.parse(rt_obj, res) if rt_obj else None,
    )
    
    return doc
```

**3. `parse_tweets(rep: Response, limit=-1)` - Main Parser**

```python
def parse_tweets(rep: Response, limit: int = -1):
    # Convert response to normalized format
    obj = to_old_rep(rep.json())
    
    ids = set()
    for x in obj["tweets"].values():
        try:
            tweet = Tweet.parse(x, obj)
            if tweet.id not in ids:  # Avoid duplicates
                ids.add(tweet.id)
                yield tweet
        except Exception as e:
            # Write error dump for debugging
            _write_dump("tweet", e, x, obj)
```

#### D. Special Parsing: Cards

Twitter cards are rich previews (polls, summaries, videos). The parsing is complex:

```python
def _parse_card(obj: dict, url: str):
    name = get_or(obj, "card.legacy.name")
    
    if name in {"summary", "summary_large_image"}:
        # Extract title, description, image, URL
        return SummaryCard(title=..., description=..., url=...)
    
    if name.startswith("poll"):
        # Extract poll options and votes
        return PollCard(options=[...], finished=True/False)
    
    if name == "745291183405076480:broadcast":
        # Video broadcast card
        return BroadcastCard(title=..., url=..., photo=...)
    
    # ... more card types
```

**Example of Tweet Parsing in Action**:

```python
# Raw Twitter API response (simplified)
raw_json = {
    "data": {
        "user": {
            "result": {
                "__typename": "User",
                "rest_id": "123",
                "legacy": {
                    "screen_name": "elonmusk",
                    "name": "Elon Musk",
                    "followers_count": 100000000
                }
            }
        },
        "tweetResult": {
            "result": {
                "__typename": "Tweet",
                "rest_id": "456",
                "legacy": {
                    "full_text": "Hello world!",
                    "reply_count": 100,
                    "retweet_count": 500
                }
            }
        }
    }
}

# After parsing
tweet = parse_tweet(raw_json, 456)
# tweet.id = 456
# tweet.user.username = "elonmusk"
# tweet.rawContent = "Hello world!"
# tweet.replyCount = 100
```

---

### 4️⃣ **twscrape/db.py** - Database Operations

Manages SQLite database for storing accounts.

#### Key Components:

**1. Database Lock System**
```python
_lock = asyncio.Lock()  # Prevents concurrent access

def lock_retry(max_retries=10):
    """Decorator that retries on database lock"""
    def decorator(func):
        async def wrapper(*args, **kwargs):
            for i in range(max_retries):
                try:
                    async with _lock:
                        return await func(*args, **kwargs)
                except sqlite3.OperationalError as e:
                    if "database is locked" in str(e):
                        await asyncio.sleep(random.uniform(0.5, 1.0))
                        continue
                    raise
        return wrapper
    return decorator
```

**Why locks?** Multiple processes might try to access the database (e.g., running two scraping scripts).

**2. Database Migrations**
```python
async def migrate(db: aiosqlite.Connection):
    # Get current version
    async with db.execute("PRAGMA user_version") as cur:
        rs = await cur.fetchone()
        uv = rs[0] if rs else 0
    
    # Migration v1: Create accounts table
    async def v1():
        qs = """CREATE TABLE IF NOT EXISTS accounts (
            username TEXT PRIMARY KEY,
            password TEXT NOT NULL,
            email TEXT NOT NULL,
            ...
        )"""
        await db.execute(qs)
    
    # Migration v2: Add stats column
    async def v2():
        await db.execute("ALTER TABLE accounts ADD COLUMN stats TEXT DEFAULT '{}'")
    
    # Run pending migrations
    migrations = {1: v1, 2: v2, 3: v3, 4: v4}
    for i in range(uv + 1, len(migrations) + 1):
        await migrations[i]()
        await db.execute(f"PRAGMA user_version = {i}")
```

**3. DB Context Manager**
```python
class DB:
    def __init__(self, db_path):
        self.db_path = db_path
    
    async def __aenter__(self):
        # Open connection and run migrations
        db = await aiosqlite.connect(self.db_path)
        db.row_factory = aiosqlite.Row  # Return rows as dict-like
        await migrate(db)
        self.conn = db
        return db
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        # Commit and close
        await self.conn.commit()
        await self.conn.close()
```

**4. Helper Functions**
```python
@lock_retry()
async def execute(db_path: str, qs: str, params: dict | None = None):
    """Execute SQL with automatic retries"""
    async with DB(db_path) as db:
        await db.execute(qs, params)

@lock_retry()
async def fetchone(db_path: str, qs: str, params: dict | None = None):
    """Fetch single row"""
    async with DB(db_path) as db:
        async with db.execute(qs, params) as cur:
            return await cur.fetchone()
```

**Example Usage**:
```python
# Add account to database
qs = "INSERT INTO accounts (username, password, email) VALUES (:username, :password, :email)"
params = {"username": "user1", "password": "pass1", "email": "user1@mail.com"}
await execute("accounts.db", qs, params)

# Get account
qs = "SELECT * FROM accounts WHERE username = :username"
row = await fetchone("accounts.db", qs, {"username": "user1"})
```

---

### 5️⃣ **twscrape/accounts_pool.py** - Account Pool Management

This is the **brain** of the account management system. It handles account rotation, locking, and state.

#### Key Class: `AccountsPool`

**Core Responsibilities**:
1. Store/load accounts from database
2. Select available accounts for requests
3. Lock accounts when rate limited
4. Track usage statistics
5. Handle login/relogin

**Important Methods**:

**1. Adding Accounts**
```python
async def add_account(
    self,
    username: str,
    password: str,
    email: str,
    email_password: str,
    user_agent: str | None = None,
    proxy: str | None = None,
    cookies: str | None = None,
):
    # Check if account exists
    qs = "SELECT * FROM accounts WHERE username = :username"
    rs = await fetchone(self._db_file, qs, {"username": username})
    if rs:
        logger.warning(f"Account {username} already exists")
        return
    
    # Create account object
    account = Account(
        username=username,
        password=password,
        email=email,
        email_password=email_password,
        user_agent=user_agent or UserAgent().safari,  # Random user agent
        active=False,
        locks={},
        stats={},
        headers={},
        cookies=parse_cookies(cookies) if cookies else {},
    )
    
    # If cookies provided, mark as active
    if "ct0" in account.cookies:
        account.active = True
    
    await self.save(account)
```

**2. Getting Account for Queue (Most Important!)**
```python
async def get_for_queue(self, queue: str):
    """
    Get an available account for specific API endpoint
    
    queue examples: "SearchTimeline", "UserTweets", "Followers"
    """
    
    # SQL query to find available account
    q = f"""
    SELECT username FROM accounts
    WHERE active = true AND (
        locks IS NULL
        OR json_extract(locks, '$.{queue}') IS NULL
        OR json_extract(locks, '$.{queue}') < datetime('now')
    )
    ORDER BY username
    LIMIT 1
    """
    
    # Lock the account for this queue for 15 minutes
    return await self._get_and_lock(queue, q)
```

**How locking works**:
```python
# Locks structure in database:
# {"SearchTimeline": "2024-11-29T01:00:00", "UserTweets": "2024-11-29T01:15:00"}

# When account is locked:
await self.lock_until(username, "SearchTimeline", unlock_at=timestamp, req_count=1)

# SQL updates locks:
"""
UPDATE accounts SET
    locks = json_set(locks, '$.SearchTimeline', datetime(unlock_at, 'unixepoch')),
    stats = json_set(stats, '$.SearchTimeline', existing_count + 1),
    last_used = datetime(now, 'unixepoch')
WHERE username = :username
"""
```

**3. Get Account or Wait**
```python
async def get_for_queue_or_wait(self, queue: str) -> Account | None:
    """
    Keep trying to get an account, wait if none available
    """
    msg_shown = False
    while True:
        account = await self.get_for_queue(queue)
        
        if not account:
            if not msg_shown:
                # Calculate when next account will be available
                nat = await self.next_available_at(queue)
                logger.info(f'No account available for queue "{queue}". Next at {nat}')
                msg_shown = True
            
            await asyncio.sleep(5)  # Wait 5 seconds
            continue
        
        return account
```

**4. Login All Accounts**
```python
async def login_all(self, usernames: list[str] | None = None):
    """Login all inactive accounts"""
    
    if usernames is None:
        # Get all inactive accounts without errors
        qs = "SELECT * FROM accounts WHERE active = false AND error_msg IS NULL"
    else:
        # Login specific accounts
        us = ",".join([f'"{x}"' for x in usernames])
        qs = f"SELECT * FROM accounts WHERE username IN ({us})"
    
    rs = await fetchall(self._db_file, qs)
    accounts = [Account.from_rs(rs) for rs in rs]
    
    counter = {"total": len(accounts), "success": 0, "failed": 0}
    for i, acc in enumerate(accounts, start=1):
        logger.info(f"[{i}/{len(accounts)}] Logging in {acc.username}")
        status = await self.login(acc)
        counter["success" if status else "failed"] += 1
    
    return counter
```

**5. Account Statistics**
```python
async def stats(self):
    """Get pool statistics"""
    
    # Get all unique queue names
    qs = "SELECT DISTINCT(f.key) as k from accounts, json_each(locks) f"
    rs = await fetchall(self._db_file, qs)
    gql_ops = [x["k"] for x in rs]
    
    # Count locked accounts per queue
    config = [
        ("total", "SELECT COUNT(*) FROM accounts"),
        ("active", "SELECT COUNT(*) FROM accounts WHERE active = true"),
        ("inactive", "SELECT COUNT(*) FROM accounts WHERE active = false"),
        *[(f"locked_{x}", locks_count(x)) for x in gql_ops],
    ]
    
    # Returns: {"total": 10, "active": 8, "locked_SearchTimeline": 2, ...}
```

**Example Flow**:
```python
# Initialize pool
pool = AccountsPool("accounts.db")

# Add accounts
await pool.add_account("user1", "pass1", "user1@mail.com", "mail_pass")
await pool.add_account("user2", "pass2", "user2@mail.com", "mail_pass")

# Login all
await pool.login_all()

# Get account for searching
acc = await pool.get_for_queue_or_wait("SearchTimeline")
# Returns: user1 (if available) or waits

# After request, lock it
await pool.lock_until("user1", "SearchTimeline", unlock_at=future_timestamp)

# Next request will use user2
acc = await pool.get_for_queue_or_wait("SearchTimeline")
# Returns: user2
```

---

### 6️⃣ **twscrape/queue_client.py** - Request Queue Manager

This file orchestrates the actual HTTP requests with account rotation and error handling.

#### Key Components:

**1. XClIdGenStore - Transaction ID Generator**
```python
class XClIdGenStore:
    """Stores X-Client-Transaction-ID generators per account"""
    items: dict[str, XClIdGen] = {}
    
    @classmethod
    async def get(cls, username: str, fresh=False) -> XClIdGen:
        if username in cls.items and not fresh:
            return cls.items[username]
        
        # Create new generator
        clid_gen = await XClIdGen.create()
        cls.items[username] = clid_gen
        return clid_gen
```

**What is x-client-transaction-id?** Twitter requires a special header that changes with each request. It's a cryptographic challenge to prevent bots.

**2. Ctx - Request Context**
```python
class Ctx:
    def __init__(self, acc: Account, clt: AsyncClient):
        self.req_count = 0  # Requests made with this account
        self.acc = acc
        self.clt = clt
    
    async def req(self, method: str, url: str, params: dict = None) -> Response:
        """Make request with proper transaction ID"""
        path = urlparse(url).path
        
        # Try up to 3 times with fresh transaction IDs
        tries = 0
        while tries < 3:
            gen = await XClIdGenStore.get(self.acc.username, fresh=tries > 0)
            hdr = {"x-client-transaction-id": gen.calc(method, path)}
            
            rep = await self.clt.request(method, url, params=params, headers=hdr)
            if rep.status_code != 404:
                return rep
            
            tries += 1
```

**3. QueueClient - Main Request Manager**
```python
class QueueClient:
    def __init__(self, pool: AccountsPool, queue: str, debug=False, proxy=None):
        self.pool = pool          # Account pool
        self.queue = queue        # API endpoint name
        self.debug = debug       # Enable request dumping
        self.ctx: Ctx | None = None  # Current context
        self.proxy = proxy
```

**Key Method: `req()` - Make Request with Auto-Retry**
```python
async def req(self, method: str, url: str, params: dict = None) -> Response | None:
    unknown_retry, connection_retry = 0, 0
    
    while True:
        # Get account from pool
        ctx = await self._get_ctx()
        if ctx is None:
            return None
        
        try:
            # Make request
            rep = await ctx.req(method, url, params=params)
            setattr(rep, "__username", ctx.acc.username)  # Track which account
            
            # Check response for errors
            await self._check_rep(rep)
            
            # Count successful request
            ctx.req_count += 1
            return rep
            
        except HandledError:
            # Rate limited or banned - get new account
            continue
        
        except AbortReqError:
            # Unrecoverable error - abort
            return None
        
        except (httpx.ReadTimeout, httpx.ProxyError):
            # Network error - retry with same account
            continue
```

**4. Response Checking - `_check_rep()`**

This is **critical** - it handles all Twitter API errors:

```python
async def _check_rep(self, rep: Response) -> None:
    """Check response and handle errors"""
    
    try:
        res = rep.json()
    except json.JSONDecodeError:
        res = {"_raw": rep.text}
    
    # Extract rate limit headers
    limit_remaining = int(rep.headers.get("x-rate-limit-remaining", -1))
    limit_reset = int(rep.headers.get("x-rate-limit-reset", -1))
    
    # Get error message if present
    if "errors" in res:
        err_msg = "; ".join([f"({x['code']}) {x['message']}" for x in res["errors"]])
    else:
        err_msg = "OK"
    
    # RATE LIMITED
    if limit_remaining == 0 and limit_reset > 0:
        logger.debug(f"Rate limited: {err_msg}")
        await self._close_ctx(limit_reset)  # Lock account until reset time
        raise HandledError()
    
    # ACCOUNT BANNED (Error 88 with remaining limits)
    if err_msg.startswith("(88) Rate limit exceeded") and limit_remaining > 0:
        logger.warning(f"Ban detected: {err_msg}")
        await self._close_ctx(-1, inactive=True, msg=err_msg)
        raise HandledError()
    
    # AUTHENTICATION ERROR (Error 32)
    if err_msg.startswith("(32) Could not authenticate you"):
        logger.warning(f"Session expired: {err_msg}")
        await self._close_ctx(-1, inactive=True, msg=err_msg)
        raise HandledError()
    
    # 403 without specific error
    if err_msg == "OK" and rep.status_code == 403:
        logger.warning(f"Session expired or banned")
        await self._close_ctx(-1, inactive=True)
        raise HandledError()
    
    # TWITTER INTERNAL ERROR (Error 131)
    if err_msg.startswith("(131) Dependency: Internal error"):
        if "data" in res:  # Has data, ignore error
            return
        logger.warning(f"Dependency error (request skipped)")
        raise AbortReqError()
    
    # Content not found (expected for some queries)
    if "_Missing: No status found with that ID" in err_msg:
        return  # Not an error
    
    # Other errors - log but continue
    if err_msg != "OK":
        logger.warning(f"API unknown error: {err_msg}")
        return
```

**Context Management**:
```python
async def _get_ctx(self):
    """Get or create context with account"""
    if self.ctx:
        return self.ctx
    
    # Get available account
    acc = await self.pool.get_for_queue_or_wait(self.queue)
    if acc is None:
        return None
    
    # Create HTTP client
    clt = acc.make_client(proxy=self.proxy)
    self.ctx = Ctx(acc, clt)
    return self.ctx

async def _close_ctx(self, reset_at=-1, inactive=False, msg=None):
    """Close context and update account state"""
    if self.ctx is None:
        return
    
    username = self.ctx.acc.username
    req_count = self.ctx.req_count
    
    # Close HTTP client
    await self.ctx.aclose()
    self.ctx = None
    
    if inactive:
        # Mark account as inactive
        await self.pool.mark_inactive(username, msg)
    elif reset_at > 0:
        # Lock account until reset time
        await self.pool.lock_until(username, self.queue, reset_at, req_count)
    else:
        # Unlock account
        await self.pool.unlock(username, self.queue, req_count)
```

**Usage Example**:
```python
async with QueueClient(pool, "SearchTimeline", debug=False) as client:
    # Client automatically gets account from pool
    
    # Make request
    response = await client.get("https://api.twitter.com/...", params={...})
    
    # If rate limited, client:
    # 1. Locks current account
    # 2. Gets new account from pool
    # 3. Retries request
    
    # On context exit, account is unlocked or locked based on response
```

---

---

### 7️⃣ **twscrape/api.py** - High-Level API Interface (500+ lines)

This is the **user-facing API** that provides simple methods to interact with Twitter. It's what you use when you `from twscrape import API`.

#### Core Class: `API`

```python
class API:
    def __init__(
        self,
        pool: AccountsPool | str | None = None,
        debug=False,
        proxy: str | None = None,
        raise_when_no_account=False,
    ):
        # Initialize account pool
        if isinstance(pool, AccountsPool):
            self.pool = pool
        elif isinstance(pool, str):
            self.pool = AccountsPool(db_file=pool)
        else:
            self.pool = AccountsPool()  # Default: accounts.db
        
        self.proxy = proxy
        self.debug = debug
```

**GraphQL Operations** - Twitter's API endpoints:
```python
# Each operation has a unique ID (format: "ID/Name")
OP_SearchTimeline = "AIdc203rPpK_k_2KWSdm7g/SearchTimeline"
OP_UserByRestId = "WJ7rCtezBVT6nk6VM5R8Bw/UserByRestId"
OP_UserByScreenName = "1VOOyvKkiI3FMmkeDNxM9A/UserByScreenName"
OP_TweetDetail = "_8aYOgEDz35BrBcBal1-_w/TweetDetail"
OP_Followers = "Elc_-qTARceHpztqhI9PQA/Followers"
# ... many more
```

**GQL Features** - Request parameters Twitter requires:
```python
GQL_FEATURES = {
    "longform_notetweets_consumption_enabled": True,
    "responsive_web_graphql_timeline_navigation_enabled": True,
    "view_counts_everywhere_api_enabled": True,
    # ... 30+ feature flags
}
```

#### Key Methods:

**1. Search Tweets**
```python
async def search(self, q: str, limit=-1, kv: dict = None):
    """
    Search for tweets
    
    Args:
        q: Search query (e.g., "python lang:en")
        limit: Max tweets to return (-1 = unlimited)
        kv: Additional parameters (e.g., {"product": "Top"})
    
    Yields:
        Tweet objects
    """
    async with aclosing(self.search_raw(q, limit=limit, kv=kv)) as gen:
        async for rep in gen:
            for tweet in parse_tweets(rep.json(), limit):
                yield tweet

async def search_raw(self, q: str, limit=-1, kv: dict = None):
    """Raw version - returns HTTP responses"""
    op = OP_SearchTimeline
    kv = {
        "rawQuery": q,
        "count": 20,  # Items per page
        "product": "Latest",  # Or "Top", "Media"
        "querySource": "typed_query",
        **(kv or {}),
    }
    
    # _gql_items handles pagination automatically
    async with aclosing(self._gql_items(op, kv, limit=limit)) as gen:
        async for x in gen:
            yield x
```

**Example**:
```python
api = API()

# Search for tweets about Python
async for tweet in api.search("python programming", limit=100):
    print(f"{tweet.user.username}: {tweet.rawContent}")

# Search top tweets only
async for tweet in api.search("elon musk", limit=50, kv={"product": "Top"}):
    print(f"Likes: {tweet.likeCount}")
```

**2. Get User Information**
```python
async def user_by_login(self, login: str, kv: dict = None) -> User | None:
    """Get user by username (e.g., 'elonmusk')"""
    rep = await self.user_by_login_raw(login, kv=kv)
    return parse_user(rep) if rep else None

async def user_by_id(self, uid: int, kv: dict = None) -> User | None:
    """Get user by numeric ID"""
    rep = await self.user_by_id_raw(uid, kv=kv)
    return parse_user(rep) if rep else None
```

**Example**:
```python
# Get user by username
user = await api.user_by_login("elonmusk")
print(f"Followers: {user.followersCount}")

# Get user by ID
user = await api.user_by_id(44196397)
print(f"Username: {user.username}")
```

**3. Get Tweet Details**
```python
async def tweet_details(self, twid: int, kv: dict = None) -> Tweet | None:
    """Get single tweet by ID"""
    rep = await self.tweet_details_raw(twid, kv=kv)
    return parse_tweet(rep, twid) if rep else None
```

**4. Get User's Tweets**
```python
async def user_tweets(self, uid: int, limit=-1, kv: dict = None):
    """Get tweets from a user (no replies/retweets)"""
    async with aclosing(self.user_tweets_raw(uid, limit=limit, kv=kv)) as gen:
        async for rep in gen:
            for tweet in parse_tweets(rep.json(), limit):
                yield tweet

async def user_tweets_and_replies(self, uid: int, limit=-1, kv: dict = None):
    """Get tweets AND replies from a user"""
    # Similar to user_tweets but different endpoint
```

**5. Get Followers/Following**
```python
async def followers(self, uid: int, limit=-1, kv: dict = None):
    """Get user's followers"""
    async with aclosing(self.followers_raw(uid, limit=limit, kv=kv)) as gen:
        async for rep in gen:
            for user in parse_users(rep.json(), limit):
                yield user

async def following(self, uid: int, limit=-1, kv: dict = None):
    """Get users that user follows"""
    # Similar pattern
```

**6. Get Tweet Interactions**
```python
async def retweeters(self, twid: int, limit=-1, kv: dict = None):
    """Get users who retweeted a tweet"""
    async with aclosing(self.retweeters_raw(twid, limit=limit, kv=kv)) as gen:
        async for rep in gen:
            for user in parse_users(rep.json(), limit):
                yield user

async def tweet_replies(self, twid: int, limit=-1, kv: dict = None):
    """Get replies to a tweet"""
    async with aclosing(self.tweet_replies_raw(twid, limit=limit, kv=kv)) as gen:
        async for rep in gen:
            for tweet in parse_tweets(rep.json(), limit):
                if tweet.inReplyToTweetId == twid:
                    yield tweet
```

#### Helper Methods:

**1. `_gql_items()` - Paginated GraphQL Requests**

This is the **core method** that handles pagination:

```python
async def _gql_items(self, op: str, kv: dict, ft: dict = None, limit=-1):
    """
    Make paginated GraphQL requests
    
    Args:
        op: Operation ID (e.g., "AIdc203rPpK_k_2KWSdm7g/SearchTimeline")
        kv: Variables (query parameters)
        ft: Features (additional flags)
        limit: Max items to return
    
    Yields:
        HTTP Response objects
    """
    queue = op.split("/")[-1]  # Extract endpoint name
    cur, cnt = None, 0  # Cursor and count
    
    async with QueueClient(self.pool, queue, self.debug, proxy=self.proxy) as client:
        while True:
            # Prepare request parameters
            params = {"variables": kv, "features": {**GQL_FEATURES, **(ft or {})}}
            
            # Add cursor for pagination
            if cur is not None:
                params["variables"]["cursor"] = cur
            
            # Make request
            rep = await client.get(f"{GQL_URL}/{op}", params=encode_params(params))
            if rep is None:
                return
            
            # Extract items and next cursor
            obj = rep.json()
            entries = get_by_path(obj, "entries") or []
            
            # Filter out cursor entries
            entries = [x for x in entries if not x["entryId"].startswith("cursor-")]
            
            # Get next page cursor
            cur = self._get_cursor(obj, "Bottom")
            
            # Check if should continue
            cnt += len(entries)
            should_continue = cur is not None and (limit < 0 or cnt < limit)
            
            if not entries:
                return
            
            yield rep
            
            if not should_continue:
                return
```

**2. `_gql_item()` - Single GraphQL Request**
```python
async def _gql_item(self, op: str, kv: dict, ft: dict = None):
    """Make single (non-paginated) GraphQL request"""
    queue = op.split("/")[-1]
    async with QueueClient(self.pool, queue, self.debug, proxy=self.proxy) as client:
        params = {"variables": kv, "features": {**GQL_FEATURES, **(ft or {})}}
        return await client.get(f"{GQL_URL}/{op}", params=encode_params(params))
```

**Flow Diagram**:
```
User calls api.search("python")
        ↓
search_raw() prepares parameters
        ↓
_gql_items() handles pagination
        ↓
QueueClient gets account and makes request
        ↓
Response parsed by parse_tweets()
        ↓
Tweet objects yielded to user
```

**Complete Usage Example**:
```python
import asyncio
from twscrape import API, gather

async def main():
    api = API()  # Uses accounts.db
    
    # Search for tweets
    tweets = await gather(api.search("python", limit=20))
    for tweet in tweets:
        print(f"{tweet.user.username}: {tweet.rawContent}")
    
    # Get user info
    user = await api.user_by_login("elonmusk")
    print(f"Followers: {user.followersCount}")
    
    # Get user's tweets
    async for tweet in api.user_tweets(user.id, limit=10):
        print(f"{tweet.date}: {tweet.rawContent}")
    
    # Get followers
    async for follower in api.followers(user.id, limit=50):
        print(f"Follower: {follower.username}")

asyncio.run(main())
```

---

### 8️⃣ **twscrape/login.py** - Twitter Login Flow

This file handles the complex Twitter login process, including 2FA and email verification.

#### Login Flow Overview:

```
1. Get guest token
2. Initiate login
3. Enter username
4. Enter password
5. [Optional] Handle 2FA
6. [Optional] Verify email
7. Success - save cookies
```

#### Key Components:

**1. LoginConfig**
```python
@dataclass
class LoginConfig:
    email_first: bool = False  # Pre-login to email before starting
    manual: bool = False       # Manually enter verification codes
```

**2. TaskCtx - Login Context**
```python
@dataclass
class TaskCtx:
    client: AsyncClient           # HTTP client
    acc: Account                  # Account being logged in
    cfg: LoginConfig              # Configuration
    prev: Any                     # Previous response
    imap: imaplib.IMAP4_SSL | None  # Email connection
```

**3. Login Steps**

Each step is a separate async function:

```python
async def get_guest_token(client: AsyncClient):
    """Get temporary guest token to start login"""
    rep = await client.post("https://api.x.com/1.1/guest/activate.json")
    rep.raise_for_status()
    return rep.json()["guest_token"]

async def login_initiate(client: AsyncClient) -> Response:
    """Start login flow"""
    payload = {
        "input_flow_data": {
            "flow_context": {
                "debug_overrides": {},
                "start_location": {"location": "unknown"}
            }
        },
        "subtask_versions": {},
    }
    rep = await client.post(LOGIN_URL, params={"flow_name": "login"}, json=payload)
    return rep

async def login_enter_username(ctx: TaskCtx) -> Response:
    """Submit username"""
    payload = {
        "flow_token": ctx.prev["flow_token"],
        "subtask_inputs": [{
            "subtask_id": "LoginEnterUserIdentifierSSO",
            "settings_list": {
                "setting_responses": [{
                    "key": "user_identifier",
                    "response_data": {"text_data": {"result": ctx.acc.username}}
                }],
                "link": "next_link",
            }
        }]
    }
    rep = await ctx.client.post(LOGIN_URL, json=payload)
    return rep

async def login_enter_password(ctx: TaskCtx) -> Response:
    """Submit password"""
    payload = {
        "flow_token": ctx.prev["flow_token"],
        "subtask_inputs": [{
            "subtask_id": "LoginEnterPassword",
            "enter_password": {
                "password": ctx.acc.password,
                "link": "next_link"
            }
        }]
    }
    rep = await ctx.client.post(LOGIN_URL, json=payload)
    return rep
```

**4. Two-Factor Authentication**
```python
async def login_two_factor_auth_challenge(ctx: TaskCtx) -> Response:
    """Handle 2FA if enabled"""
    if ctx.acc.mfa_code is None:
        raise ValueError("MFA code is required")
    
    # Generate current TOTP code
    totp = pyotp.TOTP(ctx.acc.mfa_code)
    current_code = totp.now()  # e.g., "123456"
    
    payload = {
        "flow_token": ctx.prev["flow_token"],
        "subtask_inputs": [{
            "subtask_id": "LoginTwoFactorAuthChallenge",
            "enter_text": {
                "text": current_code,
                "link": "next_link"
            }
        }]
    }
    rep = await ctx.client.post(LOGIN_URL, json=payload)
    return rep
```

**5. Email Verification**
```python
async def login_confirm_email(ctx: TaskCtx) -> Response:
    """Submit email address"""
    payload = {
        "flow_token": ctx.prev["flow_token"],
        "subtask_inputs": [{
            "subtask_id": "LoginAcid",
            "enter_text": {
                "text": ctx.acc.email,
                "link": "next_link"
            }
        }]
    }
    rep = await ctx.client.post(LOGIN_URL, json=payload)
    return rep

async def login_confirm_email_code(ctx: TaskCtx):
    """Submit email verification code"""
    if ctx.cfg.manual:
        # Manual entry
        print(f"Enter email code for {ctx.acc.username}")
        value = input("Code: ").strip()
    else:
        # Automatic via IMAP
        if not ctx.imap:
            ctx.imap = await imap_login(ctx.acc.email, ctx.acc.email_password)
        
        now_time = utc.now() - timedelta(seconds=30)
        value = await imap_get_email_code(ctx.imap, ctx.acc.email, now_time)
    
    payload = {
        "flow_token": ctx.prev["flow_token"],
        "subtask_inputs": [{
            "subtask_id": "LoginAcid",
            "enter_text": {"text": value, "link": "next_link"}
        }]
    }
    rep = await ctx.client.post(LOGIN_URL, json=payload)
    return rep
```

**6. Task Router - `next_login_task()`**

This is the **brain** that decides which step to execute next:

```python
async def next_login_task(ctx: TaskCtx, rep: Response):
    """Route to next login step based on response"""
    
    # Update CSRF token if present
    ct0 = ctx.client.cookies.get("ct0", None)
    if ct0:
        ctx.client.headers["x-csrf-token"] = ct0
        ctx.client.headers["x-twitter-auth-type"] = "OAuth2Session"
    
    ctx.prev = rep.json()
    
    # Check each subtask and route accordingly
    for x in ctx.prev["subtasks"]:
        task_id = x["subtask_id"]
        
        try:
            if task_id == "LoginSuccessSubtask":
                return await login_success(ctx)
            
            if task_id == "LoginAcid":
                # Check if email or code
                is_code = x["enter_text"]["hint_text"].lower() == "confirmation code"
                fn = login_confirm_email_code if is_code else login_confirm_email
                return await fn(ctx)
            
            if task_id == "AccountDuplicationCheck":
                return await login_duplication_check(ctx)
            
            if task_id == "LoginEnterPassword":
                return await login_enter_password(ctx)
            
            if task_id == "LoginTwoFactorAuthChallenge":
                return await login_two_factor_auth_challenge(ctx)
            
            if task_id == "LoginEnterUserIdentifierSSO":
                return await login_enter_username(ctx)
            
            if task_id == "LoginJsInstrumentationSubtask":
                return await login_instrumentation(ctx)
            
            if task_id == "LoginEnterAlternateIdentifierSubtask":
                return await login_alternate_identifier(ctx, username=ctx.acc.username)
        
        except Exception as e:
            ctx.acc.error_msg = f"login_step={task_id} err={e}"
            raise e
    
    return None
```

**7. Main Login Function**
```python
async def login(acc: Account, cfg: LoginConfig | None = None) -> Account:
    """
    Complete login flow
    
    Returns:
        Account with updated cookies and headers
    """
    if acc.active:
        logger.info(f"Account already active {acc.username}")
        return acc
    
    cfg = cfg or LoginConfig()
    
    # Pre-login to email if configured
    imap = None
    if cfg.email_first and not cfg.manual:
        imap = await imap_login(acc.email, acc.email_password)
    
    async with acc.make_client() as client:
        # Get guest token
        guest_token = await get_guest_token(client)
        client.headers["x-guest-token"] = guest_token
        
        # Initiate login
        rep = await login_initiate(client)
        ctx = TaskCtx(client, acc, cfg, None, imap)
        
        # Execute login steps
        while True:
            rep = await next_login_task(ctx, rep)
            if not rep:
                break
        
        # Verify success
        assert "ct0" in client.cookies, "ct0 not in cookies (likely IP ban)"
        
        # Update account with session data
        client.headers["x-csrf-token"] = client.cookies["ct0"]
        client.headers["x-twitter-auth-type"] = "OAuth2Session"
        
        acc.active = True
        acc.headers = {k: v for k, v in client.headers.items()}
        acc.cookies = {k: v for k, v in client.cookies.items()}
        
        return acc
```

**Login Flow Diagram**:
```
Start
  ↓
Get guest token
  ↓
Initiate login → Get flow_token
  ↓
Enter username → Get next subtask
  ↓
┌─── Is it password? → Enter password
│         ↓
│    Is it 2FA? → Generate & submit TOTP code
│         ↓
│    Is it email? → Submit email address
│         ↓
│    Is it code? → Get code from IMAP/manual → Submit code
│         ↓
└─── Loop until LoginSuccessSubtask
  ↓
Extract cookies (ct0, auth_token)
  ↓
Save to account
  ↓
Done
```

**Usage Example**:
```python
from twscrape import Account
from twscrape.login import login, LoginConfig

# Create account
acc = Account(
    username="user1",
    password="pass123",
    email="user1@gmail.com",
    email_password="emailpass",
    user_agent="Mozilla/5.0...",
    active=False,
    locks={},
    stats={},
    headers={},
    cookies={}
)

# Login with automatic email verification
await login(acc)

# Or login with manual email code entry
config = LoginConfig(manual=True)
await login(acc, cfg=config)

# Account now has cookies and can make requests
print(acc.cookies["ct0"])  # CSRF token
print(acc.cookies["auth_token"])  # Session token
```

---

### 9️⃣ **twscrape/utils.py** - Utility Functions

This file contains helper functions used throughout the codebase.

#### Key Components:

**1. UTC Time Utilities**
```python
class utc:
    """Helper for UTC datetime operations"""
    
    @staticmethod
    def now() -> datetime:
        """Get current time in UTC"""
        return datetime.now(timezone.utc)
    
    @staticmethod
    def from_iso(iso: str) -> datetime:
        """Parse ISO datetime string"""
        return datetime.fromisoformat(iso).replace(tzinfo=timezone.utc)
    
    @staticmethod
    def ts() -> int:
        """Get current Unix timestamp"""
        return int(utc.now().timestamp())
```

**Usage**:
```python
# Get current time
now = utc.now()  # datetime(2024, 11, 29, 0, 30, 0, tzinfo=timezone.utc)

# Parse ISO string
dt = utc.from_iso("2024-11-29T00:30:00")

# Get timestamp
timestamp = utc.ts()  # 1732843800
```

**2. Async Gather**
```python
async def gather(gen: AsyncGenerator[T, None]) -> list[T]:
    """Collect all items from async generator into list"""
    items = []
    async for x in gen:
        items.append(x)
    return items
```

**Usage**:
```python
# Instead of:
tweets = []
async for tweet in api.search("python"):
    tweets.append(tweet)

# Use:
tweets = await gather(api.search("python"))
```

**3. Encode Parameters**
```python
def encode_params(obj: dict):
    """
    Encode dict parameters for URL query string
    Converts nested dicts to JSON strings
    """
    res = {}
    for k, v in obj.items():
        if isinstance(v, dict):
            # Remove None values
            v = {a: b for a, b in v.items() if b is not None}
            # Convert to compact JSON
            v = json.dumps(v, separators=(",", ":"))
        
        res[k] = str(v)
    
    return res
```

**Usage**:
```python
params = {
    "variables": {"userId": "123", "count": 20},
    "features": {"enabled": True}
}

encoded = encode_params(params)
# {
#   "variables": '{"userId":"123","count":20}',
#   "features": '{"enabled":true}'
# }
```

**4. Dictionary Navigation**
```python
def get_or(obj: dict, key: str, default_value=None):
    """
    Get nested dictionary value using dot notation
    
    Example:
        get_or({"a": {"b": {"c": 123}}}, "a.b.c") → 123
        get_or({"a": {"b": 1}}, "a.x.y", 0) → 0
    """
    for part in key.split("."):
        if part not in obj:
            return default_value
        obj = obj[part]
    return obj

def get_by_path(obj: dict, key: str, default=None):
    """
    Search for key anywhere in nested dict/list structure
    
    Example:
        get_by_path({"data": {"entries": [...]}}, "entries") → [...]
    """
    stack = [iter(obj.items())]
    while stack:
        for k, v in stack[-1]:
            if k == key:
                return v
            elif isinstance(v, dict):
                stack.append(iter(v.items()))
                break
            elif isinstance(v, list):
                stack.append(iter(enumerate(v)))
                break
        else:
            stack.pop()
    return default
```

**5. Find Functions**
```python
def find_item(lst: list[T], fn: Callable[[T], bool]) -> T | None:
    """Find first item in list matching predicate"""
    for item in lst:
        if fn(item):
            return item
    return None

def find_obj(obj: dict, fn: Callable[[dict], bool]) -> Any | None:
    """Find first dict in nested structure matching predicate"""
    if not isinstance(obj, dict):
        return None
    
    if fn(obj):
        return obj
    
    # Recursively search
    for _, v in obj.items():
        if isinstance(v, dict):
            if res := find_obj(v, fn):
                return res
        elif isinstance(v, list):
            for x in v:
                if res := find_obj(x, fn):
                    return res
    
    return None
```

**Usage**:
```python
# Find user with specific ID
users = [{"id": 1, "name": "Alice"}, {"id": 2, "name": "Bob"}]
user = find_item(users, lambda x: x["id"] == 2)  # {"id": 2, "name": "Bob"}

# Find dict with cursorType="Bottom"
data = {"data": {"cursor": {"cursorType": "Bottom", "value": "abc"}}}
cursor = find_obj(data, lambda x: x.get("cursorType") == "Bottom")
# {"cursorType": "Bottom", "value": "abc"}
```

**6. Parse Cookies**
```python
def parse_cookies(val: str) -> dict[str, str]:
    """
    Parse cookies from various formats:
    - "key1=value1; key2=value2"
    - '{"key1": "value1", "key2": "value2"}'
    - '[{"name": "key1", "value": "value1"}, ...]'
    - Base64 encoded versions
    """
    # Try decode from base64
    try:
        val = base64.b64decode(val).decode()
    except Exception:
        pass
    
    try:
        # Try JSON parse
        res = json.loads(val)
        
        if isinstance(res, dict) and "cookies" in res:
            res = res["cookies"]
        
        if isinstance(res, list):
            # Chrome extension format
            return {x["name"]: x["value"] for x in res}
        
        if isinstance(res, dict):
            return res
    except json.JSONDecodeError:
        # Parse as "key=value; key=value"
        res = val.split("; ")
        res = [x.split("=") for x in res]
        return {x[0]: x[1] for x in res}
    
    raise ValueError(f"Invalid cookie value: {val}")
```

**7. Print Table**
```python
def print_table(rows: list[dict], hr_after=False):
    """Print list of dicts as formatted table"""
    if not rows:
        return
    
    keys = list(rows[0].keys())
    
    # Calculate column widths
    rows_with_header = [{k: k for k in keys}, *rows]
    colw = [max(len(str(x[k])) for x in rows_with_header) + 1 for k in keys]
    
    # Print rows
    for row in rows_with_header:
        line = [f"{str(row[k]):<{colw[i]}}" for i, k in enumerate(keys)]
        print(" ".join(line))
```

**Usage**:
```python
accounts = [
    {"username": "user1", "active": True, "requests": 100},
    {"username": "user2", "active": False, "requests": 50}
]

print_table(accounts)
# Output:
# username  active  requests
# user1     True    100
# user2     False   50
```

---

### 🔟 **twscrape/imap.py** - Email Verification via IMAP

This file handles automatic email verification by connecting to email servers via IMAP protocol.

#### Key Components:

**1. IMAP Server Mapping**
```python
IMAP_MAPPING: dict[str, str] = {
    "yahoo.com": "imap.mail.yahoo.com",
    "icloud.com": "imap.mail.me.com",
    "outlook.com": "imap-mail.outlook.com",
    "hotmail.com": "imap-mail.outlook.com",
}

def _get_imap_domain(email: str) -> str:
    """Get IMAP server for email provider"""
    email_domain = email.split("@")[1]
    if email_domain in IMAP_MAPPING:
        return IMAP_MAPPING[email_domain]
    # Default pattern: imap.{domain}
    return f"imap.{email_domain}"
```

**Example**:
```python
# Gmail
_get_imap_domain("user@gmail.com")  # → "imap.gmail.com"

# Yahoo
_get_imap_domain("user@yahoo.com")  # → "imap.mail.yahoo.com"

# Add custom mapping
add_imap_mapping("custom.com", "mail.custom.com")
```

**2. IMAP Login**
```python
async def imap_login(email: str, password: str):
    """
    Login to email account via IMAP
    
    Returns:
        imaplib.IMAP4_SSL connection
    """
    domain = _get_imap_domain(email)
    imap = imaplib.IMAP4_SSL(domain)
    
    try:
        imap.login(email, password)
        imap.select("INBOX", readonly=True)
    except imaplib.IMAP4.error as e:
        logger.error(f"Error logging into {email} on {domain}: {e}")
        raise EmailLoginError() from e
    
    return imap
```

**3. Get Email Verification Code**
```python
def _wait_email_code(imap: imaplib.IMAP4_SSL, count: int, min_t: datetime | None) -> str | None:
    """
    Search through emails for Twitter verification code
    
    Args:
        imap: IMAP connection
        count: Number of emails to check
        min_t: Minimum timestamp (only check emails after this)
    
    Returns:
        Verification code or None
    """
    # Check emails from newest to oldest
    for i in range(count, 0, -1):
        _, rep = imap.fetch(str(i), "(RFC822)")
        
        for x in rep:
            if isinstance(x, tuple):
                msg = emaillib.message_from_bytes(x[1])
                
                # Parse email metadata
                msg_time = msg.get("Date", "").split("(")[0].strip()
                msg_time = datetime.strptime(msg_time, "%a, %d %b %Y %H:%M:%S %z")
                
                msg_from = str(msg.get("From", "")).lower()
                msg_subj = str(msg.get("Subject", "")).lower()
                
                # Skip old emails
                if min_t is not None and msg_time < min_t:
                    return None
                
                # Look for Twitter verification email
                if "info@x.com" in msg_from and "confirmation code is" in msg_subj:
                    # Subject: "Your Twitter confirmation code is 123456"
                    return msg_subj.split(" ")[-1].strip()
    
    return None

async def imap_get_email_code(
    imap: imaplib.IMAP4_SSL, 
    email: str, 
    min_t: datetime | None = None
) -> str:
    """
    Wait for and retrieve Twitter verification code from email
    
    Args:
        imap: IMAP connection
        email: Email address (for logging)
        min_t: Only check emails after this time
    
    Returns:
        Verification code
    
    Raises:
        EmailCodeTimeoutError: If code not received within timeout
    """
    logger.info(f"Waiting for confirmation code for {email}...")
    start_time = time.time()
    
    while True:
        # Get message count
        _, rep = imap.select("INBOX")
        msg_count = int(rep[0].decode("utf-8")) if rep[0] else 0
        
        # Check for code
        code = _wait_email_code(imap, msg_count, min_t)
        if code is not None:
            return code
        
        # Check timeout (default 30 seconds)
        if TWS_WAIT_EMAIL_CODE < time.time() - start_time:
            raise EmailCodeTimeoutError(f"Email code timeout ({TWS_WAIT_EMAIL_CODE} sec)")
        
        await asyncio.sleep(5)  # Wait 5 seconds before checking again
```

**Configuration**:
```python
# Set timeout via environment variable
# TWS_WAIT_EMAIL_CODE=60 python script.py

TWS_WAIT_EMAIL_CODE = env_int(["TWS_WAIT_EMAIL_CODE", "LOGIN_CODE_TIMEOUT"], 30)
```

**Usage Example**:
```python
# Login to email
imap = await imap_login("user@gmail.com", "email_password")

# Wait for verification code
now = utc.now() - timedelta(seconds=30)
code = await imap_get_email_code(imap, "user@gmail.com", min_t=now)
print(f"Code: {code}")  # e.g., "123456"
```

**How it works**:
```
1. Connect to IMAP server
2. Select INBOX
3. Check emails every 5 seconds
4. Look for email from info@x.com with "confirmation code is" in subject
5. Extract code from subject line
6. Return code or timeout after 30 seconds
```

---

### 1️⃣1️⃣ **twscrape/xclid.py** - X-Client-Transaction-ID Generator

This is the **most complex file** in the project. It generates the special `x-client-transaction-id` header that Twitter requires to prevent bots.

#### What is X-Client-Transaction-ID?

Twitter requires a special header with each API request:
```
x-client-transaction-id: AgABiQgRpVY0OVoI...
```

This ID is calculated using:
1. Request method (GET/POST)
2. Request path
3. Current timestamp
4. Cryptographic keys extracted from Twitter's website
5. Animation frame data from Twitter's loading spinner

**Why is this needed?** Twitter uses this as an anti-bot mechanism. The calculation requires parsing JavaScript, extracting animation data, and performing cryptographic operations.

#### Key Components:

**1. XClIdGen Class**
```python
class XClIdGen:
    def __init__(self, vk_bytes: list[int], anim_key: str):
        self.vk_bytes = vk_bytes     # Verification key bytes
        self.anim_key = anim_key     # Animation key
    
    @staticmethod
    async def create(clt: httpx.AsyncClient | None = None) -> "XClIdGen":
        """
        Create generator by scraping Twitter's website
        
        Process:
        1. Fetch Twitter page (e.g., https://x.com/tesla)
        2. Extract verification bytes from meta tag
        3. Parse JavaScript to find animation indices
        4. Extract SVG animation data
        5. Calculate animation key
        """
        text = await get_tw_page_text("https://x.com/tesla", clt=clt)
        soup = bs4.BeautifulSoup(text, "html.parser")
        
        vk_bytes, anim_key = await load_keys(soup)
        return XClIdGen(vk_bytes, anim_key)
    
    def calc(self, method: str, path: str) -> str:
        """
        Generate transaction ID for specific request
        
        Args:
            method: HTTP method (GET, POST)
            path: API path (e.g., "/i/api/graphql/.../SearchTimeline")
        
        Returns:
            Base64 encoded transaction ID
        """
        # Get timestamp (milliseconds since April 2023)
        ts = math.floor((time.time() * 1000 - 1682924400 * 1000) / 1000)
        ts_bytes = [(ts >> (i * 8)) & 0xFF for i in range(4)]
        
        # Create payload
        dkw, drn = "obfiowerehiring", 3  # Default keyword and random number
        pld = f"{method.upper()}!{path}!{ts}{dkw}{self.anim_key}"
        
        # Hash payload
        pld = list(hashlib.sha256(pld.encode()).digest())
        
        # Combine all components
        pld = [*self.vk_bytes, *ts_bytes, *pld[:16], drn]
        
        # XOR with random number
        num = random.randint(0, 255)
        pld = bytearray([num, *[x ^ num for x in pld]])
        
        # Encode to base64
        out = base64.b64encode(pld).decode("utf-8").strip("=")
        return out
```

**2. Extract Verification Bytes**
```python
def parse_vk_bytes(soup: bs4.BeautifulSoup) -> list[int]:
    """
    Extract verification key from meta tag
    
    HTML:
    <meta name="twitter-site-verification" content="base64string" />
    """
    el = soup.find("meta", {"name": "twitter-site-verification", "content": True})
    el = str(el.get("content")) if el and isinstance(el, bs4.Tag) else None
    if not el:
        raise Exception("Couldn't get XClientTxId key bytes")
    
    return list(base64.b64decode(bytes(el, "utf-8")))
```

**3. Parse Animation Data**
```python
async def parse_anim_idx(text: str) -> list[int]:
    """
    Extract animation indices from JavaScript
    
    Finds patterns like: (a[5], 16)
    Extracts: [5, ...]
    """
    scripts = list(get_scripts_list(text))
    scripts = [x for x in scripts if "/ondemand.s." in x]
    if not scripts:
        raise Exception("Couldn't get XClientTxId scripts")
    
    text = await get_tw_page_text(scripts[0])
    
    # Regex to find animation indices
    items = [int(x.group(2)) for x in INDICES_REGEX.finditer(text)]
    return items

def parse_anim_arr(soup: bs4.BeautifulSoup, vk_bytes: list[int]) -> list[list[float]]:
    """
    Extract animation frame data from SVG
    
    Finds: <svg id='loading-x-anim'><g><path d='M...C...C...' /></g></svg>
    Extracts cubic bezier curve points
    """
    els = list(soup.select("svg[id^='loading-x-anim'] g:first-child path:nth-child(2)"))
    els = [str(x.get("d") or "").strip() for x in els]
    
    idx = vk_bytes[5] % len(els)
    dat = els[idx][9:].split("C")
    arr = [list(map(float, re.sub(r"[^\d]+", " ", x).split())) for x in dat]
    return arr
```

**4. Animation Key Calculation**
```python
def cacl_anim_key(frames: list[float], target_time: float) -> str:
    """
    Calculate animation key from frame data
    
    Uses cubic bezier interpolation to calculate color and rotation
    at specific time in animation
    """
    from_color = [*frames[:3], 1]
    to_color = [*frames[3:6], 1]
    from_rotation = [0.0]
    to_rotation = [solve(frames[6], 60.0, 360.0, True)]
    
    frames = frames[7:]
    curves = [solve(x, -1.0 if i % 2 else 0.0, 1.0, False) for i, x in enumerate(frames)]
    
    # Cubic bezier interpolation
    val = Cubic(curves).get_value(target_time)
    
    color = interpolate(from_color, to_color, val)
    rotation = interpolate(from_rotation, to_rotation, val)
    
    # Convert to hex string
    matrix = get_rotation_matrix(rotation[0])
    str_arr = [format(round(value), "x") for value in color[:-1]]
    for value in matrix:
        rounded = round(value, 2)
        hex_value = float_to_hex(abs(rounded))
        str_arr.append(hex_value if hex_value else "0")
    
    str_arr.extend(["0", "0"])
    return re.sub(r"[.-]", "", "".join(str_arr))
```

**Usage in Queue Client**:
```python
class XClIdGenStore:
    """Cache generators per account"""
    items: dict[str, XClIdGen] = {}
    
    @classmethod
    async def get(cls, username: str, fresh=False) -> XClIdGen:
        if username in cls.items and not fresh:
            return cls.items[username]
        
        # Create new generator (expensive operation)
        clid_gen = await XClIdGen.create()
        cls.items[username] = clid_gen
        return clid_gen

# In request context
gen = await XClIdGenStore.get(account.username)
tx_id = gen.calc("GET", "/i/api/graphql/.../SearchTimeline")

headers = {"x-client-transaction-id": tx_id}
response = await client.get(url, headers=headers)
```

**Algorithm Overview**:
```
1. Fetch Twitter webpage
   ↓
2. Extract <meta name="twitter-site-verification" content="..." />
   ↓
3. Decode base64 → get vk_bytes [int, int, int, ...]
   ↓
4. Find JavaScript with animation indices
   ↓
5. Extract SVG animation data (cubic bezier curves)
   ↓
6. Use vk_bytes to select specific animation frame
   ↓
7. Calculate animation state at specific time
   ↓
8. Generate hex string from colors/rotation → anim_key
   ↓
9. For each request:
   - Combine: method + path + timestamp + anim_key
   - SHA256 hash
   - XOR with random byte
   - Base64 encode
   ↓
10. Result: x-client-transaction-id header
```

**Why so complex?** This is Twitter's anti-bot system. The calculation requires:
- Fetching live data from Twitter's website
- Parsing JavaScript and SVG
- Cryptographic operations
- Mathematical interpolation

The algorithm changes periodically when Twitter updates their website, which is why the code includes fallbacks and error handling.

---

### 1️⃣2️⃣ **twscrape/logger.py** - Logging Configuration

Simple logging setup using the `loguru` library.

```python
from loguru import logger

# Type definition for log levels
_TLOGLEVEL = Literal["TRACE", "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]

def _load_from_env() -> _TLOGLEVEL:
    """Load log level from environment variable"""
    env = os.getenv("TWS_LOG_LEVEL", "INFO").upper()
    if env not in ["TRACE", "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]:
        logger.warning(f"Invalid log level '{env}'. Defaulting to INFO.")
        return "INFO"
    return cast(_TLOGLEVEL, env)

# Global log level
_LOG_LEVEL: _TLOGLEVEL = _load_from_env()

def set_log_level(level: _TLOGLEVEL):
    """Change log level programmatically"""
    global _LOG_LEVEL
    _LOG_LEVEL = level

def _filter(r):
    """Filter log records by level"""
    return r["level"].no >= logger.level(_LOG_LEVEL).no

# Configure logger
logger.remove()  # Remove default handler
logger.add(sys.stderr, filter=_filter)  # Add filtered handler
```

**Usage**:
```python
from twscrape.logger import logger, set_log_level

# Default level is INFO
logger.info("This will show")
logger.debug("This won't show")

# Change level
set_log_level("DEBUG")
logger.debug("Now this shows")

# Or via environment variable
# TWS_LOG_LEVEL=DEBUG python script.py
```

---

### 1️⃣3️⃣ **twscrape/cli.py** - Command-Line Interface

This file provides the `twscrape` command-line tool.

#### Main Commands:

**1. Account Management**
```bash
# Add accounts from file
twscrape add_accounts accounts.txt username:password:email:email_password

# List accounts
twscrape accounts

# Login all accounts
twscrape login_accounts

# Re-login specific accounts
twscrape relogin user1 user2

# Re-login failed accounts
twscrape relogin_failed

# Delete accounts
twscrape del_accounts user1 user2

# Delete inactive accounts
twscrape delete_inactive
```

**2. Statistics**
```bash
# Get pool statistics
twscrape stats

# Output:
# queue                locked  available
# SearchTimeline       2       8
# UserTweets          1       9
# Total: 10 - Active: 10 - Inactive: 0
```

**3. Search & Data Retrieval**
```bash
# Search tweets
twscrape search "python programming" --limit 100

# Get user info
twscrape user_by_login elonmusk
twscrape user_by_id 44196397

# Get tweet details
twscrape tweet_details 1234567890

# Get user's tweets
twscrape user_tweets 44196397 --limit 50

# Get followers
twscrape followers 44196397 --limit 100

# Get raw JSON response
twscrape search "python" --limit 10 --raw
```

**4. Other Commands**
```bash
# Show version
twscrape version

# Reset all locks (if accounts stuck)
twscrape reset_locks

# Use different database
twscrape --db custom.db accounts
```

#### Code Structure:

**Command Handler**:
```python
async def main(args):
    """Main command handler"""
    
    # Setup
    if args.debug:
        set_log_level("DEBUG")
    
    pool = AccountsPool(args.db)
    api = API(pool, debug=args.debug)
    
    # Route to specific command
    if args.command == "accounts":
        print_table([dict(x) for x in await pool.accounts_info()])
        return
    
    if args.command == "search":
        # Get function (search or search_raw)
        fn = api.search_raw if args.raw else api.search
        
        # Execute and print results
        async for doc in fn(args.query, limit=args.limit):
            print(to_str(doc))
        return
    
    # ... more commands
```

**Argument Parser**:
```python
def run():
    """Entry point for CLI"""
    p = argparse.ArgumentParser()
    p.add_argument("--db", default="accounts.db")
    p.add_argument("--debug", action="store_true")
    
    subparsers = p.add_subparsers(dest="command")
    
    # Define commands
    subparsers.add_parser("accounts", help="List all accounts")
    
    search = subparsers.add_parser("search", help="Search for tweets")
    search.add_argument("query", help="Search query")
    search.add_argument("--limit", type=int, default=-1)
    search.add_argument("--raw", action="store_true")
    
    # ... more commands
    
    args = p.parse_args()
    asyncio.run(main(args))
```

---

## 📊 Complete System Flow

Now let's see how everything works together:

### Example: Searching for Tweets

```
User runs: twscrape search "python" --limit 20

1. cli.py
   ↓ Parse arguments
   ↓ Create API instance
   ↓ Call api.search("python", limit=20)

2. api.py
   ↓ search() calls search_raw()
   ↓ search_raw() calls _gql_items()
   ↓ _gql_items() creates QueueClient

3. queue_client.py
   ↓ QueueClient.__aenter__()
   ↓ _get_ctx() gets account from pool
   
4. accounts_pool.py
   ↓ get_for_queue_or_wait("SearchTimeline")
   ↓ Find unlocked account in database
   ↓ Lock account for 15 minutes
   ↓ Return Account object

5. account.py
   ↓ make_client() creates HTTP client
   ↓ Set headers, cookies, proxy
   
6. queue_client.py (Ctx)
   ↓ req() generates x-client-transaction-id
   
7. xclid.py
   ↓ XClIdGen.calc(method, path)
   ↓ Calculate transaction ID
   
8. queue_client.py
   ↓ Make HTTP request to Twitter
   ↓ Receive response
   ↓ _check_rep() validates response
   
9. models.py
   ↓ parse_tweets() parses JSON
   ↓ to_old_rep() normalizes structure
   ↓ Tweet.parse() creates objects
   
10. Back to user
    ↓ Print tweets to console
```

### Example: Login Flow

```
User runs: twscrape login_accounts

1. cli.py
   ↓ main() calls pool.login_all()

2. accounts_pool.py
   ↓ Get all inactive accounts from database
   ↓ For each account, call login()

3. login.py
   ↓ get_guest_token()
   ↓ login_initiate()
   ↓ next_login_task() router
   ↓   → login_enter_username()
   ↓   → login_enter_password()
   ↓   → login_confirm_email()
   
4. imap.py (if needed)
   ↓ imap_login(email, password)
   ↓ imap_get_email_code()
   ↓ Wait for email with code
   ↓ Return code to login.py

5. login.py (continued)
   ↓ login_confirm_email_code(code)
   ↓ login_success()
   ↓ Extract cookies (ct0, auth_token)
   
6. account.py
   ↓ Update account.cookies
   ↓ Update account.headers
   ↓ Set account.active = True

7. accounts_pool.py
   ↓ save(account) to database
   ↓ Account ready for use!
```

---

## 🎓 Key Concepts Summary

### 1. **Account Pool System**
- Multiple Twitter accounts stored in SQLite database
- Accounts rotated automatically when rate limited
- Each account tracks usage per API endpoint
- Locks prevent concurrent use of same account

### 2. **Rate Limit Handling**
- Twitter limits requests per 15-minute window
- System locks accounts when rate limited
- Automatically switches to next available account
- Waits if all accounts are locked

### 3. **Authentication Flow**
- Login via Twitter's multi-step process
- Handles username, password, 2FA, email verification
- Session stored as cookies in database
- Cookies reused for future requests

### 4. **Anti-Bot Measures**
- x-client-transaction-id header required
- Calculated from website animation data
- Changes with each request
- Regenerated if Twitter updates website

### 5. **Data Parsing**
- Twitter returns nested GraphQL JSON
- Normalized to flat structure
- Converted to Python objects (Tweet, User)
- Handles quotes, retweets, media, cards

---

## 💡 Usage Examples

### Basic Search
```python
import asyncio
from twscrape import API, gather

async def main():
    api = API()
    
    tweets = await gather(api.search("python", limit=20))
    for tweet in tweets:
        print(f"{tweet.user.username}: {tweet.rawContent}")

asyncio.run(main())
```

### Get User Info
```python
user = await api.user_by_login("elonmusk")
print(f"Followers: {user.followersCount:,}")
print(f"Joined: {user.created}")
```

### Stream Tweets
```python
async for tweet in api.search("bitcoin", limit=100):
    if tweet.likeCount > 100:
        print(f"Popular tweet: {tweet.url}")
```

### Get User's Tweets
```python
user = await api.user_by_login("nasa")
async for tweet in api.user_tweets(user.id, limit=50):
    if tweet.media and tweet.media.photos:
        print(f"Tweet with photo: {tweet.url}")
```

---

## 🔧 Configuration

### Environment Variables
```bash
# Database file
TWS_DB="accounts.db"

# Global proxy
TWS_PROXY="socks5://user:pass@127.0.0.1:1080"

# Log level
TWS_LOG_LEVEL="DEBUG"

# Email code timeout (seconds)
TWS_WAIT_EMAIL_CODE=60

# Raise exception when no accounts available
TWS_RAISE_WHEN_NO_ACCOUNT=true
```

### Programmatic Configuration
```python
from twscrape import API, AccountsPool
from twscrape.logger import set_log_level

# Custom database
api = API(pool="custom.db")

# With proxy
api = API(proxy="http://proxy.com:8080")

# Debug mode
api = API(debug=True)
set_log_level("DEBUG")

# Raise when no account
pool = AccountsPool(raise_when_no_account=True)
api = API(pool=pool)
```

---

## 🏁 Conclusion

This codebase is a sophisticated Twitter scraping system that:

1. **Manages multiple accounts** with automatic rotation
2. **Handles rate limits** by switching between accounts
3. **Bypasses anti-bot measures** with cryptographic calculations
4. **Automates login** including 2FA and email verification
5. **Parses complex data** into clean Python objects
6. **Provides simple API** for users while handling complexity internally

The key to understanding this codebase is recognizing the separation of concerns:
- **account.py** - Data structure
- **db.py** - Storage
- **accounts_pool.py** - Account management
- **queue_client.py** - Request handling
- **api.py** - User interface
- **models.py** - Data parsing
- **login.py** - Authentication
- **xclid.py** - Anti-bot bypass

Each file has a specific responsibility, and they work together to create a robust Twitter scraping system.
