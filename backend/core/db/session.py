from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from backend.core.config import DATABASE_URL

is_sqlite = DATABASE_URL.startswith("sqlite")

if is_sqlite:
    engine = create_engine(
        DATABASE_URL,
        connect_args={"check_same_thread": False, "timeout": 60}
    )

    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON;")
        cursor.execute("PRAGMA journal_mode=WAL;")
        cursor.execute("PRAGMA synchronous=NORMAL;")
        cursor.execute("PRAGMA busy_timeout=60000;")
        cursor.execute("PRAGMA temp_store=MEMORY;")
        cursor.close()
else:
    pg_connect_args = {}
    try:
        import psycopg
        # Disable server-side prepared statements for Supabase PgBouncer (Transaction mode)
        pg_connect_args["prepare_threshold"] = None
    except ImportError:
        pass

    engine = create_engine(
        DATABASE_URL,
        connect_args=pg_connect_args,
        pool_pre_ping=True,
        pool_size=10,
        max_overflow=20
    )

SessionLocal = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
