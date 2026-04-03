"""
Cronoi LS — SQLAlchemy ORM Models (async)
"""
from __future__ import annotations
from datetime import datetime
from typing import Optional, List
from uuid import uuid4

from sqlalchemy import (
    Boolean, Column, DateTime, Float, ForeignKey,
    Integer, String, Text, func, Enum as PgEnum
)
from sqlalchemy.dialects.postgresql import UUID, JSONB, ARRAY
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


def _uuid():
    return str(uuid4())


class Company(Base):
    __tablename__ = "companies"
    id              = Column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    name            = Column(String(200), nullable=False)
    slug            = Column(String(100), unique=True, nullable=False)
    plan            = Column(String(20), nullable=False, default="free")
    monthly_quota   = Column(Integer, nullable=False, default=5)
    used_quota      = Column(Integer, nullable=False, default=0)
    settings        = Column(JSONB, nullable=False, default=dict)
    created_at      = Column(DateTime(timezone=True), server_default=func.now())
    updated_at      = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    users           = relationship("User", back_populates="company")
    shipments       = relationship("Shipment", back_populates="company")
    catalog_products = relationship("ProductCatalog", back_populates="company")
    vehicle_defs    = relationship("VehicleDefinition", back_populates="company")
    pallet_defs     = relationship("PalletDefinition", back_populates="company")
    constraint_defs = relationship("ConstraintDefinition", back_populates="company")


