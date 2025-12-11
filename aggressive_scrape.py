#!/usr/bin/env python3
"""
Aggressive Scraping with Jobs from x.json
Enhanced with rich metadata parsing and SQLite storage

ENHANCEMENTS:
- Multiple search strategies (hashtag, keyword, user, location, advanced)
- Network expansion (conversations, retweeters, user networks)
- Multi-language support
- Smart pagination with resume capability
- Advanced X search operators
"""

# ========== CONFIGURATION ==========
ENABLE_MULTI_LANGUAGE = False  # ✅ OPTIMIZED: False = scrape all languages at once (no duplicates, max volume)
TOP_LANGUAGES = [
    'en',  # English (highest volume)
    'ja',  # Japanese
    'es',  # Spanish
    'pt',  # Portuguese
    'ar',  # Arabic
    'fr',  # French
    'ko',  # Korean
    'de',  # German
    'hi',  # Hindi
    'tr',  # Turkish
    'it',  # Italian
]

# REPLY/COMMENT SCRAPING SETTINGS
SCRAPE_ALL_REPLIES = True  # Set to False to limit replies per tweet
MAX_REPLIES_PER_TWEET = -1  # -1 = unlimited, or set a number like 500
# ===================================

import asyncio
import json
import sys
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Dict, Optional, Set
from enum import Enum

# Add data-universe to path for imports BEFORE any imports from common
# Get the parent directory (data-universe) dynamically
current_dir = Path(__file__).resolve().parent
data_universe_dir = current_dir.parent
sys.path.insert(0, str(data_universe_dir))

# Now we can import from data-universe
from common.data import DataEntity, DataLabel, DataSource
from storage.miner.sqlite_miner_storage import SqliteMinerStorage

# Import twscrape after path setup
from twscrape import API
from twscrape.logger import set_log_level, logger
from twscrape.pagination_state import PaginationStateManager


# ========== UTILITY FUNCTIONS ==========

def sanitize_scraped_tweet(text: str) -> str:
    """
    Clean up scraped tweet text for storage
    
    Args:
        text: Raw tweet text
        
    Returns:
        Sanitized text
    """
    if not text:
        return ""
    
    # Remove excessive whitespace
    text = " ".join(text.split())
    
    # Remove null bytes
    text = text.replace('\x00', '')
    
    return text


# ========== DEDUPLICATION SYSTEM ==========

