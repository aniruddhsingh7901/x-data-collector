#!/usr/bin/env python3
"""
Enhanced Aggressive Scraping System
Includes: Multiple search strategies, network expansion, multi-language support,
smart pagination, and advanced search operators
"""

import asyncio
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Optional, Set
from enum import Enum
from twscrape import API
from twscrape.logger import set_log_level, logger
from storage_sqlite import TweetStorage


class SearchStrategy(Enum):
    """Different search strategies for data collection"""
    HASHTAG = "hashtag"
    KEYWORD = "keyword"
    USER = "user"
    LOCATION = "location"
    ADVANCED = "advanced"
    TRENDING = "trending"


class ScrapingJob:
    """Enhanced scraping job with multiple strategies and filters"""
    
    def __init__(
        self, 
        label: str, 
        keyword: Optional[str] = None,
        start_datetime: Optional[str] = None,
        end_datetime: Optional[str] = None,
        weight: float = 1.0,
        strategy: str = "hashtag",
        additional_filters: Optional[Dict] = None,
        expand_network: bool = False,
        language: Optional[str] = None
    ):
        self.label = label
        self.keyword = keyword
        self.start_datetime = start_datetime
        self.end_datetime = end_datetime
        self.weight = weight
        self.strategy = strategy
        self.additional_filters = additional_filters or {}
        self.expand_network = expand_network
        self.language = language
        
        # Parse dates or use defaults (last 30 days)
        if end_datetime:
            self.end_date = datetime.fromisoformat(end_datetime.replace('Z', '+00:00'))
        else:
            self.end_date = datetime.now()
        
        if start_datetime:
            self.start_date = datetime.fromisoformat(start_datetime.replace('Z', '+00:00'))
        else:
            self.start_date = self.end_date - timedelta(days=30)
    
    def build_query(self) -> str:
        """Enhanced query builder with multiple strategies and operators"""
        query_parts = []
        
        # Strategy-specific query building
        if self.strategy == "hashtag":
            query_parts.append(self.label)
        elif self.strategy == "keyword":
            query_parts.append(f'"{self.label}"')  # Exact phrase
        elif self.strategy == "user":
            query_parts.append(f"from:{self.label}")
        elif self.strategy == "location":
            query_parts.append(f"near:{self.label}")
        elif self.strategy == "advanced":
            # For advanced, label is the full query
            query_parts.append(self.label)
        
        # Add keyword filter
        if self.keyword:
            query_parts.append(self.keyword)
        
        # Advanced filters
        if self.additional_filters.get('min_likes'):
            query_parts.append(f"min_faves:{self.additional_filters['min_likes']}")
        if self.additional_filters.get('min_retweets'):
            query_parts.append(f"min_retweets:{self.additional_filters['min_retweets']}")
        if self.additional_filters.get('min_replies'):
            query_parts.append(f"min_replies:{self.additional_filters['min_replies']}")
        
        # Content filters
        if self.additional_filters.get('has_media'):
            query_parts.append("filter:media")
        if self.additional_filters.get('has_video'):
            query_parts.append("filter:videos")
        if self.additional_filters.get('has_images'):
            query_parts.append("filter:images")
        if self.additional_filters.get('has_links'):
            query_parts.append("filter:links")
        if self.additional_filters.get('is_reply'):
            query_parts.append("filter:replies")
        if self.additional_filters.get('is_quote'):
            query_parts.append("filter:quote")
        
        # User filters
        if self.additional_filters.get('verified_only'):
            query_parts.append("filter:verified")
        if self.additional_filters.get('blue_verified_only'):
            query_parts.append("filter:blue_verified")
        
        # Mention/interaction filters
        if self.additional_filters.get('to_user'):
            query_parts.append(f"to:{self.additional_filters['to_user']}")
        if self.additional_filters.get('mentions'):
            query_parts.append(f"@{self.additional_filters['mentions']}")
        if self.additional_filters.get('url_contains'):
            query_parts.append(f"url:{self.additional_filters['url_contains']}")
        
        # Language filter
        if self.language:
            query_parts.append(f"lang:{self.language}")
        elif self.additional_filters.get('language'):
            query_parts.append(f"lang:{self.additional_filters['language']}")
        
        # Exclude filters
        if self.additional_filters.get('exclude_retweets'):
            query_parts.append("-filter:retweets")
        if self.additional_filters.get('exclude_replies'):
            query_parts.append("-filter:replies")
        if self.additional_filters.get('exclude_quotes'):
            query_parts.append("-filter:quote")
        
        # Date range
        query_parts.append(f"since:{self.start_date.strftime('%Y-%m-%d')}")
        query_parts.append(f"until:{self.end_date.strftime('%Y-%m-%d')}")
        
        return " ".join(query_parts)
    
    def __repr__(self):
        strategy_str = f"[{self.strategy}]"
        keyword_str = f" + keyword: {self.keyword}" if self.keyword else ""
        lang_str = f" + lang: {self.language}" if self.language else ""
        return f"Job{strategy_str}({self.label}{keyword_str}{lang_str}, {self.start_date.date()} to {self.end_date.date()})"


