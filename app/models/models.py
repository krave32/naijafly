from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, Boolean, Enum
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
import enum
from datetime import datetime

Base = declarative_base()

class StatusType(enum.Enum):
    BOARDING = "boarding"
    GATE_CHANGE = "gate_change"
    DELAY = "delay"
    NOT_BOARDING = "not_boarding"
    OTHER = "other"

class ReportStatus(enum.Enum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    DISPUTED = "disputed"
    ARCHIVED = "archived"

class Route(Base):
    __tablename__ = "routes"
    id = Column(Integer, primary_key=True)
    origin = Column(String, index=True) # e.g. LOS, ACC
    destination = Column(String, index=True)
    fares = relationship("Fare", back_populates="route")

class Fare(Base):
    __tablename__ = "fares"
    id = Column(Integer, primary_key=True)
    route_id = Column(Integer, ForeignKey("routes.id"))
    price = Column(Float)
    currency = Column(String) # NGN, GHS, USD
    source = Column(String) # Air Peace, Dana, Mock
    flight_date = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    route = relationship("Route", back_populates="fares")

class Flight(Base):
    __tablename__ = "flights"
    id = Column(Integer, primary_key=True)
    flight_number = Column(String, index=True) # e.g. P47123
    date = Column(DateTime)
    reports = relationship("StatusReport", back_populates="flight")

class StatusReport(Base):
    __tablename__ = "status_reports"
    id = Column(Integer, primary_key=True)
    flight_id = Column(Integer, ForeignKey("flights.id"))
    reporter_id = Column(String) # WhatsApp number
    status_type = Column(Enum(StatusType))
    gate = Column(String, nullable=True)
    raw_text = Column(String)
    status = Column(Enum(ReportStatus), default=ReportStatus.PENDING)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    flight = relationship("Flight", back_populates="reports")

class FXRate(Base):
    __tablename__ = "fx_rates"
    id = Column(Integer, primary_key=True)
    pair = Column(String, unique=True) # USD_NGN, USD_GHS
    rate = Column(Float)
    updated_at = Column(DateTime, default=datetime.utcnow)

class UserSubscription(Base):
    __tablename__ = "subscriptions"
    id = Column(Integer, primary_key=True)
    user_id = Column(String) # WhatsApp number
    route_id = Column(Integer, ForeignKey("routes.id"), nullable=True)
    flight_id = Column(Integer, ForeignKey("flights.id"), nullable=True)
    target_price = Column(Float, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class AlertHistory(Base):
    """Record of every push we actually sent (fare drops + status pushes)."""
    __tablename__ = "alert_history"
    id = Column(Integer, primary_key=True)
    user_id = Column(String, index=True)          # WhatsApp number pushed to
    alert_type = Column(String)                    # 'fare_drop' | 'status_confirmed'
    route_id = Column(Integer, ForeignKey("routes.id"), nullable=True)
    flight_id = Column(Integer, ForeignKey("flights.id"), nullable=True)
    message = Column(String)
    delivered = Column(Boolean, default=False)     # notifier result
    created_at = Column(DateTime, default=datetime.utcnow)


class ReporterScore(Base):
    """Per-reporter trust tracking. Designed so a credit/'trusted reporter'
    system can be layered on later: `credits` and `trust_level` are already
    here, unused by MVP logic beyond contradiction scoring."""
    __tablename__ = "reporter_scores"
    id = Column(Integer, primary_key=True)
    reporter_id = Column(String, unique=True, index=True)  # WhatsApp number
    total_reports = Column(Integer, default=0)
    contradicted_reports = Column(Integer, default=0)
    confirmed_reports = Column(Integer, default=0)
    credits = Column(Integer, default=0)           # future reward hook
    trust_level = Column(String, default="normal") # normal|trusted|flagged
    updated_at = Column(DateTime, default=datetime.utcnow)

    @property
    def contradiction_rate(self) -> float:
        if not self.total_reports:
            return 0.0
        return (self.contradicted_reports or 0) / self.total_reports


class PushLog(Base):
    """Dedupe layer: remembers which (flight, status, gate) state was already
    pushed so a Confirmed state is broadcast exactly once."""
    __tablename__ = "push_log"
    id = Column(Integer, primary_key=True)
    flight_id = Column(Integer, ForeignKey("flights.id"), index=True)
    state_key = Column(String, index=True)  # e.g. "boarding:12"
    pushed_at = Column(DateTime, default=datetime.utcnow)
