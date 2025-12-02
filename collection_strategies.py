"""
Collection Strategies Module
Advanced collection methods utilizing all available twscrape API capabilities
"""

from typing import List, Dict, Set, AsyncGenerator
from datetime import datetime, timedelta, timezone
from twscrape import API
from twscrape.logger import logger
from user_analysis import (
    identify_top_contributors,
    calculate_user_relevance_score,
    is_relevant_user,
    filter_duplicate_users
)


async def collect_deep_conversations(
    api: API,
    root_tweet_ids: List[str],
    job_context: dict,
    max_depth: int = 5,
    thirty_days_ago: datetime = None
) -> AsyncGenerator[dict, None]:
    """
    Recursively collect entire conversation trees
    
    Args:
        api: Twitter API instance
        root_tweet_ids: List of tweet IDs to start from
        job_context: Job configuration
        max_depth: Maximum recursion depth
        thirty_days_ago: Cutoff date for collection
        
    Yields:
        Tweet dictionaries
    """
    if thirty_days_ago is None:
        thirty_days_ago = datetime.now(timezone.utc) - timedelta(days=30)
    
    collected_ids = set()
    
    async def recurse_replies(tweet_id: str, depth: int):
        """Recursively collect replies"""
        if depth >= max_depth or tweet_id in collected_ids:
            return
        
        collected_ids.add(tweet_id)
        reply_count = 0
        
        try:
            async for reply in api.tweet_replies(tweet_id, limit=-1):
                if reply.id in collected_ids:
                    continue
                
                # Check date filter
                reply_date = reply.date if hasattr(reply, 'date') else None
                if reply_date and reply_date < thirty_days_ago:
                    continue
                
                collected_ids.add(reply.id)
                
                # Extract metadata
                from aggressive_scrape import extract_rich_metadata
                reply_data = extract_rich_metadata(reply)
                reply_data['collection_method'] = 'deep_conversation'
                reply_data['conversation_depth'] = depth
                
                yield reply_data
                reply_count += 1
                
                # Recursively collect replies to this reply
                async for nested_reply in recurse_replies(reply.id, depth + 1):
                    yield nested_reply
            
            if reply_count > 0:
                logger.debug(f"Collected {reply_count} replies at depth {depth} for tweet {tweet_id}")
                
        except Exception as e:
            logger.warning(f"Error collecting replies for {tweet_id}: {e}")
    
    # Process all root tweets
    for tweet_id in root_tweet_ids:
        async for reply in recurse_replies(tweet_id, 0):
            yield reply


async def collect_influencer_timelines(
    api: API,
    seed_tweets: List[dict],
    job_context: dict,
    top_n: int = 30,
    tweets_per_user: int = 200,
    thirty_days_ago: datetime = None
) -> AsyncGenerator[dict, None]:
    """
    Collect timelines from top influencers discussing the topic
    
    Args:
        api: Twitter API instance
        seed_tweets: Initial tweets to analyze for influencers
        job_context: Job configuration
        top_n: Number of top influencers to collect from
        tweets_per_user: Max tweets to collect per user
        thirty_days_ago: Cutoff date for collection
        
    Yields:
        Tweet dictionaries
    """
    if thirty_days_ago is None:
        thirty_days_ago = datetime.now(timezone.utc) - timedelta(days=30)
    
    logger.info(f"Identifying top {top_n} influencers from {len(seed_tweets)} seed tweets...")
    
    # Identify top contributors
    top_users = identify_top_contributors(seed_tweets, top_n=top_n)
    
    logger.info(f"Collecting timelines from {len(top_users)} influencers...")
    
    for user_id, engagement_score in top_users:
        try:
            tweet_count = 0
            
            # Collect user tweets and replies
            async for tweet in api.user_tweets_and_replies(int(user_id), limit=tweets_per_user):
                # Check date filter
                tweet_date = tweet.date if hasattr(tweet, 'date') else None
                if tweet_date and tweet_date < thirty_days_ago:
                    continue
                
                # Extract metadata
                from aggressive_scrape import extract_rich_metadata
                tweet_data = extract_rich_metadata(tweet)
                tweet_data['collection_method'] = 'influencer_timeline'
                tweet_data['influencer_score'] = engagement_score
                
                yield tweet_data
                tweet_count += 1
            
            if tweet_count > 0:
                logger.info(f"Collected {tweet_count} tweets from influencer {user_id}")
                
        except Exception as e:
            logger.warning(f"Error collecting timeline for user {user_id}: {e}")


