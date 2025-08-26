-- NamFulgor Database Schema (Battery Catalog Version)
-- PostgreSQL dialect

-- 1. Enable pgvector extension (Required for vector similarity search, if used for battery descriptions)
CREATE EXTENSION IF NOT EXISTS vector;

-- 2. Table for storing battery product information
-- This table will store each unique battery model.
DROP TABLE IF EXISTS products CASCADE; -- Drop old 'products' table if it exists
DROP TABLE IF EXISTS batteries CASCADE; -- Drop 'batteries' table if re-running script
CREATE TABLE batteries (
    -- Primary Key: A unique identifier for a battery model.
    -- e.g., "Fulgor_NS40-670" or "Optima_D34M-AZUL"
    id VARCHAR(255) PRIMARY KEY,

    brand VARCHAR(128) NOT NULL,         -- Battery Brand (e.g., Fulgor, Optima, Mac)
    model_code VARCHAR(100) NOT NULL,    -- Specific model code of the battery (e.g., NS40-670, D34M-AZUL)
    item_name TEXT,                      -- Optional: Full descriptive name if different from brand+model
    
    description TEXT,                    -- Additional details or features of the battery
    
    warranty_months INTEGER,             -- Warranty in months for the battery
    
    -- Financials
    price_regular NUMERIC(12, 2) NOT NULL, -- Regular retail price
    price_discount_fx NUMERIC(12, 2),    -- Special discounted price for FX payment
    
    -- Stock information for this battery model (overall, not per-warehouse unless specified)
    stock INTEGER DEFAULT 0 NOT NULL,
    
    -- Embedding related fields (OPTIONAL: if you want to semantically search battery descriptions/names)
    -- searchable_text_content TEXT,        -- The actual text string used to generate the embedding
    -- embedding vector(1536),              -- Vector embedding (dimension from config.EMBEDDING_DIMENSION)
    
    additional_data JSONB,               -- Stores pre-formatted message templates or other battery-specific JSON data
    
    -- Timestamps
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP NOT NULL
);

-- 3. Indexes for common filters on the batteries table
CREATE INDEX IF NOT EXISTS idx_batteries_brand ON batteries (brand);
CREATE INDEX IF NOT EXISTS idx_batteries_model_code ON batteries (model_code);
-- Optional: If you implement semantic search for battery descriptions
-- CREATE INDEX IF NOT EXISTS idx_batteries_embedding_hnsw ON batteries USING hnsw (embedding vector_cosine_ops);


-- 4. Table for storing vehicle fitment information
DROP TABLE IF EXISTS vehicle_battery_fitment CASCADE;
CREATE TABLE vehicle_battery_fitment (
    fitment_id SERIAL PRIMARY KEY,         -- Auto-incrementing ID for each unique vehicle specification
    vehicle_make VARCHAR(100) NOT NULL,
    vehicle_model VARCHAR(100) NOT NULL,
    year_start INTEGER,
    year_end INTEGER,
    engine_details TEXT,                   -- e.g., "2.5L L4", "1.5L Turbo"
    notes TEXT                             -- Any specific notes for this fitment
);

-- 5. Indexes for vehicle_battery_fitment table
CREATE INDEX IF NOT EXISTS idx_vbf_make_model_year ON vehicle_battery_fitment (vehicle_make, vehicle_model, year_start, year_end);
CREATE INDEX IF NOT EXISTS idx_vbf_make ON vehicle_battery_fitment (vehicle_make);
CREATE INDEX IF NOT EXISTS idx_vbf_model ON vehicle_battery_fitment (vehicle_model);


-- 6. Junction Table for Many-to-Many relationship: Batteries <-> Vehicle Fitments
DROP TABLE IF EXISTS battery_vehicle_fitments CASCADE;
CREATE TABLE battery_vehicle_fitments (
    battery_product_id_fk VARCHAR(255) REFERENCES batteries(id) ON DELETE CASCADE,
    fitment_id_fk INTEGER REFERENCES vehicle_battery_fitment(fitment_id) ON DELETE CASCADE,
    PRIMARY KEY (battery_product_id_fk, fitment_id_fk)
);


-- 7. Table for storing human takeover pause state per Support Board conversation
CREATE TABLE IF NOT EXISTS conversation_pauses (
    conversation_id VARCHAR(255) PRIMARY KEY,
    paused_until TIMESTAMP WITH TIME ZONE NOT NULL
);


