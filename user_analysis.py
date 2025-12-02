"""
User Analysis Module
Provides utilities for identifying and scoring influential users for data collection
"""

from typing import Dict, List, Tuple, Set
from datetime import datetime, timezone
from twscrape.logger import logger


def calculate_user_engagement_score(tweet_data: dict) -> float:
    """
    Calculate engagement score for a user based on tweet metrics
    
    Args:
        tweet_data: Dictionary containing tweet metrics
        
    Returns:
        Engagement score (higher = more influential)
    """
    like_count = tweet_data.get('like_count', 0) or 0
    retweet_count = tweet_data.get('retweet_count', 0) or 0
    reply_count = tweet_data.get('reply_count', 0) or 0
    quote_count = tweet_data.get('quote_count', 0) or 0
    view_count = tweet_data.get('view_count', 0) or 0
    
    # Weighted engagement score
    # Likes: 1x, Retweets: 3x, Replies: 2x, Quotes: 2.5x, Views: 0.001x
    score = (
        like_count * 1.0 +
        retweet_count * 3.0 +
        reply_count * 2.0 +
        quote_count * 2.5 +
        view_count * 0.001
    )
    
    # Bonus for verified users
    if tweet_data.get('user_verified', False):
        score *= 1.5
    
    return score


def identify_top_contributors(tweets: List[dict], top_n: int = 50) -> List[Tuple[str, float]]:
    """
    Identify top contributing users based on engagement scores
    
    Args:
        tweets: List of tweet dictionaries
        top_n: Number of top users to return
        
    Returns:
        List of (user_id, total_score) tuples
    """
    user_scores = {}
    
    for tweet in tweets:
        user_id = tweet.get('user_id')
        if not user_id:
            continue
        
        score = calculate_user_engagement_score(tweet)
        user_scores[user_id] = user_scores.get(user_id, 0) + score
    
    # Sort by score and return top N
    sorted_users = sorted(user_scores.items(), key=lambda x: x[1], reverse=True)
    return sorted_users[:top_n]


def is_relevant_user(user_data: dict, job_context: dict, min_followers: int = 100) -> bool:
    """
    Determine if a user is relevant for collection based on job context
    
    Args:
        user_data: User profile data
        job_context: Job configuration with keywords/labels
        min_followers: Minimum follower count threshold
        
    Returns:
        True if user is relevant, False otherwise
    """
    # Check minimum follower threshold
    followers_count = user_data.get('followersCount', 0) or 0
    if followers_count < min_followers:
        return False
    
    # Prefer verified accounts
    if user_data.get('verified', False) or user_data.get('blueVerified', False):
        return True
    
    # Check if user bio/description contains job keywords
    description = user_data.get('rawDescription', '') or ''
    job_label = job_context.get('label', '')
    job_keyword = job_context.get('keyword', '')
    
    description_lower = description.lower()
    
    if job_label and job_label.lstrip('#').lower() in description_lower:
        return True
    
    if job_keyword and job_keyword.lower() in description_lower:
        return True
    
    # Check recent activity relevance
    # If user has high engagement on topic, they're relevant
    return followers_count > 1000  # Higher threshold for non-verified


def calculate_user_relevance_score(user_data: dict, job_context: dict) -> float:
    """
    Calculate a relevance score for a user in context of a job
    
    Args:
        user_data: User profile data
        job_context: Job configuration
        
    Returns:
        Relevance score (0-100)
    """
    score = 0.0
    
    # Follower count factor (log scale, max 30 points)
    followers_count = user_data.get('followersCount', 0) or 0
    if followers_count > 0:
        import math
        score += min(30, math.log10(followers_count) * 10)
    
    # Verified status (20 points)
    if user_data.get('verified', False) or user_data.get('blueVerified', False):
        score += 20
    
    # Bio relevance (30 points)
    description = user_data.get('rawDescription', '') or ''
    job_label = job_context.get('label', '')
    job_keyword = job_context.get('keyword', '')
    
    description_lower = description.lower()
    
    if job_label and job_label.lstrip('#').lower() in description_lower:
        score += 15
    
    if job_keyword and job_keyword.lower() in description_lower:
        score += 15
    
    # Activity level (20 points based on following/followers ratio)
    following_count = user_data.get('followingCount', 0) or 0
    if followers_count > 0 and following_count > 0:
        ratio = followers_count / max(following_count, 1)
        # Higher ratio = more influential (but cap at 10:1)
        score += min(20, ratio * 2)
    
    return min(100, score)


def filter_duplicate_users(user_ids: List[str], already_processed: Set[str]) -> List[str]:
    """
    Filter out users that have already been processed
    
    Args:
        user_ids: List of user IDs to check
        already_processed: Set of already processed user IDs
        
    Returns:
        List of new user IDs to process
    """
    return [uid for uid in user_ids if uid not in already_processed]


def should_explore_user_network(user_data: dict, depth: int, max_depth: int) -> bool:
    """
    Determine if we should explore a user's network based on their profile
    
    Args:
        user_data: User profile data
        depth: Current exploration depth
        max_depth: Maximum allowed depth
        
    Returns:
        True if network should be explored, False otherwise
    """
    if depth >= max_depth:
        return False
    
    # Only explore networks of influential users
    followers_count = user_data.get('followersCount', 0) or 0
    
    # Minimum thresholds increase with depth
    min_followers_by_depth = {
        0: 100,
        1: 500,
        2: 1000,
        3: 5000,
        4: 10000
    }
    
    threshold = min_followers_by_depth.get(depth, 50000)
    
    return followers_count >= threshold
