#!/usr/bin/env python3
"""
Load accounts with tokens from file
Format: username:password:email:email_password:ct0:auth_token:proxy_host:proxy_port:proxy_user:proxy_pass
"""

import asyncio
import sys
from twscrape import AccountsPool
from twscrape.logger import logger, set_log_level

async def load_accounts_with_tokens(pool: AccountsPool, accounts_file: str):
    """Load accounts with pre-existing tokens from file"""
    added = 0
    
    with open(accounts_file, 'r') as f:
        lines = f.readlines()
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
        
        try:
            # Parse format: username:password:email:email_password:ct0:auth_token:proxy_host:proxy_port:proxy_user:proxy_pass
            parts = line.split(':')
            
            if len(parts) < 10:
                logger.warning(f"Invalid line format (expected 10 fields): {line[:50]}...")
                continue
            
            username = parts[0]
            password = parts[1]
            email = parts[2]
            email_password = parts[3]
            ct0 = parts[4]
            auth_token = parts[5]
            proxy_host = parts[6]
            proxy_port = parts[7]
            proxy_user = parts[8]
            proxy_pass = parts[9]
            
            # Build proxy URL
            proxy = f"http://{proxy_user}:{proxy_pass}@{proxy_host}:{proxy_port}"
            
            # Build cookies string with ct0 and auth_token
            cookies = f"ct0={ct0}; auth_token={auth_token}"
            
            # Add account with cookies (this will mark it as active)
            await pool.add_account(
                username=username,
                password=password,
                email=email,
                email_password=email_password,
                proxy=proxy,
                cookies=cookies
            )
            
            added += 1
            logger.info(f"Added account {username} with tokens (active=True)")
            
        except Exception as e:
            logger.error(f"Error processing line: {str(e)}")
            logger.error(f"Line: {line[:100]}...")
            continue
    
    return added

async def main():
    if len(sys.argv) < 2:
        print("Usage: python load_accounts.py accounts.txt")
        print("\nFile format (one account per line):")
        print("username:password:email:email_password:ct0:auth_token:proxy_host:proxy_port:proxy_user:proxy_pass")
        print("\nExample:")
        print("user1:pass1:user1@mail.com:mailpass:d0dc507...:cbb381e...:5.249.176.154:5432:user:pass")
        sys.exit(1)
    
    accounts_file = sys.argv[1]
    
    print(f"Loading accounts from {accounts_file}...")
    print()
    
    # Initialize pool
    pool = AccountsPool("accounts.db")
    
    # Load accounts with tokens
    added = await load_accounts_with_tokens(pool, accounts_file)
    
    print()
    print(f"✅ Successfully added {added} accounts with tokens!")
    print()
    print("Next steps:")
    print("1. Check accounts: python -m twscrape accounts")
    print("2. Check stats: python -m twscrape stats")
    print("3. Start scraping: python aggressive_scrape.py")

if __name__ == "__main__":
    set_log_level("INFO")
    asyncio.run(main())