async def collect_trending_related(
    api: API,
    job_context: dict,
    tweets_per_trend: int = 300,
    thirty_days_ago: datetime = None
) -> AsyncGenerator[dict, None]:
    """
    Discover and collect from trending topics related to the job
    
    Args:
        api: Twitter API instance
        job_context: Job configuration
        tweets_per_trend: Max tweets per trending topic
        thirty_days_ago: Cutoff date for collection
        
    Yields:
        Tweet dictionaries
    """
    if thirty_days_ago is None:
        thirty_days_ago = datetime.now(timezone.utc) - timedelta(days=30)
    
    job_label = job_context.get('label', '')
    job_keyword = job_context.get('keyword', '')
    
    logger.info("Discovering related trending topics...")
    
    related_trends = []
    
    try:
        # Check multiple trend categories
        for category in ['trending', 'news']:
            async for trend in api.trends(category, limit=50):
                trend_query = trend.name if hasattr(trend, 'name') else str(trend)
                
                # Check if trend is related to job
                if _is_trend_related(trend_query, job_label, job_keyword):
                    related_trends.append(trend_query)
                    logger.info(f"Found related trend: {trend_query}")
        
        # Collect from each related trend
        for trend_query in related_trends[:5]:  # Limit to top 5 trends
            try:
                tweet_count = 0
                
                async for tweet in api.search_trend(trend_query, limit=tweets_per_trend):
                    # Check date filter
                    tweet_date = tweet.date if hasattr(tweet, 'date') else None
                    if tweet_date and tweet_date < thirty_days_ago:
                        continue
                    
                    # Extract metadata
                    from aggressive_scrape import extract_rich_metadata
                    tweet_data = extract_rich_metadata(tweet)
                    tweet_data['collection_method'] = 'trending_discovery'
                    tweet_data['trend_source'] = trend_query
                    
                    yield tweet_data
                    tweet_count += 1
                
                logger.info(f"Collected {tweet_count} tweets from trend '{trend_query}'")
                
            except Exception as e:
                logger.warning(f"Error collecting from trend '{trend_query}': {e}")
                
    except Exception as e:
        logger.warning(f"Error discovering trends: {e}")


async def expand_through_network(
    api: API,
    seed_user_ids: List[str],
    job_context: dict,
    max_depth: int = 2,
    tweets_per_user: int = 100,
    users_per_hop: int = 20,
    thirty_days_ago: datetime = None
) -> AsyncGenerator[dict, None]:
    """
    Discover content through user network exploration
    
    Args:
        api: Twitter API instance
        seed_user_ids: Initial user IDs to explore from
        job_context: Job configuration
        max_depth: Maximum network hops
        tweets_per_user: Max tweets to collect per user
        users_per_hop: Max users to explore per hop
        thirty_days_ago: Cutoff date for collection
        
    Yields:
        Tweet dictionaries
    """
    if thirty_days_ago is None:
        thirty_days_ago = datetime.now(timezone.utc) - timedelta(days=30)
    
    explored_users = set()
    current_hop_users = set(seed_user_ids)
    
    for hop in range(max_depth):
        if not current_hop_users:
            break
        
        logger.info(f"Network expansion hop {hop + 1}/{max_depth}: exploring {len(current_hop_users)} users...")
        
        next_hop_users = set()
        users_processed = 0
        
        for user_id in list(current_hop_users)[:users_per_hop]:
            if user_id in explored_users:
                continue
            
            explored_users.add(user_id)
            users_processed += 1
            
            try:
                # Get user profile to check relevance
                user = await api.user_by_id(int(user_id))
                if not user:
                    continue
                
                user_data = {
                    'followersCount': user.followersCount if hasattr(user, 'followersCount') else 0,
                    'followingCount': user.followingCount if hasattr(user, 'followingCount') else 0,
                    'verified': user.verified if hasattr(user, 'verified') else False,
                    'blueVerified': user.blueVerified if hasattr(user, 'blueVerified') else False,
                    'rawDescription': user.rawDescription if hasattr(user, 'rawDescription') else ''
                }
                
                # Calculate relevance
                relevance_score = calculate_user_relevance_score(user_data, job_context)
                
                if relevance_score < 30:  # Skip low relevance users
                    continue
                
                logger.debug(f"User {user_id} relevance score: {relevance_score}")
                
                # Collect their tweets
                tweet_count = 0
                async for tweet in api.user_tweets(int(user_id), limit=tweets_per_user):
                    # Check date filter
                    tweet_date = tweet.date if hasattr(tweet, 'date') else None
                    if tweet_date and tweet_date < thirty_days_ago:
                        continue
                    
                    # Extract metadata
                    from aggressive_scrape import extract_rich_metadata
                    tweet_data = extract_rich_metadata(tweet)
                    tweet_data['collection_method'] = 'network_expansion'
                    tweet_data['network_hop'] = hop
                    tweet_data['user_relevance_score'] = relevance_score
                    
                    yield tweet_data
                    tweet_count += 1
                
                if tweet_count > 0:
                    logger.debug(f"Collected {tweet_count} tweets from network user {user_id}")
                
                # Explore their network if relevance is high
                if relevance_score > 60 and hop < max_depth - 1:
                    try:
                        # Sample their following list
                        following_count = 0
                        async for following_user in api.following(int(user_id), limit=50):
                            if following_user.id not in explored_users:
                                next_hop_users.add(str(following_user.id))
                                following_count += 1
                        
                        logger.debug(f"Added {following_count} users from {user_id}'s network")
                    except Exception as e:
                        logger.debug(f"Could not explore network of {user_id}: {e}")
                
            except Exception as e:
                logger.warning(f"Error processing network user {user_id}: {e}")
        
        current_hop_users = next_hop_users
        logger.info(f"Hop {hop + 1} complete: processed {users_processed} users, discovered {len(next_hop_users)} new users")


