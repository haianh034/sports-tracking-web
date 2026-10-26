import os
import sys
import argparse
from sqlalchemy import create_engine, text, insert
from sqlalchemy.orm import sessionmaker

# Add project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.core.db.models import (
    Base, Sport, Nationality, Club, Player, NationalTeam,
    MatchPerformance, PlayerNews, NationalTeamNews
)

def migrate(target_url: str, source_sqlite_path: str = "sports_tracker.db"):
    if target_url.startswith("postgres://"):
        target_url = target_url.replace("postgres://", "postgresql://", 1)
    
    # Strip Prisma-specific pgbouncer parameter which breaks psycopg
    if "?pgbouncer=true" in target_url:
        target_url = target_url.replace("?pgbouncer=true", "")
    elif "&pgbouncer=true" in target_url:
        target_url = target_url.replace("&pgbouncer=true", "")

    print(f"Connecting to source SQLite: {source_sqlite_path}...", flush=True)
    src_engine = create_engine(f"sqlite:///{source_sqlite_path}", connect_args={"check_same_thread": False})
    SrcSession = sessionmaker(bind=src_engine)
    src_db = SrcSession()

    print(f"Connecting to target PostgreSQL: {target_url.split('@')[-1]}...", flush=True)
    target_engine = create_engine(target_url, pool_pre_ping=True)

    print("Creating all tables in target database...", flush=True)
    Base.metadata.create_all(bind=target_engine)

    models_order = [
        (Sport, "sports"),
        (Nationality, "nationalities"),
        (Club, "clubs"),
        (Player, "players"),
        (NationalTeam, "national_teams"),
        (MatchPerformance, "match_performances"),
        (PlayerNews, "player_news"),
        (NationalTeamNews, "national_team_news")
    ]

    with target_engine.connect() as conn:
        for model, table_name in models_order:
            items = src_db.query(model).all()
            print(f"Migrating {len(items)} records for '{table_name}'...", flush=True)
            
            # Truncate / delete existing in table to avoid duplicate key violations
            conn.execute(text(f"TRUNCATE TABLE {table_name} CASCADE;"))
            conn.commit()

            if items:
                # Prepare batch records
                records = []
                for item in items:
                    records.append({c.name: getattr(item, c.name) for c in model.__table__.columns})
                
                # Insert in chunks of 500 for lightning-fast network transfer
                chunk_size = 500
                for i in range(0, len(records), chunk_size):
                    chunk = records[i:i + chunk_size]
                    conn.execute(insert(model), chunk)
                    conn.commit()

            # Update sequence in Postgres so future auto-increment inserts don't collide
            try:
                conn.execute(text(f"SELECT setval(pg_get_serial_sequence('{table_name}', 'id'), COALESCE((SELECT MAX(id) FROM {table_name}), 1));"))
                conn.commit()
            except Exception:
                pass

    print("--- MIGRATION COMPLETED SUCCESSFULLY! ---", flush=True)
    
    # Verification
    print("Verification:", flush=True)
    with target_engine.connect() as conn:
        for model, table_name in models_order:
            res = conn.execute(text(f"SELECT COUNT(*) FROM {table_name};")).scalar()
            print(f"  {table_name}: {res} rows", flush=True)

    src_db.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Migrate SQLite to Supabase / PostgreSQL")
    parser.add_argument("--url", type=str, help="PostgreSQL connection URL", default=os.getenv("DATABASE_URL"))
    args = parser.parse_args()

    url = args.url
    if not url:
        url = input("Nhập URL kết nối Supabase (Connection string URI): ").strip()

    if not url:
        print("Lỗi: Bạn chưa nhập URL kết nối!")
        sys.exit(1)

    migrate(url)