class User(Base):
    __tablename__ = "users"
    id              = Column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    company_id      = Column(UUID(as_uuid=False), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    email           = Column(String(200), unique=True, nullable=False)
    password_hash   = Column(String(200), nullable=False)
    full_name       = Column(String(200), nullable=False)
    role            = Column(String(20), nullable=False, default="operator")
    is_active       = Column(Boolean, nullable=False, default=True)
    last_login_at   = Column(DateTime(timezone=True))
    created_at      = Column(DateTime(timezone=True), server_default=func.now())

    company         = relationship("Company", back_populates="users")


class Shipment(Base):
    __tablename__ = "shipments"
    id                      = Column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    company_id              = Column(UUID(as_uuid=False), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    created_by              = Column(UUID(as_uuid=False), ForeignKey("users.id"), nullable=False)
    reference_no            = Column(String(50), nullable=False)
    status                  = Column(String(30), nullable=False, default="draft")
    pallet_type             = Column(String(20), nullable=False, default="P1")
    destination             = Column(Text)
    notes                   = Column(Text)
    optimizer_version       = Column(String(50))
    optimization_duration_ms = Column(Integer)
    created_at              = Column(DateTime(timezone=True), server_default=func.now())
    updated_at              = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    optimized_at            = Column(DateTime(timezone=True))
    loaded_at               = Column(DateTime(timezone=True))
    delivered_at            = Column(DateTime(timezone=True))
    deleted_at              = Column(DateTime(timezone=True))

    company     = relationship("Company", back_populates="shipments")
    products    = relationship("ShipmentProduct", back_populates="shipment", cascade="all, delete-orphan")
    pallets     = relationship("Pallet", back_populates="shipment", cascade="all, delete-orphan")
    scenarios   = relationship("Scenario", back_populates="shipment", cascade="all, delete-orphan")
    loading_plans = relationship("LoadingPlan", back_populates="shipment", cascade="all, delete-orphan")
    order_links = relationship("OrderShipment", backref="shipment", cascade="all, delete-orphan")


class ShipmentProduct(Base):
    __tablename__ = "shipment_products"
    id              = Column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    shipment_id     = Column(UUID(as_uuid=False), ForeignKey("shipments.id", ondelete="CASCADE"), nullable=False)
    catalog_id      = Column(UUID(as_uuid=False), ForeignKey("product_catalog.id", ondelete="SET NULL"))
    name            = Column(String(200), nullable=False)
    quantity        = Column(Integer, nullable=False)
    length_cm       = Column(Float, nullable=False)
    width_cm        = Column(Float, nullable=False)
    height_cm       = Column(Float, nullable=False)
    weight_kg       = Column(Float, nullable=False)
    # Full constraint assignments stored as JSONB: [{code, param_values}]
    constraints     = Column(JSONB, nullable=False, default=list)
    sort_order      = Column(Integer, nullable=False, default=0)
    created_at      = Column(DateTime(timezone=True), server_default=func.now())

    shipment        = relationship("Shipment", back_populates="products")


class Pallet(Base):
    __tablename__ = "pallets"
    id              = Column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    shipment_id     = Column(UUID(as_uuid=False), ForeignKey("shipments.id", ondelete="CASCADE"), nullable=False)
    pallet_number   = Column(Integer, nullable=False)
    pallet_type     = Column(String(20), nullable=False)
    total_weight_kg = Column(Float, nullable=False)
    total_height_cm = Column(Float, nullable=False)
    total_volume_m3 = Column(Float, nullable=False)
    fill_rate_pct   = Column(Float, nullable=False)
    constraints     = Column(JSONB, nullable=False, default=list)   # [code, ...]
    layout_data     = Column(JSONB)                                  # 3D pozisyon verisi
    created_at      = Column(DateTime(timezone=True), server_default=func.now())

    shipment        = relationship("Shipment", back_populates="pallets")
    products        = relationship("PalletProduct", back_populates="pallet", cascade="all, delete-orphan")


class PalletProduct(Base):
    __tablename__ = "pallet_products"
    id              = Column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    pallet_id       = Column(UUID(as_uuid=False), ForeignKey("pallets.id", ondelete="CASCADE"), nullable=False)
    name            = Column(String(200), nullable=False)
    quantity        = Column(Integer, nullable=False)
    length_cm       = Column(Float, nullable=False)
    width_cm        = Column(Float, nullable=False)
    height_cm       = Column(Float, nullable=False)
    weight_kg       = Column(Float, nullable=False)
    constraints     = Column(JSONB, nullable=False, default=list)
    position_x      = Column(Float)
    position_y      = Column(Float)
    position_z      = Column(Float)
    created_at      = Column(DateTime(timezone=True), server_default=func.now())

    pallet          = relationship("Pallet", back_populates="products")


class Scenario(Base):
    __tablename__ = "scenarios"
    id                  = Column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    shipment_id         = Column(UUID(as_uuid=False), ForeignKey("shipments.id", ondelete="CASCADE"), nullable=False)
    name                = Column(String(100), nullable=False)
    strategy            = Column(String(50), nullable=False)
    total_cost          = Column(Float, nullable=False)
    cost_per_pallet     = Column(Float, nullable=False)
    total_vehicles      = Column(Integer, nullable=False)
    avg_fill_rate_pct   = Column(Float, nullable=False)
    is_selected         = Column(Boolean, nullable=False, default=False)
    is_recommended      = Column(Boolean, nullable=False, default=False)
    vehicle_assignments = Column(JSONB, nullable=False, default=list)
    created_at          = Column(DateTime(timezone=True), server_default=func.now())

    shipment            = relationship("Shipment", back_populates="scenarios")


class LoadingPlan(Base):
    __tablename__ = "loading_plans"
    id                  = Column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    shipment_id         = Column(UUID(as_uuid=False), ForeignKey("shipments.id", ondelete="CASCADE"), nullable=False)
    scenario_id         = Column(UUID(as_uuid=False), ForeignKey("scenarios.id", ondelete="SET NULL"))
    is_balanced         = Column(Boolean, nullable=False, default=False)
    front_rear_diff_pct = Column(Float)
    left_right_diff_pct = Column(Float)
    total_pallets       = Column(Integer, nullable=False)
    total_weight_kg     = Column(Float, nullable=False)
    qr_token            = Column(String(64), unique=True)
    created_at          = Column(DateTime(timezone=True), server_default=func.now())
    items               = Column(JSONB, nullable=False, default=list)  # [{pallet_id, load_order, position, is_loaded}]

    shipment            = relationship("Shipment", back_populates="loading_plans")


class ProductCatalog(Base):
    __tablename__ = "product_catalog"
    id              = Column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    company_id      = Column(UUID(as_uuid=False), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    sku             = Column(String(100))
    name            = Column(String(200), nullable=False)
    length_cm       = Column(Float, nullable=False)
    width_cm        = Column(Float, nullable=False)
    height_cm       = Column(Float, nullable=False)
    weight_kg       = Column(Float, nullable=False)
    constraints     = Column(JSONB, nullable=False, default=list)
    category        = Column(String(100))
    is_active       = Column(Boolean, nullable=False, default=True)
    use_count       = Column(Integer, nullable=False, default=0)
    created_at      = Column(DateTime(timezone=True), server_default=func.now())

    company         = relationship("Company", back_populates="catalog_products")


class VehicleDefinition(Base):
    __tablename__ = "vehicle_definitions"
    id              = Column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    company_id      = Column(UUID(as_uuid=False), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    code            = Column(String(30), nullable=False)          # programatic key: panelvan, kamyon, tir...
    name            = Column(String(100), nullable=False)
    type            = Column(String(30), nullable=False)
    icon            = Column(String(10), default="🚛")
    length_cm       = Column(Float, nullable=False)
    width_cm        = Column(Float, nullable=False)
    height_cm       = Column(Float, nullable=False)
    max_weight_kg   = Column(Float, nullable=False)
    usable_volume_m3= Column(Float, nullable=True)
    pallet_capacity = Column(Integer, nullable=False, default=0)
    base_cost       = Column(Float, nullable=False, default=0)
    fuel_per_km     = Column(Float, nullable=False, default=0)
    driver_per_hour = Column(Float, nullable=False, default=0)
    opportunity_cost = Column(Float, nullable=False, default=0)
    is_system_default = Column(Boolean, nullable=False, default=False)
    is_active       = Column(Boolean, nullable=False, default=True)
    sort_order      = Column(Integer, nullable=False, default=0)
    notes           = Column(Text)
    created_at      = Column(DateTime(timezone=True), server_default=func.now())
    updated_at      = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    company         = relationship("Company", back_populates="vehicle_defs")


class PalletDefinition(Base):
    __tablename__ = "pallet_definitions"
    id              = Column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    company_id      = Column(UUID(as_uuid=False), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    code            = Column(String(30), nullable=False)          # euro, standard, half_euro...
    name            = Column(String(100), nullable=False)
    icon            = Column(String(10), default="📦")
    length_cm       = Column(Float, nullable=False)
    width_cm        = Column(Float, nullable=False)
    max_height_cm   = Column(Float, nullable=False, default=180)
    max_weight_kg   = Column(Float, nullable=False)
    usable_area_m2  = Column(Float)                              # auto: (l*w)/10000
    tare_weight_kg  = Column(Float, nullable=False, default=25)  # palet kendi ağırlığı
    is_system_default = Column(Boolean, nullable=False, default=False)
    is_active       = Column(Boolean, nullable=False, default=True)
    sort_order      = Column(Integer, nullable=False, default=0)
    notes           = Column(Text)
    created_at      = Column(DateTime(timezone=True), server_default=func.now())
    updated_at      = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    company         = relationship("Company", back_populates="pallet_defs")


class ConstraintDefinition(Base):
    __tablename__ = "constraint_definitions"
    id              = Column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    company_id      = Column(UUID(as_uuid=False), ForeignKey("companies.id", ondelete="CASCADE"))  # NULL = system
    code            = Column(String(50), nullable=False)
    name            = Column(String(100), nullable=False)
    name_en         = Column(String(100))
    description     = Column(Text)
    category        = Column(String(30), nullable=False)
    scope           = Column(String(20), nullable=False, default="pallet")
    icon_key        = Column(String(20), nullable=False, default="alert")
    color_hex       = Column(String(10), nullable=False, default="#667eea")
    is_system_default = Column(Boolean, nullable=False, default=False)
    is_active       = Column(Boolean, nullable=False, default=True)
    optimizer_rules = Column(JSONB, nullable=False, default=dict)
    sort_order      = Column(Integer, nullable=False, default=100)
    use_count       = Column(Integer, nullable=False, default=0)
    created_at      = Column(DateTime(timezone=True), server_default=func.now())
    updated_at      = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    company         = relationship("Company", back_populates="constraint_defs")


class Order(Base):
    __tablename__ = "orders"
    id                   = Column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    company_id           = Column(UUID(as_uuid=False), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    created_by           = Column(UUID(as_uuid=False), ForeignKey("users.id"), nullable=False)
    order_no             = Column(String(50), nullable=False)
    project_code         = Column(String(50))
    customer_name        = Column(String(200), nullable=False)
    address              = Column(Text)
    city                 = Column(String(100))
    postal_code          = Column(String(20))
    country              = Column(String(100), default="TR")
    contact_name         = Column(String(200))
    contact_phone        = Column(String(50))
    contact_email        = Column(String(200))
    order_date           = Column(String(20))
    requested_ship_date  = Column(String(20))
    deadline_date        = Column(String(20))
    status               = Column(String(30), nullable=False, default="pending")
    notes                = Column(Text)
    priority             = Column(Integer, nullable=False, default=3)
    created_at           = Column(DateTime(timezone=True), server_default=func.now())
    updated_at           = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    deleted_at           = Column(DateTime(timezone=True))

    items = relationship("OrderItem", back_populates="order", cascade="all, delete-orphan")
    shipment_links = relationship("OrderShipment", backref="order", cascade="all, delete-orphan")


class OrderItem(Base):
    __tablename__ = "order_items"
    id          = Column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    order_id    = Column(UUID(as_uuid=False), ForeignKey("orders.id", ondelete="CASCADE"), nullable=False)
    catalog_id  = Column(UUID(as_uuid=False), ForeignKey("product_catalog.id", ondelete="SET NULL"))
    name        = Column(String(200), nullable=False)
    sku         = Column(String(100))
    quantity    = Column(Integer, nullable=False)
    length_cm   = Column(Float, nullable=False)
    width_cm    = Column(Float, nullable=False)
    height_cm   = Column(Float, nullable=False)
    weight_kg   = Column(Float, nullable=False)
    constraints = Column(JSONB, nullable=False, default=list)
    sort_order  = Column(Integer, nullable=False, default=0)
    created_at  = Column(DateTime(timezone=True), server_default=func.now())

    order = relationship("Order", back_populates="items")


class OrderShipment(Base):
    __tablename__ = "order_shipments"
    order_id    = Column(UUID(as_uuid=False), ForeignKey("orders.id",    ondelete="CASCADE"), primary_key=True)
    shipment_id = Column(UUID(as_uuid=False), ForeignKey("shipments.id", ondelete="CASCADE"), primary_key=True)
    added_at    = Column(DateTime(timezone=True), server_default=func.now())