async def collect_from_retweeters(
    api: API,
    seed_tweet_ids: List[str],
    job_context: dict,
    retweeters_per_tweet: int = 100,
    tweets_per_retweeter: int = 50,
    thirty_days_ago: datetime = None
) -> AsyncGenerator[dict, None]:
    """
    Collect tweets from users who retweeted seed content
    
    Args:
        api: Twitter API instance
        seed_tweet_ids: Tweet IDs to find retweeters for
        job_context: Job configuration
        retweeters_per_tweet: Max retweeters to check per tweet
        tweets_per_retweeter: Max tweets to collect per retweeter
        thirty_days_ago: Cutoff date for collection
        
    Yields:
        Tweet dictionaries
    """
    if thirty_days_ago is None:
        thirty_days_ago = datetime.now(timezone.utc) - timedelta(days=30)
    
    processed_users = set()
    
    for tweet_id in seed_tweet_ids[:50]:  # Process up to 50 seed tweets
        try:
            retweeter_count = 0
            
            async for user in api.retweeters(int(tweet_id), limit=retweeters_per_tweet):
                if user.id in processed_users:
                    continue
                
                processed_users.add(user.id)
                
                # Check user relevance
                user_data = {
                    'followersCount': user.followersCount if hasattr(user, 'followersCount') else 0,
                    'followingCount': user.followingCount if hasattr(user, 'followingCount') else 0,
                    'verified': user.verified if hasattr(user, 'verified') else False,
                    'blueVerified': user.blueVerified if hasattr(user, 'blueVerified') else False,
                    'rawDescription': user.rawDescription if hasattr(user, 'rawDescription') else ''
                }
                
                if not is_relevant_user(user_data, job_context, min_followers=50):
                    continue
                
                # Collect their tweets
                tweet_count = 0
                async for tweet in api.user_tweets(user.id, limit=tweets_per_retweeter):
                    # Check date filter
                    tweet_date = tweet.date if hasattr(tweet, 'date') else None
                    if tweet_date and tweet_date < thirty_days_ago:
                        continue
                    
                    # Extract metadata
                    from aggressive_scrape import extract_rich_metadata
                    tweet_data = extract_rich_metadata(tweet)
                    tweet_data['collection_method'] = 'retweeter_discovery'
                    tweet_data['source_tweet_id'] = tweet_id
                    
                    yield tweet_data
                    tweet_count += 1
                
                if tweet_count > 0:
                    retweeter_count += 1
                    logger.debug(f"Collected {tweet_count} tweets from retweeter {user.id}")
            
            if retweeter_count > 0:
                logger.info(f"Collected from {retweeter_count} retweeters of tweet {tweet_id}")
                
        except Exception as e:
            logger.warning(f"Error collecting retweeters for tweet {tweet_id}: {e}")


def _is_trend_related(trend_query: str, job_label: str, job_keyword: str) -> bool:
    """
    Check if a trending topic is related to the job
    
    Args:
        trend_query: Trending topic query string
        job_label: Job label/hashtag
        job_keyword: Job keyword
        
    Returns:
        True if related, False otherwise
    """
    trend_lower = trend_query.lower()
    
    # Check label match
    if job_label:
        label_clean = job_label.lstrip('#').lower()
        if label_clean in trend_lower or trend_lower in label_clean:
            return True
    
    # Check keyword match
    if job_keyword:
        keyword_lower = job_keyword.lower()
        if keyword_lower in trend_lower or trend_lower in keyword_lower:
            return True
    
    # Check for common word overlap (at least 2 words in common)
    if job_keyword:
        trend_words = set(trend_lower.split())
        keyword_words = set(job_keyword.lower().split())
        common_words = trend_words & keyword_words
        
        if len(common_words) >= 2:
            return True
    
    return False


def matches_job_criteria(tweet_data: dict, job_context: dict) -> bool:
    """
    Check if a tweet matches job criteria
    
    Args:
        tweet_data: Tweet data dictionary
        job_context: Job configuration
        
    Returns:
        True if matches, False otherwise
    """
    text = tweet_data.get('text', '').lower()
    
    job_label = job_context.get('label', '')
    job_keyword = job_context.get('keyword', '')
    
    # Check label match
    if job_label:
        label_clean = job_label.lstrip('#').lower()
        if label_clean in text:
            return True
        
        # Check hashtags
        hashtags = tweet_data.get('hashtags', [])
        for hashtag in hashtags:
            if label_clean in hashtag.lower():
                return True
    
    # Check keyword match
    if job_keyword:
        if job_keyword.lower() in text:
            return True
    
    return False
