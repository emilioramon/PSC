-- Tabla de Lambdas
CREATE TABLE IF NOT EXISTS lambdas (
    id_lambda UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    id_owner VARCHAR(255) NOT NULL,
    descripcion TEXT,
    codigo_path VARCHAR(500) NOT NULL,
    file_size BIGINT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_lambdas_owner ON lambdas(id_owner);
CREATE INDEX idx_lambdas_created ON lambdas(created_at DESC);

-- Tabla de Encargos
CREATE TABLE IF NOT EXISTS encargos (
    id_encargo UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    id_lambda UUID NOT NULL REFERENCES lambdas(id_lambda) ON DELETE CASCADE,
    datos_entrada_path VARCHAR(500),
    resultado_path VARCHAR(500),
    status VARCHAR(50) DEFAULT 'pending',
    exit_code INTEGER,
    stdout TEXT,
    stderr TEXT,
    execution_time_ms INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP
);

CREATE INDEX idx_encargos_lambda ON encargos(id_lambda);
CREATE INDEX idx_encargos_status ON encargos(status);
CREATE INDEX idx_encargos_created ON encargos(created_at DESC);

-- Trigger para actualizar updated_at
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ language 'plpgsql';

CREATE TRIGGER update_lambdas_updated_at BEFORE UPDATE ON lambdas
FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();