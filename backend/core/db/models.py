from sqlalchemy import Column, Integer, String, Boolean, Float, ForeignKey, DateTime, text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, relationship
import datetime
from backend.core.db.session import engine

class Base(DeclarativeBase):
    pass

class Sport(Base):
    __tablename__ = "sports"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), unique=True, nullable=False, index=True)
    slug = Column(String(100), nullable=True)

    clubs = relationship("Club", back_populates="sport", cascade="all, delete-orphan", passive_deletes=True)
    players = relationship("Player", back_populates="sport", cascade="all, delete-orphan", passive_deletes=True)

class Nationality(Base):
    __tablename__ = "nationalities"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), unique=True, nullable=False, index=True)
    code = Column(String(10), nullable=True)
    flag = Column(String(10), nullable=True)
    timezone = Column(String(50), nullable=True)

    players = relationship("Player", back_populates="nationality", cascade="all, delete-orphan", passive_deletes=True)
    clubs = relationship("Club", back_populates="country")

class Club(Base):
    __tablename__ = "clubs"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(150), nullable=False, index=True)
    sport_id = Column(Integer, ForeignKey("sports.id", ondelete="CASCADE"), nullable=False)
    country_id = Column(Integer, ForeignKey("nationalities.id", ondelete="SET NULL"), nullable=True)
    api_team_id = Column(String(50), nullable=True)

    sport = relationship("Sport", back_populates="clubs")
    country = relationship("Nationality", back_populates="clubs")
    players = relationship("Player", back_populates="club")

    __table_args__ = (
        UniqueConstraint("name", "sport_id", name="uq_club_name_sport"),
    )

class Player(Base):
    __tablename__ = "players"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(150), nullable=False, index=True)
    sport_id = Column(Integer, ForeignKey("sports.id", ondelete="CASCADE"), nullable=False, index=True)
    country_id = Column(Integer, ForeignKey("nationalities.id", ondelete="CASCADE"), nullable=False, index=True)
    club_id = Column(Integer, ForeignKey("clubs.id", ondelete="SET NULL"), nullable=True, index=True)
    
    api_player_id = Column(String(50), nullable=True)
    api_team_id = Column(String(50), nullable=True)
    name_aliases = Column(String(255), nullable=True)

    sport = relationship("Sport", back_populates="players")
    nationality = relationship("Nationality", back_populates="players")
    club = relationship("Club", back_populates="players")

    performances = relationship("MatchPerformance", back_populates="player", cascade="all, delete-orphan", passive_deletes=True)
    news = relationship("PlayerNews", back_populates="player", cascade="all, delete-orphan", passive_deletes=True)

    @property
    def sport_name(self) -> str:
        return self.sport.name if self.sport else "Môn khác"

    @property
    def country_name(self) -> str:
        return self.nationality.name if self.nationality else "Quốc tế"

    @property
    def team_name(self) -> str:
        return self.club.name if self.club else "Tự do"

class MatchPerformance(Base):
    __tablename__ = "match_performances"
    id = Column(Integer, primary_key=True, index=True)
    player_id = Column(Integer, ForeignKey("players.id", ondelete="CASCADE"), nullable=False, index=True)
    match_name = Column(String, nullable=True)
    match_date = Column(DateTime, nullable=True)
    has_played = Column(Boolean, default=False)
    performance_rating = Column(Float, nullable=True)
    impression_tags = Column(String, nullable=True)
    match_state = Column(String, default="pre")
    match_result = Column(String, nullable=True)
    player_stats = Column(String, nullable=True)
    competition = Column(String, nullable=True)
    event_id = Column(String(50), nullable=True, index=True)
    date_str = Column(String(20), nullable=True, index=True)

    player = relationship("Player", back_populates="performances")

class PlayerNews(Base):
    __tablename__ = "player_news"
    id = Column(Integer, primary_key=True, index=True)
    player_id = Column(Integer, ForeignKey("players.id", ondelete="CASCADE"), nullable=False, index=True)
    title = Column(String, nullable=False)
    source_url = Column(String, nullable=False)
    news_type = Column(String, nullable=True)
    region = Column(String, default="US")
    published_at = Column(DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None))

    player = relationship("Player", back_populates="news")

class NationalTeam(Base):
    __tablename__ = "national_teams"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(150), nullable=False, index=True)
    short_name = Column(String(100), nullable=True)
    nickname = Column(String(100), nullable=True)
    sport_id = Column(Integer, ForeignKey("sports.id", ondelete="CASCADE"), nullable=False, index=True)
    country_id = Column(Integer, ForeignKey("nationalities.id", ondelete="CASCADE"), nullable=False, index=True)
    tier = Column(String(50), default="Senior", index=True)
    gender = Column(String(20), default="Men")
    api_team_id = Column(String(50), nullable=True)
    flag = Column(String(10), default="🌐")
    search_query = Column(String(255), nullable=True)
    description = Column(String(255), nullable=True)

    sport = relationship("Sport")
    nationality = relationship("Nationality")
    news = relationship("NationalTeamNews", back_populates="team", cascade="all, delete-orphan", passive_deletes=True)

    @property
    def sport_name(self) -> str:
        return self.sport.name if self.sport else "Môn khác"

    @property
    def country_name(self) -> str:
        return self.nationality.name if self.nationality else "Quốc tế"

class NationalTeamNews(Base):
    __tablename__ = "national_team_news"
    id = Column(Integer, primary_key=True, index=True)
    team_id = Column(Integer, ForeignKey("national_teams.id", ondelete="CASCADE"), nullable=False, index=True)
    title = Column(String, nullable=False)
    source_url = Column(String, nullable=False)
    news_type = Column(String, nullable=True)
    region = Column(String, default="Châu Á")
    published_at = Column(DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None), index=True)

    team = relationship("NationalTeam", back_populates="news")

def init_db():
    Base.metadata.create_all(bind=engine)
    with engine.connect() as conn:
        try:
            # Create indexes if not exist
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_players_sport_id ON players(sport_id)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_players_country_id ON players(country_id)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_players_club_id ON players(club_id)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_matches_player_id ON match_performances(player_id)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_news_player_id ON player_news(player_id)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_national_teams_sport ON national_teams(sport_id)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_national_teams_country ON national_teams(country_id)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_national_news_team_id ON national_team_news(team_id)"))
            conn.commit()
        except Exception:
            pass