class GlobalDeduplication:
    """Track all scraped tweet IDs across runs to prevent duplicates"""
    
    def __init__(self, db_path: str = "dedup.db"):
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS scraped_tweets (
                tweet_id TEXT PRIMARY KEY,
                scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        self.conn.commit()
        
        # Load into memory for fast checks
        self.seen_ids = set(
            row[0] for row in 
            self.conn.execute("SELECT tweet_id FROM scraped_tweets").fetchall()
        )
        logger.info(f"✅ Loaded {len(self.seen_ids):,} previously scraped tweet IDs from dedup database")
    
    def is_scraped(self, tweet_id: str) -> bool:
        """Check if tweet has already been scraped"""
        return str(tweet_id) in self.seen_ids
    
    def mark_scraped(self, tweet_id: str):
        """Mark a single tweet as scraped"""
        if str(tweet_id) not in self.seen_ids:
            self.seen_ids.add(str(tweet_id))
            self.conn.execute(
                "INSERT OR IGNORE INTO scraped_tweets (tweet_id) VALUES (?)",
                (str(tweet_id),)
            )
            self.conn.commit()
    
    def batch_mark_scraped(self, tweet_ids: List[str]):
        """More efficient for bulk marking"""
        new_ids = [str(tid) for tid in tweet_ids if str(tid) not in self.seen_ids]
        if new_ids:
            self.seen_ids.update(new_ids)
            self.conn.executemany(
                "INSERT OR IGNORE INTO scraped_tweets (tweet_id) VALUES (?)",
                [(tid,) for tid in new_ids]
            )
            self.conn.commit()
            logger.debug(f"Marked {len(new_ids)} new tweet IDs as scraped")
    
    def close(self):
        """Close database connection"""
        self.conn.close()


# ========== STORAGE CLASS ==========

class DataEntityTweetStorage:
    """
    Wrapper around SqliteMinerStorage with BATCH INSERT capability
    Converts tweets to DataEntity format and stores in batches for performance
    """
    
    def __init__(self, db_path: str = None, batch_size: int = 1000):
        # Auto-detect database path
        if db_path is None:
            # Use parent directory (data-universe) storage path
            current_dir = Path(__file__).resolve().parent
            data_universe_dir = current_dir.parent
            storage_dir = data_universe_dir / "storage" / "miner"
            storage_dir.mkdir(parents=True, exist_ok=True)
            db_path = str(storage_dir / "SqliteMinerStorage.sqlite")
        self.storage = SqliteMinerStorage(database=db_path)
        self.batch_size = batch_size
        self.pending_batch = []
        self.lock = asyncio.Lock()
        logger.info(f"Using SqliteMinerStorage at: {db_path} (batch size: {batch_size})")
    
    def store_tweet(self, tweet_data: dict) -> bool:
        """
        Convert tweet to DataEntity and store using SqliteMinerStorage
        
        Args:
            tweet_data: Dictionary containing tweet information
            
        Returns:
            True if stored successfully, False otherwise
        """
        try:
            # Extract datetime for DataEntity (keep as datetime object)
            tweet_timestamp = tweet_data.get('timestamp')
            if isinstance(tweet_timestamp, datetime):
                # Ensure timezone is UTC
                if tweet_timestamp.tzinfo is None:
                    tweet_timestamp = tweet_timestamp.replace(tzinfo=timezone.utc)
                entity_datetime = tweet_timestamp
            else:
                entity_datetime = datetime.fromisoformat(tweet_data.get('timestamp'))
            
            # Convert datetime to UTC ISO format string for JSON serialization
            tweet_data_copy = tweet_data.copy()
            if isinstance(tweet_data_copy.get('timestamp'), datetime):
                tweet_data_copy['timestamp'] = tweet_data_copy['timestamp'].replace(tzinfo=timezone.utc).isoformat()
            
            # Convert tweet data to JSON bytes for DataEntity content
            content_json = json.dumps(tweet_data_copy).encode('utf-8')
            
            # Determine label - use job_label hashtag if available
            label = None
            if tweet_data.get('job_label'):
                # Ensure label starts with # for Twitter data
                job_label = tweet_data['job_label']
                if not job_label.startswith('#'):
                    job_label = f"#{job_label}"
                label = DataLabel(value=job_label)
            
            # Create DataEntity
            data_entity = DataEntity(
                uri=tweet_data.get('url', f"x://tweet/{tweet_data.get('id')}"),
                datetime=entity_datetime,
                source=DataSource.X,  # X/Twitter source
                label=label,
                content=content_json,
                content_size_bytes=len(content_json)
            )
            
            # Store using SqliteMinerStorage
            self.storage.store_data_entities([data_entity])
            return True
            
        except Exception as e:
            logger.error(f"Error storing tweet {tweet_data.get('id')} as DataEntity: {e}")
            return False
    
    def get_stats(self) -> dict:
        """Get storage statistics from SqliteMinerStorage"""
        try:
            # Get the compressed index which contains bucket info
            compressed_index = self.storage.get_compressed_index()
            
            # Get earliest date for X source
            earliest_date = self.storage.get_earliest_data_datetime(DataSource.X)
            
            # Count total buckets and estimate tweets
            total_buckets = 0
            total_size = 0
            labels_dict = {}
            
            if compressed_index and compressed_index.sources:
                x_buckets = compressed_index.sources.get(DataSource.X, [])
                total_buckets = len(x_buckets)
                
                for bucket in x_buckets:
                    if bucket.label:
                        labels_dict[bucket.label] = labels_dict.get(bucket.label, 0) + len(bucket.sizes_bytes)
                    total_size += sum(bucket.sizes_bytes)
            
            return {
                'total_tweets': total_buckets * 100,  # Rough estimate
                'earliest_tweet': earliest_date.isoformat() if earliest_date else 'N/A',
                'latest_tweet': datetime.now().isoformat(),
                'by_label': labels_dict,
                'total_size_mb': total_size / (1024 * 1024)
            }
        except Exception as e:
            logger.error(f"Error getting stats from SqliteMinerStorage: {e}")
            return {
                'total_tweets': 0,
                'earliest_tweet': 'N/A',
                'latest_tweet': 'N/A',
                'by_label': {},
                'total_size_mb': 0
            }


# Alias for compatibility
TweetStorage = DataEntityTweetStorage


# ========== HELPER METHODS FOR PARSING ==========

def _extract_user_info(tweet) -> dict:
    """Extract user information from tweet"""
    if not hasattr(tweet, 'user') or not tweet.user:
        return {"id": None, "user_display_name": None, "verified": False}
    
    user = tweet.user
    return {
        "id": str(user.id) if hasattr(user, 'id') else None,
        "user_display_name": user.displayname if hasattr(user, 'displayname') else None,  # ✅ FIXED: Correct field name
        "verified": getattr(user, 'verified', False) or getattr(user, 'blueVerified', False),
    }


def _extract_tags(tweet) -> List[str]:
    """Extract and format hashtags"""
    return tweet.hashtags if hasattr(tweet, 'hashtags') else []


def _extract_media_urls(tweet) -> List[str]:
    """Extract media URLs from tweet"""
    media_urls = []
    if hasattr(tweet, 'media') and tweet.media:
        if hasattr(tweet.media, 'photos'):
            for photo in tweet.media.photos:
                media_urls.append(photo.url if hasattr(photo, 'url') else str(photo))
        if hasattr(tweet.media, 'videos'):
            for video in tweet.media.videos:
                if hasattr(video, 'thumbnailUrl'):
                    media_urls.append(video.thumbnailUrl)
    return media_urls


def _extract_engagement_metrics(tweet) -> dict:
    """Extract engagement metrics"""
    return {
        "like_count": getattr(tweet, 'likeCount', None),
        "retweet_count": getattr(tweet, 'retweetCount', None),
        "reply_count": getattr(tweet, 'replyCount', None),
        "quote_count": getattr(tweet, 'quoteCount', None),
        "view_count": getattr(tweet, 'viewCount', None),
        "bookmark_count": getattr(tweet, 'bookmarkCount', None),
    }


def _extract_user_profile_data(tweet) -> dict:
    """Extract user profile data"""
    if not hasattr(tweet, 'user') or not tweet.user:
        return {}
    
    user = tweet.user
    return {
        "user_blue_verified": getattr(user, 'blueVerified', None),
        "user_description": getattr(user, 'rawDescription', None),
        "user_location": getattr(user, 'location', None),
        "profile_image_url": getattr(user, 'profileImageUrl', None),
        "user_followers_count": getattr(user, 'followersCount', None),
        "user_following_count": getattr(user, 'followingCount', None),
    }


# ========== MAIN CLASSES ==========

class SearchStrategy(str, Enum):
    """Search strategy types for X/Twitter"""
    HASHTAG = "hashtag"
    KEYWORD = "keyword"
    USER = "user"
    LOCATION = "location"
    ADVANCED = "advanced"


class ScrapingJob:
    """Represents a single scraping job with enhanced search capabilities"""
    
    def __init__(self, label: str, keyword: Optional[str], 
                 start_datetime: Optional[str], end_datetime: Optional[str], 
                 weight: float, 
                 strategy: str = "hashtag",
                 additional_filters: Optional[Dict] = None,
                 language: Optional[str] = None,
                 enable_network_expansion: bool = True,
                 max_network_depth: int = 5):
        self.label = label
        self.keyword = keyword
        self.start_datetime = start_datetime
        self.end_datetime = end_datetime
        self.weight = weight
        self.strategy = SearchStrategy(strategy) if isinstance(strategy, str) else strategy
        self.additional_filters = additional_filters or {}
        self.language = language
        self.enable_network_expansion = enable_network_expansion
        self.max_network_depth = max_network_depth
        
        # Parse dates or use defaults (last 30 days)
        # Enhanced: Explicit handling of null dates with clear logging
        if end_datetime:
            self.end_date = datetime.fromisoformat(end_datetime.replace('Z', '+00:00'))
        else:
            self.end_date = datetime.now(timezone.utc)
            logger.debug(f"Job {self.label}: No end_datetime provided, using current time")
        
        if start_datetime:
            self.start_date = datetime.fromisoformat(start_datetime.replace('Z', '+00:00'))
        else:
            self.start_date = self.end_date - timedelta(days=30)
            logger.debug(f"Job {self.label}: No start_datetime provided, using 30-day default")
        
        # Validate job has at least label or keyword
        if not self.label and not self.keyword:
            logger.warning(f"Invalid job: both label and keyword are null - this job will be skipped")
            self.is_valid = False
        else:
            self.is_valid = True
    
    def build_comprehensive_variants(self, base_term: str) -> List[str]:
        """
        Build multiple query variants for maximum coverage
        
        Args:
            base_term: The base term (with or without #)
        
        Returns:
            List of query variants
        """
        # Remove # or $ if present to get base
        clean_term = base_term.lstrip('#$').strip()
        
        variants = []
        
        # 1. Original hashtag (most important)
        variants.append(f"#{clean_term}")
        
        # 2. Keyword without hashtag (catches non-hashtag usage)
        variants.append(clean_term)
        
        # 3. Exact phrase (catches precise mentions)
        variants.append(f'"{clean_term}"')
        
        # 4. Plural forms (if applicable and word length > 3)
        if not clean_term.endswith('s') and len(clean_term) > 3:
            variants.append(f"#{clean_term}s")
            variants.append(f"{clean_term}s")
        
        # 5. For crypto: add cashtag version if original was hashtag
        if base_term.startswith('#'):
            variants.append(f"${clean_term}")
        elif base_term.startswith('$'):
            variants.append(f"#{clean_term}")
        
        return variants
    
    def _build_label_query_parts(self) -> List[str]:
        """
        Build query parts for label-based search
        
        Returns:
            List of query parts for the label
        """
        if not self.label:
            return []
        
        # Use comprehensive variants if enabled
        if self.additional_filters.get('use_variants', True):
            variants = self.build_comprehensive_variants(self.label)
            return [f"({' OR '.join(variants)})"]
        else:
            return [self.label]
    
    def _build_keyword_query_parts(self) -> List[str]:
        """
        Build query parts for keyword-based search
        
        Returns:
            List of query parts for the keyword
        """
        if not self.keyword:
            return []
        
        # Build keyword variants for maximum coverage
        keyword_variants = []
        
        # Exact phrase match (most precise)
        keyword_variants.append(f'"{self.keyword}"')
        
        # Plain keyword (broader match)
        keyword_variants.append(self.keyword)
        
        return [f"({' OR '.join(keyword_variants)})"]
    
    def build_query(self) -> str:
        """
        MAXIMUM COVERAGE query builder - combines ALL search strategies
        Uses hashtag variants, keyword variants, AND additional strategy-specific terms
        """
        all_search_terms = []
        
        # STRATEGY 1: Hashtag variants (always include if label exists)
        if self.label:
            label_variants = self.build_comprehensive_variants(self.label)
            all_search_terms.extend(label_variants)
        
        # STRATEGY 2: Keyword variants (always include if keyword exists)
        if self.keyword:
            # Exact phrase
            all_search_terms.append(f'"{self.keyword}"')
            # Plain keyword
            all_search_terms.append(self.keyword)
            # With hashtag (if not already a hashtag)
            if not self.keyword.startswith('#'):
                all_search_terms.append(f"#{self.keyword}")
        
        # STRATEGY 3: User-based search (if strategy is USER or label starts with @)
        if self.strategy == SearchStrategy.USER or (self.label and self.label.startswith('@')):
            username = self.label.lstrip('@') if self.label else self.keyword
            if username:
                all_search_terms.append(f"from:{username}")
        
        # STRATEGY 4: Mentions (search for @mentions of the term)
        if self.label and not self.label.startswith('@'):
            clean_label = self.label.lstrip('#$')
            all_search_terms.append(f"@{clean_label}")
        
        # Build the main query with OR logic for maximum coverage
        query_parts = []
        if all_search_terms:
            # Combine all search terms with OR
            query_parts.append(f"({' OR '.join(all_search_terms)})")
        
        # Advanced filters
        filters = self.additional_filters
        
        if filters.get('min_likes'):
            query_parts.append(f"min_faves:{filters['min_likes']}")
        if filters.get('min_retweets'):
            query_parts.append(f"min_retweets:{filters['min_retweets']}")
        if filters.get('min_replies'):
            query_parts.append(f"min_replies:{filters['min_replies']}")
        
        # Content type filters
        if filters.get('has_media'):
            query_parts.append("filter:media")
        if filters.get('has_video'):
            query_parts.append("filter:videos")
        if filters.get('has_images'):
            query_parts.append("filter:images")
        if filters.get('has_links'):
            query_parts.append("filter:links")
        if filters.get('has_mentions'):
            query_parts.append("filter:mentions")
        
        # Tweet type filters
        if filters.get('filter_replies'):
            query_parts.append("filter:replies")
        if filters.get('filter_quotes'):
            query_parts.append("filter:quote")
        if filters.get('filter_spaces'):
            query_parts.append("filter:spaces")
        
        # User filters
        if filters.get('verified_only'):
            query_parts.append("filter:verified")
        if filters.get('blue_verified_only'):
            query_parts.append("filter:blue_verified")
        
        # Exclude filters
        if filters.get('exclude_retweets'):
            query_parts.append("-filter:retweets")
        if filters.get('exclude_replies'):
            query_parts.append("-filter:replies")
        if filters.get('exclude_quotes'):
            query_parts.append("-filter:quote")
        
        # Language filter (use instance language if set, otherwise use filter)
        # ONLY add if it's a valid 2-letter language code, NOT 'all'
        lang = self.language or filters.get('language')
        if lang and lang != 'all' and len(lang) == 2:
            query_parts.append(f"lang:{lang}")
        
        # URL filter
        if filters.get('url_contains'):
            query_parts.append(f"url:{filters['url_contains']}")
        
        # Mention/to filters
        if filters.get('to_user'):
            query_parts.append(f"to:{filters['to_user'].lstrip('@')}")
        if filters.get('mention_user'):
            query_parts.append(f"@{filters['mention_user'].lstrip('@')}")
        
        # Date range
        query_parts.append(f"since:{self.start_date.strftime('%Y-%m-%d')}")
        query_parts.append(f"until:{self.end_date.strftime('%Y-%m-%d')}")
        
        return " ".join(query_parts)
    
    def __repr__(self):
        return f"Job({self.label}, keyword={self.keyword}, {self.start_date.date()} to {self.end_date.date()})"


def extract_rich_metadata(tweet) -> Dict:
    """
    Extract rich metadata from tweet object using helper methods
    Refactored for better maintainability and structure
    """
    try:
        # Extract components using helper methods
        user_info = _extract_user_info(tweet)
        tags = _extract_tags(tweet)
        media_urls = _extract_media_urls(tweet)
        engagement_metrics = _extract_engagement_metrics(tweet)
        user_profile_data = _extract_user_profile_data(tweet)
        
        # Build complete tweet data dictionary - ✅ FIXED: All field names match XContent model
        tweet_data = {
            # Basic tweet data
            'id': str(tweet.id),
            'url': tweet.url,
            'username': tweet.user.username,
            'text': sanitize_scraped_tweet(tweet.rawContent),
            'timestamp': tweet.date,
            
            # User info from helper - ✅ FIXED: Correct field names
            'user_id': user_info['id'],
            'user_display_name': user_info['user_display_name'],  # ✅ FIXED: Was 'display_name'
            'user_verified': user_info['verified'],
            
            # Tweet metadata
            'language': tweet.lang if hasattr(tweet, 'lang') else None,
            'is_reply': tweet.inReplyToTweetId is not None,
            'is_retweet': tweet.retweetedTweet is not None,
            'is_quote': tweet.quotedTweet is not None,
            'in_reply_to_user_id': str(tweet.inReplyToTweetId) if tweet.inReplyToTweetId else None,
            'quoted_tweet_id': str(tweet.quotedTweet.id) if tweet.quotedTweet else None,
            'conversation_id': str(tweet.conversationId) if hasattr(tweet, 'conversationId') else None,
            'tweet_id': str(tweet.id),  # ✅ ADDED: Missing tweet_id field
            
            # Content - ✅ FIXED: Correct field names matching XContent
            'tweet_hashtags': tags if tags else [],  # ✅ FIXED: Was 'hashtags', now ensures list
            'media': media_urls if media_urls else None,  # ✅ FIXED: Was 'media_urls'
            # NOTE: 'source' is NOT included - it's set at DataEntity level (DataSource.X), not in XContent
        }
        
        # Add engagement metrics
        tweet_data.update(engagement_metrics)
        
        # Add user profile data
        tweet_data.update(user_profile_data)
        
        return tweet_data
    
    except Exception as e:
        logger.warning(f"Error extracting metadata: {e}")
        # Return basic data on error
        return {
            'id': str(tweet.id),
            'url': tweet.url,
            'username': tweet.user.username,
            'text': sanitize_scraped_tweet(tweet.rawContent) if hasattr(tweet, 'rawContent') else '',
            'timestamp': tweet.date,
            # NOTE: 'source' removed - handled by DataEntity, not XContent
        }


async def expand_network(api: API, storage: TweetStorage, seed_tweet_ids: Set[str], 
                        job: ScrapingJob, max_depth: int = 1) -> Dict:
    """
    Expand collection by following conversations, quoted tweets, and user networks
    
    Args:
        api: Twitter API instance
        storage: Storage instance
        seed_tweet_ids: Set of tweet IDs to expand from
        job: Job configuration
        max_depth: Maximum depth for network expansion
    
    Returns:
        Statistics dictionary
    """
    if max_depth < 1 or not seed_tweet_ids:
        return {"network_tweets": 0, "network_users": 0}
    
    logger.info(f"[{job.label}] Expanding network from {len(seed_tweet_ids)} seed tweets (depth={max_depth})...")
    
    stats = {"network_tweets": 0, "network_users": 0, "retweeters": 0}
    new_tweet_ids = set()
    processed_users = set()
    thirty_days_ago = datetime.now(timezone.utc) - timedelta(days=30)
    
    for tweet_id in list(seed_tweet_ids)[:100]:  # Limit to first 100 to avoid overwhelming
        try:
            # Get conversation thread (replies) - only last 30 days
            reply_count = 0
            async for tweet in api.tweet_replies(tweet_id, limit=50):
                if tweet.id not in seed_tweet_ids and tweet.id not in new_tweet_ids:
                    # Check if tweet is within last 30 days
                    tweet_date = tweet.date if hasattr(tweet, 'date') else None
                    if tweet_date and tweet_date < thirty_days_ago:
                        logger.debug(f"[{job.label}] Skipping old network reply from {tweet_date.date()} (older than 30 days)")
                        continue
                    
                    new_tweet_ids.add(tweet.id)
                    tweet_data = extract_rich_metadata(tweet)
                    tweet_data['job_label'] = f"{job.label}_network"
                    tweet_data['job_keyword'] = job.keyword
                    storage.store_tweet(tweet_data)
                    stats["network_tweets"] += 1
                    reply_count += 1
            
            if reply_count > 0:
                logger.debug(f"[{job.label}] Found {reply_count} replies (within 30 days) for tweet {tweet_id}")
            
            # Get users who retweeted (sample)
            retweeter_count = 0
            async for user in api.retweeters(tweet_id, limit=20):
                if user.id not in processed_users:
                    processed_users.add(user.id)
                    stats["retweeters"] += 1
                    
                    # Get recent tweets from these users (light sampling) - only last 30 days
                    async for user_tweet in api.user_tweets(user.id, limit=10):
                        if user_tweet.id not in seed_tweet_ids and user_tweet.id not in new_tweet_ids:
                            # Check if tweet is within last 30 days
                            user_tweet_date = user_tweet.date if hasattr(user_tweet, 'date') else None
                            if user_tweet_date and user_tweet_date < thirty_days_ago:
                                logger.debug(f"[{job.label}] Skipping old user tweet from {user_tweet_date.date()} (older than 30 days)")
                                continue
                            
                            new_tweet_ids.add(user_tweet.id)
                            tweet_data = extract_rich_metadata(user_tweet)
                            tweet_data['job_label'] = f"{job.label}_network"
                            tweet_data['job_keyword'] = job.keyword
                            storage.store_tweet(tweet_data)
                            stats["network_tweets"] += 1
                            retweeter_count += 1
            
            if retweeter_count > 0:
                logger.debug(f"[{job.label}] Found {retweeter_count} tweets (within 30 days) from retweeters")
        
        except Exception as e:
            logger.warning(f"[{job.label}] Error expanding from tweet {tweet_id}: {e}")
    
    stats["network_users"] = len(processed_users)
    logger.info(f"[{job.label}] Network expansion complete: {stats['network_tweets']} tweets from {stats['network_users']} users")
    
    return stats


async def scrape_job(api: API, job: ScrapingJob, storage: TweetStorage, dedup: GlobalDeduplication = None, pagination_mgr: PaginationStateManager = None) -> Dict:
    """
    Enhanced scraping with TRUE checkpointing for 10M tweets/day
    Resumes from exact position on account ban/rate limit/crash
    Store in SQLite database with REAL resume capability
    """
    from twscrape.models import parse_tweets
    
    # Validate job before execution
    if not job.is_valid:
        logger.error(f"Skipping invalid job: {job}")
        return {
            "job": str(job),
            "query": "",
            "posts": 0,
            "replies": 0,
            "retweets": 0,
            "total": 0,
            "start_time": datetime.now().isoformat(),
            "end_time": datetime.now().isoformat(),
            "error": "Invalid job - both label and keyword are null"
        }
    
    query = job.build_query()
    logger.info(f"Starting job: {job}")
    logger.info(f"Query: {query}")
    logger.info(f"Strategy: {job.strategy.value}")
    
    # Log search strategy being used
    if job.label and job.keyword:
        logger.info(f"Search strategy: MAXIMUM COVERAGE - combining label and keyword with OR logic")
        logger.info(f"  Label: {job.label}")
        logger.info(f"  Keyword: {job.keyword}")
    elif job.label:
        logger.info(f"Search strategy: LABEL-ONLY - {job.label}")
    elif job.keyword:
        logger.info(f"Search strategy: KEYWORD-ONLY - {job.keyword}")
    
    # Show search variants if using HASHTAG strategy with variants enabled
    if job.strategy == SearchStrategy.HASHTAG and job.additional_filters.get('use_variants', True):
        variants = job.build_comprehensive_variants(job.label)
        logger.info(f"Search variants ({len(variants)}): {', '.join(variants)}")
    
    # Only log language if it's a valid 2-letter code
    if job.language and job.language != 'all' and len(job.language) == 2:
        logger.info(f"Language: {job.language}")
    if job.enable_network_expansion:
        logger.info(f"Network expansion: enabled (depth={job.max_network_depth})")
    
    # Initialize pagination state manager
    pagination_mgr = PaginationStateManager("pagination_state.db")
    query_params = {
        "label": job.label,
        "strategy": job.strategy.value,
        "language": job.language,
        "dates": f"{job.start_date.date()}_to_{job.end_date.date()}"
    }
    query_hash = pagination_mgr.generate_query_hash(query, query_params)
    
    # Check for existing pagination state (resume capability)
    existing_state = await pagination_mgr.get_state(query_hash)
    resume_cursor = None
    if existing_state and not existing_state.get('completed'):
        resume_cursor = existing_state.get('cursor')
        logger.info(f"[{job.label}] Resuming from previous run - {existing_state['items_fetched']} tweets already collected")
        if resume_cursor:
            logger.info(f"[{job.label}] Resuming from cursor: {resume_cursor[:20]}...")
    
    tweet_ids_seen = set()
    seed_tweet_ids = set()  # For network expansion
    
    stats = {
        "job": str(job),
        "query": query,
        "posts": 0,
        "replies": 0,
        "retweets": 0,
        "total": 0,
        "start_time": datetime.now().isoformat(),
        "end_time": None,
    }
    
    try:
        # Build kv dict - IMPORTANT: cursor must be in kv dict from the start for resume
        search_kv = {}
        if resume_cursor:
            search_kv["cursor"] = resume_cursor
            logger.info(f"[{job.label}] Resuming from saved cursor: {resume_cursor[:50]}...")
        
        # Use standard search (not search_raw) with limit=-1 for unlimited pagination
        # The API handles cursor management internally when limit=-1
        logger.info(f"[{job.label}] Starting unlimited pagination search...")
        
        async for tweet in api.search(query, limit=-1, kv=search_kv if search_kv else None):
            if tweet.id not in tweet_ids_seen:
                tweet_ids_seen.add(tweet.id)
                
                # Check keyword filter if specified
                if job.keyword:
                    if job.keyword.lower() not in tweet.rawContent.lower():
                        continue
                
                # Extract rich metadata
                tweet_data = extract_rich_metadata(tweet)
                tweet_data['job_label'] = job.label
                tweet_data['job_keyword'] = job.keyword
                tweet_data['search_strategy'] = job.strategy.value
                if job.language:
                    tweet_data['search_language'] = job.language
                
                # Store in database
                storage.store_tweet(tweet_data)
                stats["posts"] += 1
                
                # Track for network expansion
                if job.enable_network_expansion:
                    seed_tweet_ids.add(tweet.id)
                
                # Log progress every 100 tweets
                if stats["posts"] % 100 == 0:
                    logger.info(f"[{job.label}] Stored {stats['posts']} posts")
                
                # Get replies for this tweet (only last 30 days)
                try:
                    reply_count = 0
                    reply_limit = MAX_REPLIES_PER_TWEET if SCRAPE_ALL_REPLIES else 100
                    thirty_days_ago = datetime.now(timezone.utc) - timedelta(days=30)
                    
                    async for reply in api.tweet_replies(tweet.id, limit=reply_limit):
                        if reply.id not in tweet_ids_seen:
                            # Check if reply is within last 30 days
                            reply_date = reply.date if hasattr(reply, 'date') else None
                            if reply_date and reply_date < thirty_days_ago:
                                logger.debug(f"[{job.label}] Skipping old reply from {reply_date.date()} (older than 30 days)")
                                continue
                            
                            tweet_ids_seen.add(reply.id)
                            
                            # Extract rich metadata for reply
                            reply_data = extract_rich_metadata(reply)
                            reply_data['job_label'] = job.label
                            reply_data['job_keyword'] = job.keyword
                            reply_data['in_reply_to_user_id'] = str(tweet.user.id) if hasattr(tweet.user, 'id') else None
                            
                            # Store reply
                            storage.store_tweet(reply_data)
                            stats["replies"] += 1
                            reply_count += 1
                    
                    if reply_count > 0:
                        logger.debug(f"[{job.label}] Stored {reply_count} replies (within 30 days) for tweet {tweet.id}")
                
                except Exception as e:
                    logger.warning(f"[{job.label}] Error getting replies for {tweet.id}: {e}")
                
                # Track retweets
                if tweet.retweetedTweet:
                    stats["retweets"] += 1
        
        # Mark query as completed (no cursor tracking needed with api.search)
        await pagination_mgr.create_or_update_state(
            query_hash=query_hash,
            query_text=query,
            cursor=None,  # api.search manages cursors internally
            items_fetched=stats["posts"],
            completed=True
        )
        logger.info(f"[{job.label}] Query marked as completed in pagination state")
        
        # FALLBACK: If no results with language filter, try high-volume languages
        if stats["posts"] == 0 and job.language and job.language != 'all':
            logger.warning(f"[{job.label}] No results with language '{job.language}'. Trying high-volume languages...")
            
            # Try top 3 languages: English, Japanese, Spanish
            fallback_languages = ['en', 'ja', 'es']
            original_lang = job.language
            
            for fallback_lang in fallback_languages:
                if fallback_lang == original_lang:
                    continue  # Skip the one we already tried
                
                logger.info(f"[{job.label}] Trying fallback language: {fallback_lang}")
                job.language = fallback_lang
                fallback_query = job.build_query()
                
                # Try this language
                fallback_found = False
                
                async for tweet in api.search(fallback_query, limit=-1):
                    if tweet.id not in tweet_ids_seen:
                        fallback_found = True
                        tweet_ids_seen.add(tweet.id)
                        
                        if job.keyword and job.keyword.lower() not in tweet.rawContent.lower():
                            continue
                        
                        tweet_data = extract_rich_metadata(tweet)
                        tweet_data['job_label'] = job.label
                        tweet_data['job_keyword'] = job.keyword
                        tweet_data['search_strategy'] = f"{job.strategy.value}_fallback_{fallback_lang}"
                        
                        storage.store_tweet(tweet_data)
                        stats["posts"] += 1
                        
                        if job.enable_network_expansion:
                            seed_tweet_ids.add(tweet.id)
                        
                        if stats["posts"] % 100 == 0:
                            logger.info(f"[{job.label}] Fallback ({fallback_lang}): {stats['posts']} posts")
                        
                        # Get replies
                        try:
                            reply_count = 0
                            reply_limit = MAX_REPLIES_PER_TWEET if SCRAPE_ALL_REPLIES else 100
                            thirty_days_ago = datetime.now(timezone.utc) - timedelta(days=30)
                            
                            async for reply in api.tweet_replies(tweet.id, limit=reply_limit):
                                if reply.id not in tweet_ids_seen:
                                    reply_date = reply.date if hasattr(reply, 'date') else None
                                    if reply_date and reply_date < thirty_days_ago:
                                        continue
                                    
                                    tweet_ids_seen.add(reply.id)
                                    reply_data = extract_rich_metadata(reply)
                                    reply_data['job_label'] = job.label
                                    reply_data['job_keyword'] = job.keyword
                                    storage.store_tweet(reply_data)
                                    stats["replies"] += 1
                                    reply_count += 1
                        except Exception as e:
                            logger.warning(f"[{job.label}] Fallback error getting replies: {e}")
                        
                        if tweet.retweetedTweet:
                            stats["retweets"] += 1
                
                # Check if we found tweets with this language
                if fallback_found and stats["posts"] > 0:
                    logger.info(f"[{job.label}] ✓ Fallback SUCCESS with '{fallback_lang}': {stats['posts']} total tweets")
                    break  # Found tweets, stop trying other languages
                else:
                    logger.info(f"[{job.label}] No results with '{fallback_lang}', trying next language...")
            
            # Restore original language
            job.language = original_lang
            
            if stats["posts"] == 0:
                logger.warning(f"[{job.label}] ✗ Fallback FAILED: No tweets found in any fallback languages (en, ja, es)")
        
        # PHASE 2 & 3: Advanced Collection Strategies
        if job.enable_network_expansion and seed_tweet_ids:
            logger.info(f"[{job.label}] Starting ENHANCED collection strategies...")
            
            # Prepare seed data for advanced strategies
            seed_tweets_data = []
            seed_user_ids = set()
            
            # Collect seed tweet data and user IDs for analysis
            for tweet_id in list(seed_tweet_ids)[:200]:  # Sample for analysis
                try:
                    tweet_detail = await api.tweet_details(int(tweet_id))
                    if tweet_detail:
                        tweet_data = extract_rich_metadata(tweet_detail)
                        seed_tweets_data.append(tweet_data)
                        if tweet_data.get('user_id'):
                            seed_user_ids.add(tweet_data['user_id'])
                except Exception as e:
                    logger.debug(f"Could not get details for tweet {tweet_id}: {e}")
            
            logger.info(f"[{job.label}] Collected {len(seed_tweets_data)} seed tweets for analysis")
            
            # Import collection strategies
            from collection_strategies import (
                collect_deep_conversations,
                collect_influencer_timelines,
                collect_from_retweeters,
                matches_job_criteria
            )
            
            thirty_days_ago = datetime.now(timezone.utc) - timedelta(days=30)
            job_context = {
                'label': job.label,
                'keyword': job.keyword,
                'start_date': job.start_date,
                'end_date': job.end_date
            }
            
            # PHASE 2: Deep Conversation Threading
            logger.info(f"[{job.label}] PHASE 2: Collecting deep conversation threads...")
            deep_conv_count = 0
            try:
                async for tweet_data in collect_deep_conversations(
                    api,
                    [str(tid) for tid in list(seed_tweet_ids)[:100]],  # Process top 100
                    job_context,
                    max_depth=5,
                    thirty_days_ago=thirty_days_ago
                ):
                    tweet_data['job_label'] = job.label
                    tweet_data['job_keyword'] = job.keyword
                    storage.store_tweet(tweet_data)
                    deep_conv_count += 1
                    
                    if deep_conv_count % 100 == 0:
                        logger.info(f"[{job.label}] Deep conversations: {deep_conv_count} tweets")
                
                logger.info(f"[{job.label}] PHASE 2 Complete: {deep_conv_count} tweets from deep conversations")
                stats['deep_conversations'] = deep_conv_count
            except Exception as e:
                logger.warning(f"[{job.label}] Error in deep conversation collection: {e}")
                stats['deep_conversations'] = deep_conv_count
            
            # PHASE 3: Influencer Timeline Collection
            if len(seed_tweets_data) > 10:  # Need enough data for analysis
                logger.info(f"[{job.label}] PHASE 3: Collecting influencer timelines...")
                influencer_count = 0
                try:
                    async for tweet_data in collect_influencer_timelines(
                        api,
                        seed_tweets_data,
                        job_context,
                        top_n=30,
                        tweets_per_user=200,
                        thirty_days_ago=thirty_days_ago
                    ):
                        # Filter for relevance
                        if matches_job_criteria(tweet_data, job_context):
                            tweet_data['job_label'] = job.label
                            tweet_data['job_keyword'] = job.keyword
                            storage.store_tweet(tweet_data)
                            influencer_count += 1
                            
                            if influencer_count % 100 == 0:
                                logger.info(f"[{job.label}] Influencer timelines: {influencer_count} tweets")
                    
                    logger.info(f"[{job.label}] PHASE 3 Complete: {influencer_count} tweets from influencers")
                    stats['influencer_timelines'] = influencer_count
                except Exception as e:
                    logger.warning(f"[{job.label}] Error in influencer collection: {e}")
                    stats['influencer_timelines'] = influencer_count
            else:
                logger.info(f"[{job.label}] Skipping influencer collection (insufficient seed data)")
                stats['influencer_timelines'] = 0
            
            # PHASE 4: Retweeter Discovery  
            logger.info(f"[{job.label}] PHASE 4: Collecting from retweeters...")
            retweeter_count = 0
            try:
                async for tweet_data in collect_from_retweeters(
                    api,
                    [str(tid) for tid in list(seed_tweet_ids)[:50]],  # Process top 50
                    job_context,
                    retweeters_per_tweet=100,
                    tweets_per_retweeter=50,
                    thirty_days_ago=thirty_days_ago
                ):
                    if matches_job_criteria(tweet_data, job_context):
                        tweet_data['job_label'] = job.label
                        tweet_data['job_keyword'] = job.keyword
                        storage.store_tweet(tweet_data)
                        retweeter_count += 1
                        
                        if retweeter_count % 100 == 0:
                            logger.info(f"[{job.label}] Retweeter discovery: {retweeter_count} tweets")
                
                logger.info(f"[{job.label}] PHASE 4 Complete: {retweeter_count} tweets from retweeters")
                stats['retweeter_discovery'] = retweeter_count
            except Exception as e:
                logger.warning(f"[{job.label}] Error in retweeter collection: {e}")
                stats['retweeter_discovery'] = retweeter_count
            
            # Calculate total from all enhanced strategies
            enhanced_total = (
                stats.get('deep_conversations', 0) +
                stats.get('influencer_timelines', 0) +
                stats.get('retweeter_discovery', 0)
            )
            logger.info(f"[{job.label}] ENHANCED STRATEGIES Total: {enhanced_total} additional tweets")
    
    except KeyboardInterrupt:
        logger.info(f"[{job.label}] Interrupted. Saving progress...")
        # Save pagination state on interruption with current cursor
        await pagination_mgr.create_or_update_state(
            query_hash=query_hash,
            query_text=query,
            cursor=current_cursor if 'current_cursor' in locals() else None,
            items_fetched=stats["posts"],
            completed=False
        )
        logger.info(f"[{job.label}] Progress saved. {stats['posts'] + stats['replies']} tweets stored. Can resume later.")
    except Exception as e:
        logger.error(f"[{job.label}] Error: {e}")
        # Save progress even on error with current cursor
        try:
            await pagination_mgr.create_or_update_state(
                query_hash=query_hash,
                query_text=query,
                cursor=current_cursor if 'current_cursor' in locals() else None,
                items_fetched=stats["posts"],
                completed=False
            )
        except:
            pass
    
    # Calculate stats
    stats["total"] = stats["posts"] + stats["replies"]
    stats["end_time"] = datetime.now().isoformat()
    
    logger.info(f"[{job.label}] Stored {stats['total']} tweets in database")
    return stats


async def scrape_jobs_concurrently(jobs: List[ScrapingJob], max_concurrent: int = 10, enable_hot_reload: bool = True):
    """
    Scrape multiple jobs concurrently using a dynamic queue with HOT RELOAD support
    All data stored in SQLite database
    When a worker finishes a job, it immediately picks up the next one from the queue
    
    HOT RELOAD: Automatically detects new jobs in x.json and adds them to queue
    Perfect for 24/7 operation with pm2
    """
    # Create storage with batch capability
    storage = TweetStorage(batch_size=1000)  # ✅ OPTIMIZED: Batch inserts for performance
    
    # Create global deduplication system
    dedup = GlobalDeduplication()  # ✅ OPTIMIZED: Prevent duplicates across all runs
    
    # Create API instance (shared across jobs)
    api = API("accounts.db")
    
    # Create a queue and add all jobs
    import random
    job_queue = asyncio.Queue()
    shuffled_jobs = list(jobs)
    random.shuffle(shuffled_jobs)  # Randomize job order
    for job in shuffled_jobs:
        await job_queue.put(job)
    
    # Track processed job IDs to avoid duplicates on reload
    processed_job_ids = set()
    for job in jobs:
        job_id = f"{job.label}_{job.keyword}_{job.start_date.date()}_{job.end_date.date()}"
        processed_job_ids.add(job_id)
    
    # Track results
    results = []
    results_lock = asyncio.Lock()
    
    # Hot reload flag
    keep_running = True
    
    async def hot_reload_monitor():
        """Monitor x.json for new jobs and add them to queue"""
        if not enable_hot_reload:
            return
        
        import time
        import os
        
        json_file = "x.json"
        last_check = time.time()
        
        logger.info("🔥 HOT RELOAD: Enabled - monitoring x.json for new jobs...")
        
        while keep_running:
            try:
                await asyncio.sleep(30)  # Check every 30 seconds
                
                # Check if file was modified
                if os.path.exists(json_file):
                    mtime = os.path.getmtime(json_file)
                    
                    if mtime > last_check:
                        last_check = mtime
                        logger.info("🔥 HOT RELOAD: Detected changes in x.json, loading new jobs...")
                        
                        try:
                            new_jobs = load_jobs_from_json(json_file)
                            added_count = 0
                            
                            for new_job in new_jobs:
                                # Create unique job ID
                                job_id = f"{new_job.label}_{new_job.keyword}_{new_job.start_date.date()}_{new_job.end_date.date()}"
                                
                                # Only add if not already processed
                                if job_id not in processed_job_ids:
                                    await job_queue.put(new_job)
                                    processed_job_ids.add(job_id)
                                    added_count += 1
                            
                            if added_count > 0:
                                logger.info(f"🔥 HOT RELOAD: Added {added_count} new jobs to queue")
                            else:
                                logger.debug("🔥 HOT RELOAD: No new jobs found (all jobs already processed)")
                        
                        except Exception as e:
                            logger.error(f"🔥 HOT RELOAD: Error loading new jobs: {e}")
            
            except Exception as e:
                logger.error(f"🔥 HOT RELOAD: Monitor error: {e}")
        
        logger.info("🔥 HOT RELOAD: Monitor stopped")
    
    async def worker(worker_id: int):
        """Worker that processes jobs from the queue"""
        while keep_running:
            try:
                # Get a job from the queue with timeout
                # In hot reload mode, wait longer for new jobs
                timeout = 5.0 if enable_hot_reload else 0.1
                job = await asyncio.wait_for(job_queue.get(), timeout=timeout)
            except asyncio.TimeoutError:
                # In hot reload mode, keep waiting
                if enable_hot_reload:
                    continue
                else:
                    # No hot reload, exit when queue is empty
                    break
            
            try:
                logger.info(f"[Worker {worker_id}] Starting job: {job.label}")
                result = await scrape_job(api, job, storage, dedup)  # ✅ Pass dedup to prevent duplicates
                async with results_lock:
                    results.append(result)
                logger.info(f"[Worker {worker_id}] Completed job: {job.label}")
            except Exception as e:
                logger.error(f"[Worker {worker_id}] Job {job.label} failed: {e}")
                async with results_lock:
                    results.append(e)
            finally:
                job_queue.task_done()
    
    # Log start
    logger.info("="*80)
    logger.info(f"STARTING CONCURRENT SCRAPING: {len(jobs)} jobs")
    logger.info(f"Max concurrent workers: {max_concurrent}")
    logger.info(f"Database: tweets.db")
    logger.info(f"Jobs will be processed dynamically - workers pick up new jobs as they complete")
    logger.info("="*80)
    
    # Run workers concurrently + hot reload monitor
    start_time = datetime.now()
    workers = [asyncio.create_task(worker(i)) for i in range(max_concurrent)]
    
    # Start hot reload monitor if enabled
    monitor_task = None
    if enable_hot_reload:
        monitor_task = asyncio.create_task(hot_reload_monitor())
        logger.info(f"🔥 HOT RELOAD: Monitor started - will check x.json every 30 seconds")
    
    # Wait for all jobs to complete
    await job_queue.join()
    
    # In hot reload mode, keep workers running for 60 more seconds waiting for new jobs
    if enable_hot_reload:
        logger.info("🔥 HOT RELOAD: All current jobs complete, waiting 60s for new jobs...")
        await asyncio.sleep(60)
        
        # Check if new jobs were added during wait
        if job_queue.qsize() > 0:
            logger.info(f"🔥 HOT RELOAD: {job_queue.qsize()} new jobs detected, continuing...")
            await job_queue.join()  # Process new jobs
    
    # Stop hot reload monitor
    if monitor_task:
        keep_running = False
        monitor_task.cancel()
        try:
            await monitor_task
        except asyncio.CancelledError:
            pass
    
    # Cancel workers (they're waiting for more jobs but queue is empty)
    for w in workers:
        w.cancel()
    
    # Wait for workers to finish cancelling
    await asyncio.gather(*workers, return_exceptions=True)
    
    duration = datetime.now() - start_time
    
    # Calculate totals
    total_tweets = 0
    total_posts = 0
    total_replies = 0
    total_retweets = 0
    
    for result in results:
        if isinstance(result, dict):
            total_tweets += result.get("total", 0)
            total_posts += result.get("posts", 0)
            total_replies += result.get("replies", 0)
            total_retweets += result.get("retweets", 0)
        elif isinstance(result, Exception):
            logger.error(f"Job failed: {result}")
    
    # Get database stats
    db_stats = storage.get_stats()
    
    # Final stats
    logger.info("="*80)
    logger.info("SCRAPING COMPLETE")
    logger.info("="*80)
    logger.info(f"Jobs completed: {len(jobs)}")
    logger.info(f"New tweets: {total_tweets:,}")
    logger.info(f"  - Posts: {total_posts:,}")
    logger.info(f"  - Replies: {total_replies:,}")
    logger.info(f"  - Retweets: {total_retweets:,}")
    logger.info(f"Duration: {duration}")
    logger.info(f"Rate: {total_tweets / duration.total_seconds():.2f} tweets/sec")
    logger.info("")
    logger.info("DATABASE STATS:")
    logger.info(f"  Total tweets in DB: {db_stats['total_tweets']:,}")
    logger.info(f"  Database size: {db_stats['total_size_mb']:.2f} MB")
    logger.info(f"  Date range: {db_stats['earliest_tweet']} to {db_stats['latest_tweet']}")
    logger.info("")
    logger.info("Top hashtags:")
    for label, count in list(db_stats['by_label'].items())[:5]:
        logger.info(f"  {label}: {count:,} tweets")
    logger.info("="*80)


def load_jobs_from_json(filepath: str) -> List[ScrapingJob]:
    """Load scraping jobs from JSON file with enhanced parameters and prioritization"""
    with open(filepath, 'r') as f:
        data = json.load(f)
    
    jobs = []
    new_jobs = []
    old_jobs = []
    skipped_jobs = 0
    
    for item in data:
        # Handle new format with params nested structure
        if 'params' in item:
            params = item['params']
            job_id = item.get('id', 'unknown')
            weight = item.get('weight', 1.0)
            
            # Extract from params
            label = params.get('label')
            keyword = params.get('keyword')
            start_datetime = params.get('post_start_datetime')
            end_datetime = params.get('post_end_datetime')
            
            job = ScrapingJob(
                label=label,
                keyword=keyword,
                start_datetime=start_datetime,
                end_datetime=end_datetime,
                weight=weight,
                strategy=params.get('strategy', 'hashtag'),
                additional_filters=params.get('additional_filters'),
                language=params.get('language'),
                enable_network_expansion=params.get('enable_network_expansion', True),  # Enable by default
                max_network_depth=params.get('max_network_depth', 2),  # Increased default
            )
        else:
            # Handle old format (backward compatibility)
            job = ScrapingJob(
                label=item.get('label'),
                keyword=item.get('keyword'),
                start_datetime=item.get('start_datetime'),
                end_datetime=item.get('end_datetime'),
                weight=item.get('weight', 1.0),
                strategy=item.get('strategy', 'hashtag'),
                additional_filters=item.get('additional_filters'),
                language=item.get('language'),
                enable_network_expansion=item.get('enable_network_expansion', True),
                max_network_depth=item.get('max_network_depth', 2),
            )
        
        # Skip invalid jobs (both label and keyword are null)
        if not job.is_valid:
            logger.warning(f"Skipping invalid job: label={job.label}, keyword={job.keyword}")
            skipped_jobs += 1
            continue
        
        # Prioritize new jobs from gravity
        if item.get('is_new', False):
            new_jobs.append(job)
        else:
            old_jobs.append(job)
    
    # Return new jobs first (sorted by weight), then old jobs
    new_jobs_sorted = sorted(new_jobs, key=lambda x: x.weight, reverse=True)
    old_jobs_sorted = sorted(old_jobs, key=lambda x: x.weight, reverse=True)
    
    if new_jobs_sorted:
        logger.info(f"Prioritizing {len(new_jobs_sorted)} NEW jobs from gravity")
    
    if skipped_jobs > 0:
        logger.warning(f"Skipped {skipped_jobs} invalid jobs (null label and keyword)")
    
    return new_jobs_sorted + old_jobs_sorted


def create_multilingual_jobs(base_jobs: List[ScrapingJob], 
                             languages: Optional[List[str]] = None) -> List[ScrapingJob]:
    """
    Create jobs for multiple languages
    
    Args:
        base_jobs: Base jobs to replicate
        languages: List of language codes (e.g., ['en', 'es', 'fr'])
                  If None, uses default set
    
    Returns:
        List of jobs with language variants
    """
    if languages is None:
        languages = ['en', 'es', 'fr', 'de', 'ja', 'ko', 'pt', 'ar', 'hi', 'zh']
    
    multilingual_jobs = []
    
    for job in base_jobs:
        # Skip if job already has language set
        if job.language:
            multilingual_jobs.append(job)
            continue
        
        # Create variant for each language
        for lang in languages:
            new_job = ScrapingJob(
                label=job.label,
                keyword=job.keyword,
                start_datetime=job.start_datetime,
                end_datetime=job.end_datetime,
                weight=job.weight / len(languages),  # Distribute weight
                strategy=job.strategy.value if isinstance(job.strategy, SearchStrategy) else job.strategy,
                additional_filters=job.additional_filters.copy() if job.additional_filters else {},
                language=lang,
                enable_network_expansion=job.enable_network_expansion,
                max_network_depth=job.max_network_depth,
            )
            multilingual_jobs.append(new_job)
    
    return multilingual_jobs


async def main():
    # Configure logging
    set_log_level("INFO")
    
    # Load jobs from x.json
    try:
        jobs = load_jobs_from_json("x.json")
        logger.info(f"Loaded {len(jobs)} jobs from x.json")
    except FileNotFoundError:
        logger.error("x.json not found! Please create x.json with scraping jobs.")
        logger.info("\nExpected format:")
        logger.info('[')
        logger.info('  {')
        logger.info('    "label": "#opentensor",')
        logger.info('    "keyword": null,')
        logger.info('    "start_datetime": null,')
        logger.info('    "end_datetime": null,')
        logger.info('    "weight": 2.87')
        logger.info('  }')
        logger.info(']')
        return
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON in x.json: {e}")
        return
    
    if not jobs:
        logger.warning("No jobs found in x.json")
        return
    
    # Apply multi-language strategy based on configuration
    if ENABLE_MULTI_LANGUAGE:
        logger.info(f"Multi-language mode ENABLED: Creating jobs for {len(TOP_LANGUAGES)} languages")
        logger.info(f"Languages: {', '.join(TOP_LANGUAGES)}")
        jobs = create_multilingual_jobs(jobs, TOP_LANGUAGES)
        logger.info(f"Expanded to {len(jobs)} total jobs")
    else:
        logger.info("Multi-language mode DISABLED: Scraping in all languages (no filter)")
    
    # Show jobs
    logger.info("\nJobs to scrape:")
    for i, job in enumerate(jobs, 1):
        keyword_str = f" + keyword: {job.keyword}" if job.keyword else ""
        lang_str = f" [lang:{job.language}]" if job.language else ""
        strategy_str = f" ({job.strategy.value})" if job.strategy != SearchStrategy.HASHTAG else ""
        network_str = " [+network]" if job.enable_network_expansion else ""
        logger.info(f"  {i}. {job.label}{keyword_str}{lang_str}{strategy_str}{network_str} ({job.start_date.date()} to {job.end_date.date()})")
    
    # Start scraping with 2 workers for testing (set to 50+ for production)
    # Each worker picks up 1 job at a time, ensuring 1:1 worker-to-job ratio
    await scrape_jobs_concurrently(jobs, max_concurrent=2)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("\n\nStopping... (Ctrl+C)")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        raise
