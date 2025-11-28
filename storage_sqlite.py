#!/usr/bin/env python3
"""
SQLite Storage for Scraped Data
Stores tweets with rich metadata in a local database
"""

import sqlite3
import contextlib
import datetime as dt
from typing import List, Optional, Dict, Any
from pathlib import Path
import json


# Timezone-aware timestamp adapter
def tz_aware_timestamp_adapter(val):
    datepart, timepart = val.split(b" ")
    year, month, day = map(int, datepart.split(b"-"))

    if b"+" in timepart:
        timepart, tz_offset = timepart.rsplit(b"+", 1)
        if tz_offset == b"00:00":
            tzinfo = dt.timezone.utc
        else:
            hours, minutes = map(int, tz_offset.split(b":", 1))
            tzinfo = dt.timezone(dt.timedelta(hours=hours, minutes=minutes))
    elif b"-" in timepart:
        timepart, tz_offset = timepart.rsplit(b"-", 1)
        if tz_offset == b"00:00":
            tzinfo = dt.timezone.utc
        else:
            hours, minutes = map(int, tz_offset.split(b":", 1))
            tzinfo = dt.timezone(dt.timedelta(hours=-hours, minutes=-minutes))
    else:
        tzinfo = dt.timezone.utc

    timepart_full = timepart.split(b".")
    hours, minutes, seconds = map(int, timepart_full[0].split(b":"))

    if len(timepart_full) == 2:
        microseconds = int("{:0<6.6}".format(timepart_full[1].decode()))
    else:
        microseconds = 0

    val = dt.datetime(year, month, day, hours, minutes, seconds, microseconds, tzinfo)
    return val


