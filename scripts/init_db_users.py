#!/usr/bin/env python3
"""
Initialize database users for split-connections feature.
This script creates the voting_admin and voting_voter users if they don't exist.
"""

import os
import pymysql
import time

def wait_for_db():
    """Wait for the database to be ready."""
    root_password = os.environ.get('MYSQL_ROOT_PASSWORD', 'rootpass')
    db_host = os.environ.get('DB_HOST', 'db')
    db_port = int(os.environ.get('DB_PORT', 3306))

    print("⏳ Waiting for database to be ready...")
    attempts = 0
    max_attempts = 30
    delay = 2
    while attempts < max_attempts:
        try:
            conn = pymysql.connect(
                host=db_host,
                port=db_port,
                user='root',
                password=root_password,
                database='mysql'  # Connect to mysql db for user creation
            )
            conn.close()
            print("✅ Database is ready!")
            return
        except Exception as e:
            attempts += 1
            if attempts >= max_attempts:
                print(f"❌ Database not ready after {max_attempts} attempts: {e}")
                raise
            print(f"Database not ready (attempt {attempts}/{max_attempts}): {e}. Retrying in {delay} seconds...")
            time.sleep(delay)

def create_db_users():
    # Connect as root to create users
    root_password = os.environ.get('MYSQL_ROOT_PASSWORD', 'rootpass')
    db_host = os.environ.get('DB_HOST', 'db')
    db_port = int(os.environ.get('DB_PORT', 3306))

    try:
        conn = pymysql.connect(
            host=db_host,
            port=db_port,
            user='root',
            password=root_password,
            database='mysql'  # Connect to mysql db for user creation
        )
        with conn.cursor() as cursor:
            # Create users if they don't exist
            cursor.execute("""
                CREATE USER IF NOT EXISTS 'voting_admin'@'%' IDENTIFIED WITH caching_sha2_password BY 'adminpass'
            """)
            cursor.execute("""
                CREATE USER IF NOT EXISTS 'voting_voter'@'%' IDENTIFIED WITH caching_sha2_password BY 'voterpass'
            """)
            # Grant permissions
            # Admin user: full access except vote table modifications
            cursor.execute("GRANT ALL PRIVILEGES ON votingdb.* TO 'voting_admin'@'%'")
            try:
                cursor.execute("REVOKE INSERT, UPDATE, DELETE ON votingdb.vote FROM 'voting_admin'@'%'")
            except pymysql.err.OperationalError as e:
                if e.args[0] == 1147:  # No such grant defined
                    pass
                else:
                    raise

            # Voter user: read access to all, insert on vote, update has_voted on user
            cursor.execute("GRANT SELECT ON votingdb.* TO 'voting_voter'@'%'")
            cursor.execute("GRANT INSERT ON votingdb.vote TO 'voting_voter'@'%'")
            cursor.execute("GRANT UPDATE (has_voted) ON votingdb.user TO 'voting_voter'@'%'")

            cursor.execute("FLUSH PRIVILEGES")
        conn.commit()
        print("✅ Database users created successfully")
    except Exception as e:
        print(f"❌ Failed to create database users: {e}")
        raise
    finally:
        if 'conn' in locals():
            conn.close()

if __name__ == "__main__":
    wait_for_db()
    create_db_users()