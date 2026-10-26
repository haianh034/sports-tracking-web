import os
import sys
import argparse
from sqlalchemy import create_engine, text
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

    print(f"Connecting to source SQLite: {source_sqlite_path}...")
    src_engine = create_engine(f"sqlite:///{source_sqlite_path}", connect_args={"check_same_thread": False})
    SrcSession = sessionmaker(bind=src_engine)
    src_db = SrcSession()

    print(f"Connecting to target PostgreSQL: {target_url.split('@')[-1]}...")
    target_engine = create_engine(target_url, pool_pre_ping=True)
    TargetSession = sessionmaker(bind=target_engine)
    target_db = TargetSession()

    print("Creating all tables in target database...")
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

    for model, table_name in models_order:
        items = src_db.query(model).all()
        print(f"Migrating {len(items)} records for '{table_name}'...")
        
        # Clear existing in target if needed or skip
        for item in items:
            # Create a detached dict of attributes
            item_data = {c.name: getattr(item, c.name) for c in model.__table__.columns}
            target_obj = model(**item_data)
            target_db.merge(target_obj)
        
        target_db.commit()

        # Update sequence in Postgres so future inserts don't collide
        try:
            with target_engine.connect() as conn:
                conn.execute(text(f"SELECT setval(pg_get_serial_sequence('{table_name}', 'id'), COALESCE((SELECT MAX(id) FROM {table_name}), 1));"))
                conn.commit()
        except Exception:
            pass

    print("--- MIGRATION COMPLETED SUCCESSFULLY! ---")
    
    # Verify counts
    print("Verification:")
    for model, table_name in models_order:
        c = target_db.query(model).count()
        print(f"  {table_name}: {c} rows")

    src_db.close()
    target_db.close()

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
