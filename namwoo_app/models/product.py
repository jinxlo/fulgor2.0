# namwoo_app/models/product.py
import logging
import re
from sqlalchemy import (
    Column, String, Text, TIMESTAMP, func, Integer, NUMERIC,
    ForeignKey, Table, Index
)
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import JSONB

# Assuming 'Base' is your declarative base from a central 'database.py' or similar
# If using Flask-SQLAlchemy, this would be `from . import db` and Base would be `db.Model`
from . import Base 

logger = logging.getLogger(__name__)

# --- CORRECTED JUNCTION TABLE DEFINITION ---
# This table acts as the bridge between batteries and vehicles.
# Its name MUST exactly match the table name in your database schema.
battery_vehicle_fitments_junction_table = Table(
    'battery_vehicle_fitments', 
    Base.metadata,
    Column('battery_product_id_fk', String(255), ForeignKey('batteries.id', ondelete='CASCADE'), primary_key=True), 
    Column('fitment_id_fk', Integer, ForeignKey('vehicle_battery_fitment.fitment_id', ondelete='CASCADE'), primary_key=True)
)

# --- CORRECTED VEHICLE FITMENT MODEL ---
# This class defines a specific vehicle configuration (Make, Model, Years).
class VehicleBatteryFitment(Base):
    # --- FIX #1: The __tablename__ now points to the correct table that holds vehicle data. ---
    __tablename__ = 'vehicle_battery_fitment' 

    # --- FIX #2: Column definitions now exactly match your database schema from the `\d` command. ---
    fitment_id = Column(Integer, primary_key=True, autoincrement=True)
    vehicle_make = Column(String(100), nullable=False)
    vehicle_model = Column(String(100), nullable=False)
    year_start = Column(Integer)
    year_end = Column(Integer)
    engine_details = Column(Text, nullable=True)
    notes = Column(Text, nullable=True)
    keywords = Column(Text, nullable=True) # Added to match your schema

    # This relationship correctly uses the junction table to find all compatible batteries.
    compatible_battery_products = relationship(
        "Product", 
        secondary=battery_vehicle_fitments_junction_table,
        back_populates="fits_vehicles"
    )

    # Adding __table_args__ to explicitly create the indexes you have in your DB.
    # This is good practice for consistency between your code and schema.
    __table_args__ = (
        Index('idx_vbf_make', 'vehicle_make'),
        Index('idx_vbf_model', 'vehicle_model'),
        Index('idx_vbf_make_model_year', 'vehicle_make', 'vehicle_model', 'year_start', 'year_end'),
    )

    def __repr__(self):
        return (f"<VehicleBatteryFitment(fitment_id={self.fitment_id}, make='{self.vehicle_make}', "
                f"model='{self.vehicle_model}', years='{self.year_start}-{self.year_end}')>")

# --- BATTERY PRODUCT MODEL (Largely Unchanged) ---
# This class defines a battery product.
class Product(Base): 
    __tablename__ = 'batteries' 

    id = Column(String(255), primary_key=True, index=True)
    brand = Column(String(128), nullable=False, index=True)
    model_code = Column(String(100), nullable=False)
    item_name = Column(Text, nullable=True)
    description = Column(Text, nullable=True)
    warranty_months = Column(Integer, nullable=True)
    price_regular = Column(NUMERIC(12, 2), nullable=False)
    price_discount_fx = Column(NUMERIC(12, 2), nullable=True)
    stock = Column(Integer, default=0, nullable=False)
    additional_data = Column(JSONB, nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    # This relationship correctly uses the junction table to find all vehicles this battery fits.
    fits_vehicles = relationship(
        "VehicleBatteryFitment",
        secondary=battery_vehicle_fitments_junction_table,
        back_populates="compatible_battery_products"
    )

    def __repr__(self):
        return (f"<Product(Battery)(id='{self.id}', brand='{self.brand}', model='{self.model_code}', "
                f"price_regular='{self.price_regular}')>")

    def to_dict(self):
        """Returns a dictionary representation of the battery product."""
        return {
            "id": self.id,
            "brand": self.brand,
            "model_code": self.model_code,
            "item_name": self.item_name,
            "description": self.description,
            "warranty_months": self.warranty_months,
            "price_regular": float(self.price_regular) if self.price_regular is not None else None,
            "price_discount_fx": float(self.price_discount_fx) if self.price_discount_fx is not None else None,
            "stock": self.stock,
            "additional_data": self.additional_data,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    def format_for_llm(self):
        """Formats battery information for presentation by an LLM."""
        if self.additional_data and isinstance(self.additional_data, dict):
            template = self.additional_data.get("message_template")
            if template and isinstance(template, str):
                message = template
                message = message.replace("{BRAND}", self.brand or "N/A")
                message = message.replace("{MODEL_CODE}", self.model_code or "N/A")
                message = message.replace("{WARRANTY_MONTHS}", str(self.warranty_months or "N/A"))
                message = message.replace("{PRICE_REGULAR}", f"${float(self.price_regular):.2f}" if self.price_regular is not None else "N/A")
                message = message.replace("{PRICE_DISCOUNT_FX}", f"${float(self.price_discount_fx):.2f}" if self.price_discount_fx is not None else "N/A")
                message = message.replace("{STOCK}", str(self.stock if self.stock is not None else "N/A"))
                return message

        price_reg_str = f"Precio Regular: ${float(self.price_regular):.2f}" if self.price_regular is not None else "Precio Regular no disponible"
        price_fx_str = f"Descuento Pago en Divisas: ${float(self.price_discount_fx):.2f}" if self.price_discount_fx is not None else ""
        warranty_str = f"Garantía: {self.warranty_months} meses" if self.warranty_months is not None else "Garantía no especificada"
        stock_str = f"Stock: {self.stock}" if self.stock is not None else "Stock no disponible"
        name_str = self.item_name or f"{self.brand} {self.model_code}"

        # Consolidate the message to be cleaner and avoid extra newlines for empty fields
        parts = [
            f"Batería: {name_str}.",
            f"Marca: {self.brand}.",
            f"Modelo: {self.model_code}.",
            warranty_str,
            price_reg_str,
        ]
        if price_fx_str:
            parts.append(price_fx_str)
        
        parts.extend([
            stock_str,
            "Debe entregar la chatarra.",
            "⚠️ Para que su descuento sea válido, debe presentar este mensaje en la tienda."
        ])
        
        return "\n".join(parts)