#!/usr/bin/env python3
"""
Load accounts with tokens from file
Format: username:password:email:email_password:ct0:auth_token:proxy_host:proxy_port:proxy_user:proxy_pass
"""

import asyncio
import sys
from twscrape import AccountsPool
from twscrape.logger import logger, set_log_level

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
    added = await pool.load_accounts_with_tokens(accounts_file)
    
    print()
    print(f"✅ Successfully added {added} accounts!")
    print()
    print("Next steps:")
    print("1. Check accounts: python -m twscrape accounts")
    print("2. Check stats: python -m twscrape stats")
    print("3. Start scraping: python aggressive_scrape.py")

if __name__ == "__main__":
    set_log_level("INFO")
    asyncio.run(main())
