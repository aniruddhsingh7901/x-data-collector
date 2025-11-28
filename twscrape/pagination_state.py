"""
Pagination State Manager - Tracks pagination cursors across account switches

This allows seamless continuation of pagination when accounts get rate limited.
When Account A hits rate limit mid-pagination, Account B can continue from the same cursor.
"""

import asyncio
import hashlib
import json
import sqlite3
from datetime import datetime
from typing import Dict, Optional

import aiosqlite

from .logger import logger
from .utils import utc


class PaginationStateManager:
    """
    Manages pagination cursors across multiple accounts
    
    Features:
    - Tracks cursors per query (identified by query hash)
    - Allows seamless account switching during pagination
    - Persists state to database for recovery
    - Cleans up completed queries
    """
    
    def __init__(self, db_path: str = "pagination_state.db"):
        self.db_path = db_path
        self._lock = asyncio.Lock()
        self._initialized = False
    
    async def _init_db(self):
        """Initialize database schema"""
        if self._initialized:
            return
        
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS pagination_states (
                    query_hash TEXT PRIMARY KEY,
                    query_text TEXT NOT NULL,
                    cursor TEXT,
                    items_fetched INTEGER DEFAULT 0,
                    last_account TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    completed BOOLEAN DEFAULT 0
                )
            """)
            
            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_updated_at 
                ON pagination_states(updated_at)
            """)
            
            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_completed 
                ON pagination_states(completed)
            """)
            
            await db.commit()
        
        self._initialized = True
        logger.debug("Pagination state database initialized")
    
    def generate_query_hash(self, query: str, params: Dict = None) -> str:
        """
        Generate unique hash for query + parameters
        
        Args:
            query: Search query or operation
            params: Additional parameters (e.g., filters, options)
        
        Returns:
            MD5 hash as hex string
        """
        params_str = json.dumps(params or {}, sort_keys=True)
        combined = f"{query}:{params_str}"
        return hashlib.md5(combined.encode()).hexdigest()
    
    async def get_state(self, query_hash: str) -> Optional[Dict]:
        """
        Get pagination state for query
        
        Args:
            query_hash: Hash of query + parameters
        
        Returns:
            Dictionary with cursor, count, etc. or None
        """
        await self._init_db()
        
        async with self._lock:
            async with aiosqlite.connect(self.db_path) as db:
                db.row_factory = aiosqlite.Row
                async with db.execute(
                    "SELECT * FROM pagination_states WHERE query_hash = ?",
                    (query_hash,)
                ) as cursor:
                    row = await cursor.fetchone()
                    if row:
                        return dict(row)
                    return None
    
    async def get_cursor(self, query_hash: str) -> Optional[str]:
        """
        Get continuation cursor for query
        
        Args:
            query_hash: Hash of query + parameters
        
        Returns:
            Cursor string or None if no state exists
        """
        state = await self.get_state(query_hash)
        if state and not state.get("completed"):
            return state.get("cursor")
        return None
    
    async def create_or_update_state(
        self,
        query_hash: str,
        query_text: str,
        cursor: Optional[str] = None,
        items_fetched: int = 0,
        account: Optional[str] = None,
        completed: bool = False
    ):
        """
        Create or update pagination state
        
        Args:
            query_hash: Hash of query + parameters
            query_text: Human-readable query string
            cursor: Current pagination cursor
            items_fetched: Number of items fetched so far
            account: Last account used
            completed: Whether pagination is complete
        """
        await self._init_db()
        
        async with self._lock:
            async with aiosqlite.connect(self.db_path) as db:
                now = utc.now().isoformat()
                
                # Check if exists
                async with db.execute(
                    "SELECT query_hash FROM pagination_states WHERE query_hash = ?",
                    (query_hash,)
                ) as check_cursor:
                    exists = await check_cursor.fetchone()
                
                if exists:
                    # Update existing
                    await db.execute("""
                        UPDATE pagination_states 
                        SET cursor = ?,
                            items_fetched = items_fetched + ?,
                            last_account = ?,
                            updated_at = ?,
                            completed = ?
                        WHERE query_hash = ?
                    """, (cursor, items_fetched, account, now, completed, query_hash))
                else:
                    # Create new
                    await db.execute("""
                        INSERT INTO pagination_states 
                        (query_hash, query_text, cursor, items_fetched, 
                         last_account, created_at, updated_at, completed)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """, (query_hash, query_text, cursor, items_fetched, 
                          account, now, now, completed))
                
                await db.commit()
        
        status = "completed" if completed else f"continuing (cursor: {cursor[:20] if cursor else 'None'}...)"
        logger.debug(f"Pagination state {status} for query {query_hash[:8]}")
    
    async def mark_completed(self, query_hash: str):
        """
        Mark query as completed
        
        Args:
            query_hash: Hash of query + parameters
        """
        await self.create_or_update_state(
            query_hash=query_hash,
            query_text="",
            completed=True
        )
        logger.info(f"Query {query_hash[:8]} marked as completed")
    
    async def get_active_queries(self) -> list[Dict]:
        """
        Get all active (incomplete) queries
        
        Returns:
            List of query states
        """
        await self._init_db()
        
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM pagination_states WHERE completed = 0 ORDER BY updated_at DESC"
            ) as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]
    
    async def cleanup_old_states(self, days: int = 7):
        """
        Clean up completed or stale states
        
        Args:
            days: Remove states older than this many days
        """
        await self._init_db()
        
        cutoff = utc.now().timestamp() - (days * 86400)
        cutoff_iso = datetime.fromtimestamp(cutoff).isoformat()
        
        async with self._lock:
            async with aiosqlite.connect(self.db_path) as db:
                async with db.execute(
                    "DELETE FROM pagination_states WHERE updated_at < ? AND completed = 1",
                    (cutoff_iso,)
                ) as cursor:
                    deleted = cursor.rowcount
                
                await db.commit()
        
        if deleted > 0:
            logger.info(f"Cleaned up {deleted} old pagination states")
    
    async def get_stats(self) -> Dict:
        """
        Get statistics about pagination states
        
        Returns:
            Dictionary with counts and metrics
        """
        await self._init_db()
        
        async with aiosqlite.connect(self.db_path) as db:
            stats = {}
            
            # Total states
            async with db.execute("SELECT COUNT(*) FROM pagination_states") as cursor:
                stats["total"] = (await cursor.fetchone())[0]
            
            # Active states
            async with db.execute(
                "SELECT COUNT(*) FROM pagination_states WHERE completed = 0"
            ) as cursor:
                stats["active"] = (await cursor.fetchone())[0]
            
            # Completed states
            async with db.execute(
                "SELECT COUNT(*) FROM pagination_states WHERE completed = 1"
            ) as cursor:
                stats["completed"] = (await cursor.fetchone())[0]
            
            # Total items fetched
            async with db.execute(
                "SELECT SUM(items_fetched) FROM pagination_states"
            ) as cursor:
                result = await cursor.fetchone()
                stats["total_items"] = result[0] if result[0] else 0
        
        return stats