def extract_rich_metadata(tweet) -> Dict:
    """
    Extract rich metadata from tweet object
    Similar to ApiDojoTwitterScraper parsing logic
    """
    try:
        # Basic tweet data
        tweet_data = {
            'id': str(tweet.id),
            'url': tweet.url,
            'username': tweet.user.username,
            'user_id': str(tweet.user.id) if hasattr(tweet.user, 'id') else None,
            'user_display_name': tweet.user.displayname if hasattr(tweet.user, 'displayname') else None,
            'text': tweet.rawContent,
            'timestamp': tweet.date,
            'source': 2,  # X/Twitter
        }
        
        # Tweet metadata
        tweet_data['language'] = tweet.lang if hasattr(tweet, 'lang') else None
        tweet_data['is_reply'] = tweet.inReplyToTweetId is not None
        tweet_data['is_retweet'] = tweet.retweetedTweet is not None
        tweet_data['is_quote'] = tweet.quotedTweet is not None
        tweet_data['in_reply_to_user_id'] = str(tweet.inReplyToTweetId) if tweet.inReplyToTweetId else None
        tweet_data['quoted_tweet_id'] = str(tweet.quotedTweet.id) if tweet.quotedTweet else None
        tweet_data['conversation_id'] = str(tweet.conversationId) if hasattr(tweet, 'conversationId') else None
        
        # Engagement metrics
        tweet_data['like_count'] = tweet.likeCount if hasattr(tweet, 'likeCount') else None
        tweet_data['retweet_count'] = tweet.retweetCount if hasattr(tweet, 'retweetCount') else None
        tweet_data['reply_count'] = tweet.replyCount if hasattr(tweet, 'replyCount') else None
        tweet_data['quote_count'] = tweet.quoteCount if hasattr(tweet, 'quoteCount') else None
        tweet_data['view_count'] = tweet.viewCount if hasattr(tweet, 'viewCount') else None
        tweet_data['bookmark_count'] = tweet.bookmarkCount if hasattr(tweet, 'bookmarkCount') else None
        
        # User profile data
        if hasattr(tweet, 'user') and tweet.user:
            user = tweet.user
            tweet_data['user_verified'] = getattr(user, 'verified', False)
            tweet_data['user_blue_verified'] = getattr(user, 'blueVerified', False)
            tweet_data['user_description'] = getattr(user, 'rawDescription', None)
            tweet_data['user_location'] = getattr(user, 'location', None)
            tweet_data['user_followers_count'] = getattr(user, 'followersCount', None)
            tweet_data['user_following_count'] = getattr(user, 'followingCount', None)
            tweet_data['profile_image_url'] = getattr(user, 'profileImageUrl', None)
        
        # Hashtags
        tweet_data['hashtags'] = tweet.hashtags if hasattr(tweet, 'hashtags') else []
        
        # Media URLs
        media_urls = []
        if hasattr(tweet, 'media') and tweet.media:
            if hasattr(tweet.media, 'photos'):
                for photo in tweet.media.photos:
                    media_urls.append(photo.url if hasattr(photo, 'url') else str(photo))
            if hasattr(tweet.media, 'videos'):
                for video in tweet.media.videos:
                    if hasattr(video, 'thumbnailUrl'):
                        media_urls.append(video.thumbnailUrl)
        tweet_data['media_urls'] = media_urls
        
        return tweet_data
    
    except Exception as e:
        logger.warning(f"Error extracting metadata: {e}")
        # Return basic data on error
        return {
            'id': str(tweet.id),
            'url': tweet.url,
            'username': tweet.user.username,
            'text': tweet.rawContent,
            'timestamp': tweet.date,
            'source': 2,
        }


async def expand_network(
    api: API, 
    storage: TweetStorage, 
    seed_tweet_ids: List[str],
    job_label: str,
    max_replies: int = 50,
    max_retweeters: int = 20
) -> Set[str]:
    """