class TweetStorage:
    """SQLite storage for scraped tweets"""
    
    # Table schema
    TABLE_CREATE = """CREATE TABLE IF NOT EXISTS tweets (
        tweet_id            TEXT            PRIMARY KEY,
        url                 TEXT            NOT NULL,
        username            TEXT            NOT NULL,
        user_id             TEXT                    ,
        user_display_name   TEXT                    ,
        text                TEXT            NOT NULL,
        timestamp           TIMESTAMP(6)    NOT NULL,
        source              INTEGER         NOT NULL,
        job_label           TEXT                    ,
        job_keyword         TEXT                    ,
        
        -- Tweet metadata
        language            TEXT                    ,
        is_reply            INTEGER                 ,
        is_retweet          INTEGER                 ,
        is_quote            INTEGER                 ,
        in_reply_to_user_id TEXT                    ,
        in_reply_to_username TEXT                   ,
        quoted_tweet_id     TEXT                    ,
        conversation_id     TEXT                    ,
        
        -- Engagement metrics
        like_count          INTEGER                 ,
        retweet_count       INTEGER                 ,
        reply_count         INTEGER                 ,
        quote_count         INTEGER                 ,
        view_count          INTEGER                 ,
        bookmark_count      INTEGER                 ,
        
        -- User profile
        user_verified       INTEGER                 ,
        user_blue_verified  INTEGER                 ,
        user_description    TEXT                    ,
        user_location       TEXT                    ,
        user_followers_count INTEGER                ,
        user_following_count INTEGER                ,
        profile_image_url   TEXT                    ,
        
        -- Arrays stored as JSON
        hashtags            TEXT                    ,
        media_urls          TEXT                    ,
        
        -- Metadata
        scraped_at          TIMESTAMP(6)    NOT NULL,
        content_size_bytes  INTEGER         NOT NULL
    ) WITHOUT ROWID"""
    
    # Indexes for efficient queries
    INDEXES = [
        "CREATE INDEX IF NOT EXISTS idx_timestamp ON tweets(timestamp)",
        "CREATE INDEX IF NOT EXISTS idx_username ON tweets(username)",
        "CREATE INDEX IF NOT EXISTS idx_job_label ON tweets(job_label)",
        "CREATE INDEX IF NOT EXISTS idx_source ON tweets(source)",
        "CREATE INDEX IF NOT EXISTS idx_scraped_at ON tweets(scraped_at)",
    ]
    
    def __init__(self, database_path: str = "tweets.db"):
        """Initialize database connection"""
        sqlite3.register_converter("timestamp", tz_aware_timestamp_adapter)
        self.database_path = database_path
        
        # Create database and tables
        with contextlib.closing(self._create_connection()) as conn:
            cursor = conn.cursor()
            cursor.execute(self.TABLE_CREATE)
            
            for index_sql in self.INDEXES:
                cursor.execute(index_sql)
            
            # Enable WAL mode for better concurrency
            cursor.execute("PRAGMA journal_mode=WAL")
            conn.commit()
    
    def _create_connection(self):
        """Create database connection"""
        connection = sqlite3.connect(
            self.database_path,
            detect_types=sqlite3.PARSE_DECLTYPES,
            timeout=60.0
        )
        connection.row_factory = sqlite3.Row
        return connection
    
    def store_tweet(self, tweet_data: Dict[str, Any]) -> bool:
        """Store a single tweet - stores ALL tweets even if optional fields are missing"""
        try:
            # Validate required fields only
            required_fields = ['id', 'url', 'username', 'text', 'timestamp']
            for field in required_fields:
                if field not in tweet_data or tweet_data[field] is None:
                    print(f"Warning: Required field '{field}' missing for tweet. Skipping.")
                    return False
            
            with contextlib.closing(self._create_connection()) as conn:
                cursor = conn.cursor()
                
                # Prepare data - use .get() with None default for all optional fields
                values = (
                    str(tweet_data['id']),  # Required
                    tweet_data['url'],  # Required
                    tweet_data['username'],  # Required
                    tweet_data.get('user_id'),  # Optional
                    tweet_data.get('user_display_name'),  # Optional
                    tweet_data['text'],  # Required
                    tweet_data['timestamp'],  # Required
                    tweet_data.get('source', 2),  # Default to 2 = X/Twitter
                    tweet_data.get('job_label'),  # Optional
                    tweet_data.get('job_keyword'),  # Optional
                    tweet_data.get('language'),  # Optional
                    1 if tweet_data.get('is_reply') else 0 if tweet_data.get('is_reply') is not None else None,
                    1 if tweet_data.get('is_retweet') else 0 if tweet_data.get('is_retweet') is not None else None,
                    1 if tweet_data.get('is_quote') else 0 if tweet_data.get('is_quote') is not None else None,
                    tweet_data.get('in_reply_to_user_id'),  # Optional
                    tweet_data.get('in_reply_to_username'),  # Optional
                    tweet_data.get('quoted_tweet_id'),  # Optional
                    tweet_data.get('conversation_id'),  # Optional
                    tweet_data.get('like_count'),  # Optional
                    tweet_data.get('retweet_count'),  # Optional
                    tweet_data.get('reply_count'),  # Optional
                    tweet_data.get('quote_count'),  # Optional
                    tweet_data.get('view_count'),  # Optional
                    tweet_data.get('bookmark_count'),  # Optional
                    1 if tweet_data.get('user_verified') else 0 if tweet_data.get('user_verified') is not None else None,
                    1 if tweet_data.get('user_blue_verified') else 0 if tweet_data.get('user_blue_verified') is not None else None,
                    tweet_data.get('user_description'),  # Optional
                    tweet_data.get('user_location'),  # Optional
                    tweet_data.get('user_followers_count'),  # Optional
                    tweet_data.get('user_following_count'),  # Optional
                    tweet_data.get('profile_image_url'),  # Optional
                    json.dumps(tweet_data.get('hashtags', [])),  # Default to empty list
                    json.dumps(tweet_data.get('media_urls', [])),  # Default to empty list
                    dt.datetime.now(dt.timezone.utc),  # Always set scraped_at
                    len(tweet_data.get('text', '').encode('utf-8')),  # Calculate size
                )
                
                cursor.execute("""
                    REPLACE INTO tweets VALUES (
                        ?,?,?,?,?,?,?,?,?,?,
                        ?,?,?,?,?,?,?,?,?,?,
                        ?,?,?,?,?,?,?,?,?,?,
                        ?,?,?,?,?
                    )
                """, values)
                
                conn.commit()
                return True
        except Exception as e:
            # Log the error but don't stop execution
            print(f"Error storing tweet {tweet_data.get('id', 'UNKNOWN')}: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def store_tweets_batch(self, tweets: List[Dict[str, Any]]) -> int:
        """Store multiple tweets in batch"""
        stored_count = 0
        for tweet in tweets:
            if self.store_tweet(tweet):
                stored_count += 1
        return stored_count
    
    def get_stats(self) -> Dict[str, Any]:
        """Get database statistics"""
        with contextlib.closing(self._create_connection()) as conn:
            cursor = conn.cursor()
            
            # Total tweets
            cursor.execute("SELECT COUNT(*) as count FROM tweets")
            total = cursor.fetchone()['count']
            
            # By job label
            cursor.execute("""
                SELECT job_label, COUNT(*) as count 
                FROM tweets 
                GROUP BY job_label 
                ORDER BY count DESC
            """)
            by_label = {row['job_label']: row['count'] for row in cursor.fetchall()}
            
            # By username
            cursor.execute("""
                SELECT username, COUNT(*) as count 
                FROM tweets 
                GROUP BY username 
                ORDER BY count DESC 
                LIMIT 10
            """)
            top_users = {row['username']: row['count'] for row in cursor.fetchall()}
            
            # Date range
            cursor.execute("SELECT MIN(timestamp) as earliest, MAX(timestamp) as latest FROM tweets")
            dates = cursor.fetchone()
            
            # Storage size
            cursor.execute("SELECT SUM(content_size_bytes) as total_bytes FROM tweets")
            total_bytes = cursor.fetchone()['total_bytes'] or 0
            
            return {
                'total_tweets': total,
                'by_label': by_label,
                'top_users': top_users,
                'earliest_tweet': dates['earliest'],
                'latest_tweet': dates['latest'],
                'total_size_mb': total_bytes / (1024 * 1024),
            }
    
    def query_tweets(
        self,
        label: Optional[str] = None,
        username: Optional[str] = None,
        start_date: Optional[dt.datetime] = None,
        end_date: Optional[dt.datetime] = None,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """Query tweets with filters"""
        with contextlib.closing(self._create_connection()) as conn:
            cursor = conn.cursor()
            
            query = "SELECT * FROM tweets WHERE 1=1"
            params = []
            
            if label:
                query += " AND job_label = ?"
                params.append(label)
            
            if username:
                query += " AND username = ?"
                params.append(username)
            
            if start_date:
                query += " AND timestamp >= ?"
                params.append(start_date)
            
            if end_date:
                query += " AND timestamp <= ?"
                params.append(end_date)
            
            query += " ORDER BY timestamp DESC LIMIT ?"
            params.append(limit)
            
            cursor.execute(query, params)
            
            tweets = []
            for row in cursor.fetchall():
                tweet = dict(row)
                tweet['hashtags'] = json.loads(tweet['hashtags'])
                tweet['media_urls'] = json.loads(tweet['media_urls'])
                tweets.append(tweet)
            
            return tweets


if __name__ == "__main__":
    # Test
    storage = TweetStorage("test_tweets.db")
    
    # Test insert
    test_tweet = {
        'id': '123456789',
        'url': 'https://x.com/test/status/123456789',
        'username': 'testuser',
        'text': 'Test tweet #test',
        'timestamp': dt.datetime.now(dt.timezone.utc),
        'job_label': '#test',
        'hashtags': ['#test'],
    }
    
    storage.store_tweet(test_tweet)
    stats = storage.get_stats()
    print(f"Stats: {stats}")