-- 8. Thread Mappings Table
-- Maps a conversation ID to a provider-specific thread ID (e.g., OpenAI)
CREATE TABLE IF NOT EXISTS thread_mappings (
    id SERIAL PRIMARY KEY,
    sb_conversation_id VARCHAR(255) NOT NULL,
    provider VARCHAR(50) NOT NULL,
    thread_id VARCHAR(255) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_sb_conversation_provider UNIQUE (sb_conversation_id, provider)
);

CREATE INDEX IF NOT EXISTS idx_thread_mappings_sb_conversation_id ON thread_mappings (sb_conversation_id);
CREATE INDEX IF NOT EXISTS idx_thread_mappings_thread_id ON thread_mappings (thread_id);


-- 9. Financing Rules Table (NEW)
-- Stores business rules for financing providers like Cashea.
CREATE TABLE IF NOT EXISTS financing_rules (
    id SERIAL PRIMARY KEY,
    provider VARCHAR(50) NOT NULL,
    level_name VARCHAR(50) NOT NULL,
    initial_payment_percentage NUMERIC(5, 4) NOT NULL,
    installments INTEGER NOT NULL,
    provider_discount_percentage NUMERIC(5, 4),
    CONSTRAINT uq_provider_level UNIQUE (provider, level_name)
);

CREATE INDEX IF NOT EXISTS idx_financing_rules_provider ON financing_rules (provider);


-- 10. Function to automatically update 'updated_at' timestamp
-- This function can be reused for multiple tables.
CREATE OR REPLACE FUNCTION trigger_set_timestamp()
RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at = NOW();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Apply the trigger to the 'batteries' table
DROP TRIGGER IF EXISTS set_batteries_timestamp ON batteries; -- Drop if exists from a previous run
CREATE TRIGGER set_batteries_timestamp
BEFORE UPDATE ON batteries
FOR EACH ROW
EXECUTE FUNCTION trigger_set_timestamp();

-- (Optional) Apply the trigger to 'vehicle_battery_fitment' if you want to track its updates
-- DROP TRIGGER IF EXISTS set_vbf_timestamp ON vehicle_battery_fitment;
-- CREATE TRIGGER set_vbf_timestamp
-- BEFORE UPDATE ON vehicle_battery_fitment
-- FOR EACH ROW
-- EXECUTE FUNCTION trigger_set_timestamp();


-- 11. Comments
COMMENT ON TABLE batteries IS 'Stores battery product information, including specifications, pricing, and links to vehicle fitments.';
COMMENT ON COLUMN batteries.id IS 'Unique identifier for a battery model, e.g., "Fulgor_NS40-670".';
COMMENT ON COLUMN batteries.additional_data IS 'JSONB field for storing message templates or other structured battery-specific data.';
COMMENT ON TABLE vehicle_battery_fitment IS 'Defines specific vehicle configurations (make, model, year range, engine) for battery fitment.';
COMMENT ON TABLE battery_vehicle_fitments IS 'Junction table linking battery products to the vehicle configurations they fit.';
COMMENT ON TABLE thread_mappings IS 'Maps a Support Board conversation ID to a provider-specific thread ID (e.g., an OpenAI Assistant thread_id).';
COMMENT ON COLUMN thread_mappings.provider IS 'e.g., ''openai_assistant'', ''azure_assistant''';
COMMENT ON TABLE financing_rules IS 'Stores business rules for financing providers like Cashea.';


-- 12. Permissions (Adjust 'namfulgor_user' to your actual database user for this application)
-- DO THIS MANUALLY IN YOUR DB or ensure your Docker setup handles permissions.
-- Example:
-- GRANT ALL PRIVILEGES ON TABLE batteries TO namfulgor_user;
-- GRANT ALL PRIVILEGES ON TABLE vehicle_battery_fitment TO namfulgor_user;
-- GRANT ALL PRIVILEGES ON TABLE battery_vehicle_fitments TO namfulgor_user;
-- GRANT ALL PRIVILEGES ON TABLE conversation_pauses TO namfulgor_user;
-- GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO namfulgor_user; -- For SERIAL PKs like fitment_id

-- End of schema definition